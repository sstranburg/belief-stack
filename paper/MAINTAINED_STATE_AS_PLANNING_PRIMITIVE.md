# Reducing the Reconstruction Tax in Long-Running LLM Workflows

*Maintained State as a Planning Primitive*

**Working draft v0.4 (cost-led title; three-consequences abstract restructure)**
**Date:** 2026-06-05
**Author:** Susan Stranburg
**Status:** Working draft — paper-in-progress. v0.4 swaps the title to lead with the cost framing the industry rhetoric centers on, and restructures the abstract around the three-consequences positioning. Same data as v0.3; no new experiments. One required experiment remains before the empirical claim earns full generality: cross-substrate replication (v0.4c2).

---

## Abstract

Long-running agents incur a *reconstruction tax* when planning from raw interaction history: each planning step re-derives the current world model from the same evolving evidence. The cost is observable on three axes simultaneously — input tokens, latency, and planning correctness — and a maintained-state substrate addresses all three.

Across a sequence of pre-registered experiments on operational workflow traces (164 Claude Code session logs, 75 paired single-next-action planning questions, four LLMs from three providers), sparse substrate-derived maintained-state projections reduced input-token consumption by roughly an order of magnitude while improving planning correctness:

> *Across four models, sparse substrate-derived maintained-state projections used 241 mean input tokens vs 2,502 for raw history (roughly one-tenth), at 99.0% planning correctness vs 89.3% for raw history. Latency dropped ~3× on the single-model experiment that measured it directly.*

A first experiment (*v0.3*) showed a maintained-state projection outperforming raw workflow history by 8 percentage points (98.7% vs 90.7%) on 14% of the input tokens and 3.2× lower latency on a single model (`gpt-4o-2024-08-06`). A mechanism-isolation experiment (*v0.4a.1*) found that this lift was not explained by the spec's discipline of warrants or lifecycle markers rendered into the planner's context — a sparse bare-name projection (`belief_type :: claim`, no warrant fields, no lifecycle marker) was strictly Pareto-dominant on every measured axis among the structured arms tested at a 285-token budget. A compression-control experiment (*v0.4a.2*) ruled out compression itself: an LLM prose summary of the raw log at matched budget reached 90.7%, below the 97.3% achieved by substrate-derived projections.

A cross-model replication (*v0.4c1*) extended the program to four models from three providers (`gpt-4o-2024-08-06`, `claude-opus-4-7`, `gemini-2.5-pro`, `claude-haiku-4-5-20251001`). Every maintained-state arm improved over raw history directionally on every model. The separation from compressed raw history was model-dependent: it held clearly for Opus, partially for GPT-4o, failed on Gemini Pro with thinking, and reversed on Haiku's raw-log baseline. The result supports maintained state over raw reconstruction, while narrowing the compression-control claim.

We interpret the combined findings as evidence that maintained state functions as a distinct planning substrate rather than a better summarization strategy. The load-bearing operation is the substrate transformation — filtering to currently-held beliefs, dedup-clustering, ranking — not the rendering of richer warrant or lifecycle metadata into the planner's context. The implementation we used to produce these results is reported in §3.2; it is one of multiple possible implementations of maintained state, and the empirical claim is independent of the specific implementation choice.

**The architecture's value proposition decomposes into four consequences of the same root property:** smaller planner inputs, faster planning per call, better planning correctness on measured operational tasks, and a human-inspectable state substrate. Latency and planning correctness are directly measured. Input-token reduction is measured; *net* end-to-end economics depends on extraction, storage, and maintenance costs not measured here (v0.4b scope). Inspectability is an architectural property of the asymmetric-projection design — the substrate preserves warrants and lifecycle for human inspection while the planner consumes sparse names — and is reported as design-time, not as a measured governance outcome.

Results are bounded to operational workflow substrate (Claude Code session logs), a single budget regime (~285 tokens), and fixtured belief extraction. Cross-substrate replication is the one experiment that remains required before the empirical claim earns its full generality. End-to-end maintenance economics is an open question but does not block the planning-side claim. Governance-outcome validation of the human-inspectability consequence is a separate research direction.

---

## 1. Introduction

Long-running agents — coding assistants, DevOps assistants, customer-support agents, workflow agents — face a state-tracking problem that single-turn systems do not. Their decisions depend on workflow state that evolves over hundreds or thousands of interaction turns: whether validation has actually completed, whether a permission has been revoked, whether a prior fix attempt failed, whether "done" still holds. Current systems typically maintain this workflow state implicitly, asking the model to reconstruct it from raw history at each planning step.

We call this the *reconstruct-world-model-every-step tax*. It produces three observable costs: large input-token consumption per planning step, latency proportional to the amount of context the model must process, and a class of *operational error* in which the agent acts on a stale or incorrect understanding of current state. Examples include false-completion claims, premature actions taken before approval is confirmed, repeated failure loops in which the agent re-attempts the same failed operation, and stale-validation assumptions in which the agent treats validation that has been superseded as still authoritative.

