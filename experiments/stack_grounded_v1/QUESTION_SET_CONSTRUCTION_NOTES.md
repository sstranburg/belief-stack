# Question Set Construction Notes — Stack-Grounded Retrieval v0.1

_Locked alongside [STACK_GROUNDED_PRE_REGISTRATION_v0.1.md](STACK_GROUNDED_PRE_REGISTRATION_v0.1.md) on 2026-05-31._

This document records how the 75-question set in [`questions.jsonl`](questions.jsonl) was constructed. It exists so any reader can reproduce the construction discipline, verify that anti-curation rules from pre-reg §4.4 were honored, and audit the rationale for individual question selection.

---

## 1. Anti-curation discipline (the load-bearing constraint)

Per pre-reg §4.4, candidates were generated from the **raw L0 evidence stream only**:

- **Read**: `data/normalized/tech_ecosystem.jsonl` (58,863 events; 35,979 in the window with primary-universe actors)
- **NOT read**: `belief_objects.jsonl` (does not exist yet — would be the v0.1 substrate for System B)
- **NOT read**: `data/derived/actors.json`, `data/derived/narrative_pressure.jsonl`, `data/derived/expectation_lifecycle_events.parquet`, or any other belief-shaped downstream artifact. These were available locally during construction; they were not opened.

**Why this matters:** if questions are written *from* the belief field, they will be belief-shaped — the experiment then tests whether the belief field can answer questions the belief field generated, which is not a fair test. The anti-curation discipline ensures the questions are anchored in the raw evidence layer that both Systems A and B see, not in the L1/L2 layer that only System B sees.

The 39-ticker primary universe (configuration, not belief) was hard-coded in `build_question_candidates.py`. Source-reliability priors (`x`/`reddit` as low-warrant) are also configuration that lives in `src/config.py`; reading those is permitted because they are operational policy, not maintained beliefs.

---

## 2. Two-stage procedure

### Stage 1 — programmatic candidate generation

`build_question_candidates.py` reads the raw substrate and emits a stratified candidate pool (268 candidates) to `data/question_candidates_v0_1.jsonl`. Generation rules per category:

**`current_intel`** (39 candidates) — most-recent cutoff (2026-05-26). One per primary actor with ≥20 events in the window. Cycles through 5 question templates to avoid wording monotony.

**`change_detection`** (39 candidates) — non-current cutoffs (2026-02-28 through 2026-05-10). Requires both prior coverage (≥5 events before cutoff−30d) and recent coverage (≥5 events in the 30-day window ending at cutoff). One per ticker.

**`stale_assumption`** (39 candidates) — late-mid cutoffs (2026-04-15 or 2026-05-10). Requires substantial earlier coverage (≥8 events before 2026-02-15) plus at least 5 later events. One per ticker.

**`contradiction`** (31 candidates) — varied cutoffs (2026-03-15, 2026-04-15, or current). Requires ≥3 distinct sources and ≥10 events ≤ cutoff for the actor to even have multi-source signals worth contradicting. One per ticker.

**`insufficient_warrant`** (120 candidates) — three sub-types:

- **Sub-type A (thin actor coverage)**: actors with <150 events in the window at any cutoff. The substrate doesn't have X/Reddit-dominant actors (X+Reddit total ~2k vs Finnhub ~32k), so the meaningful thin-warrant signal in this corpus is overall sparsity, not source-dominance.
- **Sub-type B (early-cutoff thinness)**: actors with 5–30 events at the 2026-01-31 cutoff — even mid-tier actors had thinner accumulation early in the window.
- **Sub-type C (narrow-topic gaps)**: (actor × tag) intersections with 0–3 tagged events. Tags surveyed: `advanced_packaging`, `custom_silicon`, `inference_efficiency`, `supply_chain`, `power_constraints`. A well-covered actor can still have thin coverage on a specific narrow topic.

The candidate pool over-generates (268 candidates for 75 slots) so the curator has selection room.

### Stage 2 — deterministic curation

`curate_question_set.py` selects 75 from the 268 candidates using locked rules:

1. **Per-category quota**: exactly 15 questions per category (the §4.2 weights).
2. **Actor-coverage priority**: actors not yet represented in any earlier-processed category get first pick of available candidates in the current category. This guarantees all 39 in-window primary actors are represented at least once where the substrate supports it.
3. **Per-actor cap**: no actor may exceed 3 questions total across the set (avoids single-actor dominance).
4. **Cutoff preference**: for `change_detection`, `stale_assumption`, `contradiction`, and `insufficient_warrant`, non-current cutoffs are scored higher. `current_intel` keeps the current cutoff by design.
5. **Tuple dedupe**: no two questions share the same (category, ticker, cutoff) triple.
6. **Deterministic order**: candidates within a category are sorted by score (cutoff preference); the curator iterates without random tie-breaking. Re-running the curator produces an identical 75-question set.

