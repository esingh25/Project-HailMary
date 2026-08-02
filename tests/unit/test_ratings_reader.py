"""Tests for the shared team_ratings reader used by both the nightly Elo job
and the query path."""

import pytest

from hailmary.ratings import load_team_ratings


class FakePG:
    def __init__(self, rows):
        self._rows = rows
        self.calls: list[tuple] = []

    async def fetch(self, query, sport, season):
        self.calls.append((query, sport, season))
        return [r for r in self._rows if r["sport"] == sport and r["season"] == season]


@pytest.mark.unit
async def test_load_team_ratings_returns_a_team_id_to_rating_mapping():
    pg = FakePG(
        [
            {"team_id": "KC", "rating": 1600.0, "sport": "nfl", "season": 2026},
            {"team_id": "LV", "rating": 1450.0, "sport": "nfl", "season": 2026},
        ]
    )

    ratings = await load_team_ratings(pg, "nfl", 2026)

    assert ratings == {"KC": 1600.0, "LV": 1450.0}


@pytest.mark.unit
async def test_load_team_ratings_scopes_to_sport_and_season():
    """(team_id, sport, season) is the table's key — a bare team id like 'KC'
    is not unique across sports, and ratings do not carry across seasons."""
    pg = FakePG(
        [
            {"team_id": "KC", "rating": 1600.0, "sport": "nfl", "season": 2026},
            {"team_id": "KC", "rating": 1500.0, "sport": "cfb", "season": 2026},
            {"team_id": "KC", "rating": 1520.0, "sport": "nfl", "season": 2025},
        ]
    )

    assert await load_team_ratings(pg, "nfl", 2026) == {"KC": 1600.0}
    assert await load_team_ratings(pg, "cfb", 2026) == {"KC": 1500.0}


@pytest.mark.unit
async def test_load_team_ratings_returns_empty_when_the_job_has_not_run():
    """An empty mapping is the honest answer, and downstream it becomes
    assessment='insufficient_data' rather than a fabricated 1500-vs-1500."""
    assert await load_team_ratings(FakePG([]), "nfl", 2026) == {}
