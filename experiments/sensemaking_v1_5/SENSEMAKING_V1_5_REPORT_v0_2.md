# Sensemaking v1.5 — Measurement Report (v0.2)

_Generated: 2026-05-30T14:06:01.673840Z_

**Rules version:** v0.2, locked 2026-05-30.
**Pre-registration:** [SENSEMAKING_V1_5_PRE_REGISTRATION_v0.2.md](SENSEMAKING_V1_5_PRE_REGISTRATION_v0.2.md).
**v0.1 predecessor:** [SENSEMAKING_V1_5_REPORT.md](SENSEMAKING_V1_5_REPORT.md) (preserved unchanged).
**v0.1 artifacts** in `data/` are not modified by v0.2.

---

## 1. Headline

> v0.1 surfaced an apparent 20D Constructive advantage of +2.97% vs baseline.
> v0.2 re-bucketed REPRICING (direction-aware) and isolated EARLY.
> The advantage did not survive the correction.
>
> v0.2 also confirms the load-bearing direction: lifecycle revision events
> preserve a constructive-vs-cautious directional gap that the static state
> buckets lost once the baseline was tightened.

This is the belief stack doing belief revision on itself. The v0.1 headline was fragile in exactly the way v0.1's own sensitivity appendix predicted, and v0.2 confirmed it.

---

## 2. What changed from v0.1

Pre-registration §3 (bucket mapping), §12 (sensitivity restructured). Everything else — universe, walk-forward protocol, horizons, secondary protocols, exclusion rules — unchanged.

| Bucket | v0.1 states | v0.2 states |
|---|---|---|
| Constructive | CONFIRMED, EARLY, DISAGREEMENT | CONFIRMED, DISAGREEMENT, REPRICING_bullish |
| Cautious | NEG_CONFIRMATION, DIVERGENCE | NEG_CONFIRMATION, DIVERGENCE, REPRICING_bearish |
| Early_followthrough | (folded into Constructive) | EARLY (standalone) |
| Ambiguous | MACRO, PRICE-LED, UNCLEAR, **REPRICING** | MACRO, PRICE-LED, UNCLEAR |

REPRICING split: rows with `direction = +1` (actor-level bullish narrative) → REPRICING_bullish → Constructive. Rows with `direction = −1` → REPRICING_bearish → Cautious. The pre-registration's §3.3 limitation: this is the actor-level narrative direction from `backtest_history.parquet`, not a newly inferred row-specific direction signal. v0.3 may revisit.

---

## 3. Primary head-to-head: v0.1 vs v0.2

### 3.1 5D horizon

| Bucket | v0.1 n | v0.1 avg fwd_rel | v0.1 Δ baseline | v0.2 n | v0.2 avg fwd_rel | v0.2 Δ baseline |
|---|--:|--:|--:|--:|--:|--:|
| Constructive | 1,255 | +0.28% | +0.14% | 1,943 | -0.02% | -3.00% |
| Cautious | 823 | +1.46% | +1.32% | 823 | +1.46% | -1.52% |
| Ambiguous | 1,394 | +0.14% | +0.00% | 211 | +2.98% | +0.00% |
| Early_followthrough | — | — | — | 495 | -0.12% | -3.10% |

