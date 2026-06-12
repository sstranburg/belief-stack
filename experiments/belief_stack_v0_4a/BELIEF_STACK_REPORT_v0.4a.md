# Belief Stack v0.4a — Report

**Date:** 2026-06-04
**Pre-registration:** [`BELIEF_STACK_PRE_REGISTRATION_v0.4a.md`](BELIEF_STACK_PRE_REGISTRATION_v0.4a.md) (locked at v0.4a, amended to v0.4a.1, further amended to v0.4a.2)
**Lineage:** OB-001 (v0.1) → OB-002 (v0.2.2) → Belief Stack v0.3 → **v0.4a (mechanism ablation + compression-control, this report)** → v0.4b (end-to-end cost) → v0.4c (replication)

---

## §0 Headline

**Maintained state survives. Projection discipline does not separate. Compression alone is ruled out.**

v0.3 measured an 8-point planning-correctness lift from a "maintained belief overlay" over a 20-turn raw log. v0.3's interpretation attributed that lift to the spec's full discipline — *claims + warrants + lifecycle*. v0.4a's two-phase experimental program shows that v0.3's interpretation was over-strong on one axis and load-bearing on another:

- **The lift survives** at the *maintained-state-of-some-form* level. Sparse structured names (Arm C: 208 tokens, 97.3% correctness) recover the same correctness as v0.3's full-discipline overlay at lower token cost.
- **The projection-side discipline (warrants in context, lifecycle marker in context) does not pay** at this budget on this substrate. Arms D and E underperform Arm C and Arm B; the richer rendering correlates with slightly more errors, not fewer.
- **Compression alone does not explain the lift.** LLM-summarizing the raw 20-turn log at the same budget that produced Arm B reaches Arm A's correctness, not Arm B's. The substrate transformation — the rule-engine view of *what is currently true* — is doing the planning-useful work.

The combined finding refines, rather than reverses, v0.3's thesis. *Maintained state is a planning primitive* survives stronger than v0.3 alone could claim. The mechanism by which it does its work moves from "the spec's full discipline rendered in context" to "the substrate transformation upstream of the projection."

---

## §1 The experimental program

v0.4a was scoped as a two-phase test of v0.3's interpretation, executed sequentially over a single day. Both phases used the same substrate, the same generator, and the same deterministic-oracle scoring as v0.3, to maximize cross-experiment comparability.

| Phase | Question | Arms | Outcome class fired |
|---|---|---|---|
| **v0.4a.1** | What part of v0.3's overlay caused the planning lift? | A / B / C / D / E (5-arm mechanism ladder) | §7 Outcome 5 — *lifecycle/warrant discipline does not add measurable value over maintained summaries on this substrate* |
| **v0.4a.2** | Is the lift coming from compression itself, or from the substrate transformation? | A′ (LLM summary of raw log at matched budget) added as a 6th arm | §12 Outcome A_prime_near_A — *compression of raw log does not help; the substrate transformation is doing the work* |

v0.4a.1's result motivated v0.4a.2. The Phase-2 amendment was drafted, locked, and executed on the same evening (2026-06-03), with action commitments locked before any A′ data flowed.

Pre-registration discipline was preserved throughout: lock → build → audit → amend (where surfaced) → run → score. The amendment trace (v0.4a → v0.4a.1 → v0.4a.2) is in §11 of the pre-reg. The build-time audit that surfaced the D4 budget-interpretation ambiguity at v0.4a → v0.4a.1 is documented there.

---

## §2 Substrate

Reused from OB-001 / OB-002 / v0.3 without modification.

- **75 paired single-next-action planning questions** across five category metrics:
  - `stale_validation_assumption` (n=15) — has validation actually completed?
  - `repeated_failure_loop` (n=15) — is this the same failure as before?
  - `premature_action` (n=15) — is the assistant authorized to proceed?
  - `false_completion_claim` (n=15) — is the assistant correct that the task is done?
  - `missing_pause` (n=15) — should the assistant proceed, pause, or ask?
