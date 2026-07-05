# HailMaryRAG — Technical Design Document (MVP)

**Status:** v1.0 — FROZEN. All open decisions from the draft (§13) are resolved and folded
into the phase specs below. Ready to build.

**Project purpose:** Portfolio project demonstrating RAG architecture and vector-database
engineering in action: hybrid retrieval (BM25 + dense vectors + live feeds), deterministic
merge/rerank with a local cross-encoder, grounded cited synthesis, and a semantic cache.
The system must function end-to-end, but it is built for small-scale local use with a
management dashboard. No public website, no shared multi-tenant database, no cloud
deployment.

**Scope:** Full MVP — an agentic research assistant that breaks down a natural-language
betting/trading question about NFL or College Football, retrieves evidence from multiple
indexes (Elasticsearch + Qdrant + live feeds), and synthesizes a grounded, cited research
report. Evidence-first: the guaranteed deliverable is synthesized, cited evidence (line
movement, injuries, weather, matchup trends); deterministic edge math is a bonus computed
whenever the power-rating heuristic applies (spreads and moneylines).

**Owner:** Solo build. Phase labels below are organizational, not staffing.

---

## 1. Overview

HailMaryRAG is an autonomous research assistant operated through a local API with a thin
chat surface and a Streamlit management dashboard. A user asks a question in natural
language — *"Is there value on KC -6.5 vs the Raiders given Mahomes' Thursday-night history
and the current injury picture?"* — and the system decomposes the query, fans it out across
specialized retrieval indexes, merges and reranks the evidence, computes deterministic
line-value math where a model probability exists, and returns a structured research report
with citations back to the retrieved sources.

The product is a **research tool, not a tipster service and not financial advice.** It lays
out the evidence — injuries, statistical matchup edges, weather, line movement, historical
trends — and the math behind any edge it surfaces, so the user makes their own informed
decision. See §12 (Responsible Gaming & Compliance).

The MVP ships with **two pipelines**:

- An **asynchronous ingestion pipeline** (Phase 0) that pulls from free-tier data feeds on
  a demo-appropriate schedule and populates the indexes. Scheduled via APScheduler,
  queue-tracked, no synthesis LLM. Includes a **replay/fixture mode** so the full pipeline
  runs deterministically against one archived week of real data, year-round, with no live
  games and no feed dependency.
- A **synchronous query pipeline** (Phases 1–5) that answers a single research question per
  request, orchestrated as a LangGraph state graph.

External services are the free-tier data feeds (nflverse via `nfl_data_py`,
CollegeFootballData.com, The Odds API free tier, Open-Meteo), Anthropic (Claude Haiku +
Sonnet), and Voyage embeddings (free tier). Rerank runs locally. All other compute is
self-hosted on one machine via Docker Compose.

---

## 2. Architecture Summary

