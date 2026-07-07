"""Postgres connection factory (DESIGN.md §6.4 — system of record).

The §6.4 DDL uses TIMESTAMP (without time zone) columns, while the codebase
passes timezone-aware UTC datetimes everywhere. asyncpg refuses to encode an
aware datetime into a naive column, so this factory installs a codec at the
single connection choke point: aware datetimes are normalized to UTC and
stripped on the way in; column values come back as aware UTC on the way out,
matching the convention used everywhere else.
"""

from datetime import UTC, datetime

import asyncpg

from hailmary.config import Settings


def encode_timestamp(dt: datetime) -> str:
    """Render a datetime for a TIMESTAMP column; aware values become naive UTC."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.isoformat(sep=" ")


def decode_timestamp(text: str) -> datetime:
    """Parse a TIMESTAMP column value as aware UTC."""
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


async def get_pg_connection(settings: Settings) -> asyncpg.Connection:
    conn = await asyncpg.connect(dsn=settings.postgres_dsn)
    await conn.set_type_codec(
        "timestamp",
        schema="pg_catalog",
        encoder=encode_timestamp,
        decoder=decode_timestamp,
        format="text",
    )
    return conn
