"""Ingest odds from The Odds API into the database.

Separated from the HTTP client so the client stays testable and reusable.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from ..extensions import db
from ..models import Game, OddsSnapshot, Sport, Sportsbook
from .odds_api import OddsAPIClient, parse_commence_time

logger = logging.getLogger(__name__)


def ensure_sport(key: str, display_name: str) -> Sport:
    sport = db.session.query(Sport).filter_by(key=key).one_or_none()
    if sport is None:
        sport = Sport(key=key, display_name=display_name)
        db.session.add(sport)
        db.session.flush()
    return sport


def ensure_sportsbook(key: str, display_name: str) -> Sportsbook:
    book = db.session.query(Sportsbook).filter_by(key=key).one_or_none()
    if book is None:
        book = Sportsbook(key=key, display_name=display_name)
        db.session.add(book)
        db.session.flush()
    return book


def upsert_game(sport: Sport, event: dict[str, Any]) -> Game:
    external_id = event["id"]
    game = db.session.query(Game).filter_by(external_id=external_id).one_or_none()
    commence_time = parse_commence_time(event["commence_time"])
    if game is None:
        game = Game(
            sport_id=sport.id,
            external_id=external_id,
            home_team=event["home_team"],
            away_team=event["away_team"],
            commence_time=commence_time,
        )
        db.session.add(game)
        db.session.flush()
    else:
        # Teams/time can shift slightly pre-game; keep them fresh.
        game.home_team = event["home_team"]
        game.away_team = event["away_team"]
        game.commence_time = commence_time
    return game


def _extract_market_odds(
    market: dict[str, Any], home_team: str, away_team: str
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Return (home_odds, away_odds, spread_or_total) for one market."""
    outcomes = {o["name"]: o for o in market.get("outcomes", [])}
    key = market["key"]
    if key == "h2h":
        home = outcomes.get(home_team)
        away = outcomes.get(away_team)
        return (
            Decimal(str(home["price"])) if home else None,
            Decimal(str(away["price"])) if away else None,
            None,
        )
    if key == "spreads":
        home = outcomes.get(home_team)
        away = outcomes.get(away_team)
        return (
            Decimal(str(home["price"])) if home else None,
            Decimal(str(away["price"])) if away else None,
            Decimal(str(home["point"])) if home and "point" in home else None,
        )
    if key == "totals":
        # Totals have "Over"/"Under" outcomes. Store Over price as home_odds,
        # Under price as away_odds, and the line as spread_or_total.
        over = outcomes.get("Over")
        under = outcomes.get("Under")
        return (
            Decimal(str(over["price"])) if over else None,
            Decimal(str(under["price"])) if under else None,
            Decimal(str(over["point"])) if over and "point" in over else None,
        )
    return (None, None, None)


def ingest_event(event: dict[str, Any], sport: Sport, tracked_books: dict[str, str]) -> int:
    """Persist a single event's odds. Returns number of snapshots written."""
    game = upsert_game(sport, event)
    written = 0
    for book_data in event.get("bookmakers", []):
        book_key = book_data["key"]
        if book_key not in tracked_books:
            continue
        book = ensure_sportsbook(book_key, tracked_books[book_key])
        for market in book_data.get("markets", []):
            if market["key"] not in ("h2h", "spreads", "totals"):
                continue
            home_odds, away_odds, line = _extract_market_odds(
                market, event["home_team"], event["away_team"]
            )
            snapshot = OddsSnapshot(
                game_id=game.id,
                sportsbook_id=book.id,
                market_type=market["key"],
                home_odds=home_odds,
                away_odds=away_odds,
                spread_or_total=line,
            )
            db.session.add(snapshot)
            written += 1
    return written


def refresh_sport(
    client: OddsAPIClient,
    sport_key: str,
    sport_display: str,
    tracked_books: dict[str, str],
    markets: tuple[str, ...] = ("h2h", "spreads", "totals"),
) -> dict[str, int]:
    """Fetch and persist current odds for one sport. Caller commits."""
    sport = ensure_sport(sport_key, sport_display)
    events = client.get_odds(
        sport_key,
        markets=markets,
        bookmakers=tuple(tracked_books.keys()),
    )
    snapshots = 0
    for event in events:
        snapshots += ingest_event(event, sport, tracked_books)
    logger.info(
        "ingested sport=%s events=%d snapshots=%d remaining=%s",
        sport_key, len(events), snapshots,
        client.last_quota.remaining if client.last_quota else None,
    )
    return {"events": len(events), "snapshots": snapshots}
