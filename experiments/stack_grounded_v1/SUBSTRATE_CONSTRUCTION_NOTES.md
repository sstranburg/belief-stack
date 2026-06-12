# Substrate Construction Notes — Stack-Grounded Retrieval v0.1

_Locked alongside [STACK_GROUNDED_PRE_REGISTRATION_v0.1.md](STACK_GROUNDED_PRE_REGISTRATION_v0.1.md) and [QUESTION_SET_CONSTRUCTION_NOTES.md](QUESTION_SET_CONSTRUCTION_NOTES.md) on 2026-05-31._

This document records how the two substrates — `chunk_substrate.jsonl` (System A payload) and `belief_objects.jsonl` (System B payload) — were constructed. It exists so any reader can reproduce the construction, verify schema compliance with pre-reg §3.4 / §3.5, and audit how each belief field was derived from TopicSpace pipeline outputs.

---

## 1. Substrate-construction discipline (what each script may read)

### System A — chunk substrate

`build_chunk_substrate.py` reads **only the raw L0 evidence stream**:

- `data/normalized/tech_ecosystem.jsonl`

No belief artifact (`expectation_entities`, `lifecycle_events`, `narrative_pressure`, `actors.json`, etc.) is consulted. The chunk substrate is a flat per-event projection with timestamps preserved for cutoff filtering.

### System B — belief substrate

`build_belief_substrate.py` reads existing TopicSpace pipeline outputs and projects them into the locked belief object schema:

- `data/derived/expectation_entities.parquet` — primary belief atoms (entity_id, ticker, conviction, support, status, headline)
- `data/derived/expectation_lifecycle_events.parquet` — per-entity lifecycle history (born / reconfirmed / weakened / contradicted / retired)
- `data/derived/narrative_pressure.jsonl` — referenced for inputs documentation; not currently joined into belief objects in v0.1 (no direct entity_id ↔ storm_id link available)
- `data/normalized/tech_ecosystem.jsonl` — joined for evidence_refs linkage so that System B's evidence pointers resolve to the same chunk identifiers System A uses

**Why this matters:** the experiment compares two systems that share an L0 substrate. System B's "extra" is L1 warranted organization + L2 belief return derived from the *existing* pipeline. The substrate construction must not invent new belief signal beyond what the pipeline already maintains — otherwise the v0.1 comparison becomes "L0 chunks vs L0+L1+L2+novel-construction", which doesn't isolate the architectural pattern.

---

## 2. Chunk substrate construction

### 2.1 Inputs and filters

- Input: `data/normalized/tech_ecosystem.jsonl` (59,261 events)
- Window filter: `2025-12-05 ≤ timestamp ≤ 2026-05-26` (pre-reg §2.2, matches the v1.5 173-day window)
- Actor filter: at least one event actor must be in the 39-ticker primary universe (pre-reg §2.1)
- Identifier filter: event must have a non-null `event_id`; duplicates by id are dropped

### 2.2 Schema

```json
{
  "chunk_id":        "string",   // = source event_id (preserves cross-substrate linkage)
  "timestamp":       "ISO8601",  // full timestamp; cutoff filter uses timestamp[:10]
  "source":          "string",   // finnhub | newsapi | reddit | amplification | x | sec | transcript
  "title":           "string",
  "text":            "string",   // may be empty for headline-only events
  "actors":          ["TICKER", ...],          // full actor list from the source event
  "actors_primary":  ["TICKER", ...],          // intersection with the 39-ticker universe
  "tags":            ["tag", ...],
  "url":             "string",
  "reliability":     0.0 - 1.0   // source-prior, NOT presented in retrieval prompt
}
```

### 2.3 Validation results

| Constraint | Target | Actual |
|---|---|---|
| Chunks emitted | — | 35,979 |
| Unique chunk_ids | = chunks emitted | 35,979 (0 duplicates) |
| Window compliance | all in [2025-12-05, 2026-05-26] | 0 violations |
| Actor coverage | ≥ 1 per primary actor | 39 / 39 |
| Empty titles | — | 0 |
| Empty text bodies | — | 1,782 (headline-only events, normal for finnhub) |

**Source breakdown** (locked):

| Source | Chunks |
|---|--:|
| finnhub | 32,254 |
| reddit | 1,767 |
| amplification | 1,270 |
| newsapi | 348 |
| x | 182 |
| sec | 100 |
| transcript | 58 |

