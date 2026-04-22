"""Odds blueprint: Live Odds, Arbitrage Finder, upcoming-games JSON."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, jsonify, render_template, request

from ..models import Game, OddsSnapshot
from ..services.math_utils import find_two_way_arb
from ..services.queries import (
    all_snapshots_for_game,
    all_sports,
    all_sportsbooks,
    games_with_snapshot_history,
    latest_snapshots_for_upcoming,
)

odds_bp = Blueprint("odds", __name__, template_folder="../templates/odds")


# ---------- Live Odds ----------


def _parse_ids(raw: list[str]) -> list[int]:
    out: list[int] = []
    for r in raw:
        try:
            out.append(int(r))
        except (TypeError, ValueError):
            continue
    return out


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@dataclass
class GameOdds:
    """All latest snapshots for a single game, grouped by market + book."""
    game: Game
    # market_type -> list[OddsSnapshot]
    snapshots_by_market: dict[str, list[OddsSnapshot]]
    best_home_book_id: int | None
    best_away_book_id: int | None


def _group_by_game(snapshots: list[OddsSnapshot]) -> list[GameOdds]:
    by_game: dict[int, dict[str, list[OddsSnapshot]]] = defaultdict(
        lambda: defaultdict(list)
    )
    game_refs: dict[int, Game] = {}
    for s in snapshots:
        by_game[s.game_id][s.market_type].append(s)
        game_refs[s.game_id] = s.game

    results: list[GameOdds] = []
    for game_id, markets_map in by_game.items():
        game = game_refs[game_id]
        for market_snaps in markets_map.values():
            market_snaps.sort(key=lambda s: s.sportsbook.display_name)

        # Best odds highlighting uses h2h (moneyline) only.
        h2h = markets_map.get("h2h", [])
        best_home_book_id: int | None = None
        best_away_book_id: int | None = None
        if h2h:
            # Highest American odds = best payout for the bettor.
            best_home = max(
                (s for s in h2h if s.home_odds is not None),
                key=lambda s: s.home_odds,
                default=None,
            )
            best_away = max(
                (s for s in h2h if s.away_odds is not None),
                key=lambda s: s.away_odds,
                default=None,
            )
            if best_home is not None:
                best_home_book_id = best_home.sportsbook_id
            if best_away is not None:
                best_away_book_id = best_away.sportsbook_id

        results.append(
            GameOdds(
                game=game,
                snapshots_by_market=dict(markets_map),
                best_home_book_id=best_home_book_id,
                best_away_book_id=best_away_book_id,
            )
        )

    results.sort(key=lambda g: g.game.commence_time)
    return results


@odds_bp.route("/")
def live_odds():
    # Sport filter is now single-select via pill UI. Accept either a single
    # `?sport=<id>` or the legacy multi `?sport=<id>&sport=<id>`.
    raw_sport = request.args.getlist("sport")
    sport_ids = _parse_ids(raw_sport)
    book_ids = _parse_ids(request.args.getlist("book"))
    date_from = _parse_iso(request.args.get("from"))
    date_to = _parse_iso(request.args.get("to"))
    sort = request.args.get("sort", "time")
    q = (request.args.get("q") or "").strip().lower()

    # Pull ALL upcoming snapshots for counting, then filter for display.
    all_snapshots = latest_snapshots_for_upcoming(
        sportsbook_ids=book_ids or None,
        start_after=date_from,
        start_before=date_to,
    )
    # Per-sport game counts for the pill bar.
    sport_counts: dict[int, int] = defaultdict(int)
    seen_games: set[tuple[int, int]] = set()
    for s in all_snapshots:
        key = (s.game.sport_id, s.game_id)
        if key not in seen_games:
            seen_games.add(key)
            sport_counts[s.game.sport_id] += 1
    total_games = len(seen_games)

    # Filter down to selected sports + free-text query.
    def _matches_q(snap: OddsSnapshot) -> bool:
        if not q:
            return True
        g = snap.game
        haystack = f"{g.home_team} {g.away_team} {g.sport.display_name} {g.sport.key}".lower()
        return all(token in haystack for token in q.split())

    filtered = [
        s for s in all_snapshots
        if (not sport_ids or s.game.sport_id in sport_ids) and _matches_q(s)
    ]
    grouped = _group_by_game(filtered)

    if sort == "sport":
        grouped.sort(key=lambda g: (g.game.sport.display_name, g.game.commence_time))

    return render_template(
        "odds/live.html",
        grouped=grouped,
        sports=all_sports(),
        sportsbooks=all_sportsbooks(),
        selected_sports=set(sport_ids),
        selected_books=set(book_ids),
        sport_counts=dict(sport_counts),
        total_games=total_games,
        date_from=request.args.get("from", ""),
        date_to=request.args.get("to", ""),
        sort=sort,
        q=q,
    )


# ---------- Upcoming games JSON (for EV calculator dropdown) ----------


@odds_bp.route("/upcoming.json")
def upcoming_json():
    snapshots = latest_snapshots_for_upcoming(market_types=("h2h",))
    grouped = _group_by_game(snapshots)
    payload = []
    for g in grouped:
        h2h = g.snapshots_by_market.get("h2h", [])
        books = []
        for s in h2h:
            books.append(
                {
                    "book": s.sportsbook.display_name,
                    "home_odds": float(s.home_odds) if s.home_odds is not None else None,
                    "away_odds": float(s.away_odds) if s.away_odds is not None else None,
                }
            )
        payload.append(
            {
                "game_id": g.game.id,
                "sport": g.game.sport.display_name,
                "home_team": g.game.home_team,
                "away_team": g.game.away_team,
                "commence_time": g.game.commence_time.isoformat(),
                "books": books,
            }
        )
    return jsonify(payload)


# ---------- Search autocomplete ----------


@odds_bp.route("/search.json")
def search_json():
    """Fuzzy-ish text search across upcoming games by team, sport, or game name.

    Returns up to 12 matches for the header autocomplete dropdown.
    """
    q = (request.args.get("q") or "").strip().lower()
    if not q or len(q) < 2:
        return jsonify([])
    tokens = q.split()
    snapshots = latest_snapshots_for_upcoming(market_types=("h2h",))
    seen: set[int] = set()
    matches: list[dict] = []
    for s in snapshots:
        if s.game_id in seen:
            continue
        g = s.game
        haystack = f"{g.home_team} {g.away_team} {g.sport.display_name} {g.sport.key}".lower()
        if not all(t in haystack for t in tokens):
            continue
        seen.add(g.id)
        matches.append({
            "game_id": g.id,
            "sport": g.sport.display_name,
            "sport_key": g.sport.key,
            "home_team": g.home_team,
            "away_team": g.away_team,
            "commence_time": g.commence_time.isoformat(),
        })
        if len(matches) >= 12:
            break
    return jsonify(matches)


# ---------- Arbitrage Finder ----------


@dataclass
class ArbRow:
    game: Game
    home_book: str
    away_book: str
    home_odds: Decimal
    away_odds: Decimal
    profit_pct: float
    stake_home_pct: float
    stake_away_pct: float
    stake_home_dollars: float
    stake_away_dollars: float
    guaranteed_return: float


def _best_arb_for_game(h2h_snapshots: list[OddsSnapshot], stake: float) -> ArbRow | None:
    """Find the (home_book, away_book) pair maximizing arb profit for a game."""
    best: ArbRow | None = None
    for home_snap in h2h_snapshots:
        if home_snap.home_odds is None:
            continue
        for away_snap in h2h_snapshots:
            if away_snap.away_odds is None:
                continue
            arb = find_two_way_arb(
                float(home_snap.home_odds), float(away_snap.away_odds)
            )
            if arb is None:
                continue
            row = ArbRow(
                game=home_snap.game,
                home_book=home_snap.sportsbook.display_name,
                away_book=away_snap.sportsbook.display_name,
                home_odds=home_snap.home_odds,
                away_odds=away_snap.away_odds,
                profit_pct=arb.profit_pct,
                stake_home_pct=arb.stake_home_pct,
                stake_away_pct=arb.stake_away_pct,
                stake_home_dollars=round(stake * arb.stake_home_pct, 2),
                stake_away_dollars=round(stake * arb.stake_away_pct, 2),
                guaranteed_return=round(stake * arb.profit_pct, 2),
            )
            if best is None or row.profit_pct > best.profit_pct:
                best = row
    return best


@odds_bp.route("/arbitrage")
def arbitrage():
    try:
        stake = float(request.args.get("stake", "100"))
        if stake <= 0:
            stake = 100.0
    except ValueError:
        stake = 100.0

    snapshots = latest_snapshots_for_upcoming(market_types=("h2h",))
    grouped = _group_by_game(snapshots)

    arbs: list[ArbRow] = []
    for g in grouped:
        h2h = g.snapshots_by_market.get("h2h", [])
        row = _best_arb_for_game(h2h, stake)
        if row is not None:
            arbs.append(row)
    arbs.sort(key=lambda r: r.profit_pct, reverse=True)

    return render_template("odds/arbitrage.html", arbs=arbs, stake=stake)


# ---------- Line Movement ----------


@odds_bp.route("/line-movement")
def line_movement():
    game_id_raw = request.args.get("game_id")
    try:
        game_id = int(game_id_raw) if game_id_raw else None
    except ValueError:
        game_id = None

    games = games_with_snapshot_history()
    selected_game: Game | None = None
    if game_id is not None:
        selected_game = next((g for g in games if g.id == game_id), None)
        if selected_game is None:
            # Fallback: maybe the game has only one snapshot (single-snapshot games
            # are filtered out of the dropdown, but respect direct links).
            from ..extensions import db as _db
            from sqlalchemy import select as _select
            selected_game = _db.session.execute(
                _select(Game).where(Game.id == game_id)
            ).scalar_one_or_none()
    elif games:
        selected_game = games[0]

    return render_template(
        "odds/line_movement.html",
        games=games,
        selected_game=selected_game,
    )


@odds_bp.route("/line-movement/<int:game_id>.json")
def line_movement_json(game_id: int):
    """Return all snapshots for a game, grouped by (market, sportsbook)."""
    snaps = all_snapshots_for_game(game_id)
    # Series key: f"{market}|{sportsbook_key}|{side}"
    series: dict[str, list[dict[str, float | str]]] = defaultdict(list)
    meta: dict[str, dict[str, str]] = {}
    for s in snaps:
        book = s.sportsbook.display_name
        ts = s.captured_at.isoformat()
        if s.market_type == "totals":
            if s.home_odds is not None:
                k = f"totals|{book}|Over"
                series[k].append({"t": ts, "v": float(s.home_odds), "line": float(s.spread_or_total) if s.spread_or_total is not None else None})
                meta[k] = {"market": "totals", "book": book, "side": "Over"}
            if s.away_odds is not None:
                k = f"totals|{book}|Under"
                series[k].append({"t": ts, "v": float(s.away_odds), "line": float(s.spread_or_total) if s.spread_or_total is not None else None})
                meta[k] = {"market": "totals", "book": book, "side": "Under"}
        else:
            if s.home_odds is not None:
                k = f"{s.market_type}|{book}|home"
                series[k].append({"t": ts, "v": float(s.home_odds), "line": float(s.spread_or_total) if s.spread_or_total is not None else None})
                meta[k] = {"market": s.market_type, "book": book, "side": "home"}
            if s.away_odds is not None:
                k = f"{s.market_type}|{book}|away"
                series[k].append({"t": ts, "v": float(s.away_odds), "line": float(s.spread_or_total) if s.spread_or_total is not None else None})
                meta[k] = {"market": s.market_type, "book": book, "side": "away"}

    return jsonify({"series": series, "meta": meta})
