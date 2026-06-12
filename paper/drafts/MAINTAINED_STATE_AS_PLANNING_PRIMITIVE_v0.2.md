# Maintained State as a Planning Primitive

*Evidence from operational agent workflows*

**Working draft v0.2 (scope audit)**
**Date:** 2026-06-04
**Author:** Susan Stranburg
**Status:** Working draft — paper-in-progress. v0.2 narrows the paper to a result-paper scope per the locked paper-scope-discipline memory (the contribution is the empirical claim; the Belief Stack implementation is reported in support, not defended as a primary contribution). Iterated as v0.4c1 (cross-model) and v0.4c2 (cross-substrate) results land.

---

## Abstract

Long-running agents incur a *reconstruction tax* when planning from raw interaction history: each planning step re-derives the current world model from the same evolving evidence. Across a sequence of pre-registered experiments on operational workflow traces (164 Claude Code session logs, 75 paired single-next-action planning questions), compact maintained-state projections improved planning correctness while reducing token consumption and latency.

A first experiment (*v0.3*) showed a maintained-state projection outperforming raw workflow history by 8 percentage points (98.7% vs 90.7%) on 14% of the input tokens and 3.2× lower latency. A mechanism-isolation experiment (*v0.4a.1*) found that this lift is not explained by the spec's discipline of warrants or lifecycle markers rendered into the planner's context — a sparse bare-name projection (`belief_type :: claim`, no warrant fields, no lifecycle marker) was strictly Pareto-dominant on every measured axis among the structured arms tested at a 285-token budget. A compression-control experiment (*v0.4a.2*) ruled out compression itself: an LLM prose summary of the raw log at matched budget reached 90.7%, below the 97.3% achieved by substrate-derived projections.

We interpret the combined findings as evidence that maintained state functions as a distinct planning substrate rather than a better summarization strategy. The load-bearing operation is the substrate transformation — filtering to currently-held beliefs, dedup-clustering, ranking — not the rendering of richer warrant or lifecycle metadata into the planner's context. The implementation we used to produce these results is reported in §3.2; it is one of multiple possible implementations of maintained state, and the empirical claim is independent of the specific implementation choice.

Results are bounded to operational workflow substrate (Claude Code session logs), a single model family (`gpt-4o-2024-08-06`), a single budget regime (~285 tokens), and fixtured belief extraction. Cross-model replication and cross-substrate replication are the two experiments required before the empirical claim earns its full generality. End-to-end maintenance economics is a remaining open question but does not block the planning-side claim.

---

## 1. Introduction

Long-running agents — coding assistants, DevOps assistants, customer-support agents, workflow agents — face a state-tracking problem that single-turn systems do not. Their decisions depend on workflow state that evolves over hundreds or thousands of interaction turns: whether validation has actually completed, whether a permission has been revoked, whether a prior fix attempt failed, whether "done" still holds. Current systems typically maintain this workflow state implicitly, asking the model to reconstruct it from raw history at each planning step.

We call this the *reconstruct-world-model-every-step tax*. It produces three observable costs: large input-token consumption per planning step, latency proportional to the amount of context the model must process, and a class of *operational error* in which the agent acts on a stale or incorrect understanding of current state. Examples include false-completion claims, premature actions taken before approval is confirmed, repeated failure loops in which the agent re-attempts the same failed operation, and stale-validation assumptions in which the agent treats validation that has been superseded as still authoritative.

A natural architectural alternative is to maintain workflow state explicitly: derive a representation of currently-held beliefs from the event stream, project that representation into the planner's context, and let the planner reason against a current view of the world rather than reconstructing one from raw history. We tested this alternative against three different baselines and across multiple projection formats, using a specific implementation we developed for the purpose. We refer to the implementation as the *Belief Stack*; it maintains beliefs as objects with a *claim + warrant + lifecycle* contract in the substrate, and projects sparse views of those beliefs into the planner's context. The paper's contribution is the empirical claim that maintained state beats reconstruction on operational planning tasks. The implementation choices that produced this result are described in §3.2 and are not the contribution; the same claim could in principle be tested with other implementations of maintained state.