A natural architectural alternative is to maintain workflow state explicitly: derive a representation of currently-held beliefs from the event stream, project that representation into the planner's context, and let the planner reason against a current view of the world rather than reconstructing one from raw history. We tested this alternative against three different baselines and across multiple projection formats, using a specific implementation we developed for the purpose. We refer to the implementation as the *Belief Stack*; it maintains beliefs as objects with a *claim + warrant + lifecycle* contract in the substrate, and projects sparse views of those beliefs into the planner's context. The paper's contribution is the empirical claim that maintained state beats reconstruction on operational planning tasks. The implementation choices that produced this result are described in §3.2 and are not the contribution; the same claim could in principle be tested with other implementations of maintained state.

This paper reports a pre-registered experimental program designed to test whether maintained state functions as a distinct planning substrate, and if so, to identify which features of the substrate are load-bearing. The program comprises four phases:

1. **v0.3 (planning-side experiment).** Tests whether a maintained-state projection outperforms a strong raw-context baseline on planning correctness.
2. **v0.4a.1 (mechanism ablation).** Tests which features of the spec's `claim + warrant + lifecycle` projection rendering are load-bearing, by varying the projection format across five arms at matched budget.
3. **v0.4a.2 (compression control).** Tests whether the v0.3 / v0.4a lift is attributable to compression alone, by adding a sixth arm in which the raw log is compressed under the same protocol that produces the maintained-state projection.
4. **v0.4c1 (cross-model replication).** Tests whether the thesis holds across model families by re-running the four-arm subset (A / A' / B / C) on four models from three providers.

Each phase was pre-registered with locked interpretation rules and action commitments before any data flowed. Amendments to pre-registrations were re-locked and versioned (v0.4a → v0.4a.1 → v0.4a.2; v0.4c1 → v0.4c1.1) with explicit amendment logs. The same substrate, the same scoring methodology, and the same evaluation set were used across all phases to maximize cross-experiment comparability.

The paper proceeds as follows. §2 places the work in the context of related approaches to LLM state management. §3 describes the substrate and the scoring methodology. §4 reports the four experimental phases. §5 interprets the combined findings, distinguishing what the evidence supports from what the v0.3 interpretation got wrong and where the cross-model picture narrowed an earlier claim. §6 discusses limitations. §7 identifies the one remaining experiment required for full empirical generality.

---

## 2. Background and related work

The architectural question — what should an LLM-driven agent consume at planning time? — has received several incomplete answers in current practice.

**Conversation memory and raw scrollback.** The default in most chat-based agents is to feed the model the recent conversation history (or a subset of it) and let the model reconstruct relevant state. This is the baseline our v0.3 *raw K=20 log* arm represents. It places no architectural commitment on what state to maintain; the model derives state implicitly each turn.

**Summarization buffers.** Frameworks such as LangChain's `ConversationSummaryMemory` compress the conversation history into a narrative summary, replacing or supplementing the raw scrollback. This reduces token consumption but does not impose structure on the summarized state. The summary is also lossy in ways that are not explicit at consumption time.

**Vector retrieval (RAG).** Long-term memory systems retrieve relevant past content via embedding similarity at query time. This is stateless at query time: the system fetches fragments rather than maintaining a current world model. It does not model lifecycle (when a fact stops being true), provenance (why a fact is held), or contradiction (which prior beliefs the current fact refutes).

**Knowledge graphs and triple stores.** Symbolic-knowledge approaches maintain facts as `(subject, predicate, object)` triples. These have provenance and structure but typically lack first-class lifecycle semantics: facts are added, replaced, or removed, not *contradicted* or *retired*.

**Workflow / plan-graph state.** Frameworks such as LangGraph and AutoGen explicitly maintain finite-state representations of the agent's task progress (current step, sub-goal status, pending tool calls). This is execution state, not belief state: it captures *what the system has done*, not *what the system currently holds to be true about the world*.

**Reflection-based memory.** Approaches such as Reflexion have the agent periodically reflect on past actions and update an internal memory of lessons learned. This is closer to belief maintenance but is procedural rather than architectural; the reflection output is unstructured text and is not type-checked against any contract.

What distinguishes the *belief stack* pattern from these is the substrate-side contract — *claim + warrant + lifecycle* — and the explicit modeling of contradiction and retirement as first-class events. The empirical question this paper addresses is whether this contract pays off as a planning substrate, and if so, which of its features are load-bearing.

---

## 3. Substrate and method

### 3.1 Source data

The substrate for all experiments is a corpus of 164 Claude Code session logs comprising approximately 20,190 evaluation turns. Sessions vary in length and complexity; each captures a real coding-assistant interaction including user messages, assistant messages, tool invocations, and tool outputs. The corpus was assembled for an earlier study (OB-001) and reused across OB-002, v0.3, v0.4a, and v0.4c1 to maximize cross-experiment comparability.

### 3.2 Belief substrate

Beliefs are derived from the event stream by a rule engine that produces a database of `belief_instances` and `belief_events`. Each belief carries:

- `belief_type` — a category from a fixed vocabulary (e.g., `validation_pending`, `action_blocked`, `pipeline_running`, `report_ready`)
- `operational_claim` — the specific assertion being made
- `holder` — assistant, user, or tool
- `turn_first_seen`, `turn_last_updated`
- `warrant_evidence_turns` — turns at which supporting evidence was observed
- `counterevidence_turns` — turns at which contradicting evidence was observed
- `current_authority` — `asserted_by_assistant`, `confirmed_by_user`, or `confirmed_by_tool`
- `decay_status` — `fresh` or `stale`
- `revision_trail` — a sequence of lifecycle events (`born`, `refreshed`, `weakened`, `contradicted`, `retired`)

The substrate contains 13,481 belief instances across the 164 sessions. For the experiments reported here, beliefs are *fixtured* — derived ahead of time and held constant — rather than extracted live from the event stream. Live extraction is identified as an open question (§7).

### 3.3 Evaluation set

The evaluation set is 75 paired single-next-action planning questions, balanced across five task categories (15 per category):

- `approval_status` — *is the assistant authorized to proceed with the proposed next action?*
- `validation_check` — *has validation actually completed?*
- `completion_check` — *is the assistant's claim of completion warranted?*
- `readiness_check` — *should the assistant proceed, pause, or ask for clarification?*
- `repeated_failure` — *is the current failure the same kind as a recent prior failure?*

Each question is anchored to a specific `(session_id, turn_idx)` in the corpus. The evaluation task is a single next-action judgment: given a particular shape of context describing the session's state at turn T, the model is asked one of the five judgment questions about that moment.

### 3.4 Generator protocol

Phases 1–3 (v0.3, v0.4a.1, v0.4a.2) used `gpt-4o-2024-08-06` at temperature 0 with fixed seed `20260601`, top-p 1.0, and a 1500-token output cap. Phase 4 (v0.4c1) extended generation across four models from three providers. Per-provider configurations were locked at v0.4c1 and amended to v0.4c1.1 after build-time API verification surfaced two real provider behaviors:

| Model | Provider | Locked config |
|---|---|---|
| `gpt-4o-2024-08-06` | OpenAI | T=0, seed=20260601, full v0.4a parity |
| `claude-opus-4-7` | Anthropic | API rejects the `temperature` parameter; uses default sampling; no seed |
| `gemini-2.5-pro` | Google Gemini | T=0, seed=20260601, `thinking_budget=2048` (model requires thinking mode) |
| `claude-haiku-4-5-20251001` | Anthropic | T=0; no seed |

System prompts varied by arm to describe the format of context the arm received; user prompts were generated by a fixed template. Anti-curation discipline was applied throughout: all contexts for a given phase were generated before any answer-generation calls flowed; (question, arm, model) tuples were shuffled with a fixed seed for both answer generation and judging to prevent any single cell from completing before another started.

### 3.5 Scoring

Scoring is per-question paired across arms (and, in Phase 4, across models). A deterministic oracle (`score_operational_label.Scorer`) computes ground truth per `(session, turn, category)` from session events. An LLM judge (`gpt-5-mini-2025-08-07`, reasoning_effort=medium, fixed seed) classifies each generated answer's behavior on each metric. The judge model is held constant across all phases so only the *generator* varies in Phase 4. The combined label per `(question, arm, [model], metric)` is computed by `combine_oracle_and_judge` under an oracle-wins-on-disagreement policy.

The primary outcome metric is **planning correctness** — the fraction of paired questions on which the answer does not commit the category-relevant failure mode. Effect sizes between adjacent arms in the ablation ladder were pre-registered with a 3 percentage-point threshold for "advanced" and a 2-pp threshold for "noise floor."

### 3.6 Pre-registration discipline

Each phase was pre-registered with locked interpretation rules and action commitments before any data flowed. Amendments to pre-registrations (when build-time audits surfaced ambiguities in the locked design) were re-locked and versioned with explicit amendment logs. The full pre-registrations, reports, and supporting data are available in the project repository under `belief_stack_v0_3/`, `belief_stack_v0_4a/`, and `belief_stack_v0_4c1/`.

---

## 4. Experimental program

### 4.1 Phase 1 — v0.3 (planning-side experiment)

v0.3 tested whether a maintained-state projection outperforms raw context on planning correctness. Three arms, each consuming the same 75 questions:

- **Arm A** (raw K=20 log + strong baseline reconstruction prompt) — the model receives the last 20 turns of the session as raw context, with a system prompt instructing it to reconstruct the current workflow state from that raw history.
- **Arm B** (belief overlay only, no raw log) — the model receives only a §3.5a-clustered, ranked, budget-bounded projection of the substrate's currently-active beliefs.
- **Arm C** (belief overlay + minimal scratchpad) — the model receives the same overlay as Arm B plus the last K=3 turns of raw history for execution-time scratchpad.

**Results.**

| Arm | Mean input tokens | Mean wall (s) | Planning correctness |
|---|---|---|---|
| A | 2,037 | 3.55 | 90.7% |
| **B** | **285** | **1.11** | **98.7%** |
| C | 592 | 1.29 | 94.7% |

Arm B outperformed Arm A by 8 percentage points on 14% of the input tokens and 31% of the wall-clock latency. Zero questions exhibited a *grounding-bankruptcy* pattern in which Arm B failed while both Arm A and Arm C succeeded. The pre-registered interpretation: **maintained state is a planning primitive.** The model was not under-informed by the smaller, structured context; it was *over-burdened by reconstruction* in the larger raw context.

### 4.2 Phase 2 — v0.4a.1 (mechanism ablation)

v0.3's interpretation attributed the lift to the spec's full `claim + warrant + lifecycle` discipline rendered in the projection. v0.4a.1 tested this attribution by adding two intermediate arms to form a five-arm ladder, each successive arm adding one element of the discipline at a matched ~285-token budget cap:

| Arm | Format | Discipline level |
|---|---|---|
| A | Raw K=20 log + strong baseline | None — raw context |
| B | LLM prose summary of clustered substrate | Maintained + compressed; no structure |
| C | `belief_type :: claim` per cluster | Maintained + structured; no warrant, no lifecycle |
| D | C + `(auth=…, evidence=[…], decay=…, last=…)` per cluster | Structure + warrants; no lifecycle marker |
| E | D + `[active]/[weakened]/[contradicted]` prefix | Full discipline |

The pre-registered prediction, if the architecture's interpretation of v0.3 were correct, was a strictly increasing ladder: **E > D > C > B > A**, with each step crossing the 3-pp threshold.

**Results.**

| Arm | Errors / 75 | Planning correctness | Mean input tokens |
|---|---|---|---|
| A | 6 | 92.0% | 2,037 |
| B | 2 | 97.3% | 297 |
| **C** | **2** | **97.3%** | **208** |
| D | 3 | 96.0% | 333 |
| E | 3 | 96.0% | 370 |

The ladder did not hold. The only transition that crossed the 3-pp threshold was B − A (+5.3 pp). The remaining transitions — C − B (0.0 pp), D − C (−1.3 pp), E − D (0.0 pp) — fell within the 2-pp noise floor. The pre-registered Outcome 5 fired: *lifecycle/warrant discipline does not add measurable value over maintained summaries on this substrate*.

Arm C — the most stripped-down projection, with no warrant fields and no lifecycle marker — strictly Pareto-dominated arms D and E on every measured axis (better correctness, fewer tokens, faster wall, lower judge-oracle disagreement) and tied Arm B on correctness while winning on every other axis.

A second observation: the cost and the slight correctness regression both concentrate at the C → D transition (the introduction of warrant fields into the projection). The D → E transition (the addition of the lifecycle marker) is near-free on every axis. The warrant rendering — not the discipline as a whole — is the specific subcomponent that does not pay at this budget on this substrate.

### 4.3 Phase 3 — v0.4a.2 (compression control)

v0.4a.1 ruled out projection-side discipline as the mechanism but left a thesis-level ambiguity unresolved. The B − A lift could be explained by either (a) **compression** — Arm B is shorter than Arm A — or (b) **substrate transformation** — Arm B's input is the rule-engine-derived view of currently-active beliefs, while Arm A's input is raw chronological log. v0.4a.2 added a single arm to disambiguate:

- **Arm A′** — LLM prose summary of the raw K=20 log at the same ~285-token budget that produced Arm B. Same generator, same temperature, same seed, same answer-time system prompt as Arm B. Only the source differs (raw log vs §3.5a-clustered active beliefs).

The pre-registered outcome classes were: *A′ near A* (compression alone does not explain the lift; thesis maximally supported), *A′ near B/C* (compression alone explains the lift; thesis substantively weakened), *B beats A′ by ≥ 3 pp* (substrate transformation does meaningful work above compression), or *between* (partial contribution).

**Results.**

| Arm | Planning correctness | Mean input tokens |
|---|---|---|
| A | 92.0% | 2,037 |
| **A′** | **90.7%** | **259** |
| B | 97.3% | 297 |
| C | 97.3% | 208 |

A′ − A = −1.3 pp, well within the 2-pp noise floor. The pre-registered *A_prime_near_A* outcome fired: **compression of raw log alone does not reach maintained-substrate correctness** on `gpt-4o-2024-08-06`. The 5.3-pp B − A lift measured in v0.3 and replicated in v0.4a.1 is — on this model — attributable to the substrate transformation, not compression. (Phase 4 narrows the generality of this isolation claim; see §4.4.)

### 4.4 Phase 4 — v0.4c1 (cross-model replication)

v0.4c1 tested whether the v0.3/v0.4a thesis holds across model families. The substrate, the evaluation set, the prompts, and the scoring methodology were held constant. The generator varied across four models from three providers; the arm set was the four-arm subset A / A' / B / C, sufficient to test the thesis without re-running the full mechanism ablation per model. Total cells: **1,200** (75 questions × 4 arms × 4 models). Zero failures across all 1,200 generation calls and all 1,200 judge calls.

**Per-model planning correctness.**

| Model | A | A' | B | C |
|---|---|---|---|---|
| `gpt-4o-2024-08-06` | 89.3% | 93.3% | 96.0% | **100.0%** |
| `claude-opus-4-7` | 88.0% | 92.0% | 98.7% | 98.7% |
| `gemini-2.5-pro` | 82.7% | 94.7% | 94.7% | **97.3%** |
| `claude-haiku-4-5-20251001` | 97.3% | 93.3% | 100.0% | **100.0%** |

**Cross-model averages.**

| Arm | Avg input tokens | Avg planning correctness |
|---|---|---|
| A | 2,502 | 89.3% |
| A' | 358 | 93.3% |
| B | 316 | 97.3% |
| **C** | **241** | **99.0%** |

The thesis holds on every model tested: every B−A and every C−A delta is positive. The cross-model headline:

> *Across four models, sparse substrate-derived maintained-state projections were the strongest average planning surface: 99.0% correctness at 241 mean input tokens, compared with 89.3% at 2,502 tokens for raw history and 93.3% at 358 tokens for compressed raw history.*

Arm C is the cross-model Pareto winner: it is the highest-correctness arm or tied for the highest, and the lowest-token arm or tied for the lowest, on all four models.

**Per-model compression-vs-substrate (B − A' deltas).**

| Model | B − A' (pp) | Pre-registered class |
|---|---|---|
| `claude-opus-4-7` | +6.7 | full replication |
| `gpt-4o-2024-08-06` | +2.7 | partial replication |
| `gemini-2.5-pro` | +0.0 | compression equivalent |
| `claude-haiku-4-5-20251001` | +6.7 (but A' < A by −4.0) | unclassified |

The compression-vs-substrate separation that v0.4a.2 measured on `gpt-4o-2024-08-06` is **model-dependent**. It held clearly on Opus, partially on GPT-4o (only Arm C cleared the threshold; Arm B did not), failed on Gemini (B = A' at 94.7%), and reversed on Haiku in a different sense (Haiku's A' was *worse* than its own raw A — Haiku appears to lose information when summarizing its own raw log).

The pre-registered cross-model classifier returned `compression_finding_does_not_generalize`, triggering the locked action commitment: *"The maintained-state-vs-raw lift holds across models, but compression-vs-substrate isolation depends on model behavior."* The thesis is preserved; the mechanism subclaim narrows.

**A separate evidentiary line: Gemini thinking telemetry.** On `gemini-2.5-pro` (the only thinking-mode model in the set), the mean internal thinking tokens varied by arm: 954 on Arm A (raw history), 628 on Arm A' (compressed), 713 on Arm B (substrate prose), 691 on Arm C (substrate names). Gemini spent the most thinking tokens on the raw-history arm and 25–30% fewer thinking tokens on the projected arms. This is a single-model observation, not a controlled comparison. It is consistent with the reconstruction-tax framing — when context already projects current state, the model spends less time internally reconstructing it — but does not isolate the effect. A working hypothesis (not a finding from this experiment) is that the thinking phase compensates for compression on Gemini: where a non-thinking model needs the substrate transformation to surface what's currently true, a thinking model can reconstruct from a prose summary during its thinking phase. Resolving this hypothesis requires a Gemini-thinking-budget ablation (out of scope for v0.4c1).

---

## 5. Combined interpretation

### 5.1 What survives — strengthened by cross-model

Two claims survive across the program. Both are stronger after v0.4c1 than after v0.4a.

**Maintained state is a planning primitive.** This claim now has three independent empirical supports:

1. *v0.3:* substrate-derived projection beats raw context (98.7% vs 90.7%) at 14% of the input tokens on `gpt-4o-2024-08-06`.
2. *v0.4a.2:* LLM-compression of raw context at matched budget does *not* reach the maintained-substrate correctness on `gpt-4o-2024-08-06` (90.7% vs 97.3%).
3. *v0.4c1:* the substrate-derived lift over raw context replicates on all four tested models (every B−A and C−A delta is positive). Cross-model averages: 99.0% / 241 tokens (Arm C) vs 89.3% / 2,502 tokens (Arm A).

**The substrate transformation appears load-bearing on non-thinking models.** What does the planning-useful work is the rule-engine pipeline upstream of the projection — filtering beliefs to currently-held states, clustering by `(belief_type, operational_claim)`, ranking by recency and authority. The projection format is the consumer interface, not the mechanism. Bare structured names (Arm C) reach the same correctness as prose summary (Arm B) and outperform richer renderings (Arms D, E). On non-thinking models, compression of raw log alone does not recover the lift. On Gemini's thinking model, compression and substrate projections perform similarly — leaving the cross-model substrate-vs-compression isolation as a narrowed claim (see §5.4).

### 5.2 Arm C as the cross-model Pareto reference

v0.4a identified bare structured `belief_type :: claim` (Arm C) as Pareto-dominant on `gpt-4o-2024-08-06` at the 285-token budget. v0.4c1 shows this dominance is not model-specific: on all four models tested, Arm C is the Pareto winner or tied for winner on correctness and input tokens. The minimum-sufficient-state claim from v0.4a generalizes cleanly across the model field.

### 5.3 The research arc — surviving three pre-registered challenges

The empirical contribution is best read as an arc of pre-registered challenges rather than a single headline number:

- **v0.4a** challenged the spec's discipline as the mechanism (mechanism ladder A→E). Result: the discipline rendering in the planner's context was not load-bearing; the substrate transformation was.
- **v0.4a.2** challenged the compression-of-raw alternative (Arm A' control). Result: compression alone did not recover the lift on `gpt-4o-2024-08-06`.
- **v0.4c1** challenged the model-specific-artifact alternative (four models, three providers). Result: the thesis held on all four; the compression-vs-substrate isolation narrowed to model-dependent.

After three independent opportunities to collapse under pre-registered alternative hypotheses, the surviving statement is:

> *Maintained state beats raw reconstruction across all four tested models, on this substrate, at this budget.*

The credibility of this statement comes from the survival pattern, not the magnitude of the headline number.

### 5.4 What got nuanced — compression-vs-substrate is model-dependent

The v0.4a.2 compression-control finding, on `gpt-4o-2024-08-06`, established that compression of raw log alone did not recover the substrate-derived lift on that model. v0.4c1 found that this isolation claim does not generalize cleanly to all model families:

- **Opus:** clear separation between Arm B (98.7%) and Arm A' (92.0%). v0.4a.2 isolation replicates.
- **GPT-4o (Phase 4 re-run):** partial — only Arm C (100.0%) cleared the 3-pp threshold above Arm A' (93.3%); Arm B (96.0%) did not.
- **Gemini Pro (with thinking):** Arm A' (94.7%) reached Arm B (94.7%). The compression-vs-substrate isolation failed.
- **Haiku:** Arm A' (93.3%) was worse than Arm A (97.3%) — Haiku appears to lose information when summarizing its own raw log. The classifier marked this unclassified.

The honest framing the data supports:

> *Maintained state beats raw context across all four tested models. The mechanism by which the compression-vs-substrate distinction operates is model-dependent: it isolates clearly on Opus, partially on GPT-4o, fails on Gemini's thinking model, and breaks down on Haiku where compression of its own log is itself lossy.*

v0.4c1 does not isolate the contribution of Gemini's thinking phase. The working hypothesis — thinking compensates for compression — is a future-experiment direction, not a finding (§7.3).

### 5.5 The interpretation of v0.3 that does not survive

The original v0.3 interpretation attributed the lift to the spec's full `claim + warrant + lifecycle` discipline *rendered in the planner's context*. v0.4a.1 measured no separation between arms B (prose summary), C (bare names), D (with warrants), and E (with warrants + lifecycle marker) above the 2-pp noise floor at the 285-token budget on this substrate.

The numbers v0.3 reported are not in question. They replicate cleanly in v0.4a as the B − A delta and again in v0.4c1 as the B − A and C − A deltas on every model. What was over-strong was the attribution of those numbers to projection-side discipline rather than to upstream substrate machinery. v0.4c1 reinforces the same correction: across models, the substrate-derived sparse projection (Arm C) dominates; richer projections (D, E) were not retested cross-model but the within-model pattern from v0.4a holds.

### 5.6 The implementation that produced these results

The empirical claim — *maintained state beats reconstruction* — is independent of the specific implementation that produced the result. For replicability, we describe the implementation here. It is not defended as the only viable implementation; future work could test other maintained-state schemes against the same baselines.

The implementation we used (Belief Stack) carries three structural choices that distinguish it from the baselines tested:

1. **Substrate contract.** Beliefs in the substrate are objects with `claim + warrant + lifecycle` fields. The rule engine that produces the substrate from the event stream performs filtering (excluding beliefs in `retired` or `not-yet-born` states), dedup-clustering (collapsing beliefs that share `(belief_type, operational_claim)`), and ranking (by recency and authority). v0.4a.2 evidence supports this composite substrate-side transformation as load-bearing on non-thinking models; v0.4c1 shows the planning lift it produces replicates across model families even where the specific compression-vs-substrate isolation does not.

2. **Sparse planner projection.** The view the planner consumes is bare `belief_type :: claim` per active cluster, dedup-ranked and budget-bounded. v0.4a.1 evidence supports the sparse projection at the 285-token budget on `gpt-4o-2024-08-06`; v0.4c1 evidence supports it as the Pareto reference on all four tested models.

3. **Substrate-vs-projection split.** The substrate carries rich content (warrants, lifecycle); the planner-facing projection strips this richness in favor of bare names. The implementation's choice to maintain richness in the substrate while projecting sparsely to the planner is supported empirically only on the planner side; whether other consumer surfaces (e.g., human inspection) need different projection shapes is reported as a design commitment, not a measured claim.

The empirical contribution of the paper is the claim that *maintained state beats reconstruction*, defended across the four experiments above. The implementation choices reported in this subsection are the specific design we ran the experiments on. Different implementations of maintained state — with different schemas, different rule engines, different ranking heuristics — could in principle produce the same or different results.

### 5.7 A speculative mechanism (hypothesis, not finding)

The v0.4a.1 result invites — but does not establish — a hypothesis about *why* the bare projection wins. At small budgets on a single-next-action planning task, the planner may need the *names* of currently-held beliefs (what is true now) more than it needs the *evidence chain* (why each belief is held). The substrate machinery determines which beliefs are currently held upstream; the planner consumes the result and chooses the next action consistent with them. Adding warrant fields to the projection grows the budget per belief, fits fewer beliefs in context, and adds detail the planner may not productively use at this task resolution.

The v0.4c1 Gemini-thinking observation suggests a second hypothesis: a thinking phase may functionally substitute for some of the substrate transformation. Where a non-thinking model needs the rule-engine-derived view to surface what's currently true, a thinking model can reconstruct from a less-structured prose summary during its thinking phase. The reconstruction tax then shifts from context-time to inference-time rather than disappearing.

Both are candidate mechanisms, not findings. Whether they generalize — to longer planning horizons, larger budgets, substrates where evidence chains carry more diagnostic information, or other thinking models — is unmeasured.

---

## 6. Limitations

The findings reported here are bounded in several ways that future work must address before the architectural claim can be made at full generality.

**Single substrate.** All measured results are on Claude Code session logs. Substrates with different properties — sensemaking and narrative domains where current "truth" is more ambiguous, multi-actor coordination where multiple parties' belief states must be tracked, longer-horizon planning where chains of consequence matter more — may exhibit different projection trade-offs. The single-substrate caveat is the largest remaining live risk to today's interpretation and is the experiment v0.4c2 is being designed to resolve (§7).

**Limited model coverage.** v0.4c1 tested four models from three providers, spanning two scale tiers and one thinking model. Larger frontier models, open-weight models, and reasoning models other than Gemini are not tested. Within v0.4c1, three of four models showed clear B−A and C−A lifts; Haiku showed a smaller but directionally consistent lift whose magnitude was below the pre-registered 3-pp threshold (the 3-pp threshold was calibrated to v0.4a effect sizes; smaller true effects on stronger raw baselines can fall below it without invalidating the directional claim).

**Thinking-mode confound (Gemini).** Gemini's required thinking phase is internal compute that the other three models do not have. The Gemini class-3 outcome (compression equivalence) is consistent with the hypothesis that thinking compensates for compression, but v0.4c1 does not control for this. Resolving this confound requires either ablating Gemini at different thinking budgets or adding a non-thinking Gemini model (`gemini-2.5-flash`) for within-family comparison (§7.3).

**Single budget regime.** All projection arms targeted a ~285-token cap. At higher budgets — 800 or 2,000 tokens — the richer renderings have room to fit more clusters at greater detail per belief. The Arm C Pareto dominance may not hold across budget regimes.

**Fixtured belief extraction.** Beliefs were pre-derived from the v0.1 substrate. Live extraction — a write-path rule engine deriving `belief_instances` and `belief_events` from a real event stream — was not tested. Live extraction may produce different belief sets in ways that affect projection performance.

**Single task type.** The evaluation set is 75 single-next-action planning questions. Multi-step planning, plan generation, plan repair, and other planning task variants are not tested.

**Small per-metric n.** Each category contains 15 questions. Aggregate-level effects (planning correctness across all 75 paired questions, all 300 cells per arm in v0.4c1) are reasonably bounded. Per-metric patterns are directional rather than statistically conclusive at this n.

**Judge classification dependence.** The deterministic oracle is the primary score axis, but the LLM judge is consulted to classify whether the model's free-text answer commits the failure mode. Across v0.3, v0.4a, and v0.4c1, judge-oracle conflicts run ~1.5% of metric-level judgments — low but non-zero. Primary outcomes are insensitive to judge errors at this conflict rate.

**Per-model summarizer for A' and B (v0.4c1).** In v0.4c1, each model summarized its own input for Arms A' and B. This introduces a potential confound where weaker summarizers handicap their own A' and B arms. Mitigated by reporting both A and A' per-model and by the cross-model classifier explicitly capturing per-model patterns.

**Single implementation of maintained state.** The Belief Stack implementation described in §3.2 is one specific scheme — `claim + warrant + lifecycle` substrate contract, §3.5a dedup-clustering, the OB-002 ranking heuristics. The empirical claim is independent of these specific choices; other implementations of maintained state could in principle be tested against the same baselines. The paper reports a result, not the only implementation that could produce it.

---

## 7. Required and adjacent next experiments

One experiment remains required before the empirical claim earns full generality. It is blocking for the strongest version of this paper. Cross-model replication (v0.4c1) is complete and integrated above as §4.4.

### 7.1 Cross-substrate replication (v0.4c2) — required

After v0.4c1 confirmed cross-model support for the maintained-state-over-raw-history thesis, the single largest live risk to today's interpretation is the single-substrate caveat. The same protocol — pre-registered arms, deterministic oracle, paired evaluation, anti-curation discipline — applies to a second operational substrate. The data-sourcing problem is the bottleneck; the protocol transfers cleanly. The cheapest path is re-instrumenting an additional AI-agent trace corpus (a different agent harness on a comparable task). A longer-effort path is sourcing DevOps incident logs or customer-support trajectories. The cross-substrate result is what earns the *operational planning* generality claim.

### 7.2 Adjacent experiments (not blocking publication)

Reported as planned future work but not required for the paper's empirical claim:

- **Gemini thinking-budget ablation.** Run `gemini-2.5-pro` at `thinking_budget` ∈ {512, 2048, 4096} or compare to `gemini-2.5-flash` (non-thinking) within the v0.4c1 four-arm design. Tests the *thinking-compensates-for-compression* hypothesis directly. Cheap to run; clarifies a specific narrowing in this paper.
- **End-to-end maintenance economics.** v0.4a and v0.4c1 measured planning-side consumption only. End-to-end economics depends on extraction, storage, and maintenance costs that these planning-side experiments do not measure; v0.4b is scoped to measure that net-value frontier on a real workload. The planning-side efficiency we report is independent of this measurement; the system-level net-value question is honestly noted as open.
- **Budget-floor scan.** v0.4a sets an upper bound on the *minimum-sufficient* projection at ~208 tokens; v0.4c1 confirms cross-model dominance at ~241 mean tokens. The actual floor — and whether the descent is gradual or cliff-shaped — is unmeasured.
- **Multi-step planning.** The single-next-action task may be uniquely friendly to compact maintained state. Multi-step planning may rebalance the projection trade-off.
- **Cross-model mechanism replication.** v0.4c1 re-ran the four-arm subset (A / A' / B / C) on four models, sufficient for the thesis test. The full mechanism ladder (Arms D and E) was not re-run cross-model. Whether projection-side discipline gains value on other models is unmeasured.

Beyond these, the broader Belief Stack research program — substrate-side write-time discipline, lifecycle theory, human-inspection projection optimization, sensemaking substrate transfer, governance and intervention studies — produces papers of its own. None of them block the empirical claim reported here.

---

## References and artifacts

The full experimental artifacts — pre-registrations, executable code, generated data, and reports — live in the project repository at `github.com/sstranburg/topicspace-core`. Key references for replication:

- **v0.3 pre-registration:** `belief_stack_v0_3/BELIEF_STACK_PRE_REGISTRATION_v0.3.md`
- **v0.3 report:** `belief_stack_v0_3/BELIEF_STACK_REPORT_v0.3.md`
- **v0.4a.2 pre-registration (locked at v0.4a → v0.4a.1 → v0.4a.2):** `belief_stack_v0_4a/BELIEF_STACK_PRE_REGISTRATION_v0.4a.md`
- **v0.4a combined report (v0.4a.1 + v0.4a.2):** `belief_stack_v0_4a/BELIEF_STACK_REPORT_v0.4a.md`
- **v0.4c1 pre-registration (locked at v0.4c1 → v0.4c1.1):** `belief_stack_v0_4c1/BELIEF_STACK_PRE_REGISTRATION_v0.4c1.md`
- **v0.4c1 cross-model replication report:** `belief_stack_v0_4c1/BELIEF_STACK_REPORT_v0.4c1.md`
- **Substrate construction (OB-001):** `operational_belief_v1/`
- **Overlay rendering (OB-002 §3.5a):** `operational_belief_v2/build_overlay_context_b_v2.py`
- **Spec:** `https://topicspace.ai/research/belief-stack`

The web-facing case studies for v0.3 (and forthcoming case studies for v0.4a and v0.4c1) live under `https://topicspace.ai/research/case-studies/`.

---

## Changelog

- **v0.4 (2026-06-05)** — cost-led title swap; three-consequences abstract restructure. No new data; no new experiments. (1) Title becomes "Reducing the Reconstruction Tax in Long-Running LLM Workflows" with "Maintained State as a Planning Primitive" demoted to subtitle, leading with the cost framing the industry rhetoric centers on while preserving the thesis. (2) Abstract opening reframed to name the three observable cost axes (input tokens, latency, planning correctness) the substrate addresses simultaneously. (3) Inset paragraph foregrounds the 10× input-token reduction alongside the correctness number; latency context preserved. (4) New abstract paragraph introduces the three-consequences value structure (smaller planner inputs / better planning / human-inspectable substrate) with explicit evidence-state framing — first two measured, third design-time-not-measured. (5) Limitations note adds governance-outcome validation as a separate research direction. The discipline boundary holds: the paper still reports a measured result; inspectability is named as a structural design property only.
- **v0.3 (2026-06-05)** — cross-model replication integrated. Adds Phase 4 (v0.4c1) as a new §4.4. Abstract gains a cross-model paragraph with the paper-safe headline. §1 lists the program as four phases. §3.4 documents per-provider generator configs (locked at v0.4c1.1). §5 reorganized: §5.1 strengthens "what survives" with the third independent support; §5.2 elevates Arm C as cross-model Pareto reference; §5.3 introduces the research-arc framing (thesis survived three pre-registered challenges); §5.4 explicitly narrows the compression-vs-substrate claim to model-dependent; §5.5 retains the v0.3-interpretation correction; §5.6 updates the implementation description; §5.7 adds the thinking-compensation hypothesis. §6 retires single-model-family limitation, adds limited-model-coverage and thinking-mode-confound, and identifies single-substrate as the largest remaining live risk. §7 cuts cross-model from required (now §4.4), retains v0.4c2 as the one required next experiment, adds Gemini thinking ablation to adjacent experiments.
- **v0.2 (2026-06-04)** — scope audit. Per the locked paper-scope-discipline memory, the paper is narrowed to a result paper: the empirical claim is the contribution; the Belief Stack implementation is reported in support but not defended as a primary contribution. Specifically: (1) Abstract ¶3 reworked to remove "we sketch the architecture this evidence implies" overreach; (2) §1 reframed Belief Stack as the implementation we tested with, not the architecture we propose; (3) §5.3 renamed from "The architecture this evidence implies" to "The implementation that produced these results" and rewritten to describe implementation choices honestly; (4) §5.4 marked as hypothesis-not-finding; (5) §6 added "single implementation of maintained state" as a limitation; (6) §7 reordered to lead with the two required experiments (cross-model + cross-substrate) and demoted human-inspection projection, warrant write-time utility, lifecycle theory, governance to "different papers" framing.
- **v0.1 (2026-06-04)** — initial working draft. Covers v0.3, v0.4a.1, v0.4a.2. Open directions included cross-substrate replication (most important), budget-floor scan, end-to-end economics, model variance, warrant write-time utility, human-inspection measurement, multi-step planning.

---

*Working draft. The one remaining experiment required for the strongest version of the empirical claim is cross-substrate replication (v0.4c2). End-to-end maintenance economics is an open question that does not block the planning-side claim. The paper's claims should be re-anchored against each new experiment per the same pre-registration discipline that produced the v0.3 / v0.4a / v0.4c1 results.*
