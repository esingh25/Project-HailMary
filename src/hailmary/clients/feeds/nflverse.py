"""nflverse live feed via nfl_data_py (DESIGN.md §5 Phase 0) — keyless, free.

nfl_data_py is synchronous pandas; every pull runs in asyncio.to_thread and is
immediately shaped into the Phase 0 record types by pure functions (unit-tested
against captured row dicts, no network). nflverse's game_id format
(``2026_18_LV_KC``) is the same canonical format the fixture uses.
"""

import asyncio
import math
from datetime import UTC, datetime

from hailmary.ingestion.normalize import content_hash
from hailmary.schemas.contracts import InjuryRecord, StatRecord
from hailmary.schemas.internal import EntityMap, GameEntry, GameResult, PlayerAliasEntry

STAT_FIELDS = (
    "passing_yards",
    "passing_tds",
    "interceptions",
    "rushing_yards",
    "receiving_yards",
    "receptions",
)

INJURY_STATUSES = {"out", "doubtful", "questionable", "probable", "active"}


def _clean(value) -> float | int | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return value


def stat_records_from_weekly(rows: list[dict], indexed_at: datetime) -> list[StatRecord]:
    """Shape nfl_data_py import_weekly_data rows into StatRecord."""
    records = []
    for row in rows:
        fields = {name: _clean(row.get(name)) for name in STAT_FIELDS}
        fields["position"] = row.get("position")
        text_blob = (
            f"{row['player_display_name']} ({row['recent_team']}) "
            f"week {row['week']} {row['season']}: "
            + ", ".join(
                f"{v:g} {k.replace('_', ' ')}"
                for k, v in fields.items()
                if isinstance(v, (int, float))
            )
        )
        records.append(
            StatRecord(
                record_id=f"nflverse_weekly_{row['player_id']}_{row['season']}_w{row['week']:02d}",
                sport="nfl",
                season=int(row["season"]),
                week=int(row["week"]),
                team_id=row["recent_team"],
                player_id=row["player_id"],
                game_id=None,  # weekly stats aren't keyed to a game row upstream
                fields=fields,
                text_blob=text_blob,
                content_hash=content_hash(text_blob),
                indexed_at=indexed_at,
            )
        )
    return records


def game_results_from_schedule(rows: list[dict]) -> list[GameResult]:
    """Completed games only (scores present) — the Elo job's input."""
    results = []
    for row in rows:
        home_score, away_score = _clean(row.get("home_score")), _clean(row.get("away_score"))
        if home_score is None or away_score is None:
            continue
        results.append(
            GameResult(
                sport="nfl",
                home_team_id=row["home_team"],
                away_team_id=row["away_team"],
                home_score=int(home_score),
                away_score=int(away_score),
            )
        )
    return results


def game_entries_from_schedule(rows: list[dict]) -> list[GameEntry]:
    """The schedule index for EntityMap.games (Phase 1 game_id resolution)."""
    return [
        GameEntry(
            game_id=row["game_id"],
            sport="nfl",
            season=int(row["season"]),
            week=int(row["week"]),
            home_team_id=row["home_team"],
            away_team_id=row["away_team"],
        )
        for row in rows
    ]


def injury_records_from_rows(rows: list[dict]) -> list[InjuryRecord]:
    """Shape import_injuries rows; rows without a recognized report_status are
    dropped (practice-squad noise), never guessed."""
    records = []
    for row in rows:
        status = (row.get("report_status") or "").lower()
        if status not in INJURY_STATUSES or not row.get("gsis_id"):
            continue
        records.append(
            InjuryRecord(
                player_id=row["gsis_id"],
                team_id=row["team"],
                status=status,
                body_part=row.get("report_primary_injury"),
                report_date=row["date_modified"],
            )
        )
    return records


def entity_map_from_rosters(
    team_rows: list[dict], roster_rows: list[dict], schedule_rows: list[dict]
) -> EntityMap:
    """Build the canonical entity map: team aliases from team descriptions,
    player (name -> (team, id)) rows from rosters, schedule index for games."""
    team_aliases: dict[str, str] = {}
    for row in team_rows:
        abbr = row["team_abbr"]
        for alias in (abbr, row.get("team_name"), row.get("team_nick")):
            if alias:
                team_aliases[str(alias).lower()] = abbr

    players: dict[str, list[PlayerAliasEntry]] = {}
    for row in roster_rows:
        player_id, full_name, team = row.get("player_id"), row.get("player_name"), row.get("team")
        if not (player_id and full_name and team):
            continue
        entry = PlayerAliasEntry(team_id=team, player_id=player_id, full_name=full_name)
        last_name = full_name.split()[-1].lower()
        for alias in (full_name.lower(), last_name):
            existing = players.setdefault(alias, [])
            if all(e.player_id != player_id for e in existing):
                existing.append(entry)

    return EntityMap(
        team_aliases=team_aliases,
        players=players,
        games=game_entries_from_schedule(schedule_rows),
    )


class NflverseFeed:
    """Live FeedClient surface for NFL data. Odds/weather/semantic docs come
    from their own feeds — this client returns empty for those."""

    def __init__(self, season: int):
        self._season = season

    async def _rows(self, importer, *args) -> list[dict]:
        frame = await asyncio.to_thread(importer, *args)
        return frame.to_dict("records")

    async def get_stats(self, sport: str) -> list[StatRecord]:
        if sport != "nfl":
            return []
        import nfl_data_py as nfl

        rows = await self._rows(nfl.import_weekly_data, [self._season])
        return stat_records_from_weekly(rows, datetime.now(UTC))

    async def get_semantic_docs(self, sport: str) -> list:
        return []  # curated scraper owns prose docs

    async def get_odds(self, game_id: str) -> list:
        return []  # The Odds API client owns odds

    async def get_injuries(self, team_id: str) -> list[InjuryRecord]:
        import nfl_data_py as nfl

        rows = await self._rows(nfl.import_injuries, [self._season])
        return [r for r in injury_records_from_rows(rows) if r.team_id == team_id]

    async def get_weather(self, game_id: str) -> list:
        return []  # Open-Meteo client owns weather

    async def get_game_results(self, sport: str) -> list[GameResult]:
        if sport != "nfl":
            return []
        import nfl_data_py as nfl

        rows = await self._rows(nfl.import_schedules, [self._season])
        return game_results_from_schedule(rows)

    async def get_entity_map(self) -> EntityMap:
        import nfl_data_py as nfl

        teams = await self._rows(nfl.import_team_desc)
        rosters = await self._rows(nfl.import_seasonal_rosters, [self._season])
        schedule = await self._rows(nfl.import_schedules, [self._season])
        return entity_map_from_rosters(teams, rosters, schedule)
