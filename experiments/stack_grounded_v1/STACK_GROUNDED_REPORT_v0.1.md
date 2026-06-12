# Stack-Grounded Retrieval v0.1 — Report

**Locked:** 2026-05-31. **Author:** Susan Stranburg.

**Companion artifacts** (all locked the same day):
[Pre-registration](STACK_GROUNDED_PRE_REGISTRATION_v0.1.md) ·
[Question set notes](QUESTION_SET_CONSTRUCTION_NOTES.md) ·
[Substrate notes](SUBSTRATE_CONSTRUCTION_NOTES.md) ·
[Context notes](CONTEXT_CONSTRUCTION_NOTES.md) ·
[Answer generation notes](ANSWER_GENERATION_NOTES.md) ·
[Deterministic labeling notes](DETERMINISTIC_LABELING_NOTES.md) ·
[Preference judging notes](PREFERENCE_JUDGING_NOTES.md)

---

## 0. Headline

**v0.1 does not support the claim that raw L1/L2 belief objects outperform chunk retrieval under a minimal prompt.** It shows that belief-state grounding creates a better caution surface, but the model needs a clearer consumption contract to use belief objects correctly.

The architectural pattern is not falsified. The v0.1 *operationalization* — raw structured belief objects rendered as-is into a minimal-prompt LLM — is what failed. The deterministic gate inverts: System B has higher rates of stale-claim, unsupported-claim, contradiction-omission, and insufficient-warrant overclaim than System A. Preference judging is mixed: B wins caution, A wins sensemaking usefulness, traceability is close.

The most interesting result is the **cross-track disagreement**, treated as a primary section per pre-reg §9.4 — not an appendix.

---

## 1. Universe summary

| Item | Value |
|---|---|
| Question set | 75 questions, 5 categories × 15 (current_intel, change_detection, stale_assumption, contradiction, insufficient_warrant) |
| Evidence window | 2025-12-05 → 2026-05-26 (173 days) |
| Primary universe | 39 tickers |
| Non-current cutoff share | 80% (60 of 75 questions) |
| Actor coverage in questions | 39 / 39 |
| Chunk substrate | 35,979 chunks, 100% actor coverage |
| Belief substrate | 2,031 belief objects, 100% actor coverage |
| Belief lifecycle distribution | retired 94% · born 5% · contradicted/reconfirmed/weakened 1% |
| Belief coverage distribution | PARTIAL 75% · IN_DIST 16% · OOD 9% |
| Per-question context budget | 6,000 tokens (cl100k_base), identical for A and B |
| Cutoff compliance | 0 violations across both substrates and both context builders |

The substrate skews heavily to `retired` beliefs because the pipeline cycles narrative atoms in and out of attention; the snapshot at any cutoff captures the long tail of historical beliefs. This is by design and is what gives System B coverage at non-current cutoffs. It will matter when we get to the failure-mode analysis.

---

## 2. Deterministic results

**Primary metric** (pre-reg §6.1): stale-claim error rate.

| Metric | System A | System B | Direction |
|---|---:|---:|:---:|
| **stale_claim_error** (primary) | 1 / 74 (1%) | **8 / 65 (12%)** | A better |
| unsupported_claim | 10 / 70 (14%) | **18 / 65 (28%)** | A better |
| contradiction_omission | 17 / 71 (24%) | **21 / 59 (36%)** | A better |
| insufficient_warrant_overclaim | 1 / 70 (1%) | **6 / 75 (8%)** | A better |
| evidence_boundary_violation | 1 / 73 (1%) | 0 / 72 (0%) | B slightly better |

All rates are YES / applicable (NA excluded from denominator). NA counts are recorded in the [deterministic labeling notes](DETERMINISTIC_LABELING_NOTES.md).

**Reading per pre-reg §1**: the primary deterministic hypothesis was that System B would produce a *lower* stale-claim error rate than System A. The observed direction is the opposite. The hypothesis is not supported in v0.1.

**Per-category × per-system × per-metric** rates are in DETERMINISTIC_LABELING_NOTES.md §7. The pattern most worth surfacing here: B's elevated rates are concentrated in `current_intel` (B stale-claim 27%, A 0%) and `contradiction` (B stale-claim 27%, A 0%). On `stale_assumption` questions specifically, both systems perform similarly on stale-claim (A 7% / B 0%), but A makes more unsupported-claim and contradiction-omission errors (A 46% / B 7% and A 53% / B 7%).

