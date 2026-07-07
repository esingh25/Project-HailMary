"""Fan-out graceful degradation with a genuinely downed source (PLAN.md M3).

ES is pointed at a dead port while Qdrant/Redis stay real: the stats source
must land in sources_failed, and the surviving sources must still return —
no exception, no empty context.
"""

import hashlib
import random
import uuid
from datetime import UTC, datetime

import pytest
from elasticsearch import AsyncElasticsearch

from hailmary.ingestion.scheduler import run_replay_ingestion_pass
from hailmary.retrieval.fanout import fetch_retrieved_context
from hailmary.schemas.contracts import QueryEntities, RetrievalPlan

NOW = datetime(2026, 1, 4, 18, 0, tzinfo=UTC)


class DeterministicVoyage:
    def __init__(self, dim: int):
        self._dim = dim

    async def embed_query(self, model: str, text: str) -> list[float]:
        seed = int(hashlib.sha256(text.encode()).hexdigest(), 16) % (2**32)
        rng = random.Random(seed)
        raw = [rng.uniform(-1, 1) for _ in range(self._dim)]
        norm = sum(x * x for x in raw) ** 0.5
        return [x / norm for x in raw]


@pytest.mark.integration
async def test_downed_es_degrades_gracefully_while_other_sources_survive(
    stores, settings, fixture_data
):
    await run_replay_ingestion_pass(
        fixture_data, stores.es, stores.qdrant, stores.redis, stores.pg, settings
    )

    plan = RetrievalPlan(
        query_id=str(uuid.uuid4()),
        intent="spread",
        entities=QueryEntities(
            teams=["KC", "LV"], players=[], game_id="2026_18_LV_KC", week=18, season=2026
        ),
        conditions=[],
        target_indexes=["stats_es", "semantic_vector", "live_odds"],
        prompt_version="v1",
    )

    dead_es = AsyncElasticsearch(hosts=["http://localhost:59200"], request_timeout=1)
    try:
        retrieved = await fetch_retrieved_context(
            plan,
            dead_es,
            stores.qdrant,
            stores.redis,
            DeterministicVoyage(fixture_data.manifest["embedding_dim"]),
            "voyage-3",
            "nfl",
            "Is there value on the Chiefs -6.5 against the Raiders?",
            NOW,
            timeout_seconds=2.0,
        )
    finally:
        await dead_es.close()

    assert "stats_es" in retrieved.sources_failed
    assert "stats_es" in retrieved.sources_attempted
    surviving_sources = {c.source for c in retrieved.chunks}
    assert "live_odds" in surviving_sources  # real Redis still served the odds
    assert all(c.source != "stats_es" for c in retrieved.chunks)
