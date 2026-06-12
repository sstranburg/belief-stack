# Question Set Construction Notes — Operational Belief v0.1

_Locked as part of step 5c of the operational v0.1 lock sequence._

This document records how the 75-question set in `questions.jsonl` was constructed. The anti-curation discipline (§4.4) is the load-bearing constraint: candidate question TEXT was generated blind to the belief substrate; the scorer was consulted only after candidates existed, for applicability + balance.

---

## 1. Anti-curation discipline (the load-bearing constraint)

Per the locked §4.4 of the pre-registration, the two-stage construction enforces a strict separation:

| Stage | Reads | Forbidden |
|---|---|---|
| **Candidate generation** (`build_question_candidates.py`) | `sessions_normalized.jsonl`, `reasoning_ledger.jsonl`, `phase2_sample.json` | `operational_beliefs.jsonl`, `phase2_belief_timelines.jsonl`, anything from the scorer |
| **Curation** (`curate_question_set.py`) | candidate file + scorer (which is allowed to read everything) | direct reading of `operational_beliefs.jsonl` from the curator |

The substantive guardrail: question wording is shaped by the raw ledger only. The oracle classifies AFTER text exists. Reversing this would mean question text is biased by belief metadata — exactly the bias the discipline prevents.

The script logs every input it opens; opening a forbidden file invalidates the run.

---

## 2. Two-stage procedure

### Stage 1 — `build_question_candidates.py` (raw-ledger only)

Reads the 164 Phase 2 sessions from `sessions_normalized.jsonl`. For each session, walks every turn and applies category-specific ledger-level heuristics:

