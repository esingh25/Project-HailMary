"""Internal helper models — not part of the frozen DESIGN.md §4 inter-phase contracts.

These support single modules and may change without touching the design doc.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from hailmary.schemas.contracts import Condition


class GameResult(BaseModel):
    """One completed game, as input to the nightly Elo ratings job.

    `sport` lets ingestion/elo.update() reject a batch that accidentally mixes
    sports — the ratings dict it operates on is a flat team_id -> rating map with
    no sport partition, so a cross-sport team_id collision would otherwise
    silently corrupt both sports' ratings.
    """

    sport: Literal["nfl", "cfb"]
    home_team_id: str
    away_team_id: str
    home_score: int
    away_score: int


class ClarificationNeeded(BaseModel):
    """Returned by entity resolution when a surname collision can't be resolved
    deterministically. Phase 5 asks the user which entity was meant."""

    query_id: str
    ambiguous_name: str
    candidate_ids: list[str]


class PlayerAliasEntry(BaseModel):
    """One (name, team_id) -> player_id row in the canonical entity map.

    DESIGN.md §5 Phase 0: "Same-surname disambiguation handled here by storing
    (name, team_id) -> player_id."
    """

    team_id: str
    player_id: str
    full_name: str


class EntityMap(BaseModel):
    """Canonical alias tables built by Phase 0 ingestion (DESIGN.md §5 Phase 0)."""

    team_aliases: dict[str, str]  # normalized alias -> team_id
    players: dict[str, list[PlayerAliasEntry]]  # normalized name -> candidate rows


class WeatherRecord(BaseModel):
    """Open-Meteo venue weather for an outdoor game (DESIGN.md §5 Phase 0).

    Not one of the frozen §4 contracts — DESIGN.md names weather as a live-feed
    source without a formal Pydantic schema, so this fills that gap.
    """

    game_id: str
    temperature_f: float
    wind_mph: float
    precipitation_pct: float
    captured_at: datetime


class GuardrailResult(BaseModel):
    """Phase 1 guardrail classification (DESIGN.md §5 Phase 1): "A low-latency
    Haiku classify call rejects out-of-scope inputs... before any retrieval."
    """

    in_scope: bool
    reason: str | None = None


class RawEntityExtraction(BaseModel):
    """Raw LLM extraction, before deterministic entity resolution (DESIGN.md §5
    Phase 1). team_names/player_names are as mentioned in the query (e.g.
    "Chiefs", "Mahomes") — decompose/resolution.py resolves these to canonical
    IDs; the LLM never picks the IDs or the target_indexes itself.
    """

    intent: Literal["spread", "total", "moneyline", "player_prop", "futures", "general"]
    team_names: list[str]
    player_names: list[str]
    week: int | None
    season: int
    conditions: list[Condition]
