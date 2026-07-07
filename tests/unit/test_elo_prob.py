"""Tests for the Elo-diff logistic win-probability mapping."""

import pytest

from hailmary.config import EloConfig
from hailmary.synthesis.elo_prob import win_probability


@pytest.mark.unit
def test_equal_ratings_no_home_field_is_fifty_fifty():
    config = EloConfig(home_field=0.0)
    p = win_probability(1500, 1500, is_home=False, config=config, logistic_scale=400.0)
    assert p == pytest.approx(0.5)


@pytest.mark.unit
def test_home_field_bonus_pushes_probability_above_half_for_equal_ratings():
    config = EloConfig(home_field=65.0)
    p = win_probability(1500, 1500, is_home=True, config=config, logistic_scale=400.0)
    assert p > 0.5


@pytest.mark.unit
def test_symmetry_between_two_teams():
    config = EloConfig(home_field=0.0)
    p_a = win_probability(1600, 1500, is_home=False, config=config, logistic_scale=400.0)
    p_b = win_probability(1500, 1600, is_home=False, config=config, logistic_scale=400.0)
    assert p_a + p_b == pytest.approx(1.0)


@pytest.mark.unit
def test_monotonic_in_rating_difference():
    config = EloConfig(home_field=0.0)
    p_small_gap = win_probability(1550, 1500, is_home=False, config=config, logistic_scale=400.0)
    p_large_gap = win_probability(1700, 1500, is_home=False, config=config, logistic_scale=400.0)
    assert p_large_gap > p_small_gap


@pytest.mark.unit
def test_probability_stays_within_unit_interval_for_large_gaps():
    config = EloConfig(home_field=0.0)
    p = win_probability(3000, 500, is_home=False, config=config, logistic_scale=400.0)
    assert 0.0 < p < 1.0
