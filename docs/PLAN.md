# HailMaryRAG — Implementation Plan (Full MVP)

## Context

The design doc `C:\Users\epic2\Downloads\Research_Assistant_Design.md` (v1.0, **FROZEN**) fully specifies HailMaryRAG: a local, Docker-Compose-based agentic sports-research RAG system (NFL/CFB betting research). All architectural decisions are locked (§13) — Pydantic inter-phase contracts (§4) and Postgres DDL (§6.4) are written verbatim in the doc. This plan sequences the *build* into the empty repo `C:\Users\epic2\HailMaryRAG` (GitHub: esingh25/HailMaryRAG). Solo dev, Windows 11 + Docker Desktop.

**User constraints:** No API keys exist yet (Anthropic, Voyage, CFBD, The Odds API) → early milestones run 100% offline; key signup is scheduled as milestone tasks. Scope = full MVP roadmap.

## Key strategy decisions

1. **Build order de-risks:** contracts + pure deterministic logic first (zero infra), replay/fixture path before any live feed, LLM phases behind recorded cassettes, live feeds last (they feed the fallback, not the demo).
2. **Fixture chicken-and-egg resolved with two generations, one manifest format:**
   - `fixtures/synthetic_v0/` (M1): hand-built, ~3 games, committed to repo (<5 MB). Includes odds time series with line movement, a mid-week injury flip, an outdoor-weather game, a planted surname collision, precomputed embeddings, and LLM cassettes. CI runs this forever.
   - `fixtures/real_week_v1/` (M8): built by `scripts/build_fixture.py` from archived live data during the season; same format, drop-in via `FIXTURE_NAME`.
