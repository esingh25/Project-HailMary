"""Exhaustive routing-table tests: every intent must be mapped, entity-conditioned."""

import pytest

from hailmary.decompose.routing import BASE_ROUTING, route
from hailmary.schemas.contracts import QueryEntities

ALL_INTENTS = ["spread", "total", "moneyline", "player_prop", "futures", "general"]

NO_PLAYERS = QueryEntities(teams=["KC"], players=[], game_id=None, week=None, season=2026)
WITH_PLAYER = QueryEntities(
    teams=["KC"], players=["mahomes_pat"], game_id=None, week=None, season=2026
)


@pytest.mark.unit
def test_every_intent_has_a_base_routing_entry():
    for intent in ALL_INTENTS:
        assert intent in BASE_ROUTING


@pytest.mark.unit
@pytest.mark.parametrize("intent", ALL_INTENTS)
def test_route_never_raises_for_a_known_intent(intent):
    result = route(intent, NO_PLAYERS)
    assert isinstance(result, list)
    assert len(result) > 0


@pytest.mark.unit
def test_unknown_intent_raises():
    with pytest.raises(ValueError):
        route("not_a_real_intent", NO_PLAYERS)


@pytest.mark.unit
def test_player_prop_always_targets_stats_odds_and_injury():
    result = route("player_prop", NO_PLAYERS)
    assert set(result) >= {"stats_es", "live_odds", "live_injury"}


@pytest.mark.unit
def test_total_always_targets_stats_weather_odds_and_semantic():
    result = route("total", NO_PLAYERS)
    assert set(result) >= {"stats_es", "weather", "live_odds", "semantic_vector"}


@pytest.mark.unit
@pytest.mark.parametrize("intent", ALL_INTENTS)
def test_named_player_adds_live_injury_regardless_of_intent(intent):
    result = route(intent, WITH_PLAYER)
    assert "live_injury" in result


@pytest.mark.unit
def test_named_player_does_not_duplicate_live_injury_already_in_base():
    result = route("player_prop", WITH_PLAYER)
    assert result.count("live_injury") == 1
