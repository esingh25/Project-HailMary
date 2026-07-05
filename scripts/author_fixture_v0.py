"""One-off authoring script for fixtures/synthetic_v0/. Run once; output is committed.

Not part of the runtime pipeline (that's scripts/load_fixture.py). Generates real
SHA-256 content hashes and deterministic seeded pseudo-embeddings so the committed
fixture is internally consistent without needing a live Voyage key.
"""

import hashlib
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic_v0"
VIRTUAL_CLOCK = datetime(2026, 1, 4, 18, 0, 0, tzinfo=UTC)
EMBEDDING_DIM = 16


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, default=str) + "\n")


def seeded_unit_vector(key: str, dim: int = EMBEDDING_DIM) -> list[float]:
    seed = int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    raw = [rng.gauss(0, 1) for _ in range(dim)]
    norm = sum(x * x for x in raw) ** 0.5
    return [x / norm for x in raw]


def iso(dt: datetime) -> str:
    return dt.isoformat()


def main() -> None:
    indexed_at = VIRTUAL_CLOCK - timedelta(days=1)

    # --- manifest ------------------------------------------------------------------
    games = [
        {
            "game_id": "2026_18_LV_KC",
            "sport": "nfl",
            "season": 2026,
            "week": 18,
            "home_team_id": "KC",
            "away_team_id": "LV",
            "venue": "outdoor",
            "kickoff": iso(VIRTUAL_CLOCK),
        },
        {
            "game_id": "2026_18_BUF_MIN",
            "sport": "nfl",
            "season": 2026,
            "week": 18,
            "home_team_id": "MIN",
            "away_team_id": "BUF",
            "venue": "indoor",
            "kickoff": iso(VIRTUAL_CLOCK),
        },
        {
            "game_id": "2026_14_BAMA_UGA",
            "sport": "cfb",
            "season": 2026,
            "week": 14,
            "home_team_id": "UGA",
            "away_team_id": "BAMA",
            "venue": "outdoor",
            "kickoff": iso(VIRTUAL_CLOCK - timedelta(days=4)),
        },
    ]
    manifest = {
        "fixture_name": "synthetic_v0",
        "schema_version": 1,
        "virtual_clock": iso(VIRTUAL_CLOCK),
        "embedding_dim": EMBEDDING_DIM,
        "embedding_model": "synthetic-placeholder-16d",
        "games": games,
        "notes": (
            "Hand-authored fixture (scripts/author_fixture_v0.py). Deliberately "
            "includes: line movement (KC spread/ML/total + a player prop), a "
            "mid-week injury status flip (Mahomes questionable -> probable), an "
            "outdoor-weather game (LV @ KC), and a planted surname collision "
            "(Josh Allen/BUF vs Brandon Allen/MIN)."
        ),
    }
    (FIXTURE_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # --- stats.jsonl -----------------------------------------------------------------
    def stat(record_id, sport, season, week, team_id, player_id, game_id, fields, text_blob):
        return {
            "record_id": record_id,
            "sport": sport,
            "season": season,
            "week": week,
            "team_id": team_id,
            "player_id": player_id,
            "game_id": game_id,
            "fields": fields,
            "text_blob": text_blob,
            "content_hash": content_hash(text_blob),
            "indexed_at": iso(indexed_at),
        }

    stats = [
        stat(
            "st_kc_team_w18",
            "nfl",
            2026,
            18,
            "KC",
            None,
            "2026_18_LV_KC",
            {
                "schema_type": "team",
                "points_per_game": 28.4,
                "yards_per_game": 385.2,
                "def_yards_allowed_pg": 310.5,
            },
            "KC averages 28.4 points and 385.2 yards per game this season.",
        ),
        stat(
            "st_kc_pass_mahomes_w18",
            "nfl",
            2026,
            18,
            "KC",
            "mahomes_pat",
            "2026_18_LV_KC",
            {
                "schema_type": "passing",
                "pass_yards_ytd": 4100,
                "pass_tds_ytd": 32,
                "int_ytd": 9,
                "comp_pct": 67.2,
            },
            "Patrick Mahomes has thrown for 4100 yards, 32 TDs, and 9 INTs this season.",
        ),
        stat(
            "st_kc_def_w18",
            "nfl",
            2026,
            18,
            "KC",
            None,
            "2026_18_LV_KC",
            {"schema_type": "defense", "sacks_ytd": 42, "def_rank": 6},
            "KC's defense has 42 sacks and ranks 6th overall.",
        ),
        stat(
            "st_lv_team_w18",
            "nfl",
            2026,
            18,
            "LV",
            None,
            "2026_18_LV_KC",
            {
                "schema_type": "team",
                "points_per_game": 19.8,
                "yards_per_game": 315.0,
                "def_yards_allowed_pg": 355.1,
            },
            "LV averages 19.8 points and 315.0 yards per game this season.",
        ),
        stat(
            "st_lv_pass_w18",
            "nfl",
            2026,
            18,
            "LV",
            "lv_qb1",
            "2026_18_LV_KC",
            {
                "schema_type": "passing",
                "pass_yards_ytd": 3200,
                "pass_tds_ytd": 18,
                "int_ytd": 13,
                "comp_pct": 61.0,
            },
            "LV's starting QB has thrown for 3200 yards, 18 TDs, and 13 INTs this season.",
        ),
        stat(
            "st_lv_def_w18",
            "nfl",
            2026,
            18,
            "LV",
            None,
            "2026_18_LV_KC",
            {"schema_type": "defense", "sacks_ytd": 31, "def_rank": 22},
            "LV's defense has 31 sacks and ranks 22nd overall.",
        ),
        stat(
            "st_buf_team_w18",
            "nfl",
            2026,
            18,
            "BUF",
            None,
            "2026_18_BUF_MIN",
            {"schema_type": "team", "points_per_game": 27.1, "yards_per_game": 375.4},
            "BUF averages 27.1 points and 375.4 yards per game this season.",
        ),
        stat(
            "st_buf_pass_allen_w18",
            "nfl",
            2026,
            18,
            "BUF",
            "allen_josh",
            "2026_18_BUF_MIN",
            {
                "schema_type": "passing",
                "pass_yards_ytd": 3900,
                "pass_tds_ytd": 35,
                "int_ytd": 7,
                "comp_pct": 64.5,
                "rush_yards_ytd": 520,
            },
            "Josh Allen has thrown for 3900 yards and 35 TDs, adding 520 rushing yards.",
        ),
        stat(
            "st_buf_def_w18",
            "nfl",
            2026,
            18,
            "BUF",
            None,
            "2026_18_BUF_MIN",
            {"schema_type": "defense", "sacks_ytd": 38, "def_rank": 9},
            "BUF's defense has 38 sacks and ranks 9th overall.",
        ),
        stat(
            "st_min_team_w18",
            "nfl",
            2026,
            18,
            "MIN",
            None,
            "2026_18_BUF_MIN",
            {"schema_type": "team", "points_per_game": 22.5, "yards_per_game": 330.1},
            "MIN averages 22.5 points and 330.1 yards per game this season.",
        ),
        stat(
            "st_min_pass_allen_w18",
            "nfl",
            2026,
            18,
            "MIN",
            "allen_brandon",
            "2026_18_BUF_MIN",
            {
                "schema_type": "passing",
                "pass_yards_ytd": 450,
                "pass_tds_ytd": 2,
                "int_ytd": 3,
                "comp_pct": 58.0,
            },
            "Brandon Allen has thrown for 450 yards and 2 TDs in relief duty this season.",
        ),
        stat(
            "st_min_def_w18",
            "nfl",
            2026,
            18,
            "MIN",
            None,
            "2026_18_BUF_MIN",
            {"schema_type": "defense", "sacks_ytd": 35, "def_rank": 14},
            "MIN's defense has 35 sacks and ranks 14th overall.",
        ),
        stat(
            "st_bama_team_w14",
            "cfb",
            2026,
            14,
            "BAMA",
            None,
            "2026_14_BAMA_UGA",
            {"schema_type": "team", "points_per_game": 34.2},
            "Alabama averages 34.2 points per game this season.",
        ),
        stat(
            "st_bama_pass_w14",
            "cfb",
            2026,
            14,
            "BAMA",
            "qb_bama1",
            "2026_14_BAMA_UGA",
            {"schema_type": "passing", "pass_yards_ytd": 2900, "pass_tds_ytd": 24},
            "Alabama's QB has thrown for 2900 yards and 24 TDs this season.",
        ),
        stat(
            "st_uga_team_w14",
            "cfb",
            2026,
            14,
            "UGA",
            None,
            "2026_14_BAMA_UGA",
            {"schema_type": "team", "points_per_game": 31.0},
            "Georgia averages 31.0 points per game this season.",
        ),
        stat(
            "st_uga_pass_w14",
            "cfb",
            2026,
            14,
            "UGA",
            "qb_uga1",
            "2026_14_BAMA_UGA",
            {"schema_type": "passing", "pass_yards_ytd": 2700, "pass_tds_ytd": 21},
            "Georgia's QB has thrown for 2700 yards and 21 TDs this season.",
        ),
    ]
    write_jsonl(FIXTURE_DIR / "stats.jsonl", stats)

    # --- semantic_docs.jsonl + embeddings.json ---------------------------------------
    def doc(doc_id, sport, doc_type, text, days_old):
        return {
            "doc_id": doc_id,
            "sport": sport,
            "doc_type": doc_type,
            "text": text,
            "embedding_model": manifest["embedding_model"],
            "source": "curated_scrape",
            "published_at": iso(VIRTUAL_CLOCK - timedelta(days=days_old)),
            "content_hash": content_hash(text),
        }

    semantic_docs = [
        doc(
            "doc_kc_scouting",
            "nfl",
            "scouting_note",
            "Mahomes has historically excelled in primetime and Thursday-night matchups, "
            "posting a strong record and efficient passing numbers under short-week prep.",
            2,
        ),
        doc(
            "doc_lv_recap",
            "nfl",
            "game_recap",
            "LV struggled offensively in their last outing, managing just 13 points against "
            "a top-10 defense and committing two turnovers.",
            5,
        ),
        doc(
            "doc_buf_analysis",
            "nfl",
            "analysis",
            "Buffalo's offense under Josh Allen ranks top-5 in yards per play, with Allen's "
            "dual-threat rushing providing a key red-zone advantage.",
            3,
        ),
        doc(
            "doc_min_injury_context",
            "nfl",
            "injury_context",
            "Minnesota turns to backup Brandon Allen after their starter was ruled out, "
            "creating uncertainty in the passing attack for this matchup.",
            1,
        ),
        doc(
            "doc_bama_recap",
            "cfb",
            "game_recap",
            "Alabama and Georgia enter this rivalry matchup as top-10 teams, with both "
            "offenses averaging over 30 points per game this season.",
            6,
        ),
        doc(
            "doc_weather_note",
            "nfl",
            "analysis",
            "Sunday's forecast at Arrowhead calls for cold temperatures and gusty wind, "
            "conditions that have historically suppressed passing totals in outdoor games.",
            1,
        ),
    ]
    write_jsonl(FIXTURE_DIR / "semantic_docs.jsonl", semantic_docs)

    embeddings = {
        "model": manifest["embedding_model"],
        "dim": EMBEDDING_DIM,
        "vectors": {d["doc_id"]: seeded_unit_vector(d["doc_id"]) for d in semantic_docs},
    }
    (FIXTURE_DIR / "embeddings.json").write_text(json.dumps(embeddings, indent=2), encoding="utf-8")

    # --- odds_timeseries.jsonl ---------------------------------------------------------
    def odds(game_id, book, market, selection, line, price, days_before):
        captured = VIRTUAL_CLOCK - timedelta(days=days_before)
        return {
            "game_id": game_id,
            "book": book,
            "market": market,
            "selection": selection,
            "line": line,
            "price": price,
            "captured_at": iso(captured),
        }

    odds_series = [
        # KC -6.5 spread, line moved -6.0 -> -6.5, price wobbling (line movement)
        odds("2026_18_LV_KC", "draftkings", "spread", "KC -6.0", -6.0, -110, 4),
        odds("2026_18_LV_KC", "draftkings", "spread", "KC -6.0", -6.0, -115, 3),
        odds("2026_18_LV_KC", "draftkings", "spread", "KC -6.5", -6.5, -110, 1),
        odds("2026_18_LV_KC", "draftkings", "spread", "KC -6.5", -6.5, -108, 0),
        # KC moneyline tightening as favorite grows
        odds("2026_18_LV_KC", "draftkings", "moneyline", "KC", None, -260, 4),
        odds("2026_18_LV_KC", "draftkings", "moneyline", "KC", None, -280, 0),
        # Total moved down (weather-driven)
        odds("2026_18_LV_KC", "draftkings", "total", "Over 47.5", 47.5, -110, 4),
        odds("2026_18_LV_KC", "draftkings", "total", "Over 46.5", 46.5, -105, 0),
        # Mahomes passing prop
        odds(
            "2026_18_LV_KC",
            "draftkings",
            "player_prop",
            "Mahomes Over 265.5 pass yds",
            265.5,
            -112,
            1,
        ),
        # BUF -3 spread, small move
        odds("2026_18_BUF_MIN", "draftkings", "spread", "BUF -2.5", -2.5, -110, 5),
        odds("2026_18_BUF_MIN", "draftkings", "spread", "BUF -3.0", -3.0, -108, 0),
    ]
    write_jsonl(FIXTURE_DIR / "odds_timeseries.jsonl", odds_series)

    # --- injuries.jsonl (includes the mid-week status flip) --------------------------
    def injury(player_id, team_id, status, body_part, days_before):
        return {
            "player_id": player_id,
            "team_id": team_id,
            "status": status,
            "body_part": body_part,
            "report_date": iso(VIRTUAL_CLOCK - timedelta(days=days_before)),
        }

    injuries = [
        injury("mahomes_pat", "KC", "questionable", "ankle", 3),
        injury("mahomes_pat", "KC", "probable", "ankle", 1),  # mid-week flip
        injury("lv_wr1", "LV", "out", "hamstring", 2),
    ]
    write_jsonl(FIXTURE_DIR / "injuries.jsonl", injuries)

    # --- weather.jsonl (outdoor game only) ---------------------------------------------
    def weather(game_id, temp, wind, precip, days_before):
        return {
            "game_id": game_id,
            "temperature_f": temp,
            "wind_mph": wind,
            "precipitation_pct": precip,
            "captured_at": iso(VIRTUAL_CLOCK - timedelta(days=days_before)),
        }

    weather_records = [
        weather("2026_18_LV_KC", 28.0, 18.0, 10.0, 2),
        weather("2026_18_LV_KC", 31.0, 22.0, 5.0, 0),
    ]
    write_jsonl(FIXTURE_DIR / "weather.jsonl", weather_records)

    # --- entity_map.json ----------------------------------------------------------------
    entity_map = {
        "team_aliases": {
            "kc": "KC",
            "chiefs": "KC",
            "kansas city chiefs": "KC",
            "lv": "LV",
            "raiders": "LV",
            "las vegas raiders": "LV",
            "buf": "BUF",
            "bills": "BUF",
            "buffalo bills": "BUF",
            "min": "MIN",
            "vikings": "MIN",
            "minnesota vikings": "MIN",
            "uga": "UGA",
            "georgia": "UGA",
            "georgia bulldogs": "UGA",
            "bama": "BAMA",
            "alabama": "BAMA",
            "alabama crimson tide": "BAMA",
        },
        "players": {
            "patrick mahomes": [
                {"team_id": "KC", "player_id": "mahomes_pat", "full_name": "Patrick Mahomes"}
            ],
            "mahomes": [
                {"team_id": "KC", "player_id": "mahomes_pat", "full_name": "Patrick Mahomes"}
            ],
            # Planted surname collision (also exercised in tests/unit/test_resolution.py):
            "allen": [
                {"team_id": "BUF", "player_id": "allen_josh", "full_name": "Josh Allen"},
                {"team_id": "MIN", "player_id": "allen_brandon", "full_name": "Brandon Allen"},
            ],
            "josh allen": [
                {"team_id": "BUF", "player_id": "allen_josh", "full_name": "Josh Allen"}
            ],
            "brandon allen": [
                {"team_id": "MIN", "player_id": "allen_brandon", "full_name": "Brandon Allen"}
            ],
        },
    }
    (FIXTURE_DIR / "entity_map.json").write_text(json.dumps(entity_map, indent=2), encoding="utf-8")

    print(f"Authored fixture at {FIXTURE_DIR}")
    print(f"  stats: {len(stats)}  semantic_docs: {len(semantic_docs)}  odds: {len(odds_series)}")
    print(f"  injuries: {len(injuries)}  weather: {len(weather_records)}")


if __name__ == "__main__":
    main()
