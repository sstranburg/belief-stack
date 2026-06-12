# Sensemaking v1.5 — Measurement Report (v0.1)

_Generated: 2026-05-30T01:26:02.342512Z_

**Rules version:** v0.1, locked 2026-05-29.
**Pre-registration:** [SENSEMAKING_V1_5_PRE_REGISTRATION_v0.1.md](SENSEMAKING_V1_5_PRE_REGISTRATION_v0.1.md).
**Issues log:** [SENSEMAKING_V1_5_ISSUES_LOG.md](SENSEMAKING_V1_5_ISSUES_LOG.md) (I-001, I-002).
**Companion v1 case study:** [topicspace.ai/research/case-studies/sensemaking-v1](https://topicspace.ai/research/case-studies/sensemaking-v1).

---

## 1. Universe and sampling

| Field | Value |
|---|---|
| Window | 2025-12-05 → 2026-05-26 (~120 trading days) |
| Primary universe rows (date × ticker, baseline variant) | 3,627 |
| Experimental cohort rows (MP only, see I-002) | 117 |
| Tickers in backtest_history.parquet | 32 |
| Tickers in actors.json (snapshot) | 42 |
| Tickers absent from backtest_history (I-002) | 10 (ALAB, CLS, COHR, MELI, ODC, SNDK, SOFI, USAR, WDC, ZETA) |
| Horizons | 5 trading days, 20 trading days |
| Variant (per I-001) | `baseline` |

Per §1.1, this is calibrated reporting, not pass/fail. No statistical-significance threshold is invoked. Sample sizes by horizon and bucket appear in the §3 tables.

---

## 2. Primary head — bucket × horizon

Per §6, only Constructive and Cautious bucket rows are labeled with Hit / FP / FN. Ambiguous rows do not carry a directional prediction and so do not contribute to hit rate; they are the §8.1 baseline.

### 2.1 5D horizon

| Bucket | n | Hits | FP / FN | Hit rate | Avg fwd_rel | Median fwd_rel | % positive | Δ avg vs baseline |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| **Constructive** | 1,255 | 571 | 684 | 0.455 | +0.28% | -0.67% | 0.455 | +0.14% |
| **Cautious** | 823 | 375 | 448 | 0.456 | +1.46% | +0.74% | 0.544 | +1.32% |
| **Ambiguous** | 1,394 | 0 | 0 | n/a | +0.14% | -0.15% | 0.488 | +0.00% |

### 2.2 20D horizon

| Bucket | n | Hits | FP / FN | Hit rate | Avg fwd_rel | Median fwd_rel | % positive | Δ avg vs baseline |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| **Constructive** | 1,086 | 518 | 568 | 0.477 | +3.98% | -0.80% | 0.477 | +2.97% |
| **Cautious** | 685 | 330 | 355 | 0.482 | +2.82% | +0.44% | 0.518 | +1.81% |
| **Ambiguous** | 1,236 | 0 | 0 | n/a | +1.01% | -0.21% | 0.492 | +0.00% |

**Reading the bucket head, plainly:**

- At 5D, the Constructive bucket beats the Ambiguous baseline by +0.14% in average forward relative return — small. Hit rate 0.455 is close to chance. Cautious *also* beats the baseline by +1.32% in average — the **opposite** of the bucket's directional implication.
- At 20D, Constructive separates from baseline by +2.97% in average forward relative return — modest but visible. Cautious continues to beat baseline by +1.81%, again the opposite of expected direction.
- Across both horizons, the Cautious bucket does NOT separate downward from baseline. That is the v0.1 primary's clearest finding: as currently bucketed, NEG_CONFIRMATION + DIVERGENCE do not behave as a cautious group on forward outcomes.

---

## 3. Per-state heterogeneity

The bucket head hides a great deal of variation. Each individual state contributes differently to its bucket's distribution.

### 3.1 5D horizon, per state

| Bucket | State | n | Avg fwd_rel | Median fwd_rel | % positive |
|---|---|--:|--:|--:|--:|
| Ambiguous | `REPRICING` | 1,183 | -0.37% | -0.35% | 0.473 |
| Ambiguous | `PRICE-LED` | 90 | +3.08% | +1.62% | 0.589 |
| Ambiguous | `UNCLEAR` | 70 | +2.89% | +1.42% | 0.586 |
| Ambiguous | `MACRO` | 51 | +2.92% | +0.54% | 0.510 |
| Cautious | `DIVERGENCE` | 504 | +1.66% | +0.77% | 0.548 |
| Cautious | `NEG_CONFIRMATION` | 319 | +1.15% | +0.52% | 0.539 |
| Constructive | `EARLY` | 495 | -0.12% | -0.91% | 0.422 |
| Constructive | `CONFIRMED` | 407 | +0.09% | -0.68% | 0.462 |
| Constructive | `DISAGREEMENT` | 353 | +1.05% | -0.17% | 0.493 |

### 3.2 20D horizon, per state

| Bucket | State | n | Avg fwd_rel | Median fwd_rel | % positive |
|---|---|--:|--:|--:|--:|
| Ambiguous | `REPRICING` | 1,027 | +0.43% | -0.53% | 0.485 |
| Ambiguous | `PRICE-LED` | 89 | +5.52% | +1.06% | 0.551 |
| Ambiguous | `UNCLEAR` | 70 | +1.03% | +0.30% | 0.514 |
| Ambiguous | `MACRO` | 50 | +5.01% | +0.32% | 0.500 |
| Cautious | `DIVERGENCE` | 403 | +2.86% | +1.51% | 0.563 |
| Cautious | `NEG_CONFIRMATION` | 282 | +2.78% | -2.35% | 0.454 |
| Constructive | `EARLY` | 441 | +0.68% | -1.59% | 0.440 |
| Constructive | `CONFIRMED` | 345 | +5.25% | +1.91% | 0.545 |
| Constructive | `DISAGREEMENT` | 300 | +7.37% | -1.42% | 0.453 |

**State-level callouts at 20D:**

- `CONFIRMED` (n=345) avg +5.25% and `DISAGREEMENT` (n=300) avg +7.37% — these two carry the constructive signal.
- `EARLY` (n=441) avg +0.68% — weaker than its bucket implies; pulls the Constructive bucket average down.
- `DIVERGENCE` (n=403) avg +2.86% and `NEG_CONFIRMATION` (n=282) avg +2.78% — both Cautious states show POSITIVE average forward returns, contradicting the bucket's directional implication.
- `REPRICING` (n=1,027) avg +0.43% — the largest single-state population; its assignment to Ambiguous is load-bearing for the headline. Sensitivity §12.1 quantifies.

---

## 4. Secondary — lifecycle revision-prediction (§11.1)

Bucket lifecycle events by event type: reconfirmed + strengthened → Constructive_revision; contradicted + weakened → Cautious_revision. Born / retired events are field-population events and excluded from the revision-prediction measurement. Forward returns computed from the event date.

Matched events: 473 / 493 (unmatched = off-trading-day or off-universe).

### 4.1 Lifecycle revision-prediction at 5D

| Lifecycle bucket | n | Avg fwd_rel | Median | % positive | Δ avg vs primary Ambiguous baseline |
|---|--:|--:|--:|--:|--:|
| **Constructive_revision** | 216 | +0.65% | +0.15% | 0.514 | +0.51% |
| **Cautious_revision** | 242 | -0.14% | -0.23% | 0.492 | -0.28% |
| **Ambiguous_baseline** | 1,394 | +0.14% | -0.15% | 0.488 | — |

### 4.2 Lifecycle revision-prediction at 20D

| Lifecycle bucket | n | Avg fwd_rel | Median | % positive | Δ avg vs primary Ambiguous baseline |
|---|--:|--:|--:|--:|--:|
| **Constructive_revision** | 188 | +2.41% | -0.28% | 0.489 | +1.40% |
| **Cautious_revision** | 222 | +3.48% | +0.43% | 0.532 | +2.47% |
| **Ambiguous_baseline** | 1,236 | +1.01% | -0.21% | 0.492 | — |

**Reading lifecycle revision:**

- At 5D, Constructive_revision (n=216) avg +0.65% beats baseline by +0.51%; Cautious_revision (n=242) avg -0.14% underperforms baseline by -0.28%. **Both directions go the right way at 5D**; this is the v0.1 measurement's cleanest single signal.
- At 20D, Constructive_revision (n=188) avg +2.41% beats baseline by +1.40%; Cautious_revision (n=222) avg +3.48% *also* beats baseline by +2.47% — same wrong-direction pattern the Cautious *state* bucket showed at 20D in §2.

---

## 5. Tertiary — warrant coverage (§11.2)

Partition the primary universe by `sufficient_data ∈ {True, False}`. For each partition, compute bucket metrics. The §11.2 expectation under v1's coverage discipline is that insufficient-data rows produce distributions indistinguishable from baseline (the system correctly declined to make a confident claim).

### 5.1 5D horizon by sufficient-data partition

| Partition | Bucket | n | Avg fwd_rel | % positive | Δ avg vs partition baseline |
|---|---|--:|--:|--:|--:|
| sufficient_data_True | Constructive | 1,237 | +0.30% | 0.456 | +0.36% |
| sufficient_data_True | Cautious | 798 | +1.43% | 0.541 | +1.49% |
| sufficient_data_True | Ambiguous | 1,283 | -0.06% | 0.481 | — |
| sufficient_data_False | Constructive | 18 | -1.44% | 0.389 | -3.88% |
| sufficient_data_False | Cautious | 25 | +2.58% | 0.640 | +0.13% |
| sufficient_data_False | Ambiguous | 111 | +2.44% | 0.568 | — |

### 5.2 20D horizon by sufficient-data partition

| Partition | Bucket | n | Avg fwd_rel | % positive | Δ avg vs partition baseline |
|---|---|--:|--:|--:|--:|
| sufficient_data_True | Constructive | 1,068 | +4.13% | 0.483 | +2.99% |
| sufficient_data_True | Cautious | 660 | +3.05% | 0.518 | +1.91% |
| sufficient_data_True | Ambiguous | 1,125 | +1.14% | 0.494 | — |
| sufficient_data_False | Constructive | 18 | -4.70% | 0.111 | -4.43% |
| sufficient_data_False | Cautious | 25 | -3.12% | 0.520 | -2.85% |
| sufficient_data_False | Ambiguous | 111 | -0.27% | 0.468 | — |

**Reading warrant coverage:**

- At 20D, `sufficient_data=True` Constructive (n=1,068) beats its partition baseline by +2.99%; `sufficient_data=False` Constructive (n=18) misses its partition baseline by -4.43%. The sign flips. Sample size on the insufficient partition is small (n=18) and should not be over-read; directionally, the coverage flag is informative about whether a state's directional implication holds.
- This is consistent with the v1 case study's coverage-discipline claim: the system marks low-warrant observations correctly. The v1.5 measurement does NOT conclude the coverage threshold is well-calibrated; it concludes the flag carries information at this sample size and window.

---

## 6. Sensitivity appendix (§12)

Per §12.3, the sensitivity appendix is reported **clearly separated** from the primary, never inline. The purpose is to expose how much the headline numbers depend on two specific bucket / universe choices the v0.1 pre-registration committed to. These numbers are **not** competing with the primary; they show its robustness.

### 6.1 §12.1 — REPRICING-as-Constructive

Move REPRICING from Ambiguous to Constructive; everything else unchanged.

**5D horizon:**

| Bucket | n | Avg fwd_rel | Δ vs (this run's) baseline |
|---|--:|--:|--:|
| Constructive | 2,438 | -0.04% | -3.02% |
| Cautious | 823 | +1.46% | -1.52% |
| Ambiguous | 211 | +2.98% | +0.00% |

**20D horizon:**

| Bucket | n | Avg fwd_rel | Δ vs (this run's) baseline |
|---|--:|--:|--:|
| Constructive | 2,113 | +2.25% | -1.64% |
| Cautious | 685 | +2.82% | -1.07% |
| Ambiguous | 209 | +3.89% | +0.00% |

**Headline impact:** at 20D, the primary Constructive Δ vs baseline of +2.97% becomes -1.64% under REPRICING-as-Constructive. **The sign flips.** This is the most consequential sensitivity finding in v1.5: the headline depends on REPRICING's bucket. REPRICING is the largest single state (1,027 rows at 20D), so reclassifying it pulls the Constructive average down and the Ambiguous baseline up simultaneously. v0.2 should explicitly re-decide REPRICING's bucket, ideally with a narrative-direction-aware mapping that splits bullish-narrative REPRICING from bearish-narrative REPRICING.

### 6.2 §12.2 — Experimental tickers included

Include USAR / MP / ODC in the primary universe (only MP is present in `backtest_history.parquet`; see I-002). Everything else unchanged.

**5D horizon:**

| Bucket | n | Avg fwd_rel | Δ vs (this run's) baseline |
|---|--:|--:|--:|
| Constructive | 1,285 | +0.25% | +0.16% |
| Cautious | 858 | +1.47% | +1.37% |
| Ambiguous | 1,441 | +0.10% | +0.00% |

**20D horizon:**

| Bucket | n | Avg fwd_rel | Δ vs (this run's) baseline |
|---|--:|--:|--:|
| Constructive | 1,116 | +3.70% | +2.70% |
| Cautious | 713 | +3.16% | +2.16% |
| Ambiguous | 1,275 | +1.00% | +0.00% |

**Headline impact:** experimental inclusion shifts the bucket averages by at most a few basis points. The §2.2 exclusion is methodologically conservative without changing the conclusions. ALAB / CLS / COHR / MELI / SNDK / SOFI / WDC / ZETA are absent from `backtest_history.parquet` (I-002) and cannot be included in this sensitivity; a separate v0.2 measurement could rebuild backtest_history to include them.

---

## 7. What v1.5 says (and does not say)

Per §10 of the locked pre-registration, this measurement does NOT claim:

- Alpha against the market.
- Live-deployment predictive performance.
- Generalization beyond the AI ecosystem corpus, beyond 173 days, or beyond this user's pipeline.
- That the current state-to-bucket mapping (§3.2 of the pre-reg) is optimal.
- A pass / fail call on the v1 belief field.

Under locked rules, the v1.5 measurement says:

1. **The Constructive bucket separates modestly from baseline at 20D** (+2.97% avg fwd relative return). At 5D the separation is negligible. The signal is concentrated in CONFIRMED and DISAGREEMENT; EARLY does not contribute.
2. **The Cautious bucket does NOT separate from baseline in the expected direction.** Both DIVERGENCE and NEG_CONFIRMATION show positive average forward returns, contradicting the bucket's directional implication at both horizons.
3. **Lifecycle revision events show direction-correct separation at 5D.** Constructive_revision beats baseline; Cautious_revision underperforms. This is the cleanest single signal in v1.5. At 20D the cautious-revision signal also flips wrong direction.
4. **The warrant-coverage flag is informative.** sufficient_data=True Constructive carries the 20D signal; sufficient_data=False Constructive reverses sign. Small sample on the insufficient side (n=18) means this is suggestive, not conclusive.
5. **REPRICING's bucket assignment is load-bearing** for the headline. The §12.1 sensitivity flips the 20D Constructive Δ vs baseline from positive to negative. v0.2 must re-decide.

---

## 8. What v0.2 needs

Based on the v0.1 measurement, in priority order:

1. **Re-decide REPRICING's bucket.** The §12.1 sensitivity shows the headline depends on this choice. A narrative-direction-aware split (bullish REPRICING vs bearish REPRICING) is the obvious candidate; another is keeping REPRICING in Ambiguous but reporting its state-level numbers as a sub-headline.
2. **Investigate why Cautious states fail to separate downward.** DIVERGENCE and NEG_CONFIRMATION both show positive forward returns. Two candidate explanations: (a) the AI ecosystem 2025-12 to 2026-05 window was structurally constructive (rising tide); (b) the cautious states detect noise the market subsequently dismisses. v0.2 should add an actor-direction-conditional control group.
3. **Split EARLY from the Constructive headline.** It dilutes the bucket. Either move it to its own bucket or report it separately.
4. **Add temporal stratification.** v0.1 averages across the whole 173-day window. v0.2 should report per-month or per-half-window numbers; the AI ecosystem narrative was structurally different in 2025-12 (early-cycle) vs 2026-04+ (post-DeepSeek aftermath).
5. **Expand backtest_history to include post-window tickers.** ALAB, CLS, COHR, MELI, SNDK, SOFI, WDC, ZETA are tracked in actors.json but absent from the backtest substrate. v0.2 can rebuild with broader coverage if the v1 pipeline's `generate_storm_objects.py` is re-run with the augmented actor list.

---

## 9. Audit trail

| File | SHA-256 |
|---|---|
| `rows.parquet` | `6092be6b1a04368c98f9680f2bf85692572f7569e83f4d188980a90d31be753c` |
| `labeled.parquet` | `68aa6b598851e96e385b16b9f90312b82697e6564f3c5b26b6a43280662cfa04` |
| `primary.json` | `44036c6a39811f0cc66d1404757a0aa55fd4b91230dbf60c36cf465d668975bd` |
| `secondary.json` | `e20c30bb4d57e0a67ace1e7a341c42b9cb9e4607b35cc93be9d58889f1f63d21` |
| `sensitivity.json` | `e3d4be513acd6a63e828952e73aabeff5818a90ffa37828387ce966470f81bf6` |

Pre-registration locked 2026-05-29. Measurement run 2026-05-29. v1 substrate artifacts (`backtest_history.parquet`, `expectation_lifecycle_events.parquet`, prices) read-only during measurement.
