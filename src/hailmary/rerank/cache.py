"""Semantic cache: placeholder normalization + Qdrant/Postgres-backed lookup/store.

DESIGN.md §5 Phase 3 / §8: "Queries are normalized to placeholder form ([TEAM],
[PLAYER], [WEEK]) and embedded; hits at cosine >= 0.92 reuse the prior
MergedContext... Live-odds chunks are never cached — they are always re-fetched
even on a cache hit." Cache vectors live in Qdrant's `semantic_cache` collection;
the reusable MergedContext lives in Postgres `semantic_cache_index`, linked by
`qdrant_point_id`.
"""

import json
import re
import uuid
from datetime import datetime

from qdrant_client.models import PointStruct

from hailmary.clients.qdrant import SEMANTIC_CACHE
from hailmary.clients.voyage import VoyageClient
from hailmary.schemas.contracts import MergedContext, QueryEntities
from hailmary.schemas.internal import EntityMap


def normalize_to_placeholders(raw_text: str, entities: QueryEntities, entity_map: EntityMap) -> str:
    """Replace resolved entity mentions with generic placeholders so structurally
    similar queries about different teams/players/weeks hash to nearby vectors."""
    text = raw_text

    for alias, team_id in entity_map.team_aliases.items():
        if team_id in entities.teams:
            text = re.sub(rf"\b{re.escape(alias)}\b", "[TEAM]", text, flags=re.IGNORECASE)

    for name, candidates in entity_map.players.items():
        if any(c.player_id in entities.players for c in candidates):
            text = re.sub(rf"\b{re.escape(name)}\b", "[PLAYER]", text, flags=re.IGNORECASE)

    if entities.week is not None:
        text = re.sub(rf"\b{entities.week}\b", "[WEEK]", text)

    return text


async def lookup_cache(
    qdrant_client,
    pg,
    voyage: VoyageClient,
    voyage_model: str,
    placeholder_text: str,
    cosine_threshold: float,
    prompt_version: str,
    now: datetime,
) -> MergedContext | None:
    """Returns the cached MergedContext on a hit, else None (including on a
    prompt_version mismatch — a stale cache entry from before a prompt change)."""
    vector = await voyage.embed_query(voyage_model, placeholder_text)
    results = await qdrant_client.search(
        collection_name=SEMANTIC_CACHE, query_vector=vector, limit=1
    )
    if not results or results[0].score < cosine_threshold:
        return None

    row = await pg.fetchrow(
        "SELECT cache_id, merged_context, prompt_version FROM semantic_cache_index "
        "WHERE qdrant_point_id = $1",
        str(results[0].id),
    )
    if row is None or row["prompt_version"] != prompt_version:
        return None

    await pg.execute(
        "UPDATE semantic_cache_index SET last_hit_at = $1 WHERE cache_id = $2",
        now,
        row["cache_id"],
    )
    return MergedContext.model_validate(json.loads(row["merged_context"]))


async def store_cache(
    qdrant_client,
    pg,
    voyage: VoyageClient,
    voyage_model: str,
    placeholder_text: str,
    merged: MergedContext,
    prompt_version: str,
    now: datetime,
) -> None:
    """Persist a freshly-built MergedContext under its placeholder-form query.
    Live-odds chunks are stripped first — they must never be served stale."""
    vector = await voyage.embed_query(voyage_model, placeholder_text)
    point_id = str(uuid.uuid4())

    await qdrant_client.upsert(
        collection_name=SEMANTIC_CACHE,
        points=[
            PointStruct(id=point_id, vector=vector, payload={"placeholder_text": placeholder_text})
        ],
    )

    cacheable = merged.model_copy(
        update={"ranked_chunks": [c for c in merged.ranked_chunks if c.source != "live_odds"]}
    )
    await pg.execute(
        "INSERT INTO semantic_cache_index "
        "(placeholder_text, qdrant_point_id, merged_context, prompt_version, created_at) "
        "VALUES ($1, $2, $3, $4, $5)",
        placeholder_text,
        point_id,
        cacheable.model_dump_json(),
        prompt_version,
        now,
    )
