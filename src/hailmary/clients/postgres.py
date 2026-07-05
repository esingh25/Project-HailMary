"""Postgres connection factory (DESIGN.md §6.4 — system of record)."""

import asyncpg

from hailmary.config import Settings


async def get_pg_connection(settings: Settings) -> asyncpg.Connection:
    return await asyncpg.connect(dsn=settings.postgres_dsn)
