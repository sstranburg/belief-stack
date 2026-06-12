# Preference Judging Notes — Operational Belief v0.1

_Locked as part of the preference-judging step. Final report is deferred per the locked rhythm._

This document records the locked preference-judge protocol and the raw per-axis results from 73 paired comparisons. **No final report yet** — deterministic and preference are reported separately and not averaged.

---

## 1. What this step did

For each of the 73 paired questions (where both A and B have answers), presented the two answers in randomized order to a locked preference judge. Judge returned a winner (X / Y / TIE) plus rationale + confidence for each of 2 pre-registered axes:

- `traceability`
- `appropriate_caution`

(Note: pre-reg §7.1 dropped the third Stack-Grounded axis `sensemaking_usefulness` for operational because operational state is binary enough that "useful" collapses into "correct," which the deterministic track measures.)

---

## 2. Locked v0.1 preference-judge parameters

| Parameter | Value | Notes |
|---|---|---|
| Judge model | `gpt-4.1-2025-04-14` | Three-way family separation: generator gpt-4o, det judge gpt-5-mini, pref judge gpt-4.1. Same lock as Stack-Grounded v0.1 for cross-experiment comparability. |
| Temperature | 0.0 | |
| top_p | 1.0 | |
| Seed | 20260601 | Matches operational construction seed |
| Shuffle seed | 20260601 | Per-pair position randomization deterministic from `f"{SHUFFLE_SEED}:{qid}"` |
| max_tokens | 1500 | |
| Response format | `json_schema` strict | Locked 2 axes × 3 fields (winner / rationale / confidence) |
| Context visibility | **HIDDEN** | Judge sees only question + cutoff + ticker + Answer X + Answer Y |
| System identity visibility | **HIDDEN** | "Answer X" / "Answer Y" only; X→A or X→B mapping recorded out-of-band |
| Retry policy | exponential backoff (4s → 256s) + jitter, max 6 attempts | RateLimitError, APITimeoutError, 5xx |

**Locked judge prompt** (hash recorded in audit): the script's `JUDGE_SYSTEM_PROMPT` constant. Contains the 2 axis definitions in operational-workflow terms.

---

## 3. Excluded from preference judging

Per the user's explicit instruction and pre-reg §7 paired-comparison discipline:

- **q047** (`repeated_failure`, session `591632ad`, T=7089) — System B has no answer due to TPM cap (overlay = 32K tokens vs Tier 1 30K limit)
- **q061** (`validation_check`, session `a7ee69be`, T=8453) — same reason (overlay = 44K tokens)

These are generation/feasibility failures, NOT preference losses. They are reported in [ANSWER_GENERATION_NOTES.md §5](ANSWER_GENERATION_NOTES.md) and are excluded from the preference judging set entirely. Paired set = **n=73**.

---

## 4. Run audit

| Metric | Value |
|---|--:|
| Pairs to judge | 73 |
| Pairs complete | **73 / 73** |
| Permanent failures | 0 |
| Distinct `model_resolved` | 1 (`gpt-4.1-2025-04-14`) |

---

## 5. Aggregate per-axis rates (n=73)

| Axis | A wins | B wins | TIE |
|---|---|---|---|
| **traceability** | 23 (32%) | **34 (47%)** | 16 (22%) |
| **appropriate_caution** | 16 (22%) | 12 (16%) | **45 (62%)** |

### Position-bias check

| Slot | Wins across all 146 axis judgments (73 pairs × 2 axes) |
|---|---|
| X (first slot) | 41 (28%) |
| Y (second slot) | 44 (30%) |
| TIE | 61 (42%) |

Position is balanced. No systematic preference for first-or-second-position answer; the per-axis A/B/TIE rates above are not driven by ordering artifacts.

---

## 6. Per-category × per-axis (paired)

### approval_status (n=15)

| Axis | A | B | TIE |
|---|---|---|---|
| traceability | 4 (27%) | 6 (40%) | 5 (33%) |
| appropriate_caution | 5 (33%) | 2 (13%) | 8 (53%) |

### completion_check (n=15)

| Axis | A | B | TIE |
|---|---|---|---|
| traceability | 6 (40%) | 6 (40%) | 3 (20%) |
| appropriate_caution | 1 (7%) | 4 (27%) | 10 (67%) |

### readiness_check (n=15)

| Axis | A | B | TIE |
|---|---|---|---|
| traceability | 5 (33%) | 5 (33%) | 5 (33%) |
| appropriate_caution | 4 (27%) | 1 (7%) | 10 (67%) |

