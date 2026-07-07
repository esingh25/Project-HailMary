"""Unit tests for the TIMESTAMP codec installed by the Postgres connection factory.

Regression for the CI replay-E2E failure: aware `datetime.now(UTC)` values written
to §6.4's TIMESTAMP (without time zone) columns made asyncpg raise
"can't subtract offset-naive and offset-aware datetimes".
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from hailmary.clients.postgres import decode_timestamp, encode_timestamp


@pytest.mark.unit
def test_encode_aware_utc_strips_tzinfo():
    dt = datetime(2026, 7, 6, 1, 7, 36, 432000, tzinfo=UTC)
    assert encode_timestamp(dt) == "2026-07-06 01:07:36.432000"


@pytest.mark.unit
def test_encode_aware_non_utc_normalizes_to_utc():
    dt = datetime(2026, 7, 6, 6, 7, 36, tzinfo=timezone(timedelta(hours=5)))
    assert encode_timestamp(dt) == "2026-07-06 01:07:36"


@pytest.mark.unit
def test_encode_naive_passes_through_unchanged():
    dt = datetime(2026, 7, 6, 1, 7, 36)
    assert encode_timestamp(dt) == "2026-07-06 01:07:36"


@pytest.mark.unit
def test_decode_returns_aware_utc():
    decoded = decode_timestamp("2026-07-06 01:07:36.432")
    assert decoded == datetime(2026, 7, 6, 1, 7, 36, 432000, tzinfo=UTC)
    assert decoded.tzinfo is UTC


@pytest.mark.unit
def test_round_trip_preserves_instant():
    dt = datetime(2026, 7, 6, 1, 7, 36, 123456, tzinfo=UTC)
    assert decode_timestamp(encode_timestamp(dt)) == dt