Centralized ingestion feeds two indexes: a structured **Elasticsearch** index (single node)
for exact/filterable/keyword retrieval (BM25 over game logs, player stats, team metrics)
and **Qdrant** for semantic retrieval over unstructured prose (game recaps, scouting notes,
beat-writer context). A third retrieval path hits **live feeds** directly for data too
volatile to index (current odds, line movement, today's injury report) — or the replay
fixture when replay mode is on.

The query pipeline is an orchestrated graph. A low-latency model classifies and decomposes
the query into a deterministic `RetrievalPlan`. Three retrieval sub-agents execute that plan
against their assigned indexes. A deterministic merge/rerank stage dedupes and orders the
evidence (local cross-encoder, not the LLM). A synthesis stage computes line-value math
deterministically and writes a grounded report citing only retrieved chunks. The delivery
layer manages session memory so follow-up questions inherit prior entity resolution.

```
                        ASYNC INGESTION PIPELINE
   ┌────────────┐     ┌──────────────────────────────────────────────┐
   │  Sources   │ ──► │ Phase 0: ingestion + normalize + index        │
   │ free feeds │     │  → Elasticsearch (structured/BM25)            │
   │ or fixture │     │  → Qdrant (semantic embeddings)               │
   └────────────┘     │  → Live-feed cache (odds, injuries)           │
                      │  → team_ratings (nightly Elo job)             │
                      └──────────────────────────────────────────────┘
                                       │  (indexes populated)
   ════════════════════════════════════╪══════════════════════════════
                                       ▼  SYNC QUERY PIPELINE (LangGraph)
   ┌────────────┐     ┌──────────────────────┐
   │ User query │ ──► │ Phase 1: decompose    │  Haiku: guardrail +
   │ (local API)│     │  → RetrievalPlan       │  entity/intent/condition
   └────────────┘     └──────────┬───────────┘  extraction (classification)
                                 ▼
                      ┌──────────────────────┐
                      │ Phase 2: retrieve     │  3 sub-agents, deterministic
                      │ stats │ semantic │ live│ query construction
                      └──────────┬───────────┘
                                 ▼
                      ┌──────────────────────┐
                      │ Phase 3: merge+rerank │  semantic cache, dedup,
                      │  → MergedContext       │  local cross-encoder (no LLM)
                      └──────────┬───────────┘
                                 ▼
                      ┌──────────────────────┐
                      │ Phase 4: synthesis    │  deterministic EV/edge math
                      │  → ResearchReport      │  + grounded, cited writing
                      └──────────┬───────────┘
                                 ▼
                      ┌──────────────────────┐
                      │ Phase 5: delivery     │  API response, Redis session,
                      │  → user + session mem │  follow-up handling
                      └──────────────────────┘

   ┌─────────────────────────────────────────────────────────────────┐
   │ Streamlit dashboard: ingestion health, query traces, cache      │
   │ stats, cost tracking, replay-mode toggle (reads Postgres/Redis) │
   └─────────────────────────────────────────────────────────────────┘
```

---

## 3. Core Philosophy

These are committed architectural principles. Implementation details remain open.

1. **Phase isolation is contract-based, not storage-based.** Phases share a single Postgres
   instance plus shared indexes (Elasticsearch, Qdrant, Redis); the storage layer is
   coupled. Isolation lives at the Pydantic schema layer. No phase reads another phase's
   internal working state — only the canonical contract outputs.

2. **Schemas define all interfaces.** Pydantic models are the only contract between phases.
   No implicit coupling or undocumented fields. The LLM-facing structured outputs are
   validated by `instructor` against these schemas; malformed model output is rejected, not
   coerced.

3. **Deterministic logic governs retrieval and business decisions.** Index routing,
   candidate filtering, relevance reranking, cache eligibility, freshness gating, line-value
   math, power ratings, and responsible-gaming policy are all deterministic Python. None of
   these depend on LLM output.

4. **LLMs are restricted to decomposition and synthesis.**
   - **Allowed:** Phase 1 (query classification + entity/intent/condition extraction),
     Phase 4 (report prose generation from already-retrieved, already-ranked evidence),
     Phase 5 (conversational follow-up phrasing).
   - **Forbidden everywhere:** relevance ranking of retrieved chunks (use the reranker),
     index routing decisions (deterministic from extracted entities), any arithmetic on
     odds/probabilities/edge/EV (deterministic math), and any "should the user bet this"
     verdict (the system surfaces evidence and math; it does not place or recommend wagers).
   - The pattern is **LLMs propose, deterministic Python disposes.**

5. **Synthesis is grounded.** Phase 4 writes only from the `MergedContext` it is handed.
   Every factual claim in the report must carry a citation to a retrieved `chunk_id`. Claims
   that cannot be grounded in retrieved evidence are dropped, not filled from model training
   data. A post-generation citation guard enforces this.

6. **Freshness is a first-class contract.** Odds and injuries decay in minutes. Every
   retrieved chunk carries a `freshness_ts`. Phase 3 drops or down-ranks stale evidence per
   per-source TTLs. The report stamps the as-of time of its most volatile input (the line).
   In replay mode, "now" is the fixture's virtual clock, so freshness logic still exercises
   end-to-end.

7. **All state is explicitly persisted.** Postgres is the system of record for queries,
   plans, reports, ratings, the cache index, and the ingestion log. Indexes (ES, Qdrant,
   Redis) are derived caches, rebuildable from source feeds and Postgres.

8. **Ingestion is pull-based and idempotent.** Re-ingesting the same source record must not
   create duplicate index documents. Dedup is by deterministic content hash; index writes
   are upserts keyed by canonical record ID.

9. **External systems are unreliable.** All feeds, LLM APIs, and the embedding API are
   treated as failure-prone and wrapped in retry-safe, circuit-broken clients. A query that
   loses one retrieval source degrades gracefully (partial evidence + an explicit note), it
   does not fail the whole report. Replay mode is the ultimate fallback: the demo never
   depends on a live feed being up.

10. **The report is advisory.** Output is informational research, not financial advice. The
    responsible-gaming notice is a deterministic chokepoint, not optional copy. See §12.

11. **Evidence-first.** The guaranteed deliverable of every report is synthesized, cited
    evidence: line movement vs. open, market-implied probabilities, injury/weather deltas,
    and the historical trends the user asked about. `EdgeAnalysis` EV math appears when the
    power-rating heuristic covers the market (spreads, moneylines) and honestly reads
    `insufficient_data` when it does not (props, futures). The report never leads with an
    edge verdict; it leads with evidence.

---

## 4. Inter-Phase Contracts (Pydantic Schemas)

All inter-phase data flows through these typed contracts. Module boundaries are these
schemas; no phase reads another phase's internal working state.

```python
from pydantic import BaseModel
from typing import Literal
from datetime import datetime

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
    teams: list[str]                 # resolved to canonical team_ids downstream
    players: list[str]               # resolved to canonical player_ids downstream
    game_id: str | None
    week: int | None
    season: int

class Condition(BaseModel):
    field: str                       # e.g. "pass_yards", "opponent_def_rank"
    operator: Literal["gt", "lt", "eq", "gte", "lte", "in", "between"]
    value: str | int | float | list  # JSON-serializable

class RetrievalPlan(BaseModel):
    query_id: str
    intent: Literal[
        "spread", "total", "moneyline", "player_prop", "futures", "general"
    ]
    entities: QueryEntities
    conditions: list[Condition]
    # Deterministically derived from intent+entities, NOT chosen by the LLM:
    target_indexes: list[Literal[
        "stats_es", "semantic_vector", "live_odds", "live_injury", "weather"
    ]]
    prompt_version: str              # for cache keying and stale-plan detection

# ── Phase 0 records (indexed; not passed between query phases) ────────────────
class StatRecord(BaseModel):         # → Elasticsearch
    record_id: str                   # canonical; upsert key
    sport: Literal["nfl", "cfb"]
    season: int
    week: int | None
    team_id: str
    player_id: str | None
    game_id: str | None
    fields: dict                     # structured stat fields (passYards, epa, ...)
    text_blob: str                   # denormalized text for BM25
    content_hash: str                # SHA-256 of normalized source record
    indexed_at: datetime

class SemanticDoc(BaseModel):        # → Qdrant
    doc_id: str
    sport: Literal["nfl", "cfb"]
    doc_type: Literal["game_recap", "scouting_note", "injury_context", "analysis"]
    text: str
    embedding_model: str
    source: str
    published_at: datetime
    content_hash: str

class OddsSnapshot(BaseModel):       # → live-feed cache (Redis + Postgres archive)
    game_id: str
    book: str
    market: Literal["spread", "moneyline", "total", "player_prop"]
    selection: str
    line: float | None
    price: int                       # American odds
    captured_at: datetime

class InjuryRecord(BaseModel):       # → live-feed cache
    player_id: str
    team_id: str
    status: Literal["out", "doubtful", "questionable", "probable", "active"]
    body_part: str | None
    report_date: datetime

class TeamRating(BaseModel):         # → Postgres team_ratings (nightly Elo job)
    team_id: str
    sport: Literal["nfl", "cfb"]
    season: int
    rating: float                    # Elo-style power rating
    as_of: datetime

# ── Phase 2 output: retrieved evidence ───────────────────────────────────────
class RetrievedChunk(BaseModel):
    chunk_id: str
    source: Literal[
        "stats_es", "semantic_vector", "live_odds", "live_injury", "weather"
    ]
    content: str                     # human-readable evidence text
    structured_data: dict | None     # original structured payload when applicable
    index_score: float | None        # raw score from the index (pre-rerank)
    freshness_ts: datetime           # as-of time of the underlying data
    retrieved_at: datetime

class RetrievedContext(BaseModel):
    query_id: str
    chunks: list[RetrievedChunk]
    sources_attempted: list[str]
    sources_failed: list[str]        # for graceful-degradation reporting

# ── Phase 3 output: merged, reranked, cache-resolved ─────────────────────────
class MergedContext(BaseModel):
    query_id: str
    ranked_chunks: list[RetrievedChunk]   # deduped + reranked, truncated to budget
    cache_hit: bool
    dropped_stale: int                    # count dropped on freshness gate
    rerank_model: str

# ── Phase 4 output: the report ───────────────────────────────────────────────
class EdgeAnalysis(BaseModel):
    """Deterministic. Computed in Python from retrieved odds + the power-rating
    probability. The LLM never produces these numbers."""
    market: str
    selection: str
    american_odds: int
    implied_probability: float
    model_probability: float | None       # None outside spread/moneyline coverage
    expected_value_pct: float | None       # None when model_probability is None
    assessment: Literal["value", "fair", "no_value", "insufficient_data"]

class Citation(BaseModel):
    claim: str
    chunk_id: str
    source: str

class ResearchReport(BaseModel):
    query_id: str
    summary: str                          # LLM prose, every claim cited
    matchup_analysis: str
    key_factors: list[str]                # injuries, weather, trends (each cited)
    line_movement: str                    # opening → current, cited to odds chunks
    edge_analysis: list[EdgeAnalysis]     # deterministic math block
    citations: list[Citation]
    line_as_of: datetime                  # freshness stamp of most volatile input
    sources_unavailable: list[str]        # degraded-mode disclosure
    responsible_gaming_notice: str        # always present, deterministic
    replay_mode: bool                     # true when built from the fixture
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
    resolved_entities: QueryEntities | None   # carried forward for follow-ups
    timestamp: datetime
```

---

## 5. Phase Specifications

Per-phase format: Locked tools · Input · Output · Must accomplish · Must NOT do ·
Design freedom.

### Phase 0: Ingestion & Indexing

**Locked tools:** `nfl_data_py` (nflverse), `httpx`, Elasticsearch Python client, Qdrant
client, Voyage embedding API, Postgres, Redis, APScheduler. No LLM.
**Input:** Free-tier data feeds (nflverse, CollegeFootballData.com, The Odds API free
tier, Open-Meteo), scraped news/recap pages from a small curated source list — or the
replay fixture.
**Output:** `StatRecord` docs in Elasticsearch; `SemanticDoc` vectors in Qdrant;
`OddsSnapshot` / `InjuryRecord` in the live-feed cache (Redis hot + Postgres archive);
`TeamRating` rows in Postgres; `ingestion_log` rows in Postgres.

**Must accomplish:**
- Pull structured stats from **nflverse via `nfl_data_py`** (NFL: weekly stats, play-by-play
  aggregates, injuries, depth charts) and **CollegeFootballData.com** (CFB) on the schedule
  below; normalize to `StatRecord`; SHA-256 the normalized record for `content_hash`;
  **upsert** into Elasticsearch keyed by `record_id` (idempotent).
- Pull odds from **The Odds API free tier** (500 requests/month budget) on the relaxed
  schedule below; write `OddsSnapshot` to the live-feed cache and append to the Postgres
  `odds_archive` for line-movement history (opening → current).
- Pull NFL injury reports from nflverse; write `InjuryRecord`.
- Scrape/ingest unstructured prose (recaps, scouting notes) from a curated source list,
  normalize, dedup by `content_hash`, embed with Voyage, **upsert** into Qdrant keyed by
  `doc_id`.
- Pull Open-Meteo weather for outdoor venues for upcoming games.
- **Nightly ratings job:** compute Elo-style team power ratings from game results in
  Elasticsearch/Postgres and upsert `TeamRating` rows. Standard Elo with home-field
  constant and margin-of-victory multiplier; K-factor and constants live in config. This is
  the sole source of `model_probability` downstream.
- Maintain a canonical **entity map** (team aliases → `team_id`, player names → `player_id`)
  so downstream entity resolution is deterministic. Same-surname disambiguation handled here
  by storing `(name, team_id) → player_id`.
- **Replay/fixture mode.** `scripts/build_fixture.py` archives one full real week of the
  season (stats, an odds-snapshot time series, injuries, weather, recaps) into versioned
  fixture files + a Postgres fixture schema. With `REPLAY_MODE=true`, all feed clients read
  from the fixture and the system clock used for freshness math is a virtual clock pinned
  inside the fixture week. The entire pipeline — ingestion through report — runs
  deterministically with zero external feed calls. This is the default demo path.
- Rate-aware scheduling per source via APScheduler in a single worker process; track the
  Odds API monthly request budget in Postgres and refuse calls that would exceed it.

**Must NOT do:**
- No synthesis LLM calls. (Embedding API calls are permitted — they are deterministic
  transforms, not generation.)
- No relevance scoring or ranking. Pure ingest + index.
- No retention of raw HTML once normalized text is extracted.
- No user-specific logic — the evidence pool is global.
- No exceeding the Odds API free-tier budget; the budget guard is hard, not advisory.

**Design freedom:**
- Normalization regex and boilerplate stripping per source.
- Embedding chunk size and overlap.
- Elo constants (K, home-field, MOV multiplier) — config-tunable.
- Fixture week selection and file format.

**Per-source cadence (demo-appropriate, live mode):**

| Source | Cadence | Index target |
|---|---|---|
| Odds (The Odds API free) | 3–4 snapshots/day in-season; manual "tighten" button on the dashboard for a chosen demo game | live cache + archive |
| Injuries (nflverse) | 2×/day, plus manual refresh | live cache |
| NFL stats (nflverse) | post-game day + nightly backfill | Elasticsearch |
| CFB stats (CFBD) | post-game day + nightly backfill | Elasticsearch |
| News/recaps/scouting (curated scrape) | 2×/day | Qdrant |
| Weather (Open-Meteo) | 2×/day, hourly within 24h of a tracked kickoff | live cache |
| Ratings job | nightly | Postgres |

Replay mode ignores this table and serves the fixture.

---

### Phase 1: Query Intake & Decomposition (Orchestrator)

**Locked tools:** Claude **Haiku 4.5** (classifier + extractor), `instructor` for structured
output, Pydantic, LangGraph (entry node), Redis (session read for follow-up context),
Postgres.
**Input:** `ResearchQuery` (+ session context from Phase 5).
**Output:** `RetrievalPlan` persisted to Postgres; passed to Phase 2 in-graph.

**Must accomplish:**
- **Guardrail first.** A low-latency Haiku classify call rejects out-of-scope inputs
  (non-football, non-research) with a polite message before any retrieval.
- **Decompose** the query into `QueryEntities` (teams, players, game, week, season),
  `intent` (spread / total / moneyline / player_prop / futures / general), and a list of
  `Condition`s ("last 3 home games", "vs top-10 defenses", ">10 air yards").
- **Resolve entities deterministically** against the Phase 0 entity map. On ambiguous
  surname collisions, return a `clarification_needed` signal to Phase 5 (ask the user which
  player) and store the partial resolution — do not guess.
- **Derive `target_indexes` deterministically** from `intent` + `entities` via a routing
  table. A player-prop query routes to stats_es + live_odds + live_injury; a total routes
  to stats_es + weather + live_odds + semantic; etc. The LLM does not choose indexes.
- Stamp the plan with `prompt_version` for cache keying.

**Must NOT do:**
- No retrieval. Phase 1 plans; Phase 2 executes.
- No index-routing decision delegated to the LLM (deterministic mapping table only).
- No arithmetic, no edge estimation, no bet verdict.
- No free-text the user didn't ask for fed into entity extraction (only `raw_text` +
  resolved session entities).

