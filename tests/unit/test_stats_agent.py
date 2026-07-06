"""Tests for the stats sub-agent: query construction + ES hit -> chunk mapping."""

from datetime import UTC, datetime

import pytest

from hailmary.retrieval.stats_agent import build_stats_query, fetch_stats
from hailmary.schemas.contracts import Condition, QueryEntities

NOW = datetime(2026, 7, 4, tzinfo=UTC)


class FakeES:
    def __init__(self, hits: list[dict]):
        self._hits = hits
        self.last_call: dict | None = None

    async def search(self, index, query, size):
        self.last_call = {"index": index, "query": query, "size": size}
        return {"hits": {"hits": self._hits[:size]}}


def make_hit(record_id="r1", score=1.5):
    return {
        "_score": score,
        "_source": {
            "record_id": record_id,
            "text_blob": "Mahomes threw for 300 yards",
            "fields": {"schema_type": "passing", "pass_yards_ytd": 4100},
            "indexed_at": NOW.isoformat(),
        },
    }


@pytest.mark.unit
def test_build_stats_query_always_filters_by_season():
    entities = QueryEntities(teams=[], players=[], game_id=None, week=None, season=2026)
    query = build_stats_query(entities, [], raw_text="")
    assert {"term": {"season": 2026}} in query["bool"]["filter"]


@pytest.mark.unit
def test_build_stats_query_adds_team_and_player_filters():
    entities = QueryEntities(
        teams=["KC"], players=["mahomes_pat"], game_id=None, week=18, season=2026
    )
    query = build_stats_query(entities, [], raw_text="")
    filters = query["bool"]["filter"]
    assert {"terms": {"team_id": ["KC"]}} in filters
    assert {"terms": {"player_id": ["mahomes_pat"]}} in filters
    assert {"term": {"week": 18}} in filters


@pytest.mark.unit
def test_build_stats_query_translates_conditions_by_operator():
    entities = QueryEntities(teams=[], players=[], game_id=None, week=None, season=2026)

    gt_query = build_stats_query(
        entities, [Condition(field="pass_yards", operator="gt", value=250)], ""
    )
    assert {"range": {"fields.pass_yards": {"gt": 250}}} in gt_query["bool"]["filter"]

    eq_query = build_stats_query(
        entities, [Condition(field="team_id", operator="eq", value="KC")], ""
    )
    assert {"term": {"fields.team_id": "KC"}} in eq_query["bool"]["filter"]

    between_query = build_stats_query(
        entities, [Condition(field="def_rank", operator="between", value=[1, 10])], ""
    )
    assert {"range": {"fields.def_rank": {"gte": 1, "lte": 10}}} in between_query["bool"]["filter"]


@pytest.mark.unit
def test_build_stats_query_includes_bm25_match_only_when_raw_text_present():
    entities = QueryEntities(teams=[], players=[], game_id=None, week=None, season=2026)
    with_text = build_stats_query(entities, [], raw_text="Mahomes Thursday night")
    without_text = build_stats_query(entities, [], raw_text="")

    assert with_text["bool"]["must"] == [{"match": {"text_blob": "Mahomes Thursday night"}}]
    assert "must" not in without_text["bool"]


@pytest.mark.unit
async def test_fetch_stats_maps_hits_to_chunks_and_respects_k():
    client = FakeES([make_hit("r1"), make_hit("r2"), make_hit("r3")])
    entities = QueryEntities(teams=["KC"], players=[], game_id=None, week=18, season=2026)

    chunks = await fetch_stats(client, "nfl", entities, [], "Mahomes", k=2, now=NOW)

    assert len(chunks) == 2
    assert chunks[0].chunk_id == "r1"
    assert chunks[0].source == "stats_es"
    assert chunks[0].index_score == 1.5
    assert chunks[0].freshness_ts == NOW
    assert client.last_call["index"] == "nfl_stats"
    assert client.last_call["size"] == 2
