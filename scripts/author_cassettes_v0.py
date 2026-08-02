"""Author deterministic synthetic LLM/Voyage cassettes for synthetic_v0.

PLAN.md M1 defines synthetic_v0 as a hand-built fixture that *includes* LLM
cassettes, and no Anthropic/Voyage key has ever been available to record real
ones (see scripts/record_cassettes.py). This script fills that gap keylessly:
it runs the real pipeline (ingestion pass + compiled graph) against the
dockerized stores with authoring subclasses of LLMClient/VoyageClient that, on
a cassette miss, synthesize a deterministic hand-written response and record
it under the exact rendered prompt key. Re-running is idempotent — existing
cassettes are replayed, only misses are authored.

Run with the compose stack up, after migrate.py, with REPLAY_MODE=true and
REPLAY_LLM=true — then commit fixtures/synthetic_v0/llm_cassettes/.

When real keys exist, delete the directory and re-record with
scripts/record_cassettes.py (Haiku) — real cassettes are drop-in replacements.
"""

import asyncio
import re
import sys
from pathlib import Path

from author_fixture_v0 import seeded_unit_vector
from run_replay_e2e import CANNED_QUERIES, e2e_query_id, register_query

from hailmary.clients.cassette import CassetteMissError
from hailmary.clients.es import get_es_client
from hailmary.clients.feeds.replay import FixtureData
from hailmary.clients.llm import LLMClient, ResponseModel
from hailmary.clients.postgres import get_pg_connection
from hailmary.clients.qdrant import get_qdrant_client
from hailmary.clients.redis import get_redis_client
from hailmary.clients.voyage import VoyageClient
from hailmary.config import get_settings
from hailmary.graph import build_graph
from hailmary.ingestion.scheduler import run_replay_ingestion_pass
from hailmary.ratings import load_team_ratings
from hailmary.schemas.internal import DraftReportProse, GuardrailResult, RawEntityExtraction

# Hand-written Phase 1 outputs per canned query — the synthetic equivalent of
# what Haiku would return. Extraction mentions must match fixture entity_map
# aliases so deterministic resolution (decompose/resolution.py) succeeds.
CANNED_GUARDRAIL: dict[str, dict] = {
    "Is there value on the Chiefs -6.5 against the Raiders?": {
        "in_scope": True,
        "reason": None,
    },
    "How many passing yards will Mahomes throw for?": {"in_scope": True, "reason": None},
    "What's the injury situation for the Chiefs this week?": {"in_scope": True, "reason": None},
}

CANNED_EXTRACTION: dict[str, dict] = {
    "Is there value on the Chiefs -6.5 against the Raiders?": {
        "intent": "spread",
        "team_names": ["Chiefs", "Raiders"],
        "player_names": [],
        "week": None,
        "season": 2026,
        "conditions": [],
    },
    "How many passing yards will Mahomes throw for?": {
        "intent": "player_prop",
        "team_names": [],
        "player_names": ["Mahomes"],
        "week": None,
        "season": 2026,
        "conditions": [],
    },
    "What's the injury situation for the Chiefs this week?": {
        "intent": "general",
        "team_names": ["Chiefs"],
        "player_names": [],
        "week": None,
        "season": 2026,
        "conditions": [],
    },
}

_EVIDENCE_LINE = re.compile(r"^\[(?P<chunk_id>[^\]]+)\] \((?P<source>[^)]+)\) (?P<content>.*)$")
MAX_SYNTHETIC_CITATIONS = 4


def _query_from_prompt(prompt: str) -> str:
    """Both Phase 1 prompt templates end with 'Query: {query}'."""
    return prompt.rsplit("Query: ", 1)[-1].strip()


def _synthesize_draft_prose(prompt: str) -> dict:
    """Build a deterministic DraftReportProse grounded in the evidence chunks
    rendered into the writer prompt, citing real chunk_ids so the citation
    guard passes."""
    evidence = []
    for line in prompt.splitlines():
        match = _EVIDENCE_LINE.match(line)
        if match:
            evidence.append(match.groupdict())
    if not evidence:
        # No retrieved evidence: cite nothing, so the citation guard's
        # threadbare check routes report.py to its evidence-only fallback.
        return {
            "summary": "Synthetic fixture prose: no evidence chunks were retrieved.",
            "matchup_analysis": "No evidence was available to analyze.",
            "key_factors": [],
            "line_movement": "No odds evidence was retrieved for this query.",
            "citations": [],
        }

    cited = evidence[:MAX_SYNTHETIC_CITATIONS]
    citations = [
        {
            "claim": e["content"][:120],
            "chunk_id": e["chunk_id"],
            "source": e["source"],
        }
        for e in cited
    ]
    odds_lines = [e["content"] for e in evidence if e["source"] == "live_odds"]
    return {
        "summary": (
            "Synthetic fixture prose: the retrieved evidence below summarizes the "
            "matchup. Each claim cites the fixture chunk it came from."
        ),
        "matchup_analysis": " ".join(e["content"] for e in cited),
        "key_factors": [e["content"][:120] for e in cited],
        "line_movement": (
            odds_lines[0] if odds_lines else "No odds evidence was retrieved for this query."
        ),
        "citations": citations,
    }


