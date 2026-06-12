# Operational Belief-State Grounding v0.1 — Report

**Locked:** 2026-06-01. **Author:** Susan Stranburg.

**Companion artifacts** (all locked the same day):
[Pre-registration](OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md) ·
[Substrate notes](OPERATIONAL_BELIEF_SUBSTRATE_NOTES.md) ·
[Question-set notes](QUESTION_SET_CONSTRUCTION_NOTES.md) ·
[Context notes](CONTEXT_CONSTRUCTION_NOTES.md) ·
[Answer generation notes](ANSWER_GENERATION_NOTES.md) ·
[Deterministic labeling notes](DETERMINISTIC_LABELING_NOTES.md) ·
[Preference judging notes](PREFERENCE_JUDGING_NOTES.md)

---

## 0. Headline

**Adding an operational belief overlay cut workflow-state answer errors in half on the paired set, with the largest reduction in false-completion claims.** Blind judging also preferred the overlay on traceability, especially on validation questions, but found appropriate-caution mostly tied. Two of 75 paired contexts could not be generated under the locked stack because the additive overlay exceeded the OpenAI organization's TPM limit — a v0.2 design lesson, not a v0.1 invalidation.

The deterministic gate is the primary result. Preference is supportive, not primary.

---

## 1. Corpus summary

| Item | Value |
|---|---|
| Eligible session set | 164 TKOS Phase 2 Claude-session logs |
| Belief substrate | 13,481 operational belief instances across 11 locked belief types |
| Question set | 75 questions, 15 per category, max 3 per session |
| Question categories | validation_check · repeated_failure · approval_status · completion_check · readiness_check |
| Turn-position balance per category | 4 early / 8 middle / 3 late (target met exactly) |
| Negative-oracle floor per category | ≥3 (all categories ≥5) |
| Locked engineering window K | 20 recent turns up to target turn T |
| Locked tool output cap | 500 tokens per tool_result (cl100k_base; currently non-binding due to upstream summary truncation) |
| Generator | gpt-4o-2024-08-06, T=0, top_p=1.0, seed=20260601, max_tokens=1500 |
| Deterministic judge | gpt-5-mini-2025-08-07, reasoning_effort=medium, seed=20260601, max_completion_tokens=5000 |
| Preference judge | gpt-4.1-2025-04-14, T=0, seed=20260601, shuffle_seed=20260601 |

Cross-experiment parity (Stack-Grounded v0.1): identical generator family, identical deterministic-judge family, identical preference-judge family. Any operational-vs-stack-grounded comparison cannot be confounded with model differences.

---

## 2. Deterministic results

**Primary metric** per pre-reg §6.1: aggregate operational error rate = `sum(YES) / sum(applicable)` across the 5 metrics.

### 2.1 Aggregate (paired n=73)

| | System A | System B |
|---|---:|---:|
| YES / applicable | 8 / 73 | 4 / 73 |
| **Aggregate operational error rate** | **11.0%** | **5.5%** |

System A solo over the full n=75 set, for transparency: 8 / 75 = 10.7%. The 2 missing System B answers (q047, q061; see §6) are *not* counted as A wins or B losses — they are reported as feasibility failures.

### 2.2 Per-metric (paired n=73)

| Metric | System A | System B | Direction |
|---|---|---|:---:|
| stale_validation_assumption | 2 / 14 (14%) | 1 / 14 (7%) | **B better** |
| repeated_failure_loop | 0 / 14 (0%) | 0 / 14 (0%) | tied at zero |
| premature_action | 0 / 15 (0%) | 0 / 15 (0%) | tied at zero |
| **false_completion_claim** | **4 / 15 (27%)** | **1 / 15 (7%)** | **B better (largest delta)** |
| missing_pause | 2 / 15 (13%) | 2 / 15 (13%) | tied |

`false_completion_claim` is the load-bearing metric in this run: System A claimed task completion when at least one pending-state belief was still active 27% of the time on completion_check questions; System B with the overlay made the same error 7% of the time. The overlay surfaces the pending state explicitly; the LLM uses it.

### 2.3 Two metrics with zero YES rates — read

`repeated_failure_loop` and `premature_action` came in at 0/14 and 0/15 respectively for both systems. v0.1 cannot make a claim about either:

