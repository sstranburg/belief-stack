# Phase 2 — Pre-registration (v0.2)

This document is a derivative of [PHASE2_PRE_REGISTRATION_v0.1.md](PHASE2_PRE_REGISTRATION_v0.1.md) with the five amendments staged in [PHASE2_AMENDMENTS_FOR_V02.md](PHASE2_AMENDMENTS_FOR_V02.md) folded in. v0.1 results stand as v0.1. v0.2 results are reported separately. Locked 2026-05-29.

**Reading guide:** sections unchanged from v0.1 are summarized; sections with substantive changes are quoted in full with the v0.2 differences marked.

---

## 0. Why this document exists

Unchanged from v0.1. The v0.1 pre-registration discipline produced a clean, falsifiable measurement: three of four intervention rules turned out to be structurally unable to fire at scale, and that failure is itself the v0.1 finding. v0.2 amends the rule operationalizations that the v0.1 measurement revealed as too narrow, while preserving the same success criterion and corpus.

---

## 1. Success criterion

Unchanged from v0.1:

> Can TKOS replay identify stale or contradicted state-level beliefs in long-running assistant sessions, using pre-registered rules, while accounting for false positives?

---

## 2. State-level belief definitions (8 beliefs)

Belief definitions, half-lives, birth/refresh/retire/contradict conditions, and the active threshold (≥ 0.3) are **unchanged from v0.1 §2**. Only the threshold *terminology* changes:

### 2.9 Common rules across all beliefs (v0.2 update)

- **Belief identity:** identified by `(belief_name, anchor)`. Unchanged.
- **Default warrant authority weight at birth:** 1.0. Unchanged.
- **Active threshold:** weight ≥ 0.3. Unchanged.
- **Intervention authority threshold** (v0.2 rename of "suppressed threshold"): weight ≥ 0.7. Above this level, the belief is strong enough to back a runtime intervention. Below this level, the belief is too weak to authorize a suppression or retirement on its own. Value unchanged from v0.1.
- **Stale threshold:** weight < 0.3 with no refresh → automatic retirement at next observation. Unchanged.

Per A-001, the variable name `suppressed_threshold` in v0.1 code is renamed to `intervention_authority_threshold` in v0.2 code. The numeric value (0.7) is unchanged.

---

## 3. Intervention catalog (4 patterns, v0.2)

### 3.1 `repeated_failure_loop` (v0.2)

**Definition:**

A repeated-failure loop is detected when **all three conditions hold**:

1. The same operational region (`failure_diagnosis` or a region with `validation_status: FAIL`, or any region with `tool_error: true`) repeats **≥ 3 times** within a sliding window of **10 turns**.
2. The failure signatures match per the v0.2 signature-match function (below).
3. **No "material action" intervenes** between failures, where "material" is defined per the v0.2 relaxation (below).

#### 3.1.1 v0.2 signature-match function (per A-003)

Two turns share a failure signature if **any one** of the following holds (disjunction):

- **Tool + error gist:** same tool name AND error-message Jaccard similarity ≥ 0.5 over a lowercased word bag with English stopwords removed.
- **File path + command shape:** the two turns share at least one file-path token AND share at least one Bash command first-token.
- **Same exception class:** both tool_results contain a token matching `[A-Z][a-zA-Z]*Error\b` (Python/JS exception class) and the matched tokens are identical between turns.

#### 3.1.2 v0.2 material-action rule (per A-003, conservative)

A turn between two matched failures counts as "material" if it contains **any** Edit, Write, or MultiEdit tool use. Re-running the identical failing Bash command with no Edit/Write between failures is NOT material.

This is the conservative reading: a same-file edit DOES count as material in v0.2, because in many real cases a same-file edit IS the actual fix. A more refined rule that distinguishes substantive edits from whitespace-only, comment-only, or repeated-identical patches is deferred to v0.3 pending inspection of example loops surfaced by v0.2. v0.2 accepts that some genuine no-op edits will be miscounted as material; the next iteration can tighten this once we have concrete examples.

