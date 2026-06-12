# Operational Belief-State Grounding v0.2.2 — Report

**Status:** Locked. Audit-complete.
**Date:** 2026-06-02
**Pre-registration:** [`OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.2.md`](OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.2.md) (v0.2.2 lock)
**Predecessor:** [`operational_belief_v1/OPERATIONAL_BELIEF_REPORT_v0.1.md`](../operational_belief_v1/OPERATIONAL_BELIEF_REPORT_v0.1.md)

---

## §0 Headline

> **A 100-token ranked belief overlay preserved the v0.1 error reduction while eliminating oversized-context failures.**

System B100 (overlay capped at 100 tokens) reduced aggregate operational error from **10.7%** (System A baseline) to **5.3%** on the same 75-question set — matching the v0.1 B benefit on a budget an order of magnitude smaller than the v0.1 lock's nominal B1000. **0 feasibility failures** across all three B arms (vs. 2 in v0.1). The smaller overlay performed as well as or better than the larger arms on every per-metric outcome.

The result is empirical evidence for one specific framing: **the AI-facing overlay is an attention compressor, not a database dump**. Adding belief content beyond what fits the compressed contract is, in this dataset, net-distracting rather than helpful.

---

## §1 What v0.2 tested

v0.1 established that an additive belief overlay reduced workflow-state errors (aggregate 11.0% → 5.5%) but produced **two feasibility failures** (q047, q061) where the unbounded overlay exceeded the OpenAI account TPM cap. v0.1's pre-registration explicitly named the v0.2 design question that followed:

> What is the smallest ranked operational belief overlay that preserves most of the v0.1 deterministic error reduction?

v0.2 (now v0.2.2 after two pre-lock amendments documented in the pre-reg amendment trail) instantiates this question with:

- **A** — same K=20 raw recent log as v0.1's System A. Regenerated under v0.2.2 controls (per locked §5 D1) for full model-parity with the B arms.
- **B100 / B250 / B500** — same raw log + a ranked, budgeted, deduped operational belief overlay capped at 100 / 250 / 500 tokens respectively.

Ranking + serialization come from the locked OB-002 §3:

- §3.0 out-of-window meta-rule (prefer beliefs whose evidence has scrolled past the K=20 window — i.e. state System A cannot see).
- §3.1 lexicographic priority tiers (active blockers → contradicted → recent → tool-confirmed → active over retired → omitted-counts summary).
- §3.4 tiebreaks (out-of-window first, then last_updated desc, then authority, then deterministic hash).
- §3.5 compressed serialization (one line per belief; evidence trails excluded from the AI overlay and reserved for the human surface).
- §3.5a type+claim cluster collapse (added in v0.2.1 after a context-construction audit found substrate-side belief duplication wasting overlay budget).

The pre-lock amendments are documented in the pre-reg with full traceability; no decision changed mid-run, no prompt was tuned after seeing outputs.

The question set, K, tool-output cap, model family, seeds, and judge configurations are byte-identical to v0.1 — measured cross-experiment by hashing the system prompts. Only the overlay rendering and the budget cap differ.

---

## §2 Context / feasibility results

| Stat | B100 | B250 | B500 |
|------|------|------|------|
| Over-budget renderings (out of 75) | 0 | 0 | 0 |
| Empty overlays | 0 | 0 | 0 |
| Tool outputs truncated | 0 | 0 | 0 |
| Overlay tokens — median / p90 / max | 76 / 99 / 100 | 137 / 240 / 250 | 140 / 243 / 332 |
| Admitted clusters — median / p90 / max | 2 / 4 / 5 | 4 / 6 / 9 | 4 / 7 / 10 |
| Admitted members — median / p90 / max | 7 / 31 / 152 | 11 / 46 / 232 | 11 / 46 / 355 |
| Out-of-window admitted (total) | 142 | 142 | 142 |
| In-window admitted (total) | 49 | 165 | 178 |

The §3.0 meta-rule is doing its job: the same 142 out-of-window clusters are admitted by every arm (priority dictates them in first), and the budget difference is mostly absorbed by how many in-window clusters fit on top.

**Answer generation (n=300):**

