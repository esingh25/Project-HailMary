"""HTTP routes for Phase 5 delivery (DESIGN.md §5 Phase 5).

POST /research submits a query and runs it through the compiled graph
(Phases 1-4); GET /report/{query_id} fetches a previously generated report.
Session memory and the gating chokepoint are enforced here — Phase 5 owns
formatting/delivery, never report content (Phase 4 owns that; this module
never recomputes or rewrites anything the graph produced).
"""

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from hailmary.delivery.gating import check_gating
from hailmary.delivery.sessions import (
    append_turn,
    get_recent_turns,
    get_resolved_entities,
    store_resolved_entities,
)
from hailmary.graph import build_graph
from hailmary.schemas.contracts import SessionTurn

router = APIRouter()


class ResearchRequest(BaseModel):
    user_id: str
    session_id: str
    raw_text: str
    sport: str = "nfl"
    season: int = 2026


class ResearchResponse(BaseModel):
    status: str  # "ok" | "out_of_scope" | "clarification_needed"
    query_id: str
    report: dict | None = None
    reason: str | None = None
    clarification: dict | None = None


@router.post("/research", response_model=ResearchResponse)
async def submit_research(payload: ResearchRequest, request: Request) -> ResearchResponse:
    state = request.app.state
    check_gating(state.settings.gating_enabled, payload.user_id)

    query_id = str(uuid.uuid4())
    now = state.now or datetime.now(UTC)

    prior_entities = await get_resolved_entities(state.redis_client, payload.session_id)

    graph_state = {
        "query_id": query_id,
        "raw_text": payload.raw_text,
        "season": payload.season,
        "sport": payload.sport,
        "entity_map": state.entity_map,
        "team_ratings": {},
        "home_team_id": None,
        "prior_entities": prior_entities,
        "llm": state.llm,
        "voyage": state.voyage,
        "es_client": state.es_client,
        "qdrant_client": state.qdrant_client,
        "redis_client": state.redis_client,
        "pg": state.pg,
        "settings": state.settings,
        "now": now,
    }

    graph = build_graph()
    final_state = await graph.ainvoke(graph_state)

    await append_turn(
        state.redis_client,
        SessionTurn(
            session_id=payload.session_id,
            user_id=payload.user_id,
            direction="inbound",
            text=payload.raw_text,
            query_id=query_id,
            resolved_entities=None,
            timestamp=now,
        ),
    )

    status = final_state["status"]
    if status == "out_of_scope":
        return ResearchResponse(
            status=status, query_id=query_id, reason=final_state.get("out_of_scope_reason")
        )
    if status == "clarification_needed":
        clarification = final_state["clarification"]
        return ResearchResponse(
            status=status, query_id=query_id, clarification=clarification.model_dump()
        )

    plan = final_state["plan"]
    await store_resolved_entities(state.redis_client, payload.session_id, plan.entities)

    report = final_state["report"]
    return ResearchResponse(status="ok", query_id=query_id, report=report.model_dump(mode="json"))


@router.get("/report/{query_id}")
async def get_report(query_id: str, request: Request) -> dict:
    row = await request.app.state.pg.fetchrow(
        "SELECT report FROM research_reports WHERE query_id = $1", query_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return json.loads(row["report"])


@router.get("/session/{session_id}/turns")
async def get_session_turns(session_id: str, request: Request) -> list[dict]:
    turns = await get_recent_turns(request.app.state.redis_client, session_id)
    return [t.model_dump(mode="json") for t in turns]
