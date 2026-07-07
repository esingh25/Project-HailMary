"""Known-answer retrieval against real ES/Qdrant loaded with the fixture."""

from datetime import UTC, datetime

import pytest

from hailmary.clients.qdrant import GAME_RECAPS
from hailmary.ingestion.scheduler import run_replay_ingestion_pass
from hailmary.retrieval.stats_agent import fetch_stats
from hailmary.schemas.contracts import QueryEntities

NOW = datetime(2026, 1, 4, 18, 0, tzinfo=UTC)


@pytest.mark.integration
async def test_stats_agent_finds_planted_mahomes_records(stores, settings, fixture_data):
    await run_replay_ingestion_pass(
        fixture_data, stores.es, stores.qdrant, stores.redis, stores.pg, settings
    )
    await stores.es.indices.refresh(index="nfl_stats")

    entities = QueryEntities(
        teams=["KC"], players=["mahomes_pat"], game_id=None, week=None, season=2026
    )
    chunks = await fetch_stats(
        stores.es, "nfl", entities, [], "Mahomes passing yards", k=20, now=NOW
    )

    assert chunks, "expected at least one stats hit for the planted Mahomes records"
    assert all(c.source == "stats_es" for c in chunks)
    # chunk_id is the canonical record_id (e.g. st_kc_pass_mahomes_w18)
    assert any("mahomes" in c.chunk_id for c in chunks)


@pytest.mark.integration
async def test_semantic_index_returns_doc_for_its_own_committed_vector(
    stores, settings, fixture_data
):
    """A doc's own precomputed embedding must retrieve that doc as the top hit —
    the known-answer sanity check that vectors and payloads stayed aligned
    through ingestion."""
    await run_replay_ingestion_pass(
        fixture_data, stores.es, stores.qdrant, stores.redis, stores.pg, settings
    )

    recap = next(d for d in fixture_data.semantic_docs if d.doc_type == "game_recap")
    vector = fixture_data.embeddings["vectors"][recap.doc_id]

    response = await stores.qdrant.query_points(collection_name=GAME_RECAPS, query=vector, limit=1)

    assert response.points, "expected a hit from the game_recaps collection"
    top = response.points[0]
    assert top.payload["doc_id"] == recap.doc_id
    assert top.score == pytest.approx(1.0, abs=1e-5)  # cosine similarity to itself
