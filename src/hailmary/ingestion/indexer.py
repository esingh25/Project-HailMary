"""Idempotent Phase 0 indexing (DESIGN.md §5 Phase 0, §13 principle 8).

"Re-ingesting the same source record must not create duplicate index documents.
Dedup is by deterministic content hash; index writes are upserts keyed by
canonical record ID." Each function here is a thin, single-purpose upsert against
one store; ingestion/scheduler.py (M2.5) composes them into a full ingestion pass.
"""

import uuid
from datetime import timedelta

import asyncpg
import redis.asyncio as redis
from elasticsearch import AsyncElasticsearch
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct

from hailmary.clients.es import index_name_for_sport
from hailmary.clients.qdrant import collection_for_doc_type
from hailmary.clients.redis import injury_key, odds_key, weather_key
from hailmary.config import TtlConfig
from hailmary.schemas.contracts import InjuryRecord, OddsSnapshot, SemanticDoc, StatRecord
from hailmary.schemas.internal import WeatherRecord

# Fixed namespace so the same content_hash always maps to the same Qdrant point id —
# this is what makes the Qdrant upsert idempotent across re-ingestion runs.
QDRANT_NAMESPACE = uuid.UUID("2f3b1a2e-6e1a-4c3d-8f2b-000000000000")


def doc_point_id(content_hash: str) -> str:
    return str(uuid.uuid5(QDRANT_NAMESPACE, content_hash))


async def upsert_stats(client: AsyncElasticsearch, records: list[StatRecord]) -> int:
    """ES `index` by a fixed `id` is inherently an upsert (overwrites the prior doc)."""
    for record in records:
        await client.index(
            index=index_name_for_sport(record.sport),
            id=record.record_id,
            document=record.model_dump(mode="json"),
        )
    return len(records)


async def upsert_semantic_docs(
    client: AsyncQdrantClient,
    docs: list[SemanticDoc],
    embeddings: dict[str, list[float]],
) -> int:
    """Group docs by their target collection and upsert, keyed by a content-hash-derived id."""
    points_by_collection: dict[str, list[PointStruct]] = {}
    for doc in docs:
        collection = collection_for_doc_type(doc.doc_type)
        points_by_collection.setdefault(collection, []).append(
            PointStruct(
                id=doc_point_id(doc.content_hash),
                vector=embeddings[doc.doc_id],
                payload={
                    "doc_id": doc.doc_id,
                    "sport": doc.sport,
                    "doc_type": doc.doc_type,
                    "source": doc.source,
                    "published_at": doc.published_at.isoformat(),
                    "content_hash": doc.content_hash,
                },
            )
        )

    total = 0
    for collection, points in points_by_collection.items():
        await client.upsert(collection_name=collection, points=points)
        total += len(points)
    return total


async def cache_odds(
    redis_client: redis.Redis,
    snapshots: list[OddsSnapshot],
    ttl: TtlConfig,
    replay_mode: bool,
) -> int:
    """Redis SET on a natural key is inherently an upsert (overwrites the prior value)."""
    minutes = ttl.odds_minutes_replay if replay_mode else ttl.odds_minutes_live
    for snap in snapshots:
        key = odds_key(snap.game_id, snap.book, snap.market, snap.selection)
        await redis_client.set(key, snap.model_dump_json(), ex=timedelta(minutes=minutes))
    return len(snapshots)


async def archive_odds(pg: asyncpg.Connection, snapshots: list[OddsSnapshot]) -> int:
    """Append-only line-movement history — idempotent via a unique constraint on
    (game_id, book, market, selection, captured_at), not an upsert-by-id."""
    inserted = 0
    for snap in snapshots:
        result = await pg.execute(
            """
            INSERT INTO odds_archive (game_id, book, market, selection, line, price, captured_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (game_id, book, market, selection, captured_at) DO NOTHING
            """,
            snap.game_id,
            snap.book,
            snap.market,
            snap.selection,
            snap.line,
            snap.price,
            snap.captured_at,
        )
        if result == "INSERT 0 1":
            inserted += 1
    return inserted


async def cache_injuries(
    redis_client: redis.Redis, records: list[InjuryRecord], ttl: TtlConfig
) -> int:
    for rec in records:
        key = injury_key(rec.player_id)
        await redis_client.set(
            key, rec.model_dump_json(), ex=timedelta(minutes=ttl.injuries_minutes)
        )
    return len(records)


async def cache_weather(
    redis_client: redis.Redis, records: list[WeatherRecord], ttl: TtlConfig
) -> int:
    for rec in records:
        key = weather_key(rec.game_id)
        await redis_client.set(key, rec.model_dump_json(), ex=timedelta(hours=ttl.weather_hours))
    return len(records)
