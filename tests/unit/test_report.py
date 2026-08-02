"""Tests for the Phase 4 report orchestration: edge math, citation guard,
regeneration, and evidence-only fallback."""

from datetime import UTC, datetime, timedelta

import pytest

from hailmary.config import EdgeConfig, EloConfig
from hailmary.schemas.contracts import Citation, MergedContext, QueryEntities, RetrievedChunk
from hailmary.schemas.internal import DraftReportProse
from hailmary.synthesis.report import build_report

NOW = datetime(2026, 7, 4, tzinfo=UTC)


class FakeLLM:
    def __init__(self, drafts: list[DraftReportProse]):
        self._drafts = iter(drafts)
        self.call_count = 0

    async def complete(self, model, prompt_version, prompt, response_model=None):
        self.call_count += 1
        return next(self._drafts)


class FakePG:
    def __init__(self):
        self.execute_calls: list[tuple] = []

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))


def make_odds_chunk(chunk_id="odds1", price=-110, minutes_old=0):
    return RetrievedChunk(
        chunk_id=chunk_id,
        source="live_odds",
        content="KC -6.5 at -110",
        structured_data={
            "game_id": "g1",
            "book": "dk",
            "market": "spread",
            "selection": "KC -6.5",
            "line": -6.5,
            "price": price,
            "captured_at": (NOW - timedelta(minutes=minutes_old)).isoformat(),
        },
        index_score=None,
        freshness_ts=NOW - timedelta(minutes=minutes_old),
        retrieved_at=NOW,
    )


def make_stat_chunk(chunk_id="stat1"):
    return RetrievedChunk(
        chunk_id=chunk_id,
        source="stats_es",
        content="KC averages 28 points per game",
        structured_data=None,
        index_score=0.9,
        freshness_ts=NOW,
        retrieved_at=NOW,
    )


@pytest.mark.unit
async def test_build_report_happy_path_computes_edge_and_grounds_citations():
    entities = QueryEntities(teams=["KC", "LV"], players=[], game_id="g1", week=18, season=2026)
    merged = MergedContext(
        query_id="q1",
        ranked_chunks=[make_odds_chunk(), make_stat_chunk()],
        cache_hit=False,
        dropped_stale=0,
        rerank_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
    )
    draft = DraftReportProse(
        summary="KC is favored at home.",
        matchup_analysis="KC's offense is strong.",
        key_factors=["KC averages 28 points"],
        line_movement="KC -6.5 at -110",
        citations=[
            Citation(claim="KC averages 28 points", chunk_id="stat1", source="stats_es"),
            Citation(claim="line is -6.5", chunk_id="odds1", source="live_odds"),
        ],
    )
    llm = FakeLLM([draft])
    pg = FakePG()

    report = await build_report(
        "q1",
        "Is there value on KC -6.5?",
        entities,
        merged,
        team_ratings={"KC": 1600.0, "LV": 1450.0},
        home_team_id="KC",
        llm=llm,
        sonnet_model="claude-sonnet-4-6",
        prompt_version="v1",
        elo_config=EloConfig(),
        edge_config=EdgeConfig(),
        replay_mode=True,
        sources_unavailable=[],
        now=NOW,
        pg=pg,
    )

    assert len(report.edge_analysis) == 1
    assert report.edge_analysis[0].model_probability is not None
    assert report.edge_analysis[0].assessment != "insufficient_data"
    assert len(report.citations) == 2
    assert report.responsible_gaming_notice != ""
    assert report.replay_mode is True
    assert len(pg.execute_calls) == 1


@pytest.mark.unit
async def test_build_report_strips_hallucinated_citation():
    entities = QueryEntities(teams=[], players=[], game_id=None, week=None, season=2026)
    merged = MergedContext(
        query_id="q1",
        ranked_chunks=[make_stat_chunk(), make_stat_chunk("stat2")],
        cache_hit=False,
        dropped_stale=0,
        rerank_model="m",
    )
    draft = DraftReportProse(
        summary="s",
        matchup_analysis="m",
        key_factors=[],
        line_movement="l",
        citations=[
            Citation(claim="a", chunk_id="stat1", source="stats_es"),
            Citation(claim="b", chunk_id="stat2", source="stats_es"),
            Citation(claim="hallucinated", chunk_id="does_not_exist", source="stats_es"),
        ],
    )
    llm = FakeLLM([draft])

    report = await build_report(
        "q1",
        "query",
        entities,
        merged,
        team_ratings={},
        home_team_id=None,
        llm=llm,
        sonnet_model="claude-sonnet-4-6",
        prompt_version="v1",
        elo_config=EloConfig(),
        edge_config=EdgeConfig(),
        replay_mode=True,
        sources_unavailable=[],
        now=NOW,
    )

    assert len(report.citations) == 2
    assert all(c.chunk_id != "does_not_exist" for c in report.citations)


