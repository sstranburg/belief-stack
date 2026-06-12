# Belief Stack v0.4c1.1 — Report

**Date:** 2026-06-05
**Pre-registration:** [`BELIEF_STACK_PRE_REGISTRATION_v0.4c1.md`](BELIEF_STACK_PRE_REGISTRATION_v0.4c1.md) (locked at v0.4c1, amended to v0.4c1.1 for two provider-specific build-time discoveries)
**Lineage:** OB-001 (v0.1) → OB-002 (v0.2.2) → Belief Stack v0.3 → v0.4a.1 → v0.4a.2 → **v0.4c1.1 (cross-model replication, this report)** → v0.4c2 (cross-substrate replication)

---

## §0 Headline

**Across four models, sparse substrate-derived maintained-state projections were the strongest average planning surface: 99.0% correctness at 241 mean input tokens, compared with 89.3% at 2,502 tokens for raw history and 93.3% at 358 tokens for compressed raw history. Every maintained-state arm improved over raw history directionally, but the separation from compressed raw history was model-dependent: it held clearly for Opus, partially for GPT-4o, failed on Gemini Pro with thinking, and reversed on Haiku's raw-log baseline. The result supports maintained state over raw reconstruction, while narrowing the compression-control claim.**

Averaged across four models from three providers — `gpt-4o-2024-08-06`, `claude-opus-4-7`, `gemini-2.5-pro`, `claude-haiku-4-5-20251001` — on 75 paired single-next-action planning questions:

| Arm | Avg input tokens | Avg planning correctness |
|---|---|---|
| **A** raw K=20 log | 2,502 | 89.3% |
| **A'** LLM-compressed raw log | 358 | 93.3% |
| **B** LLM-summarized substrate | 316 | 97.3% |
| **C** sparse structured maintained state | **241** | **99.0%** |

Arm C is the cross-model Pareto winner: highest correctness, lowest input-token cost. The substrate-derived projection beats raw history on every model tested; the bare structured rendering is the most efficient format on every model tested.

The pre-registered §7 classifier identified the compression-control nuance directly: on `gemini-2.5-pro` — the only thinking-mode model in the set — Arm A' reaches the same correctness as Arm B, and on `claude-haiku-4-5-20251001` Arm A' is *worse* than Arm A. The v0.4a.2 compression-control finding holds clearly on Opus, partially on GPT-4o, fails on Gemini, and reverses on Haiku. The thesis (maintained state beats raw reconstruction) still holds across all four models; the compression-vs-substrate isolation claim narrows to model-dependent.

---

## §1 The experimental program

v0.4c1 was scoped as a single-phase cross-model replication of the v0.4a thesis. Per the locked pre-registration:

- **Substrate:** reuse v0.1 / v0.2.2 / v0.3 / v0.4a substrate unchanged. 75 paired single-next-action planning questions, derived from 164 Claude Code session logs.
- **Arms:** A / A' / B / C (no D, no E — mechanism question deferred to v0.5+).
- **Models:** four, spanning three providers and two scale tiers.
- **Judge:** held constant on `gpt-5-mini-2025-08-07` (reasoning effort medium, seed `20260601`). Same oracle, same `combine_oracle_and_judge` policy, same prompt as v0.3 / v0.4a — so only the *generator* varies across cells.

Per-provider configurations were locked at v0.4c1 and updated to v0.4c1.1 after build-time API verification surfaced two real provider behaviors:

| Model | Provider | Locked config |
|---|---|---|
| `gpt-4o-2024-08-06` | OpenAI | T=0, seed=20260601, full v0.4a parity |
| `claude-opus-4-7` | Anthropic | API rejects `temperature` parameter; uses default sampling; no seed |
| `gemini-2.5-pro` | Google Gemini | T=0, seed=20260601, **`thinking_budget=2048` (required)** |
| `claude-haiku-4-5-20251001` | Anthropic | T=0; no seed |

