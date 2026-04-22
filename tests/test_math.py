"""Math helper tests: odds conversions, EV, Kelly, arbitrage."""
from __future__ import annotations

import math

import pytest

from app.services.math_utils import (
    MathError,
    american_to_decimal,
    american_to_implied_prob,
    ev_and_kelly,
    find_two_way_arb,
)


class TestOddsConversions:
    @pytest.mark.parametrize("american,expected_decimal", [
        (+100, 2.0),
        (+150, 2.5),
        (-110, 1 + 100/110),
        (-200, 1.5),
    ])
    def test_american_to_decimal(self, american, expected_decimal):
        assert math.isclose(american_to_decimal(american), expected_decimal, rel_tol=1e-9)

    @pytest.mark.parametrize("american,expected_prob", [
        (+100, 0.5),
        (-110, 110/210),
        (+200, 1/3),
    ])
    def test_american_to_implied_prob(self, american, expected_prob):
        assert math.isclose(american_to_implied_prob(american), expected_prob, rel_tol=1e-9)

    def test_zero_odds_rejected(self):
        with pytest.raises(MathError):
            american_to_decimal(0)

    def test_in_between_odds_rejected(self):
        with pytest.raises(MathError):
            american_to_decimal(50)
        with pytest.raises(MathError):
            american_to_decimal(-50)


class TestEVKelly:
    def test_positive_ev_when_true_prob_beats_implied(self):
        # -110 implies ~52.4%. Claim 60%.
        result = ev_and_kelly(-110, 0.60)
        assert result.is_positive_ev
        assert result.ev_per_unit > 0
        assert 0 < result.kelly_fraction < 1
        assert result.quarter_kelly_fraction == pytest.approx(result.kelly_fraction / 4)

    def test_negative_ev_clamps_kelly_to_zero(self):
        result = ev_and_kelly(-110, 0.40)
        assert not result.is_positive_ev
        assert result.kelly_fraction == 0.0

    def test_invalid_prob_rejected(self):
        with pytest.raises(MathError):
            ev_and_kelly(-110, 0.0)
        with pytest.raises(MathError):
            ev_and_kelly(-110, 1.0)


class TestArbitrage:
    def test_no_arb_when_market_is_efficient(self):
        # Typical -110 / -110 market: 110/210 + 110/210 ~= 1.048. No arb.
        assert find_two_way_arb(-110, -110) is None

    def test_arb_when_cross_book_odds_favor_bettor(self):
        # Rare case: +105 / +105 from different books.
        arb = find_two_way_arb(+105, +105)
        assert arb is not None
        assert arb.profit_pct > 0
        assert arb.stake_home_pct + arb.stake_away_pct == pytest.approx(1.0)

    def test_arb_stake_split_equalizes_payout(self):
        arb = find_two_way_arb(+120, +110)
        assert arb is not None
        payout_if_home = arb.stake_home_pct * arb.decimal_home
        payout_if_away = arb.stake_away_pct * arb.decimal_away
        assert payout_if_home == pytest.approx(payout_if_away, rel=1e-9)
