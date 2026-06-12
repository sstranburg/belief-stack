# Belief Stack v0.4a — Mechanism Ablation Pre-Registration

**Date:** 2026-06-03
**Status:** **LOCKED 2026-06-03 as v0.4a; AMENDED + RE-LOCKED as v0.4a.1; FURTHER AMENDED + RE-LOCKED as v0.4a.2** (compression-vs-substrate isolation — Arm A′ added to test whether the maintained-state lift survives prose compression of the raw log at matched budget). See §11 Amendment log.
**Lineage:** OB-001 (v0.1) → OB-002 (v0.2.2) → Belief Stack v0.3 (planning-side, locked + run 2026-06-03) → **v0.4a.2 (mechanism ablation + compression confound isolation, this document)** → v0.4b (end-to-end cost) → v0.4c (replication)

---

## §0 The question

**What part of the v0.3 belief overlay causes the planning-correctness lift?**

v0.3 showed that a 285-token belief overlay (Arm B) outperformed a 2,037-token raw context (Arm A) on planning correctness — **98.7% vs 90.7%**, at 31% of the latency and 14% of the input tokens. The result is striking. It is also confounded: v0.3 did not isolate whether the lift came from:

1. Shorter maintained state
2. Structured claims
3. Warrants / provenance
4. Lifecycle labels
5. Ranking / budgeting
6. Removal of noisy chronology

Without an ablation, the v0.3 win is open to the rejoinder *"belief overlay beat raw log because it was shorter and more curated, not because of the architectural discipline."* If that's true, Belief Stack reduces to "another summarization layer" and the lifecycle-is-novelty claim weakens substantially.

v0.4a is the experiment that resolves this. Five arms in a strict ladder, each adding one element of the Belief Stack discipline. Same generator, same substrate, same scoring.

**Predicted ladder if the architecture is correct: E > D > C > B > A.**

If the ladder doesn't hold, the result identifies which piece of the discipline is actually doing the work — also informative, though weaker for the architectural claim.

---

## §1 Decisions

| # | Topic | Status | Resolution |
|---|-------|--------|------------|
| **D1** | Substrate | **RESOLVED** | Reuse v0.1 / v0.2.2 / v0.3 substrate unchanged. 75 paired single-next-action planning questions, derived from 164 Claude Code session logs (~20,190 evaluation turns). 5 categories: approval_status, validation_check, completion_check, readiness_check, repeated_failure. Maximizes comparability with v0.3 and with the operational-belief experiment line. No fresh fixture-construction risk. |
| **D2** | Generator | **RESOLVED** | `gpt-4o-2024-08-06`, T=0, seed `20260601`. Same as v0.3. **Locked: this is a mechanism ablation, not a replication study; changing models would confound the cleanest experiment in the program.** Model variance is v0.4c. |
| **D3** | Number of arms | **RESOLVED** | 5 (A / B / C / D / E). Strict ladder; each arm adds one element of the discipline. |
| **D4** | Token budget for arms B/C/D/E | **RESOLVED (v0.4a.1 amendment)** | **B/C/D/E use the same 285-token budget cap.** Observed token counts may vary by representation format because some formats exhaust the available substrate before filling the cap. This is acceptable and should be reported. <br/><br/>**The key audit condition is cluster admission, not observed token equality.** Since C/D/E admit the same median number of clusters, the structured-arm comparison remains a clean test of representation discipline over the same admitted belief set. <br/><br/>**Do not re-render to force observed-token equality.** That would confound format with content quantity. The locked constraint is the budget cap; the matched-content condition is cluster-admission parity. <br/><br/>*(Original v0.4a D4 wording — "all four arms targeted at ~285 input tokens ± 10%" — was internally inconsistent: v0.3 Arm B's budget was 500 tokens, not 285. The 285 figure was v0.3's observed mean. Build-time audit on 2026-06-03 surfaced this; amendment locks the budget-cap interpretation, which produces the cleanest format-only comparison.)* |
| **D5** | Arm B definition | **RESOLVED — B-option-1** | LLM-generated free-form prose summary of "what's currently true," produced by the same generator (`gpt-4o-2024-08-06`, T=0) with a fixed summarization prompt, capped at the matched ~285-token budget. **Locked: the competing-explanation hypothesis ("compression alone explains v0.3") gets its strongest case. If B performs well, the result is credible. If B performs poorly, nobody can claim the comparison was a strawman.** |
| **D6** | Arm E definition | **RESOLVED — full discipline, warrants surfaced** | Arm E surfaces `{type, label, current_state, provenance, confidence, applicability_boundary, lifecycle_stage}` per belief in the context. Richer than v0.3 Arm B (which had lifecycle markers but no surfaced warrants). **Locked: the ladder must answer *what component causes the lift?* — not *can we reproduce v0.3 exactly?* The clean B→C→D→E ladder where each step corresponds to a single mechanism is the experimental program. v0.3 Arm B (98.7%) is reported as a continuity reference, not as a 6th arm.** |
| **D7** | Primary outcome metric | **RESOLVED** | Paired planning correctness, deterministic oracle from `score_operational_label.Scorer`. n = 75 paired observations per arm. Same as v0.2.2 and v0.3. No LLM judge for primary outcome. |
| **D8** | Interpretation rules | **RESOLVED** | See §6 below. Outcome 5 wording tightened at lock time per Sue's amendment — *"compression alone explains v0.3"* was imprecise because Arm B is not pure compression (it is still maintained state with current-state selection and chronology removal). Revised wording: *lifecycle/warrant discipline does not add measurable value over maintained summaries on this substrate.* The lifecycle-is-novelty claim weakens substantially under that outcome, but the falsification is precise, not overstated. |

