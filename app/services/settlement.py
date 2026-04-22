"""Settle pending bets once their games complete.

Selection encoding (stored in `tracked_bets.selection` and `parlay_legs.selection`):

  bet_type='moneyline'  selection = 'home' | 'away'
  bet_type='spread'     selection = 'home|<line>' | 'away|<line>'   e.g. 'home|-3.5'
  bet_type='total'      selection = 'over|<line>' | 'under|<line>'  e.g. 'over|45.5'
  bet_type='parlay'     selection = human-readable label (unused for settlement)

Parlay leg encoding (parlay_legs.selection):
  '<bet_type>|<selection>'
  Example: 'moneyline|home' or 'spread|home|-3.5' or 'total|over|45.5'

Parlay push handling: a pushed leg is dropped and the parlay is recalculated
using only the remaining legs. If all legs push, the whole parlay is a push.
If any leg loses, the whole parlay loses regardless of other legs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..extensions import db
from ..models import Game, ParlayLeg, TrackedBet
from .math_utils import american_to_decimal

logger = logging.getLogger(__name__)

Outcome = Literal["won", "lost", "push"]


class SettlementError(Exception):
    """Raised when a bet cannot be settled (bad selection, etc.)."""


@dataclass(frozen=True)
class LegResult:
    outcome: Outcome
    decimal_odds: float  # only meaningful for "won" / "push" legs


def settle_moneyline(game: Game, side: str) -> Outcome:
    if game.home_score is None or game.away_score is None:
        raise SettlementError("game has no scores")
    if game.home_score == game.away_score:
        return "push"  # regulation ties; rare in US sports but possible in MLS
    winner_is_home = game.home_score > game.away_score
    if side == "home":
        return "won" if winner_is_home else "lost"
    if side == "away":
        return "lost" if winner_is_home else "won"
    raise SettlementError(f"invalid moneyline side: {side!r}")


def settle_spread(game: Game, side: str, line: float) -> Outcome:
    """A spread bet on `home` with line -3.5 wins if home_score + (-3.5) > away_score."""
    if game.home_score is None or game.away_score is None:
        raise SettlementError("game has no scores")
    if side == "home":
        adjusted = game.home_score + line
        other = game.away_score
    elif side == "away":
        adjusted = game.away_score + line
        other = game.home_score
    else:
        raise SettlementError(f"invalid spread side: {side!r}")
    if adjusted > other:
        return "won"
    if adjusted < other:
        return "lost"
    return "push"


def settle_total(game: Game, side: str, line: float) -> Outcome:
    if game.home_score is None or game.away_score is None:
        raise SettlementError("game has no scores")
    total_scored = game.home_score + game.away_score
    if total_scored > line:
        return "won" if side == "over" else "lost"
    if total_scored < line:
        return "won" if side == "under" else "lost"
    return "push"


def parse_single_selection(bet_type: str, selection: str) -> tuple[str, float | None]:
    """Return (side, line) for a non-parlay bet. Line is None for moneyline."""
    if bet_type == "moneyline":
        return selection.strip(), None
    parts = selection.split("|")
    if bet_type == "spread":
        if len(parts) != 2:
            raise SettlementError(f"bad spread selection: {selection!r}")
        return parts[0], float(parts[1])
    if bet_type == "total":
        if len(parts) != 2:
            raise SettlementError(f"bad total selection: {selection!r}")
        return parts[0], float(parts[1])
    raise SettlementError(f"unsupported bet_type: {bet_type!r}")


def settle_single_bet(bet: TrackedBet) -> Outcome:
    """Return the outcome for a non-parlay bet."""
    if bet.game is None:
        raise SettlementError("non-parlay bet is missing game")
    side, line = parse_single_selection(bet.bet_type, bet.selection)
    if bet.bet_type == "moneyline":
        return settle_moneyline(bet.game, side)
    if bet.bet_type == "spread":
        assert line is not None
        return settle_spread(bet.game, side, line)
    if bet.bet_type == "total":
        assert line is not None
        return settle_total(bet.game, side, line)
    raise SettlementError(f"unsupported bet_type: {bet.bet_type!r}")


def _leg_ready(leg: ParlayLeg) -> bool:
    g = leg.parlay_bet.legs and leg.game  # noqa: F841 — avoid lazy warning
    return leg.game is not None and leg.game.completed and leg.game.home_score is not None


def settle_parlay_leg(leg: ParlayLeg) -> LegResult:
    """Settle one parlay leg. Format: '<bet_type>|<encoded>'."""
    parts = leg.selection.split("|", 1)
    if len(parts) != 2:
        raise SettlementError(f"bad parlay leg: {leg.selection!r}")
    bet_type, rest = parts
    decimal = american_to_decimal(float(leg.odds))
    if bet_type == "moneyline":
        return LegResult(settle_moneyline(leg.game, rest), decimal)
    side_line = rest.split("|")
    if len(side_line) != 2:
        raise SettlementError(f"bad parlay leg: {leg.selection!r}")
    side, line_s = side_line
    line = float(line_s)
    if bet_type == "spread":
        return LegResult(settle_spread(leg.game, side, line), decimal)
    if bet_type == "total":
        return LegResult(settle_total(leg.game, side, line), decimal)
    raise SettlementError(f"unsupported parlay leg bet_type: {bet_type!r}")


@dataclass(frozen=True)
class ParlayResolution:
    outcome: Outcome
    decimal_odds: float  # multiplied across non-pushed legs; 1.0 if all push


def resolve_parlay(leg_results: list[LegResult]) -> ParlayResolution:
    """Apply push drop-and-recalc rules."""
    non_push = [r for r in leg_results if r.outcome != "push"]
    if not non_push:
        return ParlayResolution("push", 1.0)
    if any(r.outcome == "lost" for r in non_push):
        return ParlayResolution("lost", 1.0)
    product = 1.0
    for r in non_push:
        product *= r.decimal_odds
    return ParlayResolution("won", product)


def settle_parlay(bet: TrackedBet) -> tuple[Outcome, float]:
    """Return (outcome, decimal_odds_for_payout). Raises if any leg game isn't ready."""
    if not bet.legs:
        raise SettlementError("parlay has no legs")
    results: list[LegResult] = []
    for leg in bet.legs:
        if leg.game is None or not leg.game.completed or leg.game.home_score is None:
            raise SettlementError("parlay has leg with unfinished game")
        results.append(settle_parlay_leg(leg))
    resolution = resolve_parlay(results)
    return resolution.outcome, resolution.decimal_odds


