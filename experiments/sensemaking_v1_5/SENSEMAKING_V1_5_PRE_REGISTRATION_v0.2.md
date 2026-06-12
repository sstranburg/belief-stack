# Sensemaking v1.5 — Pre-registration (v0.2)

This document is a derivative of [SENSEMAKING_V1_5_PRE_REGISTRATION_v0.1.md](SENSEMAKING_V1_5_PRE_REGISTRATION_v0.1.md). v0.1 results stand as v0.1; v0.2 results are reported separately, with a head-to-head comparison. Locked 2026-05-30.

v0.2 scope is **narrow**: re-bucket REPRICING with direction-awareness, split EARLY out of Constructive into its own bucket, keep the same walk-forward protocol, and publish a v0.1 ↔ v0.2 head-to-head. No new horizons, no new universe, no new metrics, no new control definition.

---

## 0. Why this document exists

The v1.5 v0.1 measurement surfaced two specific fragilities of the locked bucket mapping:

1. **REPRICING was load-bearing on the headline.** §12.1 sensitivity showed that moving REPRICING from Ambiguous to Constructive flipped the 20D Constructive Δ vs baseline from +2.97% to −1.64%. Same data, opposite story.
2. **EARLY weakened the Constructive bucket.** Per §3 of the v0.1 report, EARLY at 20D averaged +0.68% — much closer to baseline than CONFIRMED (+5.25%) or DISAGREEMENT (+7.37%). Holding it in Constructive diluted the headline.

The v0.1 report's §8 named both as v0.2 candidates. This pre-registration locks the v0.2 response, with all other rules unchanged.

---

## 1. Success criterion

Unchanged from v0.1. Calibrated reporting, not pass/fail. The v0.2 measurement tests whether the direction-aware REPRICING split and the EARLY isolation produce more separable, more stable forward outcome distributions than v0.1, under rolling walk-forward evaluation. The report publishes per-bucket and per-horizon metrics and a v0.1 ↔ v0.2 head-to-head.

---

## 2. Universe

Unchanged from v0.1. Same window (2025-12-05 → 2026-05-26), same primary universe (31 tickers, per I-002), same exclusions (§7 unchanged), same `variant = "baseline"` choice (I-001).

---

## 3. State buckets (v0.2)

### 3.1 The 9 leaderboard states

Unchanged. The state labels emitted by `generate_leaderboard.py` are the same: `CONFIRMED`, `EARLY`, `REPRICING`, `DIVERGENCE`, `NEG_CONFIRMATION`, `DISAGREEMENT`, `MACRO`, `PRICE-LED`, `UNCLEAR`.

### 3.2 v0.2 bucket mapping (the change)

| Bucket | States (v0.2) | Notes |
|---|---|---|
| **Constructive** | CONFIRMED, DISAGREEMENT, REPRICING_bullish | EARLY removed (now its own bucket); REPRICING split by narrative direction added |
| **Cautious** | NEG_CONFIRMATION, DIVERGENCE, REPRICING_bearish | REPRICING split by narrative direction added |
| **Early_followthrough** | EARLY | New standalone bucket — reported separately, not folded into Constructive |
| **Ambiguous** | MACRO, PRICE-LED, UNCLEAR | REPRICING removed (now split into Constructive / Cautious by direction); EARLY moved out (own bucket) |

### 3.3 REPRICING direction split (the rule)

A row with state = `REPRICING` is classified by the `direction` field from `backtest_history.parquet`. **Important limitation:** that `direction` column is the *actor-level* narrative direction (e.g. MU = −1 because the dominant narrative on Micron is bearish; NVDA = +1 because the dominant narrative on NVIDIA is bullish). It is **not** a row-specific direction signal — every REPRICING row for a given ticker carries the same direction value. The v0.2 measurement uses this actor-level signal because it is the only pre-existing direction column on the substrate; a row-specific direction signal would require new inference and lands in v0.3 if needed.

- `direction = +1` (actor-level bullish narrative) → **REPRICING_bullish** → Constructive bucket. Interpretation: positive narrative + price catching up = constructive read.
- `direction = −1` (actor-level bearish narrative) → **REPRICING_bearish** → Cautious bucket. Interpretation: negative narrative + price catching down = cautious read.

