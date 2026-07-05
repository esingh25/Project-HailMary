"""Unified event log + ingestion heartbeats (DESIGN.md §10 Observability).

"Unified event log (events table): every phase writes significant transitions...
First stop for debugging 'what happened to query X?'" / "Ingestion heartbeats: each
worker loop writes ingestion_log rows." Both are single choke-point functions so no
phase hand-rolls its own logging shape.
"""

import json
from datetime import UTC, datetime

import asyncpg


async def record_event(
    pg: asyncpg.Connection,
    phase: str,
    event: str,
    query_id: str | None = None,
    detail: dict | None = None,
) -> None:
    await pg.execute(
        "INSERT INTO events (query_id, phase, event, detail, ts) VALUES ($1, $2, $3, $4, $5)",
        query_id,
        phase,
        event,
        json.dumps(detail) if detail is not None else None,
        datetime.now(UTC),
    )


async def record_ingestion(
    pg: asyncpg.Connection,
    source: str,
    records: int,
    status: str,
    detail: dict | None = None,
) -> None:
    if status not in ("ok", "partial", "failed"):
        raise ValueError(f"Unknown ingestion status: {status!r}")

    await pg.execute(
        "INSERT INTO ingestion_log (source, records, status, ran_at, detail) "
        "VALUES ($1, $2, $3, $4, $5)",
        source,
        records,
        status,
        datetime.now(UTC),
        json.dumps(detail) if detail is not None else None,
    )
