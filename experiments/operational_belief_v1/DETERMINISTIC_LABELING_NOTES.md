# Deterministic Labeling Notes — Operational Belief v0.1

_Locked as part of the deterministic-scoring step. Final report is deferred until preference judging completes._

This document records the locked judge protocol, the run audit, and the raw labels. **No final report yet** — per the locked rhythm, deterministic and preference are reported separately and not averaged.

---

## 1. What this step did

For each (question, system) pair where an answer exists (75 System A + 73 System B = 148 pairs), the script combined the programmatic oracle (from `score_operational_label.py`, the §6.2 ground truth) with a judge-side answer-classification call to produce final YES / NO / NA labels per metric.

The disagreement policy from pre-reg §6.3.3 is enforced: **oracle wins**. If the judge says the answer committed the failure mode but the oracle says the failure mode structurally cannot apply, the final label is NO and the disagreement is logged as `judge_oracle_conflict`.

---

## 2. Locked v0.1 judge parameters

| Parameter | Value | Notes |
|---|---|---|
| Judge model | `gpt-5-mini-2025-08-07` | Same as Stack-Grounded v0.1 judge per pre-reg §6.3 |
| Reasoning effort | `medium` | |
| top_p | `1.0` | |
| Temperature | not settable | gpt-5-mini supports default only |
| Seed | `20260601` | Matches operational construction seed |
| max_completion_tokens | `5000` | Matches Stack-Grounded's locked value |
| Response format | `json_schema` strict | Locked schema for 5 metrics × 4 fields |
| System identity visibility | shown to judge for tracking; explicit do-not-use instruction | |
| Retry policy | exponential backoff (4s → 256s) + jitter, max 6 attempts | RateLimitError, APITimeoutError, 5xx |

**Locked judge prompt** (hash `e1814ba76cfbf2f5…`): the script's `JUDGE_SYSTEM_PROMPT` constant. Contains the 5 metric definitions in answer-classification form — what does it mean for the answer to commit each failure mode, NOT what the ground truth is (that's the oracle's job).

---

## 3. Disagreement policy and conflict count

Per §6.3.3:

- Oracle = NA → final label NA (judge ignored)
- Oracle = POSITIVE + judge YES → final YES (failure mode fired)
- Oracle = POSITIVE + judge NO → final NO (answer correctly handled)
- Oracle = NEGATIVE + judge YES → **final NO** (failure mode structurally cannot fire; conflict logged)
- Oracle = NEGATIVE + judge NO → final NO

**Judge-oracle conflicts: 21** (out of 148 × 5 = 740 per-metric judgments). All resolved in favor of the oracle. The conflicts indicate cases where the judge thought the answer committed a failure mode but the oracle's ground truth said the metric was either NEGATIVE or NA. The judge's classification is preserved in the audit for review; the conflict count is itself a useful signal about judge over-calling.

---

## 4. Run audit

| Metric | Value |
|---|--:|
| Pairs labeled | **148 / 148** |
| System A pairs | 75 / 75 |
| System B pairs | **73 / 75** (q047 and q061 missing per [ANSWER_GENERATION_NOTES.md §5](ANSWER_GENERATION_NOTES.md)) |
| Paired set (both A and B have answers) | **73** |
| Permanent failures during labeling | 0 |
| Judge-oracle conflicts | 21 (all resolved oracle-wins) |

---

## 5. Per-metric YES rates (paired n=73)

Primary comparison. The paired set excludes q047 (`repeated_failure`) and q061 (`validation_check`) because System B has no answer for them.

| Metric | System A | System B |
|---|---|---|
| stale_validation_assumption | 2 / 14 (**14%**) | 1 / 14 (**7%**) |
| repeated_failure_loop | 0 / 14 (0%) | 0 / 14 (0%) |
| premature_action | 0 / 15 (0%) | 0 / 15 (0%) |
| false_completion_claim | **4 / 15 (27%)** | **1 / 15 (7%)** |
| missing_pause | 2 / 15 (13%) | 2 / 15 (13%) |

**Aggregate operational error rate (paired n=73)**:

- System A: **8 / 73 = 11.0%**
- System B: **4 / 73 = 5.5%**

For transparency, A's solo rate across the full 75-question set: **8 / 75 = 10.7%**.

---

## 6. Per-category × per-system × per-metric (paired)

Computed but read in the JSON audit; key observations summarized below. Full table in `data/deterministic_label_audit.json` under `per_category_per_system_per_metric_paired`.

