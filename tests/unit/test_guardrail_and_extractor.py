"""Tests for the Phase 1 guardrail and extraction call sites.

Uses a fake LLMClient-shaped object (same pattern as M1-M4's fake clients) —
not real cassettes, since no Anthropic key exists yet to record them against.
"""

import pytest

from hailmary.decompose.extractor import extract_entities
from hailmary.decompose.guardrail import check_in_scope
from hailmary.schemas.contracts import Condition
from hailmary.schemas.internal import GuardrailResult, RawEntityExtraction


class FakeLLMClient:
    def __init__(self, response):
        self._response = response
        self.calls: list[tuple] = []

    async def complete(self, model, prompt_version, prompt, response_model=None):
        self.calls.append((model, prompt_version, prompt, response_model))
        return self._response


@pytest.mark.unit
async def test_check_in_scope_returns_guardrail_result_for_in_scope_query():
    llm = FakeLLMClient(GuardrailResult(in_scope=True))
    result = await check_in_scope(llm, "claude-haiku-4-5", "v1", "Is there value on KC -6.5?")
    assert result.in_scope is True
    assert "Is there value on KC -6.5?" in llm.calls[0][2]


@pytest.mark.unit
async def test_check_in_scope_surfaces_out_of_scope_reason():
    llm = FakeLLMClient(GuardrailResult(in_scope=False, reason="not football-related"))
    result = await check_in_scope(llm, "claude-haiku-4-5", "v1", "What's the weather in Paris?")
    assert result.in_scope is False
    assert result.reason == "not football-related"


@pytest.mark.unit
async def test_check_in_scope_requests_the_correct_response_model():
    llm = FakeLLMClient(GuardrailResult(in_scope=True))
    await check_in_scope(llm, "claude-haiku-4-5", "v1", "query")
    assert llm.calls[0][3] is GuardrailResult


@pytest.mark.unit
async def test_extract_entities_returns_raw_extraction():
    canned = RawEntityExtraction(
        intent="spread",
        team_names=["Chiefs"],
        player_names=["Mahomes"],
        week=18,
        season=2026,
        conditions=[Condition(field="opponent_def_rank", operator="lte", value=10)],
    )
    llm = FakeLLMClient(canned)
    result = await extract_entities(
        llm,
        "claude-haiku-4-5",
        "v1",
        "Is there value on KC -6.5 vs a top-10 defense?",
        season=2026,
    )
    assert result.intent == "spread"
    assert result.team_names == ["Chiefs"]
    assert result.player_names == ["Mahomes"]
    assert result.conditions[0].field == "opponent_def_rank"


@pytest.mark.unit
async def test_extract_entities_passes_default_season_into_prompt():
    llm = FakeLLMClient(
        RawEntityExtraction(
            intent="general",
            team_names=[],
            player_names=[],
            week=None,
            season=2026,
            conditions=[],
        )
    )
    await extract_entities(llm, "claude-haiku-4-5", "v1", "query", season=2026)
    assert "2026" in llm.calls[0][2]
