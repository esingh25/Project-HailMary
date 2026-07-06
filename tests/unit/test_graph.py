"""End-to-end test of the compiled LangGraph pipeline (DESIGN.md §2, §5).

This is the "first end-to-end report" milestone from PLAN.md M6 — decompose ->
retrieve -> merge -> synthesize wired through a real, compiled LangGraph
StateGraph, driven entirely by fakes at every I/O boundary (LLM, Voyage, ES,
Qdrant, Redis, Postgres). No Docker, no Anthropic key required.
"""

from datetime import UTC, datetime

import pytest

from hailmary.config import get_settings
from hailmary.graph import build_graph
from hailmary.schemas.internal import (
    ClarificationNeeded,
    DraftReportProse,
    EntityMap,
    GuardrailResult,
    PlayerAliasEntry,
    RawEntityExtraction,
)

NOW = datetime(2026, 7, 4, tzinfo=UTC)

ENTITY_MAP = EntityMap(
    team_aliases={"kc": "KC"},
    players={
        "allen": [
            PlayerAliasEntry(team_id="BUF", player_id="allen_josh", full_name="Josh Allen"),
            PlayerAliasEntry(team_id="MIN", player_id="allen_brandon", full_name="Brandon Allen"),
        ]
    },
)


class FakeLLM:
    def __init__(self, guardrail, extraction=None, draft=None):
        self._guardrail = guardrail
        self._extraction = extraction
        self._draft = draft
        self.response_models_requested: list = []

    async def complete(self, model, prompt_version, prompt, response_model=None):
        self.response_models_requested.append(response_model)
        if response_model is GuardrailResult:
            return self._guardrail
        if response_model is RawEntityExtraction:
            return self._extraction
        if response_model is DraftReportProse:
            return self._draft
        raise AssertionError(f"Unexpected response_model requested: {response_model}")


class FakeVoyage:
    async def embed_query(self, model, text):
        return [0.1, 0.2]


class FakeES:
    async def search(self, index, query, size):
        return {"hits": {"hits": []}}


class FakeQdrant:
    async def search(self, collection_name, query_vector, limit, query_filter=None):
        return []

    async def upsert(self, collection_name, points):
        pass


class FakeRedis:
    async def get(self, key):
        return None

    async def scan_iter(self, match):
        return
        yield  # pragma: no cover - makes this an async generator


class FakePG:
    def __init__(self):
        self.execute_calls: list[tuple] = []

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))

    async def fetchrow(self, query, *args):
        return None


def base_state(raw_text: str, llm: FakeLLM) -> dict:
    return {
        "query_id": "q1",
        "raw_text": raw_text,
        "season": 2026,
        "sport": "nfl",
        "entity_map": ENTITY_MAP,
        "team_ratings": {},
        "home_team_id": None,
        "llm": llm,
        "voyage": FakeVoyage(),
        "es_client": FakeES(),
        "qdrant_client": FakeQdrant(),
        "redis_client": FakeRedis(),
        "pg": FakePG(),
        "settings": get_settings(),
        "now": NOW,
    }


@pytest.mark.unit
async def test_graph_full_pipeline_produces_a_persisted_report():
    llm = FakeLLM(
        guardrail=GuardrailResult(in_scope=True),
        extraction=RawEntityExtraction(
            intent="general", team_names=[], player_names=[], week=None, season=2026, conditions=[]
        ),
        draft=DraftReportProse(
            summary="s", matchup_analysis="m", key_factors=[], line_movement="l", citations=[]
        ),
    )
    graph = build_graph()

    final_state = await graph.ainvoke(base_state("Any general football research question?", llm))

    assert final_state["status"] == "ok"
    assert final_state["plan"] is not None
    assert final_state["retrieved"] is not None
    assert final_state["merged"] is not None
    assert final_state["report"] is not None
    assert final_state["report"].responsible_gaming_notice != ""
    assert final_state["report"].replay_mode == get_settings().replay_mode


@pytest.mark.unit
async def test_graph_short_circuits_on_out_of_scope_before_retrieval():
    llm = FakeLLM(guardrail=GuardrailResult(in_scope=False, reason="not football"))
    graph = build_graph()

    final_state = await graph.ainvoke(base_state("What's the weather in Paris?", llm))

    assert final_state["status"] == "out_of_scope"
    assert final_state["out_of_scope_reason"] == "not football"
    assert "retrieved" not in final_state  # never reached Phase 2
    assert GuardrailResult in llm.response_models_requested
    assert RawEntityExtraction not in llm.response_models_requested


@pytest.mark.unit
async def test_graph_short_circuits_on_clarification_needed():
    llm = FakeLLM(
        guardrail=GuardrailResult(in_scope=True),
        extraction=RawEntityExtraction(
            intent="player_prop",
            team_names=[],
            player_names=["Allen"],
            week=None,
            season=2026,
            conditions=[],
        ),
    )
    graph = build_graph()

    final_state = await graph.ainvoke(base_state("How many yards will Allen throw for?", llm))

    assert final_state["status"] == "clarification_needed"
    assert isinstance(final_state["clarification"], ClarificationNeeded)
    assert "merged" not in final_state  # never reached Phase 3/4
