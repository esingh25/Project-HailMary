"""PLAN.md M2 exit criterion, verified for real: "second run = zero net-new docs"."""

import pytest

from hailmary.clients.es import CFB_STATS_INDEX, NFL_STATS_INDEX
from hailmary.clients.qdrant import ANALYSIS, GAME_RECAPS, SCOUTING_NOTES
from hailmary.ingestion.scheduler import run_replay_ingestion_pass

STATS_INDEXES = f"{NFL_STATS_INDEX},{CFB_STATS_INDEX}"


async def _store_counts(stores) -> dict:
    await stores.es.indices.refresh(index=STATS_INDEXES)
    es_docs = (await stores.es.count(index=STATS_INDEXES))["count"]
    qdrant_points = 0
    for collection in (GAME_RECAPS, SCOUTING_NOTES, ANALYSIS):
        qdrant_points += (await stores.qdrant.get_collection(collection)).points_count
    odds_rows = await stores.pg.fetchval("SELECT COUNT(*) FROM odds_archive")
    rating_rows = await stores.pg.fetchval("SELECT COUNT(*) FROM team_ratings")
    return {
        "es_docs": es_docs,
        "qdrant_points": qdrant_points,
        "odds_rows": odds_rows,
        "rating_rows": rating_rows,
    }


@pytest.mark.integration
async def test_second_ingestion_pass_creates_zero_net_new_records(stores, settings, fixture_data):
    await run_replay_ingestion_pass(
        fixture_data, stores.es, stores.qdrant, stores.redis, stores.pg, settings
    )
    first = await _store_counts(stores)
    assert first["es_docs"] > 0 and first["qdrant_points"] > 0 and first["odds_rows"] > 0

    second_summary = await run_replay_ingestion_pass(
        fixture_data, stores.es, stores.qdrant, stores.redis, stores.pg, settings
    )
    second = await _store_counts(stores)

    assert second == first
    odds_inserted_on_rerun = sum(
        count for source, count in second_summary.items() if source.startswith("odds_")
    )
    assert odds_inserted_on_rerun == 0  # append-only archive: rerun inserts nothing
