"""Nightly Elo ratings job (DESIGN.md §5 Phase 0, §13 Decision Log #8).

Reads completed game results per sport via a FeedClient, applies the pure Elo
update (ingestion/elo.py), and upserts the resulting ratings to Postgres
team_ratings — run once per sport, since ratings.update() rejects mixed-sport
batches and the table's key is (team_id, sport, season).
"""

from datetime import datetime

import asyncpg

from hailmary.clients.feeds.base import FeedClient
from hailmary.config import EloConfig
from hailmary.ingestion.elo import update
from hailmary.ratings import load_team_ratings

SUPPORTED_SPORTS = ("nfl", "cfb")


async def _upsert_ratings(
    pg: asyncpg.Connection,
    sport: str,
    season: int,
    ratings: dict[str, float],
    as_of: datetime,
) -> None:
    for team_id, rating in ratings.items():
        await pg.execute(
            """
            INSERT INTO team_ratings (team_id, sport, season, rating, as_of)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (team_id, sport, season) DO UPDATE
            SET rating = EXCLUDED.rating, as_of = EXCLUDED.as_of
            """,
            team_id,
            sport,
            season,
            rating,
            as_of,
        )


async def run_ratings_job(
    feed: FeedClient,
    pg: asyncpg.Connection,
    config: EloConfig,
    season: int,
    as_of: datetime,
) -> dict[str, dict[str, float]]:
    """Run the nightly Elo job for every supported sport, upserting team_ratings.

    Returns the updated ratings per sport (for logging/testing). A sport with no
    completed games this run is skipped entirely — nothing to update.
    """
    results: dict[str, dict[str, float]] = {}
    for sport in SUPPORTED_SPORTS:
        game_results = await feed.get_game_results(sport)
        if not game_results:
            continue
        current = await load_team_ratings(pg, sport, season)
        updated = update(current, game_results, config)
        await _upsert_ratings(pg, sport, season, updated, as_of)
        results[sport] = updated
    return results
