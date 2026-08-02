# Project HailMary — Finish Plan (v2, reviewed)

**Audience:** an implementing agent (Sonnet-class) plus a paired reviewer agent, working task by task.
**Written:** 2026-08-01, against `main` @ `397c078`.
**Supersedes:** v1 of this file. v1 was audited by an 11-agent fleet before it was ever executed;
44 of 47 findings survived adversarial verification. Those findings are the backlog below.
**Companion docs:** `docs/DESIGN.md` (frozen spec), `docs/PLAN.md` (original M0–M8 plan),
`docs/AMENDMENTS.md` (arrives with Task A2).

---

## What the audit changed

v1 assumed the project was structurally sound and only needed M8 landed plus two unwired
modules connected. That assumption was wrong. The audit found **three CRITICAL defects on
code that is already merged, CI-green, and described in the README as working:**

1. **Elo ratings are never loaded into the query path.** Every non-test caller passes
   `"team_ratings": {}`, so `report.py` falls back to `1500.0` for *both* teams. The
   flagship "deterministic edge math" therefore computes a function of home-field advantage
   and nothing else: **every home team gets p=0.5925 → EV +13.11% → assessment "value"**,
   and every away team gets "no_value" — regardless of who is playing. The Elo subsystem is
   write-only. README.md states the opposite ("the sole source of model probability").
   The replay E2E cannot catch it because it asserts only that an edge block is non-empty,
   and it hardcodes the same empty dict.
2. **Every dashboard panel raises before rendering.** `dashboard/app.py` caches an asyncpg
   connection created on one event loop, then queries it through `asyncio.run()`, which
   builds a *new* loop per panel. asyncpg binds futures to the creating loop. No test
   imports `dashboard.app`; CI never runs Streamlit.
3. **The entire M8 live-feed slice is unreachable.** Nothing outside its own unit tests
   calls `get_feed_client()`. `ingestion/scheduler.py` still hardcodes `ReplayFeedClient`
   and the commit never touched it. Setting `REPLAY_MODE=false` changes nothing.

Two of those three are on `main` today. This is why Phase B exists and why it comes before
the observability work that v1 led with.

The audit also found that v1 pointed the implementing agent at the **wrong file** for the
evidence-only fallback, gave a `build_fixture.py` command that **fails on argparse**, and
set a Phase D gate that is **mathematically unsatisfiable** (both fixtures cannot pass with
one `.env`, because model ids are cassette-key components). Those are fixed below.

---

## Rules of engagement

Read this section before touching anything. It binds both the implementer and the reviewer.

1. **One task, one commit.** Use the conventions already in the log (`feat:`, `fix:`,
   `docs:`, `chore:`, `test:`). Never bundle two tasks.
2. **Never edit these files:**
   - `src/hailmary/schemas/contracts.py` — spec §4 verbatim. A change here requires a
     DESIGN.md amendment first.
   - `docs/DESIGN.md` — frozen.
   - `fixtures/synthetic_v0/llm_cassettes/*` — see rule 3.
3. **Never re-record or hand-edit cassettes, and never change a prompt string or
   `PROMPT_VERSION`, without an explicit go-ahead from Ekam.** A cassette key is
   `SHA-256(model, prompt_version, prompt)`. A prompt edit makes every cassette miss and
   fails CI loudly — that failure is the system working. Several tasks below *want* a prompt
   change; they are quarantined into Phase E for exactly this reason.
4. **Do not invent numbers.** No estimated token prices, costs, EV figures, or latencies in
   code, tests, or docs. If a real number is unavailable, build the seam, leave it disabled,
   and say so in the commit body.
5. **Line numbers in this document are as of `397c078` and are advisory.** Several tasks
   edit files that later tasks cite. **Always re-locate by symbol name** (`grep -n
   "def _model_probability_for_matchup"`), never by trusting a line number here. A line
   number that does not match is not a blocker — it is expected drift.
6. **Every task ends with the standard gate:**
   ```bash
   uv run ruff check . && uv run ruff format --check . && uv run pytest -m unit -q
   ```
   From Task B6 onward, `uv run mypy` joins that gate.
7. **When blocked, stop and report.** Do not improvise around a missing key, a missing
   Docker daemon, an ambiguous merge, or a failing gate you cannot explain. Write down what
   you found and hand back to Ekam.
8. **Rollback.** Every task is one commit on `main`. If a task's gate fails and you cannot
   fix it in the same session, `git reset --hard HEAD` (uncommitted) or `git revert <sha>`
   (committed and pushed) — **never `git push --force`**. `main` is unprotected; a force
   push loses history permanently.

### Environment facts

- Windows 11, PowerShell. Package manager is `uv` — always `uv run <cmd>`, never bare
  `python`/`pytest`.
- **Docker Desktop is installed as of 2026-08-02** (v4.84.0, engine 29.6.2, Compose v5.3.1).
  It sits at `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin` — a **per-user** install, not
  `C:\Program Files\Docker`. That directory is on the *User* PATH, so any shell started before
  the install will not see it; prepend it to `$env:PATH` for the command, or `docker` resolves
  but the `docker-credential-desktop` helper does not and image pulls fail with
  `error getting credentials`. All four containers come up healthy in well under a minute
  (ES has a 30s start period). Integration tier and replay E2E now run locally — but still
  never claim a tier passed that you did not actually run.
- No API keys configured.
- Remote is HTTPS. SSH host-key auth fails on this machine — do not "fix" the remote URL.

---

## The review protocol

This is the part v1 lacked. In v1 every task self-certified: the same agent that wrote the
code decided whether the gate passed. For a Sonnet-class worker that is the single biggest
source of silent failure — a gate like "verify by reading, since Docker is unavailable" is
an invitation to conclude what you hoped.

**Every implementation task `X` has a paired review task `R-X`.** The review is not optional
and not advisory: a task is not done until its review returns PASS.

### Rules binding the reviewer

1. **Fresh agent, no shared context.** The reviewer must be a separate agent invocation. It
   must NOT receive the implementer's account of what it did. It receives exactly three
   things: the task spec from this document, the diff (`git diff HEAD~1`), and its own
   checklist below.
2. **Independently re-run the gate.** The reviewer runs the commands itself. "The implementer
   said tests pass" is not evidence. If the reviewer cannot run something (Docker), it returns
   BLOCKED for that item rather than assuming.
3. **Evidence bar.** Every finding cites a file:line the reviewer opened or a command it ran
   with real output. No style opinions, no "consider adding". This is the same bar the audit
   that produced this plan was held to.
4. **Verdict is one of:**
   - `PASS` — gate reproduced, checklist satisfied, no findings above LOW.
   - `FAIL` — one or more findings at MEDIUM+. Lists them with evidence and a suggested fix.
   - `BLOCKED` — cannot verify without Docker/keys. Names precisely what is unverified.
5. **The reviewer must not edit code.** Separation of duties: if the reviewer fixes what it
   found, nobody is checking the reviewer. It reports; the implementer fixes.
