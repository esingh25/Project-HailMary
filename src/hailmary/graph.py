"""LangGraph wiring: Phases 1-4 as a single state graph (DESIGN.md §2, §5).

decompose -> retrieve -> merge -> synthesize, with a conditional short-circuit
after decomposition for guardrail rejection or a surname-collision
clarification — both end the graph immediately, before any retrieval happens
(DESIGN.md §5 Phase 1: "No retrieval. Phase 1 plans; Phase 2 executes.").

All dependencies (LLM/Voyage/ES/Qdrant/Redis/Postgres clients, settings, clock)
are carried in the state and dependency-injected by the caller — this is what
makes the whole graph unit-testable end-to-end with fakes, without Docker or a
real Anthropic key.
"""

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from hailmary.decompose.plan import OutOfScopeError, decompose_query
from hailmary.prompts import PROMPT_VERSION
from hailmary.rerank.merge import merge_context
from hailmary.retrieval.fanout import fetch_retrieved_context
from hailmary.schemas.internal import ClarificationNeeded
from hailmary.synthesis.report import build_report


class GraphState(TypedDict, total=False):
    query_id: str
    raw_text: str
    season: int
    sport: str
    entity_map: Any
    team_ratings: dict
    home_team_id: str | None
    llm: Any
    voyage: Any
    es_client: Any
    qdrant_client: Any
    redis_client: Any
    pg: Any
    settings: Any
    now: Any
    status: str
    plan: Any
    clarification: Any
    out_of_scope_reason: str | None
    retrieved: Any
    merged: Any
    report: Any


async def decompose_node(state: GraphState) -> dict:
    settings = state["settings"]
    try:
        result = await decompose_query(
            state["query_id"],
            state["raw_text"],
            state["season"],
            state["entity_map"],
            state["llm"],
            settings.haiku_model,
            PROMPT_VERSION,
            state["pg"],
        )
    except OutOfScopeError as exc:
        return {"status": "out_of_scope", "out_of_scope_reason": exc.reason}

    if isinstance(result, ClarificationNeeded):
        return {"status": "clarification_needed", "clarification": result}

    return {"status": "ok", "plan": result}


async def retrieve_node(state: GraphState) -> dict:
    settings = state["settings"]
    plan = state["plan"]
    retrieved = await fetch_retrieved_context(
        plan,
        state["es_client"],
        state["qdrant_client"],
        state["redis_client"],
        state["voyage"],
        settings.voyage_model,
        state["sport"],
        state["raw_text"],
        state["now"],
        k_stats=settings.retrieval.k_stats,
        k_semantic=settings.retrieval.k_semantic,
        timeout_seconds=settings.retrieval.timeout_seconds_per_source,
    )
    return {"retrieved": retrieved}


async def merge_node(state: GraphState) -> dict:
    settings = state["settings"]
    plan = state["plan"]
    merged = await merge_context(
        state["query_id"],
        state["raw_text"],
        plan.entities,
        state["retrieved"],
        state["entity_map"],
        state["qdrant_client"],
        state["pg"],
        state["redis_client"],
        state["voyage"],
        settings.voyage_model,
        settings.cache,
        settings.ttl,
        settings.decay,
        settings.retrieval,
        settings.replay_mode,
        PROMPT_VERSION,
        state["now"],
    )
    return {"merged": merged}


async def synthesize_node(state: GraphState) -> dict:
    settings = state["settings"]
    plan = state["plan"]
    report = await build_report(
        state["query_id"],
        state["raw_text"],
        plan.entities,
        state["merged"],
        state["team_ratings"],
        state["home_team_id"],
        state["llm"],
        settings.sonnet_model,
        PROMPT_VERSION,
        settings.elo,
        settings.edge,
        settings.replay_mode,
        state["retrieved"].sources_failed,
        state["now"],
        state["pg"],
    )
    return {"report": report}


def _route_after_decompose(state: GraphState) -> str:
    if state["status"] in ("out_of_scope", "clarification_needed"):
        return END
    return "retrieve"


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("decompose", decompose_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("merge", merge_node)
    graph.add_node("synthesize", synthesize_node)

    graph.set_entry_point("decompose")
    graph.add_conditional_edges(
        "decompose", _route_after_decompose, {"retrieve": "retrieve", END: END}
    )
    graph.add_edge("retrieve", "merge")
    graph.add_edge("merge", "synthesize")
    graph.add_edge("synthesize", END)

    return graph.compile()