**TKOS verdict:** SUPPRESS the next failure-retry action.

### 3.2 `stale_deploy_prior` (v0.2)

**Trigger (per A-002):**

A `stale_deploy_prior` intervention fires when **all three conditions hold**:

1. `deploy_pending` belief is active (weight ≥ 0.3).
2. The evaluation turn attempts a deploy action (`git push`, `vercel --prod`).
3. `user_approval_required` belief is active AND its weight is **at or above the intervention authority threshold** (≥ 0.7).

If `user_approval_required` does not exist as an active instance, or has decayed below the intervention authority threshold, the rule does NOT fire — the requirement has either been resolved or is too weak to authorize blocking the deploy.

**TKOS verdict:** SUPPRESS deploy action, surface `user_approval_required`.

**v0.1 → v0.2 semantic change:** The literal v0.1 reading was "user_approval_required.weight < 0.7 → suppress." The v0.2 rule inverts this: "user_approval_required.weight ≥ 0.7 → suppress." Both measurements are reported.

### 3.3 `stale_pipeline_prior` (v0.2)

**Trigger (per A-005):**

- `pipeline_running` belief active AND
- (current time − last_refresh_ts) > **30 minutes** (up from 20 min in v0.1)

**TKOS verdict:** REQUIRE explicit status check before continuing other operations that depend on the pipeline's output.

**Rationale:** 30 minutes equals the `pipeline_running` half-life. v0.1's 20 min was ad hoc. Reporting includes a head-to-head v0.1 vs v0.2 detection-rate and FPR comparison.

### 3.4 `contradicted_fix_prior` (v0.2, narrowed)

**Trigger (per A-004, narrowed by editorial feedback 2026-05-29):**

A `contradicted_fix_prior` evaluation point exists when **both** hold:

1. `fix_attempted` belief is active at the evaluation turn.
2. The evaluation turn produces evidence of failure that is *contextually related to the fix*. At least one of the following must hold:

   **(a) Touched file overlap** — the failing tool result references a file path that overlaps with the set of files edited in the `fix_attempted`'s birth turn or any of its refresh turns. Computed as set intersection over lowercased path tokens.

   **(b) Command family overlap** — the failing Bash command's first-token matches a first-token used in the `fix_attempted`'s birth turn or any of its refresh turns (e.g., the fix touched `scripts/x.py` and the failing turn runs `python scripts/x.py`; or both turns ran `pytest`).

   **(c) Validation context** — the failing turn matches the expanded v0.2 validation pattern set:
   - Bash `pytest`, `npm test`, `tsc`, `--check`, `--validate`, `--noEmit`, `git status`, `git diff` (v0.1 set)
   - Any Bash command whose tool_result includes traceback / exception text / `error:` / non-zero exit
   - Any non-Bash tool call whose result is `is_error: true`

The validation context (c) is the broadest predicate: a failed `pytest` or `tsc` close after a fix is almost always relevant even when files don't textually overlap. Predicates (a) and (b) catch fixes whose validation isn't through formal test tooling.

**What this rules OUT:** an unrelated tool error (e.g., `ls` on a different directory, an exploratory `grep` while a fix is still active) does NOT count as a contradiction unless it overlaps with (a), (b), or (c).

**TKOS verdict:** RETIRE `fix_attempted`'s implicit "fix succeeded" sub-belief AND mark `fix_attempted` as contradicted. The next turn must not act as if the fix worked.

### 3.5 Out of scope for v0.2

Unchanged from v0.1 §3.5: intent-classification interventions, multi-turn semantic drift detection, factual-correctness checks against external sources, model-confidence interventions.

---

## 4. Sampling protocol

Unchanged from v0.1. Same seed (20260529), same cap (200/session), same 164 sessions, same expected sample size (~20,190 turns). The sample file `data/phase2_sample.json` from v0.1 is reused; no new sampling.

---