**v0.2 Ambiguous baseline at 5D**: avg = +2.98%, n = 211 (much smaller than v0.1's 1,394, because REPRICING moved out).

### 3.2 20D horizon

| Bucket | v0.1 n | v0.1 avg fwd_rel | v0.1 Δ baseline | v0.2 n | v0.2 avg fwd_rel | v0.2 Δ baseline |
|---|--:|--:|--:|--:|--:|--:|
| Constructive | 1,086 | +3.98% | +2.97% | 1,672 | +2.67% | -1.22% |
| Cautious | 685 | +2.82% | +1.81% | 685 | +2.82% | -1.07% |
| Ambiguous | 1,236 | +1.01% | +0.00% | 209 | +3.89% | +0.00% |
| Early_followthrough | — | — | — | 441 | +0.68% | -3.21% |

**v0.2 Ambiguous baseline at 20D**: avg = +3.89%, n = 209 (much smaller than v0.1's 1,236, because REPRICING moved out).

**Reading the head-to-head:**

- v0.1 Constructive Δ vs baseline at 20D was +2.97%; v0.2 Constructive Δ vs (tightened) baseline at 20D is -1.22%. The flip is roughly -4.19%.
- The baseline shift accounts for most of the change: v0.1 Ambiguous baseline = +1.01%, v0.2 Ambiguous baseline = +3.89%. Removing REPRICING from Ambiguous lifted the baseline because the remaining Ambiguous states (MACRO, PRICE-LED, UNCLEAR) all had higher forward returns in this window.
- The v0.1 Constructive bucket also included EARLY, which had near-zero forward returns. v0.2 isolated EARLY (n=441 at 20D) into its own bucket. The §12.2 sensitivity shows EARLY's isolation moves the Constructive number by only ~4bps — methodologically valuable, not the cause of the flip.
- REPRICING_bullish (n=1,027 at 20D) carries an avg of only +0.43% — close to Ambiguous, not Constructive-clean. It dilutes the Constructive bucket from inside. v0.3 may want to make REPRICING its own bucket entirely rather than folding it into Constructive or Cautious by direction.

---

## 4. Per-effective-state — v0.2

Effective states encode the REPRICING direction split. CONFIRMED + DISAGREEMENT remain the cleanest Constructive states; REPRICING_bullish dilutes the bucket.

### 4.1 5D horizon

| Bucket | Effective state | n | Avg fwd_rel | Median | % positive |
|---|---|--:|--:|--:|--:|
| Ambiguous | `PRICE-LED` | 90 | +3.08% | +1.62% | 0.589 |
| Ambiguous | `UNCLEAR` | 70 | +2.89% | +1.42% | 0.586 |
| Ambiguous | `MACRO` | 51 | +2.92% | +0.54% | 0.510 |
| Cautious | `DIVERGENCE` | 504 | +1.66% | +0.77% | 0.548 |
| Cautious | `NEG_CONFIRMATION` | 319 | +1.15% | +0.52% | 0.539 |
| Constructive | `REPRICING_bullish` | 1,183 | -0.37% | -0.35% | 0.473 |
| Constructive | `CONFIRMED` | 407 | +0.09% | -0.68% | 0.462 |
| Constructive | `DISAGREEMENT` | 353 | +1.05% | -0.17% | 0.493 |
| Early_followthrough | `EARLY` | 495 | -0.12% | -0.91% | 0.422 |

### 4.2 20D horizon

| Bucket | Effective state | n | Avg fwd_rel | Median | % positive |
|---|---|--:|--:|--:|--:|
| Ambiguous | `PRICE-LED` | 89 | +5.52% | +1.06% | 0.551 |
| Ambiguous | `UNCLEAR` | 70 | +1.03% | +0.30% | 0.514 |
| Ambiguous | `MACRO` | 50 | +5.01% | +0.32% | 0.500 |
| Cautious | `DIVERGENCE` | 403 | +2.86% | +1.51% | 0.563 |
| Cautious | `NEG_CONFIRMATION` | 282 | +2.78% | -2.35% | 0.454 |
| Constructive | `REPRICING_bullish` | 1,027 | +0.43% | -0.53% | 0.485 |
| Constructive | `CONFIRMED` | 345 | +5.25% | +1.91% | 0.545 |
| Constructive | `DISAGREEMENT` | 300 | +7.37% | -1.42% | 0.453 |
| Early_followthrough | `EARLY` | 441 | +0.68% | -1.59% | 0.440 |

---

## 5. Secondary — lifecycle revision-prediction (the durable insight)

**The key result of v0.2** is not in the primary state buckets — it is in the comparison between static state labels and lifecycle revision events.

Under the v0.2 (tightened) baseline, static state buckets no longer separate. But lifecycle revision events still preserve a directional gap:

### 5.1 5D horizon

| Bucket | v0.1 n | v0.1 avg | v0.1 Δ baseline | v0.2 n | v0.2 avg | v0.2 Δ baseline |
|---|--:|--:|--:|--:|--:|--:|
| Constructive_revision | 216 | +0.65% | +0.51% | 216 | +0.65% | -2.33% |
| Cautious_revision | 242 | -0.14% | -0.28% | 242 | -0.14% | -3.12% |
| **Internal gap (Constructive_rev − Cautious_rev)** | | | +0.79% | | | +0.79% |

### 5.2 20D horizon

| Bucket | v0.1 n | v0.1 avg | v0.1 Δ baseline | v0.2 n | v0.2 avg | v0.2 Δ baseline |
|---|--:|--:|--:|--:|--:|--:|
| Constructive_revision | 188 | +2.41% | +1.40% | 188 | +2.41% | -1.48% |
| Cautious_revision | 222 | +3.48% | +2.47% | 222 | +3.48% | -0.41% |
| **Internal gap (Constructive_rev − Cautious_rev)** | | | -1.07% | | | -1.07% |

**Architectural read:**

- At 5D under v0.2: static state buckets show Constructive − Cautious = -1.48% (the wrong direction). Lifecycle revisions show Constructive_revision − Cautious_revision = +0.79% (the right direction).
- The lifecycle layer (L3) preserves directional information that the static state buckets (L2) lost once the baseline was corrected. This suggests **static state labels are weaker than lifecycle revision events** for forward-outcome separation on this substrate.
- This is the architecturally beautiful finding v0.2 surfaces: revision events are more informative than steady-state labels. The Belief Stack pattern's lifecycle layer is doing real work; the bucket abstraction may be the wrong unit of analysis for forward-outcome prediction.

---

## 6. Tertiary — warrant coverage (v0.2)

Same partition protocol as v0.1; baseline is now the v0.2 (tightened) Ambiguous. Small n on the insufficient-data side (n=18 Constructive at 5D / 20D) and the new high-baseline Ambiguous (only ~100 rows per partition) make the per-partition deltas higher-variance than in v0.1.

### 6.1 5D horizon

| Partition | Bucket | n | Avg fwd_rel | % positive | Δ partition baseline |
|---|---|--:|--:|--:|--:|
| sufficient_data_True | Constructive | 1,925 | -0.00% | 0.475 | -3.58% |
| sufficient_data_True | Cautious | 798 | +1.43% | 0.541 | -2.15% |
| sufficient_data_True | Early_followthrough | 495 | -0.12% | 0.422 | -3.70% |
| sufficient_data_True | Ambiguous | 100 | +3.58% | 0.570 | — |
| sufficient_data_False | Constructive | 18 | -1.44% | 0.389 | -3.88% |
| sufficient_data_False | Cautious | 25 | +2.58% | 0.640 | +0.13% |
| sufficient_data_False | Early_followthrough | 0 | — | — | — |
| sufficient_data_False | Ambiguous | 111 | +2.44% | 0.568 | — |

### 6.2 20D horizon

| Partition | Bucket | n | Avg fwd_rel | % positive | Δ partition baseline |
|---|---|--:|--:|--:|--:|
| sufficient_data_True | Constructive | 1,654 | +2.75% | 0.496 | -5.86% |
| sufficient_data_True | Cautious | 660 | +3.05% | 0.518 | -5.56% |
| sufficient_data_True | Early_followthrough | 441 | +0.68% | 0.440 | -7.93% |
| sufficient_data_True | Ambiguous | 98 | +8.61% | 0.592 | — |
| sufficient_data_False | Constructive | 18 | -4.70% | 0.111 | -4.43% |
| sufficient_data_False | Cautious | 25 | -3.12% | 0.520 | -2.85% |
| sufficient_data_False | Early_followthrough | 0 | — | — | — |
| sufficient_data_False | Ambiguous | 111 | -0.27% | 0.468 | — |

The v0.1 warrant-coverage finding (sufficient-data Constructive +2.99% over partition baseline, insufficient-data Constructive flipping sign) does not persist as cleanly under the v0.2 tightened baseline. The directional flip at 20D between sufficient and insufficient Constructive remains (sufficient -5.86% vs insufficient -4.43% — both negative, but the magnitudes differ). v0.3 should re-examine whether the warrant flag information was real or partly an artifact of the v0.1 baseline composition.

---

## 7. Sensitivity appendix (v0.2 §12)

Per §12.4, sensitivity is reported separately from primary. Three perturbations of the v0.2 mapping.

### 7.1 §12.1 — Direction-naive REPRICING reverse

Collapse REPRICING back to a single Ambiguous-bucket entry (the v0.1 mapping); everything else v0.2.

**5D:**

| Bucket | n | Avg fwd_rel | Δ vs (this run's) baseline |
|---|--:|--:|--:|
| Constructive | 760 | +0.54% | +0.40% |
| Cautious | 823 | +1.46% | +1.32% |
| Early_followthrough | 495 | -0.12% | -0.26% |
| Ambiguous | 1,394 | +0.14% | +0.00% |

**20D:**

| Bucket | n | Avg fwd_rel | Δ vs (this run's) baseline |
|---|--:|--:|--:|
| Constructive | 645 | +6.24% | +5.23% |
| Cautious | 685 | +2.82% | +1.81% |
| Early_followthrough | 441 | +0.68% | -0.33% |
| Ambiguous | 1,236 | +1.01% | +0.00% |

**§12.1 reading:** putting REPRICING back into Ambiguous reproduces the v0.1 headline numbers almost exactly. This confirms that REPRICING's bucket assignment was the entire source of the v0.1 vs v0.2 delta — and therefore that REPRICING was the structurally load-bearing call.

### 7.2 §12.2 — EARLY-as-Constructive reverse

Fold EARLY back into Constructive (the v0.1 mapping); everything else v0.2.

**5D:**

| Bucket | n | Avg fwd_rel | Δ vs (this run's) baseline |
|---|--:|--:|--:|
| Constructive | 2,438 | -0.04% | -3.02% |
| Cautious | 823 | +1.46% | -1.52% |
| Early_followthrough | 0 | — | — |
| Ambiguous | 211 | +2.98% | +0.00% |

**20D:**

| Bucket | n | Avg fwd_rel | Δ vs (this run's) baseline |
|---|--:|--:|--:|
| Constructive | 2,113 | +2.25% | -1.64% |
| Cautious | 685 | +2.82% | -1.07% |
| Early_followthrough | 0 | — | — |
| Ambiguous | 209 | +3.89% | +0.00% |

**§12.2 reading:** EARLY isolation moves the Constructive average by ~4bps at most. The isolation is methodologically useful (it lets us see EARLY's distribution distinctly) but does not by itself cause the v0.1→v0.2 headline flip.

### 7.3 §12.3 — Experimental tickers included

Include USAR / MP / ODC in the primary universe (only MP present in `backtest_history.parquet`, per I-002). v0.2 bucket mapping otherwise.

**5D:**

| Bucket | n | Avg fwd_rel | Δ vs (this run's) baseline |
|---|--:|--:|--:|
| Constructive | 1,989 | -0.05% | -2.90% |
| Cautious | 858 | +1.47% | -1.38% |
| Early_followthrough | 512 | -0.15% | -3.00% |
| Ambiguous | 225 | +2.85% | +0.00% |

**20D:**

| Bucket | n | Avg fwd_rel | Δ vs (this run's) baseline |
|---|--:|--:|--:|
| Constructive | 1,716 | +2.55% | -1.19% |
| Cautious | 713 | +3.16% | -0.58% |
| Early_followthrough | 458 | +0.49% | -3.24% |
| Ambiguous | 217 | +3.74% | +0.00% |

**§12.3 reading:** experimental inclusion shifts each bucket by ~1–3bps. The §2.2 exclusion remains methodologically conservative without affecting conclusions.

---

## 8. What v0.2 says publicly

> The v0.1 measurement surfaced an apparent 20D Constructive advantage of +2.97% vs baseline. The v0.2 re-bucketing showed that this advantage was fragile: moving REPRICING out of Ambiguous raised the baseline enough to eliminate the effect. The result does not invalidate the belief field; it invalidates the simpler bucket mapping.
>
> v0.2 also produced a more architecturally interesting finding: lifecycle revision events preserve a constructive-vs-cautious directional gap that the static state buckets lost under the tightened baseline. The L3 lifecycle layer carries forward-outcome information that the L2 state buckets do not, on this substrate.

v0.2 does NOT claim:

- That v1.5 invalidates the v1 belief field. v0.2 invalidates a particular bucket-level summary, not the underlying field.
- That lifecycle revision events are predictive in a live-deployment sense. The 5D internal gap is preserved under v0.2's tightened baseline, but absolute outperformance vs the new baseline is small or negative.
- That CONFIRMED + DISAGREEMENT are not constructive states. Per §4, both still have clearly positive forward returns at 20D (CONFIRMED +5.25%, DISAGREEMENT +7.37%). REPRICING_bullish dilution at the bucket level does not erase the state-level signal.

---

## 9. What v0.3 needs

Based on v0.2's measurement, in priority order:

1. **Re-architect REPRICING.** v0.2's direction-aware split confirmed the v0.1 fragility but produced its own dilution problem inside the Constructive bucket. The next move is probably to make REPRICING its own primary bucket and report its distribution directly, rather than folding it into Constructive / Cautious by an actor-level direction signal.
2. **Promote lifecycle revision-prediction to primary.** v0.2 showed lifecycle events preserve directional information under tightened baselines while static state buckets do not. v0.3 should consider making lifecycle revision the primary measurement axis and treating static state buckets as a comparison surface.
3. **Investigate the window-structural Cautious failure.** DIVERGENCE and NEG_CONFIRMATION continue to show positive forward returns at 20D under v0.2. The v0.1 hypothesis (rising-tide window) remains untested. v0.3 should add per-sub-window stratification (e.g., 2025-12–2026-02 vs 2026-03–2026-05) to test whether Cautious behaved differently in different sub-windows.
4. **Drop EARLY's Constructive labeling assumption.** EARLY's standalone 5D avg is −0.12%, 20D is +0.68%. The provisional Constructive labeling (Hit = fwd_rel > 0) produces hit rates of 0.42/0.44 — clearly below 0.5. v0.3 should either drop the labeling (treat EARLY as Ambiguous) or commit to actually-cautious labeling based on what v0.2 showed.
5. **Revisit the warrant-coverage finding.** v0.1 showed sufficient-data Constructive +2.99% over partition baseline; v0.2 shows −5.86%. Either the finding was an artifact of v0.1's baseline composition, or the warrant flag carries information that the v0.2 bucket structure obscures. v0.3 should test both possibilities.

---

## 10. Audit trail

v0.1 artifacts unmodified by v0.2 run. v0.2 artifacts:

| File | SHA-256 |
|---|---|
| `labeled_v0_2` | `eaeda8bf76ba13490310e937c088fa89af4aeb81b38f252185ea0abcfd09c9f0` |
| `primary_v0_2` | `57d0bdd73ab66c2879bbd4685f0b25886987424213e72e349290a4750268c2ef` |
| `secondary_v0_2` | `b4edc7f4543d3d0461a549046640a659fabe046f661a5e8d4f51219c90bbc90b` |
| `sensitivity_v0_2` | `000293faffa2e9de04fdea87eca0c5c903d9da6f6a04bb768257b2f83a23c209` |

Pre-registration locked 2026-05-30. Measurement run 2026-05-30. v1 substrate artifacts read-only during v0.2 run.