### repeated_failure (n=14)

| Axis | A | B | TIE |
|---|---|---|---|
| traceability | 5 (36%) | 6 (43%) | 3 (21%) |
| appropriate_caution | 2 (14%) | 4 (29%) | 8 (57%) |

### validation_check (n=14)

| Axis | A | B | TIE |
|---|---|---|---|
| traceability | 3 (21%) | **11 (79%)** | 0 (0%) |
| appropriate_caution | 4 (29%) | 1 (7%) | 9 (64%) |

The `validation_check` category produces the most decisive per-category result: traceability B 79% / A 21% / TIE 0%. The belief overlay's explicit `validation_pending` / `validation_complete` / `fix_attempted` belief blocks give the LLM specific traceable anchors that raw log alone doesn't surface.

---

## 7. Example judgments — audit evidence

Per-axis-per-direction examples (up to 4 each) are preserved in `data/preference_audit.json` under `examples_by_axis`. The pool lets any reader audit individual judge calls without re-running.

For each of `{traceability, appropriate_caution}` and each of `{A_wins, B_wins, TIE}`, the audit carries:
- question_id, category
- judge rationale (verbatim, up to 300 chars)
- confidence

---

## 8. Methodological caveats

1. **Single LLM judge**, locked. No inter-judge agreement check. v0.2 candidate: 2-judge protocol.

2. **Blind-to-context design.** The preference judge cannot detect substrate-grounded failures that require seeing the original raw log + overlay. Per pre-reg §7.2 this is by design — the disagreement between deterministic and preference tracks carries information.

3. **n=73, not n=75.** The 2 questions excluded for B-missing answers are documented in §3. A-only solo preference doesn't make sense (preference is pairwise by construction), so no transparency variant is reported here.

4. **High TIE rates on appropriate_caution** (62% overall, 53-67% per category). Both systems decline / qualify on similar question types; the differentiating axis was traceability.

5. **Confidence values are recorded but not used to weight or threshold.** Available in per-judgment records for any auditor.

6. **Cross-experiment comparability**: same judge model lock as Stack-Grounded (gpt-4.1-2025-04-14). Any operational-vs-stack-grounded preference comparison in the eventual v0.1 report cannot be confounded with judge model differences.

---

## 9. What's frozen at this step

- `judge_preference.py` — judge prompt, schema, locked parameters, deterministic shuffle
- `data/preference_judgments.jsonl` — 73 per-pair judgment records
- `data/preference_audit.json` — aggregated rates + position-bias + per-category + example rationales

---

## 10. What's NOT done

- The v0.1 report (synthesizing deterministic + preference per pre-reg §9) is deferred. The artifacts here are inputs to it.

---

## 11. How to reproduce

```bash
cd /Users/sue/Documents/git/storm
source venv/bin/activate
python operational_belief_v1/judge_preference.py
```

Inputs that must already exist:

- `operational_belief_v1/questions.jsonl`
- `operational_belief_v1/data/answers_a.jsonl`, `answers_b.jsonl`
- `.env` with `OPENAI_API_KEY`

The script is idempotent. Re-running skips `question_id`s already complete (all 2 axes judged). The per-pair shuffle is seeded deterministically from `f"{SHUFFLE_SEED}:{question_id}"` so position assignment is reproducible.

---

## 12. Audit trail

| Field | Value |
|---|---|
| Preference-judging version | v0.1 |
| Locked | 2026-06-01 |
| Author | Susan Stranburg |
| Judge script | `judge_preference.py` |
| Companion pre-registration | [OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md](OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md) |
| Companion notes | [OPERATIONAL_BELIEF_SUBSTRATE_NOTES.md](OPERATIONAL_BELIEF_SUBSTRATE_NOTES.md) · [QUESTION_SET_CONSTRUCTION_NOTES.md](QUESTION_SET_CONSTRUCTION_NOTES.md) · [CONTEXT_CONSTRUCTION_NOTES.md](CONTEXT_CONSTRUCTION_NOTES.md) · [ANSWER_GENERATION_NOTES.md](ANSWER_GENERATION_NOTES.md) · [DETERMINISTIC_LABELING_NOTES.md](DETERMINISTIC_LABELING_NOTES.md) |
| Inputs read | questions, answers_a, answers_b |
| Inputs NOT read | any context, any deterministic label, any operational substrate, any final-report artifact |
