"""Unit tests for the M8 live-feed shapers and gating — pure functions against
captured row shapes, no network, no pandas."""

from datetime import UTC, date, datetime

import pytest

from hailmary.clients.feeds.factory import LiveFeedClient, get_feed_client
from hailmary.clients.feeds.nflverse import (
    entity_map_from_rosters,
    game_entries_from_schedule,
    game_results_from_schedule,
    injury_records_from_rows,
    stat_records_from_weekly,
)
from hailmary.clients.feeds.odds_api import (
    OddsBudgetExceededError,
    _consume_budget,
    fetch_odds,
    snapshots_from_event,
)
from hailmary.clients.feeds.open_meteo import weather_record_from_response
from hailmary.clients.feeds.replay import ReplayFeedClient
from hailmary.config import Settings

NOW = datetime(2026, 1, 4, 18, 0, tzinfo=UTC)

# Row shapes captured from real nfl_data_py 0.3.3 pulls (2024 season).
WEEKLY_ROW = {
    "player_id": "00-0033873",
    "player_display_name": "Patrick Mahomes",
    "recent_team": "KC",
    "season": 2024,
    "week": 1,
    "position": "QB",
    "passing_yards": 291.0,
    "passing_tds": 1,
    "interceptions": 0.0,
    "rushing_yards": 16.0,
    "receiving_yards": float("nan"),
    "receptions": float("nan"),
}

SCHEDULE_ROWS = [
    {
        "game_id": "2024_01_BAL_KC",
        "season": 2024,
        "week": 1,
        "home_team": "KC",
        "away_team": "BAL",
        "home_score": 27.0,
        "away_score": 20.0,
    },
    {
        "game_id": "2024_20_KC_BUF",
        "season": 2024,
        "week": 20,
        "home_team": "BUF",
        "away_team": "KC",
        "home_score": float("nan"),
        "away_score": float("nan"),
    },
]


@pytest.mark.unit
def test_stat_records_from_weekly_shapes_and_cleans_nans():
    records = stat_records_from_weekly([WEEKLY_ROW], NOW)

    assert len(records) == 1
    record = records[0]
    assert record.record_id == "nflverse_weekly_00-0033873_2024_w01"
    assert record.team_id == "KC" and record.sport == "nfl"
    assert record.fields["passing_yards"] == 291.0
    assert record.fields["receiving_yards"] is None  # NaN cleaned, never leaks
    assert "Patrick Mahomes" in record.text_blob and "291" in record.text_blob
    assert record.content_hash


@pytest.mark.unit
def test_game_results_skip_unplayed_games():
    results = game_results_from_schedule(SCHEDULE_ROWS)
    assert len(results) == 1
    assert results[0].home_team_id == "KC" and results[0].home_score == 27


@pytest.mark.unit
def test_game_entries_index_full_schedule_for_resolution():
    entries = game_entries_from_schedule(SCHEDULE_ROWS)
    assert [e.game_id for e in entries] == ["2024_01_BAL_KC", "2024_20_KC_BUF"]


@pytest.mark.unit
def test_injury_records_drop_unrecognized_statuses():
    rows = [
        {
            "gsis_id": "00-0033873",
            "team": "KC",
            "report_status": "Questionable",
            "report_primary_injury": "Ankle",
            "date_modified": NOW,
        },
        {"gsis_id": "00-0000001", "team": "KC", "report_status": None, "date_modified": NOW},
    ]
    records = injury_records_from_rows(rows)
    assert len(records) == 1
    assert records[0].status == "questionable" and records[0].body_part == "Ankle"


@pytest.mark.unit
def test_entity_map_from_rosters_builds_aliases_collisions_and_schedule():
    teams = [{"team_abbr": "KC", "team_name": "Kansas City Chiefs", "team_nick": "Chiefs"}]
    rosters = [
        {"player_id": "00-1", "player_name": "Josh Allen", "team": "BUF"},
        {"player_id": "00-2", "player_name": "Brandon Allen", "team": "MIN"},
    ]
    entity_map = entity_map_from_rosters(teams, rosters, SCHEDULE_ROWS)

    assert entity_map.team_aliases["chiefs"] == "KC"
    assert entity_map.team_aliases["kansas city chiefs"] == "KC"
    assert {e.player_id for e in entity_map.players["allen"]} == {"00-1", "00-2"}
    assert entity_map.players["josh allen"][0].player_id == "00-1"
    assert len(entity_map.games) == 2


@pytest.mark.unit
def test_weather_record_from_open_meteo_response():
    payload = {
        "current": {
            "temperature_2m": 28.4,
            "wind_speed_10m": 14.0,
            "precipitation_probability": None,
        }
    }
    record = weather_record_from_response("2026_18_LV_KC", payload, NOW)
    assert record.temperature_f == 28.4 and record.wind_mph == 14.0
    assert record.precipitation_pct == 0.0  # null probability -> 0, not a crash


@pytest.mark.unit
def test_odds_snapshots_from_event_shape_all_three_markets():
    event = {
        "bookmakers": [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Kansas City Chiefs", "price": -110, "point": -6.5},
                            {"name": "Las Vegas Raiders", "price": -110, "point": 6.5},
                        ],
                    },
                    {"key": "h2h", "outcomes": [{"name": "Kansas City Chiefs", "price": -280}]},
                    {
                        "key": "totals",
                        "outcomes": [{"name": "Over", "price": -105, "point": 47.5}],
                    },
                    {"key": "alternate_spreads", "outcomes": [{"name": "x", "price": 100}]},
                ],
            }
        ]
    }
    snapshots = snapshots_from_event(event, "2026_18_LV_KC", NOW)

    assert {s.market for s in snapshots} == {"spread", "moneyline", "total"}  # unknown skipped
    spread = next(s for s in snapshots if s.market == "spread" and s.line == -6.5)
    assert spread.selection == "Kansas City Chiefs -6.5" and spread.price == -110
    total = next(s for s in snapshots if s.market == "total")
    assert total.selection == "Over 47.5"


class FakeBudgetPG:
    def __init__(self, calls_used: int, calls_limit: int = 500):
        self.row = {
            "source": "the_odds_api",
            "period_start": date(2026, 7, 1),
            "calls_used": calls_used,
            "calls_limit": calls_limit,
        }
        self.updates: list[tuple] = []

    async def fetchrow(self, query, *args):
        return self.row

    async def execute(self, query, *args):
        self.updates.append(args)


@pytest.mark.unit
async def test_odds_budget_guard_refuses_before_any_http():
    pg = FakeBudgetPG(calls_used=500)
    with pytest.raises(OddsBudgetExceededError):
        await _consume_budget(pg, 1, date(2026, 7, 7))
    assert pg.updates == []  # refusal writes nothing


@pytest.mark.unit
async def test_odds_budget_guard_consumes_when_allowed():
    pg = FakeBudgetPG(calls_used=10)
    await _consume_budget(pg, 1, date(2026, 7, 7))
    assert pg.updates == [(date(2026, 7, 1), 11)]


@pytest.mark.unit
async def test_fetch_odds_disabled_returns_empty_without_touching_budget():
    settings = Settings(odds_api_enabled=False)
    result = await fetch_odds("nfl", "g1", "evt1", settings, pg=None, client=None)
    assert result == []


@pytest.mark.unit
def test_factory_picks_replay_or_live_from_settings():
    replay = get_feed_client(Settings(replay_mode=True), season=2026)
    assert isinstance(replay, ReplayFeedClient)

    live = get_feed_client(Settings(replay_mode=False), season=2026)
    assert isinstance(live, LiveFeedClient)