- **164 Claude Code session logs (~20,190 evaluation turns)** as the upstream event stream.
- **Belief substrate**: 13,481 belief instances derived from the event stream by the v0.1 rule engine; carries claims, warrants (`current_authority`, `warrant_evidence_turns`, `decay_status`), and lifecycle history (`revision_trail` with `born / refreshed / weakened / contradicted / retired` events).
- **Oracle**: `score_operational_label.Scorer` from v0.1 — programmatic ground-truth computation per (session, turn, category). Same per-question oracle used in v0.1, v0.2.2, and v0.3.

The single-substrate, single-task-type, single-model constraint is documented as a scope limit in §8.

---

## §3 Phase 1 — v0.4a.1 mechanism ladder

### §3.1 Design

Five arms, strict ladder: each successive arm adds one element of the v0.3 Belief Stack discipline. All four belief-based arms (B/C/D/E) targeted at a **285-token budget cap**. Same generator (gpt-4o-2024-08-06, T=0, seed 20260601). Same scoring methodology.

| Arm | Context format | Discipline level |
|---|---|---|
| **A** | Raw K=20 log + strong-baseline reconstruction prompt | None — raw context (v0.3 Arm A unchanged) |
| **B** | LLM-generated prose summary of the §3.5a-clustered active substrate, capped at 285 tokens | Maintained + compressed; no structure |
| **C** | Structured `belief_type :: claim` per cluster, no warrant fields, no lifecycle marker | Maintained + structured; no warrant, no lifecycle |
| **D** | C + `(auth=…, evidence=[…], decay=…, last=…)` per cluster | Structure + warrants; no lifecycle marker |
| **E** | D + `[active]/[weakened]/[contradicted]` lifecycle prefix per cluster | Full Belief Stack discipline |

Per the v0.4a.1 D4 amendment: budget cap is matched; observed token counts vary by format because the substrate exhausts before filling the cap at some renderings. The audit condition is cluster-admission parity, which held: C / D / E admit the same median number of clusters (4) at the budget cap.

### §3.2 Result — ladder shape

| Arm | Errors / 75 | Error rate | **Planning correctness** | Mean input tokens | Mean wall (s) |
|---|---|---|---|---|---|
| **A** | 6 | 8.0% | **92.0%** | 2,037 | 2.23 |
| **B** | 2 | 2.7% | **97.3%** | 297 | 1.12 |
| **C** | 2 | 2.7% | **97.3%** | 208 | 0.92 |
| **D** | 3 | 4.0% | **96.0%** | 333 | 1.03 |
| **E** | 3 | 4.0% | **96.0%** | 370 | 1.24 |

### §3.3 Per-step deltas (in percentage points)

| Step | Δ correctness | Above 3-pp threshold? |
|---|---|---|
| B − A | **+5.3 pp** | ↑ Yes |
| C − B | 0.0 pp | ≈ noise |
| D − C | −1.3 pp | ≈ noise (slight regression) |
| E − D | 0.0 pp | ≈ noise |
| E − B | −1.3 pp | ≈ noise |

The pre-registered ladder shape *E > D > C > B > A* was not observed. Only the B − A transition cleared the 3-pp threshold.

### §3.4 Outcome class fired: §7 Outcome 5

Per the pre-registered §7 interpretation rules:

> **Outcome 5 — E ≈ B (≤ 2 pp):** Lifecycle/warrant discipline does not add measurable value over maintained summaries on this substrate. The lifecycle-is-novelty claim weakens substantially.

E − B = −1.3 pp (E slightly below B), well within the 2-pp noise floor. Outcome 5 fired exactly as pre-registered. The locked Outcome-5 wording — sharpened at Sue's lock-day amendment — applies:

> *Not "compression alone explains v0.3" — Arm B is still maintained state with current-state selection and chronology removal. The precise finding is that the additional structure / warrant / lifecycle elements do not add measurable value above maintained-summary baseline at this token budget on this substrate.*

### §3.5 Where the negative effect concentrates

The Phase-1 ladder is non-linear in an architecturally informative way. Of the three structured-ladder transitions, the harm and the token-cost both concentrate at one step:

| Step | Δ input tokens | Δ correctness |
|---|---|---|
| B → C (strip prose, keep structure) | −89 (−30%) | 0.0 pp |
| **C → D (add warrants)** | **+125 (+60%)** | **−1.3 pp** |
| D → E (add lifecycle markers) | +37 (+11%) | 0.0 pp |

Lifecycle markers added in step D → E are essentially free on every axis: small token cost, flat correctness. The introduction of warrant fields in the projection (step C → D) is where the cost and the slight degradation both appear. *Warrants rendered as structured fields in the AI-facing projection* is the specific subcomponent of the spec's discipline that does not pay at this budget on this substrate.

---

## §4 Phase 2 — v0.4a.2 compression-control arm (A′)

### §4.1 Why this arm

Phase 1 ruled out *projection discipline* as the mechanism but left an architectural ambiguity unresolved: the 5.3-pp B − A lift could be explained by either (a) compression — Arm B is shorter than Arm A — or (b) substrate transformation — Arm B's input is the rule-engine-derived view of currently-active beliefs, while Arm A's input is raw chronological log. The two explanations have very different implications for the architectural thesis.

The amendment locked at v0.4a.1 → v0.4a.2 (drafted, reviewed, and signed off the same evening as Phase 1 results) added a single arm holding compression constant and varying source.

### §4.2 Design

| Field | Value |
|---|---|
| **Arm A′** | LLM-generated prose summary of the raw K=20 log at ~285-token cap |
| Source | Identical to Arm A's input |
| Compression mechanism | Identical to Arm B's: same model, T, seed, max-output cap, system-prompt structure |
| Summarizer model | `gpt-4o-2024-08-06`, T=0, seed `20260601` |
| Output cap | 285 tokens (matched to Arm B) |
| Answer-time system prompt | **Same as Arm B's** by design — the model is intentionally blind to whether the prose summary came from raw log (A′) or maintained substrate (B). Holding answer-time framing constant isolates source from rendering. |

### §4.3 Result

| Arm | Correctness | Mean input tokens |
|---|---|---|
| **A** raw K=20 log | 92.0% | 2,037 |
| **A′** prose of raw log | **90.7%** | 259 |
| **B** prose of substrate | 97.3% | 297 |
| **C** structured names | 97.3% | 208 |

| Cross-arm delta | Value | Above 3-pp threshold? |
|---|---|---|
| A′ − A | **−1.3 pp** | ≈ noise floor — A′ does not improve over A |
| B − A′ | **+6.7 pp** | ↑ Substantial |
| C − A′ | **+6.7 pp** | ↑ Substantial |

### §4.4 Outcome class fired: §12 A_prime_near_A

Per the pre-registered §12 interpretation rules (locked at v0.4a.2 amendment time):

> **A′ ≈ A (within 2 pp):** Strongest possible support for the thesis. Compression of raw log alone does not reach maintained-substrate correctness — the substrate transformation is doing the work.

A′ − A = −1.3 pp, well inside the 2-pp noise floor. Outcome A_prime_near_A fired as pre-registered.

### §4.5 What this rules out

The B − A lift measured in Phase 1 is *not* attributable to compression. When compression is applied to the raw log under the same protocol that produced B from the substrate — same generator, same temperature, same seed, same budget, same answer-time prompt — correctness does not move. The substrate transformation between raw log and clustered active beliefs is the load-bearing operation.

---

## §5 Combined interpretation

The two phases tell a single combined story:

### §5.1 What survives

- **The matter claim:** *Maintained state is a planning primitive.* Strengthened, not weakened. The thesis now has two independent empirical supports rather than one:
  1. v0.3: Maintained overlay (Arm B) beat raw context (Arm A) by 8 pp at 14% of input tokens.
  2. v0.4a.2: Compressed raw context (Arm A′) does *not* beat raw context (Arm A) at matched budget — only substrate-derived context recovers the lift. Compression alone is ruled out.
- **The substrate transformation as load-bearing operation:** The rule-engine pipeline upstream of the AI-facing projection — clustering by `(belief_type, operational_claim)`, filtering to `{active, weakened, contradicted}` states, ranking by recency + authority — is doing planning-useful work that compression of raw history cannot replicate.

### §5.2 What does not survive