The category split is the first hint of the failure mode: B's errors cluster where the substrate has a mix of current and historical beliefs that the model has to disambiguate. B handles `stale_assumption` (where the question explicitly asks about staleness) cleanly; B fails on `current_intel` (where the question asks about current state and the model has to read lifecycle fields correctly to identify what's current).

---

## 3. Preference results

| Axis | A wins | B wins | TIE |
|---|---:|---:|---:|
| caution | 21 (28%) | **43 (57%)** | 11 (15%) |
| traceability | 30 (40%) | 34 (45%) | 11 (15%) |
| sensemaking_usefulness | **46 (61%)** | 23 (31%) | 6 (8%) |

Position-bias check is clean: X wins 44% / Y wins 43% across all 225 axis judgments, so the rates above are not ordering artifacts.

**Per-category × per-axis** rates expose more structure (PREFERENCE_JUDGING_NOTES.md §7):

- **B wins decisively on `stale_assumption`**: 87% traceability, 87% sensemaking_usefulness, 33% caution (the one weak category for B on caution).
- **B wins decisively on `insufficient_warrant` caution**: 80%.
- **B wins decisively on `current_intel` caution**: 73%.
- **A wins decisively on sensemaking_usefulness in three categories**: change_detection 73%, contradiction 93%, current_intel 87%.
- **A wins decisively on traceability for `change_detection` and `contradiction`**: 53% and 67%.

The preference pattern: B is rewarded when answering with appropriate decline or hedging matches the question type; A is rewarded when the question wants a substantive read of recent evidence.

---

## 4. Disagreement analysis (primary section per pre-reg §9.4)

This is where the v0.1 finding sits.

### 4.1 Where the two tracks agree

- **`insufficient_warrant`**: Both tracks favor B. Deterministic shows B doesn't overclaim more than A on these questions (B overclaim rate 0% on this category); preference shows B wins caution 80%. When the question is explicitly about thin warrant, B's empty contexts produce honest declines that both tracks reward.
- **`stale_assumption`**: Both tracks favor B. Deterministic: A makes more unsupported and contradiction-omission errors. Preference: B wins traceability + sensemaking_usefulness 87%. When the question is explicitly about a stale prior, B's `state: retired` markers produce the right answer and the preference judge rewards them.

### 4.2 Where the two tracks disagree — the v0.1 finding

**17 cases** where the blind preference judge awarded System B at least one axis win, while the deterministic judge labeled the same System B answer with a substantive grounding error (stale-claim, unsupported-claim, contradiction-omission, or overclaim). The counterpart for System A is **10 cases**.

This is the cleanest evidence of the v0.1 failure mode: **System B answers look more cautious / better-framed to a reader who cannot see the substrate, but they are systematically less grounded in the substrate the system was actually given.**

Three concrete examples:

#### Example 1 — `q002_current_intel_ARM_20260526`

System B answer: *"All the beliefs and narratives about ARM are marked as 'retired,' with the most recent updates occurring in 2026."*

- Deterministic judge: **YES** on stale_claim_error, unsupported_claim, contradiction_omission. *"The answer asserts that all beliefs are retired, but the context explicitly contains beliefs marked as 'born' (active/new), so the answer incorrectly treats born items as retired."*
- Preference judge (blind): **B wins** caution AND traceability. *"Answer X is more cautious, explicitly stating that there is no current intel available and declining to speculate."*

The model misread the substrate (born beliefs present, model said all retired). The blind preference judge rewarded the "honest decline" without knowing the decline was wrong.

#### Example 2 — `q004_current_intel_NBIS_20260526`

System B answer: *"The context does not provide any current claims about NBIS. All the beliefs listed are in a 'retired' state, meaning they are no longer active or current."*

- Deterministic judge: **YES** on stale_claim_error, unsupported_claim, contradiction_omission. The context contained `state: born` beliefs dated as recently as 2026-05-26.
- Preference judge (blind): **B wins** caution AND sensemaking_usefulness. *"Answer Y is more useful for sensemaking in this context because it clarifies that there are no current claims about NBIS, helping the reader avoid acting on outdated information. Answer X, while detailed, may mislead by presenting potentially outdated claims as current."*

The preference judge inverted the truth: the "decline" answer was *misleading*; the "detailed" A answer was correct. Without seeing the substrate, blind judging cannot detect this.

#### Example 3 — `q006_current_intel_ADBE_20260526`