This paper reports a pre-registered experimental program designed to test whether maintained state functions as a distinct planning substrate, and if so, to identify which features of the substrate are load-bearing. The program comprises three phases:

1. **v0.3 (planning-side experiment).** Tests whether a maintained-state projection outperforms a strong raw-context baseline on planning correctness.
2. **v0.4a.1 (mechanism ablation).** Tests which features of the spec's `claim + warrant + lifecycle` projection rendering are load-bearing, by varying the projection format across five arms at matched budget.
3. **v0.4a.2 (compression control).** Tests whether the v0.3 / v0.4a lift is attributable to compression alone, by adding a sixth arm in which the raw log is compressed under the same protocol that produces the maintained-state projection.

Each phase was pre-registered with locked interpretation rules and action commitments before any data flowed. Amendments to pre-registrations were re-locked and versioned (v0.4a → v0.4a.1 → v0.4a.2) with explicit amendment logs. The same substrate, the same generator, and the same scoring methodology were used across all phases to maximize cross-experiment comparability.

The paper proceeds as follows. §2 places the work in the context of related approaches to LLM state management. §3 describes the substrate and the scoring methodology. §4 reports the three experimental phases. §5 interprets the combined findings, distinguishing what the evidence supports from what the v0.3 interpretation got wrong. §6 discusses limitations. §7 identifies the experiments required for full empirical generality.

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

The substrate for all three experiments is a corpus of 164 Claude Code session logs comprising approximately 20,190 evaluation turns. Sessions vary in length and complexity; each captures a real coding-assistant interaction including user messages, assistant messages, tool invocations, and tool outputs. The corpus was assembled for an earlier study (OB-001) and reused across OB-002, v0.3, and v0.4a to maximize cross-experiment comparability.

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

All generation across all phases used `gpt-4o-2024-08-06` at temperature 0 with a fixed seed (20260601), top-p 1.0, and a 1500-token output cap. System prompts varied by arm to describe the format of context the arm received; user prompts were generated by a fixed template. All contexts for a given phase were generated before any answer-generation calls flowed; generation order across (question, arm) pairs was shuffled with a fixed seed to prevent any single arm from completing before another started.

### 3.5 Scoring

Scoring is per-question paired across arms. A deterministic oracle (`score_operational_label.Scorer`) computes ground truth per `(session, turn, category)` from session events. An LLM judge (`gpt-5-mini-2025-08-07`, reasoning_effort=medium, fixed seed) classifies each generated answer's behavior on each metric. The combined label per `(question, arm, metric)` is computed by `combine_oracle_and_judge` under an oracle-wins-on-disagreement policy.

The primary outcome metric is **planning correctness** — the fraction of paired questions on which the answer does not commit the category-relevant failure mode. Effect sizes between adjacent arms in the ablation ladder were pre-registered with a 3 percentage-point threshold for "advanced" and a 2-pp threshold for "noise floor."

### 3.6 Pre-registration discipline

Each phase was pre-registered with locked interpretation rules and action commitments before any data flowed. Amendments to pre-registrations (when build-time audits surfaced ambiguities in the locked design) were re-locked and versioned with explicit amendment logs. The full pre-registrations, reports, and supporting data are available in the project repository under `belief_stack_v0_3/` and `belief_stack_v0_4a/`.

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

A′ − A = −1.3 pp, well within the 2-pp noise floor. The pre-registered *A_prime_near_A* outcome fired: **compression of raw log alone does not reach maintained-substrate correctness**. The 5.3-pp B − A lift measured in v0.3 and replicated in v0.4a.1 is fully attributable to the substrate transformation, not to compression.

---

## 5. Combined interpretation

### 5.1 What survives

