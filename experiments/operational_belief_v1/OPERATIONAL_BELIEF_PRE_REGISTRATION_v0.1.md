# Operational Belief-State Grounding v0.1 — Pre-Registration (DRAFT)

**Status: DRAFT — not locked.** TBD callouts mark every parameter that must be decided before this becomes a pre-registered experiment.

**Author:** Susan Stranburg
**Drafted:** 2026-06-01
**Locked:** _(pending)_

**Sibling pre-registration:** [STACK_GROUNDED_PRE_REGISTRATION_v0.1.md](../stack_grounded_v1/STACK_GROUNDED_PRE_REGISTRATION_v0.1.md) — same discipline (pre-register → lock → run-once → head-to-head reporting); different usage pattern (operational belief-state vs world belief-state).

---

## 0. Why this document exists

Stack-Grounded Retrieval v0.1 tested the *world-belief* usage pattern of Belief Stack: can a substrate of maintained beliefs about an external domain (markets) ground LLM answers better than chunk retrieval alone? The deterministic gate fell against the belief-state system. The substrate carried narrative-cluster lifecycle metadata but lacked the propositional structure required for synthesis-heavy questions.

This experiment tests a different and more naturally fit usage pattern: the **operational-belief** layer. Long-running LLM assistants accumulate operational beliefs ("validation has run," "the user has not approved deploy," "this is a repeated failure of the same kind") that are discrete, typed, and tied to specific points in a session log. The TKOS log-replay work has already produced such a substrate from real Claude-session logs.

The animating problem stays the same — **the LLM that forgot time** — but the scoped question is sharper:

> Given the same assistant-session trace up to turn T, does adding an operational belief-state overlay help an LLM answer workflow-state questions more correctly than raw recent-log context alone?

If yes, the operational wedge is a real application path for Belief Stack. If no, even the more naturally fit substrate isn't legible enough under a minimal prompt, and the architecture needs another rethink.

---

## 1. Success criterion

The v0.1 measurement has a **primary deterministic gate** and a **lighter preference measurement**, reported separately. Preference cannot rescue failure on deterministic grounding. _(Same discipline as Stack-Grounded §1.)_

**Primary deterministic hypothesis (the gate):**

> System B (raw log context **+** operational belief-state overlay) will produce a lower aggregate error rate across the five operational metrics than System A (raw log context alone), under architectural belief-cutoff enforcement.

The five metrics are:

| Metric | Description | Scoring |
|---|---|---|
| stale_validation_assumption | Asserts that validation has happened when log-forward shows it has not | Programmatic |
| repeated_failure_loop | Fails to flag that this is the same failure signature seen recently | Programmatic |
| premature_action | Recommends deploy / commit / merge before user approval or readiness | Mostly programmatic |
| false_completion_claim | Asserts "done" while operational state is incomplete | Judge-assisted |
| missing_pause | Fails to pause / decline / ask for clarification when state is unresolved | Judge-assisted |