- **The full-discipline interpretation of v0.3:** v0.3 attributed its 8-pp lift to the spec's full `claims + warrants + lifecycle` discipline rendered in the AI-facing projection. v0.4a.1's mechanism ladder shows that the projection-side discipline does not separate. C (claims only) ties B (prose summary); D (with warrants) and E (with lifecycle marker) underperform both.
- **The warrant-rendering hypothesis:** Adding `(auth=…, evidence=[…], decay=…, last=…)` to the projection costs +60% input tokens and gives back −1.3 pp correctness. At this budget on this substrate, structured warrant rendering in the AI-facing projection is anti-productive — slightly.

### §5.3 The architectural picture this earns

| Layer | Spec implication |
|---|---|
| **Substrate** | Rich. Claims + warrants + lifecycle preserved. Rule engine runs upstream. §3.5a dedup, ranking, lifecycle-state filtering are all load-bearing — without them, prose compression of raw log cannot recover the planning lift. |
| **AI-facing projection (overlay)** | Sparse. Bare `belief_type :: claim` per active cluster, dedup-ranked, budget-bounded. ~208 tokens reaches 97.3% correctness — the most efficient point on the v0.4a Pareto front. Adding warrant or lifecycle fields to the projection does not add measurable correctness and may add noise. |
| **Human-facing inspection** | Rich. Full warrant chains, lifecycle timelines, audit trails. The dual-consumer pattern is preserved — but the two surfaces are *asymmetric* in detail demand. The planner needs less than v0.3 made it look. Humans still want the full substrate exposed. |

This is a sharper architecture than v0.3 articulated. It distinguishes *substrate machinery* (load-bearing) from *projection content* (sparse is optimal). It also reinforces the dual-consumer pattern by quantifying how different the two consumers' optimal projections are.

### §5.4 What v0.3's interpretation got wrong

v0.3's case study claimed the lift was attributable to the spec's `claim + warrant + lifecycle` discipline as a whole. v0.4a.1 falsifies that specific attribution at the projection level. The numbers v0.3 reported are not in question — they replicate cleanly in v0.4a as the B − A delta. The over-strong claim is the *attribution* of those numbers to projection-side discipline rather than to upstream substrate machinery.