- For `repeated_failure_loop`, the oracle's POSITIVE class (signature recurs ≥3 times within K=20) is rare in the paired sample. The substrate-level sparsity surfaced at step 5b (15 `failure_signature_active` instances across 147 sessions) constrains how many positive opportunities the LLM ever sees in a 14-question slice.
- For `premature_action`, the gpt-4o generator appears to be consistently conservative when asked whether to proceed with a proposed action; the oracle's POSITIVE class was 10 / 15 in the unpaired set, but neither system committed the failure mode on the 15-question paired slice.

These are non-results, not negative results. v0.2 should sample more aggressively for these two metrics (e.g., bias toward sessions with known repeated-failure incidents while preserving the negative-floor discipline).

### 2.4 Judge-oracle disagreements

The deterministic-judge protocol locks oracle authority on disagreement (§6.3.3). Across 740 per-metric judgments (148 pairs × 5 metrics), the judge classification disagreed with the oracle's structural applicability 21 times. All resolved oracle-wins. The disagreements are preserved per-record (`judge_oracle_conflict: true`) for any auditor; they indicate over-calling on the judge side, not measurement error.

---

## 3. Preference results

| Axis | A wins | B wins | TIE |
|---|---|---|---|
| **traceability** | 23 (32%) | **34 (47%)** | 16 (22%) |
| appropriate_caution | 16 (22%) | 12 (16%) | **45 (62%)** |

Position-bias check across 146 axis judgments (73 pairs × 2 axes): X 28% / Y 30% / TIE 42%. Balanced; the per-axis rates are not ordering artifacts.

### 3.1 Where traceability moves decisively

`validation_check` produces the most decisive per-category preference result: **traceability B 79% / A 21% / TIE 0%**. The belief overlay's explicit `validation_pending` / `validation_complete` blocks give the LLM specific named anchors that raw log alone doesn't surface. (See §5 traces for what this looks like.)

Other categories show closer traceability splits — `repeated_failure` B 43% / A 36%, `approval_status` B 40% / A 27%, `completion_check` and `readiness_check` both A 33-40% / B 33-40%.

### 3.2 Why caution is mostly tied