6. **Two rounds maximum.** FAIL → implementer fixes → re-review. If the second review still
   returns FAIL, **stop and escalate to Ekam**. Do not loop.
7. **Scope discipline.** The reviewer checks *this task against its spec*. Defects it notices
   outside the task's scope get recorded in the commit body or raised to Ekam — they do not
   turn into FAIL, and they do not get fixed inline. Otherwise every task grows without bound.

### Reviewer assignment

| Task | Reviewer agent | Why this one |
|---|---|---|
| A1 rebrand | `ecc:code-reviewer` | Mechanical; needs completeness checking, not depth |
| A2 merge | `ecc:code-reviewer` + `ecc:security-reviewer` | 1420 lines of new network-facing feed clients |
| B1 Elo wiring | `ecc:python-reviewer` | Correctness of the numeric path is the whole point |
| B2 dashboard loop | `ecc:python-reviewer` | asyncio/asyncpg lifetime semantics |
| B3 cache freshness | `ecc:code-reviewer` | Spec-conformance reasoning against §5 Phase 3 |
| B4 future timestamps | `ecc:python-reviewer` | Small, numeric, edge-case heavy |
| B5 key leak | `ecc:security-reviewer` | Secret-in-error-path; security lens required |
| B6 mypy | `ecc:build-error-resolver` | Type-error resolution is its specialty |
| B7 gating chokepoint | `ecc:fastapi-reviewer` | Route-level auth chokepoint |
| C1 query events | `ecc:silent-failure-hunter` | The task *deliberately* swallows exceptions — needs the specialist that knows when that is correct |
| C2 cost breakers | `ecc:python-reviewer` | Return-contract change across 4 test doubles |
| C3 spend persistence | `ecc:database-reviewer` | New writes + a dashboard read path |
| C4 logging | `ecc:code-reviewer` | Small wiring change |

### Standing reviews (phase boundaries, not per-task)

- **End of every phase:** `ecc:code-reviewer` over the whole phase diff
  (`git diff <phase-start-sha>..HEAD`). Catches cross-task incoherence that per-task review
  cannot see.
- **Before every push:** if the phase touched secrets, network calls, or user input, run
  `ecc:security-reviewer` over the phase diff.
- **End of Phase C — re-audit.** Re-run the multi-lens audit that produced this plan
  (5 lenses → adversarial verify → completeness critic) against the *new* state of the repo
  and of this document. The work in Phases A–C changes the codebase enough that new holes
  are likely. Treat its confirmed findings as the Phase D backlog. **This is the mechanism
  that keeps the plan honest as the project moves** — a plan reviewed once is only correct
  once.

### Test-quality review

Passing tests are not evidence of correct tests. The Elo bug survived 245 green tests, and
the audit found a branch test literally named
`test_odds_budget_guard_refuses_before_any_http` **that never calls `fetch_odds`**. For any
task that adds tests, the reviewer must confirm each new test **fails when the fix is
reverted**. If a test passes against the un-fixed code, it is not a test — it is decoration.

---

# Phase A — Land and label what exists

No keys, no Docker.

## Task A1 — Finish the rebrand

`main` is named "Project HailMary"; the code still says "HailMaryRAG".

Locate each by content, not line number:

| File | Find | Replace with |
|---|---|---|
| `pyproject.toml` | `description = "HailMaryRAG — agentic NFL/CFB...` | `"Project HailMary — agentic NFL/CFB...` (keep the rest) |
| `src/hailmary/delivery/app.py` | `FastAPI(title="HailMaryRAG"` | `title="Project HailMary"` |
| `src/hailmary/delivery/static/chat.html` | `<title>HailMaryRAG</title>` | `<title>Project HailMary</title>` |
| `src/hailmary/delivery/static/chat.html` | `<h1>HailMaryRAG — Research Chat</h1>` | `<h1>Project HailMary — Research Chat</h1>` |
| `dashboard/app.py` | `page_title="HailMaryRAG Dashboard"` | `page_title="Project HailMary Dashboard"` |
| `dashboard/app.py` | `st.title("HailMaryRAG — Management Dashboard")` | `st.title("Project HailMary — Management Dashboard")` |
| `tests/unit/test_routes.py` | `assert "HailMaryRAG" in response.text` | `assert "Project HailMary" in response.text` |
| `ARCHITECTURE.md` | `HailMaryRAG is two pipelines` | `Project HailMary is two pipelines` |

**Do NOT change:** the Python package name `hailmary` or any import path (deferred, F2);
`docs/DESIGN.md` (frozen); `docs/PLAN.md` (historical record); `README.md` line 1 — the
`(HailMaryRAG)` parenthetical is a deliberate alias for the old GitHub URL.

**Done means:** standard gate green (245 tests), and
`git grep -n HailMaryRAG -- src/ dashboard/ tests/ pyproject.toml ARCHITECTURE.md`
returns nothing. *(v1's gate omitted `ARCHITECTURE.md` and would have passed with one of
the eight edits skipped — audit finding `plan-a1-gate-misses-architecture-md`.)*

**Commit:** `chore: finish the Project HailMary rename in code and dashboard`

### R-A1 — Review

Checklist: (a) re-run the grep gate yourself, including `ARCHITECTURE.md`; (b) confirm all
eight edits landed, not seven; (c) confirm no import path or package name changed
(`git diff --stat` should show no renames); (d) confirm `README.md` line 1 still carries the
alias; (e) re-run the standard gate.

---

## Task A2 — Merge the M8 keyless slice, and label it honestly

`origin/m8-keyless-slice` has one commit (`9bbc336`, 26 files, +1420/-37): live feed clients,
the Anthropic+Voyage → **Google Gemini** provider swap, `build_fixture.py`, `compact.py`.

```bash
git checkout main && git pull --ff-only
git merge origin/m8-keyless-slice
```

**Exactly one file conflicts: `README.md`.** Verified via
`git merge-tree $(git merge-base main origin/m8-keyless-slice) main origin/m8-keyless-slice`.

### Resolving the README conflict

`main` got a brand-new README in `397c078` *after* the branch was cut.

- **Base your resolution on `main`'s version** — the long one. Do not take the branch's
  wholesale; you would lose ~180 lines.
- **Port forward one thing:** the branch's **"Going live" runbook** section. Recover with
  `git show origin/m8-keyless-slice:README.md`. Place it after "Replay mode", before
  "Quickstart".
- The branch README is *not* simply "the old README plus a runbook" — it also carries
  provider-swap edits. Read it in full before deciding what to port; do not assume the
  runbook is the only delta.

### The honesty requirement — do not skip this

**Merging `9bbc336` adds no runtime behavior.** `get_feed_client()` is called by nothing
outside `tests/unit/test_live_feeds.py`; `ingestion/scheduler.py` still hardcodes
`ReplayFeedClient` and the commit never touched it. `odds_api.fetch_odds` and
`open_meteo.fetch_weather` have zero production callers. 259 unit tests will go green over
code that is not on any execution path.

