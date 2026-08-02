# Handoff — Project HailMary

**Written:** 2026-08-01 · **For:** a fresh Claude Code session with no prior context.
**Read this first, then `docs/FINISH_PLAN.md`.** Nothing else is required to resume.

---

## 1. Orientation

Project HailMary is Ekam's agentic NFL/CFB betting-research RAG system — a portfolio piece
aimed at SWE-internship reviewers. Local clone:
`C:\Users\epic2\OneDrive\Desktop\personal projects\Project-HailMary`.
GitHub: `esingh25/Project-HailMary` (renamed from `HailMaryRAG`; old URLs redirect).

Architecture in one line: **LLMs propose, deterministic Python disposes.** LLMs only extract
entities and write prose; index routing, ranking, freshness, and every probability/EV number
are deterministic code. Milestones M0–M7 are merged and CI-green.

**Do not trust the README's status section.** It says the system works end-to-end. Section 3
below is why that is not currently true.

## 2. Exact repo state

- `main` == `origin/main` @ **`397c078`**, working tree clean except two untracked docs:
  - `docs/FINISH_PLAN.md` — the build plan (v2). **Untracked. Not committed. Do not lose it.**
  - `docs/HANDOFF.md` — this file.
- **One unmerged commit:** `9bbc336` on `origin/m8-keyless-slice` — "M8 keyless live-feed slice,
  Gemini provider swap, retention + hardening" (26 files, +1420/−37). Not on `main`.
- Unit suite on `main`: **245 tests green**, ruff clean, CI green.

**Nothing has been implemented yet this session.** All work so far is analysis and planning.
The first code change is Task A1 (or B1 — see §5).

## 3. What the audit found — read before touching anything

An 11-agent audit fleet (5 diverse lenses → adversarial verification → completeness critic)
ran against the plan and the repo. **47 raw findings → 44 survived adversarial verification,
2 refuted, 5 added by the critic.** All 44 are encoded as tasks in `docs/FINISH_PLAN.md`.

Three are CRITICAL, and two of the three are on already-merged, CI-green code:

**(a) Elo ratings are never loaded into the query path.** ← the big one
Every non-test caller passes `"team_ratings": {}`, so `report.py:55-56` defaults *both* teams
to `1500.0`. Measured on the real functions:

| Scenario | p | EV @ −110 | Assessment |
|---|---|---|---|
| Shipped — **any** home team | 0.5925 | **+13.11%** | **value** |
| Shipped — **any** away team | 0.5000 | −4.55% | no_value |
| Real Elo — KC 1600 home vs LV 1450 | 0.7752 | +47.98% | value |
| Real Elo — LV 1450 home vs KC 1600 | 0.3801 | **−27.44%** | no_value |

The flagship "deterministic edge math" is a function of home-field advantage and nothing
else. It returns the identical number for every matchup in the league, and **inverts the
answer for weak home teams** — it reports "+13.11%, value" on Las Vegas at home against
Kansas City. The Elo subsystem is write-only. `README.md:43` claims the opposite.

**(b) Every dashboard panel raises before rendering.** `dashboard/app.py` caches an asyncpg
connection created on one event loop, then queries it via `asyncio.run()`, which builds a new
loop per panel. asyncpg binds futures to the creating loop. No test imports `dashboard.app`;
CI never runs Streamlit.

**(c) The entire M8 live-feed slice is unreachable.** Nothing outside its own unit tests calls
`get_feed_client()`. `ingestion/scheduler.py` still hardcodes `ReplayFeedClient` and commit
`9bbc336` never touched it. `REPLAY_MODE=false` changes nothing.

Raw audit JSON is at
`C:\Users\epic2\AppData\Local\Temp\claude\C--Users-epic2-OneDrive-Desktop-personal-projects\232c6326-7597-44df-b548-00cffe41f355\tasks\w448wpdmy.output`
(174 KB; parse `.result.survivors`). **That path is a temp directory and may be cleaned —
`docs/FINISH_PLAN.md` is the durable record.** Do not depend on the JSON existing.

## 4. B1 investigation — already done, do not redo

Task B1 (wire Elo into the query path) was investigated in depth. Findings, all verified
directly, that **materially de-risk the task versus how B1 is written in the plan**:

1. **Cassettes are unaffected.** `writer.py:38` builds the prompt as
   `WRITER_PROMPT_TEMPLATE.format(query=raw_text, evidence=_render_evidence(chunks))`. The
   edge block never enters the writer prompt, so changing `model_probability` **cannot** change
   a cassette key. Rule 3 of the plan is not in play for B1.
2. **The replay fixture does produce Elo rows.** `scheduler.py:92` calls
   `run_ratings_job(feed, pg, settings.elo, season=season, as_of=fixture.virtual_clock)` during
   the replay ingestion pass. So a real reader wired into the query path will find rows in
   replay mode — the fix is testable on the fixture, not only in live mode.