@pytest.mark.unit
async def test_build_report_regenerates_when_threadbare_then_succeeds():
    entities = QueryEntities(teams=[], players=[], game_id=None, week=None, season=2026)
    merged = MergedContext(
        query_id="q1",
        ranked_chunks=[make_stat_chunk(), make_stat_chunk("stat2")],
        cache_hit=False,
        dropped_stale=0,
        rerank_model="m",
    )
    threadbare_draft = DraftReportProse(
        summary="s",
        matchup_analysis="m",
        key_factors=[],
        line_movement="l",
        citations=[Citation(claim="a", chunk_id="does_not_exist", source="stats_es")],
    )
    good_draft = DraftReportProse(
        summary="s2",
        matchup_analysis="m2",
        key_factors=[],
        line_movement="l2",
        citations=[
            Citation(claim="a", chunk_id="stat1", source="stats_es"),
            Citation(claim="b", chunk_id="stat2", source="stats_es"),
        ],
    )
    llm = FakeLLM([threadbare_draft, good_draft])

    report = await build_report(
        "q1",
        "query",
        entities,
        merged,
        team_ratings={},
        home_team_id=None,
        llm=llm,
        sonnet_model="claude-sonnet-4-6",
        prompt_version="v1",
        elo_config=EloConfig(),
        edge_config=EdgeConfig(),
        replay_mode=True,
        sources_unavailable=[],
        now=NOW,
    )

    assert llm.call_count == 2
    assert report.summary == "s2"


@pytest.mark.unit
async def test_build_report_falls_back_to_evidence_only_after_max_regenerations():
    entities = QueryEntities(teams=[], players=[], game_id=None, week=None, season=2026)
    merged = MergedContext(
        query_id="q1",
        ranked_chunks=[make_stat_chunk()],
        cache_hit=False,
        dropped_stale=0,
        rerank_model="m",
    )
    always_threadbare = DraftReportProse(
        summary="s", matchup_analysis="m", key_factors=[], line_movement="l", citations=[]
    )
    llm = FakeLLM([always_threadbare] * 3)

    report = await build_report(
        "q1",
        "query",
        entities,
        merged,
        team_ratings={},
        home_team_id=None,
        llm=llm,
        sonnet_model="claude-sonnet-4-6",
        prompt_version="v1",
        elo_config=EloConfig(),
        edge_config=EdgeConfig(),
        replay_mode=True,
        sources_unavailable=[],
        now=NOW,
    )

    assert llm.call_count == 3  # initial + 2 regenerations
    assert "Evidence-only" in report.summary
    assert report.citations == []


@pytest.mark.unit
async def test_build_report_uncovered_market_reads_insufficient_data():
    entities = QueryEntities(teams=["KC"], players=[], game_id="g1", week=18, season=2026)
    prop_chunk = RetrievedChunk(
        chunk_id="prop1",
        source="live_odds",
        content="Mahomes O265.5 pass yds",
        structured_data={
            "game_id": "g1",
            "book": "dk",
            "market": "player_prop",
            "selection": "Mahomes O265.5",
            "line": 265.5,
            "price": -112,
            "captured_at": NOW.isoformat(),
        },
        index_score=None,
        freshness_ts=NOW,
        retrieved_at=NOW,
    )
    merged = MergedContext(
        query_id="q1",
        ranked_chunks=[prop_chunk],
        cache_hit=False,
        dropped_stale=0,
        rerank_model="m",
    )
    draft = DraftReportProse(
        summary="s",
        matchup_analysis="m",
        key_factors=[],
        line_movement="l",
        citations=[Citation(claim="a", chunk_id="prop1", source="live_odds")] * 2,
    )
    llm = FakeLLM([draft])

    report = await build_report(
        "q1",
        "query",
        entities,
        merged,
        team_ratings={"KC": 1600.0},
        home_team_id="KC",
        llm=llm,
        sonnet_model="claude-sonnet-4-6",
        prompt_version="v1",
        elo_config=EloConfig(),
        edge_config=EdgeConfig(),
        replay_mode=True,
        sources_unavailable=[],
        now=NOW,
    )

    assert report.edge_analysis[0].assessment == "insufficient_data"


