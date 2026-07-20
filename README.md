# Project HailMary

Local, Docker-Compose-based agentic sports-research RAG for NFL/CFB betting
research. Fully offline demo: every LLM/embedding call replays from committed
cassettes, every feed reads from a committed fixture, and the edge math is
deterministic Python — the LLM never computes a number.

Design: [docs/DESIGN.md](docs/DESIGN.md) (frozen; deviations in
[docs/AMENDMENTS.md](docs/AMENDMENTS.md)) · Build plan: [docs/PLAN.md](docs/PLAN.md)

## Prerequisites

- Python 3.11 + [uv](https://docs.astral.sh/uv/)
- Docker with Compose (Docker Desktop, or `brew install colima docker docker-compose && colima start`)

## Quickstart (replay mode — no API keys)

```bash
uv sync --all-groups
cp .env.example .env    # defaults are already replay-mode

# 1. Four stores: Postgres, Elasticsearch, Qdrant, Redis
docker compose -f docker/docker-compose.yml up -d --wait

# 2. Schema
uv run python scripts/migrate.py

# 3. End-to-end smoke: fixture -> ingestion -> 3 canned queries -> cited reports
REPLAY_MODE=true REPLAY_LLM=true uv run python scripts/run_replay_e2e.py
```

Expected: all three queries print `OK`, and the spread query shows edge blocks.

### Chat demo

```bash
uv run uvicorn hailmary.delivery.app:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000/
```

### Dashboard

```bash
uv run streamlit run dashboard/app.py
```

## Tests

```bash
uv run pytest -m unit -q           # pure logic, no services
uv run pytest -m integration -q    # needs the compose stack + migrate
REPLAY_MODE=true REPLAY_LLM=true uv run python scripts/run_replay_e2e.py
```

CI runs all three tiers (`.github/workflows/ci.yml`) with zero secrets.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/migrate.py` | apply numbered SQL migrations |
| `scripts/load_fixture.py` | load a fixture into the stores |
| `scripts/run_replay_e2e.py` | the CI-gating replay smoke test |
| `scripts/author_cassettes_v0.py` | (re)author deterministic synthetic cassettes for synthetic_v0 |
| `scripts/record_cassettes.py` | record real LLM cassettes once a key exists |
| `scripts/build_fixture.py` | build `fixtures/real_week_v1/` from live nflverse data |
| `scripts/compact.py` | nightly retention compaction (DESIGN.md §11) |

## Going live (optional, keys required)

Replay mode is the demo; live mode feeds it. See `.env.example` for the flags.

1. **Gemini** (`GEMINI_API_KEY`, free tier) — set provider-qualified model ids
   (`HAIKU_MODEL=google/gemini-2.5-flash`, `SONNET_MODEL=google/gemini-2.5-pro`),
   then re-record cassettes: `uv run python scripts/record_cassettes.py`.
2. **CFBD** (`CFBD_API_KEY`, free) — college football stats.
3. **The Odds API** (`ODDS_API_KEY`, 500 req/month) — leave
   `ODDS_API_ENABLED=false` until you mean it; every call goes through a hard
   monthly budget guard.
4. nflverse and Open-Meteo need no keys.

Live feed clients live in `src/hailmary/clients/feeds/` behind the same
`FeedClient` protocol the replay client implements; `feeds/factory.py` picks
the implementation from `REPLAY_MODE`.