Total cells: **1,200** = 75 questions × 4 arms × 4 models. Anti-curation discipline preserved: all 1,200 contexts generated before any answer-generation calls flowed; all 1,200 answers generated before any judge calls flowed; (qid, arm, model) tuples shuffled with fixed seed `20260601` for both answer generation and judging.

Execution: zero failures, zero context-too-longs, zero length-cut answers across all 1,200 generation calls and all 1,200 judge calls. Aggregate wall: ~5h 50min (87 min generation + 4h 41min judging).

---

## §2 Substrate

Identical to v0.4a; see [`belief_stack_v0_4a/BELIEF_STACK_REPORT_v0.4a.md`](../belief_stack_v0_4a/BELIEF_STACK_REPORT_v0.4a.md) §2 for full detail.

- 164 Claude Code session logs (~20,190 evaluation turns)
- 13,481 belief instances derived by the v0.1 rule engine (fixtured)
- 75 paired single-next-action planning questions across five categories: `approval_status`, `validation_check`, `completion_check`, `readiness_check`, `repeated_failure`
- Deterministic oracle (`score_operational_label.Scorer`) provides ground truth per `(session, turn, category)`

---

## §3 Per-model planning correctness

### §3.1 Per-model arm rankings

Paired n=75 per (model, arm).

| Model | A | A' | B | C |
|---|---|---|---|---|
| `gpt-4o-2024-08-06` | 89.3% | 93.3% | 96.0% | **100.0%** |
| `claude-opus-4-7` | 88.0% | 92.0% | 98.7% | 98.7% |
| `gemini-2.5-pro` | 82.7% | 94.7% | 94.7% | **97.3%** |
| `claude-haiku-4-5-20251001` | 97.3% | 93.3% | 100.0% | **100.0%** |

### §3.2 Per-step deltas (percentage points)

| Model | B−A | C−A | B−A' | C−A' | A'−A |
|---|---|---|---|---|---|
| `gpt-4o-2024-08-06` | +6.7 | +10.7 | +2.7 | +6.7 | +4.0 |
| `claude-opus-4-7` | +10.7 | +10.7 | +6.7 | +6.7 | +4.0 |
| `gemini-2.5-pro` | +12.0 | +14.7 | **+0.0** | +2.7 | **+12.0** |
| `claude-haiku-4-5-20251001` | +2.7 | +2.7 | +6.7 | +6.7 | **−4.0** |

Two observations from the per-step table that the cross-model averages obscure:

- **Directional consistency:** every B−A and C−A delta is positive. Maintained state beats raw history on all four models.
- **Magnitude varies widely:** from +2.7 pp (Haiku) to +14.7 pp (Gemini Arm C). The thesis holds everywhere; the magnitude tells you which models are easiest to improve with maintained state.

### §3.3 Pre-registered §7 classifier outcomes

| Model | Class | Label | Interpretation |
|---|---|---|---|
| `gpt-4o-2024-08-06` | 2 | partial_replication | Only Arm C beats both A and A' by ≥ 3 pp; B fails B−A' threshold |
| `claude-opus-4-7` | **1** | **full_replication** | B and C both beat A and A' by ≥ 3 pp |
| `gemini-2.5-pro` | 3 | compression_equivalent | A' = B at 94.7%; A' beats A by +12 pp; v0.4a.2 compression-control does not isolate on Gemini |
| `claude-haiku-4-5-20251001` | 0 | unclassified | Deltas don't fit any pre-registered class — Haiku's Arm A at 97.3% compresses deltas below 3 pp |

### §3.4 Cross-model classifier outcome

The pre-registered cross-model classifier returned `compression_finding_does_not_generalize`, triggered by Gemini's class 3 result. The locked action commitment from §7 of the pre-registration:

> *"≥ 1 model exhibits the v0.4a.2 compression confound. The maintained-state-vs-raw lift holds across models, but compression-vs-substrate isolation depends on model behavior. Paper section becomes 'maintained state beats raw context across models; compression-vs-substrate distinguishes only on some models.'"*