async def _spread_report(team_ratings, home_team_id, teams=("KC", "LV")):
    """Run build_report over a single KC -6.5 spread chunk and return the edge block."""
    entities = QueryEntities(teams=list(teams), players=[], game_id="g1", week=18, season=2026)
    merged = MergedContext(
        query_id="q1",
        ranked_chunks=[make_odds_chunk()],
        cache_hit=False,
        dropped_stale=0,
        rerank_model="m",
    )
    draft = DraftReportProse(
        summary="s",
        matchup_analysis="m",
        key_factors=[],
        line_movement="l",
        citations=[Citation(claim="a", chunk_id="odds1", source="live_odds")] * 2,
    )
    report = await build_report(
        "q1",
        "Is there value on KC -6.5?",
        entities,
        merged,
        team_ratings=team_ratings,
        home_team_id=home_team_id,
        llm=FakeLLM([draft]),
        sonnet_model="claude-sonnet-4-6",
        prompt_version="v1",
        elo_config=EloConfig(),
        edge_config=EdgeConfig(),
        replay_mode=True,
        sources_unavailable=[],
        now=NOW,
    )
    return report.edge_analysis[0]


# The number the old 1500.0 defaults produced for *every* home team in the
# league, in every spread and moneyline market: win_probability(1500, 1500,
# is_home=True) with home_field=65 and logistic_scale=400.
HOME_FIELD_ONLY_ARTIFACT = 0.5925


@pytest.mark.unit
async def test_unrated_matchup_reads_insufficient_data_not_a_1500_default():
    """Regression for the Elo-defaulting bug. With no ratings loaded, both teams
    used to default to 1500, leaving home field as the only input: p=0.5925,
    EV +13.11%, assessment 'value' — on any home team against any opponent.
    Missing ratings must degrade honestly instead."""
    edge = await _spread_report(team_ratings={}, home_team_id="KC")

    assert edge.model_probability is None
    assert edge.expected_value_pct is None
    assert edge.assessment == "insufficient_data"


@pytest.mark.unit
async def test_partially_rated_matchup_reads_insufficient_data():
    """One known rating is not enough — a rating gap needs both sides. Defaulting
    only the opponent would still fabricate the gap."""
    edge = await _spread_report(team_ratings={"KC": 1600.0}, home_team_id="KC")

    assert edge.model_probability is None
    assert edge.assessment == "insufficient_data"


@pytest.mark.unit
async def test_model_probability_tracks_the_rating_gap_not_home_field():
    """The same fixture matchup, played at each team's home, must price
    differently — and neither may land on the home-field-only artifact. Under
    the bug both directions returned exactly 0.5925/'value'."""
    kc_at_home = await _spread_report(
        team_ratings={"KC": 1600.0, "LV": 1450.0}, home_team_id="KC", teams=("KC", "LV")
    )
    lv_at_home = await _spread_report(
        team_ratings={"KC": 1600.0, "LV": 1450.0}, home_team_id="LV", teams=("LV", "KC")
    )

    assert kc_at_home.model_probability == pytest.approx(0.7752, abs=1e-4)
    assert lv_at_home.model_probability == pytest.approx(0.3801, abs=1e-4)
    assert kc_at_home.model_probability != lv_at_home.model_probability
    for edge in (kc_at_home, lv_at_home):
        assert edge.model_probability != pytest.approx(HOME_FIELD_ONLY_ARTIFACT, abs=1e-3)

    # The weaker home team must not be reported as value — the exact inversion
    # the bug produced (it called Las Vegas at home against Kansas City "value").
    assert kc_at_home.assessment == "value"
    assert lv_at_home.assessment == "no_value"


@pytest.mark.unit
async def test_build_report_discloses_sources_unavailable():
    entities = QueryEntities(teams=[], players=[], game_id=None, week=None, season=2026)
    merged = MergedContext(
        query_id="q1",
        ranked_chunks=[make_stat_chunk()],
        cache_hit=False,
        dropped_stale=0,
        rerank_model="m",
    )
    draft = DraftReportProse(
        summary="s",
        matchup_analysis="m",
        key_factors=[],
        line_movement="l",
        citations=[Citation(claim="a", chunk_id="stat1", source="stats_es")] * 2,
    )
    llm = FakeLLM([draft])

    report = await build_report(
        "q1",
        "query",
        entities,
        merged,
        team_ratings={},
        home_team_id=None,
        llm=llm,
        sonnet_model="claude-sonnet-4-6",
        prompt_version="v1",
        elo_config=EloConfig(),
        edge_config=EdgeConfig(),
        replay_mode=False,
        sources_unavailable=["live_odds"],
        now=NOW,
    )

    assert report.sources_unavailable == ["live_odds"]
