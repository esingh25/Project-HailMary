"""End-to-end tests for the Phase 3 merge/dedup/rerank/cache pipeline."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from hailmary.config import CacheConfig, DecayConfig, RetrievalConfig, TtlConfig
from hailmary.rerank.merge import merge_context
from hailmary.schemas.contracts import (
    MergedContext,
    QueryEntities,
    RetrievedChunk,
    RetrievedContext,
)
from hailmary.schemas.internal import EntityMap

NOW = datetime(2026, 7, 4, tzinfo=UTC)
ENTITY_MAP = EntityMap(team_aliases={}, players={})


class FakeVoyage:
    async def embed_query(self, model, text):
        return [0.1, 0.2]


class FakeQdrant:
    def __init__(self, search_results=None):
        self._search_results = search_results or []
        self.upserts: list[tuple] = []

    async def query_points(self, collection_name, query, limit):
        return SimpleNamespace(points=self._search_results[:limit])

    async def upsert(self, collection_name, points):
        self.upserts.append((collection_name, points))


class FakePG:
    def __init__(self, row=None):
        self._row = row
        self.execute_calls: list[tuple] = []

    async def fetchrow(self, query, *args):
        return self._row

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))


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


def fake_scorer_calls(scores):
    calls = []

    def scorer(query, documents):
        calls.append((query, documents))
        return scores[: len(documents)]

    return scorer, calls


def make_chunk(source="stats_es", chunk_id="c1", content="content", minutes_old=0):
    return RetrievedChunk(
        chunk_id=chunk_id,
        source=source,
        content=content,
        structured_data={"game_id": "g1"} if source == "live_odds" else None,
        index_score=0.5,
        freshness_ts=NOW - timedelta(minutes=minutes_old),
        retrieved_at=NOW,
    )


@pytest.mark.unit
async def test_merge_context_cache_miss_reranks_and_stores():
    entities = QueryEntities(teams=["KC"], players=[], game_id="g1", week=18, season=2026)
    retrieved = RetrievedContext(
        query_id="q1",
        chunks=[
            make_chunk("stats_es", "c1", "low relevance"),
            make_chunk("stats_es", "c2", "high relevance"),
        ],
        sources_attempted=["stats_es"],
        sources_failed=[],
    )
    scorer, scorer_calls = fake_scorer_calls([0.1, 0.9])
    qdrant = FakeQdrant(search_results=[])  # no cache hit
    pg = FakePG()

    result = await merge_context(
        "q1",
        "raw text",
        entities,
        retrieved,
        ENTITY_MAP,
        qdrant,
        pg,
        FakeRedis(),
        FakeVoyage(),
        "voyage-3",
        CacheConfig(),
        TtlConfig(),
        DecayConfig(),
        RetrievalConfig(context_budget_chunks=10),
        replay_mode=True,
        prompt_version="v1",
        now=NOW,
        scorer=scorer,
    )

    assert result.cache_hit is False
    assert len(scorer_calls) == 1  # rerank actually ran
    assert result.ranked_chunks[0].chunk_id == "c2"  # higher score sorted first
    assert len(qdrant.upserts) == 1  # stored to cache
    assert any("INSERT INTO semantic_cache_index" in c[0] for c in pg.execute_calls)


@pytest.mark.unit
async def test_merge_context_cache_hit_skips_rerank_and_refreshes_odds():
    entities = QueryEntities(teams=["KC"], players=[], game_id="g1", week=18, season=2026)
    retrieved = RetrievedContext(query_id="q1", chunks=[], sources_attempted=[], sources_failed=[])

    cached_merged = MergedContext(
        query_id="q_old",
        ranked_chunks=[make_chunk("stats_es", "cached_c1")],
        cache_hit=False,
        dropped_stale=0,
        rerank_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
    )
    qdrant = FakeQdrant(search_results=[SimpleNamespace(id="point1", score=0.99)])
    pg = FakePG(
        row={
            "cache_id": "cache1",
            "merged_context": cached_merged.model_dump_json(),
            "prompt_version": "v1",
        }
    )
    fresh_odds_snapshot = (
        '{"game_id":"g1","book":"dk","market":"spread","selection":"KC -6.5",'
        '"line":-6.5,"price":-108,"captured_at":"2026-07-04T00:00:00+00:00"}'
    )
    redis_client = FakeRedis({"odds:g1:dk:spread:KC -6.5": fresh_odds_snapshot})

    scorer, scorer_calls = fake_scorer_calls([0.9])

    result = await merge_context(
        "q1",
        "raw text",
        entities,
        retrieved,
        ENTITY_MAP,
        qdrant,
        pg,
        redis_client,
        FakeVoyage(),
        "voyage-3",
        CacheConfig(),
        TtlConfig(),
        DecayConfig(),
        RetrievalConfig(),
        replay_mode=True,
        prompt_version="v1",
        now=NOW,
        scorer=scorer,
    )

    assert result.cache_hit is True
    assert result.query_id == "q1"  # query_id updated to the current query
    assert len(scorer_calls) == 0  # rerank skipped on a cache hit
    sources = {c.source for c in result.ranked_chunks}
    assert "live_odds" in sources  # freshly fetched, not from the cached blob
    assert "stats_es" in sources  # cached evidence still present


@pytest.mark.unit
async def test_merge_context_truncates_to_context_budget():
    entities = QueryEntities(teams=["KC"], players=[], game_id=None, week=18, season=2026)
    chunks = [make_chunk("stats_es", f"c{i}", f"content {i}") for i in range(5)]
    retrieved = RetrievedContext(
        query_id="q1", chunks=chunks, sources_attempted=["stats_es"], sources_failed=[]
    )
    scorer, _ = fake_scorer_calls([0.5, 0.4, 0.3, 0.2, 0.1])
    qdrant = FakeQdrant(search_results=[])

    result = await merge_context(
        "q1",
        "raw text",
        entities,
        retrieved,
        ENTITY_MAP,
        qdrant,
        FakePG(),
        FakeRedis(),
        FakeVoyage(),
        "voyage-3",
        CacheConfig(),
        TtlConfig(),
        DecayConfig(),
        RetrievalConfig(context_budget_chunks=2),
        replay_mode=True,
        prompt_version="v1",
        now=NOW,
        scorer=scorer,
    )

    assert len(result.ranked_chunks) == 2


@pytest.mark.unit
async def test_merge_context_reports_dropped_stale_count():
    entities = QueryEntities(teams=["KC"], players=[], game_id=None, week=18, season=2026)
    stale_injury = make_chunk("live_injury", "stale1", "old injury", minutes_old=999)
    fresh_stat = make_chunk("stats_es", "fresh1", "fresh stat", minutes_old=0)
    retrieved = RetrievedContext(
        query_id="q1",
        chunks=[stale_injury, fresh_stat],
        sources_attempted=["live_injury", "stats_es"],
        sources_failed=[],
    )
    scorer, _ = fake_scorer_calls([0.5])
    qdrant = FakeQdrant(search_results=[])

    result = await merge_context(
        "q1",
        "raw text",
        entities,
        retrieved,
        ENTITY_MAP,
        qdrant,
        FakePG(),
        FakeRedis(),
        FakeVoyage(),
        "voyage-3",
        CacheConfig(),
        TtlConfig(),
        DecayConfig(),
        RetrievalConfig(),
        replay_mode=False,
        prompt_version="v1",
        now=NOW,
        scorer=scorer,
    )

    assert result.dropped_stale == 1
    assert len(result.ranked_chunks) == 1


@pytest.mark.unit
async def test_cache_hit_refreshes_odds_in_position_preserving_prompt_order():
    """Repeat queries must reproduce the miss path's chunk ordering — the writer
    prompt renders from this order, and replay cassettes key on the exact
    prompt, so an appended-at-the-end refresh would break every repeat query."""
    entities = QueryEntities(teams=["KC"], players=[], game_id="g1", week=18, season=2026)
    retrieved = RetrievedContext(query_id="q1", chunks=[], sources_attempted=[], sources_failed=[])

    stale_odds_chunk = make_chunk("live_odds", "odds:g1:dk:spread:KC -6.5", content="stale -110")
    cached_merged = MergedContext(
        query_id="q_old",
        ranked_chunks=[stale_odds_chunk, make_chunk("stats_es", "cached_c1")],
        cache_hit=False,
        dropped_stale=0,
        rerank_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
    )
    qdrant = FakeQdrant(search_results=[SimpleNamespace(id="point1", score=0.99)])
    pg = FakePG(
        row={
            "cache_id": "cache1",
            "merged_context": cached_merged.model_dump_json(),
            "prompt_version": "v1",
        }
    )
    fresh_odds_snapshot = (
        '{"game_id":"g1","book":"dk","market":"spread","selection":"KC -6.5",'
        '"line":-6.5,"price":-108,"captured_at":"2026-07-04T00:00:00+00:00"}'
    )
    redis_client = FakeRedis({"odds:g1:dk:spread:KC -6.5": fresh_odds_snapshot})
    scorer, _ = fake_scorer_calls([0.9])

    result = await merge_context(
        "q1",
        "raw text",
        entities,
        retrieved,
        ENTITY_MAP,
        qdrant,
        pg,
        redis_client,
        FakeVoyage(),
        "voyage-3",
        CacheConfig(),
        TtlConfig(),
        DecayConfig(),
        RetrievalConfig(),
        replay_mode=True,
        prompt_version="v1",
        now=NOW,
        scorer=scorer,
    )

    assert [c.chunk_id for c in result.ranked_chunks] == [
        "odds:g1:dk:spread:KC -6.5",
        "cached_c1",
    ]  # same order as the cached (miss-path) ranking
    refreshed = result.ranked_chunks[0]
    assert refreshed.structured_data["price"] == -108  # fresh line, not the cached one
