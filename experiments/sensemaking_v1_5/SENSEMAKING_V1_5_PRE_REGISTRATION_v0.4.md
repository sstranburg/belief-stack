# Sensemaking v1.5 — Pre-registration (v0.4)

Derivative of [SENSEMAKING_V1_5_PRE_REGISTRATION_v0.3.md](SENSEMAKING_V1_5_PRE_REGISTRATION_v0.3.md). v0.1, v0.2, v0.3 results remain unchanged; v0.4 is reported separately with a four-way head-to-head. Locked 2026-05-30.

**v0.4 scope** — narrow but architecturally substantive:

1. **Promote per-regime state-bucket measurement to primary.** v0.3 showed window-context dominates the headline. v0.4 makes regime-conditioned state buckets the primary axis; unconditioned aggregate stays as a comparison surface.
2. **Add a real regime detector.** v0.3 used the calendar midpoint as a crude cut. v0.4 introduces a realized-volatility regime detector computed from QQQ daily returns and locks it head-to-head against the calendar cut.
3. **Keep v0.3's bucket structure unchanged.** REPRICING_primary remains standalone and unlabeled; EARLY remains its own bucket; lifecycle revision stays as a secondary axis (also stratified by regime).

Same window, same horizons, same lookahead, same labeling protocol, same exclusions.

---

## 0. Why this document exists

v0.3 surfaced two findings the v0.4 pre-registration locks against:

- **State buckets are field-context dependent.** Aggregate numbers blend regimes; per-regime numbers are sharper. Sub-window A showed +7.43% Ambiguous baseline (rising tide); Sub-window B showed −2.43% (sell-off). Constructive at 20D went from −6.43% Δ window-baseline in Sub-window A to **+14.16% Δ window-baseline in Sub-window B** — the largest constructive signal observed anywhere in v1.5.
- **The calendar midpoint cut was crude.** It worked — it confirmed the rising-tide hypothesis — but it's not a real regime detector. A reproducible volatility-based detector is the v0.4 commitment.

The v0.3 report's §9 named both as v0.4 candidates. This pre-registration locks the v0.4 response.

---

## 1. Success criterion

The v0.4 measurement tests whether **state-bucket forward outcome distributions become more separable when conditioned on regime** than when measured in aggregate. The report publishes:

- Per-regime per-bucket metrics for both regime detectors (calendar midpoint and realized volatility).
- Cross-regime aggregate (matches v0.3 secondary state-bucket measurement) as a comparison surface.
- Head-to-head: do the two regime detectors agree about which regimes are constructive-favorable vs cautious-favorable?
- Lifecycle revision events stratified by both regimes as a secondary axis.

Per v0.1 §1.1 (preserved through all iterations): calibrated reporting, not pass/fail.

---

## 2. Universe

Unchanged from v0.1 / v0.2 / v0.3. Same window (2025-12-05 → 2026-05-26), same primary universe (31 tickers, baseline variant, experimentals excluded per I-001 / I-002), same `sensemaking_v1_5_rows.parquet` reused.

---

## 3. Regime definitions

v0.4 commits to **two regime detectors**, both reported as primary measurement axes side by side.

### 3.1 Regime detector A — calendar midpoint (preserved from v0.3 §11.2)

For each evaluation row (T, ticker):

- `calendar_regime = "A_early"` if `T < 2026-03-01`
- `calendar_regime = "B_later"` if `T >= 2026-03-01`

Cut date 2026-03-01 (calendar midpoint of the 173-day window). Identical to v0.3 §11.2. Reported in v0.4 as the simpler baseline regime detector.

### 3.2 Regime detector B — realized volatility (NEW, v0.4 primary)

For each trading day T:

1. **Daily QQQ return** from `data/derived/prices/QQQ.parquet`: `r_t = (close_t - close_{t-1}) / close_{t-1}`.
2. **20-day rolling realized volatility ending at T**: `rv_t = std(r_{t-19..t})`, computed only when 20 trailing daily returns are available. Rows with insufficient lookback (first 19 trading days of the price series) are tagged `vol_regime = "UNDEFINED"` and excluded from regime-conditioned primary; they remain in the unconditioned aggregate comparison.
3. **Threshold = window-median `rv`** across all defined trading days in the window. Computed once at first run.
4. **Regime assignment per T:**
   - `vol_regime = "LOW_VOL"` if `rv_t < median(rv)`
   - `vol_regime = "HIGH_VOL"` if `rv_t >= median(rv)`