**Design freedom:**
- Prompt + few-shot examples for extraction.
- The deterministic intent → index routing table contents.
- Clarification UX trigger thresholds.

---

### Phase 2: Multi-Index Retrieval

**Locked tools:** Elasticsearch client, Qdrant client, Redis, `httpx` for any direct feed
reads, Postgres. **No LLM.**
**Input:** `RetrievalPlan`.
**Output:** `RetrievedContext`.

Three sub-agents execute the plan in parallel against their assigned indexes. "Sub-agent"
here means a deterministic retrieval function with a fixed query template — not an LLM loop.

**Must accomplish:**
- **Stats sub-agent → Elasticsearch.** Translate `entities` + `conditions` into a structured
  ES query (filters on team/player/week/season + `conditions` as range/term filters; BM25
  over `text_blob` for fuzzy phrasing). Return top-K `StatRecord`-derived chunks. Only the
  relevant ES schema fields are queried.
- **Semantic sub-agent → Qdrant.** Embed the query (Voyage), run payload-filtered ANN
  search over the relevant `doc_type`s, return top-K `SemanticDoc`-derived chunks with
  similarity scores.
- **Live sub-agent → live-feed cache.** Pull current `OddsSnapshot`s for the game's markets,
  current `InjuryRecord`s for both rosters, weather. These carry the freshest
  `freshness_ts`. In replay mode this reads the fixture at the virtual clock.
