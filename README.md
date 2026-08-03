# Project HailMary (HailMaryRAG)

An agentic NFL / College Football research assistant. Ask a natural-language betting
question — *"Is there value on the Chiefs -6.5 against the Raiders?"* — and it decomposes
the query, fans out across three retrieval indexes (Elasticsearch BM25, Qdrant vectors,
live odds/injury feeds), reranks the evidence with a local cross-encoder, computes
line-value math deterministically, and returns a cited research report.

Built as a portfolio-grade RAG system for anyone who wants to see hybrid retrieval,
grounded synthesis, and LLM guardrails done end-to-end. It is a **research tool, not a
tipster and not financial advice** — it surfaces evidence and math, never a bet verdict.

The core idea: **LLMs propose, deterministic Python disposes.** LLMs only extract
entities (`src/hailmary/decompose/extractor.py`) and write prose
(`src/hailmary/synthesis/writer.py`). Index routing, relevance ranking, freshness
gating, and every probability/EV number are deterministic code the LLM cannot touch.

## How it works

```
 user query
    │  POST /research (src/hailmary/delivery/routes.py)
    ▼
 Phase 1 DECOMPOSE   fast-model guardrail + entity/intent extraction; deterministic
    │                intent→index routing table (src/hailmary/decompose/routing.py)
    ▼
 Phase 2 RETRIEVE    3 parallel sub-agents, no LLM (src/hailmary/retrieval/fanout.py):
    │                stats→Elasticsearch, semantic→Qdrant, live→Redis odds/injuries
    ▼
 Phase 3 MERGE       semantic cache (cosine ≥ 0.92) → dedup → freshness TTL gate →
    │                local cross-encoder rerank → recency decay (src/hailmary/rerank/)
    ▼
 Phase 4 SYNTHESIZE  deterministic EV/edge math (src/hailmary/synthesis/edge_math.py)
    │                + grounded LLM prose + citation guard (citation_guard.py)
    ▼
 Phase 5 DELIVER     FastAPI + session memory + Streamlit dashboard (dashboard/app.py)
```

The whole query path is one LangGraph state graph (`src/hailmary/graph.py`) that
short-circuits before retrieval on out-of-scope queries or ambiguous player names.
An async ingestion pipeline (`src/hailmary/ingestion/`) populates the indexes with
idempotent content-hash upserts and computes Elo power ratings on each pass
(`src/hailmary/ingestion/elo.py`) — the sole source of model probability for the edge math.

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for the module-by-module map and design
decisions, **[docs/DESIGN.md](docs/DESIGN.md)** for the full frozen spec (contracts,
Postgres DDL, phase rules, failure modes), and **[docs/PLAN.md](docs/PLAN.md)** for the
milestone build plan. DESIGN.md is frozen; deliberate deviations from it are recorded in
**[docs/AMENDMENTS.md](docs/AMENDMENTS.md)**.

## Replay mode: the whole pipeline, zero API keys

The default demo path needs **no API keys and no live feeds**. With `REPLAY_MODE=true`,
feed clients read a committed fixture (`fixtures/synthetic_v0/`) and freshness math runs
on the fixture's virtual clock. With `REPLAY_LLM=true`, every LLM and embedding call
replays from committed cassettes (`fixtures/synthetic_v0/llm_cassettes/`) keyed by
SHA-256 of (model, prompt_version, prompt) — a prompt change fails loudly instead of
silently calling the live API (`src/hailmary/clients/cassette.py`). CI runs the full E2E
pipeline this way with no secrets.

The committed cassettes were recorded against Anthropic model ids, and the key includes
the model string *as recorded*, so they keep replaying byte-for-byte regardless of which
provider live mode targets. Live mode is now Google Gemini
([docs/AMENDMENTS.md](docs/AMENDMENTS.md) A1); switching to it changes the model id and
therefore every cassette key, which is why going live requires re-recording.

The fixture is deliberately adversarial: it plants line movement, a mid-week injury
status flip, an outdoor-weather game, and a surname collision (Josh Allen / Brandon
Allen) to exercise the clarification path (`fixtures/synthetic_v0/manifest.json`).

## Quickstart

Prerequisites: [uv](https://docs.astral.sh/uv/), Docker Desktop (Postgres 16,
Elasticsearch 8.14, Qdrant 1.18, Redis 7 via compose). uv installs Python 3.11
automatically (pinned in `.python-version`).

