# Deterministic Labeling Notes — Stack-Grounded Retrieval v0.1

_Locked alongside the pre-registration, question set, substrate, contexts, and answers on 2026-05-31._

This document records how the 150 paired answers in `answers_a.jsonl` + `answers_b.jsonl` were labeled against the five pre-registered deterministic metrics. It preserves the judge protocol, the per-(metric, system, category) rates, and verbatim example labels (with rationale + quote) so that any reader can audit individual calls without re-running the judge.

**Important**: this document is *not* the v0.1 report. The rates here are the raw labeling output. Interpretation of what the rates mean for the experiment's primary hypothesis is deferred to step 3e (preference judging) and the final report.

---

## 1. What this step does (and does not do)

**Does:**

- For each of the 150 `(question_id, system)` pairs, calls a locked LLM judge that returns 5 structured labels in a single JSON response.
- Records per label: YES / NO / NA, verbatim `answer_quote`, verbatim `context_evidence`, 1-2 sentence rationale, confidence (0.0-1.0).
- Aggregates per-metric YES rates by system and by question category.
- Preserves up to 8 example YES labels per metric in the audit JSON (the judge's quotes and rationales are kept for downstream review).

**Does not:**

- Run preference judging (pre-reg §7) — deferred to step 3d.
- Revise prompts, contexts, or answers based on label inspection.
- Compare answers qualitatively outside the structured labeling protocol.
- Draw experimental conclusions or write the v0.1 report.

---

## 2. Locked v0.1 deterministic-judge parameters

| Parameter | Value | Notes |
|---|---|---|
| Judge model | `gpt-5-mini-2025-08-07` | OpenAI reasoning model; different model family from generator (gpt-4o) for judge-generator separation |
| Reasoning effort | `medium` | Balances reliability of subtle stale-claim / contradiction calls against latency and cost |
| `top_p` | `1.0` | Default |
| Temperature | **not settable** | gpt-5-mini-2025-08-07 only supports the default temperature (~1.0); recorded as such in the audit |
| `seed` | `20260531` | Best-effort determinism per OpenAI's seed contract; `system_fingerprint` changes can vary outputs |
| `max_completion_tokens` | `5000` | Originally 3000; raised to 5000 after two early-run calls hit `finish=length` (the reasoning + JSON output for difficult cases needed more budget). Re-run picked up only the two failures via the resume policy |
| Response format | `json_schema` (strict typing) | Structured output enforced — see `LABEL_SCHEMA` in the script |
| System identity visibility | judge sees `system: A` or `system: B` for tracking | The judge prompt explicitly instructs: *"The system identity is shown for tracking only — DO NOT let it influence your label."* Per user direction: auditability matters; the judge is told not to use it as a criterion |
| Retry policy | exponential backoff (4s → 256s) + jitter, max 6 attempts | Triggered on RateLimitError, APITimeoutError, 5xx errors |

**Judge-generator separation**: the generator was `gpt-4o-2024-08-06` (4o family). The judge is `gpt-5-mini-2025-08-07` (gpt-5 family). Different family + different tier; this is the methodologically cleaner setup compared to using gpt-4o as its own judge.

---

## 3. The locked judge prompt (constant across all 150 calls)

The system prompt hash is `a63439d6bc888d89…`; the full text is preserved in `data/deterministic_label_audit.json` under `judge_prompt`. The five metric definitions it enforces (verbatim from the prompt):

1. **STALE_CLAIM_ERROR** — *"The answer asserts as current/active a fact that the context shows has been weakened, contradicted, or retired. For System B contexts: look for belief items with `state: retired`, `state: contradicted`, or `state: weakened`. For System A contexts: look for chronological reversal. If the answer cites the older state without flagging the staleness, that is YES."*

2. **UNSUPPORTED_CLAIM** — *"The answer asserts a specific fact that the context does not support. Pure hallucination check."*

3. **CONTRADICTION_OMISSION** — *"The context contains evidence that contradicts or qualifies the answer's claim, and the answer fails to acknowledge or characterize it."*

4. **INSUFFICIENT_WARRANT_OVERCLAIM** — *"When the context is empty (the `(no items)` sentinel), or belief items are marked OUT_OF_DISTRIBUTION, or only one or two thin chunks support a claim, the answer should decline or qualify. If the answer confidently asserts substantive claims under thin warrant, that is YES."*

5. **EVIDENCE_BOUNDARY_VIOLATION** — *"The answer cites a specific date, event, or development from AFTER the evidence_cutoff. This catches training-prior contamination."*

Guidance lines in the prompt (verbatim): *"Be conservative on YES. Require concrete evidence in the quote. Use the exact verbatim text in the quote fields, not paraphrase. Empty answer_quote and context_evidence are required for NO/NA labels. A clean decline ('the context does not support an answer') is NO on all metrics by default."*

The judge prompt was fixed before the first call. No edits were made based on inspecting outputs.

---

## 4. Per-(question, system) record schema

Every line in `deterministic_labels.jsonl` carries:

```json
{
  "question_id":          "q012_current_intel_NVDA_20260526",
  "system":               "A" | "B",
  "category":             "current_intel",
  "ticker":               "NVDA",
  "evidence_cutoff":      "2026-05-26",
  "judge_model":          "gpt-5-mini-2025-08-07",
  "model_resolved":       "gpt-5-mini-2025-08-07",
  "system_fingerprint":   null | "fp_xxx",
  "reasoning_effort":     "medium",
  "seed":                 20260531,
  "judge_prompt_hash":    "sha256(judge_system_prompt)",
  "prompt_hash":          "sha256(judge_prompt + user_payload)",
  "context_hash":         "sha256(grounding_payload)",
  "answer_hash":          "sha256(answer_text)",
  "input_tokens":         int,
  "output_tokens":        int,
  "reasoning_tokens":     int,
  "finish_reason":        "stop",
  "labels": {
    "stale_claim_error":              {"label":"...","answer_quote":"...","context_evidence":"...","rationale":"...","confidence":0.0-1.0},
    "unsupported_claim":              {...},
    "contradiction_omission":         {...},
    "insufficient_warrant_overclaim": {...},
    "evidence_boundary_violation":    {...}
  },
  "labeled_at": "2026-05-31T…Z"
}
```

Hashes make every label re-verifiable without re-running the judge: the hash chain proves which `(judge_prompt, context, answer)` triple produced which label.

---

## 5. Run audit

| Metric | Pairs labeled | Pairs missing | Notes |
|---|--:|--:|---|
| All metrics complete | 150 / 150 | 0 | Initial run had 2 `finish=length` failures; resume run with `max_completion_tokens=5000` cleared both |

**Cost summary** (gpt-5-mini-2025-08-07): combined input ~1.1M tokens + output ~140K tokens ≈ **$0.55** for the 150 labels.

**Reliability events**: 0 permanent failures after the budget bump. The two original failures (`q021_change_detection_SNOW_20260415/A`, `q070_insufficient_warrant_COHR_20260131/A`) are preserved as historical records in `deterministic_labels.jsonl`; the dedup-by-`(question_id, system)` audit logic picks the complete records emitted by the resume run.

---

## 6. Per-metric YES rates (among applicable)

| Metric | System A | System B |
|---|---|---|
| stale_claim_error | **1 / 74 (1%)**  NA=1 | **8 / 65 (12%)**  NA=10 |
| unsupported_claim | **10 / 70 (14%)**  NA=5 | **18 / 65 (28%)**  NA=10 |
| contradiction_omission | **17 / 71 (24%)**  NA=4 | **21 / 59 (36%)**  NA=16 |
| insufficient_warrant_overclaim | **1 / 70 (1%)**  NA=5 | **6 / 75 (8%)**  NA=0 |
| evidence_boundary_violation | **1 / 73 (1%)**  NA=2 | **0 / 72 (0%)**  NA=3 |

"Applicable" = YES + NO (excludes NA). NA cells are recorded but excluded from rate denominators.

No analysis or interpretation here — these are the raw judge counts. They go into the v0.1 report's deterministic-track section after preference judging completes.

---

## 7. Per-category × per-system × per-metric YES rates

### change_detection (15 questions)

| Metric | A | B |
|---|---|---|
| stale_claim_error | 0/15 (0%) | 0/12 (0%) |
| unsupported_claim | 2/14 (14%) | 7/11 (64%) |
| contradiction_omission | 5/14 (36%) | 7/10 (70%) |
| insufficient_warrant_overclaim | 0/14 (0%) | 0/15 (0%) |
| evidence_boundary_violation | 0/15 (0%) | 0/14 (0%) |

### contradiction (15 questions)

| Metric | A | B |
|---|---|---|
| stale_claim_error | 0/15 (0%) | 4/15 (27%) |
| unsupported_claim | 2/15 (13%) | 7/15 (47%) |
| contradiction_omission | 2/15 (13%) | 6/12 (50%) |
| insufficient_warrant_overclaim | 0/12 (0%) | 1/15 (7%) |
| evidence_boundary_violation | 0/15 (0%) | 0/15 (0%) |

### current_intel (15 questions)

| Metric | A | B |
|---|---|---|
| stale_claim_error | 0/15 (0%) | 4/15 (27%) |
| unsupported_claim | 0/15 (0%) | 3/15 (20%) |
| contradiction_omission | 1/14 (7%) | 7/14 (50%) |
| insufficient_warrant_overclaim | 0/14 (0%) | 4/15 (27%) |
| evidence_boundary_violation | 0/15 (0%) | 0/15 (0%) |

### insufficient_warrant (15 questions)

| Metric | A | B |
|---|---|---|
| stale_claim_error | 0/14 (0%) | 0/8 (0%) |
| unsupported_claim | 0/13 (0%) | 0/10 (0%) |
| contradiction_omission | 1/13 (8%) | 0/9 (0%) |
| insufficient_warrant_overclaim | 1/15 (7%) | 0/15 (0%) |
| evidence_boundary_violation | 1/15 (7%) | 0/15 (0%) |

### stale_assumption (15 questions)

| Metric | A | B |
|---|---|---|
| stale_claim_error | 1/15 (7%) | 0/15 (0%) |
| unsupported_claim | 6/13 (46%) | 1/14 (7%) |
| contradiction_omission | 8/15 (53%) | 1/14 (7%) |
| insufficient_warrant_overclaim | 0/15 (0%) | 1/15 (7%) |
| evidence_boundary_violation | 0/13 (0%) | 0/13 (0%) |

---

## 8. Example labels — audit evidence

For each metric, up to 3 verbatim YES examples. The judge's `answer_quote`, `context_evidence`, and `rationale` are preserved exactly so the labels are auditable without re-running.

### 8.1 stale_claim_error (8 YES labels — sample)

**`q002_current_intel_ARM_20260526` / System B** (conf 0.86)
- Rationale: *"The answer asserts that all beliefs are retired, but the context explicitly contains beliefs marked as 'born' (active/new), so the answer incorrectly treats born items as retired."*
- Answer quote: *"All the beliefs and narratives about ARM are marked as 'retired,' with the most recent updates occurring in 2026."*
- Context evidence: `BELIEF [ent-47ff4c6a45] ARM (theme=theme-63a48ff0) — "ARM's AI Chip Expansion Begins to Lift Stock" warrant: PARTIAL (confidence=0.70, support_n=1) state: born (first_seen 2026-05-21, last_updated …)`

**`q004_current_intel_NBIS_20260526` / System B** (conf 0.90)
- Rationale: *"The answer claims all beliefs are retired, but the context explicitly contains beliefs with state: born (e.g., ent-8e51468259 dated 2026-05-26), so the answer treats stale information as current."*
- Answer quote: *"The context does not provide any current claims about NBIS. All the beliefs listed are in a 'retired' state, meaning they are no longer active or current."*

**`q007_current_intel_AAPL_20260526` / System B** (conf 0.85)
- Rationale: *"The answer asserts ongoing 'driving early price leadership' while the corresponding belief in the context is explicitly marked 'state: retired', indicating the claim is stale and should have been qualified."*
- Answer quote: *"There are beliefs that these factors are driving early price leadership and positive momentum"*
- Context evidence: belief with `state: retired`

### 8.2 unsupported_claim (28 YES labels — sample)

**`q002_current_intel_ARM_20260526` / System B** (conf 0.86)
- Rationale: *"The claim that no active intel exists is unsupported because the context includes born-state beliefs indicating recent/active intel."*
- Answer quote: *"There is no active or ongoing intel available in the provided context."*

**`q006_current_intel_ADBE_20260526` / System B** (conf 0.93)
- Rationale: *"The answer states that all beliefs are retired and that no current claims exist, but the context contains beliefs with state: born (e.g., ent-353570b735 and ent-160bba2832), so the claim is unsupported."*
- Answer quote: *"The context does not provide any current claims about ADBE. All the beliefs listed are in a 'retired' state, indicating they are no longer active or current."*

### 8.3 contradiction_omission (38 YES labels — sample)

**`q002_current_intel_ARM_20260526` / System B** (conf 0.87)
- Rationale: *"The context contains born (active) beliefs that directly contradict the answer's assertion of no active intel, and the answer does not acknowledge these born entries."*

### 8.4 insufficient_warrant_overclaim (7 YES labels — sample)

**`q007_current_intel_AAPL_20260526` / System B** (conf 0.80)
- Rationale: *"The answer makes confident, broad statements though current supporting beliefs in the context are 'born' or 'PARTIAL' with very small support counts, indicating limited warrant for such definitive summary."*
- Answer quote: *"The current state of AAPL, as of the latest updates in May 2026, involves a focus on AI features and manufacturing in India, which are influencing its market dynamics."*

**`q009_current_intel_CEG_20260526` / System B** (conf 0.78)
- Rationale: *"The cited belief has only a single supporting item and a PARTIAL warrant, yet the answer states the regulatory-hurdles claim confidently without qualification."*
- Answer quote: *"'CEG's Nuclear PPA Pipeline Faces Regulatory Hurdles' — This belief is in a born state, indicating that CEG's nuclear power purchase agreement pipeline is encountering regulatory challenges."*

### 8.5 evidence_boundary_violation (1 YES label — full)

**`q065_insufficient_warrant_VRT_20260315` / System A** (conf 0.86)
- Rationale: *"The answer cites a specific event date (March 23, 2026) that is after the evidence cutoff (2026-03-15); even though the context mentions that date, the answer references an event occurring post-cutoff, so this triggers the boundary check."*
- Answer quote: *"VRT is set to join the S&P 500 on March 23, 2026, which is expected to further boost demand for its shares."*
- Context evidence: *"VRT jumps 9.3% on news that it will join the S&P 500 on March 23, a move expected to drive demand from index funds and spotlight its role in data-center infrastructure."*

**Auditor note** on the lone evidence_boundary_violation YES: this is a borderline case. The chunk in the context (pre-cutoff) referenced a forward-looking event ("will join on March 23"). The answer carried that forward reference. Whether this counts as a true boundary violation (the chunk's date was before cutoff but the event it described was after) is a definition-judgment call. The judge labeled YES with rationale; the auditor can re-grade if needed. This is exactly the kind of subjectivity the user flagged.

---

## 9. Judge confidence distribution

Mean confidence (across non-NA labels) ranges 0.86–0.91 by metric × system. Confidence floor: 0.64 (one System B `insufficient_warrant_overclaim` call); ceiling: 1.0 (one System B `evidence_boundary_violation` NA at 1.0).

| Metric | A mean | A range | B mean | B range |
|---|---|---|---|---|
| stale_claim_error | 0.89 | 0.75-0.95 | 0.88 | 0.75-0.95 |
| unsupported_claim | 0.91 | 0.80-0.96 | 0.90 | 0.78-0.95 |
| contradiction_omission | 0.88 | 0.78-0.95 | 0.87 | 0.72-0.95 |
| insufficient_warrant_overclaim | 0.89 | 0.70-0.95 | 0.86 | 0.64-0.95 |
| evidence_boundary_violation | 0.91 | 0.80-0.98 | 0.90 | 0.70-1.00 |

Confidence values are not used to filter labels in v0.1 — they are recorded for auditability. A future step could weight or threshold labels by confidence if calibration data warrants.

---

## 10. Methodological caveats (preserve and read at report time)

These are the gotchas the user explicitly flagged. They go into the v0.1 report's methodology section verbatim.

1. **Single LLM judge.** v0.1 uses one judge with no inter-judge agreement check. A v0.2 candidate is a 2-judge or 3-judge protocol with Cohen's kappa / Fleiss' kappa for agreement. The structured-output format makes this straightforward to add.

2. **Judge-generator separation is only partial.** We used a different model family (gpt-5-mini vs gpt-4o) but both are OpenAI. A v0.2 candidate: cross-provider judge (e.g., Claude judging OpenAI-generated answers, or vice versa) to test whether labeled differences hold across provider boundaries.

3. **Stale-claim and contradiction-omission are the most subjective metrics.** Per the user's flagging: these involve nuanced calls about whether the answer "qualified" or "characterized" contradictory evidence sufficiently. The judge prompt asks for verbatim quotes from both the answer and the context to constrain hallucinated YES labels, but reasonable graders can disagree on borderline cases. The audit JSON preserves the judge's full rationale and quotes for any future re-grading.

4. **Evidence_boundary_violation is structurally rare in v0.1.** Both substrates enforce the cutoff architecturally before retrieval (see CONTEXT_CONSTRUCTION_NOTES §6: 0 violations across 38,586 items at the substrate level). The only way this metric fires is via training-prior leakage in the answer text. The single YES (q065 / A) is a borderline definitional case where the answer carried forward a future-dated event mentioned in a pre-cutoff chunk.

5. **NA rates differ across metrics and systems** (especially `contradiction_omission` B with 16 NA, vs A with 4). The judge calls NA when the metric doesn't apply (e.g., no contradictory evidence is present, or the answer is a clean decline). NA rates carry information about which questions had structurally-present contradiction/staleness signals to test for. They are recorded but not part of the YES rate denominators.

6. **System identity is shown to the judge.** Per user direction, the audit value of seeing the system label outweighs the bias risk. The judge prompt explicitly forbids using identity as a criterion. v0.2 candidate: blind variant (judge sees only "system X / system Y" with shuffled assignment) for sensitivity testing.

7. **Judge stability across `system_fingerprint` changes**: OpenAI's seed contract is best-effort, not bit-identical. The audit records every per-call `system_fingerprint` so any future re-run can verify whether routing changed the labels. For v0.1 reporting, the artifacts as written are canonical.

---

## 11. What's frozen at this step

- `deterministic_label.py` — judge prompt, schema, locked parameters
- `data/deterministic_labels.jsonl` — 150 per-pair label records (plus 2 historical failure records from the budget-bump cleanup)
- `data/deterministic_label_audit.json` — aggregated rates + example labels + confidence stats

---

## 12. What's NOT frozen (deferred to step 3d)

- Preference judging (pre-reg §7) — separate locked judge + protocol
- Cross-judge agreement (multi-judge protocol candidate for v0.2)
- Aggregation method for the final report (pre-reg §7.4)
- v0.1 report writing (deferred until preference judging completes)

---

## 13. How to reproduce

```bash
cd /Users/sue/Documents/git/storm
source venv/bin/activate
python stack_grounded_v1/deterministic_label.py
```

Inputs that must already exist:

- `stack_grounded_v1/questions.jsonl`
- `stack_grounded_v1/data/contexts_a.jsonl`, `contexts_b.jsonl`
- `stack_grounded_v1/data/answers_a.jsonl`, `answers_b.jsonl`
- `.env` with `OPENAI_API_KEY`

The script is idempotent: re-running skips `(question_id, system)` pairs that already have all 5 metrics labeled. Incomplete or failed records on disk are silently re-attempted. To regenerate from scratch, delete `deterministic_labels.jsonl`.

**Determinism caveat**: `temperature` is not settable on `gpt-5-mini-2025-08-07`. `seed=20260531` is provided but OpenAI's seed contract is best-effort across `system_fingerprint` changes. Re-running may produce slightly different labels on some questions. The v0.1 artifacts as written are canonical.

---

## 14. Audit trail

| Field | Value |
|---|---|
| Deterministic-label version | v0.1 |
| Locked | 2026-05-31 |
| Author | Susan Stranburg |
| Judge script | `deterministic_label.py` |
| Companion pre-registration | [STACK_GROUNDED_PRE_REGISTRATION_v0.1.md](STACK_GROUNDED_PRE_REGISTRATION_v0.1.md) |
| Companion notes | [QUESTION_SET_CONSTRUCTION_NOTES.md](QUESTION_SET_CONSTRUCTION_NOTES.md) · [SUBSTRATE_CONSTRUCTION_NOTES.md](SUBSTRATE_CONSTRUCTION_NOTES.md) · [CONTEXT_CONSTRUCTION_NOTES.md](CONTEXT_CONSTRUCTION_NOTES.md) · [ANSWER_GENERATION_NOTES.md](ANSWER_GENERATION_NOTES.md) |
| Inputs read | questions, contexts_a/b, answers_a/b |
| Inputs NOT read | any preference-judge artifact, any final-report artifact |
