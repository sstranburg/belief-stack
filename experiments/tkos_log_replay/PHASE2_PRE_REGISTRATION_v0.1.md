# F-023 Phase 2 — Pre-Registration Document (v0.1)

**Version:** v0.1
**Locked:** 2026-05-29
**Status:** Pre-registration. All rules below are locked before any Phase 2 measurement is run. Any change requires a version bump (v0.2, v0.3 …) — silent edits forbidden.

---

## 0. Why this document exists

The F-023 backlog card requires that intervention criteria be **defined before reading the logs**. This document satisfies that requirement for Phase 2. Once any measurement is computed against the locked rules, this document becomes the audit trail for what was decided in advance versus tuned after the fact.

If the resulting numbers look "wrong" — too few interventions caught, too many false positives, too small a sample — the correct response is to **report the finding** and propose v0.2. Not to silently revise v0.1.

---

## 1. Success criterion

**The Phase 2 success criterion is NOT "TKOS improves Claude."**

The success criterion is:

> Can TKOS replay identify stale or contradicted state-level beliefs in long-running assistant sessions, using pre-registered rules, while accounting for false positives?

That is a measurement question, not a performance claim. The Phase 2 report's headline number is **the detection rate of pre-registered intervention conditions across a stratified random sample, with an explicit false-positive count alongside it**. Not an F1, not an "improvement over baseline," not any framing that implies live impact.

---

## 2. State-level belief definitions (8 beliefs)

These are the cross-turn state-level beliefs Phase 2 will track. Each one is a **decaying warrant** in the v0.1 schema sense — born under a specific condition, refreshed by evidence, retired by another condition, and subject to a half-life if neither refresh nor retirement fires.

### 2.1 `pipeline_running`

| Field | Value |
|---|---|
| Birth | Assistant turn classified `pipeline_run` that initiated a long-running process. Detected by: (a) `run_in_background: true` on a Bash tool_use, OR (b) known long-running scripts (`scripts/run_pipeline.py`, `scripts/build_backtest_history.py`, `generate_ai_compass.py`). |
| Refresh | Subsequent tool_result containing fresh process evidence (`ps aux | grep ...`, log file tail, `task-notification` with status=running). |
| Retirement | tool_result containing completion evidence: `task-notification` with status=completed/failed, exit code, or explicit assistant turn confirming end. |
| Contradiction | tool_result showing the process died unexpectedly OR tool error in pipeline-tooling Bash within the window. |
| Decay half-life | **30 minutes** (typical pipeline completes in 5–15 minutes; after 30 minutes the belief should weaken). |
| Allowed interventions | status checks, `ps aux`, log inspection, wait, kill-and-retry. |

### 2.2 `pipeline_failed`

| Field | Value |
|---|---|
| Birth | tool error in pipeline-tooling Bash OR `pipeline_running` retired with FAIL status. |
| Refresh | Any new diagnostic step on the same pipeline. |
| Retirement | Explicit turn confirming root cause identified OR subsequent successful `pipeline_run` for the same task. |
| Contradiction | Successful pipeline completion for the same task within the window. |
| Decay half-life | **60 minutes**. |
| Allowed interventions | diagnose, retry, escalate to user. |

### 2.3 `issue_under_diagnosis`

| Field | Value |
|---|---|
| Birth | Turn classified `failure_diagnosis`. |
| Refresh | Continued `failure_diagnosis` turns on the same error signature. |
| Retirement | Explicit turn stating root cause OR turn transitioning to `fix_attempted`. |
| Contradiction | Discovery that the original framing was wrong (a new error signature replaces the original). |
| Decay half-life | **45 minutes**. |
| Allowed interventions | continue diagnosis, escalate. |

### 2.4 `fix_attempted`

| Field | Value |
|---|---|
| Birth | Assistant turn making a substantive change (Edit, Write, Bash with side effect) after `issue_under_diagnosis` was active. |
| Refresh | `validation_pending` fires for the same artifact. |
| Retirement | `validation` PASS confirms the fix. |
| Contradiction | `validation` FAIL after `fix_attempted`. |
| Decay half-life | **15 minutes** (fix attempts should be validated quickly). |
| Allowed interventions | run validation, additional fix attempts. |

### 2.5 `validation_pending`

| Field | Value |
|---|---|
| Birth | `fix_attempted` born with no immediate validation in the same or next turn. |
| Refresh | Validation turn occurs and emits a result. |
| Retirement | Validation result observed (PASS or FAIL). |
| Contradiction | Time passes (decay) without validation. |
| Decay half-life | **10 minutes**. |
| Allowed interventions | run validation. |

### 2.6 `deploy_pending`

| Field | Value |
|---|---|
| Birth | `report_ready` belief active AND explicit deploy intent expressed (user "deploy" / "ship it") OR assistant about-to-deploy framing. |
| Refresh | User-side deploy approval signal. |
| Retirement | Deploy command executed (git push, vercel --prod). |
| Contradiction | Validation FAIL after `deploy_pending` OR user explicit hold ("wait", "not yet"). |
| Decay half-life | **60 minutes** (approval gets stale). |
| Allowed interventions | wait for approval, request approval, present diff. |