| Category | Candidate heuristic (ledger-only) |
|---|---|
| validation_check | any assistant turn in the last K=20 turns issued an Edit/Write/MultiEdit/NotebookEdit tool_use |
| repeated_failure | this turn has `tool_result.is_error=true` — **scanned every turn** per locked instruction (failure_signature_active is sparse) |
| approval_status | any assistant turn text in the last K turns matches ACTION_PATTERNS regex (commit/push/merge/deploy/publish/ship/send) |
| completion_check | any assistant turn matches completion language ("done", "complete", "ready") OR user message matches completion query |
| readiness_check | any assistant turn in the last K had a tool_use (broad heuristic; scorer's 4-clause rule decides applicability) |

Per-category minimum-turn rules (locked in `MIN_TURN_PER_CATEGORY`) prevent sampling at turns earlier than the relevant operational belief could plausibly be active. `repeated_failure` requires T ≥ K so the signature window is full.

**Question text** is generated from a deterministic 3-template rotation per category (template index = `(T + len(category)) % 3`). Templates reference T only — no belief content, no session-specific labels, no operational-state vocabulary. The text says things like *"As of turn T, is there evidence that the recently-applied change has been tested?"* — substrate-agnostic, ledger-anchored.

**Output**: 195,581 candidates across the 5 categories, written to `data/question_candidates_v0_1.jsonl`. Distribution:

| Category | Candidates |
|---|--:|
| readiness_check | 82,629 |
| validation_check | 52,050 |
| completion_check | 36,899 |
| approval_status | 22,764 |
| repeated_failure | 1,239 |

### Stage 2 — `curate_question_set.py` (scorer consulted; selection rules applied)

For each candidate, the scorer is called to produce `(applicability, oracle_class)`. NA candidates are dropped. The remaining 168,371 applicable candidates are bucketed by `(category, oracle_class, turn_position_bucket, session_id)`.

Selection rules (locked in §4.5):

1. **Per-category quota**: exactly 15 questions per category, 75 total.
2. **Oracle balance**: target 5 positive / 5 negative / 5 mixed per category, with hard floor of ≥3 negatives.
3. **Turn-position balance**: 4 early / 8 middle / 3 late per category (locked §4.5.2).
4. **Per-session cap**: ≤3 questions per session.
5. **Deterministic shuffle**: seeded random (seed=20260601) controls tie-breaking; re-running produces an identical set.

The curator uses a two-pass picker:
- **Pass 1**: hit each oracle class (POSITIVE then NEGATIVE) up to its target, picking from the preferred turn-position bucket first.
- **Pass 2**: fill the remaining "mixed" slots from whichever class has more remaining candidates, still respecting bucket preference.

---

## 3. Validation results

| Constraint | Target | Actual |
|---|---|---|
| Total questions | 75 | **75 ✓** |
| Per-category count | 15 each | **15 / 15 / 15 / 15 / 15 ✓** |
| Per-session max | ≤ 3 | **3 ✓** |
| Turn-position per category | 4 / 8 / 3 (early/middle/late) | **4 / 8 / 3 every category ✓** |
| Hard floor: negatives per category | ≥ 3 | **min 5 (all categories exceed floor) ✓** |
| Sessions represented | ≥ ~50 | **54 / 164 ✓** |

**Per-category oracle balance**:

| Category | Positive | Negative | Early/Mid/Late |
|---|--:|--:|---|
| validation_check | 10 | 5 | 4 / 8 / 3 |
| repeated_failure | 5 | 10 | 4 / 8 / 3 |
| approval_status | 10 | 5 | 4 / 8 / 3 |
| completion_check | 10 | 5 | 4 / 8 / 3 |
| readiness_check | 5 | 10 | 4 / 8 / 3 |

**No deviations from locked targets.** All hard constraints met; the soft 5/5/5 oracle target was overridden by the "fill remaining from larger class" pass-2 rule, but the negative-floor of 3 is exceeded everywhere (minimum 5).

---

## 4. Sparsity behavior — rules NOT loosened

Per the locked discipline (§4.5.3, §6.2.2), no scoring rule was loosened during construction. Two categories had known sparsity concerns from the scorer audit:

### 4.1 `repeated_failure`

The scorer audit (5a) found only 3 positive-oracle candidates in 480 quartile-sampled (session, T) points. The audit predicted that scanning every turn would yield more — that prediction held:

- Quartile-sample positive yield: 3 candidates
- **Every-turn-scan positive yield: 92 candidates** (across 1,239 turns-with-error)
- Selected: 5 positives + 10 negatives (well over both the 5-positive target and the 3-negative floor)

The "scan every turn" instruction was load-bearing here — without it, this category would have failed to hit balance under locked rules.

### 4.2 `approval_status`

The scorer audit reported 26 applicable / 6 negative in the quartile sample. Every-turn scan found:

- Applicable: 22,764 (broad heuristic catches lots of action proposals)
- Positive: 6,384
- **Negative: 1,987** (action proposals with no blockers active)
- Selected: 10 positives + 5 negatives

Plenty of room here. The concern was unfounded once every-turn scanning was used.

### 4.3 What was NOT done

- No relaxation of the §6.2 scoring rules
- No expansion of the ACTION_PATTERNS regex to catch more action proposals
- No relaxation of the signature-recurrence threshold (still ≥3 occurrences per §6.2.2)
- No cross-category counting (a question's metric stays anchored to its category, not opportunistically reassigned)

---

## 5. Sessions excluded and exclusion reasons

- **Eligible sessions** (Phase 2 sample): 164
- **Sessions contributing at least one question**: 54
- **Sessions not represented**: 110

Reasons for non-representation:

- **`lost_to_selection`** (most common): candidates from these sessions existed and were applicable, but the per-category quota / oracle-balance / turn-position constraints preempted them. Specifically the per-session cap of 3 means many sessions never get picked once the 75 slots fill.
- **`no_candidates_generated`**: no turns in the session passed the ledger-level heuristic (e.g., sessions that never issued code-change tools, never proposed actions, etc.). A small subset of the 17 sessions with no TKOS belief timelines fall here.

Both reasons are by-design under the locked selection rules. No session was excluded due to anything ad-hoc.

Full per-session exclusion list with reasons is in `data/question_construction_audit.json` under `excluded_sessions`.

---

## 6. Question record schema (frozen at v0.1)

Each line of `questions.jsonl` is:

```json
{
  "question_id":            "q001_validation_check_32a6ee2f_T15",
  "session_id":             "main::32a6ee2f-...",
  "turn_idx":               15,
  "category":               "validation_check",
  "question":               "As of turn 15 in this session, has the most recent code change been verified by a test or other check?",
  "turn_position_bucket":   "early" | "middle" | "late",
  "session_total_turns":    int,
  "expected_failure_mode":  "stale_validation_assumption" | "repeated_failure_loop" | ...,
  "oracle_class":           "POSITIVE" | "NEGATIVE",
  "oracle_state":           "validation_did_not_happen" | "loop_present" | ...,
  "ground_truth_resolution": {
    "type":                 "programmatic_plus_judge",
    "supporting_turns":     [int, ...],
    "counterevidence_turns": [int, ...],
    "rationale":            "..."
  }
}
```

`expected_failure_mode` and `oracle_class` are **populated** in v0.1 (filled from the scorer's result). They are NOT shown to the LLM at answer-generation time — they live in the question record for audit and for the scorer/judge pipeline to read.

---

## 7. What's frozen and what's not

**Frozen at 5c lock:**

- The 75 questions in `questions.jsonl` (question text, session_id, turn_idx, category, turn_position_bucket, session_total_turns, expected_failure_mode, oracle_class, oracle_state, ground_truth_resolution)
- The candidate pool in `data/question_candidates_v0_1.jsonl`
- The selection rules in `curate_question_set.py`
- The sampling diagnostic in `data/question_construction_audit.json`

**Not frozen yet** (per §5.4, locked at first-run time):

- Generation model + version
- Temperature, seed
- Max output tokens
- Token budget
- Judge model + version + prompt
- Context rendering function

These engineering parameters are deliberately deferred — they belong to the run, not the design.

---

## 8. How to reproduce

```bash
cd /path/to/repo
source venv/bin/activate

# Stage 1 — candidate generation (reads ledger only)
python operational_belief_v1/build_question_candidates.py

# Stage 2 — curation (calls scorer, applies selection rules)
python operational_belief_v1/curate_question_set.py
```

Both scripts are deterministic. The selection seed is `20260601` (in `curate_question_set.py`). Re-running produces an identical 75-question set, modulo the substrate-loader cost.

---

## 9. Audit trail

| Field | Value |
|---|---|
| Construction version | v0.1 |
| Locked | 2026-06-01 |
| Author | Susan Stranburg |
| Generator script | `build_question_candidates.py` |
| Curator script | `curate_question_set.py` |
| Companion pre-registration | [OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md](OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md) |
| Companion notes | [OPERATIONAL_BELIEF_SUBSTRATE_NOTES.md](OPERATIONAL_BELIEF_SUBSTRATE_NOTES.md) (5b) |
| Companion scorer | [score_operational_label.py](score_operational_label.py) (5a) |
| Inputs opened during candidate text generation | `sessions_normalized.jsonl`, `reasoning_ledger.jsonl`, `phase2_sample.json` |
| Inputs opened by scorer (eligibility/balance only, never for text) | `operational_beliefs.jsonl`, `phase2_belief_timelines.jsonl` |
| Inputs NOT opened during text generation (verified by audit) | `operational_beliefs.jsonl`, `phase2_belief_timelines.jsonl`, any scorer output |
