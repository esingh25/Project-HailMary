"""Validate fixtures/synthetic_v0/ parses cleanly against the real Pydantic contracts.

This is the fixture's own correctness test — not a replay-client test (that's M1.8).
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from hailmary.schemas.contracts import InjuryRecord, OddsSnapshot, SemanticDoc, StatRecord
from hailmary.schemas.internal import EntityMap, GameResult, WeatherRecord

FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "synthetic_v0"


def _load_jsonl(name: str) -> list[dict]:
    path = FIXTURE_DIR / name
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@pytest.mark.unit
def test_manifest_has_required_fields_and_three_games():
    manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["fixture_name"] == "synthetic_v0"
    assert "virtual_clock" in manifest
    datetime.fromisoformat(manifest["virtual_clock"])  # must parse
    assert len(manifest["games"]) == 3


@pytest.mark.unit
def test_stats_jsonl_validates_against_stat_record_contract():
    records = _load_jsonl("stats.jsonl")
    assert len(records) > 0
    for record in records:
        StatRecord.model_validate(record)


@pytest.mark.unit
def test_semantic_docs_jsonl_validates_against_semantic_doc_contract():
    records = _load_jsonl("semantic_docs.jsonl")
    assert len(records) > 0
    for record in records:
        SemanticDoc.model_validate(record)


@pytest.mark.unit
def test_odds_timeseries_validates_and_shows_line_movement():
    records = _load_jsonl("odds_timeseries.jsonl")
    assert len(records) > 0
    for record in records:
        OddsSnapshot.model_validate(record)

    kc_spread = [r for r in records if r["market"] == "spread" and r["game_id"] == "2026_18_LV_KC"]
    lines = {r["line"] for r in kc_spread}
    assert len(lines) > 1, "fixture must show real line movement, not a static line"


@pytest.mark.unit
def test_injuries_jsonl_validates_and_contains_a_status_flip():
    records = _load_jsonl("injuries.jsonl")
    for record in records:
        InjuryRecord.model_validate(record)

    mahomes_statuses = {r["status"] for r in records if r["player_id"] == "mahomes_pat"}
    assert mahomes_statuses == {
        "questionable",
        "probable",
    }, "fixture must include the mid-week flip"


@pytest.mark.unit
def test_weather_jsonl_validates_against_internal_weather_record():
    records = _load_jsonl("weather.jsonl")
    assert len(records) > 0
    for record in records:
        WeatherRecord.model_validate(record)


@pytest.mark.unit
def test_entity_map_validates_and_contains_planted_collision():
    raw = json.loads((FIXTURE_DIR / "entity_map.json").read_text(encoding="utf-8"))
    entity_map = EntityMap.model_validate(raw)

    allen_candidates = entity_map.players["allen"]
    assert len(allen_candidates) == 2
    assert {c.team_id for c in allen_candidates} == {"BUF", "MIN"}


@pytest.mark.unit
def test_embeddings_json_has_a_unit_vector_per_semantic_doc():
    docs = _load_jsonl("semantic_docs.jsonl")
    embeddings = json.loads((FIXTURE_DIR / "embeddings.json").read_text(encoding="utf-8"))

    assert set(embeddings["vectors"].keys()) == {d["doc_id"] for d in docs}
    for vector in embeddings["vectors"].values():
        assert len(vector) == embeddings["dim"]
        magnitude = sum(x * x for x in vector) ** 0.5
        assert magnitude == pytest.approx(1.0, abs=1e-6)


@pytest.mark.unit
def test_game_results_jsonl_validates_and_covers_both_sports():
    records = _load_jsonl("game_results.jsonl")
    assert len(records) > 0
    for record in records:
        GameResult.model_validate(record)

    sports = {r["sport"] for r in records}
    assert sports == {"nfl", "cfb"}
