# Player Production Predictions — Design Decision

**Written:** 2026-08-02 · **Status:** approved design, not yet scheduled
**Sequenced as:** FINISH_PLAN.md Stage 5 — **starts only after E8**
**Method:** four independent designs from different angles, each scored by three judges
(architect / hiring-manager / quantitative skeptic), then synthesis. 18 agents, 12 verdicts.

---

## The problem

Ekam asked for the system to account for three things that move *player* production:

1. **New team situations** — DK Metcalf's production fell after the trade to Pittsburgh;
   George Pickens' rose moving to Dallas; Jaxon Smith-Njigba broke out once Lockett was
   released and Metcalf traded.
2. **New offensive coordinators** — Saquon Barkley and AJ Brown both dropped off under a new OC.
3. **Injuries elsewhere on the roster** — Daniel Jones' achilles diminished Jonathan Taylor;
   the Chargers' offensive line degraded the whole offense.

All three are **player props**, and `edge_math.py:42` (`COVERED_MARKETS = {"spread","moneyline"}`)
deliberately refuses to price that market. So this is not an extension of the Elo work. It is a
second model with its own uncertainty story.

---

## The decision

**Build the Usage Ledger, hard-cut variant.**

Decompose production into `team_volume × player_share × efficiency`; estimate each factor with
recency-weighted empirical-Bayes shrinkage whose priors are **refit from the data at job time**;
**hard-cut the estimation window at every detected regime boundary** (trade, scheme changepoint,
teammate absence) so no observation from a dead regime carries weight; convert the resulting
lognormal predictive distribution into `P(stat > line)`, which drops straight into the frozen
`EdgeAnalysis.model_probability` with **zero changes to `contracts.py`**.

When a regime just changed, the designed behavior is to **widen and refuse, not to guess**:
`n_eff` collapses at the cut, the posterior falls back to the fitted positional prior,
`CV_total` blows up, and the assessment degrades to `fair` or `insufficient_data`. That is the
same epistemics `ratings.py` already argues for unrated teams, extended to players.

### The scores

| Design | Architect | Interviewer | Skeptic | Sum | Tractability (per judge) |
|---|---|---|---|---|---|
| Regime Break (event study) | 22 | 20 | 21 | **63** | 3 / 2 / 3 |
| PPX (LightGBM quantile) | 21 | 21 | 20 | **62** | **2 / 2 / 2** |
| **Usage Ledger** ✅ | 20 | 20 | 21 | **61** | **3 / 3 / 3** |
| Role Ledger (no estimator) | 20 | 20 | 20 | **60** | 3 / 3 / 3 |

All four scored **5 on architectural fit and 5 on intellectual honesty**. The field separated on
**tractability** and on **where a wrong number can enter**.

### Why the highest scorer lost

**Regime Break has the better estimator and I am not picking it.** Every probability it emits
flows through one committed `residuals.json` produced by an offline script run once on a laptop.
All three judges independently found the same problem:

- The bank is bucketed by `(stat_key, n_basis)` — a *sample-size* proxy orthogonal to
  *production volume*. One pooled **additive** residual distribution would be applied to a
  28-yard receiver and a 95-yard receiver alike. At −112 the value/fair boundary is only a couple
  of probability points wide, so a mis-scaled bank manufactures confident "value" verdicts on
  high-volume players — and **every proposed unit test (monotonicity, complement symmetry,
  run-to-run identity) passes under an arbitrarily mis-scaled bank.**
- CI can verify a SHA-256 and a row count. That proves the file is internally consistent and
  proves nothing about whether the backtest that produced it leaked.

**That is the exact shape of the bug this project just shipped** — a plausible-looking constant,
upstream of every safety check, passing CI green. The whole layer's only number cannot sit behind
an artifact whose correctness is unauditable.

**PPX** is the best-argued document in the set and drew **tractability 2 from every judge**:
10–14 weeks self-estimated, realistically 16–20 part-time around coursework. Its ship gate is also
in the wrong place — ~5 weeks of ingestion and feature work land *before* the backtest, and if the
model fails to beat a trailing-4-game baseline its own rule is ship nothing. And the flagship demo
query (`"How many passing yards will Mahomes throw for?"`) is its thinnest data slice: roughly
5.7k QB-weeks over ten seasons for seven boosters over ~40 features.