So: after merging, **the README must not claim the factory picks an implementation from
`REPLAY_MODE`** as though that were live. State plainly that the live feed clients are
landed but not yet wired into the ingestion scheduler, and point at Phase E. Wiring them is
Task E2 — not this task.

### Post-merge doc corrections (required)

- **README replay-mode paragraph** — currently says Haiku/Sonnet/Voyage. Cassettes still
  replay unchanged (they key on the model string *as recorded*), but live mode is Gemini.
  Reword to say exactly that.
- **README secrets list** — read the merged `.env.example` and match it. Note: `.env.example`
  still advertises `VOYAGE_API_KEY`, a config field nothing reads after the merge. Drop it
  from **both** files in this task and say so in the commit body.
- **README "Status" section** — M8's keyless slice has landed; live wiring and verification
  remain. Point at this file.
- **`ARCHITECTURE.md`** — mentions of Haiku, Sonnet, and Voyage. Update, and add a pointer to
  `docs/AMENDMENTS.md`, which this merge brings in.

**Do NOT** rename `settings.haiku_model` / `sonnet_model` / `voyage_model` (deferred, F1).

**Done means:** merge committed; standard gate green with **259** tests; README and
`.env.example` agree on the secrets list with no `VOYAGE_API_KEY`; README does not claim the
feed factory is live. Replay E2E and integration are **not verifiable here** (no Docker) —
do not claim they pass.

**Commits:** the merge commit, then
`docs: reconcile README and ARCHITECTURE with the Gemini swap and label the unwired feed slice`

### R-A2 — Review (two reviewers)

`ecc:code-reviewer` checklist: (a) confirm the README retained `main`'s content — spot-check
that the architecture diagram, testing tiers, and project structure sections survive;
(b) confirm the "Going live" runbook is present; (c) grep the README for `ANTHROPIC_API_KEY`
and `VOYAGE_API_KEY` and confirm they match `.env.example`; (d) confirm no false claim that
the feed factory is on an execution path — verify by running
`git grep -n "get_feed_client" -- src/ scripts/ dashboard/` and confirming the README's
wording matches the (empty) result; (e) re-run the standard gate and report the **actual**
test count, not the expected one.

`ecc:security-reviewer` checklist, over `git diff main~1...HEAD` restricted to
`src/hailmary/clients/feeds/`: (a) does any secret reach an exception message, log line, or
URL that could be logged? (b) are the new HTTP clients' URLs constructed from validated
input? (c) do the `except → return []` degradation paths distinguish a real outage from a
genuinely empty result? Findings here are expected — B5 fixes the known one. Record any
*additional* ones for Ekam rather than fixing inline.

---

## Task A3 — Push and confirm CI

```bash
git push origin main
```

Both CI jobs must be green: job 1 = ruff + unit; job 2 = boots the four stores, migrates,
runs the replay E2E + integration tier, keyless.

**If job 2 goes red:** this is the first real signal the merge broke something. Fix forward
in a new commit; prefer fixing the code over weakening the test. If you cannot fix it in this
session, `git revert` the merge commit and escalate — do not leave `main` red and do not
force-push.

**Done means:** both jobs green on `main`.

---

# Phase B — Correctness fixes

This phase did not exist in v1. Every task here is an audit-confirmed defect on merged code.
No keys, no Docker. Ordered by severity, with dependencies respected.

## Task B1 — Wire Elo ratings into the query path ⚠️ CRITICAL

**The defect:** `routes.py::submit_research`, `scripts/run_replay_e2e.py`, and
`scripts/author_cassettes_v0.py` all pass `"team_ratings": {}` into the graph.
`report.py::_model_probability_for_matchup` then does `team_ratings.get(subject, 1500.0)` and
`team_ratings.get(opponent, 1500.0)` — both sides always 1500. Measured consequence, by
running the real functions: home team → p=0.5925 → EV **+13.11%** → `"value"`; away team →
p=0.5000 → EV −4.55% → `"no_value"`. With real ratings (1600 vs 1450, home) → p=0.7752 →
EV +47.98%. **The system currently declares "value" on every home team in every spread and
moneyline market.** This is the project's flagship feature and it is a function of home-field
advantage alone.

A working reader already exists and is called by nobody outside the ingestion job:
`ingestion/ratings_job.py::_load_current_ratings` →
`SELECT team_id, rating FROM team_ratings WHERE sport = $1 AND season = $2`.

**Steps:**
1. Extract `_load_current_ratings` into a shared reader (it is currently private to the
   ratings job). Keep the SQL identical.
2. Call it in `routes.py::submit_research` and put the result into
   `graph_state["team_ratings"]` instead of `{}`.
3. Same in `scripts/run_replay_e2e.py`.
4. **Remove the `1500.0` defaults** in `report.py`. When a rating is missing,
   `_model_probability_for_matchup` must return `None` so `build_edge_analysis` yields
   `assessment="insufficient_data"`. Fabricating a coin-flip is worse than admitting
   ignorance — and "insufficient_data" is already an honest, tested path in this codebase
   (the player-prop query uses it).
5. Add a regression test asserting the two teams' `model_probability` values **differ** and
   are not 0.5/0.5925.
6. `README.md` says Elo is "the sole source of model probability for the edge math."
   After this task that becomes true. Verify it reads correctly; do not delete it.

**Watch for:** step 4 changes behavior in replay mode. If `team_ratings` is empty in the
fixture path, the E2E's spread query flips from an edge block to `insufficient_data` and CI
job 2 goes red. **Check whether the fixture actually loads ratings** before assuming — the
Elo job runs on each ingestion pass. If the fixture genuinely has no ratings, that is a
finding to escalate, not to paper over by keeping the 1500 default.

**Investigation findings (2026-08-01, each verified directly against the code — these
materially de-risk the task):**

1. **Cassettes are unaffected; Rule 3 is not in play.** `writer.py::write_report_prose` builds
   its prompt as `WRITER_PROMPT_TEMPLATE.format(query=raw_text, evidence=_render_evidence(chunks))`.
   The edge block never enters the writer prompt, so changing `model_probability` **cannot**
   change a cassette key. No re-recording, no Ekam go-ahead needed for this task.
2. **The replay fixture does produce Elo rows.** `ingestion/scheduler.py` calls
   `run_ratings_job(feed, pg, settings.elo, season=season, as_of=fixture.virtual_clock)` during
   the replay ingestion pass. A real reader wired into the query path will therefore find rows
   in replay mode — the fix is testable on the fixture, not only in live mode.
3. **Removing the `1500.0` default is safe for CI job 2.** `_build_edge_analyses` emits one
   block per `live_odds` chunk regardless of whether `model_probability` is `None`, and
   `scripts/run_replay_e2e.py` asserts only that `report.edge_analysis` is **non-empty**. Worst
   case the spread query reports `insufficient_data` honestly and the assertion still holds.
4. **The test suite encodes the bug.** Of six `build_report` tests, only two in
   `tests/unit/test_report.py` pass real ratings; the other four pass `team_ratings={}`. That is
   why 245 tests stay green over a defect this large. Do not "fix" those four by giving them
   ratings — the new regression test is the one that must fail on revert.
