# Context Construction Notes — Stack-Grounded Retrieval v0.1

_Locked alongside [STACK_GROUNDED_PRE_REGISTRATION_v0.1.md](STACK_GROUNDED_PRE_REGISTRATION_v0.1.md), [QUESTION_SET_CONSTRUCTION_NOTES.md](QUESTION_SET_CONSTRUCTION_NOTES.md), and [SUBSTRATE_CONSTRUCTION_NOTES.md](SUBSTRATE_CONSTRUCTION_NOTES.md) on 2026-05-31._

This document records how the per-question grounding payloads for System A (chunk RAG) and System B (belief-state grounding) were assembled. It records every locked engineering parameter for the retrieval and ranking stages so that the answer-generation step is downstream of one auditable artifact pair: `contexts_a.jsonl` and `contexts_b.jsonl`.

---

## 1. What this step does (and does not do)

**Does:**
- For each of the 75 locked questions, builds one grounding payload per system that fits inside a locked equal token budget.
- Enforces the per-question `evidence_cutoff` architecturally — System A filters chunks by `timestamp ≤ T`, System B filters beliefs by `last_updated ≤ T` AND filters every belief's `evidence_refs` to chunks with `timestamp ≤ T`.
- Embeds the chunk substrate once via OpenAI's `text-embedding-3-small` and caches the matrix locally so subsequent runs are zero-cost.
- Writes paired per-question records into `contexts_a.jsonl` and `contexts_b.jsonl`. Each record carries `items[]` (the retrieved units), `rendered` strings (the exact text that will form the grounding payload), and per-context audit metadata (token counts, items-post-cutoff, items-truncated-for-budget).

**Does not:**
- Generate any answers (no LLM completions called, only embeddings for System A).
- Judge any output, run preference comparisons, or compute deterministic labels.
- Mutate either substrate. The chunk substrate and belief substrate produced in Phase B step 2 are read-only inputs here.

---

## 2. Locked engineering parameters (pre-reg §5.4)

| Parameter | System A | System B | Notes |
|---|---|---|---|
| Token budget | **6000** | **6000** | Identical per pre-reg §5.3. cl100k_base tokenizer. |
| Tokenizer | cl100k_base | cl100k_base | tiktoken; deterministic. |
| Embedding model | `text-embedding-3-small` | — | 1536-dim; OpenAI. One-time cost, locally cached. |
| Retrieval method | dense cosine similarity | rule-based (see §4) | Different by design — that's the experiment. |
| Pre-cutoff candidate pool | top-150 by similarity | actor matches + ≤50 theme-only matches | Cutoff is then applied; ranking and truncation follow. |
| Evidence-ref render | n/a | up to 5 sample chunk_ids per belief | Full ref list preserved in record for audit. |

The embedding cache lives at `stack_grounded_v1/data/chunk_embeddings.npz` (35,979 rows × 1536 dims, ~221 MB, gitignored). Re-runs hit the cache; only substrate changes trigger re-embedding.

---

## 3. System A — chunk RAG (control)

### 3.1 Procedure

