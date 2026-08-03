"""CollegeFootballData.com live feed (DESIGN.md §5 Phase 0) — free key required.

Inert without CFBD_API_KEY: pulls return [] so a keyless environment degrades
the same way a downed source does, instead of erroring.
"""

from datetime import UTC, datetime

import httpx

from hailmary.config import Settings
from hailmary.ingestion.normalize import content_hash
from hailmary.schemas.contracts import StatRecord
from hailmary.schemas.internal import GameResult

API_ROOT = "https://api.collegefootballdata.com"


def stat_records_from_team_games(rows: list[dict], indexed_at: datetime) -> list[StatRecord]:
    """Shape /games/teams team-game stat rows into StatRecord."""
    records = []
    for row in rows:
        team = row["team"]
        fields = {s["category"]: s["stat"] for s in row.get("stats", [])}
        text_blob = f"{team} week {row['week']} {row['season']}: " + ", ".join(
            f"{v} {k}" for k, v in fields.items()
        )
        records.append(
            StatRecord(
                record_id=f"cfbd_team_{team}_{row['season']}_w{row['week']:02d}",
                sport="cfb",
                season=int(row["season"]),
                week=int(row["week"]),
                team_id=team,
                player_id=None,
                game_id=str(row.get("game_id")) if row.get("game_id") else None,
                fields=fields,
                text_blob=text_blob,
                content_hash=content_hash(text_blob),
                indexed_at=indexed_at,
            )
        )
    return records


def game_results_from_games(rows: list[dict]) -> list[GameResult]:
    results = []
    for row in rows:
        if row.get("homePoints") is None or row.get("awayPoints") is None:
            continue
        results.append(
            GameResult(
                sport="cfb",
                home_team_id=row["homeTeam"],
                away_team_id=row["awayTeam"],
                home_score=int(row["homePoints"]),
                away_score=int(row["awayPoints"]),
            )
        )
    return results


class CfbdFeed:
    def __init__(self, settings: Settings, season: int, client: httpx.AsyncClient):
        self._key = settings.cfbd_api_key
        self._season = season
        self._client = client

    async def _get(self, path: str, params: dict) -> list[dict]:
        if not self._key:
            return []
        response = await self._client.get(
            f"{API_ROOT}{path}",
            params=params,
            headers={"Authorization": f"Bearer {self._key}"},
            timeout=15.0,
        )
        response.raise_for_status()
        return response.json()

    async def get_stats(self, sport: str) -> list[StatRecord]:
        if sport != "cfb":
            return []
        rows = await self._get("/games/teams", {"year": self._season, "seasonType": "regular"})
        return stat_records_from_team_games(rows, datetime.now(UTC))

    async def get_game_results(self, sport: str) -> list[GameResult]:
        if sport != "cfb":
            return []
        rows = await self._get("/games", {"year": self._season, "seasonType": "regular"})
        return game_results_from_games(rows)