class AuthoringLLMClient(LLMClient):
    """Replays existing cassettes; on a miss, authors a deterministic synthetic
    response and records it under the real rendered prompt's key."""

    def __init__(self, settings, cassette_dir: Path):
        super().__init__(settings, cassette_dir)
        self.authored = 0

    async def complete(
        self,
        model: str,
        prompt_version: str,
        prompt: str,
        response_model: type[ResponseModel] | None = None,
    ) -> ResponseModel | dict:
        try:
            return await super().complete(model, prompt_version, prompt, response_model)
        except CassetteMissError:
            data = self._author(prompt, response_model)
            self.record(model, prompt_version, prompt, data)
            self.authored += 1
            return response_model.model_validate(data) if response_model else data

    def _author(self, prompt: str, response_model: type | None) -> dict:
        if response_model is GuardrailResult:
            return CANNED_GUARDRAIL[_query_from_prompt(prompt)]
        if response_model is RawEntityExtraction:
            return CANNED_EXTRACTION[_query_from_prompt(prompt)]
        if response_model is DraftReportProse:
            return _synthesize_draft_prose(prompt)
        raise ValueError(f"No authoring rule for response model: {response_model!r}")


class AuthoringVoyageClient(VoyageClient):
    """Replays existing cassettes; on a miss, records the same deterministic
    seeded unit vector scheme the fixture's document embeddings use."""

    def __init__(self, settings, cassette_dir: Path):
        super().__init__(settings, cassette_dir)
        self.authored = 0

    async def embed_query(self, model: str, text: str) -> list[float]:
        try:
            return await super().embed_query(model, text)
        except CassetteMissError:
            vector = seeded_unit_vector(f"query::{model}::{text}")
            self.record(model, text, vector)
            self.authored += 1
            return vector


async def author() -> bool:
    settings = get_settings()
    if not (settings.replay_mode and settings.replay_llm):
        print("Set REPLAY_MODE=true and REPLAY_LLM=true to author cassettes.", file=sys.stderr)
        return False

    fixture = FixtureData(settings.fixture_name)
    es = get_es_client(settings)
    qdrant = get_qdrant_client(settings)
    redis_client = get_redis_client(settings)
    pg = await get_pg_connection(settings)
    cassette_dir = fixture.dir / "llm_cassettes"
    llm = AuthoringLLMClient(settings, cassette_dir)
    voyage = AuthoringVoyageClient(settings, cassette_dir)

    try:
        await run_replay_ingestion_pass(fixture, es, qdrant, redis_client, pg, settings)
        # Mirror the E2E's state exactly. Ratings do not reach any prompt — the
        # writer sees only the query and the evidence chunks — so this cannot
        # change a cassette key; it just keeps the two scripts in step.
        team_ratings = await load_team_ratings(pg, "nfl", 2026)
        graph = build_graph()

        for label, raw_text in CANNED_QUERIES:
            query_id = e2e_query_id(label)
            await register_query(pg, query_id, raw_text)
            state = {
                "query_id": query_id,
                "raw_text": raw_text,
                "season": 2026,
                "sport": "nfl",
                "entity_map": fixture.entity_map,
                "team_ratings": team_ratings,
                "home_team_id": None,
                "llm": llm,
                "voyage": voyage,
                "es_client": es,
                "qdrant_client": qdrant,
                "redis_client": redis_client,
                "pg": pg,
                "settings": settings,
                "now": fixture.virtual_clock,
            }
            final_state = await graph.ainvoke(state)
            print(f"[{label}] status={final_state.get('status')}")

        print(f"Authored {llm.authored} LLM + {voyage.authored} Voyage cassettes -> {cassette_dir}")
        return True
    finally:
        await es.close()
        await qdrant.close()
        await redis_client.aclose()
        await pg.close()


if __name__ == "__main__":
    ok = asyncio.run(author())
    sys.exit(0 if ok else 1)