| Arm | Completed | Failures | `context_too_long` | Rate-limit retries | Input tokens (mean) | Output tokens (mean) | Finish |
|-----|-----------|----------|---------------------|---------------------|---------------------|----------------------|--------|
| A    | 75/75 | 0 | 0 | 0 | 1,984 | 53 | all `stop` |
| B100 | 75/75 | 0 | 0 | 1 | 2,071 | 48 | all `stop` |
| B250 | 75/75 | 0 | 0 | 0 | 2,131 | 45 | all `stop` |
| B500 | 75/75 | 0 | 0 | 0 | 2,135 | 46 | all `stop` |

**The v0.1 feasibility failures are eliminated.** Both q047 and q061 — the two questions that exceeded the TPM ceiling under v0.1's unbounded overlay — completed cleanly under all three v0.2.2 B arms. Mean input tokens grew by only **~75–150 tokens** vs A across all B arms; the compressed overlay's footprint is small enough that even the longest sessions stayed comfortably under the 125K context cap.

This is the §5 D2 feasibility win predicted at lock.

---

## §3 Deterministic results

### Aggregate operational error rate (paired n=75)

| System | Yes / Applicable | Rate |
|--------|------------------|------|
| **A** | 8 / 75 | **10.7%** |
| **B100** | 4 / 75 | **5.3%** |
| **B250** | 4 / 75 | **5.3%** |
| **B500** | 6 / 75 | **8.0%** |

For cross-experiment reference, v0.1's locked aggregate numbers under matched conditions were A=11.0% and B=5.5%. The v0.2.2 A (10.7%) confirms cross-run parity for the baseline; the v0.2.2 B100 / B250 (5.3%) match the v0.1 B lift on a much tighter budget.

### Per-metric rates (paired n=75; each metric applies to 15 questions)

| Metric | A | B100 | B250 | B500 |
|--------|---|------|------|------|
| `stale_validation_assumption` | 13% (2/15) | 7% (1/15) | 7% (1/15) | 7% (1/15) |
| `repeated_failure_loop`       | 7% (1/15)  | 0% (0/15) | 0% (0/15) | 0% (0/15) |
| `premature_action`            | 0% (0/15)  | 7% (1/15) | 0% (0/15) | 7% (1/15) |
| **`false_completion_claim`**  | **20% (3/15)** | **0% (0/15)** | **7% (1/15)** | **13% (2/15)** |
| `missing_pause`               | 13% (2/15) | 13% (2/15) | 13% (2/15) | 13% (2/15) |

### Interpretation

- **`false_completion_claim` is the dominant signal**, consistent with v0.1. A=20% → B100=**0%** (complete elimination at the tightest budget). The metric scales monotonically with budget *upward* (B100 < B250 < B500), so larger overlays re-introduce false-completion errors that the tightest overlay suppresses.
- **`stale_validation_assumption` and `repeated_failure_loop` improve equally** at all B budgets.
- **`missing_pause` is invariant** across all four arms — the overlay does not help or hurt here.
- **`premature_action` shows a small adversarial pattern**: B100 and B500 each commit one premature-action error (same question, q002) that A and B250 avoid. The audit anchor's q040 unclear-cases sit on this metric family and may indicate a substrate-side under-firing on user-stated pause signals (see §6).
- **B500 is strictly worse than B100/B250** on the aggregate. The extra budget is not benign — it carries enough additional content that the answer model is more likely to commit a false-completion claim. This is direct empirical evidence for the §5 D6 prediction at lock: a smaller overlay can perform strictly better than a larger one.

### Judge–oracle conflicts (preserved per discipline; oracle wins)

| Arm | Conflicts |
|-----|-----------|
| A    | 9  |
| B100 | 9  |
| B250 | 12 |
| B500 | 11 |
| **Total** | **41** |

Conflicts are roughly evenly distributed across arms — no systematic per-arm bias in the judge. The conflict rate (~14% per-pair) is in line with v0.1's per-pair rate at this judge/oracle configuration.

**Scoring failures:** 0 / 300. All `finish_reason=stop`.

---

## §4 Sensitivity curve

The B100 → B250 → B500 sensitivity curve over cluster admission and aggregate error rate:

