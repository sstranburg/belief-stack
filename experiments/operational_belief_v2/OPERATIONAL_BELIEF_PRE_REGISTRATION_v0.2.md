# Operational Belief-State Grounding v0.2 — Pre-Registration

**Status:** **LOCKED v0.2.2 — eligible for execution.**
**Date drafted:** 2026-06-01  ·  **Pre-lock revision:** 2026-06-02  ·  **Locked v0.2:** 2026-06-02  ·  **v0.2.1 amendment:** 2026-06-02  ·  **v0.2.2 amendment:** 2026-06-02

**Amendment trail:**
- **v0.2.1** (2026-06-02): Added §3.5a "Type+claim duplication collapse" after a context-construction audit revealed substrate-side belief duplication that wastes overlay budget on identical-claim repetitions.
- **v0.2.2** (2026-06-02): Replaced candidate systems B500/B1000/B2000 with **B100/B250/B500** after the v0.2.1 dedup result showed the original budget range was non-binding (max overlay 332 tokens across all 75 questions; B1000 and B2000 produced identical contexts to B500). The new range exercises the cap at the bottom (B100, with median overlay 140 tokens, forces dropouts) and reaches comfort at the top (B500, where everything fits). Primary comparison updated: **B500 vs A**.
**Predecessor:** [`operational_belief_v1/OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md`](../operational_belief_v1/OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md) and the v0.1 final report [`OPERATIONAL_BELIEF_REPORT_v0.1.md`](../operational_belief_v1/OPERATIONAL_BELIEF_REPORT_v0.1.md).

---

## 1. Background and design question

### 1.1 What v0.1 showed

Operational Belief v0.1 tested whether augmenting the same recent-log context with an additive operational belief overlay reduces workflow-state errors in answers about long-running assistant sessions. The locked v0.1 finding:

- **Aggregate deterministic operational error rate: 11.0% (A) → 5.5% (B)**, halved.
- **False-completion claims: 27% → 7%**, the largest per-metric reduction.
- **Traceability (preference): +15 pts** in favor of B.
- **Appropriate caution (preference): near-tie** (62 / 38 directionality consistent with B but not headline-worthy).
- **Two feasibility failures** (q047, q061) where the overlay-augmented System B context exceeded OpenAI Tier 1's 30 K TPM cap. Both were locked-policy `api_error:RateLimitError`, not silent truncations.

The two feasibility failures are not an isolated incident — they are the v0.1 design surfacing its own scaling limit. The overlay was unbounded; in long sessions it grew faster than the context budget.

### 1.2 The v0.2 question

> **What is the smallest ranked operational belief overlay that preserves most of the v0.1 deterministic error reduction?**

The hypothesis is that a prioritized, budgeted overlay can recover most of the v0.1 benefit (the gap from 11.0% to 5.5%) at a fraction of the context cost, *and* avoid the unbounded-overlay feasibility failures.

This is not "shrink for shrinking's sake." The product-shaped use of an operational belief overlay is as a sidecar that injects compact grounding into running assistant workflows. Unbounded overlays are not viable in that setting. A v0.2 ranking + budget design is the first step toward a feasible overlay.

---

## 2. Candidate systems

| System | Recent log | Overlay | Token budget for overlay |
|--------|------------|---------|--------------------------|
| **A** | K=20 raw recent turns (same as v0.1) | None | 0 |
| **B100** | K=20 raw recent turns | Ranked, deduped overlay capped at **100 tokens** | 100 |
| **B250** | K=20 raw recent turns | Ranked, deduped overlay capped at **250 tokens** | 250 |
| **B500** | K=20 raw recent turns | Ranked, deduped overlay capped at **500 tokens** | 500 |

All B-variants are strictly additive to A — same K=20 window, same 500-token tool-output cap, same question set. Only the overlay changes.

**Budget range rationale (v0.2.2).** Following the v0.2.1 dedup audit, the post-dedup distinct-cluster overlay has median 140 tokens and max 332 tokens across the 75 questions. The new arms span the relevant budget region:

- **B100** — below the median; forces cluster dropouts on most questions; tests squeeze.
- **B250** — between median and p90; partial dropouts on larger questions; mid-curve.
- **B500** — above the observed max; comfortable upper; everything fits.

**B0, B1000, B2000 not run.** Per v0.2.1 audit, B1000 and B2000 would produce identical contexts to B500 given the dedup result (max overlay 332 < 500). B0 (unbounded) was already excluded at v0.2 lock — v0.1 stands as the unbounded reference.

