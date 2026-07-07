"""Tests for the Odds API monthly budget guard arithmetic."""

from datetime import date

import pytest

from hailmary.ingestion.budget import BudgetState, try_consume


@pytest.mark.unit
def test_consume_within_budget_succeeds():
    state = BudgetState(
        source="the_odds_api", period_start=date(2026, 7, 1), calls_used=10, calls_limit=500
    )
    new_state, allowed = try_consume(state, 5, today=date(2026, 7, 4))
    assert allowed is True
    assert new_state.calls_used == 15


@pytest.mark.unit
def test_consume_exceeding_budget_is_refused_and_hard():
    state = BudgetState(
        source="the_odds_api", period_start=date(2026, 7, 1), calls_used=498, calls_limit=500
    )
    new_state, allowed = try_consume(state, 5, today=date(2026, 7, 4))
    assert allowed is False
    assert new_state.calls_used == 498  # unchanged — the call must not happen


@pytest.mark.unit
def test_consume_exactly_at_limit_succeeds():
    state = BudgetState(
        source="the_odds_api", period_start=date(2026, 7, 1), calls_used=495, calls_limit=500
    )
    new_state, allowed = try_consume(state, 5, today=date(2026, 7, 4))
    assert allowed is True
    assert new_state.calls_used == 500


@pytest.mark.unit
def test_new_month_rolls_over_usage_to_zero():
    state = BudgetState(
        source="the_odds_api", period_start=date(2026, 6, 1), calls_used=499, calls_limit=500
    )
    new_state, allowed = try_consume(state, 5, today=date(2026, 7, 1))
    assert allowed is True
    assert new_state.period_start == date(2026, 7, 1)
    assert new_state.calls_used == 5


@pytest.mark.unit
def test_rollover_alone_does_not_grant_extra_calls_beyond_limit():
    state = BudgetState(
        source="the_odds_api", period_start=date(2026, 6, 1), calls_used=100, calls_limit=500
    )
    new_state, allowed = try_consume(state, 600, today=date(2026, 7, 1))
    assert allowed is False
    assert new_state.period_start == date(2026, 7, 1)
    assert new_state.calls_used == 0
