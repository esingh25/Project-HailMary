"""Replay-mode ingestion worker (DESIGN.md §5 Phase 0; PLAN.md M2).

`run_replay_ingestion_pass` composes one full Phase 0 pass against a loaded
fixture: index stats/semantic docs, cache + archive odds, cache injuries/weather,
run the nightly ratings job. Store clients are dependency-injected (not
constructed internally) so this orchestration is unit-testable with the same fake
clients used in tests/unit/test_indexer.py, without needing Docker.

Live-mode cadence scheduling (the per-source table in DESIGN.md §5) is deferred to
M8, once live FeedClient implementations and a real "what games are upcoming"
discovery mechanism exist. In replay mode there's nothing to schedule on an
interval — the fixture is static — so `build_scheduler` just runs the pass once.
"""

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from hailmary.clients.es import ensure_stats_indexes, get_es_client
from hailmary.clients.feeds.replay import FixtureData, ReplayFeedClient
from hailmary.clients.postgres import get_pg_connection
from hailmary.clients.qdrant import ensure_all_collections, get_qdrant_client
from hailmary.clients.redis import get_redis_client
from hailmary.config import Settings, get_settings
from hailmary.ingestion.indexer import (
    archive_odds,
    cache_injuries,
    cache_odds,
    cache_weather,
    upsert_semantic_docs,
    upsert_stats,
)
from hailmary.ingestion.ratings_job import run_ratings_job
from hailmary.obs.events import record_ingestion

SPORTS = ("nfl", "cfb")


def _teams_in_games(games: list[dict]) -> set[str]:
    teams: set[str] = set()
    for game in games:
        teams.add(game["home_team_id"])
        teams.add(game["away_team_id"])
    return teams


async def run_replay_ingestion_pass(
    fixture: FixtureData,
    es,
    qdrant,
    redis_client,
    pg,
    settings: Settings,
) -> dict[str, int]:
    """Run one full ingestion pass against `fixture`, returning a per-source count summary."""
    feed = ReplayFeedClient(fixture)
    summary: dict[str, int] = {}

    await ensure_stats_indexes(es)
    await ensure_all_collections(qdrant, vector_size=fixture.manifest["embedding_dim"])

    for sport in SPORTS:
        stats = await feed.get_stats(sport)
        count = await upsert_stats(es, stats)
        summary[f"stats_{sport}"] = count
        await record_ingestion(pg, source=f"stats_{sport}", records=count, status="ok")

        docs = await feed.get_semantic_docs(sport)
        embeddings = {d.doc_id: fixture.embeddings["vectors"][d.doc_id] for d in docs}
        count = await upsert_semantic_docs(qdrant, docs, embeddings)
        summary[f"semantic_{sport}"] = count
        await record_ingestion(pg, source=f"semantic_{sport}", records=count, status="ok")

    for game in fixture.manifest["games"]:
        game_id = game["game_id"]
        odds = await feed.get_odds(game_id)
        await cache_odds(redis_client, odds, settings.ttl, settings.replay_mode)
        archived = await archive_odds(pg, odds)
        summary[f"odds_{game_id}"] = archived
        await record_ingestion(pg, source=f"odds_{game_id}", records=archived, status="ok")

        weather = await feed.get_weather(game_id)
        await cache_weather(redis_client, weather, settings.ttl)
        summary[f"weather_{game_id}"] = len(weather)

    for team_id in _teams_in_games(fixture.manifest["games"]):
        injuries = await feed.get_injuries(team_id)
        count = await cache_injuries(redis_client, injuries, settings.ttl)
        summary[f"injuries_{team_id}"] = count

    season = fixture.manifest["games"][0]["season"]
    ratings = await run_ratings_job(
        feed, pg, settings.elo, season=season, as_of=fixture.virtual_clock
    )
    total_ratings = sum(len(r) for r in ratings.values())
    summary["ratings_updated"] = total_ratings
    await record_ingestion(pg, source="ratings_job", records=total_ratings, status="ok")

    return summary


async def _run_once(settings: Settings) -> dict[str, int]:
    fixture = FixtureData(settings.fixture_name)
    es = get_es_client(settings)
    qdrant = get_qdrant_client(settings)
    redis_client = get_redis_client(settings)
    pg = await get_pg_connection(settings)

    try:
        return await run_replay_ingestion_pass(fixture, es, qdrant, redis_client, pg, settings)
    finally:
        await es.close()
        await qdrant.close()
        await redis_client.aclose()
        await pg.close()


def build_scheduler(settings: Settings) -> AsyncIOScheduler:
    """Register the replay ingestion pass to run once, immediately, on scheduler start."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(_run_once, args=[settings], id="replay_ingestion_pass")
    return scheduler


if __name__ == "__main__":
    result = asyncio.run(_run_once(get_settings()))
    print(result)
