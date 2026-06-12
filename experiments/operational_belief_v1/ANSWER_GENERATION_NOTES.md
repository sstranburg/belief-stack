# Answer Generation Notes — Operational Belief v0.1

_Locked as part of the answer-generation step._

This document records the locked generation parameters, the run audit, and one structural finding about the OpenAI TPM cap that affected two System B contexts.

---

## 1. What the step did

Pairs the frozen System A (raw log) and System B (raw log + belief overlay) contexts with an identical minimal prompt template. Generates one answer per (question, system). No judging, no scoring, no answer-quality inspection during generation.

---

## 2. Locked v0.1 generation parameters

| Parameter | Value | Notes |
|---|---|---|
| Model | `gpt-4o-2024-08-06` | Parity with Stack-Grounded v0.1 generator; same model family avoids confounding model differences with substrate differences |
| Temperature | 0.0 | |
| top_p | 1.0 | OpenAI default |
| max_tokens | 1500 | Same as Stack-Grounded |
| seed | 20260601 | Matches construction seed |
| Retry policy | exponential backoff 4s → 256s × jitter, max 6 attempts | RateLimitError, APITimeoutError, 5xx |

**Locked system prompt** (constant across A and B; hash `4cd185152eb5c43d…` — byte-identical to Stack-Grounded's v0.1 prompt):

```
You answer the user's question using only the information in the provided context. If the context does not support an answer, say so.
```

**Locked user template**:

```
CONTEXT:
{grounding_payload}

QUESTION:
{question}
```

Cross-experiment parity: model lock matches Stack-Grounded v0.1 so any A-vs-B differences in operational v0.1 cannot be confounded with cross-experiment model differences. Same family, same prompt → the only variables between operational and stack-grounded are: substrate, question set, and the additive-vs-replacement architecture.

---

## 3. Pre-declared failure policy

Per the locked discipline (*"If any context exceeds model limit, record it as a generation failure or use a pre-declared skip/failure policy. Do not silently truncate."*):

| Policy | Trigger | Action |
|---|---|---|
| `context_too_long` | estimated input + max_tokens > 125,000 (gpt-4o's 128K context limit, minus reserved output + system prompt overhead) | Skip without API call; write failure record with `finish_reason: context_too_long` |
| API error retry | RateLimitError, APITimeoutError, 5xx APIStatusError | Exponential backoff up to 6 attempts |
| API error permanent | Other 4xx, or rate-limit / timeout after 6 retries | Write failure record with `finish_reason: api_error:<ErrorType>` |

Resume policy: per-question idempotent. Re-running skips `(question_id, system)` pairs already in the output file with `answer_text != ""`. Failures are retried on subsequent runs.

---

## 4. Run results

| Metric | System A | System B |
|---|--:|--:|
| Contexts to process | 75 | 75 |
| Answers complete | **75** | **73** |
| Permanent failures | 0 | **2** (see §5) |
| Skipped (context_too_long pre-call) | 0 | 0 |
| Total cost (gpt-4o pricing) | — | — |
| Mean output tokens | 53 | 51 |
| Max output tokens | 116 | 111 |

System A is complete and clean. System B has 2 permanent failures that are structurally unrecoverable under the locked design (§5).

Mean output ~50 tokens is short — meta-questions about operational state typically have concise correct answers ("yes / no, here's why"). This is by design.

---

## 5. The two System B failures

| question_id | category | session | turn | overlay_tokens | total_input | failure_cause |
|---|---|---|---|--:|--:|---|
| `q047_repeated_failure_591632ad_T7089` | repeated_failure | `591632ad` | 7089 | 29,904 | 32,042 | TPM cap |
| `q061_validation_check_a7ee69be_T8453` | validation_check | `a7ee69be` | 8453 | 42,362 | 43,586 | TPM cap |

Both failed with the same OpenAI API error:

```
Error code: 429
"Request too large for gpt-4o-2024-08-06 (for limit gpt-4o) in organization
org-FMS8J450jLjNGspbjdZcZ4iq on tokens per min (TPM): Limit 30000,
Requested {32042|43586}. The input or output tokens must be reduced in order
to run successfully."
```

### Cause analysis

The OpenAI account is on **Tier 1 with a 30,000 TPM cap on gpt-4o**. The two failed requests each exceeded this single-call budget. No amount of retry-with-backoff helps because:

- The TPM cap is on the *single request size*, not on aggregate usage over time.
- A single request larger than 30K tokens is rejected immediately, regardless of timing.
- The 6 retry attempts (with up to 156s + 189s backoff in the second case) were waiting for a per-minute window that never opens for an oversized single call.

### Why this is honored under the locked policy

The `context_too_long` pre-declared policy (§3) is keyed to gpt-4o's **model context limit (128K)**. The failed contexts are far below that (43K and 32K respectively). They fit the *model*; they don't fit the *organization's tier rate-limit*.

The locked failure policy DID apply correctly:
- Retry-with-backoff was attempted (6 retries each).
- After retry exhaustion, the script wrote a `finish_reason: api_error:RateLimitError` record per the locked policy.
- No silent truncation occurred. No prompt edit. No re-roll.

### Substrate-level cause

Both failures correspond to the largest overlays in the substrate:

- **q047** has 213 simultaneously-active operational beliefs (the third-largest overlay across the 75 questions)
- **q061** has 355 simultaneously-active operational beliefs (the largest)

These are long-running TKOS sessions with heavy operational state in flight at the target turn. The additive-overlay design — locked to ensure System B receives everything System A receives plus the full belief overlay — produces these large overlays by design (§4 of CONTEXT_CONSTRUCTION_NOTES). The architectural choice was made deliberately, with the size distribution documented and flagged at context-construction time:

> *"Long sessions with high concurrent operational state will have large overlays. This is a substantive observation, not a defect. The architectural test is whether the additive overlay helps the LLM under realistic conditions."*

These two questions surface the constraint that observation predicted.

### Implications for downstream steps

- **Scoring track**: the 73 paired questions (where both A and B have answers) form the comparison set. Per-metric and aggregate rates will be computed over n=73 paired comparisons, not n=75. The audit makes this explicit.
- **Per-category breakdown**: q047 was `repeated_failure` and q061 was `validation_check`. The remaining paired pool: 14 validation_check, 14 repeated_failure, 15 approval_status, 15 completion_check, 15 readiness_check.
- **A-only baseline rates**: System A has all 75 answers, but only A-vs-B paired comparisons are statistically meaningful here. A's solo-rate over 75 is reported alongside the n=73 paired view.

---

## 6. Per-answer record schema

Every line in `answers_a.jsonl` and `answers_b.jsonl` carries:

```json
{
  "question_id":        "...",
  "system":             "A" | "B",
  "model_requested":    "gpt-4o-2024-08-06",
  "model_resolved":     "gpt-4o-2024-08-06",
  "system_fingerprint": "fp_xxxxxxxx",
  "temperature":        0.0,
  "top_p":              1.0,
  "max_output_tokens":  1500,
  "seed":               20260601,
  "prompt_hash":        "sha256(system + user)",
  "context_hash":       "sha256(grounding_payload)",
  "system_prompt_hash": "sha256(system_prompt)",
  "input_tokens":       int,
  "output_tokens":      int,
  "finish_reason":      "stop" | "length" | "context_too_long" | "api_error:RateLimitError" | ...,
  "answer_text":        "<verbatim model response>",
  "generated_at":       "ISO8601 UTC",
  "wall_seconds":       float,
  "retry_attempts":     int           // present only on successful records
}
```

Hashes let any reader prove the exact prompt and context that produced an answer without re-running. `prompt_hash` differs by question; `context_hash` differs by system. `system_prompt_hash` is constant across all records.

---

## 7. Methodological caveats

1. **Single-model generator**, locked. Same as Stack-Grounded — for cross-experiment comparability.
2. **Single-prompt template**, locked. No prompt iteration, no re-rolls.
3. **Permanent failures preserved**, not retried by adjusting design. The 2 failures stand as a v0.1 finding about overlay-size × org-tier × model interaction.
4. **n=73 paired comparison** for downstream scoring. The 2 missing System B answers cannot be filled in under the locked rules.
5. **TPM cap is account-specific.** A different OpenAI tier or a different model with looser per-request size limits could complete these. Under the locked v0.1 stack, they don't.

---

## 8. What's frozen at this step

- `generate_answers.py` — the script and its locked constants
- `data/answers_a.jsonl` — 75 System A answers (verbatim model output)
- `data/answers_b.jsonl` — 73 System B answers + 4 failure records (2 unique failures × 2 runs; resume logic dedupes by question_id)
- `data/answer_generation_audit.json` — locked-parameters audit + run summary + failure documentation

---

## 9. What's NOT done

- Deterministic scoring of the 75 + 73 answers — next step (§6 of pre-reg)
- Preference judging of paired answers — step after (§7 of pre-reg)
- Final report — depends on scoring + preference

---

## 10. How to reproduce

```bash
cd /path/to/repo
source venv/bin/activate
python operational_belief_v1/generate_answers.py
```

Inputs that must already exist:

- `operational_belief_v1/questions.jsonl`
- `operational_belief_v1/data/contexts_a.jsonl`
- `operational_belief_v1/data/contexts_b.jsonl`
- `.env` with `OPENAI_API_KEY`

The script is idempotent. Re-running on the same (question_id, system) skips already-completed records. The 2 known TPM failures will fail again under the same tier; they are stable v0.1 artifacts.

**Non-determinism caveat**: even with `temperature=0` and a fixed `seed`, OpenAI does not guarantee bit-identical outputs across `system_fingerprint` changes. Re-running may produce slightly different text on some questions if the routing pool changes. Per-answer fingerprints are recorded.

---

## 11. Audit trail

| Field | Value |
|---|---|
| Generation version | v0.1 |
| Locked | 2026-06-01 |
| Author | Susan Stranburg |
| Generator script | `generate_answers.py` |
| Companion pre-registration | [OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md](OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md) |
| Companion notes | [OPERATIONAL_BELIEF_SUBSTRATE_NOTES.md](OPERATIONAL_BELIEF_SUBSTRATE_NOTES.md) · [QUESTION_SET_CONSTRUCTION_NOTES.md](QUESTION_SET_CONSTRUCTION_NOTES.md) · [CONTEXT_CONSTRUCTION_NOTES.md](CONTEXT_CONSTRUCTION_NOTES.md) |
| Inputs read | `questions.jsonl`, `data/contexts_a.jsonl`, `data/contexts_b.jsonl` |
| Inputs NOT read | any judge artifact, any scorer output |
| Permanent failures | 2 (System B; q047 + q061 — both TPM cap violations on overlay-heavy questions) |