1. Load chunks. Build (or reuse) an L2-normalized 1536-dim embedding for every chunk's `title + text`.
2. For each question, embed the question text (one OpenAI call per question, 75 total).
3. Compute cosine similarity against the full chunk matrix. Take the top-150 chunks by similarity (this gives a generous pool so the cutoff filter doesn't starve us).
4. Filter the top-150 to chunks with `timestamp[:10] ≤ evidence_cutoff` (architectural cutoff, pre-reg §5.2).
5. Walk the surviving chunks in similarity order; pack each chunk's rendered form into the context until the next chunk would exceed the 6000-token budget. Skip oversized items (do not break) so smaller relevant chunks downstream still have a chance.
6. Emit one record per question with the items, their renderings, and per-item token counts.

### 3.2 Render format

```
[chunk_id @ YYYY-MM-DD / source] "Title text"
  actors: TICKER1, TICKER2
  body: <text body if present>
```

No retrieval scores or warrant fields are surfaced to the LLM — System A is purely chunks-and-attribution, matching pre-reg §3.1.

### 3.3 Validation results

| Constraint | Result |
|---|---|
| Contexts emitted | 75 / 75 |
| Cutoff violations (`chunk.timestamp > cutoff`) | 0 |
| Contexts exceeding token budget | 0 |
| Zero-item contexts | 0 |

| Per-context stats | min | mean | max |
|---|--:|--:|--:|
| Tokens | 623 | 5,078 | 6,000 |
| Items | 7 | 46.7 | 67 |
| Items post-cutoff (pre-truncation) | 7 | 65.4 | 150 |

- **53 / 75 contexts** are at-budget (≥ 90% of 6000); **12 / 75** are under-budget (< 50%), driven by either thin substrate coverage of the question's actor at the cutoff (insufficient_warrant questions on ZETA, COHR, SOFI, etc. at 2026-01-31) or by similarity scores dropping off after the top relevant chunks.

---

## 4. System B — belief-state grounding (experimental)

### 4.1 Procedure

1. Index beliefs by `actor` and `theme` (stable_cluster_id).
2. For each question:
   - **Actor pool**: all beliefs where `belief.actor == question.ticker`.
   - **Theme pool**: all beliefs whose `theme` matches any theme present in the actor pool, excluding beliefs already in the actor pool. Capped at 50 to prevent flooding.
3. Apply cutoff to both pools:
   - Drop beliefs with `last_updated > T`.
   - For surviving beliefs, filter `evidence_refs` and `counterevidence_refs` to chunk_ids whose chunk has `timestamp ≤ T`.
   - Recompute `source_mix` from the filtered evidence_refs.
4. Rank by the ranking rules below.
5. Pack into the same 6000-token budget; skip oversized items.

### 4.2 Ranking rules (locked, documented before answer generation)

| Rank key | Rule |
|---|---|
| 1. Match type | `actor_match > theme_only` |
| 2. Coverage status | `IN_DISTRIBUTION > PARTIAL > OUT_OF_DISTRIBUTION` |
| 3. Lifecycle state | Non-retired > retired, **EXCEPT** when `question.category == 'stale_assumption'` where retired beliefs are the target — they get the boost instead |
| 4. Recency | Larger `last_updated` (closer to cutoff) ranks higher |
| 5. Warrant strength | `support_n × confidence`, descending |

Encoded in `rank_score()` as a tuple sort. Deterministic; reproducible.

### 4.3 Render format

```
BELIEF [belief_id] ACTOR (theme=theme-xxxxxx) — "Claim text"
  warrant: COVERAGE_STATUS (confidence=0.NN, support_n=N)
  state:   lifecycle_state (first_seen YYYY-MM-DD, last_updated YYYY-MM-DD)
  sources: source1:N, source2:N, ...
  evidence_refs (N): chunk_id_1, chunk_id_2, ... (+M more)
  counterevidence (M): chunk_id_1, ... (+K more)
```

No `answer_guidance`, `prompt_hint`, `caution_note`, or any instruction-shaped text appears anywhere in the render or the items records. Pre-reg §3.5 schema discipline carries through to the rendered grounding payload.

### 4.4 Validation results

| Constraint | Result |
|---|---|
| Contexts emitted | 75 / 75 |
| Belief cutoff violations (`last_updated > cutoff`) | 0 |
| Evidence-ref cutoff violations (`chunk.timestamp > cutoff`) | 0 |
| Contexts exceeding token budget | 0 |
| Zero-item contexts | **12** (see §5 — honest substrate signal, not a bug) |

| Per-context stats | min | mean | max |
|---|--:|--:|--:|
| Tokens | 0 | 4,752 | 5,999 |
| Items | 0 | 28.1 | 47 |
| Actor-match pool size | 3 | 51.8 | 90 |
| Theme-only pool size (post-cap) | 31 | 49.0 | 50 |

| Match-type contribution (across all 2,105 ranked items) | Count |
|---|--:|
| actor_match | 1,908 (90.6%) |
| theme_only | 197 (9.4%) |

Theme expansion contributes meaningfully but does not dominate — direct actor matches still carry most of System B's payload.

---

## 5. The 12 zero-item System B contexts

System B returns no items for 12 questions. Distribution:

| Category | Count | Tickers |
|---|--:|---|
| insufficient_warrant | 5 | MELI, CLS, SOFI, COHR, ZETA |
| change_detection | 5 | COHR, SNDK, WDC, MELI, SOFI |
| stale_assumption | 2 | CLS, SNDK |

These are not builder defects. They are honest substrate signals: thin-coverage actors whose pipeline-maintained beliefs were not yet born at the question's cutoff. Verification example for `q017_change_detection_COHR_20260228`:

- COHR has 4 total beliefs in the substrate; earliest `last_updated` is `2026-05-20`.
- Theme expansion brings 40 cross-actor candidates; earliest `last_updated` is `2026-05-19`.
- Cutoff `2026-02-28` survives 0 beliefs from either pool.

This is exactly the asymmetry the experiment is designed to expose:

- **For `insufficient_warrant` questions**, the empty payload is *desired* — System B should decline because no maintained belief exists. The question is whether the LLM, seeing an empty context, declines cleanly versus synthesizing from training-priors.
- **For `change_detection` and `stale_assumption` questions on thin-coverage actors**, the empty payload is the substrate honestly saying "the pipeline didn't maintain a belief here yet." System A has 13-67 chunks for the same questions and may over-claim from them. Comparing the two answers is the entire point.

The audit records these explicitly so the v0.1 report can analyze whether decline behavior tracks with empty payloads.

---

## 6. Cross-substrate cutoff compliance (the load-bearing invariant)

| Check | Total | Violations |
|---|--:|--:|
| System A items with `chunk.timestamp > cutoff` | 3,499 | **0** |
| System B items with `belief.last_updated > cutoff` | 2,105 | **0** |
| System B `evidence_refs` whose chunk has `timestamp > cutoff` | 36,481 | **0** |

Both systems honor pre-reg §5.2 architecturally: filtering happens before ranking, not after.

---

## 7. What's frozen at this step

- `build_chunk_context.py` — System A retrieval + render logic.
- `build_belief_context.py` — System B retrieval + ranking + render logic.
- `contexts_a.jsonl` — 75 System A grounding payloads, rendered.
- `contexts_b.jsonl` — 75 System B grounding payloads, rendered.
- `chunk_embeddings.npz` — embedding cache (regenerable from the same model + chunks).
- `context_a_audit.json`, `context_b_audit.json`, `context_construction_audit.json` — per-system + combined audit summaries.

All engineering parameters (embedding model, token budget, tokenizer, theme cap, pre-cutoff pool size, ranking rules) are locked here. Re-runs are deterministic; the only non-deterministic source (OpenAI embedding) is captured in the .npz cache.

## 8. What's not frozen (deferred to step 3b / 3c)

- Generation model + version + temperature + seed (System A and System B prompts share a template per §5.1; this is the next lock).
- Judge model + version + prompt + calibration data (per pre-reg §7.6).
- Deterministic-label rule set (per pre-reg §6.3).

---

## 9. How to reproduce

```bash
cd /path/to/repo
source venv/bin/activate

# First run embeds the chunk substrate (~$0.14, ~2 min on a fast network)
python stack_grounded_v1/build_chunk_context.py

# Subsequent runs reuse stack_grounded_v1/data/chunk_embeddings.npz
python stack_grounded_v1/build_belief_context.py
```

Outputs:

- `stack_grounded_v1/data/contexts_a.jsonl`
- `stack_grounded_v1/data/contexts_b.jsonl`
- `stack_grounded_v1/data/chunk_embeddings.npz`
- `stack_grounded_v1/data/context_a_audit.json`
- `stack_grounded_v1/data/context_b_audit.json`
- `stack_grounded_v1/data/context_construction_audit.json`

Inputs that must already exist:

- `stack_grounded_v1/questions.jsonl` (locked Phase B step 1)
- `stack_grounded_v1/data/chunk_substrate.jsonl` (locked Phase B step 2)
- `stack_grounded_v1/data/belief_objects.jsonl` (locked Phase B step 2)
- `.env` with `OPENAI_API_KEY` (only needed for the one-time embedding pass)

Both context files are gitignored at the repo level (the research repo's global `data/` ignore). Reproduction from scripts + tracked artifacts is the audit path.

---

## 10. Audit trail

| Field | Value |
|---|---|
| Context version | v0.1 |
| Locked | 2026-05-31 |
| Author | Susan Stranburg |
| Chunk builder | `build_chunk_context.py` |
| Belief builder | `build_belief_context.py` |
| Companion pre-registration | [STACK_GROUNDED_PRE_REGISTRATION_v0.1.md](STACK_GROUNDED_PRE_REGISTRATION_v0.1.md) (locked 2026-05-31) |
| Companion question-set notes | [QUESTION_SET_CONSTRUCTION_NOTES.md](QUESTION_SET_CONSTRUCTION_NOTES.md) (locked 2026-05-31) |
| Companion substrate notes | [SUBSTRATE_CONSTRUCTION_NOTES.md](SUBSTRATE_CONSTRUCTION_NOTES.md) (locked 2026-05-31) |
| Inputs read (System A) | `questions.jsonl`, `data/chunk_substrate.jsonl`, OpenAI embedding API |
| Inputs read (System B) | `questions.jsonl`, `data/belief_objects.jsonl`, `data/chunk_substrate.jsonl` |
| Inputs NOT read | any answer artifact, any judge artifact, the LLM generation API |