**Month spread**:

| Month | Chunks |
|---|--:|
| 2025-12 | 1,923 |
| 2026-01 | 1,961 |
| 2026-02 | 2,524 |
| 2026-03 | 8,649 |
| 2026-04 | 12,081 |
| 2026-05 | 8,841 |

Cumulative shape is dominated by finnhub (~90%) and skews toward later months because pipeline ingestion volume grew. Both substrates inherit this skew; the question set's cutoff distribution (per QUESTION_SET_CONSTRUCTION_NOTES.md §3) provides a counterweight by spreading cutoffs across the window.

---

## 3. Belief substrate construction

### 3.1 Locked schema (pre-reg §3.4)

```json
{
  "belief_id":            "string",
  "actor":                "string",
  "theme":                "string",
  "claim":                "string",
  "coverage_status":      "IN_DISTRIBUTION" | "OUT_OF_DISTRIBUTION" | "PARTIAL",
  "confidence":           "float",    // 0.0–1.0
  "support_n":            "integer",
  "lifecycle_state":      "born" | "active" | "reconfirmed" | "weakened" | "contradicted" | "retired",
  "evidence_refs":        ["chunk_id", ...],
  "counterevidence_refs": ["chunk_id", ...],
  "source_mix":           {"finnhub": n, "reddit": n, ...},
  "last_updated":         "YYYY-MM-DD",
  "first_seen":           "YYYY-MM-DD"
}
```

Per pre-reg §3.5, no `answer_guidance`, `prompt_hint`, `caution_note`, or other instruction-shaped field appears. The script asserts this in the audit (`schema_compliance.forbidden_fields_present`).

### 3.2 Field-by-field derivation

| Schema field | Source | Derivation |
|---|---|---|
| `belief_id` | `expectation_entities.entity_id` | Used directly |
| `actor` | `expectation_entities.ticker` | Used directly; non-primary tickers (USAR/MP/ODC) skipped |
| `theme` | `expectation_entities.stable_cluster_id` | Used directly (carries the cross-actor narrative cluster id) |
| `claim` | `expectation_entities.last_headline` | Trimmed; entities with empty headline are skipped |
| `confidence` | `expectation_entities.last_conviction` | Used directly — the pipeline already emits values in `[0.4, 0.85]`, inside `[0, 1]` as the schema requires. No additional aggregation. This is one of the two valid choices noted in pre-reg §3.4 ("aggregation function is constructed in build_belief_substrate.py"); the choice here is the simpler "use the pipeline's own conviction estimate." |
| `support_n` | `expectation_entities.n_versions` | Used directly — counts how many times the pipeline observed/revised the belief |
| `lifecycle_state` | `expectation_lifecycle_events` joined on `entity_id` | Most recent (max date) lifecycle event's `event_type`. Non-schema event types are remapped: `strengthened → reconfirmed` (positive revision → closest enum slot). Entities with no lifecycle events fall back to `expectation_entities.status` (defaulting to `active`). |
| `evidence_refs` | `tech_ecosystem.jsonl` joined on actor + date window | Events whose `actors` contain `entity.ticker` AND whose timestamp falls in `[entity.first_seen − 7d, entity.last_seen]`. Capped at 50 per belief (most recent kept). The asymmetric 7-day backward lookback reflects the pipeline's 'born' events being driven by accumulated pressure from preceding days, not single-day mentions — without this lookback, ~19% of short-lived `support_n=1` beliefs had empty evidence_refs even though the pipeline had warranted them. Never looks past `last_seen` (cutoff discipline preserved). |
| `counterevidence_refs` | `tech_ecosystem.jsonl` near contradicted/weakened lifecycle events | For each lifecycle event with `event_type ∈ {contradicted, weakened}`, take events in `[event.date − 3d, event.date + 3d]` whose actors contain `entity.ticker`. Sorted, deduped. Empty when the belief has no contradiction/weakening lifecycle events. |
| `source_mix` | Counter over `evidence_refs` | Counts of source values across the evidence chunks |
| `last_updated` | max of lifecycle event dates | Falls back to `entity.last_seen`. Clamped to `window_end = 2026-05-26` for v0.1 (no belief carries a last_updated past the window). |
| `first_seen` | `expectation_entities.first_seen` | Used directly |
| `coverage_status` | Derived | Decoupled from `lifecycle_state` (currency lives there). Rule: `IN_DISTRIBUTION` if `support_n ≥ 3 AND len(evidence_refs) ≥ 5`; `OUT_OF_DISTRIBUTION` if `support_n ≤ 1 AND len(evidence_refs) ≤ 2`; `PARTIAL` otherwise. A well-warranted retired belief is still IN_DIST — historical coverage is coverage. OUT_OF_DISTRIBUTION marks thin beliefs the LLM should decline on rather than synthesize from. |

