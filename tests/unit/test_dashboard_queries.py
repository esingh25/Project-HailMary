"""Tests for the dashboard's Postgres data-fetching functions."""

import pytest

from dashboard.queries import (
    get_cache_stats,
    get_ingestion_health,
    get_odds_budget,
    get_query_trace,
)


class FakePG:
    def __init__(self, fetch_result=None, fetchrow_result=None):
        self._fetch_result = fetch_result or []
        self._fetchrow_result = fetchrow_result
        self.fetch_calls: list[tuple] = []

    async def fetch(self, query, *args):
        self.fetch_calls.append((query, args))
        return self._fetch_result

    async def fetchrow(self, query, *args):
        return self._fetchrow_result


@pytest.mark.unit
async def test_get_ingestion_health_returns_rows_as_dicts():
    pg = FakePG(fetch_result=[{"source": "nflverse", "records": 12, "status": "ok", "ran_at": "t"}])
    result = await get_ingestion_health(pg)
    assert result == [{"source": "nflverse", "records": 12, "status": "ok", "ran_at": "t"}]


@pytest.mark.unit
async def test_get_query_trace_filters_by_query_id():
    pg = FakePG(
        fetch_result=[{"phase": "decompose", "event": "plan_built", "detail": None, "ts": "t"}]
    )
    result = await get_query_trace(pg, "q1")
    assert result[0]["event"] == "plan_built"
    assert pg.fetch_calls[0][1] == ("q1",)


@pytest.mark.unit
async def test_get_cache_stats_computes_hit_rate():
    pg = FakePG(fetchrow_result={"total": 10, "hit_count": 3, "avg_age_seconds": 120.5})
    result = await get_cache_stats(pg)
    assert result == {"total": 10, "hit_rate": 0.3, "avg_age_seconds": 120.5}


@pytest.mark.unit
async def test_get_cache_stats_handles_empty_cache():
    pg = FakePG(fetchrow_result={"total": 0, "hit_count": 0, "avg_age_seconds": None})
    result = await get_cache_stats(pg)
    assert result == {"total": 0, "hit_rate": 0.0, "avg_age_seconds": 0.0}


@pytest.mark.unit
async def test_get_odds_budget_computes_remaining():
    pg = FakePG(fetchrow_result={"calls_used": 120, "calls_limit": 500})
    result = await get_odds_budget(pg)
    assert result == {"calls_used": 120, "calls_limit": 500, "remaining": 380}


@pytest.mark.unit
async def test_get_odds_budget_none_when_no_row():
    pg = FakePG(fetchrow_result=None)
    result = await get_odds_budget(pg)
    assert result is None
