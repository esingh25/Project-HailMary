"""JSON round-trip tests for every inter-phase contract (DESIGN.md §4)."""

from datetime import UTC, datetime

import pytest

from hailmary.schemas.contracts import (
    Citation,
    Condition,
    EdgeAnalysis,
    InjuryRecord,
    MergedContext,
    OddsSnapshot,
    QueryEntities,
    ResearchQuery,
    ResearchReport,
    RetrievalPlan,
    RetrievedChunk,
    RetrievedContext,
    SemanticDoc,
    SessionTurn,
    StatRecord,
    TeamRating,
)

NOW = datetime(2026, 7, 4, 18, 0, 0, tzinfo=UTC)

QUERY_ENTITIES = QueryEntities(
    teams=["KC", "LV"], players=["mahomes_pat"], game_id="2026_18_KC_LV", week=18, season=2026
)

RETRIEVED_CHUNK = RetrievedChunk(
    chunk_id="chunk_001",
    source="live_odds",
    content="KC -6.5 opened at -6.0",
    structured_data={"line": -6.5},
    index_score=0.91,
    freshness_ts=NOW,
    retrieved_at=NOW,
)

INSTANCES = [
    ResearchQuery(
        query_id="q1",
        user_id="u1",
        session_id="s1",
        raw_text="Is there value on KC -6.5?",
        sport="nfl",
        received_at=NOW,
    ),
    QUERY_ENTITIES,
    Condition(field="pass_yards", operator="gt", value=250),
    RetrievalPlan(
        query_id="q1",
        intent="spread",
        entities=QUERY_ENTITIES,
        conditions=[Condition(field="opponent_def_rank", operator="lte", value=10)],
        target_indexes=["stats_es", "live_odds"],
        prompt_version="v1",
    ),
    StatRecord(
        record_id="rec1",
        sport="nfl",
        season=2026,
        week=18,
        team_id="KC",
        player_id="mahomes_pat",
        game_id="2026_18_KC_LV",
        fields={"passYards": 300},
        text_blob="Mahomes threw for 300 yards",
        content_hash="abc123",
        indexed_at=NOW,
    ),
    SemanticDoc(
        doc_id="doc1",
        sport="nfl",
        doc_type="game_recap",
        text="KC dominated on Thursday night",
        embedding_model="voyage-3",
        source="curated_scrape",
        published_at=NOW,
        content_hash="def456",
    ),
    OddsSnapshot(
        game_id="2026_18_KC_LV",
        book="draftkings",
        market="spread",
        selection="KC -6.5",
        line=-6.5,
        price=-110,
        captured_at=NOW,
    ),
    InjuryRecord(
        player_id="mahomes_pat",
        team_id="KC",
        status="questionable",
        body_part="ankle",
        report_date=NOW,
    ),
    TeamRating(team_id="KC", sport="nfl", season=2026, rating=1650.5, as_of=NOW),
    RETRIEVED_CHUNK,
    RetrievedContext(
        query_id="q1",
        chunks=[RETRIEVED_CHUNK],
        sources_attempted=["live_odds", "stats_es"],
        sources_failed=["semantic_vector"],
    ),
    MergedContext(
        query_id="q1",
        ranked_chunks=[RETRIEVED_CHUNK],
        cache_hit=False,
        dropped_stale=2,
        rerank_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
    ),
    EdgeAnalysis(
        market="spread",
        selection="KC -6.5",
        american_odds=-110,
        implied_probability=0.5238,
        model_probability=0.58,
        expected_value_pct=10.75,
        assessment="value",
    ),
    Citation(
        claim="Mahomes is questionable with an ankle injury",
        chunk_id="chunk_001",
        source="live_injury",
    ),
    ResearchReport(
        query_id="q1",
        summary="KC is favored at home.",
        matchup_analysis="KC's offense vs LV's defense.",
        key_factors=["Mahomes questionable (ankle)"],
        line_movement="Opened -6.0, now -6.5",
        edge_analysis=[
            EdgeAnalysis(
                market="spread",
                selection="KC -6.5",
                american_odds=-110,
                implied_probability=0.5238,
                model_probability=0.58,
                expected_value_pct=10.75,
                assessment="value",
            )
        ],
        citations=[Citation(claim="Line moved to -6.5", chunk_id="chunk_001", source="live_odds")],
        line_as_of=NOW,
        sources_unavailable=[],
        responsible_gaming_notice="This is research, not financial advice. 1-800-GAMBLER.",
        replay_mode=True,
        generated_at=NOW,
        model_version="claude-sonnet-4-6",
        prompt_version="v1",
    ),
    SessionTurn(
        session_id="s1",
        user_id="u1",
        direction="inbound",
        text="Is there value on KC -6.5?",
        query_id="q1",
        resolved_entities=QUERY_ENTITIES,
        timestamp=NOW,
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize("instance", INSTANCES, ids=lambda i: type(i).__name__)
def test_contract_round_trips_through_json(instance):
    model_cls = type(instance)
    restored = model_cls.model_validate_json(instance.model_dump_json())
    assert restored == instance