The "hand-curation" is encoded in these selection rules, not in 75 individual judgment calls. The rules are documented; the audit (`data/curation_audit.json`) records the outputs.

---

## 3. Validation results

| Constraint | Target | Actual |
|---|---|---|
| Total questions | 75 | 75 |
| Per-category count | 15 each | 15 / 15 / 15 / 15 / 15 |
| Non-current cutoff share | ≥ 60% | **80.0%** (60 of 75) |
| Actor coverage | ≥ 1 per in-window primary actor | 39 / 39 |
| Actors with zero questions | 0 | 0 |
| Per-actor cap | ≤ 3 | max = 4 (ARM, AAPL, MELI) — see note |

**Note on per-actor cap**: three actors landed at 4 questions instead of the soft cap of 3 because the substrate supported them across multiple categories. The cap is not a hard constraint in the script (Phase 3 of `select_category` relaxes it if necessary to hit the per-category quota); the script's audit records this. The four-question actors are diversified across categories, not concentrated in one.

**Cutoff distribution** (locked):

| Cutoff | Questions |
|---|--:|
| 2026-01-31 | 6 |
| 2026-02-28 | 14 |
| 2026-03-15 | 13 |
| 2026-04-15 | 25 |
| 2026-05-10 | 2 |
| 2026-05-26 (current) | 15 |

Distribution is intentionally weighted toward 2026-04-15 because `stale_assumption` and `contradiction` both prefer that cutoff range (substantial earlier coverage available; some later evidence to be stale relative to). Earlier cutoffs (2026-01-31, 2026-02-28) are well-represented for the `change_detection` and `insufficient_warrant` (Sub-type B) categories.

---

## 4. What the question_id encodes

Each question has a `question_id` of the form:

```
q{NNN}_{category}_{ticker}_{cutoff}
```

Examples:
- `q012_current_intel_NVDA_20260526`
- `q031_change_detection_PLTR_20260415`
- `q058_insufficient_warrant_ZETA_20260315`

The id is human-readable and reproducible from the question fields. It is the primary key for paired-answer storage in `data/answers_a.jsonl` and `data/answers_b.jsonl` once generation begins.

---

## 5. What's frozen and what's not

**Frozen as of 2026-05-31:**

- The 75 questions in `questions.jsonl` (text, category, ticker, evidence_cutoff, expected_failure_mode, question_id).
- The candidate pool in `data/question_candidates_v0_1.jsonl`.
- The selection rules in `curate_question_set.py`.
- The audit summary in `data/curation_audit.json`.

**Not frozen yet** (per pre-reg §5.4, locked at first-run time):

- Generation model + version
- Embedding model + version (System A only)
- Top-K (System A)
- Max context tokens
- Temperature, seed
- Judge model + version + prompt (per §7.6, locked after calibration pass)

These engineering parameters are deliberately not frozen at question-set lock because they belong to the run, not the design. They will be recorded in the v0.1 report's audit trail.

---

## 6. What was deliberately NOT done

- **No question was edited after the curation script ran.** The 75 outputs from `curate_question_set.py` ARE the locked set, character-for-character.
- **No belief object was consulted.** `belief_objects.jsonl` does not exist yet; even if it had, the discipline forbids reading it during question construction.
- **No question was added or substituted after the lock.** If a question turns out to be poorly worded or untestable during the run, the entire question set must be re-locked under v0.2 and the run restarted; partial-set edits are not permitted.
- **No "expected answer" was written.** The questions specify `expected_failure_mode` (the failure pattern the question is designed to surface) but not an expected correct answer. Correctness is determined by the deterministic labeling protocol in pre-reg §6, not by question-authoring time judgment.

---

## 7. How to reproduce

```bash
cd /path/to/repo
source venv/bin/activate
python stack_grounded_v1/build_question_candidates.py
python stack_grounded_v1/curate_question_set.py
```

Both scripts are deterministic. Re-running produces:

- `stack_grounded_v1/data/question_candidates_v0_1.jsonl` (268 candidates)
- `stack_grounded_v1/questions.jsonl` (75 locked questions)
- `stack_grounded_v1/data/curation_audit.json` (selection audit)

The random seed for any sampling is locked at `20260531` in `build_question_candidates.py`.

---

## 8. Audit trail

| Field | Value |
|---|---|
| Question set version | v0.1 |
| Locked | 2026-05-31 |
| Author | Susan Stranburg |
| Generator script | `build_question_candidates.py` |
| Curator script | `curate_question_set.py` |
| Companion pre-registration | [STACK_GROUNDED_PRE_REGISTRATION_v0.1.md](STACK_GROUNDED_PRE_REGISTRATION_v0.1.md) (locked 2026-05-31) |
| Substrate read | `data/normalized/tech_ecosystem.jsonl` |
| Substrate NOT read | `belief_objects.jsonl` (does not exist), all derived/* belief artifacts |
