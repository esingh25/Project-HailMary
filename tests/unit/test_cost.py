"""Tests for LLM cost circuit breaker trackers."""

import pytest

from hailmary.config import CostConfig
from hailmary.obs.cost import DailyCostTracker, QueryCostTracker, estimate_cost_usd


@pytest.mark.unit
def test_estimate_cost_usd_computes_from_token_prices():
    cost = estimate_cost_usd(
        input_tokens=1_000_000,
        output_tokens=500_000,
        input_price_per_mtok=1.0,
        output_price_per_mtok=5.0,
    )
    assert cost == pytest.approx(1.0 + 2.5)


@pytest.mark.unit
def test_query_cost_tracker_alert_and_cap_thresholds():
    config = CostConfig(per_query_usd_cap=0.15, per_query_usd_alert=0.10)
    tracker = QueryCostTracker()

    tracker.add(0.05)
    assert tracker.exceeds_alert(config) is False
    assert tracker.exceeds_cap(config) is False

    tracker.add(0.06)  # total 0.11 > alert
    assert tracker.exceeds_alert(config) is True
    assert tracker.exceeds_cap(config) is False

    tracker.add(0.10)  # total 0.21 > cap
    assert tracker.exceeds_cap(config) is True


@pytest.mark.unit
def test_daily_cost_tracker_alert_at_configured_percentage():
    config = CostConfig(per_day_usd_cap=2.0, per_day_usd_alert_pct=0.80)
    tracker = DailyCostTracker()

    tracker.add(1.5)
    assert tracker.exceeds_alert(config) is False  # 1.5 / 2.0 = 75%

    tracker.add(0.11)
    assert tracker.exceeds_alert(config) is True  # 1.61 / 2.0 > 80%
    assert tracker.exceeds_cap(config) is False


@pytest.mark.unit
def test_daily_cost_tracker_exceeds_cap():
    config = CostConfig(per_day_usd_cap=2.0)
    tracker = DailyCostTracker()
    tracker.add(2.5)
    assert tracker.exceeds_cap(config) is True
