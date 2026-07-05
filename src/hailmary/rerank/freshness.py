"""Freshness gate (DESIGN.md §5 Phase 3, §9 Decision Log #9).

"Drop chunks whose freshness_ts exceeds the per-source TTL." Odds and injuries decay
in minutes; stats are season-scoped (never dropped here); semantic docs use the
recap TTL. Pure function driven by an injected Clock, so it's fully unit-testable
with a VirtualClock and exercises real logic in replay mode too.
"""

from datetime import datetime, timedelta

from hailmary.config import TtlConfig
from hailmary.schemas.contracts import RetrievedChunk


def _ttl_for_source(source: str, ttl: TtlConfig, replay_mode: bool) -> timedelta | None:
    if source == "live_odds":
        minutes = ttl.odds_minutes_replay if replay_mode else ttl.odds_minutes_live
        return timedelta(minutes=minutes)
    if source == "live_injury":
        return timedelta(minutes=ttl.injuries_minutes)
    if source == "weather":
        return timedelta(hours=ttl.weather_hours)
    if source == "semantic_vector":
        return timedelta(days=ttl.recaps_days)
    if source == "stats_es":
        return None  # season-scoped: never dropped by the freshness gate
    raise ValueError(f"Unknown chunk source: {source!r}")


def gate(
    chunks: list[RetrievedChunk],
    ttl: TtlConfig,
    now: datetime,
    replay_mode: bool = False,
) -> tuple[list[RetrievedChunk], int]:
    """Return (kept_chunks, dropped_count)."""
    kept: list[RetrievedChunk] = []
    dropped = 0

    for chunk in chunks:
        max_age = _ttl_for_source(chunk.source, ttl, replay_mode)
        if max_age is None:
            kept.append(chunk)
            continue

        age = now - chunk.freshness_ts
        if age <= max_age:
            kept.append(chunk)
        else:
            dropped += 1

    return kept, dropped
