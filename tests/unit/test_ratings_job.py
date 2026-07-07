"""Tests for the nightly ratings job wiring, using the real synthetic_v0 fixture."""

from datetime import UTC, datetime

import pytest

from hailmary.clients.feeds.replay import FixtureData, ReplayFeedClient
from hailmary.config import EloConfig
from hailmary.ingestion.ratings_job import run_ratings_job

NOW = datetime(2026, 7, 4, tzinfo=UTC)


class FakePG:
    """In-memory stand-in for team_ratings, keyed (team_id, sport, season)."""

    def __init__(self):
        self.rows: dict[tuple, dict] = {}

    async def fetch(self, query, sport, season):
        return [
            {"team_id": row["team_id"], "rating": row["rating"]}
            for row in self.rows.values()
            if row["sport"] == sport and row["season"] == season
        ]

    async def execute(self, query, team_id, sport, season, rating, as_of):
        self.rows[(team_id, sport, season)] = {
            "team_id": team_id,
            "sport": sport,
            "season": season,
            "rating": rating,
            "as_of": as_of,
        }


@pytest.mark.unit
async def test_ratings_job_upserts_ratings_for_every_sport_with_games():
    fixture = FixtureData("synthetic_v0")
    feed = ReplayFeedClient(fixture)
    pg = FakePG()
    config = EloConfig(k=20.0, home_field=65.0, mov_multiplier=1.0)

    results = await run_ratings_job(feed, pg, config, season=2026, as_of=NOW)

    assert set(results.keys()) == {"nfl", "cfb"}
    # NFL fixture has KC/LV and MIN/BUF results; CFB has UGA/BAMA.
    assert {"KC", "LV", "MIN", "BUF"} <= set(results["nfl"].keys())
    assert {"UGA", "BAMA"} <= set(results["cfb"].keys())


@pytest.mark.unit
async def test_ratings_job_persists_to_pg_keyed_by_sport_and_season():
    fixture = FixtureData("synthetic_v0")
    feed = ReplayFeedClient(fixture)
    pg = FakePG()
    config = EloConfig(k=20.0, home_field=65.0, mov_multiplier=1.0)

    await run_ratings_job(feed, pg, config, season=2026, as_of=NOW)

    assert ("KC", "nfl", 2026) in pg.rows
    assert ("UGA", "cfb", 2026) in pg.rows
    # Cross-sport collision safety: no accidental single "KC"-style key clash.
    assert pg.rows[("KC", "nfl", 2026)]["sport"] == "nfl"


@pytest.mark.unit
async def test_ratings_job_rerun_updates_existing_rows_not_duplicates():
    fixture = FixtureData("synthetic_v0")
    feed = ReplayFeedClient(fixture)
    pg = FakePG()
    config = EloConfig(k=20.0, home_field=65.0, mov_multiplier=1.0)

    await run_ratings_job(feed, pg, config, season=2026, as_of=NOW)
    row_count_after_first_run = len(pg.rows)

    await run_ratings_job(feed, pg, config, season=2026, as_of=NOW)
    row_count_after_second_run = len(pg.rows)

    assert row_count_after_first_run == row_count_after_second_run