### 2.7 `report_ready`

| Field | Value |
|---|---|
| Birth | Assistant turn completes a `report_generation` action and the artifact is observable (file written, output shown). |
| Refresh | User reviews report (any user turn referencing the report file). |
| Retirement | User takes action on the report (deploy, share, next iteration), OR new report supersedes it. |
| Contradiction | Corrections fired against the report content. |
| Decay half-life | **4 hours**. |
| Allowed interventions | present to user, link to artifact. |

### 2.8 `user_approval_required`

| Field | Value |
|---|---|
| Birth | Assistant proposes an action with risk (deploy, destructive Bash, send to remote) AND no prior explicit approval is in the active window. |
| Refresh | User provides approval signal. |
| Retirement | Action authorized and executed OR action abandoned. |
| Contradiction | User declines explicitly OR walks away from the thread. |
| Decay half-life | **30 minutes**. |
| Allowed interventions | wait, present action, ask explicitly. |

### 2.9 Common rules across all beliefs

- **Belief identity:** identified by `(belief_name, anchor)` where `anchor` is a stable substrate reference (typically a file path, command pattern, session-local task ID).
- **Default warrant authority weight at birth:** 1.0.
- **Active threshold:** weight ≥ 0.3. Below this, the belief is considered weakened and unsuitable for backing interventions.
- **Suppressed threshold:** weight ≥ 0.7. Above this, interventions backed by the belief may fire without additional check.
- **Stale threshold:** weight < 0.3 with no refresh → automatic retirement at next observation.

---

## 3. Intervention catalog (4 patterns, v0.1)

Each intervention is a TKOS-replay rule: at a given assistant action, check whether the action's prerequisite belief survives at firing time. Pass / fail per intervention.

### 3.1 `repeated_failure_loop`

**Definition (the strongest sub-claim per the F-023 backlog card):**

A repeated-failure loop is detected when **all three conditions hold**:

1. The same operational region (`failure_diagnosis` or a region with `validation_status: FAIL`) repeats **≥ 3 times** within a sliding window of **10 turns**.
2. The failure signatures are the **same**, defined as: same tool name AND same error keyword OR same file path AND same command pattern. The match function is documented in `phase2_signature_match.md` (forthcoming, v0.1).
3. **No "material action" intervenes** between failures. A material action is a turn that makes a substantive change: edits a different file, runs a different command shape, or invokes a different tool sequence.

**TKOS verdict:** SUPPRESS the next failure-retry action. The system should flag the loop and require state revision (the `fix_attempted` belief retired, new `issue_under_diagnosis` re-anchored on a different signature) before the next attempt.

### 3.2 `stale_deploy_prior`

**Trigger:**
- `deploy_pending` belief active, AND
- Assistant turn attempts a deploy action (`git push`, `vercel --prod`), AND
- `user_approval_required` belief is unsatisfied (authority weight < suppressed threshold).

**TKOS verdict:** SUPPRESS deploy action, surface `user_approval_required`.

### 3.3 `stale_pipeline_prior`

**Trigger:**
- `pipeline_running` belief older than **2× the expected duration** (typical pipeline = 10 min → 20 min threshold) without fresh tool evidence.

**TKOS verdict:** REQUIRE explicit status check before continuing other operations that depend on the pipeline's output.

### 3.4 `contradicted_fix_prior`

**Trigger:**
- `fix_attempted` belief active, AND
- `validation_pending` fires with `validation_status: FAIL`.

**TKOS verdict:** RETIRE `fix_attempted`'s implicit "fix succeeded" sub-belief AND mark `fix_attempted` as contradicted. The next turn must NOT act as if the fix worked.

### 3.5 Out of scope for v0.1

These interventions are explicitly deferred to v0.2 or later:
- intent-classification interventions ("user wants X but you're doing Y")
- multi-turn semantic drift detection
- factual-correctness checks against external sources
- model-confidence interventions

---

## 4. Sampling protocol

### 4.1 Universe
All 83,271 turns produced by Phase 1 are eligible for sampling. UNCLASSIFIED turns are not removed from the universe — they contribute to the loop-detection and stale-belief evaluation.

