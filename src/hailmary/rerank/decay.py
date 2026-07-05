"""Recency-decay penalty (DESIGN.md §5 Phase 3).

"Apply the recency-decay factor after the cross-encoder, as a deterministic
multiplicative penalty in Python (exponential decay per source class; half-lives in
config), so 48-hour-old injury info outranks 3-season-old trends." Pure function.
"""

import math
from datetime import datetime, timedelta

from hailmary.config import DecayConfig
from hailmary.schemas.contracts import RetrievedChunk


def _half_life_hours(source: str, config: DecayConfig) -> float:
    mapping = {
        "live_odds": config.half_life_hours_live_odds,
        "live_injury": config.half_life_hours_injury,
        "weather": config.half_life_hours_weather,
        "stats_es": config.half_life_hours_stats,
        "semantic_vector": config.half_life_hours_recap,
    }
    if source not in mapping:
        raise ValueError(f"Unknown chunk source: {source!r}")
    return mapping[source]


def decay_factor(chunk: RetrievedChunk, now: datetime, config: DecayConfig) -> float:
    """Multiplicative penalty in (0, 1] — 1.0 for a brand-new chunk, decaying toward 0."""
    age: timedelta = max(now - chunk.freshness_ts, timedelta(0))
    age_hours = age.total_seconds() / 3600
    half_life = _half_life_hours(chunk.source, config)
    return math.exp(-age_hours / half_life)


def apply_decay(
    scored_chunks: list[tuple[RetrievedChunk, float]],
    now: datetime,
    config: DecayConfig,
) -> list[tuple[RetrievedChunk, float]]:
    """Apply decay to (chunk, rerank_score) pairs, returning (chunk, decayed_score)."""
    return [(chunk, score * decay_factor(chunk, now, config)) for chunk, score in scored_chunks]