Two claims survive — one stronger, one sharper — than v0.3 alone supported.

**Maintained state is a planning primitive.** This claim now has two independent empirical supports:

1. *v0.3:* substrate-derived projection beats raw context (98.7% vs 90.7%) at 14% of the input tokens.
2. *v0.4a.2:* LLM-compression of raw context at matched budget does *not* reach the maintained-substrate correctness (90.7% vs 97.3%). The compression-alone counter-explanation is empirically ruled out.

**The substrate transformation is the load-bearing operation.** What does the planning-useful work is the rule-engine pipeline upstream of the projection — filtering beliefs to currently-held states, clustering by `(belief_type, operational_claim)`, ranking by recency and authority. The projection format is the consumer interface, not the mechanism. Bare structured names (Arm C) reach the same correctness as prose summary (Arm B) and outperform richer renderings (Arms D, E).

### 5.2 What does not survive

The interpretation of v0.3 that attributed the lift to the spec's full `claim + warrant + lifecycle` discipline *rendered in the planner's context* is empirically weakened. v0.4a.1 measured no separation between arms B (prose summary), C (bare names), D (with warrants), and E (with warrants + lifecycle marker) above the 2-pp noise floor. The richer projection renderings did not add measurable correctness; D and E underperformed C by 1.3 pp at increased token cost.

The numbers v0.3 reported are not in question. They replicate cleanly in v0.4a as the B − A delta. What was over-strong was the attribution of those numbers to projection-side discipline rather than to upstream substrate machinery.

### 5.3 The implementation that produced these results

The empirical claim — *maintained state beats reconstruction* — is independent of the specific implementation that produced the result. For replicability, we describe the implementation here. It is not defended as the only viable implementation; future work could test other maintained-state schemes against the same baselines.

The implementation we used (Belief Stack) carries three structural choices that distinguish it from the baselines tested:

1. **Substrate contract.** Beliefs in the substrate are objects with `claim + warrant + lifecycle` fields. The rule engine that produces the substrate from the event stream performs filtering (excluding beliefs in `retired` or `not-yet-born` states), dedup-clustering (collapsing beliefs that share `(belief_type, operational_claim)`), and ranking (by recency and authority). v0.4a.2 evidence supports this composite substrate-side transformation as load-bearing: compressing the raw log to the same token budget without the substrate transformation (Arm A′) does not recover the planning lift.

2. **Sparse planner projection.** The view the planner consumes is bare `belief_type :: claim` per active cluster, dedup-ranked and budget-bounded. v0.4a.1 evidence supports the sparse projection: adding warrant fields (Arm D) or lifecycle markers (Arm E) to the planner-facing projection does not improve correctness at the 285-token budget on this substrate, and may slightly hurt.

3. **Substrate-vs-projection split.** The substrate carries rich content (warrants, lifecycle); the planner-facing projection strips this richness in favor of bare names. The implementation's choice to maintain richness in the substrate while projecting sparsely to the planner is supported empirically only on the planner side; whether other consumer surfaces (e.g., human inspection) need different projection shapes is reported as a design commitment, not a measured claim. We discuss the open status of the human-side projection in §6 and §7.

The empirical contribution of the paper is the claim that *maintained state beats reconstruction*, defended across the three experiments above. The implementation choices reported in this subsection are the specific design we ran the experiments on. Different implementations of maintained state — with different schemas, different rule engines, different ranking heuristics — could in principle produce the same or different results. v0.4a's mechanism evidence identifies the substrate-side transformation, not the specific schema, as the load-bearing element.

### 5.4 A speculative mechanism (hypothesis, not finding)

The v0.4a.1 result invites — but does not establish — a hypothesis about *why* the bare projection wins. At small budgets on a single-next-action planning task, the planner may need the *names* of currently-held beliefs (what is true now) more than it needs the *evidence chain* (why each belief is held). The substrate machinery determines which beliefs are currently held upstream; the planner consumes the result and chooses the next action consistent with them. Adding warrant fields to the projection grows the budget per belief, fits fewer beliefs in context, and adds detail the planner may not productively use at this task resolution.