### 2.1 Primary comparison

- **B500 vs A** on the v0.1 aggregate deterministic operational error rate.

### 2.2 Secondary comparisons

- B100 / B250 / B500 sensitivity curve.
- v0.1 result (the unbounded overlay reference) as the historical anchor, not re-run.

### 2.3 Hypothesis levels

| H | Statement |
|---|-----------|
| H1 (primary) | B500 reduces deterministic operational error rate vs A. |
| H2 | The sensitivity curve B100 → B250 → B500 shows monotone improvement in deterministic error rate, with diminishing returns at the top end. |
| H3 (exploratory) | False-completion claims (the v0.1 dominant signal) is the metric most sensitive to overlay budget — i.e., even B100 closes a meaningful fraction of the v0.1 gap. |

---

## 3. Ranking policy

The overlay is ranked **lexicographic over priority tiers** (no continuous scoring in v0.2) with the meta-rule below applied first.

### 3.0 Out-of-window priority (meta-rule, applied first)

For every budgeted overlay rendering, partition the candidate active-belief pool into two sub-pools:

- **Out-of-window** — beliefs whose `born` event and most recent warrant-bearing `belief_events` row both lie at `at_turn ≤ (current_turn - K)`, where K = 20 (the raw-log window seen by System A).
- **In-window** — every other active belief.

Apply the §3.1 priority tiers to the **out-of-window** pool first. Only after the out-of-window pool is exhausted (no more candidates) or the budget is filled do the in-window beliefs become eligible for inclusion.

**Rationale.** System A already sees the last K=20 turns of the recent log. The overlay's distinctive value is carrying active state that is *no longer visible* in recent context — beliefs whose evidence has scrolled past the window but which remain operationally true. An overlay that ranks in-window beliefs alongside out-of-window beliefs spends its budget restating what System A already has.

This meta-rule does **not** suppress in-window beliefs entirely; if the out-of-window pool is small and budget remains, in-window beliefs land per the §3.1 tiers. The meta-rule reorders priority; it does not exclude.

### 3.1 Priority tiers (applied within each pool)

In rank order, highest first:

1. **Active blockers** — beliefs in lifecycle state `action_blocked`, `validation_pending`, `pipeline_failed`, `pipeline_running`, `user_approval_pending`.
2. **Contradicted / weakened beliefs** — beliefs that have been refreshed with counter-evidence or that hold a `contradicted` lifecycle marker.
3. **Recently updated beliefs** — within the K=20 raw-log window. (Note: by the §3.0 meta-rule, in-window beliefs are only eligible after out-of-window candidates are exhausted, so this tier mostly applies inside the in-window pool.)
4. **Tool-confirmed beliefs over assistant-asserted beliefs** — authority = `confirmed_by_tool` ranks above `asserted_by_assistant`.
5. **Active beliefs over retired beliefs** — `active` > `superseded` > `retired`.
6. **Compact summary of omitted belief counts by type** — only if budget allows after all priority slots are filled.

(Former tier 3, "beliefs directly relevant to the question category," is removed — see §3.3.)

### 3.2 Token accounting

- Token counting uses the same tokenizer as the generator model (gpt-4o-2024-08-06).
- Overlay tokens are counted **including the overlay's own framing/header**, not just belief content.
- If a single belief instance does not fit within the remaining budget, it is **dropped entirely** (no partial belief rendering). This is by design — partial state is worse than absent state.
- The omitted-counts summary (tier 6) is emitted as one final line if and only if there is budget left after all tier-1–5 selections.

### 3.3 Global deterministic ranking (locked)

The ranking is **global** — every question gets the same priority order. Category-aware ranking is **not** used in v0.2.

The ranking is also **deterministic** — no LLM in the ranking loop. No relevance scoring, no soft re-weighting, no LLM-assisted compression.

**Rationale.** Any LLM in the ranking loop creates a curation surface that we cannot easily defend as anti-curation. Category-aware ranking would let the overlay know something about the question before it ran. A global deterministic ranking is closer to "what a sidecar would actually do" without seeing the question, and it is reproducible from the substrate + the tier rules alone.

Locked. Not revisitable in v0.2.

### 3.4 Tiebreaks within a tier

When two candidate beliefs fall in the same §3.1 tier, break ties in this order:

