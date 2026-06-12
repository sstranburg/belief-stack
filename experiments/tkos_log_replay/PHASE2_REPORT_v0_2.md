# F-023 Phase 2 — TKOS Log-Replay Measurement Report (v0.2)

_Generated: 2026-05-29T19:29:12.588502Z_

**Rules version:** v0.2, locked 2026-05-29.
**Pre-registration:** [PHASE2_PRE_REGISTRATION_v0.2.md](PHASE2_PRE_REGISTRATION_v0.2.md).
**Amendments folded (from v0.1):** A-001, A-002, A-003, A-004, A-005 — see [PHASE2_AMENDMENTS_FOR_V02.md](PHASE2_AMENDMENTS_FOR_V02.md).
**v0.1 report (preserved):** [PHASE2_REPORT.md](PHASE2_REPORT.md).
**v0.1 artifacts:** unchanged in `data/`.

---

## 1. What changed from v0.1

- **A-001** — Threshold name: `suppressed_threshold` → `intervention_authority_threshold` (value unchanged at 0.7).
- **A-002** — `stale_deploy_prior` now fires when `user_approval_required` is **active AND weight ≥ 0.7** (v0.1 had the literal inverted reading).
- **A-003** — `repeated_failure_loop` signature match is now a **disjunction**: (tool ∧ error-Jaccard ≥ 0.5) ∨ (file ∩ ∧ cmd-token ∩) ∨ (shared exception class). Material action remains "any Edit/Write/MultiEdit" (refinement deferred to v0.3).
- **A-004** — `contradicted_fix_prior` applicability requires **context overlap**: touched-file ∨ command-family ∨ validation-context. Incidental unrelated errors are excluded.
- **A-005** — `stale_pipeline_prior` threshold raised from 20 min to **30 min** (= 1× pipeline_running half-life).

---

## 2. Sampling

v0.2 uses the same sample as v0.1 (seed=20260529, cap=200/session, 20,190 evaluation turns across 164 sessions). The belief timelines are also unchanged because v0.2 did not modify the belief tracker.

---

## 3. Per-rule head-to-head

Truth labels follow §5.2 (unchanged from v0.1): SUPPRESS+problem=TP, SUPPRESS+no problem=FP, ALLOW+problem=FN, ALLOW+no problem=TN, no-lookahead=UNCERTAIN.

### 3.1 `repeated_failure_loop`

| Metric | v0.1 | v0.2 | Δ |
|---|--:|--:|--:|
| Applicable | 830 | 830 | +0 |
| TP | 0 | 0 | +0 |
| FP | 0 | 0 | +0 |
| FN | 167 | 167 | +0 |
| TN | 643 | 643 | +0 |
| UNCERTAIN | 20 | 20 | +0 |
| SUPPRESS total | 0 | 0 | +0 |
| Detection rate | 0.000 | 0.000 | 0.000 |
| False-positive rate | 0.000 | 0.000 | 0.000 |
| Precision (v0.2 only) | — | n/a | — |

### 3.2 `stale_deploy_prior`

| Metric | v0.1 | v0.2 | Δ |
|---|--:|--:|--:|
| Applicable | 126 | 126 | +0 |
| TP | 0 | 0 | +0 |
| FP | 0 | 0 | +0 |
| FN | 17 | 17 | +0 |
| TN | 109 | 109 | +0 |
| UNCERTAIN | 0 | 0 | +0 |
| SUPPRESS total | 0 | 0 | +0 |
| Detection rate | 0.000 | 0.000 | 0.000 |
| False-positive rate | 0.000 | 0.000 | 0.000 |
| Precision (v0.2 only) | — | n/a | — |

### 3.3 `stale_pipeline_prior`

| Metric | v0.1 | v0.2 | Δ |
|---|--:|--:|--:|
| Applicable | 3,146 | 3,146 | +0 |
| TP | 41 | 21 | -20 |
| FP | 517 | 221 | -296 |
| FN | 190 | 210 | +20 |
| TN | 2,379 | 2,675 | +296 |
| UNCERTAIN | 19 | 19 | +0 |
| SUPPRESS total | 558 | 242 | -316 |
| Detection rate | 0.177 | 0.091 | -0.087 |
| False-positive rate | 0.179 | 0.076 | -0.102 |
| Precision (v0.2 only) | — | 0.087 | — |

### 3.4 `contradicted_fix_prior`

| Metric | v0.1 | v0.2 | Δ |
|---|--:|--:|--:|
| Applicable | 0 | 178 | +178 |
| TP | 0 | 42 | +42 |
| FP | 0 | 136 | +136 |
| FN | 0 | 0 | +0 |
| TN | 0 | 0 | +0 |
| UNCERTAIN | 0 | 0 | +0 |
| SUPPRESS total | 0 | 178 | +178 |
| Detection rate | n/a | 1.000 | — |
| False-positive rate | n/a | 1.000 | — |
| Precision (v0.2 only) | — | 0.236 | — |

