"""Semantic sub-agent -> Qdrant (DESIGN.md §5 Phase 2).

"Embed the query (Voyage), run payload-filtered ANN search over the relevant
doc_types, return top-K SemanticDoc-derived chunks with similarity scores."
"""

from datetime import datetime

from qdrant_client.models import FieldCondition, Filter, MatchValue

from hailmary.clients.qdrant import collection_for_doc_type
from hailmary.clients.voyage import VoyageClient
from hailmary.schemas.contracts import RetrievedChunk

DEFAULT_DOC_TYPES = ("game_recap", "scouting_note", "analysis", "injury_context")


def _sport_filter(sport: str) -> Filter:
    return Filter(must=[FieldCondition(key="sport", match=MatchValue(value=sport))])


def _point_to_chunk(point, now: datetime) -> RetrievedChunk:
    payload = point.payload
    return RetrievedChunk(
        chunk_id=payload["doc_id"],
        source="semantic_vector",
        content=payload["text"],
        structured_data={"doc_type": payload["doc_type"], "source": payload["source"]},
        index_score=point.score,
        freshness_ts=datetime.fromisoformat(payload["published_at"]),
        retrieved_at=now,
    )


async def fetch_semantic(
    client,
    voyage: VoyageClient,
    voyage_model: str,
    sport: str,
    query_text: str,
    k: int,
    now: datetime,
    doc_types: tuple[str, ...] = DEFAULT_DOC_TYPES,
) -> list[RetrievedChunk]:
    """Embed the query once, then ANN-search every collection the requested
    doc_types map to (de-duplicated, since injury_context and analysis share one)."""
    vector = await voyage.embed_query(voyage_model, query_text)
    query_filter = _sport_filter(sport)

    chunks: list[RetrievedChunk] = []
    collections = dict.fromkeys(collection_for_doc_type(dt) for dt in doc_types)
    for collection in collections:
        response = await client.query_points(
            collection_name=collection,
            query=vector,
            query_filter=query_filter,
            limit=k,
        )
        chunks.extend(_point_to_chunk(point, now) for point in response.points)

    return chunks