### 3.3 Construction parameters (locked at v0.1)

| Parameter | Value | Notes |
|---|---|---|
| `EVIDENCE_REF_CAP` | 50 | Max evidence_refs per belief; the most recent are kept |
| `EVIDENCE_LOOKBACK_DAYS` | 7 | Backward-only lookback before `first_seen` |
| `COUNTER_WINDOW_DAYS` | 3 | ± window around contradicted/weakened lifecycle events |
| Coverage thresholds | `IN_DIST: support_n≥3 ∧ ev_refs≥5; OOD: support_n≤1 ∧ ev_refs≤2` | Decoupled from lifecycle_state |
| `LIFECYCLE_REMAP` | `{"strengthened": "reconfirmed"}` | Non-schema event_types mapped to closest enum slot |

### 3.4 Validation results

| Constraint | Target | Actual |
|---|---|---|
| Belief objects emitted | — | 2,031 |
| Schema-required fields present | all 13 | 13 / 13 on every record |
| Forbidden instruction fields | 0 | 0 ✓ |
| Actor coverage | ≥ 1 per primary actor | 39 / 39 |
| Beliefs with `last_updated > window_end` | 0 | 0 (clamped) |
| All `evidence_refs` resolve in chunk substrate | 100% | 58,843 / 58,843 (0 unresolved) |
| All `counterevidence_refs` resolve in chunk substrate | 100% | 17,643 / 17,643 (0 unresolved) |

**Coverage status distribution**:

| Status | Beliefs | Share |
|---|--:|--:|
| IN_DISTRIBUTION | 319 | 15.7% |
| PARTIAL | 1,532 | 75.4% |
| OUT_OF_DISTRIBUTION | 180 | 8.9% |

**Lifecycle state distribution**:

| State | Beliefs | Share |
|---|--:|--:|
| retired | 1,909 | 94.0% |
| born | 92 | 4.5% |
| contradicted | 22 | 1.1% |
| reconfirmed | 7 | 0.3% |
| weakened | 1 | < 0.1% |

The heavy retired skew matches the underlying pipeline's behavior — most narrative atoms cycle in and out of attention as the field evolves; the snapshot at any cutoff captures the long tail of historical beliefs. This is by design, not a defect, and is what gives System B its historical-coverage advantage at non-current cutoffs.

**Confidence distribution**: min 0.400 / mean 0.675 / max 0.850 — inherited from the pipeline's conviction values; no normalization needed.

**Evidence ref distribution**: min 0 / mean 29.0 / max 50 (cap). 135 beliefs (6.6%) still have 0 evidence_refs after the 7-day backward lookback. These are beliefs where the underlying entity exists but no events matching `actors ⊇ {ticker}` fall in the lookback+entity window — typically very thin or theme-driven attributions. They are marked OUT_OF_DISTRIBUTION by the coverage rule and the LLM should decline on them.

**Counterevidence**: 202 beliefs (9.9%) carry at least one counterevidence_ref, all stemming from contradicted/weakened lifecycle events in the window.

### 3.5 Exclusions (recorded in audit)

| Reason | Count |
|---|--:|
| Entity ticker not in primary universe (USAR / MP / ODC) | 69 |
| `first_seen > window_end` | 0 |
| Empty `last_headline` | 0 |

---

## 4. Cutoff compatibility (pre-reg §5.2)

Per pre-reg §5.2, for each question with `evidence_cutoff = T`:

- **System A**: chunk substrate is filtered to `chunk.timestamp ≤ T` at query time.
- **System B**: belief substrate is filtered to `belief.last_updated ≤ T` AND every belief's `evidence_refs` is filtered to chunks with `timestamp ≤ T` at query time.

Both substrates as built support this:

- Every chunk carries a `timestamp`.
- Every belief carries `first_seen`, `last_updated`, and `evidence_refs` whose entries are chunk_ids in the chunk substrate. The context builder (later Phase B step) joins on chunk_id to apply the cutoff. Beliefs whose `last_updated > T` are excluded entirely; otherwise the evidence list is filtered.

