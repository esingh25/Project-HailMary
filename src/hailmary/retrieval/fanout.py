"""Parallel retrieval fan-out (DESIGN.md §5 Phase 2).

"Three sub-agents execute the plan in parallel against their assigned indexes."
"Graceful degradation: if a source times out or errors (circuit breaker open),
record it in sources_failed and continue. A missing live-odds source is
reported; it does not abort the query." Every source runs under a bounded
per-source timeout so one slow store can't stall the whole fan-out (the SLO:
p95 < 2.5s for the full parallel fan-out).

A source whose prerequisite entity is missing (no resolved game_id for
live_odds/weather, no resolved teams for live_injury) is simply not attempted —
that's "not applicable," not a failure, so it appears in neither
sources_attempted nor sources_failed.
"""

import asyncio
from datetime import datetime

from hailmary.clients.voyage import VoyageClient
from hailmary.retrieval.live_agent import fetch_injuries, fetch_odds, fetch_weather
from hailmary.retrieval.semantic_agent import fetch_semantic
from hailmary.retrieval.stats_agent import fetch_stats
from hailmary.schemas.contracts import RetrievalPlan, RetrievedContext


async def _with_timeout(coro, timeout_seconds: float):
    return await asyncio.wait_for(coro, timeout=timeout_seconds)


async def _all_team_injuries(redis_client, team_ids: list[str], now: datetime) -> list:
    results = await asyncio.gather(*(fetch_injuries(redis_client, t, now) for t in team_ids))
    return [chunk for team_chunks in results for chunk in team_chunks]


def _build_tasks(
    plan: RetrievalPlan,
    es_client,
    qdrant_client,
    redis_client,
    voyage: VoyageClient,
    voyage_model: str,
    sport: str,
    raw_text: str,
    now: datetime,
    k_stats: int,
    k_semantic: int,
    timeout_seconds: float,
) -> dict[str, asyncio.Task]:
    sources = set(plan.target_indexes)
    game_id = plan.entities.game_id
    team_ids = plan.entities.teams

    tasks: dict[str, asyncio.Task] = {}

    if "stats_es" in sources:
        coro = fetch_stats(es_client, sport, plan.entities, plan.conditions, raw_text, k_stats, now)
        tasks["stats_es"] = asyncio.ensure_future(_with_timeout(coro, timeout_seconds))

    if "semantic_vector" in sources:
        coro = fetch_semantic(qdrant_client, voyage, voyage_model, sport, raw_text, k_semantic, now)
        tasks["semantic_vector"] = asyncio.ensure_future(_with_timeout(coro, timeout_seconds))

    if "live_odds" in sources and game_id:
        coro = fetch_odds(redis_client, game_id, now)
        tasks["live_odds"] = asyncio.ensure_future(_with_timeout(coro, timeout_seconds))

    if "live_injury" in sources and team_ids:
        coro = _all_team_injuries(redis_client, team_ids, now)
        tasks["live_injury"] = asyncio.ensure_future(_with_timeout(coro, timeout_seconds))

    if "weather" in sources and game_id:
        coro = fetch_weather(redis_client, game_id, now)
        tasks["weather"] = asyncio.ensure_future(_with_timeout(coro, timeout_seconds))

    return tasks


async def fetch_retrieved_context(
    plan: RetrievalPlan,
    es_client,
    qdrant_client,
    redis_client,
    voyage: VoyageClient,
    voyage_model: str,
    sport: str,
    raw_text: str,
    now: datetime,
    k_stats: int = 20,
    k_semantic: int = 10,
    timeout_seconds: float = 2.5,
) -> RetrievedContext:
    """Fan out to every applicable source in `plan.target_indexes` concurrently."""
    tasks = _build_tasks(
        plan,
        es_client,
        qdrant_client,
        redis_client,
        voyage,
        voyage_model,
        sport,
        raw_text,
        now,
        k_stats,
        k_semantic,
        timeout_seconds,
    )

    sources_attempted = list(tasks.keys())
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    chunks = []
    sources_failed = []
    for source_name, result in zip(sources_attempted, results, strict=True):
        if isinstance(result, BaseException):
            sources_failed.append(source_name)
        else:
            chunks.extend(result)

    return RetrievedContext(
        query_id=plan.query_id,
        chunks=chunks,
        sources_attempted=sources_attempted,
        sources_failed=sources_failed,
    )