1. **Out-of-window before in-window.** Defense in depth against the §3.0 meta-rule — even within a tier that has already been filtered by the meta-rule, prefer beliefs whose evidence has scrolled out of the recent log.
2. **`last_updated_turn` descending.** Most-recently-updated belief wins.
3. **Authority rank.** `confirmed_by_tool` > `confirmed_by_user` > `asserted_by_assistant`.
4. **Deterministic hash of `belief_id`.** Final tiebreaker; reproducible across runs. No randomness allowed.

Tiebreaks are applied lexicographically, in the order listed.

### 3.5 Compressed serialization contract

Each belief in a budgeted overlay renders as **exactly one compact line**.

**Required minimal fields per line:**

- `lifecycle_state`
- `belief_type`
- `claim_short` (truncated to a fixed character width — proposed 80 chars)
- `authority`
- `last_updated_turn`

**Optional field, if it fits in remaining line budget:**

- `warrant_count` (number of supporting `belief_events` rows, useful for human sanity-checks of the overlay)

**Evidence trails, revision history, and source-event references are NOT rendered in budgeted overlays**, even when budget would allow. Full evidence and revision trails belong to the human trace/debug surface (TKOS-002 `tkos explain <belief_id>`), not the AI-facing overlay.

This separation is load-bearing. The overlay is for **action-time grounding**; deep provenance is for **inspection-time debugging**. Mixing them either bloats the AI overlay or starves the human surface of detail. Keep them apart.

**Line format (proposed, to be finalized at lock):**

```
[lifecycle_state] belief_type :: claim_short (auth=authority, last=last_updated_turn[, warrants=N])
```

Example:

```
[active] validation_pending :: pytest invoked, awaiting result (auth=assistant, last=8)
```

The token budget in §3.2 counts each rendered line including its trailing newline. Beliefs that do not fit on one line under the budget are **dropped entirely** — never partial-rendered (per §3.2).

### 3.5a Type+claim duplication collapse (added in v0.2.1)

Some sessions in the v0.1 substrate contain many belief instances with the **identical** `(belief_type, operational_claim)` pair, differing only in `turn_first_seen` and `turn_last_updated`. The substrate-construction audit on 2026-06-02 found that 42 of 75 overlays had one belief_type consuming >50% of admitted budget, almost entirely from identical-claim repetition (e.g. 30 `action_blocked` instances with the same claim text but different timestamps).

The OB-002 §3.5 contract assumed one belief = one operational state. The substrate violates that assumption. Without correction, the budgeted overlay carries far less *novel* state than its budget would suggest, defeating the v0.2 design intent of a compact, distinctive grounding payload.

**Rule.** Before ranking, group candidate beliefs in a single session by the tuple `(belief_type, operational_claim)`. Each group is rendered as **one** overlay line. The line uses one representative belief — the **most recently updated active** instance in the group — for its `lifecycle_state`, `authority`, and `last_updated_turn`. A new field `n` records the cluster size:

```
[lifecycle_state] belief_type :: claim_short (auth=authority, last=last_updated, n=cluster_count)
```

When `n=1` the field may be omitted for visual cleanliness.

**Ranking against clusters.**
- §3.0 out-of-window status: a cluster is out-of-window **iff every member** is out-of-window. Any in-window member makes the cluster in-window. (Defense in depth: if any related event is visible in the recent log, the cluster isn't carrying state the model can't already see.)
- §3.1 tier: determined by the (shared) `belief_type` and the representative's lifecycle.
- §3.4 tiebreaks: `last_updated_turn` = cluster max; `authority` = cluster highest rank; deterministic hash on the representative belief_id.

**What this changes vs unmerged.**
- Budget is spent on **distinct operational claims**, not duplicated ones.
- A cluster's representativeness is auditable: `n` is visible in the rendered line; per-cluster member counts are also surfaced in the audit JSON.
- The decision affects rendering only. The substrate is not modified.

**What this does not change.**
- No belief is dropped because of dedup. Beliefs only drop if their cluster doesn't fit the budget.
- The §3.0 meta-rule still fires first; clusters within the out-of-window pool sort by tier as before.
- The deterministic gate (§6.1), the preference axes (§6.2), and the human-audit anchor (§6.3) are unchanged.

---

## 4. Must preserve from v0.1