- Tag every chunk with `source`, `index_score`, and `freshness_ts`.
- **Graceful degradation:** if a source times out or errors (circuit breaker open), record
  it in `sources_failed` and continue. A missing live-odds source is reported; it does not
  abort the query.
- SLO: p95 < 2.5s for the full fan-out (parallel, bounded per-source timeout).

**Must NOT do:**
- No reranking or relevance judgment here (that is Phase 3).
- No LLM calls.
- No synthesis or summarization of chunks (return evidence verbatim/structured).
- No unbounded queries — every ES/Qdrant query is K-bounded and filter-bounded.

**Design freedom:**
- ES query DSL specifics and field boosts.
- K per source and per-source timeout budgets.
- Whether the live sub-agent reads Redis only or falls back to a direct feed call on cache
  miss (budget guard permitting).

---

### Phase 3: Merge, Dedup & Rerank

**Locked tools:** Local cross-encoder via `sentence-transformers`
(`cross-encoder/ms-marco-MiniLM-L-6-v2`; BGE reranker as a drop-in benchmark alternative),
Redis (semantic cache hot layer), Postgres (cache index), pure Python. **No synthesis LLM,
no rerank API dependency.**
**Input:** `RetrievedContext`.
**Output:** `MergedContext`.

**Must accomplish:**
- **Semantic cache lookup (first step).** Embed a normalized form of the query (entities
  replaced by placeholders, e.g. `[TEAM]`, `[PLAYER]`, `[WEEK]`) and ANN-search the cache.
  On a hit at **cosine ≥ 0.92** with non-stale evidence, reuse the prior `MergedContext`
  with fresh entity IDs and skip rerank. Live-odds chunks are always refreshed even on a
  cache hit.
- **Dedup** across sources (same injury surfaced by both the live feed and a scouting doc →
  keep the freshest, highest-scored instance).
- **Freshness gate.** Drop chunks whose `freshness_ts` exceeds the per-source TTL —
  starting values: odds 5 min (60 min virtual in replay mode), injuries 30 min, weather 3h,
  stats season-scoped, recaps 7 days. Count drops in `dropped_stale`.
