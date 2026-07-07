"""Tests for the semantic sub-agent: embed + filtered ANN + point -> chunk mapping."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from hailmary.retrieval.semantic_agent import fetch_semantic

NOW = datetime(2026, 7, 4, tzinfo=UTC)


class FakeVoyage:
    def __init__(self, vector):
        self._vector = vector
        self.embed_calls: list[tuple] = []

    async def embed_query(self, model, text):
        self.embed_calls.append((model, text))
        return self._vector


class FakeQdrant:
    def __init__(self, points_by_collection: dict[str, list]):
        self._points_by_collection = points_by_collection
        self.search_calls: list[dict] = []

    async def query_points(self, collection_name, query, query_filter, limit):
        self.search_calls.append({"collection_name": collection_name, "limit": limit})
        return SimpleNamespace(points=self._points_by_collection.get(collection_name, [])[:limit])


def make_point(doc_id="d1", score=0.9, doc_type="game_recap"):
    return SimpleNamespace(
        score=score,
        payload={
            "doc_id": doc_id,
            "doc_type": doc_type,
            "text": "KC dominated on Thursday night",
            "source": "curated_scrape",
            "published_at": NOW.isoformat(),
        },
    )


@pytest.mark.unit
async def test_fetch_semantic_embeds_query_once():
    voyage = FakeVoyage([0.1, 0.2])
    qdrant = FakeQdrant({})

    await fetch_semantic(qdrant, voyage, "voyage-3", "nfl", "Mahomes Thursday night", k=5, now=NOW)

    assert voyage.embed_calls == [("voyage-3", "Mahomes Thursday night")]


@pytest.mark.unit
async def test_fetch_semantic_searches_each_target_collection():
    voyage = FakeVoyage([0.1, 0.2])
    qdrant = FakeQdrant(
        {"game_recaps": [make_point("d1", doc_type="game_recap")], "scouting_notes": []}
    )

    chunks = await fetch_semantic(
        qdrant,
        voyage,
        "voyage-3",
        "nfl",
        "query",
        k=5,
        now=NOW,
        doc_types=("game_recap", "scouting_note"),
    )

    collections_searched = {c["collection_name"] for c in qdrant.search_calls}
    assert collections_searched == {"game_recaps", "scouting_notes"}
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "d1"
    assert chunks[0].source == "semantic_vector"
    assert chunks[0].content == "KC dominated on Thursday night"
    assert chunks[0].index_score == 0.9


@pytest.mark.unit
async def test_fetch_semantic_deduplicates_collections_shared_by_multiple_doc_types():
    """injury_context and analysis both map to the 'analysis' collection —
    it must only be searched once, not twice."""
    voyage = FakeVoyage([0.1, 0.2])
    qdrant = FakeQdrant({"analysis": [make_point("d1", doc_type="analysis")]})

    await fetch_semantic(
        qdrant,
        voyage,
        "voyage-3",
        "nfl",
        "query",
        k=5,
        now=NOW,
        doc_types=("analysis", "injury_context"),
    )

    analysis_calls = [c for c in qdrant.search_calls if c["collection_name"] == "analysis"]
    assert len(analysis_calls) == 1


@pytest.mark.unit
async def test_fetch_semantic_respects_k_per_collection():
    voyage = FakeVoyage([0.1])
    qdrant = FakeQdrant({"game_recaps": [make_point("d1"), make_point("d2"), make_point("d3")]})

    chunks = await fetch_semantic(
        qdrant, voyage, "voyage-3", "nfl", "query", k=2, now=NOW, doc_types=("game_recap",)
    )

    assert len(chunks) == 2