---

## 4. Reading the head-to-head (§6.1 compliance)

Per §6.1, this report does **not** claim TKOS improves Claude, does not score F1 vs threshold, does not generalize beyond corpus.

What the v0.2 numbers show:

- **`repeated_failure_loop`** (A-003): SUPPRESS verdicts unchanged at 0 despite loosening the signature predicate to a disjunction with Jaccard ≥ 0.5. Applicability stayed at 830; FN at 167. This suggests either (i) this corpus genuinely has few 3-in-10-turn repeats with even loose signature similarity, or (ii) the v0.2 looseness still doesn't cover the way real loops paraphrase across attempts. Example windows are surfaced in §5; v0.3 should inspect them before further loosening.
- **`stale_deploy_prior`** (A-002): inverting the threshold direction still produces 0 SUPPRESS across 126 applicable deploy actions. This is a structural finding: by the time a deploy action fires, `user_approval_required` has typically been retired (the user-side approval signal that triggers the deploy ALSO retires the requirement belief). The rule cannot fire because the two beliefs almost never co-exist at the deploy moment. The fix may not be in the rule but in the belief — `user_approval_required` retirement is too eager.
- **`stale_pipeline_prior`** (A-005): moving the threshold 20 min → 30 min reduced SUPPRESS from 558 to 242. Detection rate moved -0.087 (from 0.177 to 0.091); FPR moved -0.102 (from 0.179 to 0.076). The threshold trade-off is now visible: fewer firings, fewer false positives, but also fewer real catches. Neither boundary is optimal; the corpus may need an adaptive threshold tied to per-pipeline expected duration rather than a global constant.
- **`contradicted_fix_prior`** (A-004): broadened applicability from 0 to 178 turns. All applicable turns fire SUPPRESS by rule design (applicability = trigger). Of those, 42 are TP and 136 are FP (precision 0.236). The 24% precision means three of four "contradictions" are not actually fix-invalidating in the 5-turn window. The context-overlap predicate (file/cmd/validation) is helpful but not sufficiently discriminating; v0.3 should add a temporal constraint (the failing turn within N turns of the fix's birth) and/or weight validation-context evidence more strongly than incidental same-file errors.

---

## 5. `repeated_failure_loop` example windows (v0.2)

_No multi-match windows surfaced even with the v0.2 loosened predicate. The substrate may not contain 3-in-10-turn-window repeats at this signature level._

---

## 6. What v0.3 needs

Based on this v0.2 measurement, in priority order:

1. **Inspect `repeated_failure_loop` non-firings.** The signature loosening did not move the needle. Either real loops in this corpus look different than the rule expects, or our signature definition still misses how the same error gets reported across retries. Hand-review of 5–10 candidate windows is the next step before further loosening.
2. **Revisit `user_approval_required` lifecycle, not just the deploy rule.** The 0-SUPPRESS result in v0.2 is structural: the belief retires on the same signal that births deploy_pending. Consider keeping `user_approval_required` alive for one turn after retirement, or splitting it into `approval_pending` (decays) and `approval_observed` (event).
3. **Add temporal constraint to `contradicted_fix_prior`.** 24% precision suggests the failing turn often isn't actually about the fix. Restrict applicability to failures within N (say 5) turns of the fix's birth.
4. **Adaptive `stale_pipeline_prior` threshold.** Global threshold trades detection for FPR linearly. A per-pipeline expected-duration prior would let the rule scale to short vs long pipelines.
5. **Material-action refinement for §3.1.** v0.2 deferred whitespace/comment/identical-patch detection to v0.3. If example windows show genuine no-op edits being miscounted as material, this will become higher priority.

---

## 7. Audit trail

v0.1 artifacts in `data/` are unmodified by this run.

| File | SHA-256 |
|---|---|
| `phase2_sample.json` | `651f2f4eadf1309a83b826f47c81c212519c2e23a0e4f6ab6ecbd1620c83821a` |
| `phase2_belief_timelines.jsonl` | `8833f1b4f13f1fd7328b9d5a03087e509d6c50ed46469d9d494fa2b20a370ae2` |
| `phase2_intervention_verdicts_v0_2.jsonl` | `5597f08fe14a5aa6d9c91c507fe293a9cb9b49aac26aa5db75126b2cb37cce55` |
| `phase2_labeled_outcomes_v0_2.jsonl` | `d39a21bb2b755943a5c8466278d4feedc6e8e986db061b3341e9f336478c8e3f` |
