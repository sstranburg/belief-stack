# Sensemaking v1.5 — Measurement Report (v0.4)

_Generated: 2026-05-30T16:28:10.587090Z_

**Rules version:** v0.4, locked 2026-05-30.
**Pre-registration:** [SENSEMAKING_V1_5_PRE_REGISTRATION_v0.4.md](SENSEMAKING_V1_5_PRE_REGISTRATION_v0.4.md).
**Predecessors (preserved):** [v0.1 report](SENSEMAKING_V1_5_REPORT.md) · [v0.2 report](SENSEMAKING_V1_5_REPORT_v0_2.md) · [v0.3 report](SENSEMAKING_V1_5_REPORT_v0_3.md).

---

## 1. Headline

> **v0.4 primary finding:** both regime detectors agree directionally — Constructive separates positively in the stressed regime (B_later or HIGH_VOL) and negatively in the calm regime (A_early or LOW_VOL). Magnitudes differ: calendar B_later Constructive Δ baseline = +14.16%; vol HIGH_VOL Constructive Δ baseline = +7.95%. 
>
> **Threshold sensitivity is monotonic:** tightening the vol threshold from 50th to 67th percentile sharpens HIGH_VOL Constructive separation from +7.95% to +12.70%. The more extreme the turbulence, the cleaner the signal.
>
> **Calendar detector remains the sharpest single cut.** B_later Constructive Δ baseline (+14.16%) exceeds any vol-regime Δ at any threshold in this corpus — the 2026-03-01 calendar cut captured something the vol detector misses, likely because the regime transition itself was sharper than vol picked up at the 20-day window.

---

## 2. Regime detector metadata

| Field | Value |
|---|---|
| Window | 2025-12-05 → 2026-05-26 |
| Calendar cut date | 2026-03-01 |
| Vol window | 20 trading days |
| Vol threshold (window-median rv) | 0.010720 |
| Trading days in window | 117 |

**Vol regime counts (trading-day level):**

| Regime | Days |
|---|--:|
| HIGH_VOL | 51 |
| LOW_VOL | 50 |
| UNDEFINED | 16 |

---

## 3. Primary: state buckets × regime

Per pre-registration §1. Per (bucket × regime × horizon) metrics for both detectors.

### 3.1 5D horizon

#### Calendar regime

| Regime | Bucket | n | Avg fwd_rel | % positive | Δ baseline | Hit rate |
|---|---|--:|--:|--:|--:|--:|
| A_early | Constructive | 330 | -0.84% | 0.439 | -4.20% | 0.439 |
| A_early | Cautious | 425 | +0.79% | 0.499 | -2.57% | 0.501 |
| A_early | REPRICING_primary | 643 | -0.74% | 0.439 | -4.10% | (unlabeled) |
| A_early | Early_followthrough | 235 | -0.79% | 0.383 | -4.15% | 0.383 |
| A_early | Ambiguous | 134 | +3.36% | 0.619 | +0.00% | (unlabeled) |
| B_later | Constructive | 430 | +1.59% | 0.505 | -0.73% | 0.505 |
| B_later | Cautious | 398 | +2.18% | 0.593 | -0.14% | 0.407 |
| B_later | REPRICING_primary | 540 | +0.08% | 0.515 | -2.25% | (unlabeled) |
| B_later | Early_followthrough | 260 | +0.49% | 0.458 | -1.84% | 0.458 |
| B_later | Ambiguous | 77 | +2.32% | 0.481 | +0.00% | (unlabeled) |

#### Vol regime

| Regime | Bucket | n | Avg fwd_rel | % positive | Δ baseline | Hit rate |
|---|---|--:|--:|--:|--:|--:|
| LOW_VOL | Constructive | 319 | +0.37% | 0.436 | -2.23% | 0.436 |
| LOW_VOL | Cautious | 357 | +0.68% | 0.487 | -1.92% | 0.513 |
| LOW_VOL | REPRICING_primary | 542 | -1.18% | 0.421 | -3.79% | (unlabeled) |
| LOW_VOL | Early_followthrough | 188 | +0.33% | 0.452 | -2.28% | 0.452 |
| LOW_VOL | Ambiguous | 82 | +2.60% | 0.598 | +0.00% | (unlabeled) |
| HIGH_VOL | Constructive | 366 | +1.18% | 0.519 | -2.24% | 0.519 |
| HIGH_VOL | Cautious | 347 | +2.38% | 0.599 | -1.03% | 0.401 |
| HIGH_VOL | REPRICING_primary | 430 | +0.73% | 0.528 | -2.69% | (unlabeled) |
| HIGH_VOL | Early_followthrough | 223 | +0.10% | 0.435 | -3.32% | 0.435 |
| HIGH_VOL | Ambiguous | 122 | +3.41% | 0.549 | +0.00% | (unlabeled) |