### 4.2 Random seed
**Seed = 20260529** (today's date as a single integer). Documented here and in the Phase 2 code; not to be changed once measurement begins.

### 4.3 Sampling method

- **Stratified by session.** From each of the 164 sessions, sample turns uniformly without replacement.
- **Cap per session:** min(200, n_turns_in_session). Prevents the largest session (591632ad with 26k turns) from dominating the eval.
- **Expected eval size:** ~1,000–2,000 evaluation turns total, depending on session size distribution.

### 4.4 What sampling produces

A list of `(session_id, turn_idx)` evaluation points. For each, Phase 2 will:
1. Re-construct the belief state immediately preceding the evaluation turn (from the full session's preceding turns).
2. Check each of the four intervention rules against that belief state and the turn's content.
3. Record the TKOS verdict (SUPPRESS / ALLOW) per intervention rule per turn.
4. Compare against the offline ground-truth labeling protocol (§5) to produce TP / FP / FN / TN counts.

---

## 5. Labeling protocol (TP / FP / FN / TN)

### 5.1 Ground truth

For each TKOS-replay verdict, the actual run is labeled by **observing what happened next in the same session**. This is offline retrospective ground truth — it tells us whether the action TKOS would have suppressed produced a problem the user later corrected, OR whether the action was fine.

### 5.2 Truth labels

| Label | TKOS verdict | Actual outcome |
|---|---|---|
| **TP** (true positive) | SUPPRESS | The actual run produced a stale/wrong/looping output AND the user issued a correction OR the assistant looped further OR the actual outcome was clearly wrong by the next turn's evidence |
| **FP** (false positive) | SUPPRESS | The actual run was fine — no user correction within 5 turns, no further looping, no contradiction by subsequent evidence |
| **FN** (false negative) | ALLOW | The actual run produced a stale/wrong/looping output AND the user issued a correction OR further looping occurred |
| **TN** (true negative) | ALLOW | The actual run was fine |

### 5.3 "User correction" detection

Reuses the patterns pre-registered in `classify_regions.py` v0.1:
- `^no,?\s+(that|that's|this|wait)\b`
- `\bwrong\b`
- `\bthat'?s not right\b`
- `\blet me correct\b`
- `\bactually,?\s+(no|that|i mean)\b`
- `\bcan you fix\b`

Plus, for this protocol:
- Further `tool_error` within the 5-turn window for the same error signature counts as a "loop continued" signal (TP for `repeated_failure_loop`).

### 5.4 Time window

The look-ahead window for ground-truth labeling is **5 turns** after the evaluation point. This is short enough to avoid attributing later, unrelated corrections; long enough to catch the immediate "did this matter?" question.

### 5.5 Ambiguous cases

Turns where neither correction nor success can be confidently labeled within the window are tagged **UNCERTAIN** and reported as a separate count alongside TP/FP/FN/TN. They do not enter precision or recall calculations. The fraction of UNCERTAIN labels is itself a methodology metric — high UNCERTAIN rate means the offline protocol can't measure cleanly.

---

## 6. Reporting protocol

The Phase 2 report will include:

1. **TP / FP / FN / TN counts** per intervention rule, plus the UNCERTAIN count.
2. **Detection rate** = TP / (TP + FN), reported per rule, with the absolute count alongside (not just the percentage).
3. **False-positive rate** = FP / (FP + TN), reported per rule, alongside absolute counts.
4. **Per-session breakdown** of TP / FP for each rule, so concentration effects are visible.
5. **Repeated-failure-loop subsection** with at least 3 anonymized example loops detected.
6. **Methodology section** that reproduces this pre-registration document and notes any deviations or v0.x amendments made along the way.

### 6.1 What the report will NOT claim

- "TKOS improves Claude" — out of scope; offline replay is not live impact.
- A specific F1 or accuracy threshold as "good" or "bad" — only the rates are reported.
- That the pre-registered rules are correct beyond what the data shows. They are a v0.1 proposal.
- Generalization beyond this user's corpus. The substrate is one user's Claude session logs over 10.5 weeks.

---

## 7. Versioning policy

- This is **v0.1** of the Phase 2 pre-registration.
- Any change to belief definitions, intervention catalog, sampling protocol, or labeling protocol after measurement begins is a **major rule change** and requires a new document (`PHASE2_PRE_REGISTRATION_v0.2.md`). The v0.1 measurement results stay valid as the v0.1 measurement; v0.2 results are reported separately and compared.
- Bug fixes to classifier code that do not change rule semantics may be made without version bump, but must be recorded in a Phase 2 changelog.

---

## 8. What Phase 2 implementation will produce

```
tkos_log_replay/
  phase2_belief_tracker.py        builds state-level belief timelines per session
  phase2_intervention_catalog.py  applies the 4 intervention rules
  phase2_label_outcomes.py        computes TP/FP/FN/TN against pre-registered ground truth
  phase2_sample.py                stratified sample with seed=20260529
  data/
    phase2_sample.json
    phase2_belief_timelines.jsonl
    phase2_intervention_verdicts.jsonl
    phase2_labeled_outcomes.jsonl
    phase2_report.json
  PHASE2_REPORT.md                human-readable report
```

The implementation must reference this pre-registration document by version. If implementation discovers an ambiguity in the pre-registration, the discovery is recorded in a Phase 2 issues log and resolved at v0.2, not silently in code.

---

## 9. Audit trail

| Field | Value |
|---|---|
| Author | Susan Stranburg |
| Locked | 2026-05-29 |
| Hash of Phase 1 artifacts at lock time | (computed at first Phase 2 run) |
| Rules version | v0.1 |
| Spec reference | https://topicspace.ai/research/belief-stack v0.1 |
| Schema reference | https://topicspace.ai/schemas/warrant-v0.1.json |
