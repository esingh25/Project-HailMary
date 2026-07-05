"""Cross-source dedup (DESIGN.md §5 Phase 3).

"Same injury surfaced by both the live feed and a scouting doc -> keep the freshest,
highest-scored instance." Chunks are considered duplicates when their normalized
content text matches; the freshest wins, ties broken by index_score. Pure function.
"""

from hailmary.schemas.contracts import RetrievedChunk


def _dedup_key(chunk: RetrievedChunk) -> str:
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
