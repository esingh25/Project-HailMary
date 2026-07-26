# Architecture

HailMaryRAG is two pipelines sharing four datastores, orchestrated end-to-end as a
LangGraph state graph. This document maps the design onto the actual modules. The full
frozen specification (contracts, DDL, phase rules, decision log) lives in
[docs/DESIGN.md](docs/DESIGN.md); the milestone-by-milestone build plan is
[docs/PLAN.md](docs/PLAN.md).

## System overview

```
              ASYNC INGESTION PIPELINE (Phase 0)
  free feeds ──► normalize ──► idempotent upserts ──► Elasticsearch (BM25 stats)
  or fixture      (SHA-256       (keyed by             Qdrant (semantic vectors)
                 content_hash)   record_id/doc_id)     Redis (live odds/injuries)
                                                       Postgres (odds_archive,
                                                        team_ratings via Elo job)
  ═══════════════════════════════════════════════════════════════════════════
              SYNC QUERY PIPELINE (LangGraph: src/hailmary/graph.py)
  user query ──► decompose ──► retrieve ──► merge ──► synthesize ──► deliver
                 (Haiku +      (3 parallel  (dedup,    (edge math +   (FastAPI,
                  guardrail,    sub-agents,  freshness,  grounded      sessions,
                  routing       no LLM)      rerank,     prose +       dashboard)
                  table)                     cache)      citation guard)
```

The graph short-circuits after decomposition on guardrail rejection or a surname-collision
clarification — no retrieval happens for out-of-scope queries
(`_route_after_decompose` in `src/hailmary/graph.py`).

## Module responsibilities

| Phase | Module | Responsibility |
|---|---|---|
| 0 Ingestion | `src/hailmary/ingestion/` | `normalize.py` canonicalizes feed records; `indexer.py` upserts to ES/Qdrant/Redis/Postgres keyed by content hash (re-runs are no-ops); `elo.py` + `ratings_job.py` compute Elo power ratings on each ingestion pass; `budget.py` holds the refuse-don't-exceed arithmetic for The Odds API 500-req/mo quota (live wiring lands in M8); `scheduler.py` runs it all on APScheduler |
| 1 Decompose | `src/hailmary/decompose/` | `guardrail.py` rejects non-football queries; `extractor.py` pulls entities/intent/conditions via Haiku + `instructor`; `resolution.py` resolves names against the fixture entity map and raises `clarification_needed` on surname collisions; `routing.py` maps intent → target indexes with a pure lookup table — the LLM never chooses indexes |
| 2 Retrieve | `src/hailmary/retrieval/` | `stats_agent.py` (Elasticsearch structured + BM25), `semantic_agent.py` (Qdrant filtered ANN), `live_agent.py` (Redis odds/injuries/weather); `fanout.py` runs them in parallel with per-source timeouts and records `sources_failed` instead of aborting |
| 3 Merge | `src/hailmary/rerank/` | `merge.py` orchestrates: semantic-cache lookup (`cache.py`, cosine ≥ 0.92 on placeholder-normalized queries) → `dedup.py` → `freshness.py` TTL gate → `cross_encoder.py` local rerank (ms-marco-MiniLM-L-6-v2) → `decay.py` recency penalty → truncate to budget |
| 4 Synthesize | `src/hailmary/synthesis/` | `edge_math.py` + `elo_prob.py` compute implied probability, EV%, and value/fair/no_value/insufficient_data verdicts in pure Python; `writer.py` generates grounded prose via Sonnet; `citation_guard.py` strips citations whose chunk_id is not in the retrieved evidence, regenerates ≤2×, then falls back to an evidence-only summary; `report.py` assembles the final `ResearchReport` |
| 5 Deliver | `src/hailmary/delivery/` | `app.py`/`routes.py` expose `POST /research` and `GET /report/{query_id}` on localhost; `sessions.py` carries resolved entities across turns in Redis; `gating.py` is the responsible-gaming chokepoint; `static/chat.html` is the chat surface |
| Dashboard | `dashboard/` | Streamlit panels for ingestion health, query traces, cache stats, and cost; `queries.py` holds the unit-tested data-fetching functions |
| Contracts | `src/hailmary/schemas/contracts.py` | Pydantic models are the only interface between phases (mypy strict) |
| Infra | `src/hailmary/clients/` | Postgres/ES/Qdrant/Redis/LLM/Voyage clients; `cassette.py` + `feeds/replay.py` implement replay mode |
| Obs | `src/hailmary/obs/` | `events.py` provides the Postgres event-timeline and ingestion-log writers (ingestion logging is wired; per-phase query events land with live mode); `cost.py` implements the per-query/per-day LLM spend-cap arithmetic (unit-tested; graph wiring pending) |

