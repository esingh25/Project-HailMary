"""Tests for Redis-backed session memory: recent turns + entity carry-forward."""

from datetime import UTC, datetime

import pytest

from hailmary.delivery.sessions import (
    append_turn,
    get_recent_turns,
    get_resolved_entities,
    store_resolved_entities,
)
from hailmary.schemas.contracts import QueryEntities, SessionTurn

NOW = datetime(2026, 7, 4, tzinfo=UTC)


class FakeRedis:
    def __init__(self):
        self.lists: dict[str, list[str]] = {}
        self.strings: dict[str, str] = {}

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    async def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start : end + 1]

    async def lrange(self, key, start, end):
        return self.lists.get(key, [])[start : end + 1]

    async def set(self, key, value):
        self.strings[key] = value

    async def get(self, key):
        return self.strings.get(key)


def make_turn(session_id="s1", text="hello", direction="inbound"):
    return SessionTurn(
        session_id=session_id,
        user_id="u1",
        direction=direction,
        text=text,
        query_id="q1",
        resolved_entities=None,
        timestamp=NOW,
    )


@pytest.mark.unit
async def test_append_and_get_recent_turns_preserves_chronological_order():
    redis_client = FakeRedis()
    await append_turn(redis_client, make_turn(text="first"))
    await append_turn(redis_client, make_turn(text="second"))

    turns = await get_recent_turns(redis_client, "s1")

    assert [t.text for t in turns] == ["first", "second"]


@pytest.mark.unit
async def test_get_recent_turns_empty_for_unknown_session():
    redis_client = FakeRedis()
    turns = await get_recent_turns(redis_client, "unknown")
    assert turns == []


@pytest.mark.unit
async def test_turns_are_trimmed_to_max():
    redis_client = FakeRedis()
    for i in range(15):
        await append_turn(redis_client, make_turn(text=f"turn{i}"))

    turns = await get_recent_turns(redis_client, "s1")

    assert len(turns) == 10
    assert turns[-1].text == "turn14"  # most recent kept


@pytest.mark.unit
async def test_store_and_get_resolved_entities_round_trips():
    redis_client = FakeRedis()
    entities = QueryEntities(
        teams=["KC"], players=["mahomes_pat"], game_id=None, week=18, season=2026
    )
    await store_resolved_entities(redis_client, "s1", entities)

    result = await get_resolved_entities(redis_client, "s1")

    assert result == entities


@pytest.mark.unit
async def test_get_resolved_entities_none_when_absent():
    redis_client = FakeRedis()
    result = await get_resolved_entities(redis_client, "unknown")
    assert result is None
