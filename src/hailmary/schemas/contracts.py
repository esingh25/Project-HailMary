"""Inter-phase contracts (DESIGN.md §4). Transcribed verbatim — this module is frozen.

Any change here requires updating docs/DESIGN.md §4 first. No phase reads another
phase's internal working state; these Pydantic models are the only contract between
phases.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


# ── Query intake ────────────────────────────────────────────────────────────
class ResearchQuery(BaseModel):
    query_id: str
    user_id: str
    session_id: str
    raw_text: str
    sport: Literal["nfl", "cfb"]
    received_at: datetime


# ── Phase 1 output: the deterministic retrieval plan ─────────────────────────
class QueryEntities(BaseModel):
    teams: list[str]  # resolved to canonical team_ids downstream
    players: list[str]  # resolved to canonical player_ids downstream
    game_id: str | None
    week: int | None
    season: int


class Condition(BaseModel):
    field: str  # e.g. "pass_yards", "opponent_def_rank"
    operator: Literal["gt", "lt", "eq", "gte", "lte", "in", "between"]
    value: str | int | float | list  # JSON-serializable


class RetrievalPlan(BaseModel):
    query_id: str
    intent: Literal["spread", "total", "moneyline", "player_prop", "futures", "general"]
    entities: QueryEntities
    conditions: list[Condition]
    # Deterministically derived from intent+entities, NOT chosen by the LLM:
    target_indexes: list[
        Literal["stats_es", "semantic_vector", "live_odds", "live_injury", "weather"]
    ]
    prompt_version: str  # for cache keying and stale-plan detection


# ── Phase 0 records (indexed; not passed between query phases) ────────────────
class StatRecord(BaseModel):  # → Elasticsearch
    record_id: str  # canonical; upsert key
    sport: Literal["nfl", "cfb"]
    season: int
    week: int | None
    team_id: str
    player_id: str | None
    game_id: str | None
    fields: dict  # structured stat fields (passYards, epa, ...)
    text_blob: str  # denormalized text for BM25
    content_hash: str  # SHA-256 of normalized source record
    indexed_at: datetime


class SemanticDoc(BaseModel):  # → Qdrant
    doc_id: str
    sport: Literal["nfl", "cfb"]
    doc_type: Literal["game_recap", "scouting_note", "injury_context", "analysis"]
    text: str
    embedding_model: str
    source: str
    published_at: datetime
    content_hash: str


class OddsSnapshot(BaseModel):  # → live-feed cache (Redis + Postgres archive)
    game_id: str
    book: str
    market: Literal["spread", "moneyline", "total", "player_prop"]
    selection: str
    line: float | None
    price: int  # American odds
    captured_at: datetime


class InjuryRecord(BaseModel):  # → live-feed cache
    player_id: str
    team_id: str
    status: Literal["out", "doubtful", "questionable", "probable", "active"]
    body_part: str | None
    report_date: datetime


class TeamRating(BaseModel):  # → Postgres team_ratings (nightly Elo job)
    team_id: str
    sport: Literal["nfl", "cfb"]
    season: int
    rating: float  # Elo-style power rating
    as_of: datetime


# ── Phase 2 output: retrieved evidence ───────────────────────────────────────
class RetrievedChunk(BaseModel):
    chunk_id: str
    source: Literal["stats_es", "semantic_vector", "live_odds", "live_injury", "weather"]
    content: str  # human-readable evidence text
    structured_data: dict | None  # original structured payload when applicable
    index_score: float | None  # raw score from the index (pre-rerank)
    freshness_ts: datetime  # as-of time of the underlying data
    retrieved_at: datetime


class RetrievedContext(BaseModel):
    query_id: str
    chunks: list[RetrievedChunk]
    sources_attempted: list[str]
    sources_failed: list[str]  # for graceful-degradation reporting


# ── Phase 3 output: merged, reranked, cache-resolved ─────────────────────────
class MergedContext(BaseModel):
    query_id: str
    ranked_chunks: list[RetrievedChunk]  # deduped + reranked, truncated to budget
    cache_hit: bool
    dropped_stale: int  # count dropped on freshness gate
    rerank_model: str


# ── Phase 4 output: the report ───────────────────────────────────────────────
class EdgeAnalysis(BaseModel):
    """Deterministic. Computed in Python from retrieved odds + the power-rating
    probability. The LLM never produces these numbers."""

    market: str
    selection: str
    american_odds: int
    implied_probability: float
    model_probability: float | None  # None outside spread/moneyline coverage
    expected_value_pct: float | None  # None when model_probability is None
    assessment: Literal["value", "fair", "no_value", "insufficient_data"]


class Citation(BaseModel):
    claim: str
    chunk_id: str
    source: str


class ResearchReport(BaseModel):
    query_id: str
    summary: str  # LLM prose, every claim cited
    matchup_analysis: str
    key_factors: list[str]  # injuries, weather, trends (each cited)
    line_movement: str  # opening → current, cited to odds chunks
    edge_analysis: list[EdgeAnalysis]  # deterministic math block
    citations: list[Citation]
    line_as_of: datetime  # freshness stamp of most volatile input
    sources_unavailable: list[str]  # degraded-mode disclosure
    responsible_gaming_notice: str  # always present, deterministic
    replay_mode: bool  # true when built from the fixture
    generated_at: datetime
    model_version: str
    prompt_version: str


# ── Phase 5 logging ──────────────────────────────────────────────────────────
class SessionTurn(BaseModel):
    session_id: str
    user_id: str
    direction: Literal["inbound", "outbound"]
    text: str
    query_id: str | None
    resolved_entities: QueryEntities | None  # carried forward for follow-ups
    timestamp: datetime