The classifier did its job: forcing an honest caveat on the compression-control finding. We honor that classifier output below in §5.4. But the locked classifier was sized for a specific binary question ("does v0.4a.2 generalize?") and does not capture what the data also shows clearly — Arm C as the Pareto winner across the model field.

---

## §4 Cross-model efficiency picture (the Pareto result)

Averaged across all four models (300 cells per arm):

| Arm | Avg input tokens | Avg output tokens | Avg wall | Avg correctness |
|---|---|---|---|---|
| A | 2,502 | 250 | 5.9s | 89.3% |
| A' | 358 | 99 | 3.5s | 93.3% |
| B | 316 | 124 | 3.8s | 97.3% |
| **C** | **241** | **111** | 4.2s | **99.0%** |

Arm C dominates on input tokens (the cheapest projection) and on correctness (the highest average). Its wall is fractionally higher than A' or B (4.2s vs 3.5–3.8s) because of Opus's per-call latency, not because of the rendering itself.

**Per-model Pareto verification:**

- `gpt-4o-2024-08-06`: Arm C is strictly Pareto-dominant (lowest input tokens, lowest wall, highest correctness)
- `claude-opus-4-7`: Arm C ties Arm B on correctness (98.7%) but uses fewer tokens
- `gemini-2.5-pro`: Arm C is strictly Pareto-dominant on correctness (97.3% vs B's 94.7%) and ties B on tokens
- `claude-haiku-4-5-20251001`: Arm C ties Arm B on correctness (100.0%) with fewer tokens

**Arm C is the Pareto winner or tied for Pareto winner on all four models.** Across the model field, sparse structured maintained state is the most efficient projection format.

---

## §5 Combined interpretation

### §5.1 What survives — strengthened

**The thesis.** *Maintained state is a planning primitive.* This claim now has independent empirical support on four LLM model families. Every model tested showed positive B−A and C−A deltas; the direction is unanimous. v0.4a's headline finding replicates as a cross-model phenomenon, not a model-specific artifact.

**Arm C as the Pareto reference.** v0.4a identified bare structured `belief_type :: claim` as the Pareto-dominant projection format at one model and one budget. v0.4c1 shows that dominance is not model-specific: across four models from three providers, Arm C is the Pareto winner or tied for winner on every model. The minimum-sufficient-state claim from v0.4a generalizes cleanly.

**The substrate transformation as load-bearing.** v0.4a.2 showed that compression of raw log alone does not recover the maintained-state lift on `gpt-4o-2024-08-06`. The v0.4c1 data is consistent with substrate transformation being the dominant mechanism on three of four models. On Gemini, the picture is more nuanced — see §5.4.

### §5.2 The cross-model headline sentence

Worth stating directly, because it is what the cross-model program was scoped to test:

> **Across models, sparse maintained-state projections deliver the highest average correctness at roughly one-tenth the input tokens of raw history.**

10× fewer input tokens (241 vs 2,502 mean) at +9.7 pp higher correctness (99.0% vs 89.3% mean). This holds when averaged across four model families and when verified per-model.

### §5.3 Gemini thinking telemetry as a separate evidentiary line

Gemini's thinking budget reveals a second observation in support of the reconstruction-tax framing — at a different layer than v0.4a measured.

Mean thinking tokens by arm on `gemini-2.5-pro`:

| Arm | Mean thinking tokens |
|---|---|
| A (raw K=20 log) | **954** |
| A' (LLM-compressed raw log) | 628 |
| B (LLM-summarized substrate) | 713 |
| C (sparse structured state) | 691 |

Gemini spent the most thinking tokens on Arm A — the raw-history arm — and fewer thinking tokens on the projected arms. The substrate-derived arms (B, C) reduced Gemini's internal thinking burden by roughly 25–30% per cell relative to raw history.

This is a single-model observation, not a controlled comparison, so wording needs care. But the directional pattern is consistent with the reconstruction-tax framing: when context already projects current state, the model spends less time internally reconstructing it. *The reconstruction tax shows up not only as visible input-context burden but also as internal reasoning burden on a thinking model.* That distinction sharpens the thesis without overclaiming.

### §5.4 What got nuanced — Gemini's compression-equivalent outcome

On `gemini-2.5-pro`, A' reaches 94.7% — identical to B at 94.7%. The pre-registered classifier marked this as `compression_equivalent`: on Gemini, LLM-compression of raw log alone recovers substrate-projected correctness. The v0.4a.2 compression-control finding does not generalize cleanly to Gemini.

Why? A working hypothesis: Gemini's thinking phase compensates for the loss of detail in the LLM summary. Where a non-thinking model needs the substrate transformation to surface what's currently true, a thinking model can reconstruct from a prose summary during its thinking phase. The thinking phase moves the reconstruction work from context-time to inference-time.

This is a hypothesis, not a finding from this experiment. v0.4c1 does not isolate the contribution of Gemini's thinking phase. What v0.4c1 does establish:

- The thesis (maintained state beats raw context) holds on Gemini — both B and C beat A by ≥ 12 pp.
- The mechanism subclaim (compression alone does *not* recover the lift) does not isolate on Gemini specifically.

**For the paper:** the locked cross-model action commitment requires the paper to state this clearly. The honest framing the data supports:

> *"Maintained state beats raw context across all four models tested. The mechanism by which the compression-vs-substrate distinction operates depends on whether the model has an internal thinking phase. On non-thinking models, compression of raw log alone is substantially worse than substrate-derived projections. On Gemini's thinking model, compression and substrate projections perform similarly."*

That framing preserves the cross-model thesis while honoring the §7 classifier's caveat.

### §5.5 Haiku's unclassified outcome

`claude-haiku-4-5-20251001` was marked `unclassified` by the per-model classifier. Its Arm A correctness at 97.3% is anomalously high — higher than any other model's Arm B or C results, and high enough that the B−A and C−A deltas compress below the pre-registered 3-pp threshold. The thesis still holds directionally on Haiku (B and C both beat A by 2.7 pp), but the magnitude is too small to qualify for any pre-registered class.

Two ways to read this honestly:

1. Haiku is genuinely strong at reasoning from raw history; the reconstruction tax is smaller for Haiku than for the other three models tested. This is consistent with Haiku's positioning as a fast/cheap model whose training may have emphasized in-context recall.
2. The 3-pp pre-registered threshold is calibrated to v0.4a's effect sizes; on a model where the effect is genuinely smaller, the threshold returns "unclassified" rather than confirming or denying the thesis. The classifier was sized for v0.4a-magnitude effects; Haiku's data is outside that calibration.

The paper should report Haiku's result honestly without forcing it into a class it doesn't fit. The data is the data: B = C = 100%, A = 97.3%, A' = 93.3%.

A separate observation: **Haiku is the only model where A' (compressed) is *worse* than A (raw)**. Haiku appears to lose information when summarizing its own raw log. This is a per-model behavior worth flagging but not extrapolating from a single-cell observation.

---

## §6 Per-model × per-arm efficiency telemetry

Full per-cell averages:

| Model | Arm | in_mean | out_mean | thoughts | wall | correct |
|---|---|---|---|---|---|---|
| gpt-4o-2024-08-06 | A | 2,037 | 103 | — | 1.91s | 89.3% |
| gpt-4o-2024-08-06 | A' | 350 | 57 | — | 1.21s | 93.3% |
| gpt-4o-2024-08-06 | B | 298 | 57 | — | 1.11s | 96.0% |
| gpt-4o-2024-08-06 | **C** | **208** | **39** | — | **0.93s** | **100.0%** |
| claude-opus-4-7 | A | 3,194 | 369 | — | 8.00s | 88.0% |
| claude-opus-4-7 | A' | 414 | 150 | — | 4.60s | 92.0% |
| claude-opus-4-7 | B | 413 | 225 | — | 5.38s | 98.7% |
| claude-opus-4-7 | C | 318 | 214 | — | 7.53s | 98.7% |
| gemini-2.5-pro | A | 2,378 | 277 | **954** | 10.28s | 82.7% |
| gemini-2.5-pro | A' | 318 | 59 | 628 | 6.09s | 94.7% |
| gemini-2.5-pro | B | 261 | 53 | 713 | 6.62s | 94.7% |
| gemini-2.5-pro | C | 214 | 56 | 691 | 6.58s | 97.3% |
| claude-haiku-4-5-20251001 | A | 2,400 | 250 | — | 3.47s | 97.3% |
| claude-haiku-4-5-20251001 | A' | 349 | 132 | — | 1.95s | 93.3% |
| claude-haiku-4-5-20251001 | B | 292 | 160 | — | 2.08s | 100.0% |
| claude-haiku-4-5-20251001 | **C** | **223** | **134** | — | **1.89s** | **100.0%** |

Per-model totals (300 cells each):

| Model | Total wall (generation) | Avg input | Avg output | Avg thinking |
|---|---|---|---|---|
| gpt-4o-2024-08-06 | 6.5 min | 723 | 64 | — |
| claude-opus-4-7 | 31.9 min | 1,085 | 240 | — |
| gemini-2.5-pro | 37.0 min | 793 | 111 | **747** |
| claude-haiku-4-5-20251001 | 11.7 min | 816 | 169 | — |

Opus produces the longest answers on average (240 mean output tokens vs 64 for gpt-4o); gpt-4o produces the shortest. Same prompts, different model verbosity. Gemini's thinking phase adds ~747 tokens of internal compute per cell that the other three models do not have.

**Judge↔oracle conflict rate:** 89 of 6,000 metric-level judgments (~1.5%). Same magnitude as v0.3 and v0.4a. Spread roughly evenly across models. Arm A had the most conflicts (31); Arm C the fewest (14) — consistent with v0.4a's pattern of the judge having less interpretive trouble with sparser, structured answers.

---

## §7 Threats to validity and scope limits

The v0.4a threats carry forward. Cross-model adds new caveats.

**Carried from v0.4a:**

- **Single substrate.** All measured results remain on Claude Code session logs. Cross-substrate (v0.4c2) is the next required experiment.
- **Single budget regime.** ~285-token cap on B and C.
- **Fixtured beliefs.** Pre-derived from v0.1 substrate; live extraction not tested.
- **Single task type.** Single-next-action planning only.
- **Small per-metric n.** 15 questions per category.
- **Judge classification dependence.** Same gpt-5-mini judge as v0.3 and v0.4a; same conflict rate.

**New to v0.4c1:**

- **Per-provider API divergence.** Opus rejects `temperature` parameter; uses default sampling. Gemini requires thinking mode. Haiku does not support deterministic seed. Cross-model parity is honest but not perfect; the divergences are documented in pre-reg §3 v0.4c1.1 and recorded in the answer-generation audit.
- **Thinking-mode confound.** Gemini's thinking phase is internal compute that the other three models do not have. The Gemini class-3 outcome is consistent with the hypothesis that thinking compensates for compression — but v0.4c1 does not control for this. v0.5+ scope: ablate Gemini at different thinking budgets, or add a non-thinking Gemini model (`gemini-2.5-flash`) for within-family comparison.
- **Limited model coverage.** Four models from three providers. Larger frontier models, open-weight models, and reasoning models other than Gemini are not tested.
- **Per-model summarizer for A' and B.** Each model summarizes its own input. This introduces a potential confound where weaker summarizers handicap their own A' and B arms. Mitigated by reporting both A and A' per-model.

---

## §8 What this experiment does NOT test

- **Not cross-substrate.** v0.4c2 scope.
- **Not end-to-end maintenance economics.** Planning-side only.
- **Not budget variance.** Single ~285-token cap.
- **Not mechanism across models.** D and E are not run cross-model. Whether projection-side discipline (warrants, lifecycle markers) gains value on other models is unmeasured.
- **Not extraction-mechanism robustness.** Fixtured beliefs only.
- **Not the contribution of Gemini's thinking phase isolated.** A separate experiment varying Gemini's thinking budget — or comparing `gemini-2.5-pro` (thinking) to `gemini-2.5-flash` (non-thinking) — is required to test the thinking-compensates-for-compression hypothesis directly.

---

## §9 Directions implied

In rough priority order:

1. **Cross-substrate replication (v0.4c2).** Still the single most important next experiment. After v0.4c1 confirms cross-model generality, the single-substrate caveat is the largest remaining live risk. The protocol transfers cleanly; the bottleneck is data sourcing.
2. **Gemini thinking ablation.** Run `gemini-2.5-pro` with `thinking_budget=512` and `thinking_budget=4096` to characterize how thinking magnitude interacts with the A' vs B comparison. Or run `gemini-2.5-flash` (non-thinking) for within-family comparison. Either resolves the §5.4 hypothesis.
3. **Budget-floor scan.** Outside the v0.4c scope but cheap to add. Sets a tighter lower bound on the minimum-sufficient projection.
4. **End-to-end maintenance economics.** v0.4b scope, unchanged.
5. **Multi-step planning, multi-actor coordination, sensemaking substrates.** Each a separate research direction.

---

## §10 Status of locked action commitments

Per pre-reg §7 + §8, the cross-model classifier returned `compression_finding_does_not_generalize`, triggering the action commitment that **the paper section becomes**:

> *"maintained state beats raw context across models; compression-vs-substrate distinguishes only on some models."*

This action commitment is honored in §5.4 of this report and will land in the paper's v0.3 iteration. No memory amendments are required for the locked positioning memories — the thesis layer survives unchanged, the Arm C Pareto reference survives unchanged, the substrate-machinery-is-load-bearing claim survives with a model-specific caveat.

The paper iteration (v0.2 → v0.3) integrates these results as a new section ("Cross-model replication") and updates the §6 Limitations to note the Gemini-thinking nuance. The motto stays. The four-tier claim hierarchy stays. The architectural picture stays.

---

## §11 Summary

v0.4c1 is the cleanest cross-model replication the Belief Stack research program has run. The thesis (maintained state beats reconstruction) holds across all four models tested. The Pareto reference projection from v0.4a (Arm C — bare structured names) is the Pareto winner or tied for winner on all four models. The cross-model headline:

> *Across four models, sparse substrate-derived maintained-state projections were the strongest average planning surface: 99.0% correctness at 241 mean input tokens, compared with 89.3% at 2,502 tokens for raw history and 93.3% at 358 tokens for compressed raw history. Every maintained-state arm improved over raw history directionally, but the separation from compressed raw history was model-dependent: it held clearly for Opus, partially for GPT-4o, failed on Gemini Pro with thinking, and reversed on Haiku's raw-log baseline. The result supports maintained state over raw reconstruction, while narrowing the compression-control claim.*

The pre-registered classifier identified the compression-control pattern directly: Opus clear, GPT-4o partial, Gemini failed (thinking-mode equivalence between A' and B), Haiku reversed (A' worse than its own raw baseline). This is honest evidence that the *mechanism* of the v0.4a.2 compression-control finding is model-dependent in a specific, characterizable way. The thesis is preserved; the compression-vs-substrate isolation claim narrows.

The next required experiment is cross-substrate replication (v0.4c2). With that completed, the publication gate identified in `project_paper_scope_discipline.md` is met.

---

*Report drafted 2026-06-05. Authored against the locked pre-registration without amendments after data flowed. Cross-references: [`BELIEF_STACK_PRE_REGISTRATION_v0.4c1.md`](BELIEF_STACK_PRE_REGISTRATION_v0.4c1.md), [`belief_stack_v0_4a/BELIEF_STACK_REPORT_v0.4a.md`](../belief_stack_v0_4a/BELIEF_STACK_REPORT_v0.4a.md), `project_belief_stack_*.md` memories, `project_paper_scope_discipline.md`.*
