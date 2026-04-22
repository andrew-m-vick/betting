"""Bet settlement tests: moneyline, spread, total, parlay with push handling."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import Game, ParlayLeg, Sport, Sportsbook, TrackedBet, User
from app.services.settlement import (
    LegResult,
    resolve_parlay,
    settle_bet,
    settle_moneyline,
    settle_pending_bets,
    settle_spread,
    settle_total,
)


def _seed(db, home_score=24, away_score=17, completed=True):
    user = User(email="u@example.com", password_hash="x")
    sport = Sport(key="nfl", display_name="NFL")
    book = Sportsbook(key="dk", display_name="DraftKings")
    db.session.add_all([user, sport, book])
    db.session.flush()
    game = Game(
        sport_id=sport.id,
        external_id="evt_1",
        home_team="Chiefs",
        away_team="Ravens",
        commence_time=datetime.now(timezone.utc) - timedelta(hours=3),
        completed=completed,
        home_score=home_score,
        away_score=away_score,
    )
    db.session.add(game)
    db.session.flush()
    return user, sport, book, game


class TestSingleBetMath:
    def test_moneyline_home_wins(self, app, db):
        with app.app_context():
            _, _, _, game = _seed(db)
            assert settle_moneyline(game, "home") == "won"
            assert settle_moneyline(game, "away") == "lost"

    def test_moneyline_draw_is_push(self, app, db):
        with app.app_context():
            _, _, _, game = _seed(db, home_score=2, away_score=2)
            assert settle_moneyline(game, "home") == "push"

    def test_spread_push_on_exact_line(self, app, db):
        with app.app_context():
            _, _, _, game = _seed(db, home_score=24, away_score=17)
            # Home -7 with a 7-point win is a push.
            assert settle_spread(game, "home", -7) == "push"
            # Home -6.5 with a 7-point win wins.
            assert settle_spread(game, "home", -6.5) == "won"
            # Away +6.5 loses.
            assert settle_spread(game, "away", 6.5) == "lost"

    def test_total_over_under(self, app, db):
        with app.app_context():
            _, _, _, game = _seed(db, home_score=24, away_score=17)  # total=41
            assert settle_total(game, "over", 40.5) == "won"
            assert settle_total(game, "under", 40.5) == "lost"
            assert settle_total(game, "over", 41) == "push"


class TestParlayResolution:
    def test_all_push_is_push(self):
        res = resolve_parlay([LegResult("push", 2.0), LegResult("push", 1.9)])
        assert res.outcome == "push"

    def test_any_loss_is_loss(self):
        res = resolve_parlay([LegResult("won", 2.0), LegResult("lost", 1.9)])
        assert res.outcome == "lost"

    def test_push_drops_leg_and_recalculates(self):
        # Two winning legs at 2.0 and 1.9, one pushed leg at 3.0.
        # Pushed leg drops out; combined = 2.0 * 1.9 = 3.8.
        res = resolve_parlay([
            LegResult("won", 2.0),
            LegResult("push", 3.0),
            LegResult("won", 1.9),
        ])
        assert res.outcome == "won"
        assert res.decimal_odds == pytest.approx(3.8)


class TestEndToEndSettlement:
    def test_settle_moneyline_bet_updates_status_and_payout(self, app, db):
        with app.app_context():
            user, _, book, game = _seed(db, home_score=24, away_score=17)
            bet = TrackedBet(
                user_id=user.id, game_id=game.id, sportsbook_id=book.id,
                bet_type="moneyline", selection="home",
                odds_at_bet=Decimal("-150"), stake=Decimal("100.00"),
            )
            db.session.add(bet)
            db.session.commit()
            result = settle_pending_bets()
            assert result["settled"] == 1
            db.session.refresh(bet)
            assert bet.status == "won"
            # decimal odds for -150 = 1 + 100/150 = 1.6667; payout = 166.67
            assert bet.payout == Decimal("166.67")

    def test_pending_bet_without_scores_is_skipped(self, app, db):
        with app.app_context():
            user, _, book, game = _seed(db, completed=False)
            game.home_score = None
            game.away_score = None
            bet = TrackedBet(
                user_id=user.id, game_id=game.id, sportsbook_id=book.id,
                bet_type="moneyline", selection="home",
                odds_at_bet=Decimal("-110"), stake=Decimal("50.00"),
            )
            db.session.add(bet)
            db.session.commit()
            result = settle_pending_bets()
            assert result["settled"] == 0
            db.session.refresh(bet)
            assert bet.status == "pending"

    def test_parlay_settles_to_combined_payout(self, app, db):
        with app.app_context():
            user, sport, book, game1 = _seed(db, home_score=24, away_score=17)
            game2 = Game(
                sport_id=sport.id, external_id="evt_2",
                home_team="A", away_team="B",
                commence_time=datetime.now(timezone.utc) - timedelta(hours=1),
                completed=True, home_score=10, away_score=20,
            )
            db.session.add(game2)
            db.session.flush()
            parlay = TrackedBet(
                user_id=user.id, game_id=None, sportsbook_id=book.id,
                bet_type="parlay", selection="2-leg parlay",
                odds_at_bet=Decimal("2.8000"), stake=Decimal("10.00"),
            )
            db.session.add(parlay)
            db.session.flush()
            db.session.add(ParlayLeg(parlay_bet_id=parlay.id, game_id=game1.id,
                                      selection="moneyline|home", odds=Decimal("-150")))
            db.session.add(ParlayLeg(parlay_bet_id=parlay.id, game_id=game2.id,
                                      selection="moneyline|away", odds=Decimal("+120")))
            db.session.commit()
            settle_pending_bets()
            db.session.refresh(parlay)
            assert parlay.status == "won"
            # (1.6667) * (2.20) = 3.6667; payout = 10 * 3.6667 = 36.67
            assert parlay.payout == Decimal("36.67")
