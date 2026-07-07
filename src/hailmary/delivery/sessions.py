"""Session memory (DESIGN.md §5 Phase 5, §8 — simplified per §8).

"Last N turns held raw in Redis and injected into the next decomposition, plus
resolved QueryEntities carried forward so follow-ups inherit prior entity
resolution... Tiered mid-term summaries and long-term semantic memory are out
of scope (§14)."
"""

from hailmary.schemas.contracts import QueryEntities, SessionTurn

MAX_TURNS = 10


def _turns_key(session_id: str) -> str:
    return f"session:{session_id}:turns"


def _entities_key(session_id: str) -> str:
    return f"session:{session_id}:entities"


async def append_turn(redis_client, turn: SessionTurn) -> None:
    key = _turns_key(turn.session_id)
    await redis_client.lpush(key, turn.model_dump_json())
    await redis_client.ltrim(key, 0, MAX_TURNS - 1)


async def get_recent_turns(redis_client, session_id: str) -> list[SessionTurn]:
    """Oldest first — natural conversation order."""
    raw_turns = await redis_client.lrange(_turns_key(session_id), 0, MAX_TURNS - 1)
    turns = [SessionTurn.model_validate_json(r) for r in raw_turns]
    return list(reversed(turns))


async def store_resolved_entities(redis_client, session_id: str, entities: QueryEntities) -> None:
    await redis_client.set(_entities_key(session_id), entities.model_dump_json())


async def get_resolved_entities(redis_client, session_id: str) -> QueryEntities | None:
    raw = await redis_client.get(_entities_key(session_id))
    return QueryEntities.model_validate_json(raw) if raw else None