## 5. Labeling protocol (TP / FP / FN / TN)

Unchanged from v0.1 in semantics. Lookahead remains 5 turns. The §5.3 user-correction patterns are unchanged. UNCERTAIN tagging follows I-004's narrow operational definition (no follow-up turns within the session).

---

## 6. Reporting protocol (v0.2 addition)

The v0.2 report includes everything from v0.1 §6 plus:

7. **Head-to-head comparison section** with a table of v0.1 vs v0.2 per-rule numbers (applicable, TP, FP, FN, TN, UNCERTAIN, detection rate, FPR).
8. **Delta annotation** per rule explaining what changed and by how much, attributing each delta to the responsible v0.2 amendment (A-002 to A-005).
9. **§6.1 honesty constraints unchanged**: no "TKOS improves Claude" claim, no F1/accuracy threshold framing, no generalization beyond corpus.

---

## 7. Versioning policy

Unchanged from v0.1 §7. v0.2 is itself a major rule change relative to v0.1; any subsequent rule edit requires a v0.3 pre-registration. Bug fixes to classifier code that do not change rule semantics may be recorded in a Phase 2 changelog without a version bump.

---

## 8. What Phase 2 v0.2 implementation will produce

```
tkos_log_replay/
  phase2_belief_tracker.py            (unchanged from v0.1 — beliefs same)
  phase2_intervention_catalog_v0_2.py (v0.2 rule operationalizations)
  phase2_label_outcomes_v0_2.py       (unchanged labeling logic, v0.2 verdicts in)
  phase2_report_v0_2.py               (v0.2 report + head-to-head with v0.1)
  data/
    phase2_intervention_verdicts_v0_2.jsonl
    phase2_labeled_outcomes_v0_2.jsonl
    phase2_report_v0_2.json
  PHASE2_REPORT_v0_2.md
```

v0.1 artifacts under `data/` are NOT touched. The v0.2 belief-tracker is identical to v0.1's (the belief definitions did not change in v0.2), so `data/phase2_belief_timelines.jsonl` is shared between runs.

---

## 9. Audit trail

| Field | Value |
|---|---|
| Author | Susan Stranburg |
| Locked | 2026-05-29 |
| v0.1 reference | [PHASE2_PRE_REGISTRATION_v0.1.md](PHASE2_PRE_REGISTRATION_v0.1.md) |
| Amendments folded | A-001, A-002, A-003, A-004, A-005 (see PHASE2_AMENDMENTS_FOR_V02.md) |
| Hash of v0.1 artifacts at lock time | (computed at v0.2 first run; v0.1 artifacts remain immutable) |
| Rules version | v0.2 |
| Spec reference | https://topicspace.ai/research/belief-stack v0.1 |
| Schema reference | https://topicspace.ai/schemas/warrant-v0.1.json |

---

## 10. What changes (for reviewers)

| Section | v0.1 | v0.2 | Source |
|---|---|---|---|
| §2.9 threshold name | "suppressed threshold" | "intervention authority threshold" | A-001 |
| §3.1 signature match | Strict tool×err prefix conjunction | Disjunction of three predicates including Jaccard ≥ 0.5 | A-003 |
| §3.1 material action | Any Edit/Write counts | Any Edit/Write counts (unchanged; v0.3 may refine) | A-003 |
| §3.2 user_approval_required condition | weight < threshold = unsatisfied = suppress | weight ≥ threshold = active requirement = suppress | A-002 |
| §3.3 stale-pipeline threshold | 20 min | 30 min | A-005 |
| §3.4 applicability | Bash validation + tool_error | tool_error during active fix_attempted that shares touched-file, command-family, OR validation context | A-004 |
| §6 reporting | Per-rule + sample + methodology | Adds head-to-head v0.1 vs v0.2 + delta attribution | new |

No changes to: belief definitions (§2.1–§2.8), sampling (§4), labeling lookahead (§5), success criterion (§1), out-of-scope items (§3.5).