No belief or chunk in the substrates carries a date later than the locked window end (2026-05-26). Confirmed in the cross-substrate sanity check (`Beliefs with last_updated > window_end: 0; Chunks with timestamp > window_end: 0`).

The substrate builders themselves do **not** pre-filter by question cutoff. They emit the full as-of-window substrate so the same substrate file can serve every question.

---

## 5. What was deliberately NOT done

- **No belief object was hand-edited.** The 2,031 beliefs are exactly what `build_belief_substrate.py` produced.
- **No new belief signal was invented.** Every field is either lifted directly from a pipeline output, derived from the pipeline outputs via the rules in §3.2, or is structural metadata (lookups, counts). The script does not call any LLM, embedding model, or external service.
- **No `answer_guidance` / `prompt_hint` / `caution_note` field is present.** Schema compliance asserts this on every record.
- **No System A / System B context assembly was performed.** Context builders are a later Phase B step (not in scope here).
- **No answers were generated.** No retrieval, no prompts, no judging. The substrates are inert artifacts ready for context assembly.
- **No labeling protocol was applied.** Deterministic labeling and judge calibration are later Phase B steps.
- **No question was consulted.** The substrates are constructed once and serve all 75 questions; the question set is not loaded by either builder.

---

## 6. How to reproduce

```bash
cd /path/to/repo
source venv/bin/activate
python stack_grounded_v1/build_chunk_substrate.py
python stack_grounded_v1/build_belief_substrate.py
```

Both scripts are deterministic. Re-running produces:

- `stack_grounded_v1/data/chunk_substrate.jsonl` (35,979 chunks)
- `stack_grounded_v1/data/chunk_substrate_audit.json`
- `stack_grounded_v1/data/belief_objects.jsonl` (2,031 belief objects)
- `stack_grounded_v1/data/belief_substrate_audit.json`

Inputs that must exist (all already present in the research repo):

| Path | Used by | Purpose |
|---|---|---|
| `data/normalized/tech_ecosystem.jsonl` | both builders | L0 evidence stream |
| `data/derived/expectation_entities.parquet` | belief builder | belief atoms |
| `data/derived/expectation_lifecycle_events.parquet` | belief builder | lifecycle states + counterevidence anchors |
| `data/derived/narrative_pressure.jsonl` | (documented input; not joined in v0.1) | reserved for v0.2 |

The substrate files are gitignored at the repo level (the research repo's global `data/` ignore rule). Reproduction from scripts + tracked research-pipeline outputs is the audit path.

---

## 7. What's frozen and what's not

**Frozen as of 2026-05-31:**

- The 2,031 belief objects (schema, field derivations, construction parameters)
- The 35,979 chunks (schema, window, actor filter)
- The construction scripts and the audit JSONs
- The pre-registration parameters above
- The cross-substrate join key (`chunk_id` = `event_id` = `evidence_refs[i]`)

**Not frozen yet** (per pre-reg §5.4, locked at first-run time):

- The retrieval embedding model + version (System A)
- Top-K (System A)
- Token budget per system
- Context assembly logic (which beliefs / which chunks are presented when)
- Generation model + version, temperature, seed
- Judge model + version + prompt

These belong to the *run*, not the substrate, and are deliberately deferred to the run-time lock step.

---

## 8. Audit trail

| Field | Value |
|---|---|
| Substrate version | v0.1 |
| Locked | 2026-05-31 |
| Author | Susan Stranburg |
| Chunk builder | `build_chunk_substrate.py` |
| Belief builder | `build_belief_substrate.py` |
| Companion pre-registration | [STACK_GROUNDED_PRE_REGISTRATION_v0.1.md](STACK_GROUNDED_PRE_REGISTRATION_v0.1.md) (locked 2026-05-31) |
| Companion question-set notes | [QUESTION_SET_CONSTRUCTION_NOTES.md](QUESTION_SET_CONSTRUCTION_NOTES.md) (locked 2026-05-31) |
| Inputs read (chunk) | `data/normalized/tech_ecosystem.jsonl` |
| Inputs read (belief) | `data/derived/expectation_entities.parquet`, `data/derived/expectation_lifecycle_events.parquet`, `data/normalized/tech_ecosystem.jsonl` |
| Inputs NOT read | any answer artifact, any judge artifact, the question set itself |