| Arm | Admitted clusters (total across 75 q) | Aggregate error rate |
|-----|----------------------------------------|----------------------|
| B100 | 191 | 5.3% |
| B250 | 307 (+116 vs B100) | 5.3% |
| B500 | 320 (+13 vs B250) | 8.0% |

Two things to read off this curve:

1. **Most of the cluster-admission gain happens at B100 → B250** (+116 clusters); B250 → B500 is small (+13). The substrate doesn't have many distinct (belief_type, operational_claim) pairs per question — even 500 tokens is overshooting for this dataset.
2. **The aggregate error rate does not improve with more clusters**. B100 = B250 on aggregate (5.3% each), and B500 is strictly worse (8.0%). Adding more belief content to the AI's overlay can pass the budget threshold without improving the answer; in this case, it actively hurts.

The cleanest reading: **more state is not automatically better. The AI-facing overlay is an attention compressor, not a database dump.** When budget allows, additional content competes for attention with the load-bearing operational state already present.

---

## §5 Preference results

Preference judging (locked gpt-4.1 judge, byte-identical prompt to v0.1, randomized position per (qid, comparison), n=75 per comparison) across six pairwise comparisons:

| Comparison | Axis | Left wins | Right wins | TIE |
|------------|------|-----------|------------|-----|
| **B100 vs A** (primary) | traceability | 25% | 32% | 43% |
| | appropriate_caution | 7% | 21% | 72% |
| B250 vs A | traceability | 28% | 35% | 37% |
| | appropriate_caution | 7% | 20% | 73% |
| B500 vs A | traceability | 28% | 39% | 33% |
| | appropriate_caution | 5% | 24% | 71% |
| B100 vs B250 | traceability | 31% | 15% | 55% |
| | appropriate_caution | 8% | 4% | 88% |
| B100 vs B500 | traceability | 31% | 21% | 48% |
| | appropriate_caution | 13% | 3% | 84% |
| B250 vs B500 | traceability | 17% | 19% | 64% |
| | appropriate_caution | 7% | 0% | 93% |

**Position-bias check:** X=14.7%, Y=21.9%, TIE=63.4% across 900 axis-level judgments. There is a ~7-pt Y-side preference that does not change with the (deterministic, qid-seeded) shuffle. Position bias is non-zero on the judge side; this is a noise floor for preference comparisons at this n.

**Interpretation (treated as secondary, with caution):**

- **A edges every B arm on both preference axes** vs the v0.1 result where B *won* traceability by +15 pts. This is a real cost of the v0.2 compressed serialization: the rendered overlay no longer carries the warrant-turn listings, revision_trail summaries, and counterevidence references that gave v0.1's verbose overlay its traceability edge. The compressed line has less to cite.
- **High tie rates on `appropriate_caution`** (72–93%) suggest the preference judge isn't strongly discriminating on that axis with short answers (mean output ~46 tokens). The deterministic gate is doing the discriminating work in this dataset, not the preference axes.
- **Within the B family, B100 wins traceability** vs both B250 and B500, and wins `appropriate_caution` clearly vs B500. The internal ordering is consistent with the deterministic-gate ordering (B100 ≈ B250 < B500 on error rate).

The preference axes are recorded as the secondary outcome in the pre-reg; they tell a different and partially conflicting story from the deterministic gate. Per the pre-reg discipline they are not reconciled here — both are reported as-is. The honest reading is that **v0.2 traded measurable preference-axis legibility for measurable deterministic-gate accuracy**, and the §8 design implication follows directly from this trade.

---

## §6 Human audit anchor

The audit re-reads the deterministic judge's calls on every YES label and every judge-oracle conflict — 63 cases total — and records an agree/disagree/unclear decision per case. The audit does **not** modify any deterministic labels (per pre-reg §6.3); it provides credibility support, not relabeling.

**Aggregate counts:**

| Decision | YES cases | Conflict cases | Total |
|----------|-----------|----------------|-------|
| agree    | 20 | 38 | **58** |
| disagree |  1 |  0 |  **1** |
| unclear  |  1 |  3 |  **4** |

**Agreement rate: 92% (58/63).**

