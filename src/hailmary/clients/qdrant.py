"""Qdrant client + collection setup (DESIGN.md §6.2).

Collections: game_recaps, scouting_notes, analysis, plus semantic_cache (the query
cache lives in Qdrant too, keeping all vectors in one place).
"""

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams

from hailmary.config import Settings

GAME_RECAPS = "game_recaps"
SCOUTING_NOTES = "scouting_notes"
ANALYSIS = "analysis"
SEMANTIC_CACHE = "semantic_cache"

DOC_TYPE_TO_COLLECTION = {
    "game_recap": GAME_RECAPS,
    "scouting_note": SCOUTING_NOTES,
    "analysis": ANALYSIS,
    "injury_context": ANALYSIS,  # no dedicated collection; grouped with analysis
}


def collection_for_doc_type(doc_type: str) -> str:
    if doc_type not in DOC_TYPE_TO_COLLECTION:
        raise ValueError(f"Unknown doc_type: {doc_type!r}")
    return DOC_TYPE_TO_COLLECTION[doc_type]


def get_qdrant_client(settings: Settings) -> AsyncQdrantClient:
    return AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)


async def ensure_collection(client: AsyncQdrantClient, name: str, vector_size: int) -> None:
    """Create a collection with the given vector size if it doesn't already exist."""
    existing = await client.get_collections()
    existing_names = {c.name for c in existing.collections}
    if name not in existing_names:
        await client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )


async def ensure_all_collections(client: AsyncQdrantClient, vector_size: int) -> None:
    for name in (GAME_RECAPS, SCOUTING_NOTES, ANALYSIS, SEMANTIC_CACHE):
        await ensure_collection(client, name, vector_size)
