# Sensemaking v1.5 — Pre-registration (v0.1)

This document specifies the v1.5 measurement of the TopicSpace sensemaking belief field, derived from and complementary to the v1 descriptive case study at [topicspace.ai/research/case-studies/sensemaking-v1](https://topicspace.ai/research/case-studies/sensemaking-v1). v1 demonstrated that the field exists. v1.5 asks whether the field's labels have behavioral consequences over forward outcomes.

Locked 2026-05-29. v1.5 measurement runs against this document as written; any change in rule semantics requires a v0.2 pre-registration.

---

## 0. Why this document exists

v1 was a descriptive and behavioral audit: are beliefs born, refreshed, contradicted, retired; is warrant tracked; does the field move? It deliberately deferred forward-calibration claims to v1.5 because they require pre-registered evaluation criteria locked before data is examined, plus an explicit control set.

v1.5 is that pre-registration. It locks the questions, the universe, the protocol, and the metrics before any forward returns are computed. The intent mirrors the F-023 Phase 2 discipline: lock the rules first, run once, report what happens — with explicit accounting for false positives.

---

## 1. Success criterion

The v1.5 analysis tests whether v1's market state assignments produce **separable forward outcome distributions** at 5-day and 20-day horizons under rolling walk-forward evaluation, compared against a non-flagged baseline drawn from the same corpus.

The report publishes sample size, hit rate, average forward relative return, median forward relative return, percent positive relative return, and baseline difference for each state bucket. No threshold is defined as "success" before measurement; the purpose is **calibrated evidence**, not a pass/fail demo.

### 1.1 What success looks like (as a measurement, not a claim)

- The constructive buckets (CONFIRMED, EARLY, DISAGREEMENT) produce forward 5D/20D relative returns whose distribution is **observably different** from the non-flagged baseline.
- The cautious buckets (NEG_CONFIRMATION, DIVERGENCE) produce forward 5D/20D relative returns whose distribution is **observably different** in the opposite direction.
- The ambiguous buckets (MACRO, PRICE-LED, UNCLEAR, REPRICING) produce distributions **indistinguishable** from baseline, validating that they are correctly marked as non-actionable.

"Observably different" is a descriptive claim — we report the numbers, we do not pre-commit to a statistical test or significance threshold. v1.5 is calibrated reporting, not hypothesis rejection.

---

## 2. Universe

### 2.1 Time window

**2025-12-05 → 2026-05-26** (173 calendar days, ~120 trading days). Matches the v1 case study window exactly. No extension.

### 2.2 Tickers

The 42 actors tracked in v1's `actors.json` snapshot.

**Excluded from primary universe:** the three experimental tickers (USAR, MP, ODC) listed in `EXPERIMENTAL_TICKERS` in `scripts/generate_leaderboard.py`. These were added late, have less data, and were marked "under observation" in v1. v1.5 measures them as a separate secondary cohort, not as part of the primary state-prediction test.

### 2.3 Evaluation points

One row per (trading day T, ticker) where:

- T ∈ trading days in the window
- ticker ∈ primary universe
- a state assignment exists in `data/derived/backtest_history.parquet` as of T
- forward 5D and 20D price data is available in `data/derived/prices/*.parquet`
- T + 5 trading days ≤ window end (for 5D measurement)
- T + 20 trading days ≤ window end (for 20D measurement)

Rows missing 5D lookahead but having 20D lookahead are excluded from the 5D test, included in the 20D test, and vice versa.

---

## 3. State buckets

### 3.1 The 9 leaderboard states

The state labels emitted by `scripts/generate_leaderboard.py` and persisted into `backtest_history.parquet`:

`CONFIRMED`, `EARLY`, `REPRICING`, `DIVERGENCE`, `NEG_CONFIRMATION`, `DISAGREEMENT`, `MACRO`, `PRICE-LED`, `UNCLEAR`.

### 3.2 Pre-registered bucket mapping

| Bucket | States | Implied directional read |
|---|---|---|
| **Constructive** | CONFIRMED, EARLY, DISAGREEMENT | Expect forward outperformance vs benchmark |
| **Cautious** | NEG_CONFIRMATION, DIVERGENCE | Expect forward underperformance vs benchmark |
| **Ambiguous** | MACRO, PRICE-LED, UNCLEAR, REPRICING | No directional read; expect distributions indistinguishable from baseline |

#### 3.2.1 Note on REPRICING

REPRICING ("price lagging narrative") has historically been treated editorially as a constructive bucket: positive narrative + price catching up. The v0.1 pre-registration **deliberately classifies REPRICING as ambiguous** because the v1 case study's lifecycle data shows REPRICING being used for both bullish-narrative catch-up and bearish-narrative drift. If the v1.5 measurement shows REPRICING distributions separating from baseline in one direction, that is itself a v1.5 finding; if v0.2 amends the mapping, it goes through the same lock discipline as v1.

#### 3.2.2 Note on DISAGREEMENT

DISAGREEMENT ("price rejecting negative narrative") is constructive regardless of narrative direction: the bearish story is breaking, the price is moving up despite it. Included in Constructive.

### 3.3 Tickers with negative narrative direction

Per `ACTOR_DIRECTIONS` in `generate_leaderboard.py`: MU, TSLA, SOFI, SNOW, CRWV, CRM, INTC, TSM have narrative direction = −1. For these:

- The bucket mapping in §3.2 still applies (the state labels already encode the price-vs-narrative geometry).
- Forward relative returns are computed in the same direction (actor − benchmark) regardless of narrative direction. The state's directional implication is not flipped.

The pre-registration's bucket mapping is therefore actor-direction-agnostic. If results suggest direction-aware bucketing is needed, that is a v0.2 candidate.

---

## 4. Forward outcome definition

### 4.1 Forward return

For each evaluation row (T, ticker):

```
fwd_return(T, ticker, N) = (close_T+N − close_T) / close_T
```

where `close_T+N` is the closing price on the Nth trading day after T. `close_T` is the closing price on T.

### 4.2 Forward relative return

```
fwd_rel(T, ticker, N) = fwd_return(T, ticker, N) − fwd_return(T, QQQ, N)
```

QQQ is the benchmark (matches `BENCHMARK` constant in `generate_leaderboard.py`).

### 4.3 Horizons

Two horizons measured for every evaluation row: **N = 5 trading days** and **N = 20 trading days**. Both reported separately, not aggregated.

---

## 5. Validation protocol

### 5.1 Rolling walk-forward inside-window

For each trading day T in the window:

1. The state assignment used for the row is the state recorded at T in `backtest_history.parquet` — i.e., the state computed by `generate_leaderboard.py` using data ≤ T. No re-computation. No look-ahead.
2. Forward returns are computed from prices at T, T+5, and T+20 (all in the substrate, but never used in computing the state at T).
3. The row contributes one observation to its bucket's 5D distribution and one to its 20D distribution.

This produces ~120 evaluation rows per actor (minus end-of-window exclusions for missing lookahead), aggregated across ~39 primary-universe actors → roughly 3,500–4,500 5D observations and 2,500–3,500 20D observations in the primary measurement, depending on missing data.

### 5.2 No re-fitting

State assignments are immutable artifacts of the v1 pipeline as it ran day-by-day. v1.5 does not re-fit, re-score, or adjust any v1 output. It reads `backtest_history.parquet` and prices as-is.

### 5.3 What "as of T" means

The state at T in `backtest_history.parquet` was computed at end-of-day T using all evidence available at that time. The forward 5D return is scored using close prices T+1 through T+5. There is no overlap between the inputs to the state and the inputs to the outcome. This is enforced by the parquet's date column.

---

## 6. Hit / FP / FN / Ambiguous definitions

Mirrors the F-023 Phase 2 §5 truth-table discipline. Per horizon (5D, 20D), each row gets a label:

| Bucket | Forward relative return | Label |
|---|---|---|
| Constructive | > 0 | **Hit** |
| Constructive | ≤ 0 | **False positive** (constructive call underperformed) |
| Cautious | < 0 | **Hit** |
| Cautious | ≥ 0 | **False negative** (cautious call outperformed) |
| Ambiguous | — | Not labeled (no directional prediction made) |

Rows lacking full lookahead are tagged **Excluded** and reported as a separate count. They do not enter hit-rate or FP/FN calculations.

The exact-zero edge case is rare for relative returns but is bucketed conservatively: 0.0 counts as "underperformed" for constructive (FP) and "outperformed" for cautious (FN). This is the more conservative reading.

---

## 7. Excluded rows

Rows are excluded from the primary measurement (per horizon) if any of:

1. State is missing or `UNCLASSIFIED`.
2. Price data is missing for T, T+5, or T+20.
3. T+N falls outside the window (window-end exclusion).
4. Ticker is in `EXPERIMENTAL_TICKERS`.

Each exclusion type is counted and reported in §9's exclusion table.

---

## 8. Control / baseline

### 8.1 Primary baseline: ambiguous-bucket forward returns

The primary baseline is the union of all rows in the Ambiguous bucket (MACRO, PRICE-LED, UNCLEAR, REPRICING). The forward 5D and 20D relative return distributions of this baseline are the comparison reference for the constructive and cautious buckets.

Rationale: ambiguous-bucket actor-days are observations where the v1 system explicitly declined to make a directional read. They are the natural "no signal" comparator drawn from the same corpus, same window, same actors.

### 8.2 Secondary baseline (optional): random actor-days

If cheap to compute, a secondary baseline samples N random (date, ticker) pairs from the primary universe across all states — including the constructive and cautious buckets — using a locked seed. This baseline tests whether the constructive/cautious distributions differ from a random pick from the same population.

Seed: **20260601** (placeholder, locked at audit-trail time).

### 8.3 What is NOT a baseline

- The market (QQQ) is the *benchmark* for relative-return computation; it is not the baseline for state-bucket comparison.
- Hold-out tail or train/test split is explicitly NOT used. v1.5 is rolling walk-forward inside-window.

---

## 9. Report metrics

For each (bucket × horizon) cell, the report publishes:

| Metric | Definition |
|---|---|
| Sample size (n) | Number of evaluation rows in the bucket+horizon after exclusions |
| Hit rate | (Hits) / (Hits + False positives or False negatives) |
| Average forward relative return | Mean of `fwd_rel` |
| Median forward relative return | Median of `fwd_rel` |
| Percent positive relative return | (rows with fwd_rel > 0) / n |
| Baseline difference | (bucket metric) − (ambiguous-baseline metric) |
| Excluded count | Rows in the bucket excluded for any reason in §7 |

The report also publishes:

- **Exclusion table**: for each exclusion type in §7, count.
- **State-bucket table**: per state (not just bucket) sample size, average forward relative return, median, % positive. Lets readers see whether one state dominates a bucket.
- **Resolution rates**: % of rows that transitioned to a different state by T+5 and T+20. This is secondary descriptive context.

### 9.1 Metrics deliberately not reported

- Sharpe ratio. Avoids inviting finance-performance framing. v1.5 is about label separation, not strategy returns.
- p-values, t-tests, statistical significance claims. v1.5 reports the numbers; it does not perform null-hypothesis testing on this sample.
- Annualized returns, drawdowns, alpha vs the market. These belong to a downstream backtest analysis, not to v1.5.

---

## 10. What v1.5 does NOT claim

Mirrors v1 §6.1 in spirit and the F-023 Phase 2 §6.1 in form:

- v1.5 does NOT claim alpha against the market.
- v1.5 does NOT claim that v1 state assignments are predictive in a live-deployment sense.
- v1.5 does NOT claim generalization beyond the AI ecosystem corpus, beyond 173 days, or beyond this user's pipeline configuration.
- v1.5 does NOT claim that the current state-to-bucket mapping (§3.2) is optimal. It is a v0.1 mapping subject to v0.2 revision.
- v1.5 does NOT make a pass/fail call. The result is the result; framing is left to the reader.

What v1.5 *does* claim is narrower: under locked rules, the v1 state labels (do / do not) separate forward outcome distributions from a non-flagged baseline drawn from the same corpus.

---

## 11. Secondary analyses (same harness, separate reports)

### 11.1 Lifecycle revision-prediction (secondary)

Question: do actors whose expectations were reconfirmed or strengthened in window W show different forward outcomes than those whose expectations were contradicted or weakened in W?

Universe: rows from `data/derived/expectation_lifecycle_events.parquet` within the v1.5 window. Bucket by lifecycle event type. Horizon: forward 5D and 20D relative return computed from the event date.

Reported as a separate section in the v1.5 report. Bucket cuts and exclusion rules are reused from §3 / §7 where applicable.

### 11.2 Warrant coverage / sufficient-data reliability (tertiary)

Question: do (date, ticker) rows flagged as "sufficient data" by v1's warrant coverage produce more reliable forward predictions than rows flagged "insufficient"?

Universe: all primary-universe rows, partitioned by `sufficient_data: True/False` field. For each partition, compute the same §9 metrics. The expectation under v1's coverage discipline is that insufficient-data rows produce distributions indistinguishable from baseline (because the system correctly declined to make a confident claim).

Reported as a tertiary section. If insufficient-data rows ALSO show signal separation, that is itself a finding (either the coverage threshold is over-conservative or warrant tracking is informative but not gating).

---

## 12. Sensitivity appendix

The sensitivity appendix re-runs the §6 hit/FP/FN measurement under two perturbations of the primary specification. Results are reported as a clearly-marked appendix to the v1.5 report, **never as part of the primary claim**. The purpose is to show how stable the headline numbers are to two specific bucket/universe choices the v0.1 pre-registration committed to.

### 12.1 REPRICING-as-Constructive sensitivity

Re-run the §6 measurement with REPRICING moved from Ambiguous to Constructive. All other §3 mappings unchanged. Report:

- Constructive bucket sample size, hit rate, average + median forward relative return, % positive, baseline difference (5D and 20D).
- Delta versus the primary §9 Constructive metrics, attributed to the REPRICING reclassification.
- Standalone REPRICING-only table (already reported in §9 state-bucket table) repeated here for direct inspection.

If the delta is small, REPRICING's bucket assignment is not load-bearing for the primary claim. If the delta is large, that is a v0.2 candidate flagged for explicit re-decision.

### 12.2 Experimental-tickers-included sensitivity

Re-run the §6 measurement with USAR, MP, ODC included in the primary universe (in addition to their secondary-cohort reporting). All other §2.2 and §3 mappings unchanged. Report:

- Per-bucket sample size, hit rate, metrics, baseline difference (5D and 20D) — for the augmented universe.
- Delta versus the primary §9 metrics, attributed to the inclusion of experimental tickers.
- Standalone USAR / MP / ODC per-ticker row showing each experimental ticker's contribution to the delta.

If experimental-ticker inclusion shifts the primary numbers materially, that is calibration evidence that the experimental-tickers exclusion in §2.2 was load-bearing. If it does not, the exclusion is methodologically conservative without changing the conclusions.

### 12.3 Sensitivity is not the primary claim

The sensitivity appendix's headline numbers are **not** reported alongside the primary numbers in the case-study update text. They appear only in the v1.5 report's appendix section, with a one-paragraph framing reminder that they exist to show robustness of the primary specification, not to compete with it.

### 12.4 What sensitivity is not

- Sensitivity does NOT include re-running with different bucket mappings beyond §12.1 and §12.2. Any other bucket experimentation is a v0.2 candidate, not a sensitivity check.
- Sensitivity does NOT include any p-value or significance testing. Same constraint as §9.1.
- Sensitivity does NOT alter the v1.5 success criterion (§1). The primary measurement stands; sensitivity reports the robustness of that measurement to two specific choices.

---

## 13. Versioning policy

- This is **v0.1** of the v1.5 pre-registration.
- Any change to bucket mapping, universe, walk-forward protocol, or metric definitions after lock is a **major rule change** and requires `SENSEMAKING_V1_5_PRE_REGISTRATION_v0.2.md`. The v0.1 measurement results stay valid as v0.1; v0.2 results are reported separately and compared head-to-head.
- Bug fixes to harness code that do not change rule semantics may be recorded in a changelog without a version bump.
- Ambiguities encountered during implementation go to `SENSEMAKING_V1_5_ISSUES_LOG.md` and are resolved at v0.2.

---

## 14. What v1.5 implementation will produce

```
sensemaking_v1_5/
  sensemaking_v1_5_harness.py     replays state labels against price data; emits one row per (T, ticker, horizon)
  sensemaking_v1_5_label.py       buckets rows; computes hit/FP/FN per §6
  sensemaking_v1_5_secondary.py   lifecycle revision + warrant coverage secondary analyses
  sensemaking_v1_5_sensitivity.py REPRICING-as-Constructive + experimental-included sensitivity (§12)
  sensemaking_v1_5_report.py      head-to-head v1 (descriptive) vs v1.5 (predictive), plus appendix
  data/
    sensemaking_v1_5_rows.parquet            primary evaluation rows
    sensemaking_v1_5_lifecycle_rows.parquet  secondary
    sensemaking_v1_5_coverage_rows.parquet   tertiary
    sensemaking_v1_5_sensitivity.json        §12 sensitivity outputs
    sensemaking_v1_5_report.json
  SENSEMAKING_V1_5_REPORT.md
  SENSEMAKING_V1_5_ISSUES_LOG.md
```

Inputs read (NOT modified): `data/derived/backtest_history.parquet`, `data/derived/expectation_lifecycle_events.parquet`, `data/derived/prices/*.parquet`, `topicspace-site/public/actors.json`.

The implementation must reference this pre-registration document by version. Ambiguities encountered are logged in the issues file and resolved at v0.2, not silently in code.

---

## 15. Audit trail

| Field | Value |
|---|---|
| Author | Susan Stranburg |
| Locked | 2026-05-29 |
| Companion case study (v1) | [topicspace.ai/research/case-studies/sensemaking-v1](https://topicspace.ai/research/case-studies/sensemaking-v1) |
| Sibling protocol reference | [tkos_log_replay/PHASE2_PRE_REGISTRATION_v0.1.md](../tkos_log_replay/PHASE2_PRE_REGISTRATION_v0.1.md) |
| Hash of v1 artifacts at lock time | (computed at first v1.5 run) |
| Rules version | v0.1 |
| Spec reference | https://topicspace.ai/research/belief-stack v0.1 |

---

## 16. What v1 vs v1.5 says publicly

v1 said: the field exists, it moves, it tracks warrant, it distinguishes evidence volume from regime change.

v1.5 will say: under locked rules, here is whether the field's labels (do / do not) separate forward outcomes from a non-flagged baseline. The answer is a number, not a claim.

If the constructive buckets show meaningful separation: that is calibrated evidence the labels carry behavioral information.

If they do not: that is calibrated evidence the labels are descriptive but not predictive, and the case study text needs to say so.

Either result is a v1.5 result. The discipline is what makes either one publishable.
