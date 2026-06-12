# Belief Stack v0.3 — Pre-Registration (DRAFT)

**Status:** **LOCKED — eligible for execution.**
**Date drafted:** 2026-06-03  ·  **Locked:** 2026-06-03
**Predecessors:**
- [`operational_belief_v1/OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md`](../operational_belief_v1/OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md) — inspection-side baseline (11.0% → 5.5% with unbounded overlay)
- [`operational_belief_v2/OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.2.md`](../operational_belief_v2/OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.2.md) — budgeted-overlay extension (10.7% → 5.3% at B100; smallest overlay wins)
- [`tkos_sidecar/TKOS_SIDECAR_SKETCH_v0.1.md`](../tkos_sidecar/TKOS_SIDECAR_SKETCH_v0.1.md) — runtime sidecar architecture sketch
- [`tkos_sidecar/TKOS-002_IMPLEMENTATION_NOTE_v0.1.md`](../tkos_sidecar/TKOS-002_IMPLEMENTATION_NOTE_v0.1.md) — read-path slice; dual-consumer demonstrated at fixture level

**Strategic origin:** 2026-06-03 morning conversation on whether the load-bearing value proposition of Belief Stack is agent-side context compression with provenance and lifecycle, distinct from existing agent memory and RAG. v0.1 and v0.2.2 demonstrated the inspection-side case. v0.3 tests the planning-side case.

---

## 0. The conceptual frame

> **Every agentic system today pays the reconstruct-world-model-every-step tax.**

At each step, the agent re-reads its prompt history, retrieved documents, memory stores, tool outputs, and prior plans to re-infer one question:

> *What do I currently believe?*

That reconstruction work happens implicitly inside the model's context window at every step. It is expensive in tokens, in latency, and in failure modes (stale assumptions, missed contradictions, false completions).

v0.3 is the first direct test of whether **maintained belief state** can reduce that tax: not by compressing context, but by maintaining state with provenance and lifecycle *outside* the context window, so the agent does not need to reconstruct it.

The differentiator is **maintained state with provenance and lifecycle.** A summary compresses. A belief state persists, evolves, weakens, strengthens, and can be inspected.

---

## 1. Research question

> Can an agent perform a planning task using a maintained belief state with substantially less raw context, at equal or better quality than an agent using larger raw context?

## 2. Hypotheses

### 2.1 Primary hypothesis

A lifecycle-managed belief overlay will outperform or match larger raw-context bundles, because it provides **maintained state, provenance, and freshness signals** rather than forcing the model to reconstruct the workflow state from evidence at every step.

### 2.2 Secondary hypothesis

The combination of **belief overlay + minimal targeted evidence (Arm C)** will outperform or match large raw-context bundles (Arm A) more reliably than belief overlay alone (Arm B). Arm C may represent the realistic production architecture: belief state for state-keeping, minimal evidence for execution-time detail.

### 2.3 Scope discipline (bounded claim)

The hypothesis is **bounded**. To prevent overclaim:

> **Not:** agents can plan from belief state alone.
>
> **But:** maintained belief state can support planning with less raw context, while preserving provenance and lifecycle signals that generic summaries lack.

The narrower claim is the one we have evidence for and the one we will defend.

## 3. Core claim under test

This is **not generic context compression.** A summary compresses. A belief state persists, evolves, weakens, strengthens, and can be inspected.

The claim is:

> A smaller bundle of lifecycle-managed beliefs can support planning better than a larger bundle of raw evidence, because the belief state preserves what is currently believed, why, and whether it is still valid — not because it is smaller.

The differentiator is **maintained state with provenance and lifecycle**, not compression.

## 4. Arms

| Arm | Description |
|---|---|
| **A — Raw Context Large (strong baseline)** | Agent receives large raw workflow context. **Prompt explicitly instructs the model to reconstruct workflow state from the raw history** — identify active assumptions, prior attempts, constraints, and what is still pending — before deciding the next action. This is the strongest defensible baseline; the comparison must not be vulnerable to the claim that Arm A failed because it was poorly prompted. |
| **B — Belief Overlay Small** | Agent receives compact active belief state only. No raw evidence bundle. |
| **C — Belief Overlay + Minimal Evidence** | Agent receives compact active belief state plus a small supporting evidence bundle (scratchpad-like: relevant filenames, recent tool outputs, specific parameters). Likely the realistic production architecture per §2.2. |

### 4.1 Fair-comparison constraint (load-bearing)

The experiment must distinguish *"belief state helps planning"* from *"the belief builder did extra work the raw-context arm never got."* If Arm A is starved of evidence that Arms B/C silently received via belief construction, the comparison measures substrate-builder effort, not the belief-state architecture.

