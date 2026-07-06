"""Tests for semantic cache normalization, lookup, and store."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from hailmary.rerank.cache import lookup_cache, normalize_to_placeholders, store_cache
from hailmary.schemas.contracts import MergedContext, QueryEntities, RetrievedChunk
from hailmary.schemas.internal import EntityMap, PlayerAliasEntry

NOW = datetime(2026, 7, 4, tzinfo=UTC)

ENTITY_MAP = EntityMap(
    team_aliases={"kc": "KC", "chiefs": "KC", "lv": "LV", "raiders": "LV"},
    players={
        "patrick mahomes": [
            PlayerAliasEntry(team_id="KC", player_id="mahomes_pat", full_name="Patrick Mahomes")
        ],
        "mahomes": [
            PlayerAliasEntry(team_id="KC", player_id="mahomes_pat", full_name="Patrick Mahomes")
        ],
    },
)


class FakeVoyage:
    async def embed_query(self, model, text):
        return [0.1, 0.2]


class FakeQdrant:
    def __init__(self, search_results=None):
        self._search_results = search_results or []
        self.upserts: list[tuple] = []

    async def search(self, collection_name, query_vector, limit):
        return self._search_results[:limit]

    async def upsert(self, collection_name, points):
        self.upserts.append((collection_name, points))


class FakePG:
    def __init__(self, row=None):
        self._row = row
        self.execute_calls: list[tuple] = []
        self.updated_cache_ids: list[str] = []

    async def fetchrow(self, query, *args):
        return self._row

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))
        if "UPDATE semantic_cache_index" in query:
            self.updated_cache_ids.append(args[1])


def make_merged(chunks=None):
    return MergedContext(
        query_id="q1",
        ranked_chunks=chunks or [],
        cache_hit=False,
        dropped_stale=0,
        rerank_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
    )


def make_chunk(source="stats_es", chunk_id="c1"):
    return RetrievedChunk(
        chunk_id=chunk_id,
        source=source,
        content="content",
        structured_data=None,
        index_score=0.5,
        freshness_ts=NOW,
        retrieved_at=NOW,
    )


@pytest.mark.unit
def test_normalize_replaces_team_and_player_and_week():
    entities = QueryEntities(
        teams=["KC"], players=["mahomes_pat"], game_id=None, week=18, season=2026
    )
    result = normalize_to_placeholders(
        "Is there value on the Chiefs -6.5 in week 18 with Mahomes playing?",
        entities,
        ENTITY_MAP,
    )
    assert "[TEAM]" in result
    assert "[PLAYER]" in result
    assert "[WEEK]" in result
    assert "Chiefs" not in result
    assert "Mahomes" not in result


@pytest.mark.unit
def test_normalize_leaves_unresolved_entities_untouched():
    entities = QueryEntities(teams=[], players=[], game_id=None, week=None, season=2026)
    result = normalize_to_placeholders("Is there value on the Chiefs -6.5?", entities, ENTITY_MAP)
    assert result == "Is there value on the Chiefs -6.5?"


@pytest.mark.unit
async def test_lookup_cache_hit_returns_merged_context():
    merged = make_merged([make_chunk()])
    qdrant = FakeQdrant([SimpleNamespace(id="point1", score=0.95)])
    pg = FakePG(
        row={
            "cache_id": "cache1",
            "merged_context": merged.model_dump_json(),
            "prompt_version": "v1",
        }
    )

    result = await lookup_cache(
        qdrant, pg, FakeVoyage(), "voyage-3", "[TEAM] -6.5", 0.92, "v1", NOW
    )

    assert result is not None
    assert result.query_id == "q1"
    assert pg.updated_cache_ids == ["cache1"]  # last_hit_at bumped


@pytest.mark.unit
async def test_lookup_cache_miss_below_threshold():
    qdrant = FakeQdrant([SimpleNamespace(id="point1", score=0.5)])
    pg = FakePG(row={"cache_id": "cache1", "merged_context": "{}", "prompt_version": "v1"})
    result = await lookup_cache(qdrant, pg, FakeVoyage(), "voyage-3", "text", 0.92, "v1", NOW)
    assert result is None


@pytest.mark.unit
async def test_lookup_cache_miss_on_prompt_version_mismatch():
    merged = make_merged()
    qdrant = FakeQdrant([SimpleNamespace(id="point1", score=0.99)])
    pg = FakePG(
        row={
            "cache_id": "cache1",
            "merged_context": merged.model_dump_json(),
            "prompt_version": "v0_old",
        }
    )
    result = await lookup_cache(qdrant, pg, FakeVoyage(), "voyage-3", "text", 0.92, "v1", NOW)
    assert result is None


@pytest.mark.unit
async def test_lookup_cache_miss_when_no_results():
    qdrant = FakeQdrant([])
    pg = FakePG()
    result = await lookup_cache(qdrant, pg, FakeVoyage(), "voyage-3", "text", 0.92, "v1", NOW)
    assert result is None


@pytest.mark.unit
async def test_store_cache_strips_live_odds_before_persisting():
    merged = make_merged(
        [make_chunk(source="stats_es"), make_chunk(source="live_odds", chunk_id="c2")]
    )
    qdrant = FakeQdrant()
    pg = FakePG()

    await store_cache(qdrant, pg, FakeVoyage(), "voyage-3", "[TEAM] -6.5", merged, "v1", NOW)

    assert len(qdrant.upserts) == 1
    insert_call = pg.execute_calls[0]
    persisted_json = insert_call[1][2]
    assert "live_odds" not in persisted_json
    assert "stats_es" in persisted_json
