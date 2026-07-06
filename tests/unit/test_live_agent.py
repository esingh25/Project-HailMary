"""Tests for the live sub-agent: Redis SCAN -> RetrievedChunk mapping."""

from datetime import UTC, datetime

import pytest

from hailmary.retrieval.live_agent import fetch_injuries, fetch_odds, fetch_weather
from hailmary.schemas.contracts import InjuryRecord, OddsSnapshot
from hailmary.schemas.internal import WeatherRecord

NOW = datetime(2026, 7, 4, tzinfo=UTC)


class FakeRedis:
    def __init__(self, store: dict[str, str] | None = None):
        self.store = store or {}

    async def get(self, key):
        return self.store.get(key)

    async def scan_iter(self, match):
        prefix = match.rstrip("*")
        for key in list(self.store.keys()):
            if key.startswith(prefix):
                yield key


@pytest.mark.unit
async def test_fetch_odds_returns_all_snapshots_for_the_game():
    snap1 = OddsSnapshot(
        game_id="g1",
        book="dk",
        market="spread",
        selection="KC -6.0",
        line=-6.0,
        price=-110,
        captured_at=NOW,
    )
    snap2 = OddsSnapshot(
        game_id="g1",
        book="dk",
        market="total",
        selection="Over 47.5",
        line=47.5,
        price=-105,
        captured_at=NOW,
    )
    other_game = OddsSnapshot(
        game_id="g2",
        book="dk",
        market="spread",
        selection="BUF -3",
        line=-3.0,
        price=-110,
        captured_at=NOW,
    )
    redis_client = FakeRedis(
        {
            "odds:g1:dk:spread:KC -6.0": snap1.model_dump_json(),
            "odds:g1:dk:total:Over 47.5": snap2.model_dump_json(),
            "odds:g2:dk:spread:BUF -3": other_game.model_dump_json(),
        }
    )

    chunks = await fetch_odds(redis_client, "g1", now=NOW)

    assert len(chunks) == 2
    assert all(c.source == "live_odds" for c in chunks)
    assert {c.structured_data["selection"] for c in chunks} == {"KC -6.0", "Over 47.5"}


@pytest.mark.unit
async def test_fetch_odds_returns_empty_when_no_snapshots_cached():
    redis_client = FakeRedis({})
    chunks = await fetch_odds(redis_client, "g1", now=NOW)
    assert chunks == []


@pytest.mark.unit
async def test_fetch_injuries_scoped_to_team_not_other_rosters():
    kc_injury = InjuryRecord(
        player_id="mahomes_pat",
        team_id="KC",
        status="probable",
        body_part="ankle",
        report_date=NOW,
    )
    lv_injury = InjuryRecord(
        player_id="lv_wr1",
        team_id="LV",
        status="out",
        body_part="hamstring",
        report_date=NOW,
    )
    redis_client = FakeRedis(
        {
            "injury:KC:mahomes_pat": kc_injury.model_dump_json(),
            "injury:LV:lv_wr1": lv_injury.model_dump_json(),
        }
    )

    chunks = await fetch_injuries(redis_client, "KC", now=NOW)

    assert len(chunks) == 1
    assert chunks[0].source == "live_injury"
    assert chunks[0].structured_data["player_id"] == "mahomes_pat"


@pytest.mark.unit
async def test_fetch_weather_returns_single_chunk_when_present():
    rec = WeatherRecord(
        game_id="g1", temperature_f=31.0, wind_mph=22.0, precipitation_pct=5.0, captured_at=NOW
    )
    redis_client = FakeRedis({"weather:g1": rec.model_dump_json()})

    chunks = await fetch_weather(redis_client, "g1", now=NOW)

    assert len(chunks) == 1
    assert chunks[0].source == "weather"
    assert chunks[0].freshness_ts == NOW


@pytest.mark.unit
async def test_fetch_weather_returns_empty_for_indoor_game_with_no_cached_weather():
    redis_client = FakeRedis({})
    chunks = await fetch_weather(redis_client, "g_indoor", now=NOW)
    assert chunks == []
