"""Nightly retention compaction (DESIGN.md §11).

Enforces the retention table against Postgres and invalidates semantic-cache
rows whose prompt_version no longer matches current. ES/Qdrant season-based
retention (drop seasons older than current-2) only applies once multiple
seasons of live data exist — Postgres is the fastest-growing store and the
first target (§14 risk register). Prints one line per table so the ingestion
log/dashboard can surface it.

Run manually or via the live scheduler: `uv run python scripts/compact.py`.
"""

import asyncio

from hailmary.clients.postgres import get_pg_connection
from hailmary.config import get_settings
from hailmary.prompts import PROMPT_VERSION

# (table, WHERE clause) pairs from the §11 retention table. Interval literals
# are constants from the frozen doc, not tunables.
RETENTION_DELETES = [
    ("events", "ts < NOW() - INTERVAL '90 days'"),
    ("research_reports", "generated_at < NOW() - INTERVAL '180 days'"),
    ("session_turns", "ts < NOW() - INTERVAL '180 days'"),
    ("semantic_cache_index", "created_at < NOW() - INTERVAL '14 days'"),
    ("odds_archive", "captured_at < NOW() - INTERVAL '2 years'"),
]


def _deleted_count(status: str) -> int:
    return int(status.split()[-1])  # asyncpg execute() returns e.g. "DELETE 42"


async def compact() -> dict[str, int]:
    settings = get_settings()
    pg = await get_pg_connection(settings)
    deleted: dict[str, int] = {}
    try:
        for table, where in RETENTION_DELETES:
            status = await pg.execute(f"DELETE FROM {table} WHERE {where}")  # noqa: S608
            deleted[table] = _deleted_count(status)

        status = await pg.execute(
            "DELETE FROM semantic_cache_index WHERE prompt_version <> $1", PROMPT_VERSION
        )
        deleted["semantic_cache_index_stale_prompt"] = _deleted_count(status)
    finally:
        await pg.close()
    return deleted


if __name__ == "__main__":
    for table, count in asyncio.run(compact()).items():
        print(f"{table}: deleted {count}")