System B answer: *"The context does not provide any current claims about ADBE. All the beliefs listed are in a 'retired' state, indicating they are no longer active or current."*

- Deterministic judge: **YES** on unsupported_claim, contradiction_omission. Born beliefs present in context (e.g. `ent-353570b735`, `ent-160bba2832`).
- Preference judge (blind): **B sweeps** — wins caution, traceability, AND sensemaking_usefulness.

This is the cleanest failure case. The model produced a confidently-wrong answer that *looked* cautious, traceable, and useful to a blind reader.

### 4.3 The failure mode

The failure is *not* that belief-state grounding is wrong as a category. The failure is interpretive: the LLM is not automatically fluent in belief-object semantics under the minimal prompt the pre-reg required.

Specifically, the model treats `state: retired` as *"this information is no longer relevant"* and uses it as a decline cue, even when the context also contains `state: born` beliefs that should be the load-bearing signal. The substrate carries the right information; the model does not read it correctly.

Note the corresponding pattern in the deterministic per-category breakdown (§2): B fails on `current_intel` (where the model has to *infer* current-vs-historical from the lifecycle field) but performs well on `stale_assumption` (where the question explicitly asks about staleness and the lifecycle field becomes a direct match). The failure mode is asymmetric and predictable.

### 4.4 What this means in pre-reg §13 terms

Of the five outcomes the pre-reg's public framing anticipated, the one that fits is *"divergent — deterministic fails, preference partially holds."* The framing for that outcome is:

> The deterministic / preference gap is the primary finding.

The gap here is: belief-state answers *look* more cautious to a reader, but are *less* grounded in the substrate they were given. The architectural pattern is not falsified; the operationalization (raw belief objects, minimal prompt) is.

---

## 5. Qualitative traces (5–10 example pairs)

Per pre-reg §9.5, a small set of paired examples is preserved to illustrate the patterns.

| # | Question ID | Category | A's outcome | B's outcome | Why this is in the trace |
|---|---|---|---|---|---|
| 1 | q001_ZETA | current_intel | A wins all 3 pref axes; det clean | det clean; pref loses | Clean A win: A's answer is concrete with named events / dates; B's is generic |
| 2 | q002_ARM | current_intel | det clean; pref loses caution+trace | YES on 3 det metrics; wins caution+trace | Cross-track disagreement #1 — see §4.2 |
| 3 | q004_NBIS | current_intel | det clean; pref loses caution+useful | YES on 3 det metrics; wins caution+useful | Cross-track disagreement #2 — see §4.2 |
| 4 | q006_ADBE | current_intel | det clean; pref loses all 3 axes | YES on 2 det metrics; B sweeps all 3 pref axes | Cross-track disagreement #3 — see §4.2 |
| 5 | q020_PLTR | change_detection | det clean; pref TIE all axes | det clean; pref TIE all axes | Genuine TIE — both decline appropriately on thin warrant |
| 6 | q033_CLS_stale | stale_assumption | det YES on 1 metric; loses pref usefulness | det clean; wins pref usefulness 87% | B's strength: lifecycle markers handle stale_assumption cleanly |
| 7 | q065_VRT_iw | insufficient_warrant | YES on evidence_boundary_violation | det clean | The one A boundary violation — forward-dated event in pre-cutoff chunk; borderline call |

Full per-(question, system) labels and per-pair preference judgments are in `data/deterministic_labels.jsonl` and `data/preference_judgments.jsonl`. Per-metric and per-axis example pools (up to 8 per metric / 4 per axis-direction) are in the respective audit JSON files.

---

## 6. Limits

These are the explicit pre-reg §3.3 and §8 limits, plus what surfaced during the run.

### 6.1 Pre-registered limits (preserved verbatim)

- v0.1 does NOT claim Belief Stack "beats" RAG in general. It tests one corpus, one question set, one comparison axis pair.
- v0.1 does NOT claim live-runtime improvement for any deployed system.
- v0.1 does NOT claim equivalence of real-time processing between A and B. Substrate-construction caveat is explicit (pre-reg §2.3).
- v0.1 does NOT claim generalization beyond the AI ecosystem intel corpus.
- v0.1 does NOT score trustworthiness as a preference axis; only its three constituent axes (caution, traceability, sensemaking usefulness).

### 6.2 What surfaced during the run

1. **Single LLM judge per track.** No inter-judge agreement check. v0.2 candidate: 2- or 3-judge protocols with Cohen's / Fleiss' kappa.