This is a candidate mechanism, not a finding. Whether it generalizes — to longer planning horizons, larger budgets, or substrates where evidence chains carry more diagnostic information — is unmeasured. We report it as a hypothesis that would direct future mechanism-level work.

---

## 6. Limitations

The findings reported here are bounded in several ways that future work must address before the architectural claim can be made at full generality.

**Single substrate.** All measured results are on Claude Code session logs. Substrates with different properties — sensemaking and narrative domains where current "truth" is more ambiguous, multi-actor coordination where multiple parties' belief states must be tracked, longer-horizon planning where chains of consequence matter more — may exhibit different projection trade-offs. The single-substrate caveat is the largest live risk to today's interpretation.

**Single model family.** All generation used `gpt-4o-2024-08-06` at T=0. Other models (different families, different scales, newer or older capabilities) may extract more from rich projections (potentially restoring the discipline's advantage) or compress so well that even sparse projections are unnecessary (potentially pushing the optimal projection further down). The model-variance question is unmeasured.

**Single budget regime.** All projection arms targeted a ~285-token cap. At higher budgets — 800 or 2000 tokens — the richer renderings have room to fit more clusters at greater detail per belief. The Arm C Pareto dominance may not hold across budget regimes.

**Fixtured belief extraction.** Beliefs were pre-derived from the v0.1 substrate. Live extraction — a write-path rule engine deriving `belief_instances` and `belief_events` from a real event stream — was not tested. Live extraction may produce different belief sets in ways that affect projection performance.

**Single task type.** The evaluation set is 75 single-next-action planning questions. Multi-step planning, plan generation, plan repair, and other planning task variants are not tested.

**Small per-metric n.** Each category contains 15 questions. Aggregate-level effects (planning correctness across all 75) are reasonably bounded. Per-metric patterns are directional rather than statistically conclusive at this n.

**Judge classification dependence.** The deterministic oracle is the primary score axis, but the LLM judge is consulted to classify whether the model's free-text answer commits the failure mode. Across v0.3 and v0.4a, judge-oracle conflicts run ~1.5% of metric-level judgments — low but non-zero. Primary outcomes are insensitive to judge errors at this conflict rate.

**Single implementation of maintained state.** The Belief Stack implementation described in §3.2 is one specific scheme — `claim + warrant + lifecycle` substrate contract, §3.5a dedup-clustering, the OB-002 ranking heuristics. The empirical claim is independent of these specific choices; other implementations of maintained state could in principle be tested against the same baselines. The paper reports a result, not the only implementation that could produce it.

---

## 7. Required and adjacent next experiments

Two experiments are required before the empirical claim earns its full generality. They are blocking for the strongest version of this paper. Both are pre-registered following the same lock-before-run discipline as v0.3 and v0.4a.

### 7.1 Cross-model replication (v0.4c1) — required

The first reviewer question for any single-model result is: *how do we know this is not a model-specific artifact?* v0.4c1 holds the substrate and the experimental design constant and varies the generator across at least one frontier-class alternative (Claude Opus 4.7, Gemini 2.5 Pro) and at least one smaller / cheaper model. The pre-registered arm set is `A / A' / B / C` — sufficient to test the thesis (maintained state beats reconstruction) across models without re-running the mechanism ablation on each. The mechanism finding from v0.4a.1 (`E ≈ B`) is reported as substrate-and-model-specific until a separate cross-model mechanism study replicates it.

### 7.2 Cross-substrate replication (v0.4c2) — required

After v0.4a.2 ruled out compression as the explanation, the single largest live risk to today's interpretation is the single-substrate caveat. The same protocol — pre-registered arms, deterministic oracle, paired evaluation — applies to a second operational substrate. The data-sourcing problem is the bottleneck; the protocol transfers cleanly. The cheapest path is re-instrumenting an additional AI-agent trace corpus (a different agent harness on a comparable task). A longer-effort path is sourcing DevOps incident logs or customer-support trajectories. The cross-substrate result is what earns the *operational planning* generality claim.

### 7.3 Adjacent experiments (not blocking publication)

Reported as planned future work but not required for the paper's empirical claim:

- **End-to-end maintenance economics.** v0.4a measured planning-side consumption only. The substrate-side write-path cost (tokens, latency, dollars per evidence event) determines whether the architecture is net-cheaper at the system level. The planning-side efficiency we report is independent of this measurement; the system-level economic question is honestly noted as open.
- **Budget-floor scan.** v0.4a sets an upper bound on the *minimum-sufficient* projection at ~208 tokens. The actual floor — and whether the descent is gradual or cliff-shaped — is unmeasured.
- **Multi-step planning.** v0.4a's single-next-action task may be uniquely friendly to compact maintained state. Multi-step planning may rebalance the projection trade-off.

Beyond these, the broader Belief Stack research program — substrate-side write-time discipline, lifecycle theory, human-inspection projection optimization, sensemaking substrate transfer, governance and intervention studies — produces papers of its own. None of them block the empirical claim reported here.

---

## References and artifacts

The full experimental artifacts — pre-registrations, executable code, generated data, and reports — live in the project repository at `github.com/sstranburg/topicspace-core`. Key references for replication:

- **v0.3 pre-registration:** `belief_stack_v0_3/BELIEF_STACK_PRE_REGISTRATION_v0.3.md`
- **v0.3 report:** `belief_stack_v0_3/BELIEF_STACK_REPORT_v0.3.md`
- **v0.4a.2 pre-registration (locked at v0.4a → v0.4a.1 → v0.4a.2):** `belief_stack_v0_4a/BELIEF_STACK_PRE_REGISTRATION_v0.4a.md`
- **v0.4a combined report (v0.4a.1 + v0.4a.2):** `belief_stack_v0_4a/BELIEF_STACK_REPORT_v0.4a.md`
- **Substrate construction (OB-001):** `operational_belief_v1/`
- **Overlay rendering (OB-002 §3.5a):** `operational_belief_v2/build_overlay_context_b_v2.py`
- **Spec:** `https://topicspace.ai/research/belief-stack`

The web-facing case studies for v0.3 (and a forthcoming case study for v0.4a) live under `https://topicspace.ai/research/case-studies/`.

---

## Changelog

- **v0.2 (2026-06-04)** — scope audit. Per the locked paper-scope-discipline memory, the paper is narrowed to a result paper: the empirical claim is the contribution; the Belief Stack implementation is reported in support but not defended as a primary contribution. Specifically: (1) Abstract ¶3 reworked to remove "we sketch the architecture this evidence implies" overreach; (2) §1 reframed Belief Stack as the implementation we tested with, not the architecture we propose; (3) §5.3 renamed from "The architecture this evidence implies" to "The implementation that produced these results" and rewritten to describe implementation choices honestly; (4) §5.4 marked as hypothesis-not-finding; (5) §6 added "single implementation of maintained state" as a limitation; (6) §7 reordered to lead with the two required experiments (cross-model + cross-substrate) and demoted human-inspection projection, warrant write-time utility, lifecycle theory, governance to "different papers" framing.
- **v0.1 (2026-06-04)** — initial working draft. Covers v0.3, v0.4a.1, v0.4a.2. Open directions included cross-substrate replication (most important), budget-floor scan, end-to-end economics, model variance, warrant write-time utility, human-inspection measurement, multi-step planning.

---

*Working draft. Iterated as additional substrates, models, and economic measurements land. The paper's claims should be re-anchored against each new experiment per the same pre-registration discipline that produced the v0.3 / v0.4a results.*
