"""Tests for Phase 1 orchestration: guardrail -> extract -> resolve -> route -> persist."""

import pytest

from hailmary.decompose.plan import OutOfScopeError, decompose_query
from hailmary.schemas.contracts import Condition
from hailmary.schemas.internal import (
    ClarificationNeeded,
    EntityMap,
    GuardrailResult,
    PlayerAliasEntry,
    RawEntityExtraction,
)

ENTITY_MAP = EntityMap(
    team_aliases={"kc": "KC", "chiefs": "KC"},
    players={
        "mahomes": [
            PlayerAliasEntry(team_id="KC", player_id="mahomes_pat", full_name="Patrick Mahomes")
        ],
        "allen": [
            PlayerAliasEntry(team_id="BUF", player_id="allen_josh", full_name="Josh Allen"),
            PlayerAliasEntry(team_id="MIN", player_id="allen_brandon", full_name="Brandon Allen"),
        ],
    },
)


class FakeLLM:
    def __init__(self, guardrail: GuardrailResult, extraction: RawEntityExtraction | None = None):
        self._guardrail = guardrail
        self._extraction = extraction
        self.calls: list = []

    async def complete(self, model, prompt_version, prompt, response_model=None):
        self.calls.append(response_model)
        if response_model is GuardrailResult:
            return self._guardrail
        return self._extraction


class FakePG:
    def __init__(self):
        self.execute_calls: list[tuple] = []

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))


@pytest.mark.unit
async def test_decompose_query_raises_on_out_of_scope():
    llm = FakeLLM(GuardrailResult(in_scope=False, reason="not football"))
    with pytest.raises(OutOfScopeError, match="not football"):
        await decompose_query(
            "q1", "what's the weather in Paris?", 2026, ENTITY_MAP, llm, "haiku", "v1", FakePG()
        )


@pytest.mark.unit
async def test_decompose_query_happy_path_persists_and_returns_plan():
    llm = FakeLLM(
        GuardrailResult(in_scope=True),
        RawEntityExtraction(
            intent="spread",
            team_names=["Chiefs"],
            player_names=["Mahomes"],
            week=18,
            season=2026,
            conditions=[Condition(field="pass_yards", operator="gt", value=250)],
        ),
    )
    pg = FakePG()

    plan = await decompose_query(
        "q1",
        "Is there value on the Chiefs -6.5 with Mahomes playing?",
        2026,
        ENTITY_MAP,
        llm,
        "haiku",
        "v1",
        pg,
    )

    assert plan.intent == "spread"
    assert plan.entities.teams == ["KC"]
    assert plan.entities.players == ["mahomes_pat"]
    assert "live_injury" in plan.target_indexes  # player named -> injury always included
    assert len(pg.execute_calls) == 1
    assert "INSERT INTO retrieval_plans" in pg.execute_calls[0][0]


@pytest.mark.unit
async def test_decompose_query_returns_clarification_on_surname_collision():
    llm = FakeLLM(
        GuardrailResult(in_scope=True),
        RawEntityExtraction(
            intent="player_prop",
            team_names=[],
            player_names=["Allen"],
            week=None,
            season=2026,
            conditions=[],
        ),
    )
    result = await decompose_query(
        "q1", "How many yards will Allen throw for?", 2026, ENTITY_MAP, llm, "haiku", "v1", FakePG()
    )
    assert isinstance(result, ClarificationNeeded)
    assert set(result.candidate_ids) == {"allen_josh", "allen_brandon"}


@pytest.mark.unit
async def test_decompose_query_drops_unresolvable_team_names_without_erroring():
    llm = FakeLLM(
        GuardrailResult(in_scope=True),
        RawEntityExtraction(
            intent="general",
            team_names=["Nonexistent Team"],
            player_names=[],
            week=None,
            season=2026,
            conditions=[],
        ),
    )
    plan = await decompose_query(
        "q1", "some general query", 2026, ENTITY_MAP, llm, "haiku", "v1", FakePG()
    )
    assert plan.entities.teams == []