#### 3.2.1 Why realized volatility, why 20-day, why median

- **Realized volatility** is the most universal regime measure across markets. It is direction-agnostic (a rallying market can be calm or turbulent; same for a falling market), so it cleanly separates regime from sign-of-return.
- **20-day window** matches the longer of the v1.5 forward-return horizons (`fwd_rel_20d`). This deliberately ties the regime window to the measurement window — a regime computed over the same horizon the bucket is being scored against.
- **Median threshold** keeps the two regimes equal-sized. No arbitrary cutpoint. The percentile is data-driven and reproducible.

#### 3.2.2 Limitation noted in pre-reg

The volatility regime detector is **backward-looking** — it uses trailing 20 days of QQQ returns to classify T. This is intentional for walk-forward discipline (no look-ahead) but means classifications at the start of any volatility shift lag the shift itself. v0.5 could test a forward-looking or event-aware regime detector if needed.

### 3.3 Cross-detector reporting

Both regimes are joined onto every evaluation row:

| Row | calendar_regime | vol_regime |
|---|---|---|
| (T₁, NVDA) | A_early | LOW_VOL |
| (T₂, NVDA) | B_later | HIGH_VOL |
| ... | ... | ... |

State-bucket primary measurement reports per (state_bucket × regime) for both detectors. The cross-tab calendar × vol is reported in the appendix to show whether the two detectors agree.

---

## 4. State buckets (unchanged from v0.3 §11.1)

Restated for completeness:

| Bucket | States |
|---|---|
| Constructive | CONFIRMED, DISAGREEMENT |
| Cautious | NEG_CONFIRMATION, DIVERGENCE |
| REPRICING_primary | REPRICING (unlabeled — descriptive only) |
| Early_followthrough | EARLY (Constructive-style labeling, provisional) |
| Ambiguous | MACRO, PRICE-LED, UNCLEAR |

No bucket changes in v0.4. The scope is regime-conditioning, not re-bucketing.

---

## 5. Forward outcome definition

Unchanged from v0.1.

---

## 6. Validation protocol

Unchanged in spirit. Walk-forward inside-window. State assignments read from `backtest_history.parquet` (baseline variant) as-is. Forward returns from per-ticker prices at T+5 and T+20. v0.4 adds:

- Each evaluation row is tagged with both `calendar_regime` and `vol_regime` (per §3) at T using only data ≤ T.
- The volatility detector's threshold (window-median rv) is computed once over the full window before regime assignment. This is **technically a look-ahead** because the threshold uses the full window's vol distribution. Documented as a v0.4 limitation; v0.5 candidate is to use rolling-threshold or expanding-window-threshold to remove the look-ahead entirely.

---

## 7. Hit / FP / FN / Excluded definitions

Unchanged from v0.3 §6. Applied per (bucket × regime) cell.

---

## 8. Excluded rows

Unchanged from v0.1 / v0.2 / v0.3 §7. v0.4 adds:

- Rows where `vol_regime = "UNDEFINED"` (first 19 trading days of the QQQ price series) are excluded from regime-conditioned primary measurement but retained in the unconditioned aggregate comparison.

The exclusion count for "vol_regime UNDEFINED" is reported alongside other exclusion counts in §10.

---

## 9. Baseline

Per-regime Ambiguous baseline:

- For each (regime_detector × regime_label) cell, the baseline is the Ambiguous bucket within that regime.
- Constructive Δ vs baseline within Sub-window A uses Sub-window A's Ambiguous; same for Sub-window B and for HIGH_VOL / LOW_VOL.

The cross-regime aggregate baseline (matches v0.3 §8) is reported separately as the comparison surface.

---

## 10. Report metrics