5. **Residual uncertainty, not closable locally:** whether the fixture's `team_ratings` rows
   actually cover the specific teams in the E2E's canned queries is inferred from the code path,
   not observed — confirming needs Docker (Task D1). If they do not, correct behavior is
   `insufficient_data`, which is a **fixture bug worth surfacing**, not a reason to keep the
   1500 default.

**Done means:** standard gate green; the new regression test fails when step 4 is reverted;
no non-test caller passes an empty `team_ratings` dict
(`git grep -n '"team_ratings": {}' -- src/ scripts/` returns nothing).

**Commit:** `fix: load Elo ratings into the query path instead of defaulting both teams to 1500`

### R-B1 — Review (`ecc:python-reviewer`)

Checklist: (a) independently compute what the edge math returns before and after — run
`win_probability` and `expected_value_pct` yourself with 1500/1500 and with two distinct
ratings, and confirm the numbers moved; (b) confirm the regression test fails against
reverted code; (c) confirm `insufficient_data` is returned, not a fabricated default, when
ratings are missing; (d) grep for any *remaining* `1500.0` literal in the synthesis path;
(e) assess the CI-job-2 risk in step 4 and state explicitly whether the fixture supplies
ratings — this is the item most likely to be hand-waved.

---

## Task B2 — Fix the dashboard's event-loop bug ⚠️ CRITICAL

**The defect:** `dashboard/app.py` does
`@st.cache_resource def _pg_connection(): return asyncio.new_event_loop().run_until_complete(get_pg_connection(settings))`,
then every panel calls `asyncio.run(get_*(pg))`. `asyncio.run` builds a **new loop each
call**; asyncpg binds its futures to the connection's creating loop
(`asyncpg/connection.py` `self._loop = loop`). Awaiting a loop-A future from loop B raises
`RuntimeError: ... attached to a different loop`. **Every panel raises before rendering.**

Nothing catches this: `tests/unit/test_dashboard_import_smoke.py` imports only
`dashboard.queries`, never `dashboard.app`; CI never runs Streamlit; `app.py`'s own docstring
says "Not automatically tested."

**This must land before C1/C3.** Both feed data to a dashboard that cannot currently render
it, and their unit-tier gates would never reveal that.

**Fix:** either cache a single loop alongside the connection and use
`loop.run_until_complete(...)` for every panel, or open a short-lived connection inside each
`asyncio.run`. Prefer whichever is simpler to test.

**Also:** extend `test_dashboard_import_smoke.py` to import `dashboard.app`. It cannot fully
exercise Streamlit, but an import smoke test is strictly better than the current zero
coverage.

**Done means:** standard gate green; `dashboard.app` is imported by a test; the loop-lifetime
fix is explained in a comment so it is not "simplified" back later. **Full verification needs
Docker — defer to Task D1 and mark it BLOCKED here, do not claim the panels render.**

**Commit:** `fix: give the dashboard a single event loop so asyncpg panels can render`

### R-B2 — Review (`ecc:python-reviewer`)

Checklist: (a) trace the loop lifetime yourself and confirm one loop owns both the connect and
every query; (b) confirm `st.cache_resource` interaction is sound — a cached connection
outliving its loop is the original bug, so check the fix does not just relocate it; (c) confirm
the import smoke test covers `dashboard.app`; (d) return **BLOCKED** on "panels actually
render" and say so explicitly rather than passing on a code-reading.

---

## Task B3 — Run the freshness gate on cache hits

**Spec violation.** DESIGN.md §5 Phase 3 permits reuse only "On a hit at cosine ≥ 0.92 with
non-stale evidence", and Appendix A: "if the cached structured evidence is older than its TTL,
it's treated as a miss and re-retrieved." `merge_context`'s hit path refreshes only
`live_odds` and never gates the cached injury/weather/semantic chunks.

Compounding this, the merged branch's `_refresh_live_odds` appends every Redis odds chunk not
already in the cached context **unconditionally** — those chunks skip `gate()`, get no rerank
score, and are not counted against `context_budget_chunks`. So the hit path can emit a longer,
differently-ordered chunk list than the miss path, which is precisely what the branch's commit
message claims it fixed. The existing test asserts only that the source names are present —
never length or order — so it stays green through both the overflow and the gate bypass.

**Fix:** after `_refresh_live_odds`, run `gate()` over the refreshed list with the current
`now` and re-truncate to `context_budget_chunks`. If any non-odds chunk is dropped as stale,
treat the entry as a miss and fall through to the full retrieve path per Appendix A.
Recompute `dropped_stale` for the served context rather than inheriting the cached value.

**Add tests** asserting the hit path and the miss path produce the **same length and the same
order** for the same inputs. That invariant is what the docstrings claim and nothing checks.

**Done means:** standard gate green; new order/length tests fail against reverted code; the
docstring claims in `merge.py` and `cache.py` are either true or corrected.

**Commit:** `fix: gate and re-truncate cached context on a semantic-cache hit`

### R-B3 — Review (`ecc:code-reviewer`)

Checklist: (a) read DESIGN.md §5 Phase 3 and Appendix A yourself and confirm the fix matches
the spec, not just the finding; (b) confirm the new tests fail against reverted code;
(c) confirm the docstrings no longer overclaim; (d) check that the fall-through-to-miss path
cannot recurse or double-retrieve.

---

## Task B4 — Reject future-dated chunks in the freshness gate

`rerank/freshness.py` lets future-dated chunks bypass the TTL entirely, and such a chunk can
become the report's `line_as_of` stamp. Clamp or reject them, and test the boundary.

**Done means:** standard gate green; a future-timestamp test fails against reverted code.

**Commit:** `fix: treat future-dated chunks as invalid in the freshness gate`

### R-B4 — Review (`ecc:python-reviewer`)
Checklist: boundary cases — exactly-now, one second future, one second past. Confirm the
`line_as_of` stamp cannot be sourced from a rejected chunk.

---

## Task B5 — Stop leaking the Odds API key into exceptions 🔒

*(Requires A2 merged.)* `feeds/odds_api.py` passes the secret as a query parameter
(`"apiKey": settings.odds_api_key`) then calls `response.raise_for_status()` unguarded. httpx
embeds the **full request URL — including the key** — in `HTTPStatusError`'s message. Any 4xx
or 5xx from the vendor prints a live API key into logs and tracebacks.

**Fix:** catch `httpx.HTTPStatusError` and re-raise sanitized — use
`exc.response.status_code` and `exc.request.url.copy_remove_param('apiKey')`. Apply the same
treatment before any log line that could carry the request URL. Prefer a header if the vendor
supports one.

**While here, also fix:** `feeds/scraper.py::fetch_docs` swallows every HTTP error and its
comment promises logging that does not exist. Either log or remove the promise.

**Done means:** standard gate green; a test asserts the sanitized error does **not** contain
the key value.