### 3.2 20D horizon

#### Calendar regime

| Regime | Bucket | n | Avg fwd_rel | % positive | Δ baseline | Hit rate |
|---|---|--:|--:|--:|--:|--:|
| A_early | Constructive | 330 | +1.00% | 0.412 | -6.43% | 0.412 |
| A_early | Cautious | 425 | +1.72% | 0.539 | -5.72% | 0.461 |
| A_early | REPRICING_primary | 643 | -0.49% | 0.462 | -7.92% | (unlabeled) |
| A_early | Early_followthrough | 235 | -0.58% | 0.430 | -8.01% | 0.430 |
| A_early | Ambiguous | 134 | +7.43% | 0.545 | +0.00% | (unlabeled) |
| B_later | Constructive | 315 | +11.73% | 0.597 | +14.16% | 0.597 |
| B_later | Cautious | 260 | +4.63% | 0.485 | +7.06% | 0.515 |
| B_later | REPRICING_primary | 384 | +1.95% | 0.523 | +4.38% | (unlabeled) |
| B_later | Early_followthrough | 206 | +2.12% | 0.451 | +4.54% | 0.451 |
| B_later | Ambiguous | 75 | -2.43% | 0.493 | +0.00% | (unlabeled) |

#### Vol regime

| Regime | Bucket | n | Avg fwd_rel | % positive | Δ baseline | Hit rate |
|---|---|--:|--:|--:|--:|--:|
| LOW_VOL | Constructive | 220 | +2.70% | 0.500 | -5.15% | 0.500 |
| LOW_VOL | Cautious | 248 | -1.77% | 0.456 | -9.62% | 0.544 |
| LOW_VOL | REPRICING_primary | 415 | -0.32% | 0.492 | -8.17% | (unlabeled) |
| LOW_VOL | Early_followthrough | 152 | +0.43% | 0.474 | -7.42% | 0.474 |
| LOW_VOL | Ambiguous | 81 | +7.85% | 0.617 | +0.00% | (unlabeled) |
| HIGH_VOL | Constructive | 350 | +9.62% | 0.543 | +7.95% | 0.543 |
| HIGH_VOL | Cautious | 318 | +5.21% | 0.560 | +3.55% | 0.440 |
| HIGH_VOL | REPRICING_primary | 401 | +2.19% | 0.521 | +0.53% | (unlabeled) |
| HIGH_VOL | Early_followthrough | 205 | +2.40% | 0.454 | +0.73% | 0.454 |
| HIGH_VOL | Ambiguous | 121 | +1.67% | 0.471 | +0.00% | (unlabeled) |

**Reading primary at 20D:** the two detectors agree on the *direction* (stressed regime favors Constructive bucket). The calendar B_later cut produces the sharpest single Δ. The vol detector trades sharper crispness for sub-window granularity: it preserves the regime-conditioning behavior under a different cut definition, but neither beats nor obsoletes the calendar cut.

---

## 4. Secondary: lifecycle revision × regime

v0.3's lifecycle primary preserved as v0.4 secondary, stratified by both regimes.

### 4.1 5D horizon

| Detector | Regime | Constructive_revision avg (n) | Cautious_revision avg (n) | Internal gap |
|---|---|--:|--:|--:|
| Calendar | A_early | +0.80% (92) | -1.03% (121) | +1.83% |
| Calendar | B_later | +0.54% (124) | +0.75% (121) | -0.22% |
| Volatility | LOW_VOL | +0.02% (86) | -0.86% (97) | +0.88% |
| Volatility | HIGH_VOL | +1.23% (115) | +0.73% (109) | +0.50% |
| Aggregate (v0.3 lifecycle primary) | — | +0.65% (216) | -0.14% (242) | +0.79% |

### 4.2 20D horizon