Per (bucket × regime × horizon), report v0.3 §9 metrics: n, avg fwd_rel, median, % positive, baseline diff (per-regime), hit rate where labeled.

Add:

- **Regime-detector head-to-head section.** For each (bucket × horizon), a side-by-side table: calendar A_early vs B_later vs vol LOW_VOL vs HIGH_VOL. Reveals whether the two detectors agree about which regime is constructive-favorable.
- **Cross-tab agreement table.** How many rows are in each of the four (calendar, vol) cells: (A_early, LOW_VOL), (A_early, HIGH_VOL), (B_later, LOW_VOL), (B_later, HIGH_VOL). Tests whether the two detectors are picking up the same underlying regime.
- **v0.1 / v0.2 / v0.3 / v0.4 head-to-head** for the unconditioned aggregate Constructive bucket at 20D (the most-tracked headline number across all iterations).

§9.1 (no Sharpe, no p-values, no annualized framing) preserved.

---

## 11. What v0.4 does NOT claim

Unchanged in spirit from v0.1 / v0.2 / v0.3:

- v0.4 does NOT claim alpha or live-runtime prediction.
- v0.4 does NOT claim the realized-volatility detector is the *correct* regime definition. It claims volatility is a measurable, reproducible regime cut, and tests whether conditioning on it produces sharper bucket separation than the calendar cut.
- v0.4 does NOT claim 20D + median is the optimal vol-detector configuration. §13.2 sensitivity tests alternative thresholds.
- v0.4 does NOT remove the small look-ahead in the volatility threshold computation (window-median rv uses the full window's distribution). Documented as v0.5 candidate.

---

## 12. Secondary measurements

### 12.1 Lifecycle revision per regime

The v0.3 §3 lifecycle primary measurement is preserved as v0.4 secondary, stratified by both regime detectors.

For each (lifecycle_bucket × regime × horizon): report v0.3 §3 metrics. Tests whether the 5D lifecycle internal gap (v0.3: +0.79% overall, but +1.83% in Sub-window A vs −0.22% in Sub-window B per §12.2) holds under the volatility regime cut.

### 12.2 Warrant coverage (preserved from v0.3 §11.3 / §11.4)

Same protocol, also stratified by both regimes.

---

## 13. Sensitivity appendix

### 13.1 Calendar vs volatility regime agreement

A 2×2 contingency table of row counts across (calendar_regime × vol_regime). If the two detectors are picking up the same regime structure, the table will be diagonal-dominant (most rows in A_early∩LOW_VOL and B_later∩HIGH_VOL, or the reverse). If they're orthogonal, the cells will be roughly equal.

### 13.2 Volatility threshold sensitivity

The §3.2 detector uses the median as the threshold (50th percentile). §13.2 re-runs the regime assignment using three alternative thresholds and reports how the per-regime bucket numbers shift:

- 33rd percentile (LOW_VOL = bottom third; HIGH_VOL = top two-thirds)
- 50th percentile (the primary — for direct comparison)
- 67th percentile (LOW_VOL = bottom two-thirds; HIGH_VOL = top third)

Tests whether the v0.4 finding is stable across threshold choices or sensitive to the exact cut.

### 13.3 Event-type granularity (preserved from v0.3 §12.1)

Same as v0.3 §12.1. Reconfirmed / strengthened / contradicted / weakened reported separately for the lifecycle secondary axis. v0.4 adds per-regime stratification of this granular view.

### 13.4 Sensitivity is not the primary claim (preserved)

Same constraint as prior versions.

---

## 14. Versioning policy

v0.4 is a major rule change relative to v0.3 (primary axis is now regime-conditioned). Any further change after v0.4 lock requires v0.5. v0.1 / v0.2 / v0.3 measurement results remain valid as their own versions.

Ambiguities encountered during v0.4 implementation are appended to `SENSEMAKING_V1_5_ISSUES_LOG.md` (continuing from I-001, I-002, and any later entries) and resolved at v0.5.

---

## 15. What v0.4 implementation will produce

```
sensemaking_v1_5/
  sensemaking_v1_5_harness.py            (unchanged; rows.parquet reused)
  sensemaking_v1_5_regime_v0_4.py        v0.4: compute calendar_regime + vol_regime per (T, ticker)
  sensemaking_v1_5_state_v0_4.py         v0.4 primary: state buckets × regime
  sensemaking_v1_5_lifecycle_v0_4.py     v0.4 secondary: lifecycle revision × regime
  sensemaking_v1_5_coverage_v0_4.py      v0.4 tertiary: warrant coverage × regime
  sensemaking_v1_5_sensitivity_v0_4.py   §13 sensitivity (cross-detector agreement, threshold sensitivity, event-type)
  sensemaking_v1_5_report_v0_4.py        v0.4 report + four-way head-to-head
  data/
    sensemaking_v1_5_regimes_v0_4.parquet         per-T regime tags
    sensemaking_v1_5_state_v0_4.parquet           state rows with regime joined
    sensemaking_v1_5_lifecycle_v0_4.parquet       lifecycle rows with regime joined
    sensemaking_v1_5_state_summary_v0_4.json
    sensemaking_v1_5_lifecycle_summary_v0_4.json
    sensemaking_v1_5_coverage_summary_v0_4.json
    sensemaking_v1_5_sensitivity_summary_v0_4.json
    sensemaking_v1_5_report_v0_4.json
  SENSEMAKING_V1_5_REPORT_v0_4.md
```

v0.1 / v0.2 / v0.3 artifacts in `data/` are NOT touched.

---

## 16. Audit trail

| Field | Value |
|---|---|
| Author | Susan Stranburg |
| Locked | 2026-05-30 |
| Immediate predecessor | [SENSEMAKING_V1_5_PRE_REGISTRATION_v0.3.md](SENSEMAKING_V1_5_PRE_REGISTRATION_v0.3.md), locked 2026-05-30 |
| v0.2 reference | [SENSEMAKING_V1_5_PRE_REGISTRATION_v0.2.md](SENSEMAKING_V1_5_PRE_REGISTRATION_v0.2.md), locked 2026-05-30 |
| v0.1 reference | [SENSEMAKING_V1_5_PRE_REGISTRATION_v0.1.md](SENSEMAKING_V1_5_PRE_REGISTRATION_v0.1.md), locked 2026-05-29 |
| Hash of predecessor artifacts at lock time | (computed at v0.4 first run) |
| Rules version | v0.4 |

---

## 17. What v0.4 will say publicly

If regime-conditioning sharpens bucket separation:

> v0.4 promoted regime-conditioned state buckets to the primary measurement and introduced a realized-volatility regime detector alongside the v0.3 calendar cut. Per-regime numbers are materially sharper than the aggregate — the v0.3 finding that state buckets are field-context dependent generalizes from a calendar-midpoint cut to a market-volatility cut. The unconditioned aggregate headline blends two regimes and loses information.

If the volatility detector does not improve on the calendar cut:

> v0.4 tested whether a market-vol regime detector produces sharper state-bucket separation than the v0.3 calendar midpoint. It does not — both detectors produce similar per-regime numbers. The v0.3 calendar cut was a usable proxy for whatever underlying regime structure was driving the v1.5 window's heterogeneity; finer regime detection is not required at this measurement scale.

If the two detectors disagree dramatically:

> The calendar and volatility regime detectors classify the window's evaluation rows differently. The v0.4 finding is methodological: which regime cut you use changes which buckets look constructive. v0.5 needs an external arbiter (a benchmark regime classification, or a holdout-window validation) before further conditioning.

Each outcome is a v0.4 result. The discipline is what makes any of them publishable.

---

## 18. Out of v0.4 scope

Explicitly deferred to v0.5 or later:

- Rolling / expanding-window threshold for the volatility detector (removes the small look-ahead in §6).
- Trend-based or drawdown-based regime detectors (v0.4 commits to volatility).
- Three-or-more regime cuts (v0.4 uses two: LOW_VOL vs HIGH_VOL).
- Recalibration of bucket assignments (REPRICING, EARLY remain as v0.3 specified).
- Live-runtime claims of any kind.
- Tests on substrates beyond the AI ecosystem corpus.
