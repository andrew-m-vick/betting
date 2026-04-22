"""End-to-end: simulate an Odds API response, ingest it, render the page.

This test does NOT hit the real Odds API — it mocks the HTTP response
so CI doesn't consume quota. The pipeline it exercises is:
  mocked API payload -> ingest_event -> OddsSnapshot rows -> rendered HTML.
"""
from __future__ import annotations

from unittest.mock import patch

from app.models import Game, OddsSnapshot, Sport, Sportsbook
from app.services.ingest import refresh_sport
from app.services.odds_api import OddsAPIClient

SAMPLE_NFL_RESPONSE = [
    {
        "id": "evt_abc123",
        "sport_key": "americanfootball_nfl",
        "commence_time": "2099-09-08T00:20:00Z",
        "home_team": "Kansas City Chiefs",
        "away_team": "Baltimore Ravens",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Kansas City Chiefs", "price": -150},
                            {"name": "Baltimore Ravens", "price": 130},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Kansas City Chiefs", "price": -110, "point": -3.5},
                            {"name": "Baltimore Ravens", "price": -110, "point": 3.5},
                        ],
                    },
                ],
            },
            {
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Kansas City Chiefs", "price": -145},
                            {"name": "Baltimore Ravens", "price": 125},
                        ],
                    }
                ],
            },
        ],
    }
]


def _mock_odds_response(*args, **kwargs):
    return SAMPLE_NFL_RESPONSE


def test_end_to_end_ingest_and_render(app, client, db):
    tracked_books = {"draftkings": "DraftKings", "fanduel": "FanDuel"}
    api_client = OddsAPIClient("test-key")

    with patch.object(OddsAPIClient, "get_odds", _mock_odds_response):
        result = refresh_sport(
            api_client, "americanfootball_nfl", "NFL", tracked_books
        )
        db.session.commit()

    assert result["events"] == 1
    assert result["snapshots"] == 3  # DK h2h + DK spreads + FD h2h

    # Verify DB state
    assert db.session.query(Sport).filter_by(key="americanfootball_nfl").count() == 1
    assert db.session.query(Sportsbook).count() == 2
    game = db.session.query(Game).filter_by(external_id="evt_abc123").one()
    assert game.home_team == "Kansas City Chiefs"

    h2h_snapshots = (
        db.session.query(OddsSnapshot).filter_by(market_type="h2h").all()
    )
    assert len(h2h_snapshots) == 2
    dk_h2h = next(s for s in h2h_snapshots if s.sportsbook.key == "draftkings")
    assert dk_h2h.home_odds == -150
    assert dk_h2h.away_odds == 130

    # Render the live odds page and confirm the event shows up.
    resp = client.get("/odds/")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Kansas City Chiefs" in body
    assert "Baltimore Ravens" in body
    assert "DraftKings" in body
    assert "FanDuel" in body
