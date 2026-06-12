# Answer Generation Notes — Stack-Grounded Retrieval v0.1

_Locked alongside [STACK_GROUNDED_PRE_REGISTRATION_v0.1.md](STACK_GROUNDED_PRE_REGISTRATION_v0.1.md), the question set, the substrate, and the contexts on 2026-05-31._

This document records the locked generation parameters and the run audit for Phase B step 3b. Both System A (chunk RAG) and System B (belief-state grounded) received the **identical** minimal prompt template against the **frozen** contexts in `contexts_a.jsonl` and `contexts_b.jsonl`. No judging, deterministic labeling, or comparative inspection was performed during generation.

---

## 1. Locked v0.1 generation parameters

| Parameter | Value | Notes |
|---|---|---|
| Model requested | `gpt-4o-2024-08-06` | OpenAI Chat Completions API, version-pinned for reproducibility |
| Model resolved (API echo) | `gpt-4o-2024-08-06` | 1 distinct value across all 150 generations |
| `system_fingerprint` (API echo) | 13 distinct values | Multiple compute pools served the run; normal at this scale. Recorded per-answer for audit. |
| Temperature | `0.0` | Greedy / quasi-deterministic |
| `top_p` | `1.0` | OpenAI default; not perturbed |
| `max_tokens` | `1500` | Output budget; finish_reason proves none truncated |
| `seed` | `20260531` | Deterministic seed; OpenAI does not guarantee bit-identical outputs across `system_fingerprint` changes but seed is honored within a fingerprint |
| Retry policy | exponential backoff (4s → 256s) + jitter, max 6 attempts | Triggered on `RateLimitError`, `APITimeoutError`, 5xx `APIStatusError` |

---

## 2. The locked prompt (identical for A and B)

**System prompt** (constant; hash `4cd185152eb5c43d…`):

```
You answer the user's question using only the information in the provided context. If the context does not support an answer, say so.
```

**User prompt template** (constant; payload differs by system):

```
CONTEXT:
{grounding_payload}

QUESTION:
{question}
```

Per pre-reg §5.1, both systems receive the same template. Only `{grounding_payload}` differs — System A passes the concatenated rendered chunks from `contexts_a.jsonl`, System B passes the concatenated rendered belief objects from `contexts_b.jsonl`. The `{question}` text comes from `questions.jsonl` and is identical across systems by `question_id`.

Per pre-reg §3.5 / §5.1, the prompt contains **no** instructions about caution, hedging, citation style, decline behavior, or warrant interpretation. The single conditional sentence — *"If the context does not support an answer, say so"* — is a baseline behavior expected of both systems and is not directional toward either substrate type. It applies equally to System A receiving an empty chunk pool and System B receiving an empty belief pool.

### 2.1 Zero-item context handling

12 System B contexts have 0 items (see [CONTEXT_CONSTRUCTION_NOTES.md §5](CONTEXT_CONSTRUCTION_NOTES.md)). The grounding payload for these is the literal sentinel `(no items)` — a single explicit phrase telling the model the context is empty, rather than a blank string. This avoids ambiguity between "no context provided" and "system error" and lets the model exercise its decline behavior cleanly.

System A had 0 zero-item contexts in v0.1.

---

## 3. Per-answer record schema

Every line in `answers_a.jsonl` and `answers_b.jsonl` carries:

```json
{
  "question_id":        "q017_change_detection_COHR_20260228",
  "system":             "A" | "B",
  "model_requested":    "gpt-4o-2024-08-06",
  "model_resolved":     "gpt-4o-2024-08-06",
  "system_fingerprint": "fp_xxxxxxxx",
  "temperature":        0.0,
  "top_p":              1.0,
  "max_output_tokens":  1500,
  "seed":               20260531,
  "prompt_hash":        "sha256(system + user)",
  "context_hash":       "sha256(grounding_payload)",
  "system_prompt_hash": "sha256(system_prompt)",
  "input_tokens":       int,
  "output_tokens":      int,
  "finish_reason":      "stop",
  "answer_text":        "<verbatim model response>",
  "generated_at":       "2026-05-31T…Z",
  "wall_seconds":       float,
  "retry_attempts":     int           // present only on successful records
}
```

Hashes let any reader prove the exact prompt and context that produced an answer without re-running. `prompt_hash` differs by question (the question text varies); `context_hash` differs by system; `system_prompt_hash` is constant across all 150 records.

---

## 4. Run audit

| Metric | System A | System B |
|---|--:|--:|
| Contexts in | 75 | 75 |
| Answers complete (`answer_text != ""`) | 75 | 75 |
| Missing | 0 | 0 |
| Distinct `model_resolved` | 1 | 1 |
| Distinct `finish_reason` | `stop` (75) | `stop` (75) |
| Input tokens (sum) | 528,604 | 210,319 |
| Output tokens (sum) | 13,533 | 5,077 |
| Output tokens mean | 180 | 68 |
| Output tokens max | 636 | 192 |

**Combined input tokens**: 738,923. **Combined output tokens**: 18,610.
**Estimated API cost** (gpt-4o pricing $2.50 / M input + $10 / M output): **$2.03**.

