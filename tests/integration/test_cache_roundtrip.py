"""Semantic cache round-trip against real Qdrant + Postgres (PLAN.md M4).

Voyage is faked (deterministic per-text unit vectors) — the integration surface
here is the Qdrant point + Postgres index row lifecycle, not embeddings.
"""

import hashlib
import random
import uuid
from datetime import UTC, datetime

import pytest

from hailmary.ingestion.scheduler import run_replay_ingestion_pass
from hailmary.rerank.cache import lookup_cache, store_cache
from hailmary.schemas.contracts import MergedContext, RetrievedChunk

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


def _chunk(chunk_id: str, source: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source=source,
        content=f"evidence from {chunk_id}",
        structured_data=None,
        index_score=1.0,
        freshness_ts=NOW,
        retrieved_at=NOW,
    )


@pytest.mark.integration
async def test_cache_store_then_lookup_round_trips_full_ranking(stores, settings, fixture_data):
    # Ensures the semantic_cache collection exists at the fixture's vector dim.
    await run_replay_ingestion_pass(
        fixture_data, stores.es, stores.qdrant, stores.redis, stores.pg, settings
    )
    voyage = DeterministicVoyage(fixture_data.manifest["embedding_dim"])
    # Unique per run so re-runs against a warm stack never collide.
    placeholder = f"is there value on the [TEAM] spread? ({uuid.uuid4()})"

    merged = MergedContext(
        query_id=str(uuid.uuid4()),
        ranked_chunks=[_chunk("stats_1", "stats_es"), _chunk("odds_1", "live_odds")],
        cache_hit=False,
        dropped_stale=0,
        rerank_model="test",
    )
    await store_cache(stores.qdrant, stores.pg, voyage, "voyage-3", placeholder, merged, "v1", NOW)

    hit = await lookup_cache(
        stores.qdrant,
        stores.pg,
        voyage,
        "voyage-3",
        placeholder,
        settings.cache.cosine_threshold,
        "v1",
        NOW,
    )
    assert hit is not None
    # Full ranking round-trips, odds included as position placeholders; the
    # serve path (merge._refresh_live_odds) replaces odds content before use.
    assert [c.chunk_id for c in hit.ranked_chunks] == ["stats_1", "odds_1"]

    stale = await lookup_cache(
        stores.qdrant,
        stores.pg,
        voyage,
        "voyage-3",
        placeholder,
        settings.cache.cosine_threshold,
        "v2-changed",
        NOW,
    )
    assert stale is None  # prompt_version mismatch is a miss, never a stale hit