**Commit:** `fix: sanitize Odds API errors so the key never reaches logs or tracebacks`

### R-B5 — Review (`ecc:security-reviewer`)
Checklist: (a) construct the error path yourself and confirm the key is absent from the
message; (b) grep the whole feeds package for other places a secret could reach a log, URL, or
exception; (c) confirm the scraper's comment and behavior now agree.

---

## Task B6 — Make mypy actually run

`[tool.mypy]` is configured with `strict = true` on contracts, mypy is a declared dev
dependency, and **no CI job or pre-commit hook ever invokes it**. It fails on `main` right now
with 9 errors — 4 in the contracts/pure-math groups, 5 `[no-untyped-def]` across
`rerank/cache.py`, `rerank/cross_encoder.py`, and `rerank/merge.py` (the `files` list covers
`src/hailmary/rerank` too, so the scope is wider than it first appears). README advertises the
gate.

**Fix the 9 errors, then add `uv run mypy` to CI job 1 and to Rule 6's standard gate.** If any
error cannot be fixed without touching frozen `contracts.py`, stop and escalate — do not
loosen the mypy config to make it pass.

**Done means:** `uv run mypy` exits 0; CI job 1 runs it; Rule 6 in this document is updated.

**Commit:** `fix: clear the 9 mypy errors and enforce mypy in CI`

### R-B6 — Review (`ecc:build-error-resolver`)
Checklist: (a) run `uv run mypy` yourself and confirm exit 0; (b) confirm the fix narrowed
types rather than adding `# type: ignore` or loosening config — `git diff pyproject.toml`
should show no weakening; (c) confirm CI job 1 actually invokes it.

---

## Task B7 — Put `GET /report/{query_id}` behind the gating chokepoint

DESIGN.md §12 specifies gating as "a deterministic chokepoint before any report is returned",
and `gating.py`'s docstring repeats "runs before ANY report is returned". `routes.py::get_report`
never calls it — one of the two report-returning paths is ungated.

**Note the distinction from F4:** the deferred item is *implementing jurisdiction logic inside
the stub*. This task adds the **missing call site**. Runtime impact today is nil
(`GATING_ENABLED` defaults false); the defect is architectural.

`GET /report/{query_id}` takes no user identity — either accept a `user_id` query parameter or
resolve it from the stored `research_queries.user_id` row. Add a unit test asserting
`get_report` raises when gating is enabled, mirroring the existing `tests/unit/test_gating.py`.

**Done means:** standard gate green; the new test fails against reverted code.

**Commit:** `fix: route GET /report through the gating chokepoint`

### R-B7 — Review (`ecc:fastapi-reviewer`)
Checklist: (a) enumerate every path that returns a report and confirm each passes the
chokepoint; (b) confirm the stub still raises `NotImplementedError` (F4 is untouched);
(c) confirm the new test fails against reverted code.

---

## Task B8 — Phase B standing review, push, confirm CI

Run `ecc:code-reviewer` over the full Phase B diff, then `ecc:security-reviewer` (Phase B
touched secrets and user input). Push. Both CI jobs green.

**Then stop and report to Ekam before starting Phase C.** Phase B changed correctness-critical
numeric behavior; it deserves a human look before more work stacks on it.

---

# Phase C — Observability wiring

No keys, no Docker. **Requires B2** (the dashboard must be able to render before we feed it).

## Task C1 — Wire per-phase query events

`obs/events.py::record_event` is called by **nothing**; only `record_ingestion` is used.
`dashboard/queries.py::get_query_trace` does
`SELECT phase, event, detail, ts FROM events WHERE query_id = $1`, so the trace panel has no
data source. DESIGN.md §10 calls this table the "first stop for debugging 'what happened to
query X?'"

**Where:** `graph.py`. Each node already has `state["pg"]` and `state["query_id"]`. Emit from
the nodes, not from inside the phase modules — the graph is the one place that sees every
transition, and the phase modules are deliberately I/O-light.

| Node | phase | event | detail |
|---|---|---|---|
| `decompose_node` | `decompose` | `started` | `{"raw_text_len": ...}` |
| `decompose_node` | `decompose` | `out_of_scope` | `{"reason": ...}` |
| `decompose_node` | `decompose` | `clarification_needed` | collision candidates |
| `decompose_node` | `decompose` | `completed` | `{"intent": ..., "indexes": [...]}` |
| `retrieve_node` | `retrieve` | `completed` | `{"counts_per_source": {...}, "sources_failed": [...]}` |
| `merge_node` | `merge` | `completed` | `{"cache_hit": bool, "chunks_in": n, "chunks_out": n}` |
| `synthesize_node` | `synthesize` | `completed` | `{"citations": n, "edge_assessment": "..."}` |

Constraints:
- **Event logging must never fail a query.** Wrap each call so a Postgres error is swallowed
  and the phase still returns. This is the one place in the codebase where swallowing is
  correct — say so in a comment so a future reviewer does not "fix" it.
- Pull `detail` from data the node **already has**. Do not add a query or a timing harness to
  manufacture a field. If a field is not cheaply available, drop it and note that in the commit.
- `detail` is `json.dumps`'d — everything must be JSON-serializable. Pydantic models are not;
  use `.model_dump(mode="json")`.
- `state["pg"]` may be `None` in some unit-test paths. Guard.

**Tests** (`tests/unit/test_graph_events.py`): fake `pg` recording `execute` calls; assert
(a) happy path emits the full sequence in order, (b) the out-of-scope short-circuit emits
`decompose/out_of_scope` and **no** retrieve/merge/synthesize events, (c) a `pg` that raises
still returns a report.

**Done means:** standard gate green; new tests fail against reverted code; no existing test
modified to accommodate the change.

**Commit:** `feat: emit per-phase query events so the dashboard trace panel has data`

### R-C1 — Review (`ecc:silent-failure-hunter`)
Chosen deliberately: this task *mandates* swallowing exceptions. Checklist: (a) confirm the
swallow is scoped to event logging only and cannot mask a phase failure; (b) confirm the
comment explains why; (c) confirm no *other* exception got swallowed as collateral;
(d) confirm the `pg is None` guard cannot hide a real misconfiguration in production;
(e) confirm test (c) genuinely raises from the fake.

---

## Task C2 — Wire the LLM cost circuit breakers

`QueryCostTracker` and `DailyCostTracker` are implemented and unit-tested in `obs/cost.py`,
with caps in `config.py` (`per_query_usd_cap=0.15`, `per_query_usd_alert=0.10`,
`per_day_usd_cap=2.0`, `per_day_usd_alert_pct=0.80`). **Nothing in `src/` imports either
class.** DESIGN.md §9: "A query exceeding the cap returns the deterministic evidence/edge
block without full prose synthesis." **Degrade to evidence-only; do not raise.**

### Two seams v1 got wrong — read before coding

**Seam 1 — the evidence-only builder is NOT in `citation_guard.py`.** v1 said it was. It is
`report.py::_evidence_only_fallback`, it is private, and it is called only from
`build_report`'s `if report is None:` branch. Reuse *that*, and keep the over-cap path inside
`report.py` rather than importing a private symbol from `synthesize_node`.