### 4.1 Reliability events during the run

| Event | Count |
|---|--:|
| First-attempt success | 144 |
| Retry-then-success (RateLimitError) | 6 (1 on A during the first run, 2 on A during the resumed run, 6 on B) |
| Permanent failure after retries | 0 |

Two of the rate-limit incidents during the first run (before retry-with-backoff was added) wrote failure records to `answers_a.jsonl` (`q033`, `q037`). The resume policy correctly identified them as incomplete (`answer_text == ""`), re-attempted them on the resumed run, and appended new success records. The historical failure records remain in the file as audit evidence; the dedup-by-`question_id` (success-wins) logic used by all downstream readers picks the success.

### 4.2 Token-budget asymmetry — by design

System B's input tokens are ~40% of System A's (210K vs 528K). This is because:

- System A packs near the 6000-token budget more often (53 / 75 contexts at-budget per [CONTEXT_CONSTRUCTION_NOTES.md §3.3](CONTEXT_CONSTRUCTION_NOTES.md)).
- System B's items are denser (belief objects are more compact than chunk renderings), and 12 contexts are empty.

The pre-reg §5.3 fairness constraint is **identical token budget** (both 6000), not identical actual input tokens. Equalizing item counts would be the wrong constraint — the unit of return is different by design. Equalizing the ceiling is the right one.

---

## 5. What this step deliberately did NOT do

- **No judging.** No preference comparison, no LLM-judge calls, no rubric application.
- **No deterministic labels.** The labeling protocol (pre-reg §6.3) is a separate step.
- **No comparative inspection.** The script never reads both answers for the same question in the same code path. It writes A, moves on; writes B, moves on.
- **No answer trimming or post-processing.** `answer_text` is the verbatim model response.
- **No prompt tuning.** The prompt was fixed before the first generation; no edits were made based on inspecting outputs.
- **No re-roll on "bad" outputs.** Whatever the model returned at temperature=0 with seed=20260531 is what got recorded. Re-runs only re-attempt API-error cases.
- **No comparative quality reading.** I have NOT read paired answers side-by-side. The mean output-token gap (180 vs 68) was noted only because the script emits it as an audit summary number; no inferences about quality have been drawn.

---

## 6. How to reproduce

```bash
cd /path/to/repo
source venv/bin/activate
python stack_grounded_v1/generate_answers.py
```

Inputs that must already exist:

- `stack_grounded_v1/questions.jsonl` (locked Phase B step 1)
- `stack_grounded_v1/data/contexts_a.jsonl` (locked Phase B step 3a)
- `stack_grounded_v1/data/contexts_b.jsonl` (locked Phase B step 3a)
- `.env` with `OPENAI_API_KEY`

The script is idempotent. Re-running with the same parameters on the existing output files will skip every `(question_id, system)` pair that already has a non-empty `answer_text` and only re-attempt failures. To regenerate from scratch, delete `answers_a.jsonl` and `answers_b.jsonl`.

**Non-determinism caveat**: even with `temperature=0` and a fixed `seed`, OpenAI does not guarantee bit-identical outputs across `system_fingerprint` changes. Re-running may produce slightly different text on some questions if the routing pool changes. The per-answer `system_fingerprint` is recorded so this is traceable. For v0.1 reporting purposes, the artifacts as written are the canonical run.

---

## 7. What's frozen at this step

- `generate_answers.py` — the script and its locked constants
- `answers_a.jsonl` — 75 System A answers (verbatim model output)
- `answers_b.jsonl` — 75 System B answers (verbatim model output)
- `answer_generation_audit.json` — the locked-parameters audit + run summary

---

## 8. What's NOT frozen (deferred to step 3c onward)

- Deterministic labeling rules (pre-reg §6.3)
- Judge model + version + prompt + calibration data (pre-reg §7.6)
- Aggregation method (pre-reg §7.4)
- Reporting structure (pre-reg §9)

The artifacts produced here are the input to those downstream steps. Once judges run, they read `answers_a.jsonl` and `answers_b.jsonl`; they do not re-call the generator.

---

## 9. Audit trail

| Field | Value |
|---|---|
| Generation version | v0.1 |
| Locked | 2026-05-31 |
| Author | Susan Stranburg |
| Generator script | `generate_answers.py` |
| Companion pre-registration | [STACK_GROUNDED_PRE_REGISTRATION_v0.1.md](STACK_GROUNDED_PRE_REGISTRATION_v0.1.md) |
| Companion notes | [QUESTION_SET_CONSTRUCTION_NOTES.md](QUESTION_SET_CONSTRUCTION_NOTES.md) · [SUBSTRATE_CONSTRUCTION_NOTES.md](SUBSTRATE_CONSTRUCTION_NOTES.md) · [CONTEXT_CONSTRUCTION_NOTES.md](CONTEXT_CONSTRUCTION_NOTES.md) |
| Inputs read | `questions.jsonl`, `data/contexts_a.jsonl`, `data/contexts_b.jsonl` |
| Inputs NOT read | any judge artifact, any label artifact, any prior answer of the *other* system (no peeking) |