**All six decisions resolved.** Pre-registration is LOCKED. Effect-size threshold (3 pp per ladder step) confirmed.

---

## §2 The five arms

| Arm | Context shape | Discipline level | Token budget |
|---|---|---|---|
| **A** | Raw K=20 most-recent-log + strong baseline prompt ("treat as belief state, reconstruct what you need") | None — raw context | Variable (mean ~2,037 in v0.3) |
| **B** | Plain summary of current state (per D5 lean: LLM-generated free-form) | Maintained + compressed; **no structure** | ~285 tokens (per D4 lean) |
| **C** | Structured claims only — `{type, label, current_state}` per belief, no warrant, no lifecycle markers | Maintained + structured; **no warrant, no lifecycle** | ~285 tokens |
| **D** | Claims + warrants — `{type, label, current_state, provenance, confidence, applicability_boundary}` per belief, no lifecycle markers | Maintained + structured + warranted; **no lifecycle** | ~285 tokens |
| **E** | Claims + warrants + lifecycle — full discipline. Each belief surfaces `{type, label, current_state, provenance, confidence, applicability_boundary, lifecycle_stage}` | **Full Belief Stack discipline** | ~285 tokens |

**Reference point (not an arm):** v0.3 Arm B at 98.7%. Reported alongside results for continuity. v0.3 Arm B sits *between* C and E in the discipline ladder (had lifecycle markers but no warrants in context).

Same generator, same temperature, same seed across all 5 arms. Only the **shape of the context** differs.

---

## §3 Context construction per arm

Each arm derives from the same underlying belief substrate (the v0.1 fixtured beliefs). The arms differ in **how that substrate is projected into the context window** at each evaluation turn.

**Arm A.** Reuse v0.3 Arm A context construction unchanged: K=20 most recent log entries + the v0.3 strong-baseline system prompt.

**Arm B.** For each evaluation turn, the substrate is summarized by an LLM call (`gpt-4o-2024-08-06`, T=0) with a fixed prompt: *"Given the following maintained belief state, write a concise prose summary of what is currently true at this point in the session. Cap your summary at ~285 tokens. Do not invent facts not present in the input."* The LLM call has access to the same belief substrate as arms C/D/E but produces unstructured prose.

**Arm C.** For each evaluation turn, render the active beliefs at that turn as a structured list. Each entry: `{type, label, current_state}`. Drop all warrant fields and lifecycle markers. Truncate to budget by §3.5a dedup-ranking (same logic as v0.3) until under budget.

