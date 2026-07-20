"""Phase 3 orchestration: merge, dedup & rerank (DESIGN.md §5 Phase 3).

Pipeline: semantic-cache lookup (skip rerank on a hit, always refresh live-odds)
-> dedup -> freshness gate -> cross-encoder rerank -> recency decay -> truncate
to the context budget -> cache store on a miss.

`scorer` is injectable (defaults to the real cross-encoder) so the unit test
tier never has to load sentence-transformers or download a model.
"""

from datetime import datetime

from hailmary.clients.voyage import VoyageClient
from hailmary.config import CacheConfig, DecayConfig, RetrievalConfig, TtlConfig
from hailmary.rerank.cache import lookup_cache, normalize_to_placeholders, store_cache
from hailmary.rerank.cross_encoder import score_pairs
from hailmary.rerank.decay import apply_decay
from hailmary.rerank.dedup import dedup
from hailmary.rerank.freshness import gate
from hailmary.retrieval.live_agent import fetch_odds
from hailmary.schemas.contracts import MergedContext, QueryEntities, RetrievedContext
from hailmary.schemas.internal import EntityMap


async def _refresh_live_odds(
    cached: MergedContext, redis_client, game_id: str | None, now: datetime
) -> MergedContext:
    """Live-odds chunks are never served from cache — always re-fetched, even on
    a cache hit (a stale line poisons the edge math).

    Refresh is in-position by chunk_id (odds chunk_ids are stable natural keys),
    so a cache hit reproduces the miss path's chunk ordering. Ordering matters:
    the writer prompt is rendered from this order, and in replay mode an
    identical prompt is what makes the recorded cassette hit again on a repeat
    query. Odds chunks that vanished from the live cache are dropped; brand-new
    ones append at the end."""
    fresh_odds = await fetch_odds(redis_client, game_id, now) if game_id else []
    fresh_by_id = {c.chunk_id: c for c in fresh_odds}

    refreshed = []
    for chunk in cached.ranked_chunks:
        if chunk.source != "live_odds":
            refreshed.append(chunk)
        elif chunk.chunk_id in fresh_by_id:
            refreshed.append(fresh_by_id.pop(chunk.chunk_id))
    refreshed.extend(fresh_by_id.values())

    return cached.model_copy(update={"ranked_chunks": refreshed, "cache_hit": True})


async def merge_context(
    query_id: str,
    raw_text: str,
    entities: QueryEntities,
    retrieved: RetrievedContext,
    entity_map: EntityMap,
    qdrant_client,
    pg,
    redis_client,
    voyage: VoyageClient,
    voyage_model: str,
    cache_config: CacheConfig,
    ttl_config: TtlConfig,
    decay_config: DecayConfig,
    retrieval_config: RetrievalConfig,
    replay_mode: bool,
    prompt_version: str,
    now: datetime,
    scorer=score_pairs,
    rerank_model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
) -> MergedContext:
    placeholder_text = normalize_to_placeholders(raw_text, entities, entity_map)

    cached = await lookup_cache(
        qdrant_client,
        pg,
        voyage,
        voyage_model,
        placeholder_text,
        cache_config.cosine_threshold,
        prompt_version,
        now,
    )
    if cached is not None:
        refreshed = await _refresh_live_odds(cached, redis_client, entities.game_id, now)
        return refreshed.model_copy(update={"query_id": query_id})

    deduped = dedup(retrieved.chunks)
    kept, dropped_stale = gate(deduped, ttl_config, now, replay_mode)

    scores = scorer(raw_text, [c.content for c in kept]) if kept else []
    decayed = apply_decay(list(zip(kept, scores, strict=True)), now, decay_config)
    decayed.sort(key=lambda pair: pair[1], reverse=True)
    truncated = [chunk for chunk, _ in decayed[: retrieval_config.context_budget_chunks]]

    merged = MergedContext(
        query_id=query_id,
        ranked_chunks=truncated,
        cache_hit=False,
        dropped_stale=dropped_stale,
        rerank_model=rerank_model_name,
    )

    await store_cache(
        qdrant_client, pg, voyage, voyage_model, placeholder_text, merged, prompt_version, now
    )
    return merged