**Role Ledger** is the honest loser: it emits no quantity reality can contradict, so no Brier
score, no calibration curve, no held-out season, and every knob is unadjudicable by data forever.

### Why Usage Ledger wins on the axis that matters

1. **No committed statistical artifact of any kind.** No trained model, no residual bank, no
   coefficient file. Priors and shrinkage constants are refit by method of moments from whatever
   data the job is handed, so fixture and live execute identical code. **There is no file that
   can silently be wrong.**
2. **Zero frozen-contract changes.** A prop is a binary market; `P(Y > L)` is exactly the shape of
   `EdgeAnalysis.model_probability`.
3. **Bit-identical arithmetic, no new dependency.** `statistics.NormalDist` is stdlib — no
   scipy/numpy skew, no model download, no golden-prediction test that breaks on a library bump.
4. **Consistent tractability 3**, and genuinely incremental — Phase 1 ships a real bug fix while
   every prop still returns `insufficient_data`.
5. **The lognormal is multiplicative**, so dispersion scales with the mean — sidestepping Regime
   Break's scale bug by construction.

---

## The correction applied before any code

The skeptic landed a real hit on the original Usage Ledger. Its `gamma_team`, `gamma_oc`,
`gamma_personnel` "adjacent regime" down-weights are **hand-set numbers upstream of every refusal
gate**. `min_effective_games`, `max_cv` and `max_line_z` all key off `n_eff` and `CV_total`, so
every gate sat downstream of the one number nobody fit. Set gamma generously and pre-trade weeks
retain weight, `n_eff` stays high, the interval stays tight, and the layer emits a confident
`value` verdict built on a regime that no longer exists — **in exactly the trade and OC cases that
motivated the project.** That is the fabricated-1500 disease again.

**Fix: delete gamma. Regimes are hard cuts — weight 1 inside the current regime, 0 outside.**
This grafts Regime Break's "never pool across a break" discipline onto Usage Ledger's estimator
and removes the free parameter entirely.

It also establishes the rule governing every remaining knob:

> **Every free parameter must be set so that its error direction is refusal.**

A hard cut can only shrink `n_eff` → only widen the interval → only push toward
`fair`/`insufficient_data`. It cannot manufacture an edge. Same logic sets the scheme changepoint
threshold to **over-detect**: a false positive costs a refusal; a false negative pools across a
real break and produces overconfidence.

### Parameter audit

| Parameter | Error direction if wrong | Safe? |
|---|---|---|
| Hard regime cut (replaces gamma) | Shrinks `n_eff` → widens → refuses | ✅ |
| `changepoint_z_threshold` (set low) | Extra cut → widens → refuses | ✅ |
| `half_life_games` (short) | Fewer effective observations → widens | ✅ |
| `min_effective_games` (high) | More refusals | ✅ |
| `max_line_z` (low) | More refusals | ✅ |
| **`max_cv` if set too HIGH** | **Admits noisy projections that should be refused** | ⚠️ **Set low — the one knob that can let a bad number through** |
| **"efficiency travels with the player"** | **Silently imports the wrong Ê on a trade** | ⚠️ **A stated assumption, not a fitted value — see caveats** |

---

## Grafts from the losing designs