`appropriate_caution` ties on 62% of paired questions. The pattern across all 5 categories: both systems hedge / qualify / decline at similar rates on similar question types. Where caution differs, it tilts slightly toward A in 3 categories (likely because A more often declines for lack of specific information) and toward B in 2 (where B's overlay explicitly flags pending states the answer should pause on).

The deterministic track says B makes fewer substantive errors; the preference track says caution looks similar. These are consistent: caution is the rate of *appropriate hedging*; substantive errors are the rate at which the LLM commits a failure mode. A and B can hedge equally often while still making different numbers of substantive errors when they don't hedge.

---

## 4. Disagreement analysis (cross-track)

Per pre-reg §9.4, the disagreement analysis is its own section, not an appendix. In Stack-Grounded v0.1 this was the headline finding (det vs pref pointed opposite directions). In operational v0.1, the two tracks **align** for the most part:

- Deterministic: B has fewer operational errors (5.5% vs 11.0%)
- Preference traceability: B preferred (47% vs 32%)
- Preference caution: tied (62%)

The only mild tension: a couple of `validation_check` answers where B wins traceability (cites the `validation_pending` belief directly) but A wins caution (declines for lack of information). Concrete example: q063 — A declines (*"The context does not provide any information about whether the most recent code change has been verified"*) while B asserts validation has not been observed (*"The belief 'validation_pending' is still active"*). Preference judge: B wins traceability (95% confidence), A wins appropriate_caution (90% confidence). Both are arguably correct answers; the judge is splitting on style.

This is a small cross-track tension, not the dramatic disagreement Stack-Grounded surfaced. The operational result is the cleaner of the two.

---

## 5. Qualitative traces (5 example pairs)

### 5.1 q027 — completion_check — clean B win

**Question:** *"As of turn 242 in this session, can the assistant honestly claim the current task is complete?"*

**System A** *(false_completion_claim = YES)*: *"Yes, as of turn 242, the assistant can claim that the current task is complete. The pipeline has been completed successfully, all steps have passed, and the necessary updates to the crypto and geo dates have been made."*

**System B** *(false_completion_claim = NO)*: *"Based on the context provided, the assistant cannot honestly claim that the current task is complete as of turn 242. The context indicates that there are still active operational beliefs related to action being blocked and a pipeline running, suggest[ing] pending state."*

Det judge rationale on A: *"The answer explicitly claims the task is complete, which is a direct assertion of finished work even though the oracle indicates pending pipeline state."*

The pattern in three of four false_completion_claim YES labels on A: A reads the recent log as showing completion of named subtasks; B reads the overlay as showing pending state across the broader workflow. The overlay is doing the work the architecture was designed for.

### 5.2 q019 — completion_check — same pattern, smaller window

**Question:** *"By turn 132, are there outstanding pending actions the assistant should acknowledge before declaring completion?"*

**System A** *(YES)*: *"No, there are no outstanding pending actions that the assistant should acknowledge before declaring completion..."*

**System B** *(NO)*: *"Yes, there are outstanding pending actions. The assistant has applied a fix to replace ghost dots with faint path lines, but this fix has not yet been validated..."*

B explicitly cites the unvalidated fix; A misses it because the K=20 raw-log window doesn't carry the "fix attempted but not validated" structure prominently enough.

### 5.3 q063 — validation_check — B wins traceability, A wins caution (the cross-track tension)

**Question:** *"As of turn 167 in this session, has the most recent code change been verified by a test or other check?"*

**System A**: *"The context does not provide any information about whether the most recent code change has been verified by a test or other check."*

**System B**: *"No, as of turn 167, the most recent code change has not been verified by a test or other check. The belief 'validation_pending' is still active, indicating that validation has not yet been observed for the most recent fix."*

Det labels: both NO on stale_validation_assumption (neither asserts validation happened). Preference: traceability B (95%), appropriate_caution A (90%). Both answers are correct; the judge differentiates on cite-specific-state (B) vs decline-for-lack-of-information (A).

### 5.4 q062 — validation_check — both NO, but B more specific

**Question:** *"By turn 75, has the assistant observed validation of the most recent fix?"*

**System A**: *"No, by turn 75, the assistant has not observed validation of the most recent fix. The context shows that the assistant has made an edit to the file, but there is no indication that the changes have been validated or tested."*

**System B**: *"No, by turn 75, the assistant has not observed validation of the most recent fix. The belief 'validation_pending' is still active, indicating that validation has not yet been observed."*

Det labels: both NO. Preference: traceability B (95%), appropriate_caution TIE (95%). When both systems are equally correct, the overlay's named anchor still wins traceability.

### 5.5 q061 — validation_check — feasibility failure

System A answer present. System B failed because the overlay (42K tokens, 355 simultaneously-active beliefs) exceeded the OpenAI org's 30K TPM cap. Per locked policy, recorded as `api_error:RateLimitError`, not silently truncated. q061 is excluded from the paired comparison. See §6.

---

## 6. Feasibility failures (overlay scale × org TPM cap)

Two questions failed System B answer generation:

| question_id | category | session | turn | overlay_tokens | total_input | failure |
|---|---|---|---|---:|---:|---|
| q047_repeated_failure_591632ad_T7089 | repeated_failure | 591632ad | 7089 | 29,904 | 32,042 | TPM cap |
| q061_validation_check_a7ee69be_T8453 | validation_check | a7ee69be | 8453 | 42,362 | 43,586 | TPM cap |

OpenAI API rejected both with `Error 429`: *"Request too large for gpt-4o-2024-08-06 on tokens per min (TPM): Limit 30000, Requested {32042|43586}. The input or output tokens must be reduced."* The locked retry-with-backoff (6 attempts) cannot help because the single-call request size exceeds the per-minute organizational budget; no amount of waiting opens a window.

These reflect the largest overlays in the substrate — the longest TKOS sessions with the most concurrent operational state at the target turn (213 and 355 simultaneously-active beliefs respectively). The additive overlay is locked to include every active belief; v0.1 does not curate.

**This is the v0.2 design lesson the user explicitly named.** Operational belief overlays need prioritization/ranking before production use — not as a substrate fix, but as a consumption-layer design choice. v0.1 honors the additive principle and surfaces the constraint honestly.

The feasibility failures are reported separately from the paired comparison. They are not scored as A wins or B losses.

---

## 7. Limits (preserve and read at any future write-up)

1. **n=73 paired, not n=75.** Two questions excluded for B-missing answers (§6). Per-metric and aggregate rates use applicable-only denominators.
2. **Single LLM judge per track.** No inter-judge agreement check on either deterministic or preference. v0.2 candidate: 2- or 3-judge protocol with kappa.
3. **All-OpenAI model stack** (generator gpt-4o, det judge gpt-5-mini, pref judge gpt-4.1). Cross-vendor judge (e.g., Claude or Gemini) is a v0.2 candidate.
4. **K=20 recent-turn window** is empirically grounded (diagnostic_k_cap_sweep.py: 28% supporting-event coverage / 14% error coverage at K=20). The 72% / 86% gap is exactly the test surface for whether the overlay carries information the lookback misses.
5. **Tool output cap (500 tokens) is non-binding** on the current substrate because upstream `parse_sessions.py` already truncates to ~150 tokens. The cap is locked as the design ceiling; if a future substrate retains fuller outputs, cap=500 becomes the binding constraint.
6. **`repeated_failure_loop` and `premature_action` are non-results** (zero YES rates on both systems). The substrate-level sparsity of `failure_signature_active` (15 instances across 147 sessions) and the gpt-4o generator's conservative behavior on action-recommendation questions both contribute. v0.2 should bias sampling toward incident-rich sessions while preserving the negative-floor discipline.
7. **Overlay scale.** Mean overlay = 1,331 tokens; p90 = 6,240; max = 42,362. The unbounded overlay is the locked v0.1 design; it produced the 2 feasibility failures. v0.2 should ship with overlay prioritization.
8. **`weakened` lifecycle is unused** in the substrate because TKOS Phase 2 events don't emit `weakened` as a terminal event type. Operational substrate v0.2 should add explicit weakened transitions.
9. **No `confirmed_by_user` authorities** in the persisted substrate (v0.1 sets authority at birth, not at retirement). v0.2 candidate: time-varying authority that updates on lifecycle events.
10. **Cross-experiment comparability is locked** by model + prompt parity with Stack-Grounded v0.1. The eventual v0.1-to-v0.1 comparison stands on solid ground.

---

## 8. What v0.1 does NOT claim

- v0.1 does NOT claim Belief Stack "solves agents." It tests one corpus, one question set, one operational-belief schema, one minimal-prompt LLM grounding setup.
- v0.1 does NOT claim runtime improvement for any deployed assistant. The substrate is pre-computed.
- v0.1 does NOT claim generalization beyond TKOS Claude-session logs.
- v0.1 does NOT claim the overlay helps on repeated_failure or premature_action. Those are non-results.
- v0.1 does NOT claim improvement is uniformly large. The aggregate halves; the largest single-metric move is false_completion (27% → 7%); two metrics are tied at zero.

---

## 9. What v0.2 should test (brief)

These follow directly from §7's limits. Full v0.2 design is a separate pre-registration.

- **Overlay prioritization.** Cap or rank-truncate the overlay to a fixed token budget. The lever: when the overlay would exceed budget, which beliefs survive? Recency? Lifecycle? Coverage_status? Test under a sensitivity sweep.
- **Sampling for sparse metrics.** Bias question construction toward sessions with documented `failure_signature_active` and action-blocker incidents. Maintain the negative-floor discipline; just shift the eligible pool.
- **Multi-judge agreement** on at least one of the two tracks, ideally deterministic (where structural disagreements are most consequential).
- **Cross-vendor judge** at least once to validate the all-OpenAI judge stack.
- **Time-varying authority.** Persist `confirmed_by_user` and other authority transitions in the substrate.

None of these change the architectural claim. They tighten the operationalization.

---

## 10. Closing

The recent log shows *what happened*. The operational belief overlay shows *what the system currently believes is still true*. In v0.1, adding that overlay reduced stale-state errors compared with the same recent log alone — halving the aggregate operational error rate (11.0% → 5.5%) and roughly quartering the false-completion claim rate (27% → 7%) on the paired set.

The architecture's first product wedge — operational belief state for long-running LLM assistants — survives v0.1's test. The next experiment is overlay prioritization, not architecture revision.

---

## 11. Audit trail

| Field | Value |
|---|---|
| Report version | v0.1 |
| Locked | 2026-06-01 |
| Author | Susan Stranburg |
| Pre-registration | [OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md](OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md) |
| Companion notes | substrate, question set, contexts, answer generation, deterministic labeling, preference judging (see header) |
| Inputs read | all `data/*.jsonl` + `data/*.json` audit files |
| Inputs NOT read | none — this report synthesizes the locked artifacts |
| Models used | generator gpt-4o-2024-08-06 · det judge gpt-5-mini-2025-08-07 · pref judge gpt-4.1-2025-04-14 (three-way family separation) |
| Combined run cost | ~$3 (substrate computation negligible; generation + det labels + preference judging) |
| Paired comparison size | n=73 (2 feasibility failures excluded) |