3. **Removing the `1500.0` default is safe for CI job 2.** `_build_edge_analyses` emits one
   block per `live_odds` chunk regardless of whether `model_probability` is `None`, and
   `run_replay_e2e.py:122` asserts only that `report.edge_analysis` is non-empty. Worst case
   the spread query reports `insufficient_data` honestly and the assertion still holds.
4. **The test suite encodes the bug.** Of six `build_report` tests, only
   `tests/unit/test_report.py:94` and `:288` pass real ratings; the other four pass
   `team_ratings={}`. That is why 245 tests stay green.
5. **Residual uncertainty (cannot close locally):** whether the fixture's `team_ratings` rows
   actually cover KC and LV for the fixture's season is inferred from the code path, not
   observed — verifying needs Docker. If they don't, correct behavior is `insufficient_data`,
   which is a fixture bug worth surfacing, not a reason to keep the 1500 default.

**Pending action:** B1's spec in `docs/FINISH_PLAN.md` still carries the original, more
cautious "Watch for" paragraph. Fold points 1–3 into it — Ekam was asked and the session
ended before he answered.

## 5. What to do next

Ekam's last instruction was "let's look at B1 first," and he was asked whether to implement it.
**Ask him before writing code** — he may want A1/A2 first for ordering, or B1 first for impact.

- **If B1:** it is a contained fix with a real regression test available and no cassette risk.
  Full spec in `docs/FINISH_PLAN.md` Task B1; apply §4 above.
- **If sequential:** start at Task A1 (rebrand) and work the plan in order.

Either way, **commit `docs/FINISH_PLAN.md` and this file first** — they are untracked and
represent the whole session's output.

## 6. How to work this plan

`docs/FINISH_PLAN.md` is written for a Sonnet-class implementer **paired with a reviewer
agent**. The core rules:

- **Every task has a paired review task.** The reviewer is a **fresh agent** that gets only
  the task spec, the diff, and its checklist — never the implementer's account of what it did.
  It **re-runs the gate itself**, **may not edit code**, and gets **two rounds max** before
  escalating to Ekam. Reviewer assignment per task is in the plan's table.
- **New tests must fail when the fix is reverted.** Non-negotiable — the audit found a branch
  test named `test_odds_budget_guard_refuses_before_any_http` that never calls `fetch_odds`.
- **Never change a prompt string or `PROMPT_VERSION`** without Ekam's go-ahead — it invalidates
  every cassette. Tasks that need this are quarantined in Phase E.
- **Never invent numbers** — no token prices, costs, or EV figures.
- **Line numbers in the plan are advisory.** Re-locate by symbol; several tasks edit files that
  later tasks cite.
- Phase boundaries get a standing `ecc:code-reviewer` pass; **Task C5 re-runs the whole audit
  fleet** against the changed repo and the changed plan.

## 7. Environment constraints

- Windows 11, PowerShell. Package manager is `uv` — always `uv run <cmd>`, never bare
  `python`/`pytest`.
- **Docker Desktop is NOT installed.** Integration tier and replay E2E cannot run locally —
  CI is the only witness. Phases A–C don't need it; D onward does. **Never claim a tier passed
  that you could not run.**
- No API keys configured (Gemini / CFBD / Odds API all absent).
- Remote is HTTPS; SSH host-key auth fails on this machine. Do not "fix" the remote.
- `main` is unprotected — **never `git push --force`**.

## 8. Open questions for Ekam

1. **Implement B1 now, or run A1/A2 first?** (his call; he was mid-decision)
2. **Gemini per-MTok input/output prices** — blocks Task C2's cost breakers. Plan Rule 4
   forbids guessing them.
3. **Cassette/model-id decision for live mode (Task E1):** decouple the cassette model
   component into a separate `cassette_model_id` setting, or keep two `.env` files? The model
   id is the first component of every cassette key, so replay and live cannot share one config.
4. **Task E6** changes the writer prompt and therefore requires re-recording cassettes —
   or dropping the retry loop entirely and correcting three documents instead. Cheaper
   alternative, his choice.
5. **Docker install** — gates Phase D and every BLOCKED verification item in Phases B and C.

## 9. Files worth reading, in order

| File | Why |
|---|---|
| `docs/FINISH_PLAN.md` | The plan. Tasks, gates, reviewer assignments. |
| `docs/DESIGN.md` | Frozen spec. Cited constantly by the plan; **never edit.** |
| `docs/PLAN.md` | Original M0–M8 plan. Historical context. |
| `src/hailmary/synthesis/report.py` | Where the Elo bug lives (`_model_probability_for_matchup`). |
| `src/hailmary/delivery/routes.py` | `"team_ratings": {}` — the bug's origin. |
| `src/hailmary/ingestion/ratings_job.py` | Has the working reader nobody calls. |
| `src/hailmary/graph.py` | LangGraph wiring; where Phase C's events go. |
| `docs/AMENDMENTS.md` | **Only on `origin/m8-keyless-slice`** — read via `git show origin/m8-keyless-slice:docs/AMENDMENTS.md`. |
