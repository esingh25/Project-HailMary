"""httpx ASGITransport tests for the FastAPI delivery routes.

Builds the app with lifespan=None and populates app.state with fakes directly
— no real ES/Qdrant/Redis/Postgres/Anthropic needed.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from hailmary.config import get_settings
from hailmary.delivery.app import create_app
from hailmary.schemas.internal import (
    DraftReportProse,
    EntityMap,
    GuardrailResult,
    PlayerAliasEntry,
    RawEntityExtraction,
)

NOW = datetime(2026, 7, 4, tzinfo=UTC)

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
    def __init__(self, guardrail, extraction=None, draft=None):
        self._guardrail = guardrail
        self._extraction = extraction
        self._draft = draft

    async def complete(self, model, prompt_version, prompt, response_model=None):
        if response_model is GuardrailResult:
            return self._guardrail
        if response_model is RawEntityExtraction:
            return self._extraction
        if response_model is DraftReportProse:
            return self._draft
        raise AssertionError("unexpected response_model")


class FakeVoyage:
    async def embed_query(self, model, text):
        return [0.1, 0.2]


class FakeES:
    async def search(self, index, query, size):
        return {"hits": {"hits": []}}


class FakeQdrant:
    async def query_points(self, collection_name, query, limit, query_filter=None):
        return SimpleNamespace(points=[])

    async def upsert(self, collection_name, points):
        pass


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

    async def scan_iter(self, match):
        return
        yield  # pragma: no cover

    async def aclose(self):
        pass


class FakePG:
    def __init__(self, team_ratings: dict[str, float] | None = None):
        self.execute_calls: list[tuple] = []
        self.fetch_calls: list[tuple] = []
        self.reports: dict[str, str] = {}
        self.team_ratings = team_ratings or {}

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))

    async def fetch(self, query, *args):
        self.fetch_calls.append((query, args))
        if "team_ratings" in query:
            return [{"team_id": t, "rating": r} for t, r in self.team_ratings.items()]
        return []

    async def fetchrow(self, query, *args):
        if "research_reports" in query:
            report_json = self.reports.get(args[0])
            return {"report": report_json} if report_json else None
        return None


def make_app(llm: FakeLLM, pg: FakePG | None = None) -> httpx.AsyncClient:
    app = create_app(lifespan_fn=None)
    app.state.settings = get_settings()
    app.state.entity_map = ENTITY_MAP
    app.state.now = NOW
    app.state.llm = llm
    app.state.voyage = FakeVoyage()
    app.state.es_client = FakeES()
    app.state.qdrant_client = FakeQdrant()
    app.state.redis_client = FakeRedis()
    app.state.pg = pg if pg is not None else FakePG()
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.unit
async def test_submit_research_happy_path_returns_report():
    llm = FakeLLM(
        guardrail=GuardrailResult(in_scope=True),
        extraction=RawEntityExtraction(
            intent="general", team_names=[], player_names=[], week=None, season=2026, conditions=[]
        ),
        draft=DraftReportProse(
            summary="s", matchup_analysis="m", key_factors=[], line_movement="l", citations=[]
        ),
    )
    async with make_app(llm) as client:
        response = await client.post(
            "/research",
            json={"user_id": "u1", "session_id": "s1", "raw_text": "General football question?"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["report"]["responsible_gaming_notice"] != ""


@pytest.mark.unit
async def test_submit_research_registers_query_row_with_uuid_identities():
    """§6.4: retrieval_plans/research_reports FK-reference research_queries, so
    the intake row must be inserted (with UUID-mapped identities) before the
    graph persists anything."""
    llm = FakeLLM(
        guardrail=GuardrailResult(in_scope=True),
        extraction=RawEntityExtraction(
            intent="general", team_names=[], player_names=[], week=None, season=2026, conditions=[]
        ),
        draft=DraftReportProse(
            summary="s", matchup_analysis="m", key_factors=[], line_movement="l", citations=[]
        ),
    )
    pg = FakePG()
    async with make_app(llm, pg=pg) as client:
        response = await client.post(
            "/research",
            json={"user_id": "local-user", "session_id": "s1", "raw_text": "General question?"},
        )

    assert response.status_code == 200
    inserts = [c for c in pg.execute_calls if "INSERT INTO research_queries" in c[0]]
    assert len(inserts) == 1
    assert pg.execute_calls[0] == inserts[0], "research_queries row must be the first write"
    _, (query_id, user_id, session_id, raw_text, sport) = inserts[0]
    assert query_id == response.json()["query_id"]
    for identity in (user_id, session_id):
        assert uuid.UUID(identity)
    assert raw_text == "General question?"
    assert sport == "nfl"


@pytest.mark.unit
async def test_submit_research_loads_team_ratings_for_the_requested_sport_and_season():
    """The edge math's only rating source is this read. Before it existed the
    route passed a hardcoded empty dict and report.py defaulted both sides to
    1500, so every home team priced out as 'value' regardless of opponent."""
    llm = FakeLLM(
        guardrail=GuardrailResult(in_scope=True),
        extraction=RawEntityExtraction(
            intent="general", team_names=[], player_names=[], week=None, season=2026, conditions=[]
        ),
        draft=DraftReportProse(
            summary="s", matchup_analysis="m", key_factors=[], line_movement="l", citations=[]
        ),
    )
    pg = FakePG(team_ratings={"KC": 1600.0, "LV": 1450.0})
    async with make_app(llm, pg=pg) as client:
        response = await client.post(
            "/research",
            json={
                "user_id": "u1",
                "session_id": "s1",
                "raw_text": "General question?",
                "sport": "nfl",
                "season": 2026,
            },
        )

    assert response.status_code == 200
    ratings_reads = [c for c in pg.fetch_calls if "team_ratings" in c[0]]
    assert len(ratings_reads) == 1, "the query path must read team_ratings exactly once"
    assert ratings_reads[0][1] == ("nfl", 2026), "must scope the read to the requested sport/season"


@pytest.mark.unit
async def test_submit_research_out_of_scope_returns_reason():
    llm = FakeLLM(guardrail=GuardrailResult(in_scope=False, reason="not football"))
    async with make_app(llm) as client:
        response = await client.post(
            "/research",
            json={"user_id": "u1", "session_id": "s1", "raw_text": "weather in Paris?"},
        )

    body = response.json()
    assert body["status"] == "out_of_scope"
    assert body["reason"] == "not football"


@pytest.mark.unit
async def test_submit_research_clarification_needed():
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
    async with make_app(llm) as client:
        response = await client.post(
            "/research",
            json={
                "user_id": "u1",
                "session_id": "s1",
                "raw_text": "How many yards will Allen throw?",
            },
        )

    body = response.json()
    assert body["status"] == "clarification_needed"
    assert set(body["clarification"]["candidate_ids"]) == {"allen_josh", "allen_brandon"}


@pytest.mark.unit
async def test_follow_up_query_inherits_entities_from_prior_turn():
    llm = FakeLLM(
        guardrail=GuardrailResult(in_scope=True),
        extraction=RawEntityExtraction(
            intent="general",
            team_names=["Chiefs"],
            player_names=["Mahomes"],
            week=18,
            season=2026,
            conditions=[],
        ),
        draft=DraftReportProse(
            summary="s", matchup_analysis="m", key_factors=[], line_movement="l", citations=[]
        ),
    )
    async with make_app(llm) as client:
        first = await client.post(
            "/research",
            json={
                "user_id": "u1",
                "session_id": "s1",
                "raw_text": "Is there value on Chiefs -6.5 with Mahomes?",
            },
        )
        assert first.json()["status"] == "ok"

        # Follow-up names no entities at all — must inherit from the prior turn.
        llm._extraction = RawEntityExtraction(
            intent="general", team_names=[], player_names=[], week=None, season=2026, conditions=[]
        )
        second = await client.post(
            "/research",
            json={
                "user_id": "u1",
                "session_id": "s1",
                "raw_text": "What about his red-zone numbers?",
            },
        )

    assert second.json()["status"] == "ok"


@pytest.mark.unit
async def test_chat_page_is_served_at_root():
    llm = FakeLLM(guardrail=GuardrailResult(in_scope=True))
    async with make_app(llm) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "HailMaryRAG" in response.text


@pytest.mark.unit
async def test_get_report_returns_404_for_unknown_query_id():
    llm = FakeLLM(guardrail=GuardrailResult(in_scope=True))
    async with make_app(llm) as client:
        response = await client.get("/report/does-not-exist")
    assert response.status_code == 404


@pytest.mark.unit
async def test_gating_enabled_blocks_the_request():
    llm = FakeLLM(guardrail=GuardrailResult(in_scope=True))
    app = create_app(lifespan_fn=None)
    app.state.settings = get_settings().model_copy(update={"gating_enabled": True})
    app.state.entity_map = ENTITY_MAP
    app.state.now = NOW
    app.state.llm = llm
    app.state.voyage = FakeVoyage()
    app.state.es_client = FakeES()
    app.state.qdrant_client = FakeQdrant()
    app.state.redis_client = FakeRedis()
    app.state.pg = FakePG()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/research", json={"user_id": "u1", "session_id": "s1", "raw_text": "query"}
        )

    assert response.status_code == 500  # gating stub raises NotImplementedError
