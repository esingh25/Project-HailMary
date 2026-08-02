"""Shared read access to the §6.4 `team_ratings` table.

Two subsystems touch these rows and neither should own the other's access:
the nightly Elo job (ingestion/ratings_job.py) *writes* them, and the query
path (delivery/routes.py -> graph -> synthesis/report.py) *reads* them to
derive model_probability for spread and moneyline markets. This module holds
the read so the query path never has to import from ingestion, and so there is
exactly one copy of the SELECT.

Reading returns only what the table actually holds. A team with no row is
absent from the mapping — callers must treat a missing rating as "unknown" and
degrade to `insufficient_data`, never as a default. Substituting a nominal
1500 makes every unrated matchup look like a coin flip plus home field, which
reads as a real edge and is not one.
"""

import asyncpg


async def load_team_ratings(pg: asyncpg.Connection, sport: str, season: int) -> dict[str, float]:
    """Return {team_id: rating} for one sport-season, empty if the job has not run."""
    rows = await pg.fetch(
        "SELECT team_id, rating FROM team_ratings WHERE sport = $1 AND season = $2",
        sport,
        season,
    )
    return {row["team_id"]: row["rating"] for row in rows}