**Seam 2 — `complete()` has no token counts.** v1 said to charge cost in
`LLMClient.complete` and treated missing prices as the only blocker. But `complete()` returns
only the validated Pydantic model and discards the provider envelope, so
`input_tokens`/`output_tokens` have no source either. Resolution, confirmed available in this
environment: instructor v2 exposes `create_with_completion` on the async client. Switch the
live branch to it, read `completion.usage.prompt_tokens` / `completion_tokens`, and pass the
tracker in as an **optional keyword arg defaulting to `None`** so the non-graph call sites are
untouched. **`complete()`'s return type must not change** — four test files
(`test_routes.py`, `test_graph.py`, `test_plan.py`, `test_report.py`) define `FakeLLM` doubles
that depend on it.

**Also note:** the provider swap silently removed `max_tokens=1024` from the only live LLM
call path. Restore an explicit output cap as part of this task — an uncapped output is both a
cost and a latency risk, and the breaker is a poor substitute for a hard limit.

### The price problem

`estimate_cost_usd` needs per-MTok prices and `CostConfig` has no fields for them. Per Rule 4,
do not invent Gemini prices. Add `input_price_per_mtok: float | None = None` and
`output_price_per_mtok: float | None = None`, defaulting to `None`. When either is `None`,
skip accounting entirely (emit one `cost_tracking_disabled` event via C1) and let the query
proceed. Wire the full breaker path so it activates the moment real prices are set.
**Ekam supplies the prices — ask, do not look them up and guess at the tier.**

**Charging rules:** replay-mode calls cost $0 — never charge them, or the replay E2E starts
tripping breakers. `DailyCostTracker` lives on FastAPI app state; cross-restart persistence is
F3, and C3 handles the dashboard read path.

**Tests** (`tests/unit/test_cost_wiring.py`): (a) over-cap tracker → `build_report` skips the
writer and returns evidence-only with the edge block intact; (b) under cap → writer called
normally; (c) `None` prices → no accounting, query completes; (d) replay mode never charges.

**Done means:** standard gate green; new tests fail against reverted code; the four `FakeLLM`
doubles are unmodified.

**Commit:** `feat: wire the per-query and per-day LLM cost breakers into the query path`

### R-C2 — Review (`ecc:python-reviewer`)
Checklist: (a) confirm `complete()`'s return type is unchanged and the four `FakeLLM` doubles
were not edited; (b) confirm replay mode charges nothing — trace it, do not assume;
(c) confirm the over-cap path reuses `_evidence_only_fallback` rather than a second builder;
(d) confirm `max_tokens` is restored; (e) confirm no price literal appears anywhere.

---

## Task C3 — Persist LLM spend so the dashboard can show it

DESIGN.md §5 panel (d) requires "LLM spend per query/day vs caps" with "Dashboard reads
Postgres/Redis directly", and §9 requires an 80%-of-daily-cap alert **on the dashboard**.
C2's trackers live in FastAPI process memory; Streamlit is a **separate process** and cannot
see them. Without this task the cost panel stays exactly as empty as before — it currently
renders only the Odds budget metric and the static cap constants.

**Fix:** write each query's spend to Postgres — reuse the `events` table C1 wires, or a small
dedicated row — then add `dashboard/queries.py::get_llm_spend()` and render it in the Cost tab
with the 80% alert.

**Done means:** standard gate green; `get_llm_spend` has a unit test; the Cost tab renders a
real spend value. *(Rendering is Docker-gated — mark BLOCKED and verify in D1.)*

**Commit:** `feat: persist LLM spend and surface it on the dashboard cost panel`

### R-C3 — Review (`ecc:database-reviewer`)
Checklist: (a) confirm the write path cannot fail a query; (b) confirm the read query is
bounded (no unbounded scan of `events`); (c) confirm the 80% alert threshold reads from config,
not a literal; (d) BLOCKED on actual rendering.

---

## Task C4 — Install structured logging

A third unwired observability module the audit found: `obs/logging_config.py::configure_logging`
is never called by any entrypoint, so DESIGN.md §10's JSON-to-stdout logging does not happen.
Call it from the FastAPI lifespan and from the ingestion worker's entrypoint.

**Done means:** standard gate green; a test asserts `configure_logging` is invoked on app
startup.

**Commit:** `feat: install structured JSON logging at both entrypoints`

### R-C4 — Review (`ecc:code-reviewer`)
Checklist: confirm both entrypoints call it; confirm it is idempotent (double-configuring
loggers duplicates output).

---

## Task C5 — Phase C standing review + **re-audit** + push

1. `ecc:code-reviewer` over the full Phase C diff.
2. **Re-run the multi-lens audit** (5 lenses → adversarial verify → completeness critic)
   against the current repo *and* against this document. Phases A–C changed enough that new
   holes are likely, and this plan's own accuracy has decayed. Confirmed findings become the
   Phase D backlog.
3. Push; both CI jobs green.
4. **Report to Ekam and stop.** Everything past this needs Docker or keys.

---

# Phase D — Local verification (needs Docker; Ekam-gated)

## Task D1 — Install Docker Desktop and run the full stack

```bash
docker compose -f docker/docker-compose.yml up -d
uv run python scripts/migrate.py
uv run pytest -m integration -q
uv run python scripts/run_replay_e2e.py
```

**This is where every BLOCKED item from Phases B and C gets resolved.** Specifically confirm:
- The dashboard panels actually render (B2, C3).
- The replay E2E still passes after B1's Elo change — and that the spread query's edge block
  now shows **different** `model_probability` values for the two teams. If it still shows
  0.5925, B1 did not work.
- Integration tests pass after B3's cache-gating change.

**Done means:** four containers healthy; integration tier green; replay E2E prints 3 OK; every
Phase B/C BLOCKED item resolved to PASS or escalated.

### D1 partial run — 2026-08-02, after B1 only

Docker arrived early, so D1 was run against a tree containing **B1 and nothing else from
Phases B/C**. Four containers healthy, `0001_init.sql` applied, `pytest -m integration` 6
passed, replay E2E 3 OK. Recorded results:

- **B1 — PASS, verified end-to-end.** The E2E logged `Loaded 4 team ratings for nfl/2026`,
  closing the open question of whether the fixture supplies ratings. Stored
  `research_reports` row for `q_spread`:

  | market | selection | odds | implied | model_probability | EV | assessment |
  |---|---|---|---|---|---|---|
  | spread | KC -6.5 | −108 | 0.5192 | **0.865555** | **+66.70%** | value |
  | moneyline | KC | −280 | 0.7368 | **0.865555** | +17.47% | value |
  | total | Over 46.5 | −105 | 0.5122 | None | None | insufficient_data |

  Ratings read back: KC 1629.2504, LV 1370.7496 (BUF 1642.75, MIN 1357.25). The
  home-field-only artifact 0.5925/+13.11% is gone, and `total` correctly falls outside
  `COVERED_MARKETS`. **CI job 2 is not at risk** — the spread query still emits edge blocks.