The category × metric mapping is one-to-one (each question's category determines which metric is applicable for it). So:

| Category | Applicable metric | Paired n | A YES | B YES |
|---|---|---|---|---|
| validation_check | stale_validation_assumption | 14 | 2 | 1 |
| repeated_failure | repeated_failure_loop | 14 | 0 | 0 |
| approval_status | premature_action | 15 | 0 | 0 |
| completion_check | false_completion_claim | 15 | **4** | **1** |
| readiness_check | missing_pause | 15 | 2 | 2 |

The two zero-zero rows (`repeated_failure_loop` and `premature_action`) reflect that neither system committed the failure mode on any paired question of those categories.

---

## 7. Two metrics with zero YES rates — interpretation status

`repeated_failure_loop` and `premature_action` both came in at 0/14 and 0/15 respectively for both systems. Possible readings (not analyzed here; preserved for the v0.1 report):

- For `repeated_failure_loop`: the oracle predicted few positive-class candidates (5 positives + 9 negatives among the 15-question category, then 1 lost to q047's failure → 14 paired). The base rate of "loop present AND answer fails to flag" is low when many oracle cases are NEGATIVE (no actual loop).
- For `premature_action`: the gpt-4o generator may be consistently conservative on action-recommendation questions, OR the oracle's POSITIVE class for this category is rare enough that the failure mode opportunity rarely arises in the paired sample.

These observations stay in the audit, not interpreted as findings. The v0.1 report (deferred) is where the synthesis happens.

---

## 8. Example labels — audit evidence

For each metric, up to 8 YES labels are preserved in the audit JSON with verbatim `answer_quote`, `oracle_state`, `rationale`, and `confidence`. The example pool lets any reader audit individual calls without re-running.

Sample (full set in `data/deterministic_label_audit.json` under `examples_by_metric`):

**false_completion_claim** (4 YES labels on System A vs 1 on System B): the largest single-metric delta in the run. A typical YES from System A asserts completion while the oracle's ground truth shows ≥1 pending state belief still active. System B's overlay surfaces those pending beliefs to the LLM and the false-completion rate drops accordingly.

**stale_validation_assumption** (2 YES on A, 1 on B): System A asserts validation has happened when the log-forward shows no validation tool ran between the most recent fix_attempted and T + horizon. System B's `validation_pending` belief in the overlay reduces this.

The complete per-metric example pools, with quotes, are preserved in the audit JSON for the report writer.

---

## 9. Methodological caveats

1. **Single LLM judge.** No inter-judge agreement check. v0.2 candidate: 2-judge protocol with Cohen's kappa.

2. **Judge-generator separation is partial.** Generator: gpt-4o-2024-08-06 (4o family). Judge: gpt-5-mini-2025-08-07 (gpt-5 family). Different family, but both OpenAI. v0.2 candidate: cross-vendor judge.

3. **Paired set is n=73, not n=75.** Two questions (q047, q061) are missing System B answers because of the org-tier TPM cap (see [ANSWER_GENERATION_NOTES.md §5](ANSWER_GENERATION_NOTES.md)). A-only solo rates over 75 are reported for transparency but the primary paired comparison is n=73.

4. **Judge-oracle conflicts: 21.** The judge's answer-classification was overridden by the oracle 21 times. Oracle authority is the locked discipline. The 21 conflicts are preserved in per-record labels (`labels[metric].judge_oracle_conflict = true`) so any auditor can review them.

5. **Aggregate is sum-over-metrics, not mean-of-rates.** Per pre-reg §6.1: `op_error_rate = sum(YES) / sum(applicable)`. Per-metric rates are reported alongside so high-applicability metrics don't hide per-metric failures.

6. **Cross-experiment comparability is locked.** Generator and judge match Stack-Grounded's models. Any operational-vs-stack-grounded comparison in the eventual v0.1 report cannot be confounded with model differences.

---

## 10. What's frozen at this step

- `deterministic_label.py` — judge prompt, schema, locked parameters, oracle-wins combination logic
- `data/deterministic_labels.jsonl` — 148 per-pair label records (each with all 5 metrics labeled)
- `data/deterministic_label_audit.json` — full audit: per-metric rates (paired + solo), per-category × per-system × per-metric, judge-oracle conflicts, examples per metric, locked parameter recording

---

## 11. What's NOT done

- **Preference judging** (pre-reg §7) — next step. Same locked judge model selection process (gpt-4.1 per Stack-Grounded precedent), three axes, blind to context.
- **v0.1 report** — explicitly deferred. Synthesizes deterministic + preference + disagreement analysis per pre-reg §9.

---

## 12. How to reproduce

```bash
cd /path/to/repo
source venv/bin/activate
python operational_belief_v1/deterministic_label.py
```

Inputs that must already exist:

- `operational_belief_v1/questions.jsonl`
- `operational_belief_v1/data/contexts_a.jsonl`, `contexts_b.jsonl`
- `operational_belief_v1/data/answers_a.jsonl`, `answers_b.jsonl`
- `operational_belief_v1/data/operational_beliefs.jsonl`
- `tkos_log_replay/data/sessions_normalized.jsonl`, `reasoning_ledger.jsonl`, `phase2_belief_timelines.jsonl`, `phase2_sample.json`
- `.env` with `OPENAI_API_KEY`

The script is idempotent. Re-running skips `(question_id, system)` pairs that already have all 5 metrics labeled.

---

## 13. Audit trail

| Field | Value |
|---|---|
| Deterministic-label version | v0.1 |
| Locked | 2026-06-01 |
| Author | Susan Stranburg |
| Judge script | `deterministic_label.py` |
| Oracle script | [`score_operational_label.py`](score_operational_label.py) (step 5a) |
| Companion pre-registration | [OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md](OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md) |
| Companion notes | [OPERATIONAL_BELIEF_SUBSTRATE_NOTES.md](OPERATIONAL_BELIEF_SUBSTRATE_NOTES.md) · [QUESTION_SET_CONSTRUCTION_NOTES.md](QUESTION_SET_CONSTRUCTION_NOTES.md) · [CONTEXT_CONSTRUCTION_NOTES.md](CONTEXT_CONSTRUCTION_NOTES.md) · [ANSWER_GENERATION_NOTES.md](ANSWER_GENERATION_NOTES.md) |
| Inputs read | questions, contexts (A, B), answers (A, B), operational substrate, TKOS source artifacts |
| Inputs NOT read | any preference-judging artifact, any final-report artifact |
