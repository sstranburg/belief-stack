# Stack-Grounded Retrieval — Pre-registration (v0.1)

This is the v0.1 pre-registration for a paired-comparison experiment testing whether maintained belief-state knowledge sources produce better LLM answers than chunk-grounded RAG over the same evidence substrate. It is the first proof-point case study for the **Stack-grounded intelligence** usage pattern named in [`research/belief-stack`](https://topicspace.ai/research/belief-stack).

Locked 2026-05-31.

---

## 0. Why this document exists

The Belief Stack spec (v0.1) names three usage patterns: Sensemaking (proof point: sensemaking-v1), Reasoning-trace state management (proof point: tkos-log-replay-v1), and **Stack-grounded intelligence** (currently marked *case study pending*). This pre-registration is the gating step for that pending case study.

The narrow claim being tested:

> Holding the same L0 evidence substrate constant, adding L1 warranted organization and L2 belief return produces measurably different LLM answers than L0-only chunk retrieval, on a set of pre-registered intel-style queries.

If true under locked rules, this is the first measured proof that belief-state knowledge sources are a distinct category hypothesis from chunk-based RAG. If false, the architectural claim weakens and the spec's positioning needs revision. Either outcome is publishable under the v0.x discipline.

---

## 1. Success criterion

The v0.1 measurement has a **primary deterministic gate** and a **secondary preference measurement**, reported separately. Preference cannot rescue failure on deterministic grounding.

**Primary deterministic hypothesis (the gate):**
> System B (L0 + L1 + L2 belief-state grounded) will produce a lower stale-claim error rate than System A (L0-only chunk-grounded), with measurably fewer unsupported-claim, contradiction-omission, and insufficient-warrant-overclaim errors, under architectural evidence-cutoff enforcement.

**Secondary preference hypothesis:**
> System B will be preferred over System A on blind pairwise judging across three axes: appropriate caution, traceability usefulness, and sensemaking usefulness.

The two tracks are reported **separately**. Per the locked discipline:

> Preference is not correctness. Correctness is not preference. Divergence between deterministic and preference results is reported as a finding, not averaged away.

**Why deterministic is the gate:** if System B's answers cite contradicted evidence, overclaim on insufficient warrant, or violate evidence boundaries at a higher rate than System A, the architectural claim is invalidated regardless of how favorably the answers are judged. Preference can validate the architectural claim only when grounding correctness holds; preference cannot substitute for it.

Per v1.5 §1.1 (preserved): calibrated reporting, not pass/fail. No pre-committed significance threshold. The four-quadrant outcome space (both confirmed, deterministic only, preference only, both flat) is built into the design; each outcome is publishable, but a "preference only" result is reported as "preferred but less accurate," not as a win.

---

## 2. Substrate

### 2.1 Evidence corpus

The AI ecosystem intel corpus already maintained by the TopicSpace pipeline:

- **Primary evidence stream**: `data/normalized/tech_ecosystem.jsonl` and per-ticker derived files (events, narrative pressure, lifecycle).
- **Source mix**: news (NewsAPI, Finnhub validation tier), filings, transcripts, amplification tier, Reddit, X. Source-reliability priors are already encoded in the pipeline.
- **Ticker universe**: the 31 primary tickers used in `sensemaking-v1.5` (matching that case study's universe; experimental tickers USAR/MP/ODC excluded).

### 2.2 Date window

- **Evidence accumulation period**: 2025-12-05 → 2026-05-26 (matches v1.5 window — the substrate is what the pipeline maintained over those 173 days).
- **Per-question evidence cutoff**: each question carries its own `evidence_cutoff` date. Both systems' substrates are filtered architecturally to evidence ≤ cutoff before query time (see §5.2).

### 2.3 Substrate-construction caveat (explicit)

This experiment compares two access paths over the same evidence substrate: L0-only chunk retrieval versus maintained L1/L2 belief-state access. The belief field is the result of running L1/L2 processing as evidence accumulated over time. **The experiment is not a real-time competition between two equally-naive systems.**

Stated plainly:

> System A receives L0-only retrieved chunks.
> System B receives L1/L2 belief objects produced by maintained processing over the same L0 evidence substrate.
> The processing advantage is the architectural claim being tested, not a confound to hide.

This is not an unfair advantage; it is the architectural claim under test. Pretending the comparison is real-time would understate what's being measured. Pretending it isn't there would be intellectually dishonest.

---

## 3. Systems under test

### 3.1 System A — chunk-grounded RAG (control)

```
query → embed → retrieve top-K L0 evidence chunks (≤ cutoff)
      → assemble context → LLM answer
```

- Retrieval over the raw L0 evidence stream chunked at ingest.
- Embedding model: locked at §5.4.
- Top-K: locked at §5.4.
- No L1 / L2 / L3 access of any kind.

### 3.2 System B — L0 + L1 + L2 belief-state grounded (experimental)

```
query → resolve relevant L1 region(s) / coverage status (≤ cutoff)
      → return L2 belief objects with warrants (≤ cutoff)
      → assemble context → LLM answer
```

- L1 coverage gating: query may resolve to a covered region, multiple covered regions, or OUT_OF_DISTRIBUTION.
- L2 belief objects returned as structured records (schema in §3.4).
- No `answer_guidance` field; no instructions to the LLM baked into the payload (see §3.5).

### 3.3 What's NOT in v0.1

- **No System C with L3 lifecycle as primary test.** The `lifecycle_state` field appears in the belief object schema because the underlying TopicSpace pipeline already emits it as existing substrate metadata. v0.1 does NOT separately ablate it, isolate its contribution, or treat L3 as the primary architectural test. The primary test in v0.1 is L0-only vs L0+L1+L2; the v0.2 candidate is a dedicated L3-contribution measurement that isolates the lifecycle layer's effect.
- **No L4 calibration scoring** as a system input. (L4 is a separate measurement of the substrate, not part of the access path being tested.)
- **No GOV layer.** Both systems serve answers without intervention gating. GOV is downstream of this experiment per the spec's optional/downstream framing.

### 3.4 Belief object schema (System B payload)

Each belief object returned to System B carries **only structured state** — no instructions:

```json
{
  "belief_id":            "string",
  "actor":                "string",   // ticker OR theme identifier
  "theme":                "string",   // optional cross-actor narrative theme
  "claim":                "string",
  "coverage_status":      "IN_DISTRIBUTION" | "OUT_OF_DISTRIBUTION" | "PARTIAL",
  "confidence":           "float",    // 0.0–1.0 warrant strength
  "support_n":            "integer",
  "lifecycle_state":      "born" | "active" | "reconfirmed" | "weakened" | "contradicted" | "retired",
  "evidence_refs":        ["ev_id", ...],
  "counterevidence_refs": ["ev_id", ...],
  "source_mix":           {"newsapi": n, "finnhub": n, "x": n, ...},
  "last_updated":         "YYYY-MM-DD",
  "first_seen":           "YYYY-MM-DD"
}
```

**Notes on specific fields:**

- `actor` / `theme`: a belief can be about a single actor (typically a ticker) or a cross-actor theme (e.g., "AI infrastructure capacity narrative"). At least one must be populated.
- `confidence`: **numeric warrant metadata** in the range 0.0–1.0, aggregated from the underlying pipeline's pressure / sufficient_data / source-mix scoring. It is a structured field, not a prompt-shaped instruction. The LLM may infer caution from a low confidence value; it is not told to do so. The exact aggregation function is constructed in `build_belief_substrate.py` (see §11) and is documented in the v0.1 report's methodology section so any reader can reproduce how a belief object's `confidence` was derived from underlying pipeline outputs.
- `lifecycle_state`: **existing substrate metadata only in v0.1.** Included because the underlying TopicSpace pipeline already emits it as part of the belief field's natural state; not separately ablated and not treated as the primary L3 test. A dedicated L3-contribution measurement (one that isolates lifecycle's effect against an L0+L1+L2-but-no-L3 variant) is a v0.2 candidate. v0.1 results may not be cited as evidence about L3's contribution either way.
- No `answer_guidance`, `prompt_hint`, `caution_note`, or any other instructional field (per §3.5).

### 3.5 No answer_guidance field

A belief object MUST NOT contain instructional fields like `answer_guidance`, `prompt_hint`, `caution_note`, or any other field whose value is shaped to be read by the LLM as direction. The LLM must derive caution, contradiction handling, and qualifying language from the warrant fields alone. If the LLM cannot do this, that is a v0.1 finding — it means belief objects require prompt scaffolding to be useful, which weakens the architectural claim.

This rule exists to prevent contaminating the comparison: if System B's payload contains prompt-shaped guidance that System A's payload does not, the comparison stops being "different grounding payload, same prompt template" and becomes "different prompt template."

---

## 4. Question set

### 4.1 Size

- **Minimum**: 50 questions
- **Target**: 75 questions
- **Ideal**: 100 questions

### 4.2 Categories

Five categories, locked weights:

| Category | Share of set | At target (75) | At minimum (50) |
|---|--:|--:|--:|
| Current intel | 20% | 15 | 10 |
| Change detection | 20% | 15 | 10 |
| Stale assumption | 20% | 15 | 10 |
| Contradiction / tension | 20% | 15 | 10 |
| **Insufficient warrant** | 20% | 15 | 10 |

The insufficient-warrant category is the critical negative-example set. It tests whether each system can correctly decline ("I don't have a maintained belief here; here are raw events only") when warrant is thin. L1 coverage gating's whole purpose is to enable this; without 15+ such questions, the experiment can't measure it.

### 4.3 Question shape

Each question is a record in `questions.jsonl`:

```json
{
  "question_id":            "nvda_current_intel_001",
  "question":               "What is the current intel on NVDA capacity constraints?",
  "category":               "current_intel",
  "ticker":                 "NVDA",
  "evidence_cutoff":        "2026-05-26",
  "expected_failure_mode":  "stale_prior" | "unsupported_claim" | "overclaim" | "missing_decline" | null
}
```

### 4.4 Question construction discipline (authorship, anti-curation-bias)

The question set must not be written *from* the belief objects. That would let belief-shaped questions sneak into the set, biasing the experiment toward System B by construction.

**Procedure:**

1. Candidate questions are generated/selected from the **raw L0 evidence stream** (`data/normalized/tech_ecosystem.jsonl` and per-ticker derived files), **blind to** `belief_objects.jsonl`. The author may not consult the belief substrate while drafting questions.
2. Candidates are stratified by:
   - **Actor**: at minimum, one question per actor in the primary universe of 31 tickers.
   - **Date**: per-question evidence cutoffs spread across the 173-day window, not concentrated at one end.
   - **Category**: per §4.2 weights.
3. After stratified candidate generation, the question set is hand-curated for clarity, deduplication, and the §4.2 quota balance.
4. Questions are frozen in `questions.jsonl` **before any answers are generated by either system**. No question is added, removed, or edited after lock.
5. Each question records its `expected_failure_mode` for downstream analysis (not for either system to see).

### 4.5 Point-in-time queries as central, not incidental

Point-in-time queries (`"As of YYYY-MM-DD, what is the current intel on …?"`) are the cleanest test of currency and evidence-boundary discipline. They must be **central** to the question set, not a token category:

- At least **60% of questions** carry a non-current evidence_cutoff (i.e., cutoff date earlier than the substrate's most recent date), forcing both systems to operate as-of-historical.
- The remaining 40% may use the substrate's most recent date as cutoff.
- This distribution forces temporal-leakage to be detectable: if either system answers using post-cutoff evidence, it produces a measurable evidence-boundary violation (§6.2).

Without enough point-in-time queries, currency cannot be tested rigorously and System B's L1/L2 currency advantages are not exercised.

---

## 5. Validation protocol

### 5.1 Identical-prompt constraint

System A and System B receive **identical** system prompts and user prompts. The only difference is the grounding payload assembled into the context window. Any prompt-template drift between the two systems invalidates the comparison and must be re-run.

Locked prompt template (parameterized):

```
[locked system prompt instructing the LLM to answer the user's
query using the provided context, with no instructions about
caution, hedging, citation style, or decline behavior]

CONTEXT:
{grounding_payload}

QUESTION:
{question}
```

The grounding_payload differs (chunks vs. belief objects). The system prompt does not.

### 5.2 Architectural evidence cutoff

For each question with `evidence_cutoff = T`:

- System A's retrieval pool is filtered to evidence with `timestamp ≤ T` BEFORE retrieval runs.
- System B's belief substrate is filtered to belief objects whose `last_updated ≤ T` AND whose underlying evidence_refs all have `timestamp ≤ T` BEFORE belief return runs.
- Neither system can see post-cutoff evidence under any circumstance.

This is architectural enforcement, not post-hoc labeling. If a system returns an answer that cites post-cutoff evidence, that indicates a substrate construction bug, not a measurement edge case.

### 5.3 Token budget

Locked equal: same max-context-tokens for both systems' grounding payloads. If System A's top-K chunks would exceed the budget, K is truncated. If System B's belief objects would exceed the budget, the lowest-warrant beliefs are truncated first.

### 5.4 Locked engineering parameters

The pre-registration locks these at first run:

- Generation model + version (same for both systems)
- Embedding model + version (System A only)
- Top-K (System A)
- Max context tokens for grounding payload
- Temperature (probably 0 for both, for reproducibility)
- Random seed (where applicable)

Specific values committed at first-run time and recorded in the report's audit trail.

---

## 6. Deterministic measurement track

### 6.1 Primary metric

**Stale-claim error rate** — fraction of answers that rely on at least one claim that was contradicted, weakened, retired, or superseded in the substrate before the question's evidence_cutoff.

A stale-claim error requires:
1. The answer makes a specific claim X.
2. The substrate contains evidence ≤ cutoff that should have updated, weakened, or retired X.
3. The answer does not acknowledge that update.

### 6.2 Other deterministic metrics

- **Unsupported-claim rate**: claims in the answer not backed by any evidence in the corpus ≤ cutoff.
- **Contradiction-omission rate**: cases where the substrate contains contradicting evidence (counterevidence_refs in the belief object, or contradictory raw events for the chunk system) and the answer fails to acknowledge it.
- **Insufficient-warrant-overclaim rate**: answers to insufficient-warrant questions where the system makes a confident claim instead of declining.
- **Evidence-boundary violation rate**: answers citing evidence with timestamp > cutoff. (Architectural enforcement per §5.2 should make this zero; any non-zero rate indicates a bug.)

### 6.3 Labeling protocol

- LLM-as-judge with a locked judge model + version + prompt scores each answer against the above metrics.
- Human spot-check on a sampled subset (target: 20% of answers per category) validates LLM-judge calls.
- Disagreement between LLM judge and human spot-check is itself reported.
- **Escalation is per (metric × category), not blanket.** If LLM-judge / human disagreement exceeds 20% on a specific (metric, category) cell — for example, stale-claim error in the change-detection category — only the LLM-judge results for *that cell* are downgraded to "indicative" and human labeling is escalated to full coverage *for that cell only*. Other (metric × category) cells retain their LLM-judge labels without modification. The full experiment is not invalidated by isolated cell-level disagreement.
- If escalation fires on a majority of cells across either dimension (e.g., > 50% of metrics on any single category, or > 50% of categories on any single metric), the LLM judge configuration is treated as unfit for the v0.1 measurement and human labeling becomes primary for the affected dimension. This is a more severe call; the report names it explicitly.

### 6.4 Reporting per metric

Per (metric × system) cell:
- Raw count (numerator and denominator)
- Rate (numerator / denominator)
- 95% confidence interval (no significance tests; intervals only)
- Per-category breakdown

---

## 7. Preference measurement track

### 7.1 Axes (three only)

- **Appropriate caution**: did the answer hedge when warrant was weak without becoming useless?
- **Traceability usefulness**: could a knowledgeable user actually audit this answer's basis?
- **Sensemaking usefulness**: did the answer help the user form a current view?

Trustworthiness is **deliberately excluded** as a scored axis — it is the composite of the other three and would double-count. Trust signals may appear in qualitative comments and are reported there, not scored.

### 7.2 Judging protocol

- **Pairwise blind judging**: same question, both answers presented in randomized order, system identity stripped (no "system A / system B" labels; presented as "Answer 1 / Answer 2" with mapping recorded out-of-band).
- **LLM judge**: locked judge model + version + prompt. Scores each axis per pair.
- **Human spot-check**: ~20% of pairs reviewed by a domain-knowledgeable human, especially for sensemaking usefulness (which is domain-specific).
- Per pair per axis: judge picks A, picks B, calls tie, or marks uncertain.

### 7.3 Tie and uncertain handling (locked)

- **Tie**: judge explicitly judges both answers equivalent on the axis. Reported as its own category; not split between A and B.
- **Uncertain**: judge cannot determine which is better on the axis (e.g., both decline, both fail in similar ways). Reported as its own category; not split.
- Tie + uncertain rates are first-class outcomes. A high uncertain rate on any axis is a signal that either the axis is ill-defined or the judge prompt needs revision.
- **Per-axis win rate is computed excluding ties and uncertains**: `win_rate_A = wins_A / (wins_A + wins_B)`. Ties and uncertains are reported alongside but not silently allocated.

### 7.4 Aggregation method (locked)

- **Per-axis win rate** with 95% confidence interval (bootstrap over questions, n=10,000 resamples).
- **No single composite "preference score"** across the three axes. Each axis is reported independently; readers can form their own aggregate judgment.
- **No Bradley-Terry / ELO modeling** in v0.1 (only two systems; pairwise win rate is sufficient).
- Per-category breakdown for each axis.

### 7.5 Reporting per axis

Per axis:
- Win rate for A, win rate for B, tie rate, uncertain rate
- 95% confidence interval on the A-vs-B margin (bootstrap)
- Per-category breakdown
- Human-spot-check agreement rate with LLM judge

### 7.6 Judge validation and configuration freeze

**Calibration procedure:**

1. Before the primary preference run, a small calibration set (~20 pairs) is human-rated by the experimenter on each of the three axes.
2. A candidate LLM judge configuration (model, version, prompt) is run on the same set.
3. If agreement is < 70% per axis, the judge prompt is revised and the calibration repeated. Iteration is allowed.
4. The first judge configuration that passes calibration on all three axes becomes the **frozen primary-run configuration**.

**Configuration-freeze rule:**

- The judge model, version, prompt, tie/uncertain handling (§7.3), and aggregation method (§7.4) **must be recorded in writing before any primary-run judgment is generated**.
- Calibration iteration is permitted right up to that recording moment. Calibration is not measurement.
- Once primary-run judgment begins, no parameter of the judge configuration may change. If a problem with the judge surfaces mid-run, the run is halted, the configuration revised, and the run restarted from question 1 — partial-run output is discarded.

The frozen judge configuration is documented in the v0.1 report's audit trail alongside the engineering parameters from §5.4.

---

## 8. What v0.1 does NOT claim

- v0.1 does NOT claim Belief Stack "beats" RAG in general. It tests one corpus, one question set, one comparison axis pair.
- v0.1 does NOT claim live-runtime improvement for any deployed system.
- v0.1 does NOT claim equivalence of real-time processing between A and B. The substrate-construction caveat in §2.3 is explicit.
- v0.1 does NOT claim generalization beyond the AI ecosystem intel corpus.
- v0.1 does NOT pre-commit to which direction "wins." A mixed result (e.g., deterministic confirmed, preference flat) is a primary finding, not a failure.
- v0.1 does NOT score trustworthiness as a preference axis; only its three constituent axes.

---

## 9. Reporting structure

The v0.1 report MUST contain, in this order:

1. **Universe summary** — question set composition, evidence cutoffs distribution, substrate stats
2. **Deterministic results** — primary stale-claim metric and all secondary metrics, per system, per category
3. **Preference results** — three axes, win/loss/tie per axis, per category
4. **Disagreement analysis** — where deterministic and preference results diverge. This is a headline section, not an appendix. The four-quadrant outcome space is the framing.
5. **Qualitative traces** — 5-10 example pairs (winning A, winning B, ties, instructive failures)
6. **Limits** — substrate scope, judge validation results, labeling agreement rates, known confounds

The disagreement analysis (§4) is the most architecturally interesting outcome of the experiment and is treated as a primary section, not an appendix.

---

## 10. Versioning policy

v0.1 is the first measurement. Any change to systems, question set, prompts, judging protocol, or metrics after lock requires v0.2 (new pre-registration). v0.1 results stay valid as v0.1; v0.2 results are reported separately with head-to-head per the established discipline.

Ambiguities encountered during v0.1 implementation are appended to `STACK_GROUNDED_ISSUES_LOG.md` and resolved at v0.2.

---

## 11. Deliverables

```
stack_grounded_v1/
  STACK_GROUNDED_PRE_REGISTRATION_v0.1.md   (this document)
  questions.jsonl                            (locked at pre-reg lock time)
  evidence_cutoffs.jsonl                     (per-question cutoffs)
  build_belief_substrate.py                  (extracts belief objects from TopicSpace pipeline outputs)
  build_chunk_substrate.py                   (chunks raw events for embedding)
  build_chunk_context.py                     (System A context assembly)
  build_belief_context.py                    (System B context assembly)
  generate_answers.py                        (paired generation, both systems)
  deterministic_label.py                     (judge + spot-check labeling for §6)
  judge_preference.py                        (pairwise blind judging for §7)
  validate_judge.py                          (judge calibration per §7.4)
  STACK_GROUNDED_REPORT_v0.1.md              (the final report)
  data/
    answers_a.jsonl                          (System A outputs)
    answers_b.jsonl                          (System B outputs)
    deterministic_labels.jsonl               (per-metric per-answer labels)
    preference_judgments.jsonl               (per-pair per-axis judgments)
    report_summary.json                      (machine-readable summary)
```

`build_belief_substrate.py` is the new component — it reads the existing TopicSpace pipeline outputs (actors.json, lifecycle events, narrative_pressure, sufficient_data flags) and emits `belief_objects.jsonl` per the §3.4 schema. No re-derivation; just extraction.

---

## 12. Audit trail

| Field | Value |
|---|---|
| Author | Susan Stranburg |
| Locked | 2026-05-31 |
| Companion spec | [topicspace.ai/research/belief-stack](https://topicspace.ai/research/belief-stack) (v0.1, locked 2026-05-30) |
| Sibling pre-regs | [SENSEMAKING_V1_5_PRE_REGISTRATION_v0.1.md](../sensemaking_v1_5/SENSEMAKING_V1_5_PRE_REGISTRATION_v0.1.md), [PHASE2_PRE_REGISTRATION_v0.1.md](../tkos_log_replay/PHASE2_PRE_REGISTRATION_v0.1.md) |
| Engineering parameters (model, K, tokens, seed) | Locked at first-run time; recorded in report audit trail |
| Question set | Locked at pre-reg lock; `questions.jsonl` finalized concurrently |
| Judge configuration | Locked after calibration pass per §7.4 |
| Rules version | v0.1 |

---

## 13. Public framing

If the deterministic hypothesis holds (B reduces stale-claim error vs A):

> Belief-state grounding reduces stale-claim errors on intel-style queries compared with chunk retrieval over the same evidence substrate. The architectural claim — that maintained L1 + L2 layers carry information chunk retrieval can't access — is measurably supported on this corpus.

If the preference hypothesis holds:

> Blind pairwise judging preferred belief-state-grounded answers on caution, traceability, and sensemaking usefulness. The architectural claim that L1 coverage gating and L2 belief return improve the perceived quality of answers is supported on this corpus.

If both hold:

> Belief-state grounding is both more accurate (deterministically) and preferred (subjectively) on this corpus. The architectural claim is supported on both axes.

If results diverge (deterministic wins, preference flat — or the reverse):

> The deterministic / preference gap is the primary finding. [Articulation of what the gap means architecturally.]

If neither holds:

> Belief-state grounding did not improve answers on this corpus under the v0.1 rules. The architectural claim needs revision before further investment, or the specific operationalization in v0.1 (belief object schema, judge protocol) needs to be reconsidered.

All four outcomes are honest, publishable, and informative. None require the experiment to "win" to be useful.

The closing thesis stays:

> RAG retrieves relevant evidence. A belief-state knowledge source returns what that evidence currently warrants. The experiment tests whether that difference improves LLM answers.
