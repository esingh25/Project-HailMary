"""Build fixtures/<name>/ from archived live data (PLAN.md M8, DESIGN.md §5).

Same manifest format as synthetic_v0, drop-in via FIXTURE_NAME. Off-season
reality (risk register #8): nflverse serves historical stats/schedules/injuries
any time, but The Odds API free tier has no history and Open-Meteo is
forecast-only — so a fixture built between seasons has real stats, results,
schedule, and entity map, with empty odds/weather series. Run it in-season
(after the live scheduler has been archiving odds) to capture a full week;
odds_timeseries.jsonl is then exported from the odds_archive table.

Usage: uv run python scripts/build_fixture.py --season 2025 --week 18 [--name real_week_v1]
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from hailmary.clients.feeds.nflverse import (
    entity_map_from_rosters,
    game_results_from_schedule,
    injury_records_from_rows,
    stat_records_from_weekly,
)
from hailmary.clients.postgres import get_pg_connection
from hailmary.config import get_settings

FIXTURES_ROOT = Path(__file__).resolve().parent.parent / "fixtures"
EMBEDDING_DIM = 64  # matches synthetic_v0 until a real embedding model is wired


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, default=str) + "\n" for r in records), encoding="utf-8")


async def export_archived_odds(pg, game_ids: list[str]) -> list[dict]:
    """In-season path: the live scheduler has been archiving odds; export them."""
    rows = await pg.fetch(
        "SELECT game_id, book, market, selection, line, price, captured_at "
        "FROM odds_archive WHERE game_id = ANY($1) ORDER BY captured_at",
        game_ids,
    )
    return [dict(r) for r in rows]


async def build(season: int, week: int, name: str) -> Path:
    import nfl_data_py as nfl

    out = FIXTURES_ROOT / name
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)

    weekly = await asyncio.to_thread(nfl.import_weekly_data, [season])
    schedule = await asyncio.to_thread(nfl.import_schedules, [season])
    injuries = await asyncio.to_thread(nfl.import_injuries, [season])
    teams = await asyncio.to_thread(nfl.import_team_desc)
    rosters = await asyncio.to_thread(nfl.import_seasonal_rosters, [season])

    weekly_rows = weekly[weekly["week"] <= week].to_dict("records")
    schedule_rows = schedule.to_dict("records")
    week_games = [r for r in schedule_rows if int(r["week"]) == week]
    injury_rows = injuries[injuries["week"] == week].to_dict("records")

    stats = stat_records_from_weekly(weekly_rows, now)
    results = game_results_from_schedule([r for r in schedule_rows if int(r["week"]) < week])
    entity_map = entity_map_from_rosters(
        teams.to_dict("records"), rosters.to_dict("records"), schedule_rows
    )
    injury_records = injury_records_from_rows(injury_rows)

    settings = get_settings()
    try:
        pg = await get_pg_connection(settings)
    except OSError:
        archived_odds: list[dict] = []
    else:
        try:
            archived_odds = await export_archived_odds(pg, [g["game_id"] for g in week_games])
        finally:
            await pg.close()

    write_jsonl(out / "stats.jsonl", [s.model_dump(mode="json") for s in stats])
    write_jsonl(out / "game_results.jsonl", [r.model_dump(mode="json") for r in results])
    write_jsonl(out / "injuries.jsonl", [i.model_dump(mode="json") for i in injury_records])
    write_jsonl(out / "odds_timeseries.jsonl", archived_odds)
    write_jsonl(out / "semantic_docs.jsonl", [])  # curated scrape docs are captured in-season
    write_jsonl(out / "weather.jsonl", [])  # forecast-only API; captured in-season
    (out / "entity_map.json").write_text(entity_map.model_dump_json(indent=2), encoding="utf-8")
    (out / "embeddings.json").write_text(
        json.dumps({"embedding_model": "", "vectors": {}}), encoding="utf-8"
    )

    kickoffs = [g["gameday"] for g in week_games if g.get("gameday")]
    manifest = {
        "fixture_name": name,
        "built_at": now.isoformat(),
        "embedding_dim": EMBEDDING_DIM,
        "virtual_clock": f"{min(kickoffs)}T18:00:00+00:00" if kickoffs else now.isoformat(),
        "games": [
            {
                "game_id": g["game_id"],
                "sport": "nfl",
                "season": int(g["season"]),
                "week": int(g["week"]),
                "home_team_id": g["home_team"],
                "away_team_id": g["away_team"],
                "venue": "outdoor" if g.get("roof") in ("outdoors", "open") else "indoor",
                "kickoff": str(g.get("gameday")),
            }
            for g in week_games
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--name", default="real_week_v1")
    args = parser.parse_args()
    path = asyncio.run(build(args.season, args.week, args.name))
    print(f"Fixture written to {path}")