**Arm D.** Same as C, but each entry includes `provenance` (source turn / evidence reference), `confidence` (numeric), and `applicability_boundary` (text). Drop lifecycle markers. Truncate as in C.

**Arm E.** Same as D, but each entry also includes `lifecycle_stage` (one of: `born`, `active`, `strengthened`, `weakening`, `contradicted`, `retired`). Truncate as in C.

All arms targeted at ~285 input tokens ± 10%. Header reserve computed against worst-case render so the budget is honestly enforced (same discipline as v0.2.2 §3.2 / §3.5).

---

## §4 Generator protocol

Per D2 lean:

- **Model:** `gpt-4o-2024-08-06`
- **Temperature:** 0
- **Seed:** 20260601
- **System prompt:** arm-specific (each arm's prompt explains the context format it is receiving — same discipline as v0.3 SYSTEM_PROMPTS).

All 75 questions × 5 arms = 375 answers. Generation order: shuffled so no arm completes before another starts (anti-curation discipline).

---

## §5 Scoring

Per D7:

- **Primary metric:** paired planning correctness — per-question oracle agreement from `score_operational_label.Scorer`.
- **Sample:** n = 75 paired observations per arm pair (e.g., A vs B, B vs C, ...).
- **No LLM judge for primary outcome.** The deterministic oracle is the score axis. (LLM judge may be used for explanation quality as a secondary axis but does not affect the primary result.)

Reuse `belief_stack_v0_3/score_v3.py` adapted for the 5-arm structure.

---

## §6 Pre-registered predictions

**Primary prediction (committed):**

> **E > D > C > B > A** on paired planning correctness.

**Minimum effect sizes for each rung to count as "advanced":**

- B > A by ≥ **3 percentage points** (compression alone helps over raw)
- C > B by ≥ **3 percentage points** (structure adds beyond compression)
- D > C by ≥ **3 percentage points** (warrants add beyond structure)
- E > D by ≥ **3 percentage points** (lifecycle adds beyond warrants)

3 pp ≈ 2 of 75 questions per step. Below 2 pp the result is noise on this sample size; above 3 pp it is a meaningful step.

**Reference predictions:**

- Arm E at approximately the v0.3 Arm B level (98.7% ± 2 pp), since E and v0.3 Arm B share most of the same content with E additionally surfacing warrants. A large E > v0.3 Arm B gap would itself be a finding.
- Arm A at approximately v0.3 Arm A level (90.7% ± 2 pp), since the configuration is unchanged.

---

## §7 Pre-registered interpretation rules

**Locked decision tree** — interpret BEFORE seeing results:

1. **If E > D > C > B > A with each step ≥ 3 pp** → architecture validated at mechanism level. Lifecycle-is-novelty empirically defended. Database analogy empirically earned at the structural-extraction level.

2. **If E > D > C > B but B ≈ A (≤ 2 pp)** → compression alone doesn't help. The discipline (structure/warrant/lifecycle) is what wins, not the shorter context. Strongest result for the architecture.

3. **If E ≈ D > C > B > A (within 2 pp)** → warrants don't add over structure-and-lifecycle. Possible interpretations: (a) warrants are useful for human inspection but not for AI planning consumption, (b) lifecycle markers implicitly carry warrant information at this token budget. Worth investigating but doesn't falsify the architecture.

4. **If E ≈ D ≈ C > B > A** → structure is the load-bearing element. Warrants and lifecycle are decorative at this budget. Architecture significantly weakens; lifecycle-is-novelty needs revision.

5. **If E ≈ B (≤ 2 pp)** → **lifecycle/warrant discipline does not add measurable value over maintained summaries on this substrate.** The lifecycle-is-novelty claim weakens substantially. *Note: this is not "compression alone explains v0.3" — Arm B is still maintained state with current-state selection and chronology removal. The precise finding would be that the additional structure/warrant/lifecycle elements do not add measurable value above maintained-summary baseline at this token budget on this substrate.* This is the falsification outcome.

6. **If A wins overall** → the architecture is wrong at this task; substrate or scoring may be confounded. Halt and audit.

**Action commitments per outcome:**

- Outcomes 1 or 2 → proceed to v0.4b (end-to-end cost) as next step.
- Outcome 3 → proceed to v0.4b but flag warrant-in-context as a separate question for v0.5.
- Outcome 4 → amend lifecycle-is-novelty memory; revise positioning to emphasize structure rather than full discipline; reassess v0.4b/c scope.
- Outcome 5 → amend lifecycle-is-novelty memory and database-analogy memory honestly per the precise falsification (above); revise positioning toward "maintained summaries are a planning primitive; additional structure is unverified at this budget on this substrate"; reconsider the architectural-category claim while preserving what was actually shown (maintained-state-of-any-shape > raw context).
- Outcome 6 → halt; audit substrate / scoring / context construction before proceeding.

These commitments lock now. They do not get amended after seeing results.

---

## §8 Anti-curation discipline

Same as v0.3:

- All 5 arm contexts generated for **all 75 questions before any answers are generated**. No iterative tuning.
- **No prompt tuning after seeing outputs.** System prompts and context-construction code lock at pre-reg lock time.
- All seeds, model IDs, and configuration values are in source control before the first API call.
- **No silent truncation.** Budget cap enforced by §3.5a dedup-ranking with explicit `omitted: N` counter when applicable.
- **Failures (e.g., TPM caps, malformed JSON) are reported honestly**, not retried with different parameters. If a TPM cap drops a question for an arm, that question is excluded from paired comparison for that arm pair (n < 75 reported with explicit count).

---

## §9 What this experiment does NOT test

- **Not end-to-end cost.** Same v0.3 framing: planning consumption only. Substrate-side maintenance cost is v0.4b.
- **Not model transferability.** Single generator. Model variance is v0.4c.
- **Not domain transferability.** Single substrate (Claude Code sessions). Other operational substrates are v0.4c.
- **Not extraction-mechanism robustness.** Beliefs are fixtured (v0.1 substrate). Live extraction is v0.4c.
- **Not narrative/sensemaking transferability.** Operational substrate only. Operational-vs-sensemaking architectural split is a separate open question per the post-v0.3 memory.

Outcomes 1, 2, or 3 above earn the right to run v0.4b/c. Outcomes 4 or 5 require revisiting the architecture before broader replication.

---

## §10 Lock signature

This pre-registration is **LOCKED at v0.4a.1.**

- [x] D1 — substrate (resolved as drafted)
- [x] D2 — generator locked at `gpt-4o-2024-08-06`, T=0, seed `20260601`
- [x] D3 — five arms (A/B/C/D/E)
- [x] D4 — **AMENDED v0.4a.1:** budget cap = 285 tokens (matched). Observed tokens may vary; cluster-admission parity is the audit condition.
- [x] D5 — Arm B = LLM-generated free-form summary (B-option-1)
- [x] D6 — Arm E = full discipline, warrants surfaced
- [x] D7 — paired planning correctness, deterministic oracle, n=75
- [x] D8 — interpretation rules locked with Outcome 5 wording tightened

**v0.4a lock:**
- Locked by: Sue Stranburg
- Locked on: 2026-06-03
- Lock hash: commit `b3af1a0` (initial v0.4a lock)

**v0.4a.1 re-lock (this version):**
- Re-locked by: Sue Stranburg
- Re-locked on: 2026-06-03
- Lock hash: [commit SHA of this re-lock — set by the git commit that lands v0.4a.1]
- Triggered by: build-time audit of `build_v4a_contexts.py` output (observed tokens ran below the originally-intended ~285 floor; root cause identified as substrate density at the budgeted cap)

After lock: no amendments without a re-lock and re-version (v0.4a.2, etc.).

---

**One philosophical anchor preserved at lock time** (Sue's closing observation):

> *"The most important thing isn't whether E wins. It's whether B, C, D, and E separate cleanly at all. Because the shape of that ladder will tell you more about Belief Stack than another headline result ever could."*

This is the right interpretive lens for the result. v0.4a is informative regardless of which outcome lands — the ladder's *shape* (and the magnitude of each step) carries the architectural information, not just whether the predicted winner wins. The locked interpretation rules in §7 are sized accordingly: each outcome carries a specific architectural conclusion, not a binary pass/fail. See `project_belief_stack_ladder_shape_over_headline.md` for the discipline.

---

## §11 Amendment log

### v0.4a → v0.4a.1 (2026-06-03)

**Trigger:** Build-time audit of `build_v4a_contexts.py` output on 2026-06-03 reported observed token means for arms C / D / E at **109 / 175 / 184** — all below the originally-locked "~285 ± 10%" floor of 256 tokens.

**Root cause:** The original D4 wording was internally inconsistent:
- *"~285 input tokens ± 10%"* read as a target for **observed** tokens.
- *"matched to v0.3 Arm B budget"* read as a target for **budget**.
- But v0.3 Arm B's actual budget was **500** tokens, not 285. The 285 figure was v0.3's *observed* mean at a 500-token budget — i.e., v0.3 Arm B ran at ~57% fill rate.

v0.4a as implemented used budget = 285. Observed tokens land below 285 because the substrate (median ~4 active clusters per evaluation turn) exhausts before filling the cap at the structured arms' line-formats.

**Resolution path considered:** Three options were on the table:
1. **Re-version v0.4a.1** with D4 amended to a budget-cap interpretation (this option).
2. Re-render at budget = 500 (matched to v0.3 Arm B's actual budget). Would push D/E observed tokens closer to 285 but admit more clusters; *confounds format with content quantity*.
3. Per-arm budgets tuned to land observed tokens at ~285 ± 10%. *Most artificial; explicitly engineered comparison; confounds in the same way as option 2.*

**Decision:** Path 1 (this amendment). The matched-budget interpretation is the cleaner ablation because:
- The 4 admitted clusters at the median represent **identical evidence across arms** — each arm renders the same beliefs at different verbosity.
- The observed-token disparity is a *property of the architecture's per-belief verbosity*, not a confound.
- Forcing observed-token equality would require giving Arm C more clusters or Arm E fewer — confounding "format" with "amount of content," which is exactly what the experiment is trying to isolate.

**What changed:**
- D4 wording: "all four arms targeted at ~285 input tokens ± 10%" → "B/C/D/E use the same 285-token budget cap; observed tokens may vary by format; cluster-admission parity is the audit condition."
- Added explicit instruction: *"Do not re-render to force observed-token equality."*
- Recorded build-time observation: arms C/D/E admit the **same median number of clusters (4)** — confirming the matched-content condition holds at the budget cap.

**What did NOT change:** D1, D2, D3, D5, D6, D7, D8, §2 arm definitions, §3 context construction logic, §5 scoring methodology, §6 predictions, §7 interpretation rules, §8 anti-curation discipline, §9 scope limits.

The experimental design is unchanged. Only the *interpretation* of D4's "matched budget" claim is clarified. Contexts already generated (`belief_stack_v0_4a/data/contexts_arm_{a,b,c,d,e}.jsonl`) are preserved; no re-render required.

**Discipline reflection:** This amendment is exactly the build-time audit the *Lock before run* operating principle is designed to surface. Catching the D4 ambiguity at the context-construction step — *before* answer generation flows — is the discipline working as intended. The v0.4a → v0.4a.1 trace is part of the experiment's provenance, not a stain on it.

---

---

## §12 v0.4a.2 extension — Arm A′ (compression-vs-substrate isolation)

**Locked 2026-06-03 by Sue Stranburg.** Added after v0.4a.1 results landed (Outcome 5: lifecycle/warrant discipline does not add measurable value over maintained summaries on this substrate). The result left one architectural ambiguity unresolved: **is the maintained-state lift coming from compression itself, or from the substrate transformation?**

### Why this arm

Arm B summarizes the *maintained-state substrate* (the §3.5a-clustered active beliefs with full warrant + lifecycle fields). Arm A summarizes nothing — it shows the raw K=20 log. The B − A lift (5.3 pp) is therefore confounded between:

1. **Compression** (B is shorter than A).
2. **Source transformation** (B's input is substrate-derived; A's input is raw log).

Arm A′ holds compression constant and varies source. If A′ ≈ B, the substrate transformation contributes nothing measurable beyond compression — the architectural thesis weakens substantively. If A′ < B, the substrate transformation matters above and beyond compression — the thesis strengthens.

### Arm A′ definition

| Field | Value |
|---|---|
| Source | Raw K=20 log (identical to Arm A's input) |
| Compression mechanism | LLM-generated prose summary, same protocol as Arm B |
| Summarizer model | `gpt-4o-2024-08-06` |
| Summarizer temperature | 0 |
| Summarizer seed | 20260601 |
| Summarizer max output | 285 tokens (matched to Arm B) |
| Summarizer system prompt | Same as Arm B's, but instructed to summarize "what is currently true" from raw session history rather than from a maintained belief list |

### Pre-registered predictions (locked at amendment time)

**Three outcome classes, with locked action commitments:**

| Result | Architectural implication | Action |
|---|---|---|
| **A′ ≈ B/C** (within 2 pp) | **Compression alone explains v0.4a's B-vs-A lift.** The maintained-state thesis weakens substantively: the substrate transformation contributes nothing measurable beyond LLM-compression of raw log at the same budget. | Amend `project_belief_stack_database_analogy.md` and `project_belief_stack_claim_hierarchy.md` to reflect the new central claim ("LLM-compressed context is the planning primitive; substrate-derived maintenance is unverified to add above compression"). The matter claim itself doesn't disappear — A′ ≈ B is still substantively better than A — but it would lose its architectural distinctiveness. |
| **A′ < B** by ≥ 3 pp | **Substrate transformation does meaningful work above compression.** The maintained-state thesis strengthens; the rule-engine-derived view of the substrate is doing planning-useful work the LLM cannot replicate by summarizing raw history. | Strengthen `project_belief_stack_database_analogy.md` first-prediction line. Amend `project_belief_stack_claim_hierarchy.md` to reflect the sharpened thesis. |
| **A′ ≈ A** (within 2 pp) | **Compression of raw log doesn't help — maintained state must be doing the work.** Strongest possible support for the architecture's thesis at this cell of the design space. | Strengthen the thesis layer of `project_belief_stack_claim_hierarchy.md` substantively. Amend `project_belief_stack_database_analogy.md`. |
| **Between** (A′ between A and B by more than 2 pp on each side) | **Compression and substrate transformation each contribute partially.** Magnitude tells you how much. | Quantify the split. Report honestly. Likely a mid-tier amendment. |

Effect-size threshold matches v0.4a.1's pre-reg: **3 pp for "advanced," ≤ 2 pp for "noise floor."**

### What this experiment does NOT test

- Not budget-sensitivity (still ~285 token cap).
- Not model variance (still gpt-4o-2024-08-06).
- Not domain transfer (still Claude Code session logs).
- Not "what is the optimal raw-log compression strategy" — A′ uses a single fixed prose-summarization protocol matched to Arm B.

### Lock signature

**v0.4a.2 amendment locked by:** Sue Stranburg
**v0.4a.2 amendment locked on:** 2026-06-03 (same evening as v0.4a.1 results)
**Triggered by:** v0.4a.1 result revealed Outcome 5 (lifecycle/warrant discipline ≈ maintained summaries); Sue's follow-up question identified the compression-vs-substrate confound as the load-bearing thesis-level question; agreed to run the disambiguating experiment before broader memory amendments and any cross-substrate replication.

---

*Generated 2026-06-03 as the first deliverable in the v0.4 sequence. Cross-references: ``project_belief_stack_cost_frontier.md`` (internal memory note), ``project_belief_stack_lifecycle_is_novelty.md`` (internal memory note), ``project_belief_stack_database_analogy.md`` (internal memory note).*