This is a deliberate v0.2 commitment. If the v0.2 measurement shows REPRICING_bullish or REPRICING_bearish distributions do not align with their assigned bucket, that becomes a v0.3 candidate. v0.2 makes the call, locks it, and reports what happens.

### 3.4 EARLY isolation (the rule)

EARLY is no longer in any aggregate bucket. It is reported as a standalone fourth bucket (`Early_followthrough`) with the same per-bucket metrics as Constructive / Cautious / Ambiguous. The §6 Hit / FP / FN labeling for EARLY rows uses the **Constructive truth table** (fwd_rel > 0 = Hit, ≤ 0 = FP) on the rationale that EARLY's directional implication is "constructive but weaker." This labeling is provisional and can be revised in v0.3 if EARLY's measured distribution suggests a different mapping.

### 3.5 What does NOT change in §3

- The other state assignments (CONFIRMED, DISAGREEMENT, DIVERGENCE, NEG_CONFIRMATION, MACRO, PRICE-LED, UNCLEAR) keep their v0.1 bucket assignments.
- Actor-direction agnosticism for all states OTHER than REPRICING is preserved per v0.1 §3.3.
- The conservative-zero-bucket-edge-case rule from v0.1 §6 is preserved (0.0 = "underperformed" for Constructive / Early_followthrough; "outperformed" for Cautious).

---

## 4. Forward outcome definition

Unchanged from v0.1. Actor minus QQQ relative returns at 5 and 20 trading days; trading days inferred from QQQ index.

---

## 5. Validation protocol

Unchanged from v0.1. Same rolling walk-forward inside-window. Same no-re-fitting discipline. The state assignments are read from `backtest_history.parquet` as-is; v0.2 only changes how those state assignments are *bucketed*, not how they are *computed*.

---

## 6. Hit / FP / FN / Excluded definitions

Unchanged in form. Applied to the new bucket set:

| Bucket | Forward relative return | Label |
|---|---|---|
| Constructive | > 0 | **Hit** |
| Constructive | ≤ 0 | **False positive** |
| Cautious | < 0 | **Hit** |
| Cautious | ≥ 0 | **False negative** |
| Early_followthrough | > 0 | **Hit** (provisional, per §3.4) |
| Early_followthrough | ≤ 0 | **False positive** (provisional, per §3.4) |
| Ambiguous | — | Not labeled |

---

## 7. Excluded rows

Unchanged from v0.1.

---

## 8. Control / baseline

Primary baseline = Ambiguous bucket forward returns, as in v0.1 §8.1. **Note on baseline composition:** because REPRICING moves out of Ambiguous, the v0.2 Ambiguous baseline is much smaller (~211 rows at 5D vs ~1,394 at 5D in v0.1). This is expected and noted in the report. A smaller, more directionally-pure baseline is the intent; the head-to-head report will display both baselines explicitly so the reader can see the change.

Secondary baseline (random actor-days with seed `20260601`) optional and unchanged in definition.

---

## 9. Report metrics

Unchanged from v0.1 §9, with one addition:

- **Head-to-head section.** For each (bucket × horizon) cell that exists in both v0.1 and v0.2, report n, avg fwd_rel, % positive, Δ vs respective baseline. Delta attribution: which v0.2 amendment moved the number, and by how much.

The §9.1 "metrics deliberately not reported" list is unchanged: no Sharpe, no p-values, no alpha framing.

---

## 10. What v0.2 does NOT claim

Unchanged in spirit from v0.1 §10. Additionally:

- v0.2 does NOT claim the direction-aware REPRICING split is the *correct* mapping. It claims the split is *a* mapping that the v0.1 sensitivity surfaced as worth committing to, and v0.2 measures what that mapping does.
- v0.2 does NOT claim Early_followthrough's truth-table assignment (per §3.4) is correct. It is provisional.

---

## 11. Secondary analyses

§11.1 (lifecycle revision-prediction) and §11.2 (warrant coverage) are unchanged in protocol. The lifecycle event buckets (`Constructive_revision`, `Cautious_revision`) keep their v0.1 definitions because they are typed by event_type, not by state. Warrant coverage partitioning is by `sufficient_data ∈ {True, False}`, also unchanged.

The secondary analyses re-run against the v0.2 bucket set for the purpose of consistency in the report, but their lifecycle and coverage buckets are not affected by §3 changes.

---

## 12. Sensitivity appendix (v0.2)

