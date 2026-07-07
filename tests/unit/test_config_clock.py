"""Unit tests for Settings defaults and the Clock abstraction."""

from datetime import UTC, datetime

import pytest

from hailmary.clock import SystemClock, VirtualClock
from hailmary.config import Settings


@pytest.mark.unit
def test_settings_default_to_offline_replay_mode():
    settings = Settings(_env_file=None)
    assert settings.replay_mode is True
    assert settings.replay_llm is True
    assert settings.gating_enabled is False
    assert settings.odds_api_enabled is False


@pytest.mark.unit
def test_settings_postgres_dsn_uses_configured_fields():
    settings = Settings(_env_file=None)
    assert settings.postgres_dsn == "postgresql://hailmary:hailmary@localhost:5432/hailmary"


@pytest.mark.unit
def test_virtual_clock_returns_pinned_time_not_wall_clock():
    pinned = datetime(2026, 1, 1, tzinfo=UTC)
    clock = VirtualClock(pinned=pinned)
    assert clock.now() == pinned
    assert clock.now() == pinned  # stable across calls


@pytest.mark.unit
def test_system_clock_returns_timezone_aware_datetime():
    clock = SystemClock()
    now = clock.now()
    assert now.tzinfo is not None