- **Rerank** the surviving chunks with the local cross-encoder against the original query.
  Apply the recency-decay factor **after** the cross-encoder, as a deterministic
  multiplicative penalty in Python (exponential decay per source class; half-lives in
  config), so 48-hour-old injury info outranks 3-season-old trends and the decay is
  tunable and explainable independent of the model. Truncate to the synthesis context
  budget.
- Write the result to the semantic cache (placeholder form) for future reuse.

**Must NOT do:**
- No LLM-based relevance judgment — the reranker is the authority.
- No fabrication of chunks; only reorder/drop/dedup existing evidence.
- No serving stale odds from cache (live chunks always refreshed).

**Design freedom:**
- Decay half-lives per source class.
- Context budget (token cap handed to Phase 4).
- Cross-encoder batch size / ONNX optimization if latency demands.

---

### Phase 4: Synthesis & Edge Analysis

**Locked tools:** Claude **Sonnet 4.6** (report prose; sole synthesis model), `instructor` +
Pydantic for the structured `ResearchReport`, pure Python for all math, Postgres.
**Input:** `MergedContext` + `TeamRating` rows for the involved teams.
**Output:** `ResearchReport` persisted to Postgres; returned to Phase 5.

**Must accomplish:**
- **Compute `EdgeAnalysis` deterministically in Python**, before any prose generation:
  convert American odds → `implied_probability`; for **spreads and moneylines**, derive
  `model_probability` from the Elo rating difference + home field via a logistic mapping
  (constants in config, documented); compute `expected_value_pct`; classify `assessment`
  (value / fair / no_value) with configurable EV thresholds. For **props and futures**,
  `model_probability = None` and `assessment = "insufficient_data"` — no fabricated edge.
  The LLM never produces these numbers — it narrates them.
- **Lead with evidence.** The report template orders: summary of evidence → line movement
  (opening → current from `odds_archive`) → key factors (injuries, weather, trends) →
  matchup analysis → edge block last. The edge block is presented as supplementary math,
  not a verdict.
- **Generate grounded prose** (summary, matchup analysis, key factors, line-movement
  narrative) from `ranked_chunks` only. Pass the chunks as the sole evidence context;
  instruct the model to cite a `chunk_id` for every factual claim.
- **Citation guard (hallucination guard).** Post-generation, deterministically verify that
  every claim sentence maps to a cited `chunk_id` present in `MergedContext`. Uncited or
  mis-cited claims are stripped; if stripping leaves the report threadbare, regenerate up to
  2× with a tightened prompt, then fall back to an evidence-only structured summary (no free
  prose).
- **Stamp `line_as_of`** with the freshest odds chunk's `freshness_ts`; set `replay_mode`.
- **Disclose degradation:** populate `sources_unavailable` from
  `RetrievedContext.sources_failed`.
- **Always attach** the `responsible_gaming_notice` (deterministic, not model-generated).

**Must NOT do:**
- No arithmetic on odds, probabilities, edge, or stake performed by the LLM.
- No "you should bet X" verdict, no stake-sizing recommendation, no guaranteed-outcome
  language.
- No claims sourced from model training data — retrieved evidence only.
- No report shipped without passing the citation guard.
- No edge math for markets the rating heuristic doesn't cover — `insufficient_data` is the
  honest answer.

**Design freedom:**
- Report prose tone and few-shot examples.
- EV threshold cutoffs for the `assessment` buckets.
- Logistic mapping constants (documented alongside the Elo config).

---

### Phase 5: Delivery, Session & Dashboard

**Locked tools:** FastAPI, Redis (session state), Postgres, Claude Haiku 4.5 (follow-up
phrasing only), **Streamlit** (management dashboard), thin local web chat (plain HTML/JS
served by FastAPI).
**Input:** `ResearchReport` from Phase 4; inbound local API requests; `clarification_needed`
signals from Phase 1.
**Output:** Formatted response to the user; `SessionTurn` log rows; session memory updates.

**Must accomplish:**
- Expose `POST /research` (submit a query) and `GET /report/{query_id}` (fetch a prior
  report), bound to localhost. Stream the report to the chat surface.
- **Session memory (simplified):** last N turns held raw in Redis and injected into the
  next decomposition, plus resolved `QueryEntities` carried forward so *"what about his
  red-zone numbers?"* inherits the player from the prior turn. (Tiered mid-term summaries
  and long-term semantic memory are out of scope — §14.)
- **Clarification handling:** when Phase 1 returns `clarification_needed` (ambiguous
  player), ask the user which one, store the answer, and resume the same query with the
  resolved entity.
- Render the deterministic `EdgeAnalysis` block and citations faithfully; never paraphrase
  the math. Surface `replay_mode` and `line_as_of` visibly.
- Enforce the responsible-gaming surface: the notice is always shown. Jurisdiction/age
  gating is a config-flag stub (`GATING_ENABLED=false` locally) with the check function
  implemented as a deterministic chokepoint so the architecture demonstrates the principle
  (§12).
- **Management dashboard (Streamlit, localhost):** panels for (a) ingestion health — last
  run, status, record counts per source from `ingestion_log`; (b) query traces — the
  `events` timeline for any `query_id`; (c) cache stats — hit rate, entry age; (d) cost —
  LLM spend per query/day vs caps, Odds API request budget remaining; (e) controls —
  replay-mode toggle, manual ingestion triggers, "tighten odds cadence for game X".
  Dashboard reads Postgres/Redis directly; it never mutates report content.

**Must NOT do:**
- No mutation of report content (Phase 4 owns the report; Phase 5 formats and delivers).
- No LLM re-computation of any number in `EdgeAnalysis`.
- No persistence of sensitive PII in session memory.
- No bypass of the responsible-gaming notice.
- No public network binding — API and dashboard are localhost-only.

**Design freedom:**
- API response shape and streaming strategy.
- Chat surface styling.
- Dashboard layout and additional panels.

---