- **B2 — CONFIRMED, still broken (expected; not yet implemented).** Reproduced directly:
  importing `dashboard.app`, taking `_pg_connection()`, then calling a query through
  `asyncio.run` raises
  `RuntimeError: Task ... got Future ... attached to a different loop` from
  `asyncpg/protocol/protocol.pyx:165`. The audit's code-reading is now a reproduction.

- **Two findings sharpened by having a live database:**
  - `events` table has **0 rows** after a full E2E — confirms C1 (`record_event` has no caller).
  - `session_turns` has **0 rows** — confirms the E8 item that nothing ever inserts one.
  - `odds_archive` has **11 rows**, but the ingestion summary reported
    `odds_<game_id>: 0` for all three games and `record_ingestion` logged `records=0`.
    **The archive write succeeds while its own count lies.** Not in B1's scope; add to the
    Phase D backlog — a monitoring path that reports 0 for successful work is worse than
    no monitoring.

---

# Phase E — Live mode (needs keys + season data; Ekam-gated)

v1's Phase D was unsatisfiable as written. The audit found a **circular dependency** that
blocks it, a **command that fails on argparse**, a **gate that cannot be met with one `.env`**,
and a **missing re-embedding step**. Rewritten accordingly, and resequenced.

## Task E1 — Acquire keys, model ids, and prices

- `GEMINI_API_KEY` (LLM **and** embeddings), `CFBD_API_KEY`, `ODDS_API_KEY` (free tier,
  **500 req/month**).
- **Provider-qualified model ids** — this is not just keys. Live mode requires
  `HAIKU_MODEL` / `SONNET_MODEL` / `VOYAGE_MODEL` set to Gemini ids (e.g.
  `google/gemini-2.5-flash`); `llm.py` raises if the id has no `/`.
- Gemini per-MTok input/output prices for C2's `CostConfig`.

**The cassette collision — understand this before proceeding.** The model id is the **first
component of every cassette key**. Changing it to a Gemini id makes every committed
`synthetic_v0` cassette miss. Therefore **replay and live are two different `.env`
configurations and cannot be one file.** Either (a) decouple the cassette model component
into a separate `cassette_model_id` setting, or (b) keep two env files and state plainly that
`synthetic_v0` passes with the replay config while `real_week_v1` passes with the live config.
**Pick one and record it in `docs/AMENDMENTS.md` before writing code.** Option (a) is cleaner
and makes CI's keyless guarantee robust; option (b) is cheaper.

## Task E2 — Wire the feed factory into the ingestion scheduler

**Blocks E3 and E4.** The A2 merge landed the live feed clients but nothing calls them —
`ingestion/scheduler.py` hardcodes `ReplayFeedClient`. Replace it with `get_feed_client()`, and
add the per-game odds/weather loop the factory docstring promises but no code implements.

Also fix, while here:
- `get_feed_client` constructs `LiveFeedClient` **without `scrape_sources`**, so the curated
  scraper can never return a document.
- `_consume_budget` in `odds_api.py` is a non-atomic SELECT-then-UPDATE; concurrent callers can
  overshoot the "hard" monthly cap. Make it atomic.
- **`api_budget` has no seed row anywhere**, so the guard fails closed with a setup error on the
  first live call, and the Going-live runbook never mentions seeding. Add seeding + a runbook step.
- `test_odds_budget_guard_refuses_before_any_http` **never calls `fetch_odds`** — it does not
  test its own name. Rewrite it to assert no HTTP call is issued when over budget.

**Done means:** `REPLAY_MODE=false` demonstrably changes ingestion behavior; the budget guard
test actually exercises the guard.

## Task E3 — Re-embed the corpus

**Missing entirely from v1.** Both `docs/AMENDMENTS.md` and `clients/voyage.py` state that
going live requires re-embedding the whole document corpus with the Gemini embedding model,
because query and document vectors must share one scheme. Today `fixtures/synthetic_v0` ships
`{"model": "synthetic-placeholder-16d", "dim": 16}`.

Re-embed all `semantic_docs` with the live model, **recreate the Qdrant collections at the new
vector size** (`ensure_collection` is create-if-missing — it will silently reuse the old size
otherwise), and gate on a known-answer semantic retrieval check.

**Decide up front:** does `synthetic_v0` stay on the 16-dim placeholder scheme so CI remains
keyless, or move too? Keeping it keyless is almost certainly right. Record the decision.

**Also fix:** `build_fixture.py` hardcodes `EMBEDDING_DIM = 64` with a comment claiming it
"matches synthetic_v0" — synthetic_v0 is 16. The shared `SEMANTIC_CACHE` collection is sized
from the manifest but filled by live mode at a third dimension.

## Task E4 — Live ingestion inside the budget

**Prerequisite the audit found:** `build_fixture.py` sources `odds_timeseries.jsonl` by
exporting the `odds_archive` table, whose only writer is the *replay* ingestion pass reading
odds out of an *existing fixture*. **Circular.** E2's live scheduler must run first and
populate `odds_archive` from live data, or E5 can never produce a fixture containing real odds.

Enable sources one at a time — keyless/free first (nflverse, Open-Meteo), then CFBD, then
**Odds API last**. After each, check the `api_budget` table and the dashboard's budget panel.
Target cadence ~120 req/month against a 500 cap.

**Done means:** a full live pass completes; `ingestion_log` shows `ok`; `api_budget` is inside
cadence; a deliberately over-budget call is **refused before the HTTP request** — assert it,
do not assume.

## Task E5 — Build and validate `real_week_v1`

The real invocation — v1's version fails immediately on argparse:
```bash
uv run python scripts/build_fixture.py --season 2025 --week 18 --name real_week_v1
```

**Known defects to fix first:**
- The builder stamps every `StatRecord`'s `indexed_at` with **build wall-clock time**, while
  pinning the manifest's `virtual_clock` to the fixture week's kickoff. `ReplayFeedClient`
  filters `indexed_at <= virtual_clock`, so **the one payload the builder populates is
  discarded in full at ingestion.** Pass a fixture-week timestamp instead.
- The builder writes empty `semantic_docs`, empty `weather`, and an empty embeddings map.
- Its embeddings file uses `embedding_model`/`vectors` keys where synthetic_v0 uses
  `model`/`dim`/`vectors`.

**Split the gate** — v1's single gate was unsatisfiable:
- (a) `build_fixture.py` produces a **loadable** fixture, with a positive assertion on
  ingestion summary counts (`stats_nfl > 0`), not merely "it loads".
- (b) In-season prerequisites are named as preconditions: `odds_archive` populated by E4's live
  scheduler, curated scrape docs captured, weather captured live.
- (c) State explicitly that an **off-season build yields an odds/weather/doc-empty fixture** and
  therefore cannot pass the same three canned E2E queries as synthetic_v0 —
  `run_replay_e2e.py` hardcodes "Chiefs -6.5 against the Raiders" and fails unless it produces
  an edge block. A real fixture from an arbitrary week will not contain that game.