**Constraint:** Arm A must receive **the same underlying evidence used to derive the belief state**. The difference between arms is whether that evidence arrives as maintained-state-with-lifecycle (Arms B, C) or as raw history that the agent must reconstruct state from at every step (Arm A, per its strong-baseline prompt in §4).

This is the only way the v0.3 comparison cleanly attributes any observed lift to the belief-state architecture itself.

### 4.2 State vs scratchpad

Belief Stack is a **state substrate**. Raw evidence may still be required as **scratchpad**. They are different objects and serve different functions in planning.

| State (what Belief Stack tracks) | Scratchpad (raw evidence) |
|---|---|
| active assumptions | exact filenames |
| constraints | exact errors |
| prior attempts | exact line numbers |
| workflow status | raw parameter values |

The v0.3 hypothesis is that **maintained state** can substitute for the work of reconstructing state from raw evidence at every step. The hypothesis is **not** that scratchpad can be eliminated. Arm C tests precisely this split: belief state for state-keeping, minimal targeted evidence for execution detail.

## 5. Task type

Workflow planning task with **changing state**. Examples:

- user goal changes midstream
- prior assumption becomes contradicted
- tool output introduces new constraint
- agent must decide next action

The task surface should reward correct handling of state evolution, not just one-shot question-answering.

## 6. Evaluation criteria

### 6.1 Planning quality (primary outcome)

1. Correct next action
2. Avoids acting on stale or contradicted belief
3. Identifies uncertainty when evidence is missing
4. Produces coherent plan
5. Can explain which belief justified the action

### 6.2 Operational telemetry (primary outcome — quantifies the tax)

Each arm tracks, per planning task:

- Cumulative tokens consumed across the workflow
- Latency per planning step
- Total latency across the workflow

The planning-quality result is the headline. The token / latency result **quantifies the reconstruct-world-model-every-step tax** — turning the §0 framing into a measured number rather than rhetoric.

### 6.3 Failure-mode catalog

Inheriting v0.2.2's deterministic metrics where applicable; adding one v0.3-specific failure mode.

| Failure mode | Source |
|---|---|
| Stale-validation assumption | v0.2.2 |
| Premature action | v0.2.2 |
| False-completion claim | v0.2.2 |
| Repeated-failure loop | v0.2.2 |
| Missing pause | v0.2.2 |
| **Grounding bankruptcy** (new) | v0.3 |

**Grounding bankruptcy** — the agent has the correct high-level workflow state (active assumptions, constraints, pending validations) but lacks the evidentiary detail needed to execute correctly (specific filenames, exact error messages, raw parameters). The belief state is right; the scratchpad is missing. This is the predicted failure mode of Arm B if it fails, and the failure mode Arm C is designed to prevent.

## 7. Success condition (locked)

Arm **B** or arm **C** matches or beats arm **A** under both gates simultaneously:

- **Token gate (D7):** Mean input-token count is **≤ 50%** of Arm A's mean input-token count across the 75-question set.
- **Quality gate (D8):** Aggregate planning-correctness rate is **within 2 percentage points** of Arm A's rate, **or** strictly exceeds Arm A's rate.

A "win" requires both gates to clear. Either gate failing means the headline claim is not supported for that arm.

## 8. Failure condition (locked)

Arm A outperforms both belief-based arms on planning correctness by more than 2 percentage points,
**or** belief-based arms do not achieve the ≥ 50% token reduction (rendering the "materially fewer tokens" claim unfalsifiable for them),
**or** belief-only planning (Arm B) fails specifically via the **grounding-bankruptcy** failure mode at a materially higher rate than Arm C — indicating that the architecture needs scratchpad-as-evidence to function, which would weaken the headline "maintained state for planning" claim.

## 9. What this would prove

If successful, v0.3 supports the claim that Belief Stack is not only useful for **human inspection** (the v0.1 / v0.2.2 result). It is also useful as a **runtime planning substrate for agents.**

## 10. What this would not prove

It would not prove agents can fully replace context with beliefs. It would only show that, for **bounded planning tasks**, lifecycle-managed belief state can reduce the need to reconstruct workflow state from raw context.

## 11. Locked language

| Use | Avoid |
|---|---|
| maintained state with provenance and lifecycle | generic context compression |
| maintained belief state | agent memory |
| planning from belief state | belief state alone solves everything |
| lifecycle-managed belief overlay | summarized context |
| warrant-bearing claims | compressed prompt |
| the reconstruct-world-model-every-step tax | inference cost |
| belief state for state, scratchpad for detail | beliefs replace context |

The language discipline matters: "context compression" puts this in a crowded category (chunking, summarization, RAG variants). The differentiated framing is that the maintained state is **warranted and lifecycle-managed**, and that scratchpad-style raw evidence has its own legitimate place in execution. Use the **reconstruct-world-model-every-step tax** as the named operational pain point this work is targeted at.

---

## 12. Pending decisions before lock