```bash
git clone https://github.com/esingh25/Project-HailMary.git
cd Project-HailMary
cp .env.example .env          # defaults run replay mode; no keys required
uv sync --all-groups
docker compose -f docker/docker-compose.yml up -d
uv run python scripts/migrate.py            # apply db/migrations/*.sql
uv run python scripts/run_replay_e2e.py     # load fixture + full E2E smoke
```

Then start the API + chat surface and the dashboard:

```bash
uv run uvicorn hailmary.delivery.app:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000  (chat UI: src/hailmary/delivery/static/chat.html)
uv run streamlit run dashboard/app.py
```

Secrets (`GEMINI_API_KEY`, `CFBD_API_KEY`, `ODDS_API_KEY`) are only needed for live mode
and for re-recording cassettes (`scripts/record_cassettes.py`); every variable is
documented in `.env.example`.

## Going live (optional, keys required)

Replay mode is the demo; live mode feeds it. See `.env.example` for the flags.

1. **Gemini** (`GEMINI_API_KEY`, free tier) — set provider-qualified model ids
   (`HAIKU_MODEL=google/gemini-2.5-flash`, `SONNET_MODEL=google/gemini-2.5-pro`,
   `VOYAGE_MODEL=gemini-embedding-001`), then re-record cassettes:
   `uv run python scripts/record_cassettes.py`. Query and document vectors must share one
   embedding scheme, so switching the embedding model also means re-embedding the corpus.
2. **CFBD** (`CFBD_API_KEY`, free) — college football stats.
3. **The Odds API** (`ODDS_API_KEY`, 500 req/month) — leave `ODDS_API_ENABLED=false` until
   you mean it; every call goes through a hard monthly budget guard.
4. nflverse and Open-Meteo need no keys.

`.env.example` also carries `ANTHROPIC_API_KEY`, unset by default — it is only read if you
deliberately point `HAIKU_MODEL`/`SONNET_MODEL` back at an `anthropic/`-qualified id.

Live feed clients live in `src/hailmary/clients/feeds/` behind the same `FeedClient`
protocol the replay client implements. **They are landed and unit-tested, but nothing
selects through the factory yet** — `ingestion/scheduler.py` still constructs
`ReplayFeedClient` directly, so setting `REPLAY_MODE=false` does not currently change
ingestion behaviour. Wiring the factory into the scheduler is the next live-mode task.

## Demo walkthrough

`scripts/run_replay_e2e.py` — the same script CI gates on — ingests the fixture into the
real dockerized stores, then runs three canned queries through the compiled graph:

1. **Spread query** ("Is there value on the Chiefs -6.5 against the Raiders?") → full
   report with the deterministic edge block: American odds → implied probability,
   Elo-derived model probability, EV%, and a value/fair/no_value assessment.
2. **Player prop** ("How many passing yards will Mahomes throw for?") → edge block
   honestly reads `insufficient_data` — the Elo heuristic only covers spreads and
   moneylines, so no number is fabricated.
3. **General injury query** → cited evidence synthesis with freshness stamps.

The script asserts every citation resolves to a real retrieved `chunk_id`, reports are
stamped `replay_mode=true` with `line_as_of`, and the responsible-gaming notice is
present — it exits non-zero on any failure. Reports are Pydantic `ResearchReport` objects
(`src/hailmary/schemas/contracts.py`) with summary, key factors, line movement,
edge analysis, and citations.

## Testing

Three tiers, gated by pytest markers (`pyproject.toml`), all runnable locally:

```bash
uv run pytest -m unit -q            # 266 tests, pure logic, no services needed
uv run pytest -m integration -q     # dockerized stores, replay mode, no keys
uv run python scripts/run_replay_e2e.py   # CI-gating end-to-end replay smoke
```

- **Unit** (`tests/unit/`, 38 files): edge math vs hand-computed cases (-110 → 0.5238),
  Elo symmetry/monotonicity, the exhaustive intent-routing matrix, freshness TTLs on a
  virtual clock, dedup/decay ordering, citation-guard strip/regenerate/fallback paths,
  cassette keying, budget arithmetic, contract round-trips. The rerank pipeline is
  unit-tested with an injected fake scorer, so no model download is required.
- **Integration** (`tests/integration/`): ingestion run-twice invariance (idempotent
  upserts), known-answer ES/Qdrant retrieval, semantic-cache hit with live-odds refresh,
  fan-out degradation with a downed source, plan snapshots.
