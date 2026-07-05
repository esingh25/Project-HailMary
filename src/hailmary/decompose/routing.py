"""Deterministic intent -> target_indexes routing (DESIGN.md §5 Phase 1).

"Derive target_indexes deterministically from intent + entities via a routing table.
[...] The LLM does not choose indexes." Pure function, no I/O.
"""

from hailmary.schemas.contracts import QueryEntities

# Base routing per intent (DESIGN.md §5 gives player_prop and total as worked examples;
# the remaining intents are filled in per the same evidence-need logic).
BASE_ROUTING: dict[str, list[str]] = {
    "spread": ["stats_es", "live_odds", "semantic_vector"],
    "total": ["stats_es", "weather", "live_odds", "semantic_vector"],
    "moneyline": ["stats_es", "live_odds", "semantic_vector"],
    "player_prop": ["stats_es", "live_odds", "live_injury"],
    "futures": ["stats_es", "semantic_vector"],
    "general": ["stats_es", "semantic_vector"],
}


def route(intent: str, entities: QueryEntities) -> list[str]:
    """Return the target indexes for a given intent, conditioned on resolved entities.

    A named player always adds live_injury (their availability is always relevant),
    even for intents whose base routing doesn't already include it.
    """
    if intent not in BASE_ROUTING:
        raise ValueError(f"No routing entry for intent: {intent!r}")

    indexes = list(BASE_ROUTING[intent])
    if entities.players and "live_injury" not in indexes:
        indexes.append("live_injury")
    return indexes
