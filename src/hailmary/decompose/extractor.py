"""Phase 1 entity/intent/condition extraction (DESIGN.md §5 Phase 1).

"Decompose the query into QueryEntities (teams, players, game, week, season),
intent, and a list of Conditions." The LLM extracts raw mentions only —
decompose/resolution.py and decompose/routing.py (both deterministic, M1) turn
this into canonical entity IDs and target_indexes; the LLM never does either.
"""

from hailmary.clients.llm import LLMClient
from hailmary.schemas.internal import RawEntityExtraction

EXTRACTION_PROMPT_TEMPLATE = (
    "Extract structured information from this football research query.\n\n"
    "- intent: one of spread, total, moneyline, player_prop, futures, general\n"
    "- team_names: team names or nicknames mentioned (as written, e.g. 'Chiefs')\n"
    "- player_names: player names mentioned (as written, e.g. 'Mahomes')\n"
    "- week: the NFL/CFB week number if mentioned, else null\n"
    "- season: the season year (default {season} if not stated otherwise)\n"
    "- conditions: any statistical conditions implied (e.g. 'last 3 home games', "
    "'vs top-10 defenses') as field/operator/value triples\n\n"
    "Query: {query}"
)


async def extract_entities(
    llm: LLMClient,
    model: str,
    prompt_version: str,
    raw_text: str,
    season: int,
) -> RawEntityExtraction:
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(query=raw_text, season=season)
    return await llm.complete(model, prompt_version, prompt, response_model=RawEntityExtraction)