The v0.3 essay ([execution-state-vs-belief-state](https://topicspace.ai/writing/execution-state-vs-belief-state)) and the spec's empirical-status section need amendments to distinguish these two claims clearly. Memory amendments and site-surface revisions are queued separately.

---

## §6 Per-metric texture

Error counts per metric (n=15 per category, paired):

| Metric | A | A′ | B | C | D | E |
|---|---|---|---|---|---|---|
| stale_validation_assumption | 1 | 2 | 0 | 0 | 0 | 0 |
| repeated_failure_loop | 0 | 0 | 0 | 1 | 1 | 1 |
| premature_action | 1 | 1 | 0 | 0 | 0 | 1 |
| false_completion_claim | 2 | 2 | 1 | 1 | 2 | 1 |
| missing_pause | 2 | 2 | 1 | 0 | 0 | 0 |

Within the small n=15 per category, several patterns are suggestive without being statistically conclusive:

- **`missing_pause`** is the metric most cleanly responsive to maintained state. A and A′ both commit 2 errors; B commits 1; C/D/E commit zero. Maintained state — in any of its substrate-derived forms — appears to help the planner identify when to pause.
- **`repeated_failure_loop`** shows a *reverse* pattern: B catches all 15 cases; C, D, E each miss one. The compact structured rendering may strip the chronological texture the planner uses to identify recurring failures. Worth noting as a possible weakness of bare-claims-only projection at this metric.
- **`stale_validation_assumption`**: A′ commits 2 errors (worse than A's 1). The LLM summarizing raw history may *introduce* stale-validation errors by foregrounding completion language present earlier in the session. The substrate-derived arms (B/C/D/E) all commit zero.
- **`false_completion_claim`** is the metric where the discipline arms (D, E) show no advantage over claims-only (C). C commits 1 error; D commits 2; E commits 1. Warrant fields rendered in context do not appear to help the planner avoid false-completion mistakes.

The per-metric pattern reinforces the §5 interpretation: substrate-derived projection wins broadly; richer projection rendering does not consistently help and sometimes hurts.

---

## §7 Efficiency telemetry

The Pareto picture across all six arms:

| Arm | Input tokens | Output tokens | Wall (s) | Correctness | Judge↔oracle conflicts |
|---|---|---|---|---|---|
| A | 2,037 | 104.4 | 2.23 | 92.0% | 7 / 375 |
| A′ | 259 | — | — | 90.7% | 6 / 375 |
| B | 297 | 56.4 | 1.12 | 97.3% | 6 / 375 |
| **C** | **208** | **40.6** | **0.92** | **97.3%** | **2 / 375** |
| D | 333 | 59.3 | 1.03 | 96.0% | 7 / 375 |
| E | 370 | 67.6 | 1.24 | 96.0% | 6 / 375 |

**Arm C is the Pareto winner.** C strictly dominates D and E (better correctness, fewer tokens, faster wall, lower judge-oracle disagreement). C ties B on correctness but wins on every other axis: 30% fewer input tokens, 28% fewer output tokens, 18% faster wall, and one-third the judge-oracle disagreements. Arm C is the most efficient representation of state observed in v0.4a — and the simplest.

The judge↔oracle conflict pattern (a secondary diagnostic) is also informative: C had the fewest conflicts (2/375), indicating the judge had the least interpretive difficulty classifying C's answers. The richer projections did not produce more agreement; they produced more noise.

---

## §8 Threats to validity and scope limits

- **Single substrate.** The only operational substrate tested is Claude Code session logs. Substrates with different properties — longer reasoning chains, ambiguous evidence, multi-actor planning, sensemaking domains — are unmeasured. The v0.4a findings may not transfer.
- **Single model.** `gpt-4o-2024-08-06` only. Newer or differently-trained models may extract more from rich projections (potentially restoring the discipline's advantage) or compress so well that even C is unnecessary (potentially pushing the Pareto winner lower still).
- **Single budget regime.** Budget cap was 285 tokens for all of B/C/D/E. At higher budgets — say 800 or 2000 tokens — the richer arms have room to surface more cluster content per belief, and the trade-off may shift.
- **Fixtured beliefs.** The belief substrate was pre-derived from the v0.1 question set. Live extraction (write-path rule engine deriving beliefs from real event streams) is not tested here; that is v0.4c scope.
- **Single-next-action task only.** Multi-step planning is not tested. The "what's the next correct action" task may be uniquely friendly to compressed maintained state.
- **Small n per metric.** 15 questions per category is enough to detect aggregate-level effects (planning correctness across all 75) but too few to make per-metric claims with confidence. Per-metric patterns reported in §6 are directional, not definitive.
- **Judge classification dependence.** Per the v0.4a.1 §5 interpretation, the deterministic oracle is the score axis and the LLM judge is consulted as answer classifier under oracle-wins-on-disagreement policy. 28 conflicts out of 1,875 metric-level judgments (~1.5%) is low but non-zero; primary outcomes are insensitive to small judge errors at this conflict rate.

---

## §9 What v0.4a does NOT test

- Not end-to-end maintenance cost. v0.4b scope: the substrate transformation's cost in tokens, latency, and dollars per evidence event.
- Not model variance. v0.4c scope.
- Not domain transfer. v0.4c scope. Especially important after v0.4a results — the single-substrate caveat is the largest live risk to today's interpretation.
- Not extraction-mechanism robustness. v0.4c scope. Fixtured beliefs may flatter the projection arms relative to a live-extraction baseline.
- Not narrative or sensemaking substrates. Operational-substrate-only; the open question about whether Belief Stack is one architecture or a family (per `project_belief_stack_open_questions_post_v03.md`) is unaddressed by v0.4a.
- Not budget-floor mapping. v0.4a shows 208 tokens of bare structured names suffices at 97.3% correctness; it does not establish how low the floor goes before correctness drops. A small budget-floor scan (e.g., 50 / 100 / 150 / 208 tokens of Arm C–style render) is a candidate sub-experiment.

---

## §10 Directions implied

In rough priority order, refined by v0.4a's findings:

1. **Cross-substrate replication is now the most important next experiment.** v0.4a's single-substrate result needs a second operational substrate (DevOps incident logs, customer-support trajectories) to test whether C-style projection generalizes beyond Claude Code sessions. This was originally part of v0.4c; it may deserve its own experiment ahead of the broader v0.4c replication scope.
2. **Budget-floor scan.** v0.4a sets an upper bound on the minimum-sufficient projection at 208 tokens. Where the floor actually is — and whether the descent is gradual or cliff-shaped — is a candidate ~$1 / ~1-hour experiment.
3. **End-to-end cost.** v0.4b's original scope (substrate-side maintenance cost vs planner-side savings) is now substantively reframed: the architecture is sparser AI-side than v0.3 suggested, and the substrate-side cost is the load-bearing measurement that determines net economic viability.
4. **Warrant utility at write-time, not read-time.** Warrants did not pay in the AI-facing projection. They may still be load-bearing in the substrate's *write path* — deciding which beliefs to maintain, how to score authority, when to retire. This is a separate research direction; v0.4a does not test it.
5. **Lifecycle inspection-side value.** v0.4a measured lifecycle's value only on the AI side, where it was flat. The human-side value (debugging, audit, trust calibration) is unmeasured by v0.4a but plausibly remains high.

---

## §11 Status of locked action commitments

Per the pre-registered §7 (Outcome 5) and §12 (A_prime_near_A) action commitments, the following memory amendments are queued for execution post-report:

- **`project_belief_stack_lifecycle_is_novelty.md`** — surgical rewrite distinguishing substrate machinery (load-bearing, confirmed by A′ < B) from projection content (not load-bearing at this budget, confirmed by D ≈ C and E ≈ B).
- **`project_belief_stack_database_analogy.md`** — first testable prediction (*state should become separable from reasoning*) strengthened by A′ ≈ A. Third testable prediction (*reduce reconstruction burden when maintained outside the planner*) is empirically defended against the obvious counter-argument.
- **`project_belief_stack_claim_hierarchy.md`** — thesis-layer claim strengthens; engineering-bridge wording (*state-transition guards*) softens given lifecycle is not load-bearing in projection.
- **`project_belief_stack_cost_frontier.md`** — v0.4a result + v0.4a.2 result noted; v0.4b/c scopes refined per §10 above.
- **NEW**: `project_belief_stack_substrate_machinery_is_load_bearing.md` — affirmative finding earned by v0.4a.2.
- **NEW** (optional): `project_belief_stack_minimum_sufficient_state.md` — Arm C's Pareto dominance as a candidate minimum-sufficient projection target.

Site-surface revisions (essay, spec empirical-status section, case-study page, pre-reg page) are queued separately as Session-level work, distinct from this report.

---

## §12 Summary

v0.4a was the cleanest falsification experiment the Belief Stack research program has run. It surfaced one finding the program was unprepared for (projection-side discipline is not load-bearing) and one finding the program had hoped for but not isolated (substrate transformation is load-bearing above and beyond compression). Combined, the two findings produce a sharper and more empirically defensible architectural picture than v0.3 alone could claim.

The thesis survives. The mechanism story sharpens. The architecture splits more cleanly into substrate machinery (rich) and AI projection (sparse) than the v0.3 spec articulated. Human inspection-side projection remains rich, preserving the dual-consumer pattern.

The next experiment is cross-substrate replication. If C-style projection generalizes beyond Claude Code sessions, the architecture earns its category claim. If it does not, the operational-vs-sensemaking architectural split candidate (per `project_belief_stack_open_questions_post_v03.md`) becomes the live question.

---

*Report drafted 2026-06-04. Authored against the locked pre-registration without amendments after data flowed. Cross-references: [`BELIEF_STACK_PRE_REGISTRATION_v0.4a.md`](BELIEF_STACK_PRE_REGISTRATION_v0.4a.md), [`belief_stack_v0_3/BELIEF_STACK_REPORT_v0.3.md`](../belief_stack_v0_3/BELIEF_STACK_REPORT_v0.3.md), `project_belief_stack_*.md` memories.*
