"""Tests for FixtureData parsing and ReplayFeedClient virtual-clock filtering."""

from datetime import UTC, datetime, timedelta

import pytest

from hailmary.clients.feeds.replay import FixtureData, ReplayFeedClient


@pytest.mark.unit
async def test_replay_client_serves_real_synthetic_v0_fixture():
    fixture = FixtureData("synthetic_v0")
    client = ReplayFeedClient(fixture)

    nfl_stats = await client.get_stats("nfl")
    cfb_stats = await client.get_stats("cfb")
    assert len(nfl_stats) == 12
    assert len(cfb_stats) == 4

    kc_odds = await client.get_odds("2026_18_LV_KC")
    assert len(kc_odds) == 9

    kc_injuries = await client.get_injuries("KC")
    assert {i.status for i in kc_injuries} == {"questionable", "probable"}

    weather = await client.get_weather("2026_18_LV_KC")
    assert len(weather) == 2

    entity_map = await client.get_entity_map()
    assert len(entity_map.players["allen"]) == 2


@pytest.mark.unit
async def test_replay_client_excludes_data_captured_after_the_virtual_clock(tmp_path):
    """A live feed could never hand back a snapshot captured in the future — the
    replay client must enforce the same invariant against the fixture."""
    import hailmary.clients.feeds.replay as replay_module

    fixture_dir = tmp_path / "tiny_fixture"
    fixture_dir.mkdir()

    virtual_clock = datetime(2026, 1, 1, tzinfo=UTC)
    future_ts = virtual_clock + timedelta(days=1)
    past_ts = virtual_clock - timedelta(days=1)

    odds_records = [
        {
            "game_id": "g1",
            "book": "dk",
            "market": "spread",
            "selection": "A -3",
            "line": -3.0,
            "price": -110,
            "captured_at": past_ts.isoformat(),
        },
        {
            "game_id": "g1",
            "book": "dk",
            "market": "spread",
            "selection": "A -3.5",
            "line": -3.5,
            "price": -110,
            "captured_at": future_ts.isoformat(),
        },
    ]

    fixture = FixtureData.__new__(FixtureData)
    fixture.dir = fixture_dir
    fixture.manifest = {"fixture_name": "tiny_fixture", "virtual_clock": virtual_clock.isoformat()}
    fixture.virtual_clock = virtual_clock
    fixture.stats = []
    fixture.semantic_docs = []
    fixture.odds = [replay_module.OddsSnapshot.model_validate(r) for r in odds_records]
    fixture.injuries = []
    fixture.weather = []
    fixture.entity_map = replay_module.EntityMap.model_validate({"team_aliases": {}, "players": {}})
    fixture.embeddings = {}

    client = ReplayFeedClient(fixture)
    odds = await client.get_odds("g1")

    assert len(odds) == 1
    assert odds[0].captured_at == past_ts
