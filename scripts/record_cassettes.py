"""Record real Haiku cassettes for the fixture's demo query set (DESIGN.md M5).

NOT RUNNABLE YET: requires a real ANTHROPIC_API_KEY. Written and reviewed as
part of M5, but never executed — no key was available during that build. Run
this once a key exists (with REPLAY_LLM=false), then commit the resulting
files under fixtures/synthetic_v0/llm_cassettes/ and flip REPLAY_LLM back to
true for CI/demo use.

Covers: all 6 intents, one guardrail rejection, and the planted Josh/Brandon
Allen surname collision — the same scenarios tests/unit/test_plan.py exercises
against a fake LLMClient.
"""

import asyncio
from pathlib import Path

from hailmary.clients.llm import LLMClient
from hailmary.config import get_settings
from hailmary.decompose.extractor import EXTRACTION_PROMPT_TEMPLATE
from hailmary.decompose.guardrail import GUARDRAIL_PROMPT_TEMPLATE
from hailmary.prompts import PROMPT_VERSION
from hailmary.schemas.internal import GuardrailResult, RawEntityExtraction

FIXTURES_ROOT = Path(__file__).resolve().parent.parent / "fixtures"

DEMO_QUERIES = [
    ("Is there value on the Chiefs -6.5 against the Raiders?", 2026),
    ("Will the KC vs LV game go over 47.5 points?", 2026),
    ("Are the Chiefs a good moneyline bet this week?", 2026),
    ("How many passing yards will Mahomes throw for?", 2026),
    ("Will KC win the Super Bowl this season?", 2026),
    ("What's the injury situation for the Chiefs this week?", 2026),
    ("What's the weather like in Paris today?", 2026),  # guardrail: out of scope
    ("How many yards will Allen throw for?", 2026),  # planted surname collision
]


async def record_all(llm: LLMClient, haiku_model: str) -> None:
    for query, season in DEMO_QUERIES:
        guardrail_prompt = GUARDRAIL_PROMPT_TEMPLATE.format(query=query)
        guardrail_result = await llm.complete(
            haiku_model, PROMPT_VERSION, guardrail_prompt, response_model=GuardrailResult
        )
        llm.record(
            haiku_model, PROMPT_VERSION, guardrail_prompt, guardrail_result.model_dump(mode="json")
        )
        print(f"Recorded guardrail cassette for: {query!r} -> in_scope={guardrail_result.in_scope}")

        if not guardrail_result.in_scope:
            continue

        extraction_prompt = EXTRACTION_PROMPT_TEMPLATE.format(query=query, season=season)
        extraction_result = await llm.complete(
            haiku_model, PROMPT_VERSION, extraction_prompt, response_model=RawEntityExtraction
        )
        llm.record(
            haiku_model,
            PROMPT_VERSION,
            extraction_prompt,
            extraction_result.model_dump(mode="json"),
        )
        print(f"Recorded extraction cassette for: {query!r} -> intent={extraction_result.intent}")


if __name__ == "__main__":
    settings = get_settings()
    if settings.replay_llm or not (settings.gemini_api_key or settings.anthropic_api_key):
        raise SystemExit(
            "Set REPLAY_LLM=false and a provider API key (GEMINI_API_KEY or "
            "ANTHROPIC_API_KEY) before running — this script must talk to the live "
            "API to produce real cassettes. Model ids must be provider-qualified, "
            "e.g. HAIKU_MODEL=google/gemini-2.5-flash (see docs/AMENDMENTS.md)."
        )
    cassette_dir = FIXTURES_ROOT / settings.fixture_name / "llm_cassettes"
    client = LLMClient(settings, cassette_dir)
    asyncio.run(record_all(client, settings.haiku_model))