## Key design decisions

**LLMs propose, deterministic Python disposes.** LLMs are confined to Phase 1 extraction
and Phase 4 prose. Index routing, relevance reranking, freshness gating, all odds/EV
arithmetic, and the responsible-gaming policy are deterministic Python with no LLM in the
loop. Rationale: numbers a model hallucinates are worse than no numbers; every
number in a report must be recomputable from `edge_math.py`.

**Grounded synthesis with a citation guard.** Phase 4 writes only from retrieved chunks.
`citation_guard.py` verifies every citation against real chunk IDs post-generation. If
fewer than `MIN_SURVIVING_CITATIONS` survive, the report is regenerated (max 2×) and then
degraded to a no-free-prose evidence summary rather than shipped ungrounded.

**Replay mode makes the whole system deterministic and keyless.** With
`REPLAY_MODE=true`, all feed clients read `fixtures/synthetic_v0/` and "now" is the
fixture's virtual clock, so freshness TTLs still exercise. With `REPLAY_LLM=true`, LLM and
embedding calls are served from committed cassettes keyed by SHA-256 of
(model, prompt_version, rendered prompt) — a prompt change causes a loud cassette miss
instead of a silent live call (`src/hailmary/clients/cassette.py`). CI runs the full
pipeline with zero secrets.

**The fixture is adversarial on purpose.** `fixtures/synthetic_v0/manifest.json` plants
line movement, a mid-week injury status flip, an outdoor-weather game, and a surname
collision (Josh Allen vs Brandon Allen) so the clarification path, freshness gate, and
weather routing are all exercised by the standard demo data.

**Freshness is a first-class contract.** Every chunk carries `freshness_ts`; per-source
TTLs (odds 5 min live / 60 min virtual, injuries 30 min, weather 3 h) drop stale evidence
in `rerank/freshness.py`. Live-odds chunks are never served from the semantic cache — a
stale line poisons the edge math (`_refresh_live_odds` in `rerank/merge.py`).

**Postgres is the system of record; everything else is rebuildable.** Queries, plans,
reports, ratings, odds history, the cache index, and the event log live in Postgres
(`db/migrations/0001_init.sql`). ES/Qdrant/Redis are derived caches.

**Cost circuit breakers.** Per-query and per-day LLM spend caps (`obs/cost.py`) are designed
to degrade to the deterministic evidence/edge block instead of failing, and the Odds API
monthly budget is a refuse-don't-exceed guard (`ingestion/budget.py`) backed by the
`api_budget` table. The cap/budget arithmetic is built and unit-tested; wiring into the live
query and feed paths lands with live mode (M8).

## Storage layout

| Store | Role | Key structures |
|---|---|---|
| Postgres 16 | System of record | `research_queries`, `retrieval_plans`, `research_reports`, `team_ratings`, `odds_archive`, `semantic_cache_index`, `api_budget`, `ingestion_log`, `events`, `session_turns` |
| Elasticsearch 8.14 (single node) | Structured stats + BM25 | `nfl_stats`, `cfb_stats` indexes; upserts keyed by `record_id` |
| Qdrant 1.18 | Semantic vectors + cache vectors | recaps/scouting/analysis collections + `semantic_cache`; payload-filtered ANN |
| Redis 7 | Live-feed hot cache + sessions | odds/injuries/weather keyed by game/player, TTL per source cadence |

## Failure modes

Designed-for failures (full list in docs/DESIGN.md Appendix A): a downed retrieval source
degrades to partial evidence with `sources_unavailable` disclosed in the report; stale or
budget-exhausted odds produce `insufficient_data` rather than EV off a bad line; ungroundable
prose falls back to the evidence-only summary; re-ingestion is idempotent by content hash;
fixture drift is caught by the CI replay smoke (`scripts/run_replay_e2e.py`).

## Testing tiers

- **Unit** (`tests/unit/`, `pytest -m unit`): pure-logic tests, no services — edge math
  against hand-computed cases, exhaustive routing matrix, freshness/decay/dedup properties,
  citation-guard paths, contract round-trips. The rerank pipeline is tested with an
  injected fake scorer so no model download is needed.
- **Integration** (`tests/integration/`, `pytest -m integration`): dockerized stores —
  ingestion run-twice invariance, known-answer retrieval, cache hit/refresh, fan-out
  degradation with a downed source, plan snapshots.
- **E2E** (`scripts/run_replay_e2e.py`): the CI-gating replay smoke — three canned queries
  through the compiled graph, asserting citation grounding, freshness stamps, and
  replay-mode disclosure.
