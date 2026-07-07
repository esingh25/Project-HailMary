"""Phase 1 guardrail (DESIGN.md §5 Phase 1).

"Guardrail first. A low-latency Haiku classify call rejects out-of-scope inputs
(non-football, non-research) with a polite message before any retrieval."
"""

from hailmary.clients.llm import LLMClient
from hailmary.schemas.internal import GuardrailResult

GUARDRAIL_PROMPT_TEMPLATE = (
    "You are a scope guardrail for a football research assistant. Classify "
    "whether the following user query is in-scope (a research question about "
    "NFL or College Football betting/matchup analysis — spreads, totals, "
    "moneylines, player props, injuries, weather, matchup trends) or "
    "out-of-scope (anything else, e.g. unrelated sports, general chit-chat, "
    "requests to place a bet). If out-of-scope, give a brief, polite reason.\n\n"
    "Query: {query}"
)


async def check_in_scope(
    llm: LLMClient, model: str, prompt_version: str, raw_text: str
) -> GuardrailResult:
    prompt = GUARDRAIL_PROMPT_TEMPLATE.format(query=raw_text)
    return await llm.complete(model, prompt_version, prompt, response_model=GuardrailResult)
