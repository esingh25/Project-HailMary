"""Tests for the replay ingestion pass orchestration, using fake store clients.

Verifies the *composition* is correct (every source gets indexed/cached/archived,
the ratings job runs, ingestion_log rows get written) — not real ES/Qdrant/Redis/
Postgres behavior, which needs Docker.
"""

from types import SimpleNamespace

import pytest

from hailmary.clients.feeds.replay import FixtureData
from hailmary.config import get_settings
from hailmary.ingestion.scheduler import run_replay_ingestion_pass


class FakeIndices:
    def __init__(self):
        self.existing: set[str] = set()

    async def exists(self, index):
        return index in self.existing

    async def create(self, index, mappings):
        self.existing.add(index)


class FakeES:
    def __init__(self):
        self.indices = FakeIndices()
        self.index_calls: list[tuple] = []

    async def index(self, index, id, document):
        self.index_calls.append((index, id, document))


class FakeQdrant:
    def __init__(self):
        self.existing_collections: set[str] = set()
        self.upserts: list[tuple] = []

    async def get_collections(self):
        return SimpleNamespace(
            collections=[SimpleNamespace(name=n) for n in self.existing_collections]
        )

    async def create_collection(self, collection_name, vectors_config):
        self.existing_collections.add(collection_name)

    async def upsert(self, collection_name, points):
        self.upserts.append((collection_name, points))


class FakeRedis:
    def __init__(self):
        self.store: dict[str, tuple] = {}

    async def set(self, key, value, ex=None):
        self.store[key] = (value, ex)


class FakePG:
    def __init__(self):
        self.execute_calls: list[tuple] = []

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))
        return "INSERT 0 1"

    async def fetch(self, query, *args):
        return []


@pytest.mark.unit
async def test_replay_ingestion_pass_covers_every_source_and_ratings_job():
    fixture = FixtureData("synthetic_v0")
    es, qdrant, redis_client, pg = FakeES(), FakeQdrant(), FakeRedis(), FakePG()
    settings = get_settings()

    summary = await run_replay_ingestion_pass(fixture, es, qdrant, redis_client, pg, settings)

    # Stats indexed for both sports.
    assert summary["stats_nfl"] == 12
    assert summary["stats_cfb"] == 4
    # Semantic docs upserted for both sports.
    assert summary["semantic_nfl"] + summary["semantic_cfb"] == 6
    # Odds archived per game.
    assert summary["odds_2026_18_LV_KC"] == 9
    # Ratings job ran and updated something.
    assert summary["ratings_updated"] > 0

    # Indexes/collections were created since none existed.
    assert "nfl_stats" in es.indices.existing
    assert "cfb_stats" in es.indices.existing
    assert "game_recaps" in qdrant.existing_collections

    # Redis got odds/injury/weather keys.
    assert any(key.startswith("odds:") for key in redis_client.store)
    assert any(key.startswith("injury:") for key in redis_client.store)
    assert any(key.startswith("weather:") for key in redis_client.store)

    # ingestion_log rows were written (via obs.events.record_ingestion).
    ingestion_log_calls = [c for c in pg.execute_calls if "ingestion_log" in c[0]]
    assert len(ingestion_log_calls) > 0


@pytest.mark.unit
async def test_replay_ingestion_pass_skips_index_creation_when_already_present():
    fixture = FixtureData("synthetic_v0")
    es, qdrant, redis_client, pg = FakeES(), FakeQdrant(), FakeRedis(), FakePG()
    es.indices.existing.update({"nfl_stats", "cfb_stats"})
    qdrant.existing_collections.update(
        {"game_recaps", "scouting_notes", "analysis", "semantic_cache"}
    )
    settings = get_settings()

    await run_replay_ingestion_pass(fixture, es, qdrant, redis_client, pg, settings)

    # No new indexes/collections needed to be created — sets are unchanged in size.
    assert es.indices.existing == {"nfl_stats", "cfb_stats"}
