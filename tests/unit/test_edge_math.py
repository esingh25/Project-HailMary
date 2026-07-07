"""Hand-computed test cases for deterministic edge/EV math."""

from datetime import UTC, datetime

import pytest

from hailmary.config import EdgeConfig
from hailmary.schemas.contracts import OddsSnapshot
from hailmary.synthesis.edge_math import (
    american_to_implied,
    build_edge_analysis,
    classify_assessment,
    expected_value_pct,
    payout_per_unit_stake,
)

NOW = datetime(2026, 7, 4, tzinfo=UTC)


@pytest.mark.unit
@pytest.mark.parametrize(
    "odds,expected",
    [
        (-110, 0.5238),
        (150, 0.40),
        (-200, 0.6667),
        (100, 0.50),
    ],
)
def test_american_to_implied_matches_hand_computed_values(odds, expected):
    assert american_to_implied(odds) == pytest.approx(expected, abs=1e-4)


@pytest.mark.unit
def test_payout_per_unit_stake_negative_odds():
    assert payout_per_unit_stake(-110) == pytest.approx(100 / 110)


@pytest.mark.unit
def test_payout_per_unit_stake_positive_odds():
    assert payout_per_unit_stake(150) == pytest.approx(1.5)


@pytest.mark.unit
def test_expected_value_is_zero_when_model_matches_implied():
    implied = american_to_implied(-110)
    ev = expected_value_pct(implied, -110)
    assert ev == pytest.approx(0.0, abs=1e-6)


@pytest.mark.unit
def test_expected_value_positive_when_model_probability_exceeds_implied():
    ev = expected_value_pct(0.58, -110)
    assert ev > 0


@pytest.mark.unit
def test_expected_value_negative_when_model_probability_below_implied():
    ev = expected_value_pct(0.45, -110)
    assert ev < 0


@pytest.mark.unit
@pytest.mark.parametrize(
    "ev_pct,expected",
    [
        (None, "insufficient_data"),
        (3.0, "value"),
        (10.0, "value"),
        (-3.0, "no_value"),
        (-10.0, "no_value"),
        (0.0, "fair"),
        (2.9, "fair"),
        (-2.9, "fair"),
    ],
)
def test_classify_assessment_threshold_edges(ev_pct, expected):
    config = EdgeConfig()
    assert classify_assessment(ev_pct, config) == expected


@pytest.mark.unit
def test_build_edge_analysis_covered_market_with_model_probability():
    config = EdgeConfig()
    odds = OddsSnapshot(
        game_id="g1",
        book="dk",
        market="spread",
        selection="KC -6.5",
        line=-6.5,
        price=-110,
        captured_at=NOW,
    )
    result = build_edge_analysis(odds, model_probability=0.58, config=config)
    assert result.model_probability == 0.58
    assert result.expected_value_pct is not None
    assert result.assessment != "insufficient_data"


@pytest.mark.unit
def test_build_edge_analysis_none_probability_propagates_insufficient_data():
    config = EdgeConfig()
    odds = OddsSnapshot(
        game_id="g1",
        book="dk",
        market="player_prop",
        selection="Mahomes o250.5 pass yds",
        line=250.5,
        price=-115,
        captured_at=NOW,
    )
    result = build_edge_analysis(odds, model_probability=None, config=config)
    assert result.model_probability is None
    assert result.expected_value_pct is None
    assert result.assessment == "insufficient_data"


@pytest.mark.unit
def test_build_edge_analysis_uncovered_market_ignores_model_probability():
    """Totals (outside the Elo heuristic's coverage) read insufficient_data even if a
    probability is passed in error."""
    config = EdgeConfig()
    odds = OddsSnapshot(
        game_id="g1",
        book="dk",
        market="total",
        selection="Over 47.5",
        line=47.5,
        price=-110,
        captured_at=NOW,
    )
    result = build_edge_analysis(odds, model_probability=0.6, config=config)
    assert result.assessment == "insufficient_data"
    assert result.model_probability is None