- (d) Qdrant collections are dropped/recreated (or namespaced per fixture) when switching
  `FIXTURE_NAME`. "synthetic_v0 still passes" must be a **separate run against a clean store**,
  not an implied same-instance property.

## Task E6 — Tighten the citation-guard regeneration prompt

Quarantined here because **it changes a prompt string and therefore invalidates cassettes**
(Rule 3) — it cannot be done in Phase B or C.

DESIGN.md §5 Phase 4 mandates "regenerate up to 2× with a **tightened prompt**". The retry loop
in `report.py` re-invokes the writer with loop-invariant arguments. In replay mode the cassette
key is identical, so attempts 2 and 3 return the byte-identical draft — a strict no-op. In live
mode no temperature or seed is set, so a retry can differ only by provider nondeterminism. Either
way, **nothing is tightened**, and DESIGN.md, both module docstrings, and README all claim
otherwise.

Add an escalating strictness parameter to `write_report_prose` (restate the valid `chunk_id`
allowlist, name the citations just stripped) and pass the attempt index. **Re-record the writer
cassettes in the same task.** If Ekam prefers not to re-record, the alternative is to delete the
retry loop and go straight to `_evidence_only_fallback`, then correct the three documents — that
is a legitimate choice and cheaper.

## Task E7 — Retention, soak, and provider breakers

- `uv run python scripts/compact.py` against a populated DB; assert DESIGN.md §11 retention
  windows are enforced — rows outside the window gone, rows inside intact.
- Container soak: kill each store in turn under load; confirm degradation via `sources_failed`,
  not a 500.
- **Exercise the C2 cost breaker end-to-end** — v1 never did. D4's "breaker soak" was about
  container circuit breakers; the LLM cost breaker was wired and never fired. Force a
  small `per_query_usd_cap` and confirm the query returns evidence-only with the edge block intact.
- **§9 provider circuit breakers** (5 consecutive 5xx → pause the stage) exist nowhere in the
  codebase. Implement or record as an amendment.

## Task E8 — End-state check

The audit's completeness critic found that no task proves the whole thing works. This is it.

On a **clean clone into a fresh directory**, run exactly the README quickstart — nothing else,
no local state, no cached venv:

```bash
git clone https://github.com/esingh25/Project-HailMary.git && cd Project-HailMary
cp .env.example .env
uv sync --all-groups
docker compose -f docker/docker-compose.yml up -d
uv run python scripts/migrate.py
uv run python scripts/run_replay_e2e.py
```

**Done means:** it works from a cold start with no keys, exactly as the README claims. Any step
that needs an undocumented action is a README bug — fix the README, not your local setup. This
is what a reviewer of your GitHub will actually do.

Also close out the remaining items the audit confirmed but no task above owns:
- `session_turns` table is created, retained, and compacted, but **nothing ever inserts a row**.
- `odds_archive` is **write-only** — the "opening → current" line-movement narrative has no
  opening line to cite.
- A single subject-team win probability is applied to **every** odds chunk, including the
  opponent's side of the same market.
- The `.pre-commit-config.yaml` `detect-secrets` hook points at a `.secrets.baseline` that does
  not exist.
- `POST /research` accepts an **unbounded** `raw_text` that flows into three LLM prompts.
- `check_gating`'s docstring promises `GatingDeniedError`; the code raises `NotImplementedError`
  and the exception class is dead.
- Three §6.4/§8 storage deviations are justified in SQL comments but absent from `AMENDMENTS.md`.
- `record_cassettes.py` records only 2 of the 4 cassette kinds, though AMENDMENTS A1 points at it
  as *the* re-record instruction.

---

# Phase F — Explicitly deferred

Listed so they are not mistaken for oversights. **Do not do these.**

- **F1 — Config field rename.** `haiku_model`/`sonnet_model`/`voyage_model` now hold Gemini ids.
  Touches config, `.env.example`, `graph.py`, `report.py`, tests. Do it when nothing else is in flight.
- **F2 — Python package rename** (`hailmary` → …). Large, risky, no user value.
- **F3 — Daily cost persistence across process restarts.** Flagged in `obs/cost.py`'s own
  docstring. Note C3 handles the *dashboard read path*; this is the separate restart-durability item.
- **F4 — Implementing jurisdiction logic inside `delivery/gating.py`.** DESIGN.md §12 scopes it as
  a demo stub. **Not a bug.** (B7 adds the missing *call site* — different thing.)
- **F5 — `clients/voyage.py` `NotImplementedError`.** Resolved by the A2 merge. If it still raises
  after merging, that *is* a bug — report it.

---

# Task summary

| # | Task | Reviewer | Docker | Keys |
|---|---|---|---|---|
| A1 | Finish the rebrand | code-reviewer | – | – |
| A2 | Merge M8 slice, reconcile docs, label unwired | code-reviewer + security-reviewer | – | – |
| A3 | Push, confirm CI | – | – | – |
| **B1** | **Wire Elo ratings into the query path** ⚠️ | python-reviewer | – | – |
| **B2** | **Fix dashboard event loop** ⚠️ | python-reviewer | – | – |
| B3 | Gate + re-truncate on cache hit | code-reviewer | – | – |
| B4 | Reject future-dated chunks | python-reviewer | – | – |
| B5 | Stop leaking the Odds API key 🔒 | security-reviewer | – | – |
| B6 | Make mypy run, clear 9 errors | build-error-resolver | – | – |
| B7 | Gate `GET /report` | fastapi-reviewer | – | – |
| B8 | Phase review, push, **stop for Ekam** | code + security | – | – |
| C1 | Per-phase query events | silent-failure-hunter | – | – |
| C2 | LLM cost breakers | python-reviewer | – | – |
| C3 | Persist spend for the dashboard | database-reviewer | – | – |
| C4 | Install structured logging | code-reviewer | – | – |
| C5 | Phase review + **re-audit** + push | full audit fleet | – | – |
| D1 | Full local stack; resolve all BLOCKED | – | **yes** | – |
| E1 | Keys, model ids, prices, cassette decision | – | yes | **yes** |
| E2 | Wire the feed factory (blocks E4/E5) | security-reviewer | yes | **yes** |
| E3 | Re-embed the corpus | python-reviewer | yes | **yes** |
| E4 | Live ingestion inside budget | database-reviewer | yes | **yes** |
| E5 | Build + validate `real_week_v1` | code-reviewer | yes | **yes** |
| E6 | Tighten citation-guard prompt (re-records cassettes) | code-reviewer | yes | **yes** |
| E7 | Retention, soak, cost + provider breakers | security-reviewer | yes | **yes** |
| E8 | Clean-clone end-state check | code-reviewer | yes | **yes** |

**A1 → C5 is the agent-executable run.** D1 onward is Ekam-gated.
Highest value in the whole plan is **B1** — until it lands, the project's headline feature
reports a fabricated number.
