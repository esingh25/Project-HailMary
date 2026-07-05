"""Unit tests for the freshness gate, dedup, and recency-decay pure logic."""

from datetime import UTC, datetime, timedelta

import pytest

from hailmary.config import DecayConfig, TtlConfig
from hailmary.rerank.decay import apply_decay, decay_factor
from hailmary.rerank.dedup import dedup
from hailmary.rerank.freshness import gate
from hailmary.schemas.contracts import RetrievedChunk

NOW = datetime(2026, 7, 4, 18, 0, 0, tzinfo=UTC)


def make_chunk(
    source: str,
    minutes_old: int = 0,
    content: str = "content",
    score: float = 0.5,
    structured_data: dict | None = None,
):
    return RetrievedChunk(
        chunk_id=f"{source}_{minutes_old}_{content}",
        source=source,
        content=content,
        structured_data=structured_data,
        index_score=score,
        freshness_ts=NOW - timedelta(minutes=minutes_old),
        retrieved_at=NOW,
    )


# --- freshness.gate ---------------------------------------------------------------


@pytest.mark.unit
def test_fresh_live_odds_survives_gate_in_live_mode():
    ttl = TtlConfig()
    chunk = make_chunk("live_odds", minutes_old=2)
    kept, dropped = gate([chunk], ttl, NOW, replay_mode=False)
    assert kept == [chunk]
    assert dropped == 0


@pytest.mark.unit
def test_stale_live_odds_dropped_in_live_mode():
    ttl = TtlConfig()
    chunk = make_chunk("live_odds", minutes_old=10)
    kept, dropped = gate([chunk], ttl, NOW, replay_mode=False)
    assert kept == []
    assert dropped == 1


@pytest.mark.unit
def test_replay_mode_uses_the_virtual_60_minute_odds_ttl():
    ttl = TtlConfig()
    chunk = make_chunk("live_odds", minutes_old=45)
    kept_live, dropped_live = gate([chunk], ttl, NOW, replay_mode=False)
    kept_replay, dropped_replay = gate([chunk], ttl, NOW, replay_mode=True)
    assert dropped_live == 1
    assert dropped_replay == 0
    assert kept_replay == [chunk]


@pytest.mark.unit
def test_stats_are_season_scoped_and_never_dropped():
    ttl = TtlConfig()
    ancient = make_chunk("stats_es", minutes_old=60 * 24 * 365)
    kept, dropped = gate([ancient], ttl, NOW, replay_mode=False)
    assert kept == [ancient]
    assert dropped == 0


@pytest.mark.unit
def test_injury_ttl_class():
    ttl = TtlConfig()
    fresh = make_chunk("live_injury", minutes_old=10)
    stale = make_chunk("live_injury", minutes_old=45)
    kept, dropped = gate([fresh, stale], ttl, NOW, replay_mode=False)
    assert kept == [fresh]
    assert dropped == 1


# --- dedup -------------------------------------------------------------------------


@pytest.mark.unit
def test_dedup_keeps_freshest_of_duplicate_content():
    older = make_chunk("live_injury", minutes_old=60, content="Mahomes questionable ankle")
    newer = make_chunk("semantic_vector", minutes_old=5, content="Mahomes questionable ankle")
    result = dedup([older, newer])
    assert result == [newer]


@pytest.mark.unit
def test_dedup_tie_breaks_on_index_score():
    same_age_low = make_chunk("live_injury", minutes_old=10, content="same text", score=0.3)
    same_age_high = make_chunk("semantic_vector", minutes_old=10, content="same text", score=0.9)
    result = dedup([same_age_low, same_age_high])
    assert result == [same_age_high]


@pytest.mark.unit
def test_dedup_preserves_distinct_content():
    a = make_chunk("stats_es", content="KC passing stats")
    b = make_chunk("stats_es", content="LV rushing stats")
    result = dedup([a, b])
    assert {c.chunk_id for c in result} == {a.chunk_id, b.chunk_id}


@pytest.mark.unit
def test_dedup_collapses_an_injury_status_flip_to_the_latest_status():
    """Regression for the HIGH review finding: a status change (questionable ->
    probable) produces different content text, so text-based dedup alone would
    wrongly keep both as contradictory evidence. Identity keying on player_id
    (from structured_data) must collapse them to the single freshest status."""
    older_status = make_chunk(
        "live_injury",
        minutes_old=60 * 48,
        content="Mahomes is questionable with an ankle injury",
        structured_data={"player_id": "mahomes_pat", "status": "questionable"},
    )
    newer_status = make_chunk(
        "live_injury",
        minutes_old=60 * 24,
        content="Mahomes is probable with an ankle injury",
        structured_data={"player_id": "mahomes_pat", "status": "probable"},
    )
    result = dedup([older_status, newer_status])
    assert result == [newer_status]


@pytest.mark.unit
def test_dedup_does_not_collapse_distinct_players_sharing_a_source():
    a = make_chunk(
        "live_injury", content="A is questionable", structured_data={"player_id": "player_a"}
    )
    b = make_chunk(
        "live_injury", content="B is questionable", structured_data={"player_id": "player_b"}
    )
    result = dedup([a, b])
    assert {c.chunk_id for c in result} == {a.chunk_id, b.chunk_id}


@pytest.mark.unit
def test_dedup_does_not_collapse_distinct_odds_snapshots_by_identity():
    """Odds line-movement history must survive dedup even though every snapshot
    for a game/market/selection shares the same natural key — only injuries use
    identity-based keying."""
    opening = make_chunk(
        "live_odds",
        minutes_old=60 * 4,
        content="KC -6.0 opened at -110",
        structured_data={"game_id": "g1", "market": "spread", "selection": "KC -6.0"},
    )
    current = make_chunk(
        "live_odds",
        minutes_old=0,
        content="KC -6.5 currently at -108",
        structured_data={"game_id": "g1", "market": "spread", "selection": "KC -6.5"},
    )
    result = dedup([opening, current])
    assert {c.chunk_id for c in result} == {opening.chunk_id, current.chunk_id}


# --- decay ---------------------------------------------------------------------


@pytest.mark.unit
def test_decay_factor_is_one_for_brand_new_chunk():
    config = DecayConfig()
    chunk = make_chunk("live_injury", minutes_old=0)
    assert decay_factor(chunk, NOW, config) == pytest.approx(1.0)


@pytest.mark.unit
def test_decay_factor_shrinks_with_age():
    config = DecayConfig()
    fresh = make_chunk("live_injury", minutes_old=1)
    old = make_chunk("live_injury", minutes_old=60 * 48)
    assert decay_factor(old, NOW, config) < decay_factor(fresh, NOW, config)


@pytest.mark.unit
def test_recent_injury_outranks_old_stats_after_decay():
    """The doc's worked example: 48h-old injury info outranks 3-season-old trends."""
    config = DecayConfig()
    injury_48h = make_chunk("live_injury", minutes_old=60 * 48, score=0.6)
    stats_3_seasons = make_chunk("stats_es", minutes_old=60 * 24 * 365 * 3, score=0.6)

    decayed = apply_decay([(injury_48h, 0.6), (stats_3_seasons, 0.6)], NOW, config)
    scores = {chunk.source: score for chunk, score in decayed}
    assert scores["live_injury"] > scores["stats_es"]