This draft establishes the **framing and arms**. The following decisions are still open and must be settled before locking. Each one is the kind of choice that determines whether the experiment is interpretable.

| # | Decision | Status | Resolution / notes |
|---|---|---|---|
| D1 | Agent / generator model | OPEN | Options: gpt-4o-2024-08-06 (parity with v0.1/v0.2.2); Claude Sonnet; both. Family separation question per v0.2.2; cross-model is a v0.4 question. Leaning gpt-4o for parity unless a planning-specific reason emerges. |
| **D2** | **Task substrate** | **RESOLVED → REUSE v0.1/v0.2.2 corpus** | **The locked v0.1 question set already reads as single-next-action planning questions** (e.g. *"At turn 2987, can the assistant act on the proposal without waiting for user confirmation?"*, *"At turn 312, are there outstanding pending actions before declaring completion?"*). All five categories (approval_status, validation_check, completion_check, readiness_check, repeated_failure) map cleanly onto next-action decisions. No reframing of question text needed; oracle from `score_operational_label.Scorer` already determines correct action per turn. Maximizes cross-experiment comparability with v0.1 / v0.2.2 and avoids fresh-fixture-construction risk. |
| D3 | Token budgets per arm | OPEN — depends on D2 | A: 4–8K (matched to v0.2.2 raw-log); B: 100–500 (matched to v0.2.2 overlay arms); C: 100 overlay + 500 evidence. Will be finalized once D2 lands. |
| D4 | Task / question count | OPEN | 75 (parity with v0.1/v0.2.2); larger if planning needs more variance; smaller pilot first. Pilot recommended given the new task type. |
| **D5** | **Planning task definition** | **LEANING** | **Single next-action selection.** Multi-step is tempting but single-next-action is cleaner to score and easier to falsify cleanly. v0.3 tests whether belief state changes the next justified action. Multi-step plans can be a follow-up if v0.3 lands. |
| **D6** | **Evaluation methodology** | **LEANING** | **Deterministic programmatic gate for the primary planning-correctness outcome. LLM judge used only as a secondary signal for explanation quality.** The primary outcome must not depend mainly on an LLM judge. |
| **D7** | **"Materially fewer tokens" threshold** | **LOCKED** | **Mean input-token count per arm must be ≤ 50% of Arm A's mean input-token count** across the 75-question set. Measured per question; reported as mean reduction with min/p10/p50/p90/max for full distribution. |
| **D8** | **"Matches Arm A" threshold** | **LOCKED** | **Belief arm's aggregate planning-correctness rate must be within 2 percentage points of Arm A's rate, OR strictly exceed it.** Both the D7 token gate and the D8 quality gate must clear simultaneously for a "win." |
| D9 | Belief overlay rendering | OPEN | Reuse OB-002 §3.5a compressed line format (likely); new format optimized for planning context (if it justifies itself); both. |
| D10 | Failure-mode catalog | PARTIAL | Inherit v0.2.2's five deterministic metrics + add Grounding bankruptcy (per §6.3). Confirm whether planning surface needs additional v0.3-specific modes once D5 is locked. |

D2, D7, and D8 locked 2026-06-03. D5 (single-next-action) and D6 (deterministic gate primary, LLM judge for explanation only) operate at the user-leaning resolution. D1, D3, D4, D9, D10 carry forward from v0.1/v0.2.2 conventions and require no fresh decision before execution.

## 13. Anti-curation discipline (carry-forward)

- Task / question text generated blind to the substrate state that will be ranked.
- Belief overlay rendering policy (ranking, dedup, budget) locked before answer generation.
- Seeds, model IDs, judge configurations locked here before any data flows.
- All failures preserved with metadata; no silent truncation.
- No prompt tuning after seeing outputs.

These are the same constraints v0.1 and v0.2.2 ran under and that produced credible results. They apply to v0.3 unchanged.

## 14. Non-goals

- v0.3 does not test multi-agent coordination.
- v0.3 does not test long-horizon (multi-hour) planning.
- v0.3 does not test belief overlay generation from a real event stream — overlays are rendered from the locked v0.1 substrate format.
- v0.3 does not claim a general theory of agent reasoning. It tests a specific, bounded planning claim on a specific substrate.
- v0.3 does not displace the human-inspection surface. The dual-consumer framing remains load-bearing; v0.3 just tests the agent surface specifically.

---

## 15. Framing question — RESOLVED 2026-06-03

The earlier open question (does the v0.3 design distinguish "belief state helps planning" from "the substrate-builder did extra work Arm A never got"?) is resolved as the **fair-comparison constraint** in §4.1: Arm A must receive the same underlying evidence used to derive the belief state.

This is now a load-bearing design constraint, not an open question.

---

*End of locked pre-registration. Eligible for execution as of 2026-06-03.*