The sensitivity appendix is **restructured** for v0.2. The v0.1 §12.1 (REPRICING-as-Constructive) is no longer a sensitivity because v0.2 commits to a direction-aware split; testing the naive collapse would be re-running the v0.1 mistake. The v0.2 appendix contains:

### 12.1 Direction-naive REPRICING reverse sensitivity (new)

Re-run the v0.2 measurement with REPRICING collapsed back into a single Ambiguous bucket (the v0.1 mapping). Reports how much of any v0.2 delta vs v0.1 is attributable to the REPRICING split. This is the inverse of v0.1 §12.1 and the cleanest test of whether the direction-aware split is doing real work.

### 12.2 EARLY-as-Constructive reverse sensitivity (new)

Re-run the v0.2 measurement with EARLY folded back into Constructive (the v0.1 mapping). Reports how much of any v0.2 delta is attributable to the EARLY isolation.

### 12.3 Experimental-tickers-included (preserved from v0.1 §12.2)

Same as v0.1 §12.2. Include USAR / MP / ODC in the primary universe.

### 12.4 Sensitivity is not the primary claim (preserved from v0.1 §12.3)

Same constraint as v0.1: the sensitivity appendix is reported separately, never inline with primary numbers.

### 12.5 What sensitivity is not (preserved from v0.1 §12.4)

Same constraint as v0.1.

---

## 13. Versioning policy

- This is **v0.2** of the v1.5 pre-registration. The immediate predecessor is v0.1, locked 2026-05-29.
- v0.1 measurement results stay valid as v0.1. v0.2 results are reported separately and compared head-to-head.
- Any change to v0.2 rules after lock requires v0.3.
- Ambiguities encountered during v0.2 implementation are appended to `SENSEMAKING_V1_5_ISSUES_LOG.md` (continuing from I-001, I-002) and resolved at v0.3.

---

## 14. What v0.2 implementation will produce

```
sensemaking_v1_5/
  sensemaking_v1_5_harness.py            (unchanged from v0.1 — rows.parquet reused)
  sensemaking_v1_5_label_v0_2.py         v0.2 bucket + label logic
  sensemaking_v1_5_secondary_v0_2.py     v0.2 secondary (unchanged protocol, re-run)
  sensemaking_v1_5_sensitivity_v0_2.py   §12 v0.2 sensitivity (restructured)
  sensemaking_v1_5_report_v0_2.py        v0.2 report + v0.1 ↔ v0.2 head-to-head
  data/
    sensemaking_v1_5_labeled_v0_2.parquet
    sensemaking_v1_5_primary_summary_v0_2.json
    sensemaking_v1_5_secondary_summary_v0_2.json
    sensemaking_v1_5_sensitivity_summary_v0_2.json
    sensemaking_v1_5_report_v0_2.json
  SENSEMAKING_V1_5_REPORT_v0_2.md
```

`sensemaking_v1_5_rows.parquet` and `data/sensemaking_v1_5_labeled.parquet` (v0.1) are NOT touched. Likewise the v0.1 summary JSONs and report markdown are preserved as the v0.1 record.

---

## 15. Audit trail

| Field | Value |
|---|---|
| Author | Susan Stranburg |
| Locked | 2026-05-30 |
| Predecessor | [SENSEMAKING_V1_5_PRE_REGISTRATION_v0.1.md](SENSEMAKING_V1_5_PRE_REGISTRATION_v0.1.md), locked 2026-05-29 |
| Hash of v0.1 artifacts at lock time | (computed at v0.2 first run; v0.1 artifacts remain immutable) |
| Rules version | v0.2 |

---

## 16. What v0.1 vs v0.2 says publicly

v0.1 said: under locked rules, the Constructive bucket separates from baseline at 20D by +2.97%, but a sensitivity appendix showed the headline depended on REPRICING's bucket.

v0.2 will say: under a direction-aware REPRICING split and an EARLY-isolated bucket, here is whether the same data produces a more stable headline. If yes, the v1 field's predictive content holds up under a tighter mapping. If no, the next iteration's scope shrinks to a more local question.

The public-facing framing of the case study after v0.2 should be:

> v1.5 v0.1 found that the headline depended on a bucket assignment. v1.5 v0.2 tests a narrower, direction-aware mapping and reports both side by side.

That is honest correction. It does not erase the v0.1 fragility; it shows the system surfacing the weak point and tightening the representation.
