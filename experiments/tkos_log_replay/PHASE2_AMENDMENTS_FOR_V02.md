# Phase 2 — Amendments staged for v0.2

This file collects rule-language clarifications and small corrections that
have been identified during or after v0.1 implementation. These changes do
not affect the v0.1 measurement; they are staged for inclusion in a future
`PHASE2_PRE_REGISTRATION_v0.2.md`.

Discipline: nothing here is silently applied to the v0.1 implementation.
v0.1 measurements stand as v0.1. When v0.2 is written, this file's
amendments are folded in and dated.

---

## Pending amendments

### A-001 — Rename "suppressed threshold" → "intervention authority threshold"

**Source:** Editorial feedback, 2026-05-29.

**The issue:** In §2.9 of v0.1, the term "suppressed threshold" reads as
"above this level, suppression occurs." But the document defines it as the
weight above which **interventions backed by the belief may fire** —
i.e., the *opposite* of suppression. The current name is the meaning
exactly inverted from how a reader will parse it.

**Proposed v0.2 rename:** "intervention authority threshold" — the
authority-weight level at which a belief is strong enough to back a
runtime intervention.

**What does NOT change for v0.1:** the threshold value (≥ 0.7) and its
semantics are correctly implemented. The label is the only confusion.

**v0.1 implementation handling:** existing code uses `suppressed_threshold`
as the variable name to honor the locked terminology. The variable will be
renamed in v0.2.

---

### A-002 — Fix `stale_deploy_prior` so fresh `user_approval_required` suppresses deploy

**Source:** v0.1 measurement (see I-002 in PHASE2_ISSUES_LOG.md) + user direction 2026-05-29.

**The issue:** §3.2's parenthetical ("authority weight < suppressed threshold") inverts the §2.9 threshold semantics. Under the literal v0.1 reading the rule produced 0 SUPPRESS verdicts across 126 applicable deploy actions.

**Proposed v0.2 rewrite of §3.2 trigger:**

A `stale_deploy_prior` intervention fires when **all three conditions hold**:

1. `deploy_pending` belief is active (weight ≥ active threshold, 0.3).
2. The assistant turn attempts a deploy action (`git push`, `vercel --prod`).
3. `user_approval_required` belief is active AND its weight is **at or above the intervention authority threshold** (≥ 0.7).

The semantic flip: "user_approval_required is unsatisfied" now means the *requirement* is fresh and strong (high weight). If `user_approval_required` does not exist as an active instance OR has decayed below the authority threshold, the rule does NOT fire.

**TKOS verdict (unchanged):** SUPPRESS deploy action, surface `user_approval_required`.

---

### A-003 — Loosen `repeated_failure_loop` signature predicate

**Source:** v0.1 measurement (0 SUPPRESS verdicts across 830 applicable turns, 167 FN). The strict tool×error-keyword conjunction over-filters real loops with paraphrased error text.

**Proposed v0.2 signature-match function:**

Two turns share a "failure signature" if **any one** of the following holds (disjunction, not conjunction):

1. **Tool + error gist:** same tool name AND error-message Jaccard ≥ 0.5 over lowercased word bag (excluding stopwords).
2. **File path + command shape:** any shared file path AND any shared command first-token.
3. **Same error class:** same Python/JS exception class name (regex match `[A-Z][a-zA-Z]*Error\\b` on tool_result content), regardless of message details.

The "no material action between failures" constraint applies the **conservative rule** for v0.2: any Edit, Write, or MultiEdit tool use between matched failures counts as material. A refined rule that excludes whitespace-only / comment-only / repeated-identical patches (i.e., differentiating real fixes from trivial re-saves) is deferred to v0.3 pending inspection of example loops surfaced by v0.2. v0.2 keeps the cleanest implementable rule and accepts that some genuine no-op edits will be miscounted as material.

Re-running the identical failing Bash command with no Edit/Write between failures is NOT material.

---

### A-004 — Broaden `contradicted_fix_prior` applicability beyond Bash validation

**Source:** v0.1 measurement (0 applicable turns across 20,190 sampled). The applicability predicate required a Bash command matching VALIDATION_PATTERNS with tool_error, which never coincided in the substrate.

**Proposed v0.2 applicability (narrowed per editorial feedback 2026-05-29):**

A `contradicted_fix_prior` evaluation point exists when **both** hold:

1. `fix_attempted` belief is active at the evaluation turn.
2. The evaluation turn produces evidence of failure that is *contextually related to the fix*. Specifically, at least one of the following holds:

   **(a) Same anchor / touched file** — the failing tool result references a file path that overlaps with the set of files edited in the `fix_attempted`'s birth turn or any of its refresh turns. File-path overlap is computed as set intersection over lowercased path tokens.

   **(b) Same command family** — the failing turn runs a Bash command whose first-token matches a first-token used in the `fix_attempted`'s birth turn or any of its refresh turns (e.g., the fix touched `scripts/x.py` via Edit and the failing turn runs `python scripts/x.py`; or both turns ran `pytest`).

   **(c) Validation context** — the failing turn matches the expanded v0.2 validation pattern set:
   - Bash `pytest`, `npm test`, `tsc`, `--check`, `--validate`, `--noEmit`, `git status`, `git diff` (v0.1 set)
   - Any Bash command whose tool_result includes traceback / exception text / `error:` / non-zero exit
   - Any non-Bash tool call whose result is `is_error: true`

The validation context (c) is the broadest predicate and intentionally so: a failed `pytest` or `tsc` close after a fix is almost always relevant to the fix even when files don't textually overlap. The anchor and command-family predicates (a, b) catch fixes whose validation isn't through formal test tooling.

**What this rules OUT:** an unrelated tool error (e.g., `ls` on a different directory, an exploratory `grep` while the fix is still active) does NOT count as a contradiction unless it overlaps with one of (a), (b), or (c).

**TKOS verdict (unchanged):** RETIRE `fix_attempted`'s implicit "fix succeeded" sub-belief AND mark `fix_attempted` as contradicted.

---

### A-005 — Recalibrate `stale_pipeline_prior` threshold

**Source:** v0.1 measurement (FPR 17.9% at 20-min threshold suggests miscalibration; many long pipelines complete fine without status check).

**Proposed v0.2 threshold:** **30 minutes** (1× the pipeline_running half-life, up from 20 min = 0.66× half-life).

Rationale: the half-life is the calibrated decay scale; using the half-life directly as the "stale" threshold ties the rule to the same time constant that already governs the belief weight. The v0.1 20-min figure was set ad-hoc as "2× expected duration."

**Reporting discipline:** v0.1 (20 min) and v0.2 (30 min) measurements are reported **separately** with a head-to-head table. No retroactive replacement of v0.1 figures.

---

## Note on v0.2 measurement isolation

When v0.2 measurement runs, it writes parallel output files (`*_v0_2.jsonl`) and a separate `PHASE2_REPORT_v0_2.md`. The v0.1 outputs are not modified or deleted. The v0.2 report includes a comparison section against v0.1 numbers.