## 6. Index & Storage Architecture

Four storage systems, all local via **Docker Compose** (`postgres`, `elasticsearch`,
`qdrant`, `redis`, plus `api`, `worker`, `dashboard` services). Postgres is the system of
record; the rest are derived, rebuildable caches. Elasticsearch runs single-node with a
1–2 GB heap — ample for a demo corpus of a few seasons.

### 6.1 Elasticsearch (structured + BM25)

Indexes: `nfl_stats`, `cfb_stats`. Organized by schema (passing / rushing / defense / team)
so only the relevant field set is queried per request.

```jsonc
// nfl_stats mapping (sketch)
{
  "mappings": {
    "properties": {
      "record_id":   { "type": "keyword" },
      "season":      { "type": "integer" },
      "week":        { "type": "integer" },
      "team_id":     { "type": "keyword" },
      "player_id":   { "type": "keyword" },
      "game_id":     { "type": "keyword" },
      "schema_type": { "type": "keyword" },   // passing | rushing | defense | team
      "fields":      { "type": "object" },     // passYards, epa, airYards, ...
      "text_blob":   { "type": "text" },       // BM25 fuzzy phrasing
      "content_hash":{ "type": "keyword" },
      "indexed_at":  { "type": "date" }
    }
  }
}
```

### 6.2 Qdrant (semantic)

Collections: `game_recaps`, `scouting_notes`, `analysis`, plus `semantic_cache` (the query
cache lives here too, keeping all vectors in the vector DB). Each vector carries `sport`,
`doc_type`, `published_at`, `source`, `content_hash` as payload for filtered ANN search.
Voyage `voyage-3` embeddings (1024-dim, cosine distance). Collection config, payload
indexes, and snapshot/backup are part of the repo's documented setup.

### 6.3 Live-feed cache (Redis hot + Postgres archive)

`OddsSnapshot` and `InjuryRecord` live in Redis keyed by `game_id`/`player_id` for sub-ms
reads, with a TTL matching the source cadence. An append-only Postgres `odds_archive` table
retains line history for movement analysis (opening → current). In replay mode these keys
are populated from the fixture.

### 6.4 Postgres (system of record + DDL)

```sql
CREATE TABLE research_queries (
  query_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL,
  session_id    UUID NOT NULL,
  raw_text      TEXT NOT NULL,
  sport         TEXT NOT NULL,
  received_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE retrieval_plans (
  query_id       UUID PRIMARY KEY REFERENCES research_queries(query_id),
  intent         TEXT NOT NULL,
  entities       JSONB NOT NULL,
  conditions     JSONB NOT NULL,
  target_indexes TEXT[] NOT NULL,
  prompt_version TEXT NOT NULL,
  created_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE research_reports (
  query_id      UUID PRIMARY KEY REFERENCES research_queries(query_id),
  report        JSONB NOT NULL,          -- serialized ResearchReport
  line_as_of    TIMESTAMP NOT NULL,
  replay_mode   BOOLEAN NOT NULL DEFAULT FALSE,
  model_version TEXT NOT NULL,
  generated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE team_ratings (
  team_id     TEXT NOT NULL,
  sport       TEXT NOT NULL,
  season      INT NOT NULL,
  rating      REAL NOT NULL,
  as_of       TIMESTAMP NOT NULL,
  PRIMARY KEY (team_id, season)
);

CREATE TABLE semantic_cache_index (
  cache_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  placeholder_text TEXT NOT NULL,        -- query with [TEAM]/[PLAYER] placeholders
  qdrant_point_id  UUID NOT NULL,        -- vector lives in Qdrant
  merged_context  JSONB NOT NULL,        -- reusable MergedContext (sans live odds)
  prompt_version  TEXT NOT NULL,
  created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
  last_hit_at     TIMESTAMP
);

CREATE TABLE odds_archive (
  id           BIGSERIAL PRIMARY KEY,
  game_id      TEXT NOT NULL,
  book         TEXT NOT NULL,
  market       TEXT NOT NULL,
  selection    TEXT NOT NULL,
  line         REAL,
  price        INT NOT NULL,
  captured_at  TIMESTAMP NOT NULL
);
CREATE INDEX idx_odds_archive_game ON odds_archive (game_id, captured_at DESC);

CREATE TABLE api_budget (
  source       TEXT PRIMARY KEY,        -- e.g. 'the_odds_api'
  period_start DATE NOT NULL,
  calls_used   INT NOT NULL DEFAULT 0,
  calls_limit  INT NOT NULL             -- 500 for The Odds API free tier
);

CREATE TABLE ingestion_log (
  id           BIGSERIAL PRIMARY KEY,
  source       TEXT NOT NULL,
  records      INT NOT NULL,
  status       TEXT NOT NULL,           -- ok | partial | failed
  ran_at       TIMESTAMP NOT NULL DEFAULT NOW(),
  detail       JSONB
);

CREATE TABLE events (
  id           BIGSERIAL PRIMARY KEY,
  query_id     UUID,
  phase        TEXT NOT NULL,
  event        TEXT NOT NULL,           -- plan_built | fanout_done | cache_hit | ...
  detail       JSONB,
  ts           TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_events_query ON events (query_id, ts);

CREATE TABLE session_turns (
  id                BIGSERIAL PRIMARY KEY,
  session_id        UUID NOT NULL,
  user_id           UUID NOT NULL,
  direction         TEXT NOT NULL,
  text              TEXT NOT NULL,
  query_id          UUID,
  resolved_entities JSONB,
  ts                TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_session_turns ON session_turns (session_id, ts);
```

---

## 7. Data Sources & Tools (Explicit)

Every external and internal tool the MVP depends on. **The only paid dependency is the
Anthropic API.** Everything else is free tier or self-hosted.

### Data feeds (all free)

