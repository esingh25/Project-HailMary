"""Phase 1 orchestration: decompose a query into a persisted RetrievalPlan.

DESIGN.md §5 Phase 1: guardrail -> extract -> resolve entities deterministically
-> derive target_indexes deterministically -> persist. "No index-routing decision
delegated to the LLM" — routing.route() (M1) is the only thing that picks
target_indexes; resolution.py (M1) is the only thing that picks canonical IDs.

game_id resolution (matching entities to a specific upcoming game) needs a
schedule-lookup mechanism not yet built — DESIGN.md doesn't fully specify this
either. Left as None here; Phase 2's live sub-agents that need a game_id simply
have nothing to query in that case (fanout.py already treats a missing game_id
as "not applicable," not a failure).
"""

import json

from hailmary.clients.llm import LLMClient
from hailmary.decompose.extractor import extract_entities
from hailmary.decompose.guardrail import check_in_scope
from hailmary.decompose.resolution import resolve_player, resolve_teams
from hailmary.decompose.routing import route
from hailmary.schemas.contracts import QueryEntities, RetrievalPlan
from hailmary.schemas.internal import ClarificationNeeded, EntityMap


class OutOfScopeError(Exception):
    """Raised when the guardrail rejects a query. Phase 5 turns this into a
    polite user-facing message before any retrieval happens."""

    def __init__(self, reason: str | None):
        self.reason = reason
        super().__init__(reason or "Query is out of scope")


async def decompose_query(
    query_id: str,
    raw_text: str,
    season: int,
    entity_map: EntityMap,
    llm: LLMClient,
    haiku_model: str,
    prompt_version: str,
    pg,
    prior_entities: QueryEntities | None = None,
) -> RetrievalPlan | ClarificationNeeded:
    """`prior_entities` (DESIGN.md §8 session memory): when this turn names no
    team/player at all, inherit the prior turn's resolved entities so a
    follow-up like "what about his red-zone numbers?" still resolves — they're
    already-canonical IDs, so no re-resolution is needed for the inherited
    fields.
    """
    guardrail = await check_in_scope(llm, haiku_model, prompt_version, raw_text)
    if not guardrail.in_scope:
        raise OutOfScopeError(guardrail.reason)

    raw = await extract_entities(llm, haiku_model, prompt_version, raw_text, season)

    if not raw.team_names and prior_entities and prior_entities.teams:
        resolved_teams = prior_entities.teams
    else:
        resolved_teams = resolve_teams(raw.team_names, entity_map)

    resolved_players: list[str] = []
    if not raw.player_names and prior_entities and prior_entities.players:
        resolved_players = prior_entities.players
    else:
        team_hint = resolved_teams[0] if len(resolved_teams) == 1 else None
        for name in raw.player_names:
            resolved = resolve_player(query_id, name, entity_map, team_id_hint=team_hint)
            if isinstance(resolved, ClarificationNeeded):
                return resolved
            if resolved is not None:
                resolved_players.append(resolved)

    entities = QueryEntities(
        teams=resolved_teams,
        players=resolved_players,
        game_id=None,
        week=raw.week,
        season=raw.season,
    )
    target_indexes = route(raw.intent, entities)

    plan = RetrievalPlan(
        query_id=query_id,
        intent=raw.intent,
        entities=entities,
        conditions=raw.conditions,
        target_indexes=target_indexes,
        prompt_version=prompt_version,
    )

    await pg.execute(
        "INSERT INTO retrieval_plans "
        "(query_id, intent, entities, conditions, target_indexes, prompt_version) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        plan.query_id,
        plan.intent,
        entities.model_dump_json(),
        json.dumps([c.model_dump(mode="json") for c in plan.conditions]),
        plan.target_indexes,
        plan.prompt_version,
    )
    return plan