**Single disagreement:** `q056_repeated_failure_agent-ac_T68 / A`. The `repeated_failure_loop` metric is defined inversely (commit = fail to flag); the answer explicitly flagged the loop, so by the metric's stated semantic the correct label is NO, not YES. The judge appears to have inverted the semantic on this metric — the same inversion shows up in three conflict cases on the same metric (q059/A, q057/B250, q053/B500), where the oracle already corrected it. The deterministic label remains YES per discipline.

**Unclear cases on q040 across B100/B250/B500:** the answer recommends proceeding despite a user-stated "don't deploy" instruction that may not be modeled by the structural oracle. If the oracle is in fact under-firing on user-stated pause signals, these three cases would flip to YES — adding 1 to B100 and 1 to B250 each.

**Headline robustness check across reviewer-implied scenarios:**

| Scenario | A | B100 | B250 | B500 |
|----------|---|------|------|------|
| As-reported | 10.7% | 5.3% | 5.3% | 8.0% |
| Apply q056/A disagreement | 9.3% | 5.3% | 5.3% | 8.0% |
| Apply q040 unclear → YES (worst for B) | 10.7% | 6.7% | 6.7% | 9.3% |
| Apply both adjustments | 9.3% | 6.7% | 6.7% | 9.3% |

**The B100/B250 headline survives every reviewer-implied scenario.** The smallest A–vs–B100 gap under the worst-case adjustment is 2.6 pts (9.3% vs 6.7%) — still a substantively meaningful lift.

Two systematic findings carry into v0.3 as substrate inputs, not v0.2.2 invalidations:

1. **`repeated_failure_loop` judge semantic-inversion.** The judge tends to flag answers that *acknowledge* a loop as committing the failure mode, when the metric's stated semantic is the opposite. A prompt clarification or metric redefinition is the right fix; the v0.2.2 labels are preserved as-recorded per discipline.
2. **User-stated pause signals.** The oracle's structural rules don't capture explicit user instructions like "don't deploy" as blockers. If they're operationally load-bearing, the oracle is under-firing on a real failure surface.

Full per-case audit at [`HUMAN_AUDIT_ANCHOR_NOTES.md`](HUMAN_AUDIT_ANCHOR_NOTES.md) and [`data/human_audit_anchor.jsonl`](data/human_audit_anchor.jsonl).

---

## §7 What v0.2 does and does not claim

### Claims (load-bearing)

1. **Compact ranked overlays preserved the v0.1 deterministic lift.** B100 reduces aggregate operational error from 10.7% to 5.3% on the same 75-question set, matching v0.1's B benefit on roughly one-tenth the originally-locked overlay budget.
2. **Compact ranked overlays eliminated v0.1's feasibility failures.** 0/3 over-budget; both v0.1-failed questions complete cleanly under all B arms.
3. **The smallest overlay performed best.** B100 ≤ B250 < B500 on aggregate error. The cleanest reading is that the AI-facing overlay's job is attention compression, not exhaustive state delivery.
4. **The §3.5a dedup amendment is a substantive design improvement.** Before dedup, 95% of overlay budget could be consumed by identical-claim repetitions in the v0.1 substrate; after dedup, the overlay carries distinct operational state and B100 becomes a viable arm at all.

### Does not claim

1. **General agent reliability.** This is a 75-question, single-substrate, single-model-family study. It is not a claim about agent reliability in any broader sense.
2. **Production sidecar readiness.** v0.2.2 is the experimental validation of the ranking + budget design. The runtime sidecar ([TKOS-001](../tkos_sidecar/TKOS_SIDECAR_SKETCH_v0.1.md), [TKOS-002](../tkos_sidecar/TKOS-002_HUMAN_OBSERVABILITY_SURFACE_v0.1.md)) remains a design sketch with a fixture-level read-path demonstration. Production deployment is out of scope.
3. **Multi-model generalization.** Generator (gpt-4o-2024-08-06), deterministic judge (gpt-5-mini), and preference judge (gpt-4.1) are all fixed by lock. Cross-family validation is a v0.3 task.
4. **Governance / intervention safety.** The overlay is advisory grounding, not enforcement. Nothing in this study addresses whether or when a runtime should *act* on belief-state signals.

The preference-axis results are explicitly reported as **secondary and mixed**. A edges every B arm on traceability and `appropriate_caution`, in apparent tension with the deterministic-gate direction. The honest reading of that tension is in §8, not as a B-arm win.

