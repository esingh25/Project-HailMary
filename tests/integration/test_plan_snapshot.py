"""Phase 1 plan snapshot: cassette-backed decomposition persisted to real Postgres
(PLAN.md M5), using the committed synthetic_v0 cassettes — no keys."""

import uuid

import pytest

from hailmary.clients.llm import LLMClient
from hailmary.decompose.plan import decompose_query
from hailmary.prompts import PROMPT_VERSION

SPREAD_QUERY = "Is there value on the Chiefs -6.5 against the Raiders?"


@pytest.mark.integration
async def test_decompose_persists_plan_with_resolved_game(stores, settings, fixture_data):
    query_id = str(uuid.uuid4())
    await stores.pg.execute(
        "INSERT INTO research_queries (query_id, user_id, session_id, raw_text, sport) "
        "VALUES ($1, $2, $3, $4, $5)",
        query_id,
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        SPREAD_QUERY,
        "nfl",
    )
    llm = LLMClient(settings, fixture_data.dir / "llm_cassettes")

    plan = await decompose_query(
        query_id,
        SPREAD_QUERY,
        2026,
        fixture_data.entity_map,
        llm,
        settings.haiku_model,
        PROMPT_VERSION,
        stores.pg,
    )

    assert plan.intent == "spread"
    assert plan.entities.teams == ["KC", "LV"]
    assert plan.entities.game_id == "2026_18_LV_KC"

    row = await stores.pg.fetchrow(
        "SELECT intent, target_indexes FROM retrieval_plans WHERE query_id = $1", query_id
    )
    assert row is not None
    assert row["intent"] == "spread"
    assert "live_odds" in row["target_indexes"]
