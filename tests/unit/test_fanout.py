"""Tests for parallel retrieval fan-out: source selection, merging, degradation."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from hailmary.retrieval.fanout import fetch_retrieved_context
from hailmary.schemas.contracts import Condition, QueryEntities, RetrievalPlan

NOW = datetime(2026, 7, 4, tzinfo=UTC)


class FakeES:
    def __init__(self, hits=None, delay=0.0, raise_error=False):
        self._hits = hits or []
        self._delay = delay
        self._raise_error = raise_error

    async def search(self, index, query, size):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raise_error:
            raise RuntimeError("ES is down")
        return {"hits": {"hits": self._hits[:size]}}


class FakeQdrant:
    def __init__(self, points=None, raise_error=False):
        self._points = points or []
        self._raise_error = raise_error

    async def query_points(self, collection_name, query, query_filter, limit):
        if self._raise_error:
            raise RuntimeError("Qdrant is down")
        return SimpleNamespace(points=self._points[:limit])


class FakeVoyage:
    async def embed_query(self, model, text):
        return [0.1, 0.2]


class FakeRedis:
    def __init__(self, store=None):
        self.store = store or {}

    async def get(self, key):
        return self.store.get(key)

    async def scan_iter(self, match):
        prefix = match.rstrip("*")
        for key in list(self.store.keys()):
            if key.startswith(prefix):
                yield key


def make_plan(target_indexes, game_id="g1", teams=("KC", "LV")):
    return RetrievalPlan(
        query_id="q1",
        intent="spread",
        entities=QueryEntities(
            teams=list(teams), players=[], game_id=game_id, week=18, season=2026
        ),
        conditions=[Condition(field="pass_yards", operator="gt", value=200)],
        target_indexes=target_indexes,
        prompt_version="v1",
    )


@pytest.mark.unit
async def test_fanout_attempts_only_requested_sources():
    plan = make_plan(["stats_es"])
    context = await fetch_retrieved_context(
        plan, FakeES(), FakeQdrant(), FakeRedis(), FakeVoyage(), "voyage-3", "nfl", "text", NOW
    )
    assert context.sources_attempted == ["stats_es"]
    assert context.sources_failed == []


@pytest.mark.unit
async def test_fanout_merges_chunks_from_multiple_successful_sources():
    plan = make_plan(["stats_es", "live_odds"])
    hit = {
        "_score": 1.0,
        "_source": {
            "record_id": "r1",
            "text_blob": "text",
            "fields": {},
            "indexed_at": NOW.isoformat(),
        },
    }
    redis_client = FakeRedis({})
    context = await fetch_retrieved_context(
        plan,
        FakeES([hit]),
        FakeQdrant(),
        redis_client,
        FakeVoyage(),
        "voyage-3",
        "nfl",
        "text",
        NOW,
    )
    assert len(context.chunks) == 1
    assert context.chunks[0].source == "stats_es"


@pytest.mark.unit
async def test_fanout_records_source_failure_without_aborting_others():
    plan = make_plan(["stats_es", "semantic_vector"])
    hit = {
        "_score": 1.0,
        "_source": {
            "record_id": "r1",
            "text_blob": "text",
            "fields": {},
            "indexed_at": NOW.isoformat(),
        },
    }
    context = await fetch_retrieved_context(
        plan,
        FakeES([hit]),
        FakeQdrant(raise_error=True),
        FakeRedis(),
        FakeVoyage(),
        "voyage-3",
        "nfl",
        "text",
        NOW,
    )
    assert "semantic_vector" in context.sources_failed
    assert len(context.chunks) == 1  # stats_es still succeeded


@pytest.mark.unit
async def test_fanout_treats_timeout_as_source_failure():
    plan = make_plan(["stats_es"])
    slow_es = FakeES(delay=0.2)
    context = await fetch_retrieved_context(
        plan,
        slow_es,
        FakeQdrant(),
        FakeRedis(),
        FakeVoyage(),
        "voyage-3",
        "nfl",
        "text",
        NOW,
        timeout_seconds=0.01,
    )
    assert context.sources_failed == ["stats_es"]
    assert context.chunks == []


@pytest.mark.unit
async def test_fanout_skips_live_odds_and_weather_when_no_game_id_resolved():
    plan = make_plan(["stats_es", "live_odds", "weather"], game_id=None)
    context = await fetch_retrieved_context(
        plan, FakeES(), FakeQdrant(), FakeRedis(), FakeVoyage(), "voyage-3", "nfl", "text", NOW
    )
    assert context.sources_attempted == ["stats_es"]
    assert "live_odds" not in context.sources_failed
    assert "weather" not in context.sources_failed


@pytest.mark.unit
async def test_fanout_live_injury_fans_across_all_resolved_teams():
    plan = make_plan(["live_injury"], teams=("KC", "LV"))
    redis_client = FakeRedis(
        {
            "injury:KC:mahomes_pat": (
                '{"player_id":"mahomes_pat","team_id":"KC","status":"probable",'
                '"body_part":"ankle","report_date":"2026-07-04T00:00:00+00:00"}'
            ),
            "injury:LV:lv_wr1": (
                '{"player_id":"lv_wr1","team_id":"LV","status":"out",'
                '"body_part":"hamstring","report_date":"2026-07-04T00:00:00+00:00"}'
            ),
        }
    )
    context = await fetch_retrieved_context(
        plan, FakeES(), FakeQdrant(), redis_client, FakeVoyage(), "voyage-3", "nfl", "text", NOW
    )
    assert len(context.chunks) == 2
    assert {c.structured_data["team_id"] for c in context.chunks} == {"KC", "LV"}