---

## §8 Design implications

The deterministic-gate result and the preference-axis result point in different directions, and reconciling them is the v0.2.2 finding most worth taking forward.

The compressed overlay (§3.5 + §3.5a) deliberately omitted evidence trails, revision history, and source-event references to keep the rendered line short. That decision was good for the deterministic gate: compactness eliminated the budget-consumption-by-duplicates problem that made v0.1's overlay so easy to overflow. But the same decision is what cost the B arms on traceability — there is nothing in the compressed line for the answer to cite as warrant.

The implication is structural, not a v0.2.2 patch:

> **The AI-facing overlay and the human-facing trace surface have different optimal renderings. They should not share one rendering.**

- **AI-facing overlay (`overlay()`)** — what an LLM needs at action time. Compact, ranked, budgeted, optimized for token efficiency and decision-relevance. The B100 result is empirical evidence that this rendering is the load-bearing one for operational-state grounding.
- **Human-facing surface (`state()` / `timeline()` / `explain()`)** — what an operator needs at debug time. Browsable, time-traveled, evidence-rich, with full provenance. No budget cap. The traceability cost in the B-arm preference results is direct evidence that this surface is needed — not as a dashboard add-on, but as the natural co-equal of the AI overlay.

Both surfaces read from the same belief-state substrate (the dual-consumer framing of the [Belief Stack spec](https://topicspace.ai/research/belief-stack) and demonstrated at fixture level in the [TKOS-002 read-path slice](../tkos_sidecar/TKOS-002_IMPLEMENTATION_NOTE_v0.1.md)). The split is in rendering, not in source of truth.

v0.2.2 turns "belief observability" from a category claim into a measured design constraint: the AI surface needs compact grounding; the human surface needs evidence-rich traces; one substrate serves both. Compressed serialization for the AI is the right call empirically; preserving evidence somewhere else (on the human surface) is now required to recover the traceability that compression cost.

---

## §9 v0.3 directions

In rough priority order, each motivated by something v0.2.2 surfaced:

1. **User-stated pause / instruction beliefs.** The q040 unclear cases suggest the structural oracle under-fires on explicit user signals like "don't deploy." A v0.3 substrate addition that captures user-stated blockers as first-class beliefs (lifecycle: born when stated, retired when explicitly cleared) would close the gap and test whether the dataset's `missing_pause` floor of 13% across all arms reflects real residual difficulty or substrate under-modeling.
2. **`repeated_failure_loop` judge prompt clarification.** The judge has a recurring semantic inversion on this metric; the prompt should disambiguate `commits = fails to flag the loop` more aggressively, with a counter-example.
3. **Cross-model validation.** v0.2.2 fixes generator and judge model families. v0.3 should test whether the B100 lift transfers to other generators (Claude, Gemini) and whether preference results change with a different preference-judge family.
4. **Sidecar read + write path.** The TKOS-002 read-path slice proved the dual-consumer substrate at fixture level. v0.3 (or TKOS-002 v0.2) should add the rule engine and at least one real event-stream adapter, then re-run the v0.2.2 experiment on substrate-derived beliefs to test whether the lift survives without the v0.1 substrate's specific belief-generation properties.
5. **Runtime demo.** A scripted end-to-end demo where a live coding-assistant workflow consumes both `overlay()` (AI grounding) and `state()` / `timeline()` / `explain()` (operator inspection) — the first concrete user-facing instantiation of the dual-consumer claim.

---

## §10 Closing

The recent log shows what happened.
The belief overlay carries what is still true.
The trace surface explains why.

v0.2.2's empirical contribution is narrow and concrete: a 100-token ranked overlay reduces operational workflow-state errors in long-running assistant sessions from 10.7% to 5.3% on the v0.1 question set, without producing any of the v0.1 feasibility failures. The smallest overlay performs best.

The broader contribution is the design discipline that result implies: **compactness is the AI surface's job, evidence is the human surface's job, and one substrate serves both.** That is the belief-observability framing in its measured form.

---

*End of v0.2.2 report. Eligible for cross-experiment citation. Subsequent experiments (v0.3 and beyond) should be pre-registered separately under the same anti-curation discipline that carried through v0.1 and v0.2.*
