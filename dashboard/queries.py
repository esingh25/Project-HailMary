"""Data-fetching functions for the Streamlit dashboard panels (DESIGN.md §5
Phase 5). Kept separate from the Streamlit rendering script (app.py) so these
are unit-testable with a fake Postgres connection — PLAN.md's stated testing
strategy explicitly excludes Streamlit visuals from automated testing.
"""


async def get_ingestion_health(pg) -> list[dict]:
    """Most recent ingestion_log row per source (DESIGN.md §10 ingestion heartbeats)."""
    rows = await pg.fetch(
        "SELECT DISTINCT ON (source) source, records, status, ran_at "
        "FROM ingestion_log ORDER BY source, ran_at DESC"
    )
    return [dict(r) for r in rows]


async def get_query_trace(pg, query_id: str) -> list[dict]:
    """The events timeline for one query_id (DESIGN.md §10: "first stop for
    debugging 'what happened to query X?'")."""
    rows = await pg.fetch(
        "SELECT phase, event, detail, ts FROM events WHERE query_id = $1 ORDER BY ts",
        query_id,
    )
    return [dict(r) for r in rows]


async def get_cache_stats(pg) -> dict:
    row = await pg.fetchrow(
        "SELECT COUNT(*) AS total, COUNT(last_hit_at) AS hit_count, "
        "AVG(EXTRACT(EPOCH FROM (NOW() - created_at))) AS avg_age_seconds "
        "FROM semantic_cache_index"
    )
    if row is None or row["total"] == 0:
        return {"total": 0, "hit_rate": 0.0, "avg_age_seconds": 0.0}
    return {
        "total": row["total"],
        "hit_rate": row["hit_count"] / row["total"],
        "avg_age_seconds": row["avg_age_seconds"] or 0.0,
    }


async def get_odds_budget(pg) -> dict | None:
    row = await pg.fetchrow(
        "SELECT calls_used, calls_limit FROM api_budget WHERE source = 'the_odds_api'"
    )
    if row is None:
        return None
    return {
        "calls_used": row["calls_used"],
        "calls_limit": row["calls_limit"],
        "remaining": row["calls_limit"] - row["calls_used"],
    }