- **Same 75-question v0.1 set.** No new questions. If the committee wants to construct a new set, that becomes v0.3, not v0.2.
- **Same K=20 raw-log window.**
- **Same 500-token tool-output cap.**
- **Same additive design** — every B-variant receives everything System A receives, plus the budgeted overlay.
- **Same deterministic primary gate** — the 5 v0.1 deterministic metrics remain the primary outcome.
- **Same generator model family** — gpt-4o-2024-08-06, T=0, seed=20260601.
- **Same deterministic judge** — gpt-5-mini.
- **Same preference judge** — gpt-4.1, used as secondary only.
- **No answer_guidance fields anywhere.** No prompt tuning after seeing outputs.
- **No silent truncation outside the declared overlay budget.** Budget overruns must surface as either ranked-overlay dropouts (counted) or as feasibility failures (recorded).

---

## 5. Explicit decisions required before lock

| Decision | Options | Status |
|---|---|---|
| **D1. Reuse v0.1 A answers, or regenerate A for model parity?** | (a) reuse v0.1 A answers as-is; (b) regenerate A under v0.2 controls | **RESOLVED → (b) regenerate A.** Removes timing-or-tooling-drift confound. Cost modest (75 generations). |
| **D2. How to handle q047 and q061 (the v0.1 feasibility failures)?** | (a) drop from v0.2 set; (b) keep, accept B0 may fail again; (c) keep, re-classify as `feasibility_failure_v01` — scored under budgeted B-variants, ignored under B0 | **RESOLVED → (c).** Budgeted B-variants are expected to fit them — that is the whole point of v0.2. Keeps the feasibility win demonstrable. |
| **D3. How are omitted beliefs represented in the overlay?** | (a) not at all; (b) one-line summary of omitted counts by belief type; (c) full omitted list compressed | **RESOLVED → (b).** Locked in §3.1 tier 6 + §3.5. One-line summary; gated on fit under the budget. |
| **D4. Global vs category-aware ranking** | (a) global; (b) category-aware | **RESOLVED → (a) global.** Locked in §3.3. |
| **D5. Where do belief evidence / revision trails sit in the overlay?** | (a) before claim+state; (b) after; (c) drop evidence entirely from overlay | **RESOLVED → (c) MOOT per §3.5.** Compressed serialization contract omits evidence/revision trails from the budgeted overlay entirely; they live on the human surface (`tkos explain`). |
| **D6. How to report if a smaller overlay performs strictly better than the unbounded overlay?** | (a) report it; (b) flag it as a finding, not an anomaly | **RESOLVED → (a) report directly.** Note the implication: the unbounded overlay's tail was net-distracting. This is itself the strongest validation of the budget-and-rank design. |
| **D7. Should the ranking use any LLM scoring of "relevance to question"?** | (a) no — deterministic only; (b) yes, with a separate ranker model | **RESOLVED → (a) no.** Locked in §3.3. |
| **D8. Multiple seeds per system?** | (a) single seed (as v0.1); (b) k seeds per system for variance estimation | **RESOLVED → (a) single seed.** Matches v0.1 parity. Defer variance estimation to v0.3 if H1 lands. |

---

## 6. Outcome measurement (locked from v0.1)

### 6.1 Primary — deterministic operational error rate

Five metrics, judged by gpt-5-mini with oracle-side disagreement policy unchanged:

1. `stale_validation_assumption`
2. `repeated_failure_loop`
3. `premature_action`
4. `false_completion_claim`
5. `missing_pause`

Aggregate = mean across the 5 metrics across the question set.

### 6.2 Secondary — preference axes

Two axes, judged by gpt-4.1:

1. `traceability`
2. `appropriate_caution`

(`sensemaking_usefulness` remains excluded, as locked in v0.1.)

### 6.3 Human-audit anchor (audit support, not a primary metric)

After deterministic scoring completes, manually review a stratified sample of judge labels. This is **audit support** for the deterministic gate, not a third primary metric.

**Sample composition:**

- All judge labels where the deterministic judge returned `YES` (i.e. an error was flagged).
- All cases where the judge and the oracle disagreed (per the v0.1 oracle-wins disagreement policy, these are already recorded; the audit re-reads them).
- A small random stratum across the remaining `NO`-labeled cases for sanity.

**What the audit produces:**

- A short reviewer note per sampled case: agree / disagree / unclear, with a one-sentence reason.
- An aggregate disagreement rate vs the deterministic judge, reported as audit support alongside the v0.2 results.

**What the audit does NOT do:**

- It does **not** override the deterministic judge's labels. The primary gate stays the deterministic-judge aggregate per §6.1.
- It is **not** a third headline metric. The headline metrics remain the §6.1 deterministic gate and the §6.2 preference axes.
- It is **not** prompt-tuning input. The judge config remains frozen per the v0.1 lock.