- **CI** (`.github/workflows/ci.yml`): job 1 runs ruff + unit tests; job 2 boots
  Postgres/ES/Qdrant/Redis, migrates, and runs the replay E2E plus integration tests —
  keyless via cassettes.

Lint/format is ruff (E, F, I, UP, B, ASYNC); mypy checks the contract and pure-math
modules, strict on the contracts (`pyproject.toml`); pre-commit config in
`.pre-commit-config.yaml`.

## Project structure

```
src/hailmary/
├── graph.py            # LangGraph wiring: decompose → retrieve → merge → synthesize
├── config.py           # pydantic-settings: Elo constants, EV thresholds, TTLs, caps
├── clock.py            # SystemClock | VirtualClock (fixture-pinned "now")
├── schemas/contracts.py# Pydantic inter-phase contracts (mypy strict)
├── clients/            # postgres, es, qdrant, redis, llm, embeddings, cassette replay
│   └── feeds/          # FeedClient protocol + replay.py fixture client
│                       #   + live clients (nflverse, cfbd, odds_api, open_meteo,
│                       #     scraper) behind factory.py — landed, not yet wired
├── ingestion/          # Phase 0: normalize, idempotent indexer, Elo job, budget guard
├── decompose/          # Phase 1: guardrail, extractor, entity resolution, routing
├── retrieval/          # Phase 2: stats/semantic/live sub-agents + parallel fanout
├── rerank/             # Phase 3: cache, dedup, freshness, cross-encoder, decay
├── synthesis/          # Phase 4: edge_math, elo_prob, writer, citation_guard, report
├── delivery/           # Phase 5: FastAPI app, sessions, gating, chat.html
└── obs/                # events timeline + LLM cost caps
dashboard/              # Streamlit management dashboard (+ unit-tested queries.py)
db/migrations/          # 0001_init.sql — full system-of-record DDL
fixtures/synthetic_v0/  # committed replay fixture + LLM cassettes
scripts/                # migrate, load_fixture, record_cassettes, run_replay_e2e,
                        #   build_fixture (live→fixture), compact (retention)
tests/                  # unit/ (266 tests) · integration/ · e2e/
docs/                   # DESIGN.md (frozen spec) · PLAN.md (milestone plan)
                        #   AMENDMENTS.md (recorded deviations from the frozen spec)
```

## Design highlights

- **Grounded synthesis:** every factual claim must cite a retrieved chunk; the citation
  guard strips unverifiable citations, regenerates at most twice, then falls back to an
  evidence-only summary rather than ship ungrounded prose.
- **Freshness as a contract:** per-source TTLs (odds 5 min live / 60 min virtual,
  injuries 30 min, weather 3 h) gate evidence in `src/hailmary/rerank/freshness.py`;
  live-odds chunks are never served from cache.
- **Cost circuit breakers:** per-query/per-day LLM spend caps (`src/hailmary/obs/cost.py`)
  and a refuse-don't-exceed guard for The Odds API's 500-req/month free tier
  (`src/hailmary/ingestion/budget.py`, `api_budget` table in the DDL) — the arithmetic is
  built and unit-tested; wiring into the live query/feed paths lands with live mode (M8).
- **Observability without SaaS:** a Postgres `events` timeline (`src/hailmary/obs/events.py`)
  backs the dashboard's per-query trace, cache-stats, ingestion-health, and cost panels;
  the ingestion pass logs every run to `ingestion_log` today, and per-phase query events
  wire up alongside live mode.

## Status

Milestones M0–M7 of [docs/PLAN.md](docs/PLAN.md) are built and CI-gated: contracts,
deterministic core, fixture + replay spine, ingestion, retrieval, rerank/cache,
decomposition, synthesis + graph, delivery + dashboard.

**M8 is partially landed.** Its keyless slice — the live `FeedClient` implementations, the
Gemini provider swap, `build_fixture.py`, `compact.py` — is merged and unit-tested. What
remains is wiring: the ingestion scheduler still constructs `ReplayFeedClient` directly
rather than selecting through `feeds/factory.py`, so no live feed is on an execution path
yet. That wiring, plus running against real season data, is season-dependent.

Known gaps are tracked in [docs/FINISH_PLAN.md](docs/FINISH_PLAN.md) rather than left
implicit — including per-phase query events, the LLM cost breakers, and the dashboard
cost panel, all of which have tested arithmetic but no call site.