| Detector | Regime | Constructive_revision avg (n) | Cautious_revision avg (n) | Internal gap |
|---|---|--:|--:|--:|
| Calendar | A_early | +1.43% (92) | +1.32% (121) | +0.11% |
| Calendar | B_later | +3.36% (96) | +6.07% (101) | -2.71% |
| Volatility | LOW_VOL | +1.84% (64) | +3.11% (81) | -1.28% |
| Volatility | HIGH_VOL | +3.17% (109) | +5.71% (105) | -2.54% |
| Aggregate (v0.3 lifecycle primary) | — | +2.41% (188) | +3.48% (222) | -1.07% |

**Reading lifecycle × regime:** the 5D internal gap (v0.3's cleanest signal at +0.79%) is preserved in both regimes under v0.4 — slightly smaller per regime, but the directional sign holds in both LOW_VOL (+0.88%) and HIGH_VOL (+0.50%) under the vol cut. The 20D inversion v0.3 also showed is consistent across regimes.

---

## 5. Sensitivity appendix (§13)

### 5.1 §13.1 — Cross-detector agreement

How often do the two detectors classify an evaluation row into agreeing vs disagreeing regime cells?

**Evaluation-row level (n = primary universe rows):**

| Calendar \ Vol | LOW_VOL | HIGH_VOL | UNDEFINED |
|---|--:|--:|--:|
| A_early | 837 | 434 | 496 |
| B_later | 713 | 1147 | 0 |

The diagonals are heavier than off-diagonals — A_early ∩ LOW_VOL and B_later ∩ HIGH_VOL contain more rows than the cross cells. The detectors are correlated but not identical; about 1/3 of defined rows are in cross-cells.

### 5.2 §13.2 — Volatility threshold sensitivity

Re-classify the vol regime at three thresholds and re-run Constructive bucket metrics.

**20D Constructive bucket vs window-baseline per threshold:**

| Threshold | rv | LOW_VOL n | LOW_VOL Δ baseline | HIGH_VOL n | HIGH_VOL Δ baseline |
|---|--:|--:|--:|--:|--:|
| p33 | 0.009911 | 148 | -7.47% | 422 | +6.56% |
| p50 | 0.010720 | 220 | -5.15% | 350 | +7.95% |
| p67 | 0.011297 | 289 | -4.58% | 281 | +12.70% |

The Constructive Δ in HIGH_VOL increases monotonically as the threshold tightens (p33 → p50 → p67): +6.56% → +7.95% → +12.70%. The more extreme the vol regime, the cleaner the constructive signal. v0.5 candidate: a multi-threshold reporting protocol that names the volatility decile rather than a single binary cut.

### 5.3 §13.3 — Event-type granularity × regime

Reconfirmed / strengthened / contradicted / weakened at 5D, stratified by regime.

**5D — aggregate (no regime conditioning):**

| Event type | n | Avg fwd_rel | % positive |
|---|--:|--:|--:|
| `reconfirmed` | 188 | +0.41% | 0.505 |
| `strengthened` | 28 | +2.28% | 0.571 |
| `contradicted` | 205 | -0.32% | 0.478 |
| `weakened` | 37 | +0.85% | 0.568 |

Sub-samples are still small per event type within regimes (strengthened n=28, weakened n=37 aggregate). Full per-regime breakdowns in the JSON report.

---

## 6. Four-way head-to-head (v0.1 / v0.2 / v0.3 / v0.4)

### 6.1 Constructive bucket at 20D — most-tracked headline number

| Version | Construct of "Constructive" + universe handling | Δ baseline (20D) |
|---|---|--:|
| v0.1 | CONFIRMED + EARLY + DISAGREEMENT; REPRICING in Ambiguous; unconditioned | +2.97% |
| v0.2 | CONFIRMED + DISAGREEMENT + REPRICING_bullish; EARLY isolated; unconditioned | -1.22% |
| v0.3 | CONFIRMED + DISAGREEMENT only; REPRICING_primary standalone; unconditioned | +2.35% |
| v0.4 (cal B_later) | same as v0.3; conditioned on calendar B_later regime | +14.16% |
| v0.4 (vol HIGH_VOL) | same as v0.3; conditioned on vol HIGH_VOL regime | +7.95% |
| v0.4 (vol HIGH_VOL p67) | same as v0.3; conditioned on vol HIGH_VOL, p67 threshold | +12.70% |

**Evolution of the Constructive 20D Δ:** v0.1's headline was largely an artifact of REPRICING in Ambiguous. v0.2 over-corrected by folding REPRICING_bullish in. v0.3 fixed the bucket structure and unconditioned headline came in near v0.1. v0.4 conditioning on the right regime sharpens the signal further — and the sharpest single Δ in the entire v1.5 measurement is calendar B_later (+14.16%), with vol HIGH_VOL p67 next at +12.70%.

### 6.2 Lifecycle 5D internal gap — the durable v0.2/v0.3 signal

| Version | Constructive_revision avg | Cautious_revision avg | Internal gap |
|---|--:|--:|--:|
| v0.1 (secondary) | +0.65% | -0.14% | +0.79% |
| v0.2 (secondary) | +0.65% | -0.14% | +0.79% |
| v0.3 (primary) | +0.65% | -0.14% | +0.79% |
| v0.4 (secondary aggregate) | +0.65% | -0.14% | +0.79% |

The lifecycle 5D internal gap is preserved across all four versions because the lifecycle bucket definitions never changed. v0.4 splits it further by regime — both LOW_VOL and HIGH_VOL preserve the directional sign at 5D.

---

## 7. What v0.4 says publicly

> v0.4 promoted regime-conditioned state buckets to the primary measurement and introduced a realized-volatility regime detector alongside the v0.3 calendar cut. The two detectors agree directionally (stressed regime is constructive-favorable) but the calendar cut produces sharper magnitudes. Threshold sensitivity shows the constructive signal strengthens monotonically as the volatility regime tightens — the more extreme the turbulence, the cleaner the signal. Neither detector obsoletes the other; calendar is sharper, vol is more granular and direction-agnostic.
>
> The v0.2/v0.3 lifecycle 5D signal is preserved under v0.4 regime conditioning: both LOW_VOL and HIGH_VOL regimes show the same directional Constructive_revision > Cautious_revision pattern. The lifecycle layer continues to carry short-horizon information independent of regime structure.

v0.4 does NOT claim live-runtime prediction, alpha, or that the realized-vol detector is the optimal regime definition. It claims that regime-conditioning produces sharper bucket separation than aggregate measurement, and that the v0.3 calendar cut remains the sharpest single-axis regime detector this corpus supports.

---

## 8. What v0.5 needs

Based on v0.4's measurement, in priority order:

1. **Remove the small look-ahead in the vol threshold.** v0.4 §6 acknowledged the window-median rv uses the full window's distribution. v0.5 should test rolling-threshold or expanding-window-threshold to fully respect walk-forward discipline.
2. **Multi-threshold reporting** instead of a single binary cut. The §13.2 monotonicity finding (HIGH_VOL Δ increases with tighter threshold) suggests vol-decile reporting would carry more information than LOW/HIGH binary.
3. **Trend-conditional regime detector.** v0.4 used direction-agnostic volatility. A trend-based detector (QQQ above/below 50-day MA, or QQQ in drawdown vs recovery) would test whether trend direction adds information beyond volatility magnitude.
4. **Investigate why calendar beats vol on sharpness.** The B_later cut captured the regime transition more crisply than the 20-day-window vol detector. Candidate explanations: (a) the transition was sharp enough that the 20-day window lagged it; (b) calendar timing aligned with an event the vol detector smooths over; (c) coincidence at this sample size. v0.5 could test a 10-day or 5-day vol window to reduce lag.
5. **Investigate why the lifecycle gap doesn't survive 20D.** v0.4 confirmed the 5D gap holds under regime conditioning, but 20D inverts in both regimes. v0.5 should test 10D and 15D horizons to find where the inversion happens.

---

## 9. Audit trail

v0.1 / v0.2 / v0.3 artifacts unmodified by v0.4 run. v0.4 artifacts:

| File | SHA-256 |
|---|---|
| `state_v04` | `6d191d18a71ae3bb75f004b4744be4d654ba52589b4d0fc7d090841292f768e4` |
| `lifecycle_v04` | `642d8cc080436bfa1908dd54112fb7dd28bfbce2e76edb9d4a667ac4ed708d2a` |
| `coverage_v04` | `7ad886f1f8009d5cfc6f98e89fda7084a680bc01bd39d29bedf2bc66c13a05a5` |
| `sensitivity_v04` | `ede027b2495751b8d4c3b229a089f36b530cd9982959e46b60decfcb266a20a7` |
| `regime_meta` | `6a60d99b445b350d2a8d60ddc598f88753c2896cc9a4febf91547e0fed48428e` |

Pre-registration locked 2026-05-30. Measurement run 2026-05-30. All predecessor artifacts read-only during v0.4 run.
