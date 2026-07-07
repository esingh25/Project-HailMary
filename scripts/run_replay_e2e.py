"""CI-gating replay E2E smoke test (DESIGN.md M6, PLAN.md M6).

Runs the full replay-mode pipeline against real dockerized services and real
Haiku/Sonnet cassettes: load the fixture into the indexes -> run 3 canned
queries through the compiled graph -> assert report structure, citation
grounding, and replay-mode stamping. Exits non-zero on any failure — this is
what CI job 2 (.github/workflows/ci.yml) runs.

The committed cassettes under fixtures/synthetic_v0/llm_cassettes/ are
deterministic synthetic ones (scripts/author_cassettes_v0.py) — hand-built
like the rest of synthetic_v0, keyless by design. When real API keys exist,
re-record with scripts/record_cassettes.py; they are drop-in replacements.
"""

import asyncio
import sys
import uuid

from hailmary.clients.es import get_es_client
from hailmary.clients.feeds.replay import FixtureData
from hailmary.clients.llm import LLMClient
from hailmary.clients.postgres import get_pg_connection
from hailmary.clients.qdrant import get_qdrant_client
from hailmary.clients.redis import get_redis_client
from hailmary.clients.voyage import VoyageClient
from hailmary.config import get_settings
from hailmary.graph import build_graph
from hailmary.ingestion.scheduler import run_replay_ingestion_pass


# §6.4 query_id columns are UUIDs; derive them deterministically from stable
# labels so replay runs are reproducible and log lines stay readable.
def e2e_query_id(label: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"hailmary:e2e:{label}"))


E2E_USER_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "hailmary:e2e:user"))
E2E_SESSION_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "hailmary:e2e:session"))

CANNED_QUERIES = [
    ("q_spread", "Is there value on the Chiefs -6.5 against the Raiders?"),
    ("q_prop", "How many passing yards will Mahomes throw for?"),
    ("q_general", "What's the injury situation for the Chiefs this week?"),
]


async def register_query(pg, query_id: str, raw_text: str, sport: str = "nfl") -> None:
    """Insert the §6.4 research_queries system-of-record row that
    retrieval_plans and research_reports reference by foreign key."""
    await pg.execute(
        "INSERT INTO research_queries (query_id, user_id, session_id, raw_text, sport) "
        "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (query_id) DO NOTHING",
        query_id,
        E2E_USER_ID,
        E2E_SESSION_ID,
        raw_text,
        sport,
    )


async def run() -> bool:
    settings = get_settings()
    if not settings.replay_mode:
        print("REPLAY_MODE must be true for this smoke test.", file=sys.stderr)
        return False

    fixture = FixtureData(settings.fixture_name)
    es = get_es_client(settings)
    qdrant = get_qdrant_client(settings)
    redis_client = get_redis_client(settings)
    pg = await get_pg_connection(settings)
    cassette_dir = fixture.dir / "llm_cassettes"
    llm = LLMClient(settings, cassette_dir)
    voyage = VoyageClient(settings, cassette_dir)

    try:
        print("Loading fixture into indexes...")
        summary = await run_replay_ingestion_pass(fixture, es, qdrant, redis_client, pg, settings)
        print(f"Ingestion summary: {summary}")

        graph = build_graph()
        all_ok = True

        for label, raw_text in CANNED_QUERIES:
            query_id = e2e_query_id(label)
            await register_query(pg, query_id, raw_text)
            state = {
                "query_id": query_id,
                "raw_text": raw_text,
                "season": 2026,
                "sport": "nfl",
                "entity_map": fixture.entity_map,
                "team_ratings": {},
                "home_team_id": "KC",
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

            if final_state.get("status") != "ok":
                print(f"[{label}] did not reach 'ok': {final_state.get('status')}")
                all_ok = False
                continue

            report = final_state["report"]
            valid_ids = {c.chunk_id for c in final_state["merged"].ranked_chunks}
            if any(c.chunk_id not in valid_ids for c in report.citations):
                print(f"[{label}] FAILED: citation references a chunk_id not in evidence")
                all_ok = False
            if not report.responsible_gaming_notice:
                print(f"[{label}] FAILED: missing responsible_gaming_notice")
                all_ok = False
            if report.replay_mode is not True:
                print(f"[{label}] FAILED: replay_mode should be True")
                all_ok = False
            print(
                f"[{label}] OK: {len(report.citations)} citations, "
                f"{len(report.edge_analysis)} edge blocks"
            )

        return all_ok
    finally:
        await es.close()
        await qdrant.close()
        await redis_client.aclose()
        await pg.close()


if __name__ == "__main__":
    ok = asyncio.run(run())
    sys.exit(0 if ok else 1)