The audit's role is to give the v0.2 report a credibility anchor — a human spot-check of where the deterministic gate fires and where it disagrees with the oracle — without inflating the metric surface.

### 6.4 Reporting

Same table format as the v0.1 report:

- Aggregate deterministic rate by system.
- Per-metric deterministic rate by system.
- Pairwise preference (B1000 vs A primarily; B500 vs A, B2000 vs A, B500 vs B1000, B1000 vs B2000 secondarily).
- Feasibility-failure log (which system × question combinations failed which way).

Plus a **new v0.2-specific reporting block:**

- For each B-variant, the average overlay-token utilization (mean tokens used / budget) across the question set.
- For each B-variant, count of beliefs admitted by tier (1 / 2 / 3 / 4 / 5 / 6 / 7-summary).
- For each B-variant, count of beliefs *omitted* by tier, where countable.

---

## 7. Open questions / TBDs before lock

- **Q1.** Tie-breaks within a tier — **CLOSED.** Locked in §3.4: out-of-window before in-window, `last_updated_turn` desc, authority rank, deterministic hash of `belief_id`.
- **Q2.** Should B0 be run at all? **CLOSED → skip B0.** The v0.1 dataset serves as the unbounded-overlay reference (same question set, K, tool-output cap, and generator model family). B0 is removed from the v0.2 candidate systems; v0.1 numbers stand as the reference comparison.
- **Q3.** Minimal rendering shape — **CLOSED.** Locked in §3.5: `lifecycle_state · belief_type · claim_short · authority · last_updated_turn`, optional `warrant_count` if budget allows. Evidence/revision trails are excluded from the overlay.
- **Q4.** Strict vs soft budget — **CLOSED → strict.** Locked in §3.2 + §3.5: beliefs that do not fit on one line under the remaining budget are dropped entirely. The header reserve is computed from a worst-case placeholder render so the cap is honestly enforced. (Validated at fixture level in [TKOS-002 implementation note](../tkos_sidecar/TKOS-002_IMPLEMENTATION_NOTE_v0.1.md).)
- **Q5.** v0.1 oracle / scorer / judge configs — **CLOSED → frozen.** Locked from v0.1: same gpt-5-mini deterministic judge, same gpt-4.1 preference judge, same scoring logic, same disagreement policy. No prompt tuning, no config review.
- **Q6.** Budget header in overlay — **CLOSED → yes.** Locked in §3.5: header line carries `budget / used / omitted / K`. Consistent with anti-silent-truncation policy.

---

## 8. Deliverables (in order)

1. **Locked v0.2 pre-registration** — this document, with §5 decisions resolved and §7 TBDs nailed down.
2. **Overlay ranking specification** — proposed in §3 here; to be lifted into its own short doc once §5 D4 is resolved.
3. **Context-budget policy** — proposed in §3.2; to be lifted into its own short doc once §5 D3 is resolved.
4. **Audit hooks list** — a short note specifying what is logged per (system, question) so the resulting run is auditable end-to-end (per the rolling rhythm: build → audit → pause).

**Not included in this draft, by user instruction:**

- Context construction (System A regeneration and B500/B1000/B2000 overlay rendering).
- Answer generation.
- Deterministic scoring.
- Preference judging.

These remain explicitly deferred until v0.2 is locked.

---

## 9. Anti-curation discipline (carry-forward from v0.1)

The v0.1 anti-curation discipline carries forward in full:

- Question text and judge prompts are blind to the overlay content.
- The deterministic scorer is consulted only post-generation.
- No prompt tuning after seeing outputs.
- No silent truncation; budget overruns surface as ranked dropouts (counted) or `api_error:RateLimitError` (recorded).
- All seeds, model IDs, and budget configurations are locked here before any data flows.

---

## 10. Non-goals

- v0.2 is not a sidecar implementation. The sidecar is sketched separately in `tkos_sidecar/TKOS_SIDECAR_SKETCH_v0.1.md`.
- v0.2 does not test substitutive belief overlays. The overlay remains additive.
- v0.2 does not introduce new belief types. Same v0.1 typology.
- v0.2 does not introduce new question categories. Same v0.1 set.
- v0.2 does not generalize across model families. Same v0.1 generator + judges.

---

*End of locked pre-registration. Eligible for execution as of 2026-06-02.*
