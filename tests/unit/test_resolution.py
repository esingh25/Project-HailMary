"""Tests for deterministic entity resolution, including the surname-collision case."""

import pytest

from hailmary.decompose.resolution import (
    home_team_for_game,
    resolve_game,
    resolve_player,
    resolve_team,
    resolve_teams,
)
from hailmary.schemas.internal import ClarificationNeeded, EntityMap, GameEntry, PlayerAliasEntry

ENTITY_MAP = EntityMap(
    team_aliases={
        "kc": "KC",
        "chiefs": "KC",
        "kansas city chiefs": "KC",
        "lv": "LV",
        "raiders": "LV",
    },
    games=[
        GameEntry(
            game_id="2026_18_LV_KC",
            sport="nfl",
            season=2026,
            week=18,
            home_team_id="KC",
            away_team_id="LV",
        ),
        GameEntry(
            game_id="2026_18_BUF_MIN",
            sport="nfl",
            season=2026,
            week=18,
            home_team_id="MIN",
            away_team_id="BUF",
        ),
    ],
    players={
        "patrick mahomes": [
            PlayerAliasEntry(team_id="KC", player_id="mahomes_pat", full_name="Patrick Mahomes")
        ],
        # Planted surname collision: two "Allen"s on different teams.
        "allen": [
            PlayerAliasEntry(team_id="BUF", player_id="allen_josh", full_name="Josh Allen"),
            PlayerAliasEntry(team_id="MIN", player_id="allen_brandon", full_name="Brandon Allen"),
        ],
    },
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "alias,expected", [("KC", "KC"), ("chiefs", "KC"), ("Kansas City Chiefs", "KC")]
)
def test_resolve_team_matches_known_aliases_case_insensitively(alias, expected):
    assert resolve_team(alias, ENTITY_MAP) == expected


@pytest.mark.unit
def test_resolve_team_returns_none_for_unknown_alias():
    assert resolve_team("not a team", ENTITY_MAP) is None


@pytest.mark.unit
def test_resolve_teams_drops_unresolvable_entries():
    result = resolve_teams(["chiefs", "not a team", "raiders"], ENTITY_MAP)
    assert result == ["KC", "LV"]


@pytest.mark.unit
def test_resolve_player_unambiguous_name():
    result = resolve_player("q1", "Patrick Mahomes", ENTITY_MAP)
    assert result == "mahomes_pat"


@pytest.mark.unit
def test_resolve_player_unknown_name_returns_none():
    result = resolve_player("q1", "Nobody Special", ENTITY_MAP)
    assert result is None


@pytest.mark.unit
def test_resolve_player_surname_collision_without_hint_needs_clarification():
    result = resolve_player("q1", "Allen", ENTITY_MAP)
    assert isinstance(result, ClarificationNeeded)
    assert result.query_id == "q1"
    assert result.ambiguous_name == "Allen"
    assert set(result.candidate_ids) == {"allen_josh", "allen_brandon"}


@pytest.mark.unit
def test_resolve_player_surname_collision_disambiguated_by_team_hint():
    result = resolve_player("q1", "Allen", ENTITY_MAP, team_id_hint="BUF")
    assert result == "allen_josh"


@pytest.mark.unit
def test_resolve_player_never_guesses_on_collision_with_wrong_team_hint():
    """A team hint that doesn't match any candidate still requires clarification —
    the system never silently guesses."""
    result = resolve_player("q1", "Allen", ENTITY_MAP, team_id_hint="KC")
    assert isinstance(result, ClarificationNeeded)


@pytest.mark.unit
def test_resolve_game_matches_two_teams_regardless_of_order():
    assert resolve_game(["KC", "LV"], 2026, ENTITY_MAP) == "2026_18_LV_KC"
    assert resolve_game(["LV", "KC"], 2026, ENTITY_MAP) == "2026_18_LV_KC"


@pytest.mark.unit
@pytest.mark.parametrize("teams", [[], ["KC"], ["KC", "LV", "BUF"]])
def test_resolve_game_requires_exactly_two_teams(teams):
    assert resolve_game(teams, 2026, ENTITY_MAP) is None


@pytest.mark.unit
def test_resolve_game_returns_none_when_no_shared_game_or_wrong_season():
    assert resolve_game(["KC", "BUF"], 2026, ENTITY_MAP) is None
    assert resolve_game(["KC", "LV"], 2025, ENTITY_MAP) is None


@pytest.mark.unit
def test_home_team_for_game_looks_up_schedule():
    assert home_team_for_game("2026_18_LV_KC", ENTITY_MAP) == "KC"
    assert home_team_for_game("unknown_game", ENTITY_MAP) is None
    assert home_team_for_game(None, ENTITY_MAP) is None
