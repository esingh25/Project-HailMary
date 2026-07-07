"""Cross-source dedup (DESIGN.md §5 Phase 3).

"Same injury surfaced by both the live feed and a scouting doc -> keep the freshest,
highest-scored instance." Chunks are considered duplicates either by a stable
real-world identity (when structured_data carries one, e.g. an injury's player_id)
or, failing that, by normalized content text. The freshest wins, ties broken by
index_score. Pure function.

Identity-based keying matters for sources whose single "current truth" changes over
time in a way that changes the rendered text — an injury status flip
(questionable -> probable) is textually a different chunk, but it is the same
underlying fact and must collapse to one, not survive as two contradictory chunks.
Odds/weather are deliberately left on content-text fallback: distinct historical
odds snapshots are genuinely different facts (line movement), not duplicates, so
identity-keying them by (game_id, market, selection) would incorrectly collapse the
line-movement history Phase 4 needs.
"""

from hailmary.schemas.contracts import RetrievedChunk


def _identity_key(chunk: RetrievedChunk) -> str | None:
    """Stable real-world identity for sources where only the latest fact matters."""
    if chunk.source == "live_injury" and chunk.structured_data:
        player_id = chunk.structured_data.get("player_id")
        if player_id:
            return f"live_injury:{player_id}"
    return None


def _dedup_key(chunk: RetrievedChunk) -> str:
    identity = _identity_key(chunk)
    if identity is not None:
        return identity
    return " ".join(chunk.content.split()).lower()


def _is_better(candidate: RetrievedChunk, incumbent: RetrievedChunk) -> bool:
    if candidate.freshness_ts != incumbent.freshness_ts:
        return candidate.freshness_ts > incumbent.freshness_ts
    candidate_score = candidate.index_score if candidate.index_score is not None else float("-inf")
    incumbent_score = incumbent.index_score if incumbent.index_score is not None else float("-inf")
    return candidate_score > incumbent_score


def dedup(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    best_by_key: dict[str, RetrievedChunk] = {}
    order: list[str] = []

    for chunk in chunks:
        key = _dedup_key(chunk)
        existing = best_by_key.get(key)
        if existing is None:
            best_by_key[key] = chunk
            order.append(key)
        elif _is_better(chunk, existing):
            best_by_key[key] = chunk

    return [best_by_key[key] for key in order]
