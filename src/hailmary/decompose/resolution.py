"""Deterministic entity resolution against the Phase 0 canonical entity map.

DESIGN.md §5 Phase 1: "Resolve entities deterministically against the Phase 0 entity
map. On ambiguous surname collisions, return a clarification_needed signal to Phase 5
(ask the user which player) and store the partial resolution — do not guess."
"""

from hailmary.schemas.internal import ClarificationNeeded, EntityMap


def _normalize(name: str) -> str:
    return " ".join(name.split()).lower()


def resolve_team(alias: str, entity_map: EntityMap) -> str | None:
    """Resolve a team alias to a canonical team_id, or None if unknown."""
    return entity_map.team_aliases.get(_normalize(alias))


def resolve_player(
    query_id: str,
    name: str,
    entity_map: EntityMap,
    team_id_hint: str | None = None,
) -> str | ClarificationNeeded | None:
    """Resolve a player name to a canonical player_id.

    Returns:
        str: resolved player_id (unambiguous, or disambiguated by team_id_hint)
        ClarificationNeeded: multiple candidates and no team hint resolves it
        None: name not found in the entity map at all
    """
    candidates = entity_map.players.get(_normalize(name), [])

    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0].player_id

    if team_id_hint is not None:
        matching = [c for c in candidates if c.team_id == team_id_hint]
        if len(matching) == 1:
            return matching[0].player_id

    return ClarificationNeeded(
        query_id=query_id,
        ambiguous_name=name,
        candidate_ids=[c.player_id for c in candidates],
    )


def resolve_teams(teams: list[str], entity_map: EntityMap) -> list[str]:
    """Resolve a list of raw team aliases, dropping any that don't resolve."""
    resolved = (resolve_team(t, entity_map) for t in teams)
    return [t for t in resolved if t is not None]


def resolve_game(team_ids: list[str], season: int, entity_map: EntityMap) -> str | None:
    """Match exactly two resolved team_ids to the scheduled game containing both.

    Anything other than an unambiguous two-team matchup returns None — Phase 2
    already treats a missing game_id as "not applicable," not a failure.
    """
    if len(team_ids) != 2:
        return None
    matchup = set(team_ids)
    for game in entity_map.games:
        if game.season == season and {game.home_team_id, game.away_team_id} == matchup:
            return game.game_id
    return None


def home_team_for_game(game_id: str | None, entity_map: EntityMap) -> str | None:
    """Look up the home team of a resolved game, for the Elo home-field term."""
    if game_id is None:
        return None
    for game in entity_map.games:
        if game.game_id == game_id:
            return game.home_team_id
    return None