2. **Three-way OpenAI separation but same vendor.** Generator gpt-4o-2024-08-06, deterministic judge gpt-5-mini-2025-08-07, preference judge gpt-4.1-2025-04-14. Cross-vendor replication (e.g., Claude or Gemini judges) is a v0.2 candidate.

3. **Stale-claim and contradiction-omission carry inherent labeler subjectivity.** The audit preserves per-label verbatim quotes and rationales so disputed labels can be re-graded. v0.1 reports unweighted single-judge counts.

4. **Preference judge is blind to context** (DETERMINISTIC_LABELING_NOTES §3) — this is by design but means the preference track cannot detect substrate-grounded failures. The cross-track disagreement analysis depends on this asymmetry.

5. **Belief lifecycle field carries 94% `retired`.** This is the natural state of the pipeline at any snapshot, not a defect — but the model's mishandling of `retired` is the dominant System B failure mode, and a substrate where 94% of items are marked with the same lifecycle label probably amplifies the misreading. A v0.2 substrate with explicit `current_status` derived semantics may attenuate this.

6. **Reproducibility is best-effort, not bit-identical.** Generator (gpt-4o) and judges (gpt-5-mini, gpt-4.1) all honor `seed` but OpenAI's seed contract changes outputs across `system_fingerprint` shifts. Per-call fingerprints are recorded for downstream verification.

7. **The 12 zero-item System B contexts** (5 insufficient_warrant, 5 change_detection, 2 stale_assumption — see CONTEXT_CONSTRUCTION_NOTES §5) are honest substrate signals, not bugs. They contribute to the preference judge's reward of B's caution behavior.

### 6.3 What the failure mode does NOT prove

- It does NOT prove belief-state grounding fails as a category. It proves the v0.1 operationalization fails.
- It does NOT prove the substrate is wrong. The substrate contains the right information; the LLM does not consume it correctly.
- It does NOT support adding `answer_guidance` or prompt-shaped scaffolding to the belief objects. That would violate pre-reg §3.5 schema discipline and would conflate "the substrate is more legible" with "we told the LLM the answer."

---

## 7. What v0.2 should test

(Brief; full v0.2 design is a separate pre-registration.)

The v0.1 finding points to a substrate-vocabulary problem, not a substrate-content problem. v0.2 should test whether a more legible neutral schema fixes the belief-object readability gap without instruction-shaped fields.

Candidate v0.2 schema additions (structured semantics, not prompt advice):

```
current_status: current | historical | inactive
warrant_status: sufficient | partial | insufficient
claim_scope:    current_read | historical_record | contradicted_prior
```

These translate pipeline-native lifecycle states (born / active / reconfirmed / weakened / contradicted / retired) into reader-native semantics whose load is less ambiguous under a minimal prompt. The hypothesis under test in v0.2 would be:

> Belief-state grounding with explicit consumption-contract semantics improves stale-claim error rate over chunk retrieval and over v0.1 belief-state grounding, under the same minimal prompt.

That hypothesis is testable with the same question set and the same answer-generation parameters; only the substrate-construction step needs to change.

---

## 8. Closing — what this saves us from

The v0.1 finding saves the program from a specific bad outcome: building product on the assumption that *structuring* belief objects is sufficient for an LLM to consume them correctly. The structuring is necessary but not sufficient. A consumption contract is needed, and the contract has to be substrate-shaped, not prompt-shaped.

The architectural claim — that maintained L1 + L2 layers carry information chunk retrieval cannot access — is not addressed by v0.1's failure. v0.1 tested *consumption*, not *content*. The content question stays open for v0.2.

---

## 9. Audit trail

| Field | Value |
|---|---|
| Report version | v0.1 |
| Locked | 2026-05-31 |
| Author | Susan Stranburg |
| Pre-registration | [STACK_GROUNDED_PRE_REGISTRATION_v0.1.md](STACK_GROUNDED_PRE_REGISTRATION_v0.1.md) |
| Companion notes | question set, substrate, contexts, answer generation, deterministic labeling, preference judging (see header) |
| Inputs read | all data/*.jsonl + data/*.json audit files |
| Inputs NOT read | none — this report synthesizes the locked artifacts |
| Models used | generator gpt-4o-2024-08-06 · deterministic judge gpt-5-mini-2025-08-07 · preference judge gpt-4.1-2025-04-14 (three-way separation) |
| Combined run cost | ~$3 (embeddings + generation + both judges) |
