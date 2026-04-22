"""Tests for the latest-snapshot query + arb finder page."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.extensions import db as _db
from app.models import Game, OddsSnapshot, Sport, Sportsbook
from app.services.queries import latest_snapshots_for_upcoming


def _seed_game_with_two_books(db, sport_key="nfl"):
    sport = Sport(key=sport_key, display_name="NFL")
    dk = Sportsbook(key="dk", display_name="DraftKings")
    fd = Sportsbook(key="fd", display_name="FanDuel")
    db.session.add_all([sport, dk, fd])
    db.session.flush()

    game = Game(
        sport_id=sport.id,
        external_id=f"evt_{sport_key}",
        home_team="Chiefs",
        away_team="Ravens",
        commence_time=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db.session.add(game)
    db.session.flush()
    return game, dk, fd


def test_latest_snapshot_picks_newest_per_book(app, db):
    with app.app_context():
        game, dk, _ = _seed_game_with_two_books(db)
        now = datetime.now(timezone.utc)
        # Older snapshot
        db.session.add(OddsSnapshot(
            game_id=game.id, sportsbook_id=dk.id, market_type="h2h",
            home_odds=Decimal("-150"), away_odds=Decimal("130"),
            captured_at=now - timedelta(hours=2),
        ))
        # Newer snapshot
        db.session.add(OddsSnapshot(
            game_id=game.id, sportsbook_id=dk.id, market_type="h2h",
            home_odds=Decimal("-145"), away_odds=Decimal("125"),
            captured_at=now - timedelta(minutes=5),
        ))
        db.session.commit()

        snapshots = latest_snapshots_for_upcoming(market_types=("h2h",))
        assert len(snapshots) == 1
        assert snapshots[0].home_odds == Decimal("-145")


def test_stale_snapshots_are_excluded(app, db):
    with app.app_context():
        game, dk, _ = _seed_game_with_two_books(db)
        old = datetime.now(timezone.utc) - timedelta(hours=48)
        db.session.add(OddsSnapshot(
            game_id=game.id, sportsbook_id=dk.id, market_type="h2h",
            home_odds=Decimal("-150"), away_odds=Decimal("130"),
            captured_at=old,
        ))
        db.session.commit()
        assert latest_snapshots_for_upcoming(market_types=("h2h",)) == []


def test_arbitrage_page_empty_state(client):
    resp = client.get("/odds/arbitrage")
    assert resp.status_code == 200
    assert b"No arbitrage opportunities" in resp.data or b"arbitrage" in resp.data.lower()


def test_live_odds_page_renders(client):
    resp = client.get("/odds/")
    assert resp.status_code == 200
    assert b"Live Odds" in resp.data


def test_tools_pages_render(client):
    for path in ("/ev-calculator", "/parlay-simulator"):
        resp = client.get(path)
        assert resp.status_code == 200, path


def test_upcoming_json_returns_list(client):
    resp = client.get("/odds/upcoming.json")
    assert resp.status_code == 200
    assert resp.is_json
    assert isinstance(resp.get_json(), list)
