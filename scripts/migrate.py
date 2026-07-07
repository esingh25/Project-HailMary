"""Apply ordered .sql files under db/migrations/, tracked in a schema_migrations ledger."""

import asyncio
import sys
from pathlib import Path

import asyncpg

from hailmary.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "db" / "migrations"

LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    TEXT PRIMARY KEY,
    applied_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
"""


async def run_migrations() -> None:
    settings = get_settings()
    conn = await asyncpg.connect(dsn=settings.postgres_dsn)
    try:
        await conn.execute(LEDGER_DDL)
        applied_rows = await conn.fetch("SELECT filename FROM schema_migrations")
        applied = {row["filename"] for row in applied_rows}

        pending = sorted(p for p in MIGRATIONS_DIR.glob("*.sql") if p.name not in applied)
        if not pending:
            print("No pending migrations.")
            return

        for path in pending:
            sql = path.read_text(encoding="utf-8")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES ($1)", path.name
                )
            print(f"Applied {path.name}")
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        asyncio.run(run_migrations())
    except Exception as exc:  # noqa: BLE001
        print(f"Migration failed: {exc}", file=sys.stderr)
        sys.exit(1)