| Source | Role | Coverage | Phase | Cost |
|---|---|---|---|---|
| nflverse (`nfl_data_py`) | Stats, play-by-play, injuries, depth charts | NFL | 0 | free |
| CollegeFootballData.com | Full CFB game + player stats API | CFB | 0 | free (API key) |
| The Odds API (free tier) | Odds + line movement, 500 req/mo | NFL + CFB | 0 | free tier |
| Open-Meteo | Venue weather for outdoor games | both | 0 | free |
| News/recap scrape (`httpx`, curated list) | Unstructured prose for Qdrant | both | 0 | infra only |
| **Replay fixture** | One archived real week; deterministic demo data | both | all | free |

### Models & AI services

| Tool | Role | Phase | Cost |
|---|---|---|---|
| Claude **Haiku 4.5** | Guardrail classify + entity/intent/condition extraction; follow-up phrasing | 1, 5 | paid (Anthropic API) |
| Claude **Sonnet 4.6** | Grounded report synthesis (sole synthesis model) | 4 | paid (Anthropic API) |
| Voyage `voyage-3` | Embed docs + queries (1024-dim) | 0, 2, 3 | free tier |
| `cross-encoder/ms-marco-MiniLM-L-6-v2` (local) | Relevance reranking | 3 | free |

### Infrastructure & libraries

| Tool | Role | Phase(s) |
|---|---|---|
| **Docker Compose** | Runs the full stack on one machine | all |
| **LangGraph** | Query-pipeline orchestration (stateful graph, retries, conditional edges) | 1–5 |
| **FastAPI** | Local API surface + chat page, streaming | 5 |
| **Streamlit** | Management dashboard | 5 |
| **Postgres 16** | System of record | all |
| **Elasticsearch** (single node) | Structured + BM25 stats index | 0, 2 |
| **Qdrant** | Semantic vector index + semantic cache vectors | 0, 2, 3 |
| **Redis** | Live-feed hot cache, session state | 0, 2, 3, 5 |
| **Pydantic + `instructor`** | Inter-phase contracts; validated LLM structured output | 1, 4 |
| `httpx` | Async HTTP for all feed/API clients | 0, 2 |
| `sentence-transformers` | Local cross-encoder rerank | 3 |
| APScheduler | Phase 0 ingestion scheduling (in-process) | 0 |

---

## 8. Semantic Cache & Memory

**Semantic cache (Phase 3).** Queries are normalized to placeholder form (`[TEAM]`,
`[PLAYER]`, `[WEEK]`) and embedded; hits at cosine ≥ 0.92 reuse the prior `MergedContext`
with fresh entity IDs substituted in, skipping rerank. Cache vectors live in a Qdrant
`semantic_cache` collection; the reusable context lives in Postgres
(`semantic_cache_index`). **Live-odds chunks are never cached** — they are always re-fetched
even on a cache hit, because a stale line poisons the edge math.

**Session memory (Phase 5), simplified:** last N turns held raw in Redis and injected into
the next decomposition, plus resolved entities carried forward. Once "Mahomes" resolves to
a `player_id`, follow-ups reuse it without re-disambiguation. Tiered mid-term/long-term
memory is deferred (§14).

---

## 9. Cost Circuit Breakers

The only metered spend is the Anthropic API and the Odds API request quota.

- **Per-query LLM spend cap:** $0.15/query, alert at $0.10. A query exceeding the cap
  returns the deterministic evidence/edge block without full prose synthesis.
- **Per-day LLM cap:** env-configurable (default $2/day), alert at 80% on the dashboard.
- **Provider circuit breakers:** 5 consecutive 5xx from Anthropic / Voyage → pause the
  affected stage, surface on the dashboard, serve degraded (cached or evidence-only) until
  recovery.
- **Odds API budget guard:** monthly 500-request quota tracked in the `api_budget` table; a
  call that would exceed the budget is refused and the system serves from Redis/archive or
  the fixture. Hard guard, not advisory.

---

## 10. Observability (Local)

No external observability services. The `events` table + dashboard replace them.

- **Unified event log** (`events` table): every phase writes significant transitions
  (query received, plan built, retrieval fan-out result with per-source latency, cache
  hit/miss, freshness drops, citation-guard regenerations, report generated). First stop
  for debugging "what happened to query X?" — the dashboard's query-trace panel renders
  this timeline per `query_id`.
- **Ingestion heartbeats:** each worker loop writes `ingestion_log` rows; the dashboard
  flags any source whose last successful run is overdue.
- **Retrieval quality telemetry:** per-source hit counts, rerank score distributions, and
  `dropped_stale` counts logged to `events.detail` to tune K, TTLs, and decay half-lives.
- **Structured logging** (JSON to stdout) for everything else; `docker compose logs` is the
  raw fallback.

---

## 11. Data Retention

Demo scale keeps everything small; retention is mainly hygiene.

| Store | Retention | Notes |
|---|---|---|
| `odds_archive` | 2 seasons | line-movement history + the fixture source |
| Elasticsearch stats | current + prior 2 seasons | demo corpus; older seasons dropped |
| Qdrant docs | 1 season rolling | re-embeddable from source |
| `research_reports` | 180 days | prior research visible in chat |
| `semantic_cache_index` | 14 days or until prompt_version bump | invalidated on schema/prompt change |
| `session_turns` | 180 days | conversation continuity |
| `events` | 90 days | hard delete |
| Redis live cache | TTL per source (minutes) | ephemeral by design |
| Fixture files | permanent, versioned in repo (or a release asset) | the demo depends on them |

A nightly compaction job (`scripts/compact.py`, APScheduler) enforces these and invalidates
`semantic_cache_index` rows whose `prompt_version` no longer matches current.

---

## 12. Responsible Gaming & Compliance

This is a research/informational product, and these are deterministic chokepoints, not
optional copy. On a local demo the gating is a stub, but the chokepoint architecture is
implemented and demonstrable.

- **Not financial advice.** Every report carries `responsible_gaming_notice`. The system
  surfaces evidence and math; it does not recommend placing wagers, does not size stakes,
  and never implies guaranteed outcomes.