| From | Graft | Why |
|---|---|---|
| **Role Ledger** | **`synthesis/numeric_guard.py`** — tokenize every numeric literal in the LLM draft, assert each appears in a cited chunk's content or the deterministic edge block, feed the existing `MAX_REGENERATIONS` loop. | **All three judges called this the highest-value item in the entire field.** `verify_citations` only checks that a claimed `chunk_id` exists — **nothing in the repo constrains the numbers in the prose.** "LLMs propose, deterministic Python disposes" is currently a docstring, not an invariant. ~4 days, pure, no Docker, ships standalone. |
| **Regime Break** | **Measure the scheme; don't look up the coordinator.** Changepoint-detect on neutral-script pass rate / plays-per-game / seconds-per-play from play-by-play. Use a hand-curated staff CSV **only as a prose label**, never as arithmetic input. | Kills silent-rot risk: a stale CSV row can mislabel prose but cannot corrupt a number. Also strictly better — a hire that changed nothing correctly moves nothing, and a mid-season play-calling handoff is caught even though no coordinator changed on paper. |
| **Regime Break** | Pooled ratios (`Σnum / Σdenom`), never mean-of-ratios. Carry `n_basis`/`n_eff` as first-class provenance. | Weights each week by its own opportunity. Makes the refusal condition a data property rather than a policy guess. |
| **PPX** | **`test_projection_leakage.py`** — assert `build_feature_row` produces a **byte-identical** dict when every row with `week >= w` is deleted from the input. **Write it before the features.** | Temporal leakage is what makes sports models look brilliant offline and worthless live. Pure, keyless, model-free — and the artifact a quant reviewer will respect most. |
| **PPX** | Deliberately exclude the market line, spread and total from every projection input. | A projection conditioned on the market cannot disagree with the market informatively. |
| **PPX** | **Conditional** coverage, not just marginal — stratify by `n_eff` tier, post-trade rows, post-changepoint rows. | Marginal coverage can pass while the model is badly miscalibrated on exactly the subpopulations this was built for. |
| **Role Ledger** | `vacated_share` as a fact requiring **zero post-event games**, plus an AST-walking purity test asserting no module in `projection/` imports `httpx`/`asyncpg`/`nfl_data_py`. | The vacated share is the only honest quantitative thing you can say the week after a trade. The purity test makes a layering claim testable instead of aspirational. |
| **Judge panel** | **Move calibration forward and make it keyless.** Calibrate the *projection* against realized nflverse yardage (PIT histogram, CRPS, coverage) — needs no prop lines and no key. | The original deferred all empirical evidence to a final phase requiring a paid feed. Distributional calibration is free and answers "how do you know it works?" |

---

## Data sources

| Source | Key? | Used for |
|---|---|---|
| **nflverse via `nfl_data_py`** — weekly player stats, rosters, snap counts, depth charts, injuries, schedules | **KEYLESS** | The entire spine. **Weekly rosters diffed week-over-week *is* the trade detector.** Already declared at `pyproject.toml:26`, imported nowhere. Verify function/column names against the pinned version — the API has drifted. |
| **nflfastR play-by-play** | **KEYLESS** | Neutral-script pass rate, plays/game, seconds/play → the scheme changepoint series. **There is no coordinator column anywhere in nflverse** — verified. |
| `data/reference/nfl_staff.csv` (hand-curated) | **KEYLESS** | The coordinator's *name*, for prose only. Rows lacking `source_url`/`verified_on` rejected at load. **Never read by arithmetic.** Head-coach rows cross-validated against nflfastR by a unit test. |
| **The Odds API** — prop lines | **KEY REQUIRED** | The line to price against. Player props are per-event requests and may sit outside the free tier. **Not on the critical path** — in replay the line comes from the fixture. |
| **CFBD** | KEY REQUIRED | **Nothing in v1.** No CFB equivalent of nflverse usage data exists. CFB props return `insufficient_data` by construction. |

---

## The math

Pure Python over floats. No fitting loop, no gradient, no seed, no artifact.

**Decomposition (an identity, not a fit):**
```
rec_yards  = team_pass_attempts × target_share   × yards_per_target
rush_yards = team_rush_attempts × carry_share    × yards_per_carry
pass_yards = team_pass_attempts × dropback_share × yards_per_attempt
```

**Segment and weights (the hard cut):**
```
segment S = weeks since the most recent regime cut for this player-factor
w_i = 2 ** (-games_back_i / half_life_games)   for i in S
w_i = 0                                        outside S
n_eff = (Σ w_i)² / Σ w_i²                      # Kish effective sample size
```

Which factors each cut invalidates is a **stated modeling assumption**, documented in the module
docstring:

| Cut | Volume | Share | Efficiency |
|---|---|---|---|
| `team_change` | cut (use new team's own log) | **cut** | not cut |
| `scheme_change` | cut | cut | not cut |
| `teammate_absence` | cut | cut | cut |

**Priors, refit at job time by method of moments:**
```
Beta (shares):     k_S = m(1-m)/v - 1 ;  α = m·k_S ; β = (1-m)·k_S
                   REFUSE if k_S <= 0
Normal (V and E):  k = σ²_within / σ²_between
```

**Posteriors, closed form.** Rescale weighted counts so the Beta's implied sample size equals
`n_eff` — do **not** mix Kish `n_eff` for the Normal path with raw `n_w` for the Beta path.

**Projection and dispersion:**
```
μ̂ = V̂ · Ŝ · Ê
1 + CV²_total = (1+CV²_game)(1+CV²_V)(1+CV²_S)(1+CV²_E)
```

**Line → probability:**
```
σ²    = ln(1 + CV²_total)
μ_log = ln μ̂ - σ²/2
z     = (ln L - μ_log) / sqrt(σ²)
P(over) = 1 - NormalDist().cdf(z)      # statistics, stdlib
```

**Refusals return `None`**, which the existing gate at `edge_math.py:58` converts to
`insufficient_data`: unparseable selection, uncovered `stat_key`, no projection row,
`n_eff < min_effective_games`, `CV_total > max_cv`, `|z| > max_line_z`, `k_S <= 0`, projection
staler than the freshest `InjuryRecord` for that team, or the player himself out/doubtful.

**Vacated share is reported, not redistributed, in v1.** It enters as evidence text and fires a
`teammate_absence` cut. It **does not shift `μ̂` upward** — proportional redistribution is
"a coefficient wearing a disguise."

---

## How it answers the three cases

### Case 1 — New team (Metcalf, Pickens, Smith-Njigba)

**Detected, never asserted:** a trade is `weekly_rosters[w].team != weekly_rosters[w-1].team`.
No news parsing, no LLM. Then the three factors part company:

- **V̂** is re-estimated entirely from the **new team's own game log** — needs zero player data.
- **Ŝ** is **hard-cut**. Target share is a property of a depth chart, not a player. Post-trade
  `n_eff` starts near 0 and Ŝ is dominated by the fitted positional prior with large variance.
- **Ê** is **not cut** — a stated assumption, and the design's weakest (see caveats).

**What moves:** `CV_total` rises → `|z|` shrinks → `P(over)` pulled toward 0.5 → EV falls under
the vig → `fair`, or below `min_effective_games` → `insufficient_data`. **The system never claims
the trade made Metcalf worse. It claims to know less.**

**Smith-Njigba is the cleanest thing this layer does.** He never changed teams — Metcalf and
Lockett left. `vacated_share(SEA, week, targets)` sums their prior-window share and reports it as
a fact needing zero post-event games, while the departures fire a `teammate_absence` cut widening
his own estimate.

### Case 2 — New offensive coordinator (Barkley, AJ Brown)

Changepoint-detect on neutral-script pass rate, plays per game, seconds per play. The
coordinator's *name* comes from the staff CSV and becomes a citable `scouting_note` touching no
arithmetic.

**What moves:** post-cut `n_eff` for V̂ and Ŝ collapses, both regress to priors, `CV_total`
widens, and lines derived from last season's usage return `fair`/`insufficient_data` instead of
confidently repeating a regime that no longer exists.

**This is the weakest of the three cases and the README must say so.** At week 1 of a new season
under a new OC there are *zero* post-cut games and the layer refuses — correct, and commercially
useless. With n=1 no model learns "this coordinator hurt these players."

### Case 3 — Injury cascade (Jones → Taylor; Chargers O-line)

**(a) Teammate absence** — detected from *zero offensive snaps*, a counted fact, not an inference
from a "questionable" tag. Fires a cut on Taylor's V̂, Ŝ **and** Ê. The Ê cut matters: a back can
hold his carry share and lose a yard per carry when defenses stop respecting the pass, and a naive
before/after would blame the wrong factor. Three simultaneous cuts compound through the CV
product — this is where `max_cv` fires most.

**(b) O-line degradation** — no lineman has targets or carries, so share redistribution is
meaningless. What free data supports is `unit_continuity`: the fraction of the prior window's OL
snaps played by men available this week. **This measures churn and availability, not quality of
play.** A fully healthy but bad line is invisible to it. The README must not imply otherwise.

---

## Phases

| # | Phase | Effort | Ships |
|---|---|---|---|
| **0** | **Land the amendment.** `docs/AMENDMENTS.md` exists only on `origin/m8-keyless-slice`. Carry it forward, write the amendment recording the props-coverage scope change. No code. | ~2 days | The repo's stated process actually followed — itself a portfolio signal. |
| **1** | **Make the prop refusal visible.** `game_for_team` + narrow single-player backfill; `semantic_vector` in prop routing; `prop_selection.py`; per-market dispatch in `_build_edge_analyses`; fixture prop `days_before=0`; E2E asserts `q_prop` produces a **non-empty** edge block with `insufficient_data`. | ~1.5 wk | **A real bug fix — see below.** |
| **2** | **`synthesis/numeric_guard.py`.** Ship it warning on the report *before* it gates regeneration, so a false positive can't silently collapse every report to the evidence-only fallback. | ~4 days | Converts "the LLM never produces a number" from docstring to CI-enforced invariant. **Stands alone even if you abandon everything else.** |
| **3** | **The pure estimator.** Full unit tier: hand-computed posteriors, Kish `n_eff`, hard-cut behavior, lognormal tail, `k_S <= 0` guard, the leakage test, the AST purity test. Nothing imports it yet. | ~2 wk | A standalone hand-verifiable statistics module. Zero risk to the pipeline. |
| **4** | **Keyless calibration.** Walk held-out weeks over real nflverse seasons; score the projection against realized yardage — PIT histogram, CRPS, coverage, **marginal and conditional**. Commit the report. | ~1.5 wk | **The answer to "how do you know it works?"** Needs no key. Moved before wiring on purpose: if it isn't calibrated you find out at week ~6, not week ~11. |
| **5** | **Storage and wiring.** Migration, fixture `player_weeks.jsonl`, `projection_job.py`, `projections.py`, `ProjectionConfig`, threading through graph/routes. | ~2 wk | The first real prop `model_probability` the system has produced. |
| **6** | **Regime cuts.** All cut kinds, unit continuity, vacated share, full refusal gates. Fixture gains three planted scenarios; tests assert each **widens the interval** rather than shifting the mean. | ~1.5 wk | The three cases, demoable end to end. |
| **7** | **Live NFL feed.** `nflverse.py` (**check `origin/m8-keyless-slice` first**), staff CSV with enforced provenance, historical backfill. CFB stays out. | ~1.5 wk | The repo's first live data path — and it is keyless. |

**~10 weeks part-time, realistically 8–12.** **Phases 0–4 are a coherent stopping point:** a bug
fixed, an invariant enforced, a hand-verifiable estimator, a real calibration report — nothing
half-wired in `main`.

---

## Bugs this design surfaced in the *current* codebase

These are not Stage 5 work. They are defects today.

1. **Player-prop queries silently produce an empty edge block.** A prop query resolves no
   `game_id`, so `fanout.py` attempts neither `live_odds` nor `live_injury`, so `report.py` finds
   no odds chunks, so `edge_analysis` is `[]` — and `run_replay_e2e.py` only asserts the *spread*
   query, so CI has never noticed. **Confirmed by observation** in the 2026-08-02 D1 run:
   `[q_prop] OK: 0 citations, 0 edge blocks`.
2. **Nothing constrains numbers in the generated prose.** `verify_citations` checks only that a
   claimed `chunk_id` exists. An LLM can state any figure it likes as long as it cites a real
   chunk. The project's central claim is currently unenforced.
3. **The fixture's prop odds row is stamped `days_before=1`** against a 60-minute replay TTL, so
   the freshness gate drops it before synthesis regardless of anything else.
4. **The fixture cannot express the phenomenon.** 16 stat records, all 6 player rows are QBs,
   10 have `player_id: null`, every value is a `_ytd` season aggregate. "Production changed after
   week N" is not currently representable.

---

## Honest caveats

**Read this as the load-bearing section.**

1. **It refuses exactly when the question is interesting.** Week 2 after a trade is when you want
   an answer and when `min_effective_games` trips. By week 8, when `n_eff` recovers, the market
   has repriced. **Confident when useless, silent when valuable.** Structural to a shrinkage
   estimator whose regime signal is sample count — there is no tuning fix.
2. **"Efficiency travels with the player" is the most dangerous unexamined assumption.**
   Yards-per-target depends on the quarterback, the scheme's route concepts, and the coverage a
   departed teammate used to draw. Unlike a fabricated coefficient it **hides inside a
   defensible-looking counted ratio**, which makes it worse. Put it in the docstring in those
   words.
3. **The CV independence product is false and knowingly so.** V, S and E are entangled by game
   script. The misspecification **overstates** variance — the conservative direction, pushing
   toward `fair`, never toward a fake edge. That is why it is acceptable. Do not call it exact.
4. **Lognormal is wrong in the tails.** A receiver who tweaks a hamstring in the first quarter
   produces 12 yards, which lognormal gives almost no mass. Deep alternate lines — where sharp
   money looks — will be mispriced. `max_line_z` is a bandage, not a fix.
5. **Props carry a materially larger hold than sides.** Comparing a raw model probability against
   a vigged implied probability biases toward `no_value`. Pre-existing in `edge_math.py`, but it
   bites harder here.
6. **The changepoint statistic has no calibrated null** — a max-z on ~17 autocorrelated weekly
   points is a documented screening threshold, not a p-value. Say so in the docstring.
7. **Vacated share is reported, not allocated.** Publishing "31% of targets are vacant" and
   declining to allocate does not stop the reader allocating it in their head. Real objection,
   no fully satisfying answer. Mitigation: the disclaimer is generated by Python, not the LLM,
   so it cannot be paraphrased away.
8. **CFB is out** — half the stated sport surface returns `insufficient_data` by construction.

### Checklist before any performance claim

Until every box is ticked, the honest claim is about **method and refusal behavior**, never
about performance.

- [ ] Phase 4 has run on real seasons; PIT histogram roughly flat and coverage within tolerance —
      **conditionally**, on post-trade and post-changepoint rows, not just marginally.
- [ ] The leakage test passes and was written **before** the features.
- [ ] `_build_edge_analyses` has a dedicated test proving a mixed chunk list (spread + moneyline +
      two props) attaches the right probability source to each block. **This is the single edit
      most likely to attach an Elo win probability to a receiving-yards line.**
- [ ] `verify_numeric_grounding` is gating, not warning, with zero false positives on canned queries.
- [ ] The staff CSV is provably read by no arithmetic path — enforced by the AST purity test, not
      by discipline.
- [ ] `max_cv` is calibrated from the Phase 4 backtest.
- [ ] No accuracy figure, no coefficient, and no use of the word "profitable" appears in the
      README, `DESIGN.md`, or a resume bullet until the box above it is ticked.

### The outcome to plan for

**The market almost certainly beats this.** Books run proprietary projections on better feeds with
faster injury news, at roughly double the hold of the spread market. The realistic result is that
nearly every prop returns `fair` or `insufficient_data`, and **the interesting output of this layer
is the refusals rather than the edges.**

That is defensible as a portfolio piece — it is the epistemics the project already advertises, and
a numeric guard plus a leakage test plus a real calibration report is a stronger interview artifact
than a poorly-calibrated yards model. But build it knowing that, and never let a green CI badge
imply otherwise.

---

## Note on one stale assumption

The synthesis recommends adding a `workflow_dispatch` CI job to author cassettes because
"Docker is not installed locally." **That is no longer true as of 2026-08-02** — Docker Desktop
is installed and the full stack runs locally, so `scripts/author_cassettes_v0.py` can be run
directly. The CI job remains a reasonable convenience, not a necessity.
