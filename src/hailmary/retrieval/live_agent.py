"""Live sub-agent -> Redis hot cache (DESIGN.md §5 Phase 2).

"Pull current OddsSnapshots for the game's markets, current InjuryRecords for
both rosters, weather. These carry the freshest freshness_ts." Mode-agnostic —
Redis was already populated identically by Phase 0 whether ingestion ran in
replay or live mode, so this sub-agent never checks REPLAY_MODE.
"""

from datetime import datetime

from hailmary.clients.redis import (
    injury_key,
    injury_scan_pattern,
    odds_key,
    odds_scan_pattern,
    weather_key,
)
from hailmary.schemas.contracts import InjuryRecord, OddsSnapshot, RetrievedChunk
from hailmary.schemas.internal import WeatherRecord


async def _scan_values(redis_client, pattern: str) -> list[str]:
    values: list[str] = []
    async for key in redis_client.scan_iter(match=pattern):
        value = await redis_client.get(key)
        if value is not None:
            values.append(value)
    return values


async def fetch_odds(redis_client, game_id: str, now: datetime) -> list[RetrievedChunk]:
    chunks = []
    for raw in await _scan_values(redis_client, odds_scan_pattern(game_id)):
        snap = OddsSnapshot.model_validate_json(raw)
        chunks.append(
            RetrievedChunk(
                chunk_id=odds_key(snap.game_id, snap.book, snap.market, snap.selection),
                source="live_odds",
                content=f"{snap.selection} at {snap.price} ({snap.book})",
                structured_data=snap.model_dump(mode="json"),
                index_score=None,
                freshness_ts=snap.captured_at,
                retrieved_at=now,
            )
        )
    return chunks


async def fetch_injuries(redis_client, team_id: str, now: datetime) -> list[RetrievedChunk]:
    chunks = []
    for raw in await _scan_values(redis_client, injury_scan_pattern(team_id)):
        rec = InjuryRecord.model_validate_json(raw)
        chunks.append(
            RetrievedChunk(
                chunk_id=injury_key(rec.team_id, rec.player_id),
                source="live_injury",
                content=f"{rec.player_id} is {rec.status} ({rec.body_part})",
                structured_data=rec.model_dump(mode="json"),
                index_score=None,
                freshness_ts=rec.report_date,
                retrieved_at=now,
            )
        )
    return chunks


async def fetch_weather(redis_client, game_id: str, now: datetime) -> list[RetrievedChunk]:
    raw = await redis_client.get(weather_key(game_id))
    if raw is None:
        return []
    rec = WeatherRecord.model_validate_json(raw)
    return [
        RetrievedChunk(
            chunk_id=weather_key(game_id),
            source="weather",
            content=(
                f"{rec.temperature_f}F, {rec.wind_mph}mph wind, {rec.precipitation_pct}% precip"
            ),
            structured_data=rec.model_dump(mode="json"),
            index_score=None,
            freshness_ts=rec.captured_at,
            retrieved_at=now,
        )
    ]