- **No bet execution.** The product has no path to place, fund, or transfer a wager. It is
  read-only research.
- **Jurisdiction & age gating (stubbed).** The Phase 5 gate function exists as a
  deterministic chokepoint before any report is returned; locally it runs with
  `GATING_ENABLED=false` and a code comment documenting the production behavior
  (configurable jurisdiction allowlist + age attestation).
- **Problem-gambling resources.** The notice includes the 1-800-GAMBLER line. The system
  never encourages chasing losses or increasing wager frequency.
- **Provider ToS.** Feed providers' terms govern redistribution; the report presents
  derived analysis, not bulk re-publication of licensed feeds. The replay fixture is a
  private demo dataset, not a redistribution channel.

---

## 13. Decision Log (Formerly "Open Decisions Deferred")

All draft-stage open decisions are resolved:

| # | Decision | Resolution | Rationale |
|---|---|---|---|
| 1 | Product framing | **Evidence-first; edge math as bonus** | No trained model in MVP; the guaranteed deliverable is cited evidence synthesis. Elo heuristic covers spreads/moneylines; props/futures return `insufficient_data`. |
| 2 | Scale & deployment | **Single local machine, Docker Compose, localhost-only** | Resume/demo project; small scale; no public surface. |
| 3 | Data feeds | **Free tier everywhere** — nflverse, CFBD, The Odds API free, Open-Meteo — **plus replay/fixture mode** | No recurring feed cost; demo runs deterministically year-round with zero live dependencies. |
| 4 | ES vs OpenSearch | **Elasticsearch, single node, 1–2 GB heap** | Keeps the hybrid-retrieval (BM25 + dense) story real; trivial to run in Compose at demo scale. |
| 5 | Qdrant vs pgvector | **Qdrant** | Dedicated vector DB is the portfolio centerpiece: collection design, payload-filtered ANN, snapshotting. |
| 6 | Rerank | **Local cross-encoder** (`ms-marco-MiniLM-L-6-v2`) | Free, no external dependency, ~100 MB, CPU-fast at demo K; demonstrates cross-encoder vs bi-encoder understanding. Recency decay applied post-rerank in Python. |
| 7 | Synthesis model | **Sonnet 4.6 only** (DeepSeek dropped) | One vendor, one key; Anthropic already required for Haiku. |
| 8 | `model_probability` | **Nightly Elo ratings job (Phase 0) + logistic mapping (Phase 4)** | Transparent, documented heuristic; spreads/moneylines only. |
| 9 | Cache threshold + TTLs | **Cosine ≥ 0.92; odds 5 min (60 min virtual in replay), injuries 30 min, weather 3 h, stats season, recaps 7 d** | Starting values; tune from `events` telemetry. |
| 10 | Session memory | **Recent turns + entity carry-forward only** | Demo sessions are short; tiered memory deferred. |
| 11 | Observability | **Local: `events` table + dashboard** (Sentry/UptimeRobot dropped) | No external services for a localhost project. |
| 12 | Dashboard | **Streamlit** | Fastest path to a credible management surface; reads Postgres/Redis directly. |

---

## 14. Out of Scope for MVP

- A trained predictive model for win probabilities / projections (the Elo heuristic is the
  MVP signal; the edge math accepts a model probability later).
- Live in-play / second-screen real-time updating during games.
- Bet placement, account funding, or any wagering execution.
- Sports beyond NFL and CFB.
- Multi-modal evidence (video, tracking-data charts) in the report.
- Bulk re-publication of licensed odds tables.
- Public/cloud deployment, multi-tenant use, auth beyond a local user stub.
- Paid feeds (SportsDataIO, OpticOdds) and the Cohere Rerank API — the contracts allow
  swapping them in later behind the same Phase 0/3 interfaces.
- Tiered session memory (mid-term LLM summaries, long-term semantic memory).
- User-facing model fine-tuning or personalization beyond session memory.
- SOC 2 / formal compliance audit.
- MinHash near-duplicate detection for the scrape corpus (defer to v1.5).

---

## Appendix A: Failure Modes Worth Naming

- **Odds feed outage / staleness / budget exhaustion.** The live sub-agent's source goes
  dark or the monthly quota is spent. The freshness gate drops stale odds; the report ships
  with `sources_unavailable=["live_odds"]` and the edge block reads `insufficient_data`
  rather than computing EV off a stale line. Never silently use an old line. Replay mode is
  the demo-day fallback that makes this failure irrelevant to a demo.
- **Entity collision (same surname).** Phase 1 returns `clarification_needed`; Phase 5 asks
  the user; resolution is stored for the session. The system never guesses which player.
- **Citation guard can't ground the prose.** After 2 regenerations, Phase 4 falls back to an
  evidence-only structured summary — no free-text claims — rather than ship an ungrounded
  report.
- **Qdrant / ES unavailable.** Retrieval degrades to whatever sources answered; the report
  discloses the gap. A query never hard-fails because one index is down.
- **Embedding API down.** Circuit breaker opens; Phase 2's semantic sub-agent reports
  failure; Phase 3 proceeds on the remaining sources. The local cross-encoder has no API to
  fail.
- **Stale semantic-cache hit.** Cache reuse always re-fetches live odds; if the cached
  structured evidence is older than its TTL, it's treated as a miss and re-retrieved.
- **LLM cost spike.** Per-query cap trips → deterministic evidence + edge math returned
  without prose synthesis. The user still gets the numbers.
- **Ingestion duplicate storm.** Upsert-by-`content_hash`/`record_id` makes re-ingestion
  idempotent; a re-run of a source produces zero net new index docs.
- **Postgres disk pressure.** Retention compaction (§11) bounds growth; the dashboard flags
  it. `odds_archive` is the fastest-growing table and the first compaction target.
- **Fixture drift.** A schema change breaks the archived fixture. Fixture files are
  versioned; `build_fixture.py` can regenerate from `odds_archive` + indexes, and the CI
  smoke test runs the full replay pipeline so breakage is caught at commit time.
