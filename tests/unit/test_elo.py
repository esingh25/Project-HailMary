"""Tests for the pure Elo ratings update."""

import pytest

from hailmary.config import EloConfig
from hailmary.ingestion.elo import update
from hailmary.schemas.internal import GameResult


@pytest.mark.unit
def test_upset_win_increases_underdogs_rating():
    config = EloConfig(k=20.0, home_field=0.0, mov_multiplier=0.0)
    ratings = {"WEAK": 1400.0, "STRONG": 1700.0}
    game = GameResult(home_team_id="WEAK", away_team_id="STRONG", home_score=24, away_score=20)

    updated = update(ratings, [game], config)

    assert updated["WEAK"] > 1400.0
    assert updated["STRONG"] < 1700.0


@pytest.mark.unit
def test_zero_sum_rating_change():
    config = EloConfig(k=20.0, home_field=0.0, mov_multiplier=0.0)
    ratings = {"A": 1500.0, "B": 1500.0}
    game = GameResult(home_team_id="A", away_team_id="B", home_score=30, away_score=10)

    updated = update(ratings, [game], config)

    delta_a = updated["A"] - ratings["A"]
    delta_b = updated["B"] - ratings["B"]
    assert delta_a == pytest.approx(-delta_b)


@pytest.mark.unit
def test_larger_margin_of_victory_produces_larger_swing():
    config = EloConfig(k=20.0, home_field=0.0, mov_multiplier=1.0)
    ratings = {"A": 1500.0, "B": 1500.0}

    close_game = GameResult(home_team_id="A", away_team_id="B", home_score=21, away_score=20)
    blowout_game = GameResult(home_team_id="A", away_team_id="B", home_score=45, away_score=10)

    close_result = update(ratings, [close_game], config)
    blowout_result = update(ratings, [blowout_game], config)

    close_delta = close_result["A"] - ratings["A"]
    blowout_delta = blowout_result["A"] - ratings["A"]
    assert blowout_delta > close_delta


@pytest.mark.unit
def test_unlisted_team_defaults_to_default_rating():
    config = EloConfig(k=20.0, home_field=0.0, mov_multiplier=0.0)
    game = GameResult(home_team_id="NEW", away_team_id="ALSO_NEW", home_score=14, away_score=7)

    updated = update({}, [game], config, default_rating=1500.0)

    assert "NEW" in updated
    assert "ALSO_NEW" in updated
    assert updated["NEW"] > 1500.0


@pytest.mark.unit
def test_sequence_of_games_converges_sensibly():
    """A team that wins every game across a season should end with a higher rating
    than one that loses every game."""
    config = EloConfig(k=20.0, home_field=0.0, mov_multiplier=0.5)
    ratings = {"WINNER": 1500.0, "LOSER": 1500.0}

    for _ in range(8):
        game = GameResult(home_team_id="WINNER", away_team_id="LOSER", home_score=28, away_score=14)
        ratings = update(ratings, [game], config)

    assert ratings["WINNER"] > ratings["LOSER"]