def _compute_payout(stake: Decimal, decimal_odds: float, outcome: Outcome) -> Decimal:
    """Payout = total amount returned to bettor (stake + winnings, or stake on push, or 0 on loss)."""
    if outcome == "won":
        return (stake * Decimal(str(decimal_odds))).quantize(Decimal("0.01"))
    if outcome == "push":
        return stake
    return Decimal("0.00")


def settle_bet(bet: TrackedBet) -> bool:
    """Settle one bet in-place; returns True on success, False if not ready."""
    try:
        if bet.bet_type == "parlay":
            outcome, decimal = settle_parlay(bet)
            bet.payout = _compute_payout(bet.stake, decimal, outcome)
            # Update leg statuses for display.
            for leg in bet.legs:
                try:
                    leg.status = settle_parlay_leg(leg).outcome
                except SettlementError:
                    continue
        else:
            if bet.game is None or not bet.game.completed or bet.game.home_score is None:
                return False
            outcome = settle_single_bet(bet)
            bet.payout = _compute_payout(
                bet.stake, american_to_decimal(float(bet.odds_at_bet)), outcome
            )
        bet.status = outcome
        bet.settled_at = datetime.now(timezone.utc)
        return True
    except SettlementError as e:
        logger.warning("cannot settle bet id=%s: %s", bet.id, e)
        return False


def settle_pending_bets() -> dict[str, int]:
    """Attempt to settle all pending bets. Each bet is its own transaction
    so a single failure can't block the whole batch.

    Idempotent: already-settled bets (status != 'pending') are skipped.
    """
    pending = db.session.execute(
        select(TrackedBet)
        .where(TrackedBet.status == "pending")
        .options(
            selectinload(TrackedBet.legs).selectinload(ParlayLeg.game),
        )
    ).scalars().all()

    settled = skipped = errored = 0
    for bet in pending:
        try:
            if settle_bet(bet):
                db.session.commit()
                settled += 1
                logger.info("settled bet id=%s status=%s payout=%s", bet.id, bet.status, bet.payout)
            else:
                db.session.rollback()
                skipped += 1
        except Exception:
            db.session.rollback()
            errored += 1
            logger.exception("error settling bet id=%s", bet.id)
    return {"settled": settled, "skipped_not_ready": skipped, "errored": errored}