3. **LLM determinism in CI (extension in the doc's spirit):** `clients/llm.py` gets a cassette layer (`REPLAY_LLM=true`) — real Anthropic responses recorded once, keyed by SHA-256 of (model, prompt_version, rendered prompt); replayed as validated instructor outputs. CI needs **no secrets**. Prompt change → cassette miss → CI fails loudly → re-record. Same pattern for Voyage query embeddings.
4. **No-keys bootstrap:** until keys exist, fixture embeddings use deterministic pseudo-random unit vectors; swap to real Voyage vectors (free tier) when the key arrives. Key acquisition tasks: Voyage ~M1 (optional, improves semantic realism), **Anthropic required by M5**, CFBD + Odds API by M8.

## Tooling

| Tool | Choice | Why |
|---|---|---|
| Python | 3.11 pinned (`<3.12`) | `nfl_data_py` (locked dep) supports ≤3.11 |
| Packaging | uv (`uv.lock` shared host/container/CI) | fast, consistent |
| Lint/format | ruff (check + format; E,F,I,UP,B,ASYNC) | one tool |
| Types | mypy strict only on `schemas/`, `edge_math`, `routing`, `rerank/` pure modules | type errors there are catastrophic |
| Tests | pytest + pytest-asyncio; markers `unit`/`integration`/`e2e` | tiered gating |
| Pre-commit | ruff, `uv lock --check`, large-file guard, detect-secrets | cheap hooks only |
| CI | GitHub Actions, ubuntu. Job 1: lint+unit. Job 2 (from M6): compose up infra → migrate → load synthetic_v0 → `run_replay_e2e.py` with `REPLAY_MODE=true REPLAY_LLM=true`. HF model cached via actions/cache | doc mandates replay smoke in CI |
| Migrations | numbered plain `.sql` + tiny `scripts/migrate.py` runner | Alembic overkill; DDL already hand-written |

## Repo structure

```
HailMaryRAG/
├── pyproject.toml / uv.lock / .env.example / .pre-commit-config.yaml
├── .github/workflows/ci.yml
├── docker/  (docker-compose.yml, docker-compose.ci.yml, app.Dockerfile, es/ heap config)
├── src/hailmary/
│   ├── config.py            # pydantic-settings; ALL tunables (Elo, EV thresholds, TTLs, caps, REPLAY_*)
│   ├── clock.py             # Clock protocol: SystemClock | VirtualClock (fixture-pinned now)
│   ├── schemas/contracts.py # §4 VERBATIM — frozen; internal.py for helpers
│   ├── clients/             # postgres, es, qdrant, redis, llm (cassettes+cost+breaker), voyage, circuit
│   │   └── feeds/           # base.py FeedClient protocol; nflverse/cfbd/odds_api/open_meteo/scraper; replay.py
│   ├── ingestion/           # Phase 0: normalize, indexer (idempotent upserts), entity_map, elo, budget, scheduler
│   ├── decompose/           # Phase 1: guardrail, extractor, resolution, routing (pure table)
│   ├── retrieval/           # Phase 2: stats_agent, semantic_agent, live_agent, fanout
│   ├── rerank/              # Phase 3: cache, dedup, freshness, decay, cross_encoder, merge
│   ├── synthesis/           # Phase 4: edge_math (pure), elo_prob (pure), writer, citation_guard (pure), report
│   ├── delivery/            # Phase 5: FastAPI app/routes, sessions, gating stub, static/chat.html
│   ├── graph.py             # LangGraph wiring 1→2→3→4(→5)
│   └── obs/                 # events.py (single choke), cost.py (query/day caps)
├── dashboard/app.py         # Streamlit, 5 panels per §5 Phase 5
├── db/migrations/0001_init.sql   # §6.4 verbatim
├── fixtures/synthetic_v0/   # manifest.json, *.jsonl, embeddings.parquet, llm_cassettes/
├── scripts/                 # migrate, load_fixture, build_fixture, compact, seed_entity_map, record_cassettes, run_replay_e2e
└── tests/  (unit/ integration/ e2e/ conftest.py)
```

Principles: `contracts.py` frozen (doc changes first); `FeedClient` protocol is the replay seam — only the factory + clock check `REPLAY_MODE`; all pure logic import-clean (no I/O) so unit tests need no Docker/network/models.

## Milestones

| # | Delivers | Verifiable at end |
|---|---|---|
| **M0** Skeleton (~2–3d) | uv project, ruff/pytest/pre-commit, `contracts.py` + round-trip test, `config.py`, `clock.py`, compose w/ 4 stores + healthchecks (ES 1 GB heap, security off), `0001_init.sql` + migrate runner, CI job 1 | `docker compose up` → 4 healthy; unit CI green |
| **M1** Deterministic core + fixture + replay spine (~1w) | `edge_math`, `elo_prob`, Elo update core, `routing.py` (exhaustive intent table), `freshness`, `dedup`, `decay`, entity resolution, budget guard; **synthetic_v0 fixture**; FeedClient protocol + `replay.py`; `load_fixture.py`; VirtualClock; cassette layer. *Task: sign up Voyage (free) — else pseudo-random vectors* | All math unit-tested vs hand-computed cases; replay clients serve fixture at pinned virtual now |
| **M2** Phase 0 vs fixture (~4–5d) | normalize, indexer (ES/Qdrant/Redis/odds_archive upserts, mappings/collections auto-create), events + ingestion_log writers, APScheduler worker, Elo job wired | Worker run populates all stores; **second run = zero net-new docs** (idempotency); ratings rows exist |
| **M3** Phase 2 retrieval (~4d) | stats/semantic/live sub-agents (deterministic query construction, K-bounded), `fanout.py` (parallel, timeouts, sources_failed) | Hand-written plan → real `RetrievedContext`; kill a container → graceful degradation |
| **M4** Phase 3 merge/rerank/cache (~4–5d) | cross-encoder wrapper (lazy, HF_HOME-pinned), pipeline dedup→freshness→rerank→decay→truncate, semantic cache (placeholder normalize, cosine ≥0.92, live-odds always refreshed, prompt_version match) | Paraphrased repeat query hits cache with fresh odds |
| **M5** Phase 1 decomposition (~3–4d) | Haiku guardrail + instructor extraction, resolution + clarification_needed, routing applied, plan persisted; `record_cassettes.py` + committed cassettes. ***Task: sign up Anthropic (required)*** | Text → persisted `RetrievalPlan`; off-topic rejected; collision → clarification; all replayable keyless |
| **M6** Phase 4 + graph + CI smoke (~1w) | edge block assembly (evidence-first template, `line_as_of`, notice), Sonnet grounded prose, citation guard (verify→strip→≤2 regen→evidence-only fallback), LangGraph wiring, `cost.py` caps, `run_replay_e2e.py` → **CI job 2 on** | **First end-to-end report** in replay mode; poisoned prose stripped by guard; CI E2E green |
| **M7** Phase 5 delivery + dashboard (~1w) | FastAPI (POST /research SSE, GET /report/{id}, localhost-only), Redis sessions + entity carry-forward, clarification round-trip, gating chokepoint, Streamlit 5 panels + replay toggle + manual triggers | Full demo: chat → cited report w/ edge block + replay banner; follow-up inherits player; dashboard shows query trace |
| **M8** Live mode + real fixture + hardening (~1–1.5w, season-dependent) | Live feed clients (nfl_data_py via to_thread, CFBD, Odds API behind hard budget guard, Open-Meteo, curated scraper), live cadences, `build_fixture.py` → real_week_v1, `compact.py` retention, breaker soak tests, README runbook. *Task: CFBD + Odds API keys* | Live ingestion within budget; real fixture loads + passes E2E; retention enforced |

## Testing strategy

- **Unit (bulk, no services):** edge math (−110→0.5238 etc.), elo_prob symmetry/monotonicity, exhaustive routing matrix (all 6 intents), freshness gate per TTL class w/ VirtualClock (incl. 60-min virtual odds TTL in replay), dedup/decay ordering properties, citation guard (pass/strip/threadbare/fallback), placeholder normalization, collision resolution, budget arithmetic, content-hash stability, contract round-trips. Rerank pipeline unit-tested with injected fake scorer.
- **Integration (dockerized stores + cassettes):** ingestion run-twice invariance, known-answer ES/Qdrant retrieval, cache hit/refresh, fan-out degradation with downed source, Phase 1 plan snapshots.
- **E2E replay smoke (CI-gating):** 3 canned queries (spread w/ edge math; player prop → `insufficient_data`; follow-up w/ entity carry-forward); asserts citations resolve to real chunk_ids, freshness stamps, notice, events timeline. Doubles as Appendix-A fixture-drift tripwire.

## Risk register (top items)

1. **Odds API 500 req/mo burned in dev** → budget guard from first live call; `ODDS_API_ENABLED=false` default; all pre-M8 dev on fixture; cadence ≈120/mo.
2. **No keys early** → mitigated by design: M0–M4 fully offline; pseudo-random vectors until Voyage; Anthropic blocking only at M5 cassette recording.
3. **ES memory** → 1 GB heap/2 GB limit local, 512 MB CI; tiny corpus.
4. **Windows + Docker quirks** → WSL2 backend, named volumes (no bind-mount data dirs), `.gitattributes` LF for sql/sh/fixtures, no uvloop; ubuntu CI catches Linux issues.
5. **`nfl_data_py` fragility** → Python 3.11 pin; isolated behind FeedClient protocol; demo never depends on it.
6. **Cross-encoder download flakiness in CI** → actions/cache on HF_HOME; Docker layer pre-download; unit tier never imports it.
7. **LLM nondeterminism/cost in CI** → cassettes; zero CI secrets; optional manual real-key drift-check workflow.
8. **Off-season (no live games now, July)** → M0–M7 fixture-driven; M8 live capture waits for season or backfills historical stats.

## Config approach

Single `Settings(BaseSettings)`, `env_file=".env"`, nested `__` delimiter. All doc-flagged tunables: Elo constants, logistic mapping, EV thresholds, cache 0.92, per-source TTLs + decay half-lives, per-source K + timeouts, context budget, cost caps (0.15/query, 2.00/day), `REPLAY_MODE`, `REPLAY_LLM`, `FIXTURE_NAME`, `GATING_ENABLED=false`, `ODDS_API_ENABLED`. `.env.example` committed + documented; real `.env` gitignored; secrets local-only (CI keyless). Replay mode resolved once at startup into the client factory + Clock.

## Verification (overall)

- Each milestone ends with full CI green (`uv run pytest -m unit`, integration locally, replay E2E from M6).
- The doc-mandated end state: fresh clone → `docker compose up` → `migrate` → `load_fixture synthetic_v0` → chat query → grounded cited report with deterministic edge block, in replay mode, with zero external calls.

## First commit sequence (M0 day 1)

1. `pyproject.toml` + lock + ruff/pytest config
2. `schemas/contracts.py` + round-trip test
3. compose + `0001_init.sql` + `migrate.py`
4. `config.py`, `clock.py`, `.env.example`
5. CI (lint+unit) + pre-commit
