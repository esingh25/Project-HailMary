"""Unit tests for the M8 live-feed shapers and gating — pure functions against
captured row shapes, no network, no pandas."""

from datetime import UTC, date, datetime

import httpx
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
    """Stands in for the api_budget row, honouring the compare-and-swap guard.

    `execute` returns an asyncpg-style command tag, and the UPDATE only "lands"
    when the CAS predicate still matches — which is what makes the contention
    test below meaningful rather than decorative.
    """

    def __init__(self, calls_used: int, calls_limit: int = 500, period_start=date(2026, 7, 1)):
        self.row = {
            "source": "the_odds_api",
            "period_start": period_start,
            "calls_used": calls_used,
            "calls_limit": calls_limit,
        }
        self.updates: list[tuple] = []
        # Simulates other consumers winning the race: each entry bumps
        # calls_used just before our UPDATE is evaluated.
        self.steal_before_update = 0

    async def fetchrow(self, query, *args):
        return dict(self.row)

    async def execute(self, query, *args):
        if self.steal_before_update > 0:
            self.steal_before_update -= 1
            self.row["calls_used"] += 1

        if "calls_used = calls_used - " in query:  # refund path
            n, period_start = args
            if self.row["period_start"] == period_start and self.row["calls_used"] >= n:
                self.row["calls_used"] -= n
                self.updates.append(("refund", n))
                return "UPDATE 1"
            return "UPDATE 0"

        new_period, new_used, seen_period, seen_used = args
        if self.row["period_start"] != seen_period or self.row["calls_used"] != seen_used:
            return "UPDATE 0"  # CAS miss — someone else moved the row
        self.row["period_start"] = new_period
        self.row["calls_used"] = new_used
        self.updates.append((new_period, new_used))
        return "UPDATE 1"


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
    assert pg.row["calls_used"] == 11


@pytest.mark.unit
async def test_odds_budget_guard_retries_when_a_concurrent_consumer_wins_the_race():
    """The CAS is the whole point: a competing consumer that lands between our
    read and our write must not be overwritten. Before the guard existed, both
    callers wrote an absolute value and one increment vanished."""
    pg = FakeBudgetPG(calls_used=10)
    pg.steal_before_update = 1  # one rival consumes while we are deciding

    await _consume_budget(pg, 1, date(2026, 7, 7))

    # 10 start + 1 stolen by the rival + 1 ours == 12. A lost update would be 11.
    assert pg.row["calls_used"] == 12
    assert len(pg.updates) == 1  # only our own successful write is recorded


@pytest.mark.unit
async def test_odds_budget_guard_refuses_rather_than_overspend_under_sustained_contention():
    """If every attempt loses the CAS, refuse. Never fall through to the call."""
    pg = FakeBudgetPG(calls_used=10)
    pg.steal_before_update = 99  # rivals win every round

    with pytest.raises(OddsBudgetExceededError, match="contention"):
        await _consume_budget(pg, 1, date(2026, 7, 7))


@pytest.mark.unit
async def test_odds_budget_guard_refuses_when_the_rival_exhausts_the_cap_mid_decision():
    pg = FakeBudgetPG(calls_used=499)
    pg.steal_before_update = 1  # rival takes the last slot

    with pytest.raises(OddsBudgetExceededError):
        await _consume_budget(pg, 1, date(2026, 7, 7))
    assert pg.row["calls_used"] <= pg.row["calls_limit"]


@pytest.mark.unit
async def test_odds_budget_is_refunded_when_the_request_never_reaches_the_vendor():
    """A DNS/TLS/connection failure means the vendor never counted the call, so
    neither should we — otherwise transient faults permanently burn quota."""

    class ExplodingClient:
        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("name resolution failed")

    # fetch_odds stamps itself from the real clock, so pin the fake's period to
    # the current month — otherwise try_consume rolls the period over and the
    # before/after counts are not comparable.
    this_month = datetime.now(UTC).date().replace(day=1)
    pg = FakeBudgetPG(calls_used=10, period_start=this_month)
    settings = Settings(odds_api_enabled=True, odds_api_key="k")

    with pytest.raises(httpx.ConnectError):
        await fetch_odds("nfl", "g1", "evt1", settings, pg=pg, client=ExplodingClient())

    assert pg.row["calls_used"] == 10, "the reserved slot must be given back"
    assert ("refund", 1) in pg.updates


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
