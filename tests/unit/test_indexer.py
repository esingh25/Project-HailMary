"""Unit tests for ingestion/indexer.py against lightweight fake clients.

These verify *what gets sent* (correct keys/ids/TTLs, idempotent-upsert shape) —
not real ES/Qdrant/Redis/Postgres behavior, which needs Docker (tracked separately
as an integration-test follow-up once Docker is available).
"""

from datetime import UTC, datetime

import pytest

from hailmary.config import TtlConfig
from hailmary.ingestion.indexer import (
    archive_odds,
    cache_injuries,
    cache_odds,
    cache_weather,
    doc_point_id,
    upsert_semantic_docs,
    upsert_stats,
)
from hailmary.schemas.contracts import InjuryRecord, OddsSnapshot, SemanticDoc, StatRecord
from hailmary.schemas.internal import WeatherRecord

NOW = datetime(2026, 7, 4, tzinfo=UTC)


class FakeES:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []

    async def index(self, index, id, document):
        self.calls.append((index, id, document))


class FakeQdrant:
    def __init__(self):
        self.upserts: list[tuple[str, list]] = []

    async def upsert(self, collection_name, points):
        self.upserts.append((collection_name, points))


class FakeRedis:
    def __init__(self):
        self.store: dict[str, tuple] = {}

    async def set(self, key, value, ex=None):
        self.store[key] = (value, ex)


class FakePG:
    """Emulates the ON CONFLICT (...) DO NOTHING semantics for odds_archive."""

    def __init__(self):
        self._seen: set[tuple] = set()

    async def execute(self, query, *args):
        key = (args[0], args[1], args[2], args[3], args[6])  # game_id, book, market, sel, ts
        if key in self._seen:
            return "INSERT 0 0"
        self._seen.add(key)
        return "INSERT 0 1"


def make_stat(record_id="r1", sport="nfl"):
    return StatRecord(
        record_id=record_id,
        sport=sport,
        season=2026,
        week=18,
        team_id="KC",
        player_id=None,
        game_id="g1",
        fields={"schema_type": "team"},
        text_blob="KC stats",
        content_hash="hash1",
        indexed_at=NOW,
    )


def make_doc(doc_id="d1", doc_type="game_recap", content_hash="hashA"):
    return SemanticDoc(
        doc_id=doc_id,
        sport="nfl",
        doc_type=doc_type,
        text="recap text",
        embedding_model="synthetic-placeholder-16d",
        source="curated_scrape",
        published_at=NOW,
        content_hash=content_hash,
    )


def make_odds(selection="KC -6.5", captured_at=NOW):
    return OddsSnapshot(
        game_id="g1",
        book="dk",
        market="spread",
        selection=selection,
        line=-6.5,
        price=-110,
        captured_at=captured_at,
    )


@pytest.mark.unit
async def test_upsert_stats_indexes_by_sport_and_record_id():
    client = FakeES()
    record = make_stat(record_id="r1", sport="nfl")
    count = await upsert_stats(client, [record])
    assert count == 1
    assert client.calls == [("nfl_stats", "r1", record.model_dump(mode="json"))]


@pytest.mark.unit
async def test_upsert_stats_same_record_id_overwrites_not_duplicates():
    """Re-ingesting the same record_id must target the same ES doc id (idempotent
    upsert shape) — real ES overwrites on `index` with a fixed id."""
    client = FakeES()
    record = make_stat(record_id="r1")
    await upsert_stats(client, [record])
    await upsert_stats(client, [record])
    ids_used = {call[1] for call in client.calls}
    assert ids_used == {"r1"}
    assert len(client.calls) == 2  # both calls hit ES, but always the same id


@pytest.mark.unit
def test_doc_point_id_is_deterministic_for_same_content_hash():
    assert doc_point_id("abc123") == doc_point_id("abc123")


@pytest.mark.unit
def test_doc_point_id_differs_for_different_content_hash():
    assert doc_point_id("abc123") != doc_point_id("xyz789")


@pytest.mark.unit
async def test_upsert_semantic_docs_routes_by_doc_type_to_correct_collection():
    client = FakeQdrant()
    recap = make_doc(doc_id="d1", doc_type="game_recap", content_hash="h1")
    note = make_doc(doc_id="d2", doc_type="scouting_note", content_hash="h2")
    embeddings = {"d1": [0.1, 0.2], "d2": [0.3, 0.4]}

    count = await upsert_semantic_docs(client, [recap, note], embeddings)

    assert count == 2
    collections_used = {call[0] for call in client.upserts}
    assert collections_used == {"game_recaps", "scouting_notes"}


@pytest.mark.unit
async def test_cache_odds_uses_replay_ttl_in_replay_mode():
    client = FakeRedis()
    ttl = TtlConfig(odds_minutes_live=5, odds_minutes_replay=60)
    snap = make_odds()

    await cache_odds(client, [snap], ttl, replay_mode=True)

    (value, ex) = next(iter(client.store.values()))
    assert ex.total_seconds() == 60 * 60


@pytest.mark.unit
async def test_cache_odds_uses_live_ttl_outside_replay_mode():
    client = FakeRedis()
    ttl = TtlConfig(odds_minutes_live=5, odds_minutes_replay=60)
    snap = make_odds()

    await cache_odds(client, [snap], ttl, replay_mode=False)

    (value, ex) = next(iter(client.store.values()))
    assert ex.total_seconds() == 5 * 60


@pytest.mark.unit
async def test_archive_odds_is_idempotent_on_rerun():
    pg = FakePG()
    snapshots = [make_odds(selection="KC -6.5", captured_at=NOW)]

    first_run = await archive_odds(pg, snapshots)
    second_run = await archive_odds(pg, snapshots)

    assert first_run == 1
    assert second_run == 0  # same snapshot re-ingested inserts nothing new


@pytest.mark.unit
async def test_archive_odds_distinguishes_genuinely_new_snapshots():
    pg = FakePG()
    opening = make_odds(selection="KC -6.0", captured_at=NOW)
    current = make_odds(selection="KC -6.5", captured_at=NOW)

    count = await archive_odds(pg, [opening, current])

    assert count == 2  # distinct selections are genuinely different facts


@pytest.mark.unit
async def test_cache_injuries_keys_by_player_id():
    client = FakeRedis()
    ttl = TtlConfig()
    record = InjuryRecord(
        player_id="mahomes_pat",
        team_id="KC",
        status="probable",
        body_part="ankle",
        report_date=NOW,
    )
    await cache_injuries(client, [record], ttl)
    assert "injury:KC:mahomes_pat" in client.store


@pytest.mark.unit
async def test_cache_weather_keys_by_game_id():
    client = FakeRedis()
    ttl = TtlConfig()
    record = WeatherRecord(
        game_id="g1", temperature_f=31.0, wind_mph=22.0, precipitation_pct=5.0, captured_at=NOW
    )
    await cache_weather(client, [record], ttl)
    assert "weather:g1" in client.store