**Secondary preference hypothesis** (lighter than Stack-Grounded's three axes):

> Blind pairwise judging will prefer System B over System A on operational *traceability* (does the answer cite specific operational state?) and *appropriate caution* (does the answer pause when state is unresolved?).

Per the locked discipline:

> Preference is not correctness. Correctness is not preference. Divergence between deterministic and preference results is reported as a finding, not averaged away.

**Why deterministic is the gate:** if System B asserts validation has run when it hasn't, or fails to flag a repeated failure loop, the architectural claim ("operational belief overlay helps the LLM handle time correctly") is invalidated regardless of how favorably the answers are judged.

The four-quadrant outcome space carries over: each of {both confirmed, det only, pref only, both flat} is publishable. A "preference only" result is reported as "preferred but less accurate," not as a win.

---

## 2. Substrate

### 2.1 Trace corpus

**Locked:** TKOS Claude-session logs as parsed by `tkos_log_replay/`.

| Source | Path | Scale |
|---|---|---|
| Parsed turn ledger | `tkos_log_replay/data/reasoning_ledger.jsonl` | 83,271 turns |
| Belief timelines | `tkos_log_replay/data/phase2_belief_timelines.jsonl` | 11,262 belief instances |
| Intervention verdicts | `tkos_log_replay/data/phase2_intervention_verdicts.jsonl` | 4,102 verdicts |
| Session sample | `tkos_log_replay/data/phase2_sample.json` | 164 sessions, ~20K eval turns |

**§2.1.1 — Session scope — LOCKED.**

Eligible corpus: the existing 164-session TKOS Phase 2 sample at `tkos_log_replay/data/phase2_sample.json`, plus their corresponding rows in `reasoning_ledger.jsonl`. No expansion beyond Phase 2's sampled set in v0.1.

**Selection rule: balanced subset, NOT incident-only.** Incident-filtered sampling would introduce selection bias toward sessions where the failure modes the experiment measures already occurred — which would inflate the apparent value of the belief overlay (since System B is most useful exactly when failure modes are present). Balanced sampling means the question set must include questions where the operational state is *resolved / clean*, so the test isn't "can the overlay help on known failures?" but "can the overlay help under realistic state, including the states where nothing has gone wrong?"

Concretely, the eligible session set is partitioned by `phase2_sample.json` metadata into balance buckets (length, domain, incident-presence) and questions are drawn so each bucket contributes proportionally. Specific bucket boundaries are computed at construction time and recorded in the sampling audit (§4.6); no manual cherry-pick of "interesting" sessions.

### 2.2 Belief substrate (what System B sees over and above System A)

Each operational belief object carries **only structured state** — no instructions:

```json
{
  "belief_id":             "string",
  "session_id":            "string",
  "belief_type":           "string",     // see §2.3 typology TBD
  "operational_claim":     "string",     // e.g. "validation has run on the most recent change"
  "holder":                "assistant",  // single-holder by construction
  "turn_first_seen":       "integer",
  "turn_last_updated":     "integer",
  "lifecycle_state":       "active" | "weakened" | "contradicted" | "retired",
  "warrant_evidence_turns": ["integer", ...],
  "counterevidence_turns": ["integer", ...],
  "decay_status":          "fresh" | "decaying" | "stale",
  "revision_trail": [
    {"turn": int, "prior_claim": "...", "new_claim": "...", "trigger": "..."}
  ],
  "current_authority":     "asserted_by_assistant" | "confirmed_by_tool" | "confirmed_by_user"
}
```

**Two fields are deliberately richer than the market substrate carried:**

- `revision_trail` — the diff between belief versions, with the turn that triggered each revision. Operational beliefs *should* carry the diff; the market substrate's lack of this was a known v0.1 weakness.
- `current_authority` — who established the current claim (the assistant alone, a tool output, or a user statement). This is the operational analog of holder-perspective.

**TBD §2.2.1 — Field derivation rules.** How each field is computed from the existing TKOS artifacts must be documented before lock. Some fields (lifecycle_state, warrant_evidence_turns) are already in `phase2_belief_timelines.jsonl`. Others (revision_trail with deltas, current_authority) need extraction logic that doesn't yet exist.

### 2.3 Belief typology

The substrate restricts to a fixed set of operational belief types so the experiment doesn't conflate "belief grounding helps" with "the substrate happens to cover the question's type."

**Lock candidate (tentative):** the 11 belief types below. Final lock pending step 1 of the lock sequence (§ "Lock sequence" at the end of this document).

```
pipeline_running          — a long-running action is currently executing
pipeline_failed           — the most recent action ended in failure
issue_under_diagnosis     — the assistant is actively investigating an error
fix_attempted             — a fix has been proposed/applied but not yet validated
validation_pending        — validation expected but not yet observed
validation_complete       — validation observed in tool output
user_approval_pending     — assistant requested approval, none received
action_ready              — assistant believes preconditions for next action are met
action_blocked            — assistant believes one or more preconditions block proceeding
report_ready              — output artifact ready for user review
failure_signature_active  — the same failure signature has recurred ≥ N times
```

**Design notes:**

- `action_ready` / `action_blocked` replace the earlier `deploy_pending`. The TKOS corpus contains commit / push / run / publish / send / generate actions far more often than deploy specifically, so a more generic ready/blocked pair generalizes to the substrate. `action_blocked` is the assistant's *belief* that it cannot proceed, independent of which specific precondition is the blocker (those have their own belief types). The interesting failure mode is when `action_blocked` and `action_ready` disagree with the actual operational state — e.g. the assistant believes it's ready when `user_approval_pending` is still active.
- `validation_pending` and `validation_complete` are kept as a complementary pair because the transition between them is the load-bearing operational moment (and the most common stale-state failure: the assistant continues as if validation_complete when validation_pending is still active).
- `failure_signature_active` is the only type that requires extraction logic beyond field lifting — it depends on signature comparison across turns. Detection rule is locked separately in §6.2.

**Detection rules (locked):**

Eight of the eleven types reuse extraction rules already implemented in [`tkos_log_replay/phase2_belief_tracker.py`](../tkos_log_replay/phase2_belief_tracker.py); the rule body is whatever that script implemented at the point this pre-reg was locked. Four types are NEW for Operational Belief v0.1.

| Type | Source | Birth condition | Retire condition (`retired_reason`) | Half-life |
|---|---|---|---|---|
| **pipeline_running** | TKOS existing | Assistant turn issues a long-running pipeline tool (Bash with pipeline-script pattern) | `stale_decay`; `contradicted` on tool error from same Bash; `completion_evidence` on success observation in subsequent turn | per TKOS BELIEF_SPECS |
| **pipeline_failed** | TKOS existing | Tool error inside an active `pipeline_running` Bash | `stale_decay`; retired when `issue_under_diagnosis` or `fix_attempted` succeeds it | per TKOS BELIEF_SPECS |
| **issue_under_diagnosis** | TKOS existing | Assistant turn with diagnostic intent (Read/Grep over error-related files, or explicit "let me check why X failed") | `transitioned_to_fix_attempted`; `stale_decay` | per TKOS BELIEF_SPECS |
| **fix_attempted** | TKOS existing | Assistant turn with substantive change tool (Edit/Write/MultiEdit) following an active `issue_under_diagnosis` | `validation_observed_*` (passed/failed); `stale_decay`; `contradicted` if next tool error matches the same signature | per TKOS BELIEF_SPECS |
| **validation_pending** | TKOS existing | After `fix_attempted`, until a validation tool runs (test, typecheck, build, lint) | `validation_observed_pass` / `validation_observed_fail`; `stale_decay` | per TKOS BELIEF_SPECS |
| **validation_complete** | **NEW** | A validation tool returns success while `validation_pending` is active. This is the success-side analog of `validation_observed_pass` in TKOS retired_reasons — but tracked as a *positive belief* with its own lifecycle, not only as a retirement event | `stale_decay`; `contradicted` if subsequent code change invalidates (births a new `fix_attempted`) | 30 minutes (TBD) |
| **user_approval_pending** | TKOS existing (renamed from `user_approval_required`) | Assistant turn explicitly requests approval (e.g. "should I commit?" or "ready to deploy — confirm?") | `user_provided_approval`; `stale_decay` | per TKOS BELIEF_SPECS |
| **action_ready** | **NEW** | Assistant turn proposes an action verb (commit/push/run/publish/send/generate/deploy/merge) AND no concurrently-active blocking belief from {`user_approval_pending`, `validation_pending`, `pipeline_failed`, `pipeline_running`, `issue_under_diagnosis`} | `action_executed` (next assistant turn invokes the proposed tool); `contradicted` (a blocker belief becomes active before execution); `stale_decay` | 5 turns (TBD) |
| **action_blocked** | **NEW** | Assistant turn proposes an action AND at least one concurrently-active blocking belief exists | `blocker_cleared` (the blocking belief retires); `action_executed_despite_block` (the action runs anyway — flagged as a `premature_action` event for the deterministic gate); `stale_decay` | 5 turns (TBD) |
| **report_ready** | TKOS existing | Assistant produces a substantive Write/output artifact targeted at user review (e.g. report file, summary, recommendation block) | `user_acknowledged`; `superseded_by_new_report`; `stale_decay` | per TKOS BELIEF_SPECS |
| **failure_signature_active** | **NEW** | The signature `(tool_name, normalized_args, normalized_error_msg)` recurs ≥3 times within the last K=20 turns. Signature extracted from invoking assistant turn + paired tool_result turn per §6.2.2 — NOT the user-role failure turn | Signature does not recur for K turns (`signature_aged_out`); user explicitly steers off the loop (`user_redirected`); successful execution of the same signature (`signature_resolved`) | 10 turns (TBD) |

Half-lives marked TBD will be locked alongside §5.4 (engineering parameters). The four NEW types need a fresh implementation pass in `build_operational_belief_substrate.py`; the eight TKOS-existing types are projected directly from `phase2_belief_timelines.jsonl` with field rename (`belief_name` → `belief_type`; `user_approval_required` → `user_approval_pending`).

**Coverage exclusions** (deliberately not in the typology):
- `data_fetch`, `evidence_sealing` (from TKOS `operation_type` labels): too domain-specific; excluded.
- Free-text status descriptions ("doing X next"): not structured enough to extract as discrete beliefs.
- Multi-actor beliefs (assistant + user agreeing/disagreeing on a fact): single-holder discipline applies in v0.1.

**Composite belief discipline (locked):**

`action_ready` and `action_blocked` are *derived composites* — their definitions reference the active state of other beliefs. The substrate builder must compute the eight primary beliefs first, then derive the two action beliefs against the primary set. Order matters; if a derivation reads a stale snapshot, the composite is wrong. The implementation in `build_operational_belief_substrate.py` must topologically order: primaries → composites → signature recurrence.

### 2.4 Date / window

**§2.4.1 — Window — LOCKED: full Phase 2 sample window.**

Eligible sessions are every session in `phase2_sample.json` regardless of date. The Phase 2 sample was already a curated, time-bounded selection; v0.1 inherits its window verbatim. No additional date filtering. Recorded in the sampling audit (§4.6) for transparency.

### 2.5 Substrate-construction caveat (explicit, mirrors Stack-Grounded §2.3)

The belief substrate is **pre-computed** from the full session log. System B benefits from accumulated operational-state extraction that System A's raw log does not directly carry. This is the architectural claim being tested, not a confound to hide — but it must be stated explicitly in the report.

---

## 3. Systems under test

### 3.1 System A — raw log context (control)

Receives the last K turns of the session log up to turn T, including assistant messages, user messages, and tool outputs.

**§3.1.1 — K (recent-turn window) — LOCKED: K=20.**

Locked empirically against the diagnostic in `diagnostic_k_cap_sweep.py` (345 sample points across 115 sessions × 3 T-positions). Summary:

| K | cov_supporting | cov_error | tokens median / p90 / max | overflow vs 6000 |
|---|---|---|---|---|
| 10 | 15.4% | 5.3% | 873 / 1,862 / 4,421 | 0.0% |
| **20** | **28.3%** | **13.8%** | **1,774 / 3,434 / 6,930** | **0.3%** |
| 50 | 57.4% | 40.8% | 4,647 / 6,985 / 15,803 | 22.9% |

K=10 was rejected: misses 85% of belief-supporting events; slow-failure loops would not be detectable. K=50 was rejected: 23% of contexts overflow the 6000-token budget on long sessions, AND System A would see so much context that the overlay's contribution gets washed out (the experimental purity degrades when raw log already covers most of what the overlay carries).

K=20 leaves substantive coverage gap (~72% of belief-supporting events live outside the window) — that gap is the test surface. Whether the belief overlay adds value depends on it carrying information the recent log does not.

**§3.1.2 — Tool output rendering — LOCKED: verbatim with per-tool 500-token cap.**

Locked per the same diagnostic. Tool cap is currently a non-binding constraint: upstream `tkos_log_replay/parse_sessions.py` already truncates `output_summary` to ~600 chars (≈150 tokens), so neither 500 nor 1000 cap fires on the current substrate. Cap=250 was rejected (3.4% of outputs would be truncated; meaningful loss).

**Important caveat to flag in the v0.1 report**: cap=500 is the *design* limit; on this substrate it is *redundant* with upstream truncation. If a future substrate version retains fuller tool outputs without upstream pre-truncation, cap=500 would become the binding constraint. The rendering function MUST enforce cap=500 explicitly regardless of upstream state, so the design intent survives substrate changes.

Oversized tool outputs are token-truncated to the first 500 tokens followed by `[+N tokens elided]`. Implementation locked in the rendering function (TBD §5.4 — locks at first-run).

### 3.2 System B — raw log context + operational belief overlay (experimental)

Receives **everything System A receives**, plus a structured rendering of the currently-active operational beliefs as of turn T. This is the operational analog of "annotated retrieval" — additive, not replacement.

**Rendering rules** (mirror Stack-Grounded C1's narrative-prose discipline):

- Active beliefs listed first; weakened/contradicted next; recently-retired last
- Each belief renders its `operational_claim`, `lifecycle_state`, turn range, warrant_evidence_turn count, counterevidence_turn count, decay_status, and revision_trail entries
- Substrate-agnostic vocabulary — no TopicSpace jargon, no NDS, no market-state language
- No `answer_guidance` / `prompt_hint` / `caution_note` fields (per Stack-Grounded §3.5)

The LLM must derive caution, decline behavior, and traceability from the warrant fields alone.

### 3.3 What's NOT in v0.1

- No reasoning-trace intervention. v0.1 measures whether the LLM, given the overlay, answers more correctly. It does not test whether the LLM, given the overlay, *acts* differently in a live session.
- No next-action prediction. The task is meta-questions about operational state (§4), not "what should the assistant do next?"
- No multi-turn extension. Each question is evaluated at a single turn T; the LLM produces one answer; no follow-up turns.

### 3.4 No answer_guidance field

Mirrors Stack-Grounded §3.5 exactly. The belief overlay MUST NOT contain `answer_guidance`, `prompt_hint`, `caution_note`, or any field shaped to be read by the LLM as direction. Caution, contradiction handling, and qualifying language must be inferred from warrant fields alone.

---

## 4. Question set

### 4.1 Size

- **Minimum:** 50 questions
- **Target:** 75 questions
- **Ideal:** 100 questions

Each question is associated with a specific session and a specific turn T within that session. The (session_id, turn_idx) pair determines which log slice and which belief snapshot the LLM sees.

### 4.2 Categories

Five categories, balanced 1/5 each at the target of 75:

| Category | Question shape |
|---|---|
| validation_check | "As of turn T, has validation actually completed?" |
| repeated_failure | "Is the current failure the same kind as a prior failure in this session?" |
| approval_status | "Is the assistant currently authorized to proceed with [action]?" |
| completion_check | "Has the assistant accurately claimed completion, or is something still pending?" |
| readiness_check | "Should the assistant proceed, pause, or ask for clarification at this point?" |

Each category maps to one or more of the five deterministic metrics:

| Category | Primary metric |
|---|---|
| validation_check | stale_validation_assumption |
| repeated_failure | repeated_failure_loop |
| approval_status | premature_action |
| completion_check | false_completion_claim |
| readiness_check | missing_pause |

### 4.3 Question shape

```json
{
  "question_id":           "q001_validation_check_S###_T###",
  "session_id":            "...",
  "turn_idx":              integer,
  "category":              "validation_check" | ...,
  "question":              "As of turn T, has validation actually completed?",
  "expected_failure_mode": "stale_assumption" | "missed_loop" | "premature" | "false_completion" | "missing_pause" | null,
  "ground_truth_resolution": {                  // derived from log-forward, NOT shown to LLM
    "type":   "deterministic" | "judge_assisted",
    "answer": "yes" | "no" | "uncertain",
    "derivation": "...",
    "supporting_turns": [int, int]
  }
}
```

The `ground_truth_resolution` block is the audit record for how the metric will be scored. For deterministic metrics it cites specific log-forward turns; for judge-assisted it stays empty until calibration.

### 4.4 Construction discipline (anti-curation) — LOCKED

Same discipline as Stack-Grounded §4.4, adapted to the operational substrate:

- Candidate questions generated/selected from the **raw reasoning ledger** (`reasoning_ledger.jsonl` rows for sessions in `phase2_sample.json`), blind to `phase2_belief_timelines.jsonl` AND to the operational belief substrate `operational_beliefs.jsonl` (once that is derived).
- Stratified by category, session, and turn-position bucket per §4.5.
- Hand-curation is encoded in deterministic selection rules (the "hand-curation" lives in the script's selection logic, not in 75 individual picks).
- Frozen before any answer generation.

The construction script (TBD §5.4, implementation) MUST log every input file it opens. Opening `operational_beliefs.jsonl` during construction invalidates the run.

### 4.5 Sampling — LOCKED

**§4.5.1 — Per-session cap.** No session contributes more than **3** questions across the locked set. With 75 target questions and 164 eligible sessions, expected coverage is ~50 sessions minimum, with ≤3 questions each. Hitting the cap is allowed; bypassing it is not.

**§4.5.2 — Turn-position balance.** For each session that contributes questions, target turns are drawn from three buckets:

| Bucket | Definition | Target share | Rationale |
|---|---|---|---|
| Early | turn position 0–25% of session length | ≤ 25% of questions | Limit: too early to support most operational states (validation_pending, fix_attempted typically born mid-session) |
| **Middle** | **25–75%** | **≥ 50%** (prioritized) | **Most operational state is in flight here; richest test surface** |
| Late | 75–100% | 15–35% | Necessary to test completion / readiness states that only mature toward end-of-session |

A question cannot be sampled at a turn earlier than the first turn at which its category's target operational belief could plausibly be active. For example, a `validation_check` question cannot be asked at turn 5 if no `fix_attempted` belief has been born by turn 5. The construction script enforces this with a per-category minimum turn rule derived from the belief detection logic in §2.3.

**§4.5.3 — Negative-example requirement (locked).** Each category MUST include **at least 3 negative-oracle questions** (questions where the ground-truth answer is "no failure mode present" — e.g., for `validation_check`, a question where validation actually has happened by the target turn). Without this, the experiment becomes "can the overlay help when failure is present?" — a much weaker claim than "can the overlay help under realistic operational state?"

Target negative-positive balance per category: **5 positive / 5 mixed-or-ambiguous / 5 negative oracle**, with hard minimum of 3 negatives per category. Negative-oracle identification depends on the programmatic scorer (§6.3.1) being available before construction; if scorer is not ready, construction is blocked.

### 4.6 Sampling diagnostic — REQUIRED ARTIFACT

Before the question set is locked, the construction script MUST emit a sampling-diagnostic JSON capturing:

- **sessions_represented**: count + list of session_ids actually contributing questions
- **sessions_eligible**: count of sessions in `phase2_sample.json`
- **excluded_sessions**: list of (session_id, exclusion_reason) for any session in the eligible pool not contributing any question; valid reasons include `too_short` (fewer than K+min_turn turns), `no_qualifying_turn` (no turn where any category's minimum-turn condition is met), `cap_filled` (sampler stopped picking once 75 questions were assembled)
- **category_counts**: 15 per category target; deviation > 0 invalidates the lock
- **per_session_max**: max questions assigned to any one session (must be ≤ 3)
- **turn_position_distribution**: count per bucket per category
- **per_category_balance_buckets**: distribution across length / domain / incident-presence buckets from `phase2_sample.json`
- **positive_negative_oracle_balance_per_metric**: count of questions where ground truth is "failure present" vs "failure absent" vs "ambiguous/judge-required"; minimum 3 negative per category enforced
- **construction_inputs_opened**: literal list of every file the construction script read; must NOT include `operational_beliefs.jsonl` or `phase2_belief_timelines.jsonl`
- **seed**: locked random seed for any sampling-with-randomness step (recommend `20260601`)

The diagnostic is committed alongside `questions.jsonl` and is part of the locked artifact set. A construction run that does not produce a passing diagnostic does not produce a locked question set.

---

## 5. Validation protocol

### 5.1 Identical-prompt constraint

Mirrors Stack-Grounded §5.1. System A and System B receive **identical** system prompts and user prompts. Only the grounding payload differs. The system prompt does not instruct the LLM about caution, hedging, citation style, or decline behavior.

```
[system prompt — locked, minimal]

CONTEXT:
{grounding_payload}      <-- A: last-K turns
                             B: last-K turns + operational belief overlay

QUESTION:
{question}               <-- meta-question about operational state at turn T
```

### 5.2 Architectural belief-cutoff enforcement

For each question with target turn T:

- System A's raw-log context is filtered to turn ≤ T BEFORE the LLM sees it.
- System B's belief overlay is filtered to beliefs whose `turn_last_updated ≤ T` AND whose `warrant_evidence_turns` and `revision_trail` entries are all ≤ T BEFORE rendering.
- Neither system can see post-T turns of the session.

Architectural enforcement, not post-hoc labeling. Any post-T reference indicates a substrate construction bug, not a measurement edge case.

### 5.3 Token budget

**TBD §5.3.1 — Token budget.** Same locked equal budget for both systems' grounding payloads. Stack-Grounded used 6000 tokens. Operational may need more (long tool outputs) or less (sparser context). Lock a value.

### 5.4 Locked engineering parameters

**TBD §5.4.1 through §5.4.6** — to be locked at first-run time:

- Generation model + version
- Temperature, seed
- Max output tokens
- Token budget
- Judge model + version + prompt (deterministic and preference)
- Belief-overlay rendering function (lock the exact format before run)

---

## 6. Deterministic measurement track

### 6.1 Primary metric and aggregation

**Aggregate operational error rate** across the five metrics:

```
op_error_rate = sum(YES across all 5 metrics) / sum(applicable across all 5 metrics)
```

where `applicable = YES + NO` for each metric (NA excluded from the denominator).

System B must produce a lower aggregate operational error rate than System A for the primary hypothesis to be supported.

**Per-metric error rate** (reported alongside aggregate, never collapsed into it):

```
metric_rate(m) = YES_m / applicable_m
```

**No averaging across metrics.** Aggregate is a sum-over-metrics, not a mean-of-rates. This means metrics with more applicable cases contribute more to the aggregate — by design. Per-metric rates are reported separately precisely so high-volume metrics cannot hide per-metric failures.

### 6.2 Scoring-rule lock — per metric

Each metric specifies seven fields: (1) applicability condition, (2) YES condition, (3) NO condition, (4) NA condition, (5) required evidence fields / log events, (6) scoring path (programmatic / judge-assisted), (7) normalization denominator.

All five metrics share a common pattern: a **programmatic ground-truth oracle** (derivable from the log forward of turn T plus the belief substrate) combined with an **answer classification** (does the answer commit the failure mode?). The answer classification is the part that requires a judge for soft cases; the ground-truth side is fully programmatic.

#### 6.2.1 — `stale_validation_assumption`

| Field | Rule |
|---|---|
| **Applicability** | `question.category == "validation_check"`. Question targets a turn T at which a `fix_attempted` belief is active (i.e., there is something to be validated). |
| **YES** | Answer makes a positive validation claim (asserts validation has happened, tests pass, fix is verified, or equivalent) AND log-forward shows **no successful validation tool_result** between the most recent `fix_attempted.turn_first_seen` and T+VALIDATION_HORIZON. |
| **NO** | (a) Answer declines or correctly states validation has not been observed; OR (b) Answer makes a positive validation claim AND log-forward shows a successful validation tool_result in the applicable window. |
| **NA** | (a) No `fix_attempted` belief active at T (nothing to validate); OR (b) Log-forward ends before VALIDATION_HORIZON elapses (ground truth indeterminate). |
| **Required evidence** | (i) `fix_attempted.turn_first_seen` from `operational_beliefs.jsonl`; (ii) all `tool_uses` and `tool_results` between fix_attempted and T+VALIDATION_HORIZON from `reasoning_ledger.jsonl`; (iii) validation-tool whitelist (test runners, type checkers, build tools, linters) — locked in `score_operational_label.py` |
| **Scoring path** | Hybrid. Ground truth (did validation actually happen) is **programmatic**. Answer classification (does the answer claim validation happened) is **judge-assisted**. |
| **Normalization denominator** | applicable_stale_validation = (YES + NO). NA contributes 0 to numerator and 0 to denominator. |

VALIDATION_HORIZON parameter: locked at first-run time in §5.4. Candidate: 20 turns from T, or session end, whichever comes first.

#### 6.2.2 — `repeated_failure_loop`

Signature-turn discipline (locked above, preserved verbatim):

> The failure signature is extracted from the **invoking assistant turn** (the turn that contains the tool_use block) joined with **its associated tool_result turn** (the next turn in the ledger where the tool returned). The user-role turn that follows the failure (often a user re-prompt or comment) is NOT the signature source. Signature = `(tool_name, normalized_arguments, normalized_error_message)`.

| Field | Rule |
|---|---|
| **Applicability** | `question.category == "repeated_failure"`. Question targets a turn T at which at least one failed `(tool_use → tool_result)` pair exists within the K-turn lookback. |
| **YES** | Ground truth: the signature at T recurs ≥3 times within the last K=20 turns (per locked window). AND answer does NOT flag the recurrence (does not call it a loop, repeat, same-error pattern, or equivalent). |
| **NO** | (a) Ground truth = signature recurs ≥3 times AND answer correctly flags the loop; OR (b) Ground truth = no recurrence AND answer correctly says no loop / first-time failure. |
| **NA** | Signature extraction fails: no clean `(assistant tool_use turn, tool_result turn)` pair within K, OR all tool_results in the window are non-errors (`is_error=false` everywhere). |
| **Required evidence** | (i) For each tool_result with `is_error=true` in `[T-K+1, T]`, the *invoking assistant turn* identified via `tool_use_id` join; (ii) `(tool_name, normalized_arguments, normalized_error_message)` triple per signature; (iii) recurrence count across the window. |
| **Scoring path** | Hybrid. Signature recurrence count is **fully programmatic**. Answer classification (does the answer flag the loop) is **judge-assisted**. |
| **Normalization denominator** | applicable_repeated_failure = (YES + NO). |

**Normalization rules for signature components** (locked here; implementation in `score_operational_label.py`):

- `tool_name`: lowercase, strip whitespace
- `normalized_arguments`: drop volatile keys (`timestamp`, `request_id`, `uuid`, `run_id`); for file paths, strip absolute path prefix and keep the basename + last 2 directory components; for command strings, strip leading/trailing whitespace and collapse internal whitespace runs to single space
- `normalized_error_message`: lowercase, strip stack-trace line numbers and file paths (regex: `:\d+:` → `:LINE:`, `(?:/\w+)+/` → `<PATH>/`), strip timestamps (ISO-8601 regex → `<TS>`), collapse whitespace, then truncate to first 200 chars

Recurrence is **exact-match equality** on the normalized triple. Approximate or embedding-based matching is explicitly excluded from v0.1.

#### 6.2.3 — `premature_action`

| Field | Rule |
|---|---|
| **Applicability** | `question.category == "approval_status"`. Question targets a turn T at which a candidate action (commit / push / run / publish / send / merge / deploy) has been proposed by the assistant in the last K turns. |
| **YES** | Ground truth: at T, **at least one** of `user_approval_pending`, `action_blocked`, `validation_pending`, `pipeline_failed`, or `pipeline_running` is active in the belief substrate. AND answer recommends proceeding with the action (or asserts the assistant should/can proceed). |
| **NO** | (a) Ground truth = blocker active AND answer correctly identifies the block (recommends waiting / requesting approval / completing prerequisite); OR (b) Ground truth = no blocker active AND answer correctly recommends proceed. |
| **NA** | No candidate action has been proposed in the K-turn lookback (the question is not actually about whether to proceed with anything specific). |
| **Required evidence** | (i) Active belief snapshot at T from `operational_beliefs.jsonl` (cutoff-filtered); (ii) the assistant turn(s) in the lookback that proposed an action (action-verb pattern match per §2.3 detection rules for `action_ready` / `action_blocked`); (iii) the answer text. |
| **Scoring path** | Hybrid. Blocker-presence at T is **fully programmatic**. Answer classification (does the answer recommend proceeding) is **judge-assisted** but should rarely be ambiguous — answers that recommend an action tend to do so explicitly. |
| **Normalization denominator** | applicable_premature_action = (YES + NO). |

#### 6.2.4 — `false_completion_claim`

| Field | Rule |
|---|---|
| **Applicability** | `question.category == "completion_check"`. Question targets a turn T at which the user (or context) has asked or implied a question about whether something is complete. |
| **YES** | Ground truth: at T, at least one of `validation_pending`, `user_approval_pending`, `pipeline_running`, `fix_attempted` (without subsequent `validation_complete`), or `action_blocked` is active in the belief substrate. AND answer asserts the work is complete / done / finished / ready (or equivalent strong completion claim). |
| **NO** | (a) Ground truth = pending state active AND answer correctly identifies what's still pending; OR (b) Ground truth = no pending state AND answer correctly asserts completion. |
| **NA** | No reasonable "completion candidate" can be identified — the session has no active operational state to evaluate as complete-or-not (e.g., the assistant is in pure-discussion mode with no actions in flight). |
| **Required evidence** | (i) Active belief snapshot at T from `operational_beliefs.jsonl`; (ii) the answer text. |
| **Scoring path** | Hybrid. Pending-state at T is **fully programmatic**. Answer classification (does the answer assert completion) is **judge-assisted** because completion claims come in many surface forms ("done," "ready," "all set," "this should work," etc.). |
| **Normalization denominator** | applicable_false_completion = (YES + NO). |

#### 6.2.5 — `missing_pause`

| Field | Rule |
|---|---|
| **Applicability** | `question.category == "readiness_check"`. Question explicitly asks whether the assistant should proceed, pause, or ask for clarification at turn T. |
| **YES** | Ground truth = "should pause" (defined below). AND answer recommends proceeding or acting (does not recommend pause / decline / clarification). |
| **NO** | (a) Ground truth = should pause AND answer correctly recommends pause / decline / clarification; OR (b) Ground truth = should proceed AND answer correctly recommends proceeding. |
| **NA** | Ground truth is genuinely indeterminate (no clear "should pause" signal AND no clear "should proceed" signal from the belief state). |
| **Required evidence** | (i) Active belief snapshot at T (especially count of pending beliefs, presence of `failure_signature_active`, presence of `contradicted` lifecycle states); (ii) the answer text. |
| **Scoring path** | Hybrid. "Should pause" ground truth is **programmatic** per the rule below. Answer classification (does the answer recommend pause) is **judge-assisted**. |
| **Normalization denominator** | applicable_missing_pause = (YES + NO). |

**"Should pause" ground-truth rule** (locked):

Ground truth = "should pause" iff at T, **any of the following** hold:

1. `failure_signature_active` belief is active
2. ≥2 distinct pending-state beliefs are simultaneously active (e.g., `validation_pending` AND `user_approval_pending`)
3. A belief in `lifecycle_state=contradicted` exists within the K-turn lookback
4. `action_blocked` is active AND the question proposes an action

Otherwise, ground truth = "should proceed." If neither rule fires cleanly, label is NA.

### 6.3 Labeling protocol

#### 6.3.1 — Programmatic scoring

A deterministic scorer (`score_operational_label.py`) computes, per question:

- **For each metric:** the programmatic ground-truth state (signature recurrence count, validation observed yes/no, active belief snapshot at T, etc.). This produces a structured `ground_truth` record per (question, metric).
- Metric labels with no answer-classification component (rare; in v0.1 all five metrics have at least some judge-assisted component) would emit YES/NO/NA directly.

The scorer's output is the **labeling oracle** for the judge — it provides the ground-truth side so the judge only has to decide whether the answer commits the failure mode.

`score_operational_label.py` is locked before run; its normalization rules per §6.2 are the spec.

#### 6.3.2 — Judge-assisted answer classification

A locked judge (model TBD per §5.4) sees, per (question, system, answer) triple:

- The question and its category
- The session context up to turn T (System A's payload)
- The belief overlay if scoring System B (otherwise omitted to avoid contamination)
- The answer text
- The programmatic `ground_truth` block (the oracle from §6.3.1)

The judge emits, per metric, the same structured JSON schema as Stack-Grounded's deterministic labeling step (label / answer_quote / context_evidence / rationale / confidence). Required content:

- `label`: one of `YES` / `NO` / `NA`
- `answer_quote`: **verbatim** snippet from the answer that triggered the label (empty if `NO`/`NA`)
- `context_evidence`: **verbatim** snippet from the log / belief overlay / ground-truth block that supports the label
- `rationale`: 1–2 sentences explaining the call
- `confidence`: 0.0–1.0

**Judge prompt requirements** (locked here; full prompt text locked at first-run):

1. The judge MUST distinguish ground-truth state (from the oracle block) from answer-classification (from the answer text). Conflating the two invalidates the label.
2. The judge MUST NOT use the system identity (A or B) as a label criterion. System identity is shown for tracking only.
3. The judge MUST produce verbatim quotes, not paraphrases. A label with an empty or paraphrased quote where the rule requires a quote is treated as an incomplete label and re-attempted.
4. The judge is conservative on YES: requires concrete textual evidence in the quote field.
5. A clean decline ("the context does not support an answer") is `NO` on every metric by default.

Judge model + version + final prompt text are locked at first-run alongside §5.4.

#### 6.3.3 — Disagreement handling

If the programmatic scorer's `ground_truth` block disagrees with the judge's `label` (e.g., scorer says "validation did happen in log-forward" but judge labels YES on stale_validation_assumption), the scorer's ground truth wins — the judge is the answer-classifier, not the oracle. The disagreement is logged as `judge_oracle_conflict` and the per-record audit preserves both for review.

### 6.4 Reporting per metric

For each of the five metrics, report:

- System A rate (`YES_A / applicable_A`), System B rate (`YES_B / applicable_B`), delta with sign
- NA count per system (transparency — high NA is itself a signal)
- Per-category breakdown (each metric's primary category should dominate applicability; cross-category applicability would be a v0.2 candidate)
- Example pairs where A and B disagree (the diagnostic value is in the disagreement)
- For judge-assisted components: confidence distribution (mean / range) and rate of `judge_oracle_conflict` events

**Aggregate reporting** (top-line):

- `aggregate_op_error_rate_A = sum(YES_A) / sum(applicable_A)` across all 5 metrics
- `aggregate_op_error_rate_B = sum(YES_B) / sum(applicable_B)` across all 5 metrics
- Per-metric rates always shown alongside aggregate — never just the headline.

---

## 7. Preference measurement track

### 7.1 Axes (two, narrower than Stack-Grounded's three)

- **traceability** — does the answer cite specific operational state (turn numbers, belief IDs, tool outputs)?
- **appropriate_caution** — does the answer pause / decline / qualify when the state is unresolved?

`sensemaking_usefulness` is dropped for operational because operational state is binary enough that "useful" collapses into "correct," which deterministic measures.

### 7.2 Judging protocol

Mirrors Stack-Grounded §7. Blind to context. Position-randomized. Locked prompt. Same gpt-4.1 preference judge as Stack-Grounded for cross-experiment comparability.

### 7.3 Tie and uncertain handling (locked)

Same as Stack-Grounded §7.3: TIE is its own column; rates computed as wins/total; no auto-resolution.

### 7.4 Aggregation method (locked)

Same as Stack-Grounded §7.4.

---

## 8. What v0.1 does NOT claim

- v0.1 does NOT claim Belief Stack "beats" raw-log RAG in general. It tests one corpus, one question set, one operational-belief schema.
- v0.1 does NOT claim runtime improvement for any deployed assistant. The substrate is pre-computed; live extraction is out of scope.
- v0.1 does NOT claim generalization beyond TKOS Claude-session logs. Other assistant traces (Cursor, ChatGPT, custom agents) are future work.
- v0.1 does NOT pre-commit to a direction. A negative result (B doesn't beat A on aggregate operational error) is a primary finding, not a failure.
- v0.1 does NOT measure intervention effectiveness. The diagnostic substrate is tested; what an assistant *does* with it is a separate later experiment.

---

## 9. Reporting structure

The v0.1 report MUST contain, in this order:

1. **Corpus summary** — sessions sampled, belief substrate stats, question set composition
2. **Deterministic results** — aggregate operational error rate, per-metric rates, per-category breakdown
3. **Preference results** — two axes, win/loss/tie per axis, per-category
4. **Disagreement analysis** — where deterministic and preference results diverge; pair-level traces for instructive failures
5. **Qualitative traces** — 5-10 (session, turn) pairs showing System A and System B side-by-side
6. **Limits** — corpus scope, judge validation, single-LLM caveats, known confounds

---

## 10. Versioning policy

v0.1 is locked once and run once. Mid-run edits invalidate the run. v0.2 is a new pre-registration with an explicit changelog.

---

## 11. Deliverables

The locked deliverable set:

| Artifact | Path |
|---|---|
| Question set | `operational_belief_v1/questions.jsonl` |
| Chunk-side context (raw log) | `operational_belief_v1/data/contexts_a.jsonl` |
| Belief-overlay context | `operational_belief_v1/data/contexts_b.jsonl` |
| Belief substrate (derived from TKOS) | `operational_belief_v1/data/operational_beliefs.jsonl` |
| Answers (per system) | `operational_belief_v1/data/answers_a.jsonl`, `answers_b.jsonl` |
| Deterministic labels | `operational_belief_v1/data/deterministic_labels.jsonl` |
| Preference judgments | `operational_belief_v1/data/preference_judgments.jsonl` |
| Audit files | per-stage `*_audit.json` |
| Notes documents | one per stage, paralleling Stack-Grounded |
| Final report | `operational_belief_v1/OPERATIONAL_BELIEF_REPORT_v0.1.md` |

Scripts (paralleling Stack-Grounded):

| Script | Purpose |
|---|---|
| `build_operational_belief_substrate.py` | Derive `operational_beliefs.jsonl` from TKOS phase2 artifacts |
| `build_question_candidates.py` | Stratified candidates from the reasoning ledger |
| `curate_question_set.py` | Deterministic curation to the locked set |
| `build_log_context_a.py` | Raw-log context per question (System A) |
| `build_belief_overlay_context_b.py` | Raw-log + belief overlay per question (System B) |
| `generate_answers.py` | Identical-prompt generation for A and B |
| `score_operational_label.py` | Deterministic + judge-assisted scoring of the 5 metrics |
| `judge_preference.py` | Pairwise preference judging on the two axes |

---

## 12. Audit trail

| Field | Value |
|---|---|
| Pre-registration version | v0.1 |
| Drafted | 2026-06-01 |
| Locked | _(pending — must complete all TBDs first)_ |
| Author | Susan Stranburg |
| Sibling experiment | [STACK_GROUNDED_PRE_REGISTRATION_v0.1.md](../stack_grounded_v1/STACK_GROUNDED_PRE_REGISTRATION_v0.1.md) |
| Companion artifacts (TKOS upstream) | [tkos_log_replay/PHASE2_REPORT_v0_2.md](../tkos_log_replay/PHASE2_REPORT_v0_2.md), [tkos_log_replay/PHASE2_LOOP_INSPECTION_v0_2.md](../tkos_log_replay/PHASE2_LOOP_INSPECTION_v0_2.md) |
| Substrate sources | `tkos_log_replay/data/reasoning_ledger.jsonl`, `phase2_belief_timelines.jsonl`, `phase2_intervention_verdicts.jsonl` |
| Substrate NOT read at question-construction time | `phase2_belief_timelines.jsonl` (per anti-curation §4.4) |

---

## 13. Public framing (locked)

> **TopicSpace Research is developing Belief Stack, an architectural pattern for building belief-state knowledge sources for LLM systems — starting with the operational beliefs long-running assistants need to track, revise, and retire over time.**

If the deterministic hypothesis holds (System B reduces aggregate operational error vs System A):

> Belief-state grounding measurably reduces stale-state errors in long-running LLM assistant workflows compared with raw-log context alone. The architectural claim — that maintained operational beliefs carry information the recent log cannot directly carry — is supported on this corpus.

If the preference hypothesis holds:

> Blind pairwise judging preferred belief-overlay-grounded answers on traceability and appropriate caution. The architectural claim that operational beliefs improve perceived quality of state-tracking answers is supported on this corpus.

If both hold:

> Operational belief-state grounding is both more accurate and preferred on this corpus. The first application wedge for Belief Stack is operational state assistance to long-running LLM workflows.

If results diverge (deterministic wins, preference flat — or the reverse):

> The deterministic / preference gap is the primary finding. [Articulation of what the gap means architecturally.]

If neither holds:

> Operational belief-state grounding did not improve LLM workflow-state answers on this corpus under the v0.1 rules. The architectural claim needs revision before further investment, or the specific operationalization in v0.1 (belief schema, rendering, judge protocol) needs to be reconsidered.

All five outcomes are honest, publishable, and informative. None require the experiment to "win" to be useful.

The closing thesis:

> The recent log shows *what happened*. An operational belief-state knowledge source returns *what the system currently believes is still true* and *what has been retired or contradicted since*. The experiment tests whether that difference helps the LLM stop forgetting time.

---

## Summary of TBDs and lock sequence

### Lock sequence (recommended order)

1. **Belief typology** (§2.3) — **locked.** 11 types; detection rules locked against existing TKOS extraction for 8 types + 4 NEW types defined; composite belief discipline locked; coverage exclusions explicit.
2. **K (recent-turn window) + tool-output policy** (§3.1.1, §3.1.2) — **locked.** K=20, tool cap=500. Empirically grounded against diagnostic_k_cap_sweep.py (345 sample points). Caveat about cap=500 being non-binding on current substrate documented in §3.1.2.
3. **Scoring rules** (§6.2, §6.3) — **locked.** Per-metric applicability / YES / NO / NA conditions, required evidence, scoring path, and normalization denominators specified for all 5 metrics (§6.2.1–§6.2.5). Signature normalization rules locked. Judge prompt requirements locked (judge model + final prompt text deferred to §5.4 first-run lock). Aggregate = `sum(YES)/sum(applicable)`; per-metric rates always reported alongside.
4. **Session scope and sampling** (§2.1.1, §2.4.1, §4.4, §4.5, §4.6) — **locked.** Eligible corpus = 164 Phase 2 sessions; balanced subset (not incident-only); 75 target / 15 per category / max 3 per session; turn-position buckets with middle prioritized; negative-oracle minimum 3 per category; sampling-diagnostic artifact required before lock.
5. **Construction script and engineering parameters** (§5.3.1, §5.4) — locked last, right before run. The construction script must produce the §4.6 sampling diagnostic to pass.

### Current TBD state

| # | Section | TBD | State |
|---|---|---|---|
| 1 | §2.1.1 | Session scope | **locked** (balanced subset of 164 Phase 2 sessions; NOT incident-only) |
| 2 | §2.2.1 | Field derivation rules (revision_trail, current_authority) | open |
| 3 | §2.3 | Operational belief typology + detection rules | **locked** (11 types; 8 reuse TKOS extraction; 4 NEW with locked birth/retire conditions; composite discipline locked) |
| 4 | §2.4.1 | Window (date range) | **locked** (full Phase 2 sample window; no extra date filtering) |
| 5 | §3.1.1 | K (recent-turn window) | **locked: K=20** (diagnostic-grounded) |
| 6 | §3.1.2 | Tool output rendering / truncation policy | **locked: verbatim + 500-token per-tool cap** (non-binding on current substrate; design-binding for future) |
| 7 | §4.4 | Anti-curation discipline | **locked** (ledger-only construction; `operational_beliefs.jsonl` MUST NOT be opened) |
| 8 | §4.5.1 | Per-session cap | **locked: 3** |
| 9 | §4.5.2 | Turn-position balance | **locked** (≤25% early / ≥50% middle / 15–35% late; per-category minimum-turn rule from §2.3 detection) |
| 9b | §4.5.3 | Negative-oracle minimum | **locked: ≥3 negatives per category** (5+/5±/5− target with 3-negative floor) |
| 9c | §4.6 | Sampling diagnostic artifact | **locked** (required output of construction script; specifies 10 audit fields) |
| 10 | §5.3.1 | Token budget for both systems | open |
| 11 | §5.4 (6 sub-items) | Generation model, temperature, seed, max-out, judge model, rendering function | open |
| 12 | §6.2 | Per-metric scoring rules (applicability, YES/NO/NA, evidence, denominator) | **locked** (§6.2.1–§6.2.5) |
| 13 | §6.3 | Labeling protocol (programmatic + judge-assisted; judge prompt requirements) | **locked** (judge model + final prompt text deferred to §5.4) |
| 14 | §5.4 | `score_operational_label.py` implementation against locked rules | open (depends on construction step) |

None of these are blockers individually; together they're what separates a draft from a runnable pre-registration. **Do not lock the experiment as a whole until all TBDs close.**
