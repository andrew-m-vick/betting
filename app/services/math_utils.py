"""Betting math: odds conversions, EV, Kelly, arbitrage.

All inputs validated so callers get a useful error on bad data rather than
a surprising result deep in a calculation.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


class MathError(ValueError):
    """Raised for invalid inputs to the math helpers."""


def _validate_american(odds: float) -> None:
    if not isfinite(odds):
        raise MathError("odds must be finite")
    if odds == 0:
        raise MathError("American odds of 0 are invalid")
    if -100 < odds < 100:
        raise MathError("American odds must be <= -100 or >= +100")


def american_to_decimal(odds: float) -> float:
    _validate_american(odds)
    if odds >= 100:
        return 1 + odds / 100
    return 1 + 100 / abs(odds)


def american_to_implied_prob(odds: float) -> float:
    """Implied probability (0-1) from American odds, without removing the vig."""
    _validate_american(odds)
    if odds >= 100:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def _validate_prob(p: float, name: str = "probability") -> None:
    if not isfinite(p) or not 0 < p < 1:
        raise MathError(f"{name} must be in the open interval (0, 1)")


@dataclass(frozen=True)
class EVResult:
    true_prob: float            # user's estimate, 0-1
    implied_prob: float         # sportsbook's, 0-1
    decimal_odds: float
    ev_per_unit: float          # EV per $1 staked
    ev_pct: float               # EV per $1 as percentage
    kelly_fraction: float       # full Kelly, 0-1 (clamped at 0)
    quarter_kelly_fraction: float
    is_positive_ev: bool


def ev_and_kelly(american_odds: float, true_prob: float) -> EVResult:
    """Expected value and Kelly sizing given American odds and a true prob.

    true_prob is 0-1 (so 55% -> 0.55). Kelly is clamped to 0 on negative EV
    rather than returning a negative fraction (which would say "bet the
    other side" — not meaningful when the user chose a specific side).
    """
    _validate_prob(true_prob, "true_prob")
    decimal = american_to_decimal(american_odds)
    implied = american_to_implied_prob(american_odds)
    b = decimal - 1  # net profit per $1 staked on a win
    q = 1 - true_prob
    ev = true_prob * b - q  # per $1 staked
    raw_kelly = (b * true_prob - q) / b
    kelly = max(0.0, raw_kelly)
    return EVResult(
        true_prob=true_prob,
        implied_prob=implied,
        decimal_odds=decimal,
        ev_per_unit=ev,
        ev_pct=ev * 100,
        kelly_fraction=kelly,
        quarter_kelly_fraction=kelly / 4,
        is_positive_ev=ev > 0,
    )


@dataclass(frozen=True)
class ArbOpportunity:
    decimal_home: float
    decimal_away: float
    total_implied: float        # sum of 1/decimal_odds; < 1 means arb exists
    profit_pct: float           # guaranteed return on total stake, e.g. 0.023 = 2.3%
    stake_home_pct: float       # fraction of total stake to put on home
    stake_away_pct: float       # fraction of total stake to put on away


def find_two_way_arb(home_american: float, away_american: float) -> ArbOpportunity | None:
    """Return arb details if (1/d_home + 1/d_away) < 1, else None."""
    d_home = american_to_decimal(home_american)
    d_away = american_to_decimal(away_american)
    total = 1 / d_home + 1 / d_away
    if total >= 1:
        return None
    profit_pct = (1 / total) - 1
    # Optimal stake split to equalize payout regardless of outcome.
    stake_home = (1 / d_home) / total
    stake_away = (1 / d_away) / total
    return ArbOpportunity(
        decimal_home=d_home,
        decimal_away=d_away,
        total_implied=total,
        profit_pct=profit_pct,
        stake_home_pct=stake_home,
        stake_away_pct=stake_away,
    )
