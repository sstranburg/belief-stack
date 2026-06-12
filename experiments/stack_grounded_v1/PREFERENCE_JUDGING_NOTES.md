# Preference Judging Notes — Stack-Grounded Retrieval v0.1

_Locked alongside the pre-registration, question set, substrate, contexts, answers, and deterministic labels on 2026-05-31._

This document records the locked preference-judge protocol and the raw per-axis results from 75 paired comparisons. It preserves rates, position-bias checks, and verbatim example rationales for downstream auditability.

**Important**: this document is *not* the v0.1 report. The rates here are the raw preference-judge output. Interpretation of how the deterministic results and the preference results combine into the v0.1 finding is deferred to the final report.

---

## 1. What this step does (and does not do)

**Does:**

- For each of 75 paired (System A answer, System B answer) tuples, presents the two answers in randomized order to a locked preference judge.
- Judge returns a winner (X / Y / TIE) plus rationale + confidence for each of 3 pre-registered axes: `caution`, `traceability`, `sensemaking_usefulness`.
- Un-shuffles X/Y back to A/B at write time so downstream readers see direct A/B/TIE preferences.
- Aggregates per-axis and per-(category × axis) win rates.
- Runs a position-bias check (raw X vs Y win rate across all axes).

**Does not:**

- Judge with context visible (the preference judge is BLIND to chunks vs beliefs — it sees only question + two answers; see §3 for rationale).
- Combine preference rates with deterministic labels into a "composite score." Deterministic and preference are reported separately per pre-reg §7.5.
- Interpret directional findings, write the v0.1 report, or draw conclusions.

---

## 2. Locked v0.1 preference-judge parameters

| Parameter | Value | Notes |
|---|---|---|
| Judge model | `gpt-4.1-2025-04-14` | Three-way separation: generator (4o), deterministic judge (gpt-5-mini), preference judge (4.1) — three different model families |
| Temperature | `0.0` | Deterministic |
| `top_p` | `1.0` | Default |
| `seed` | `20260531` | Best-effort determinism per OpenAI's seed contract |
| `shuffle_seed` | `20260531` | Per-pair position randomization seeded from `f"{SHUFFLE_SEED}:{qid}"`; reproducible across runs |
| `max_tokens` | `1500` | Sufficient for 3-axis JSON output; no `finish=length` events |
| Response format | `json_schema` (strict typing) | See `PREF_SCHEMA` in `judge_preference.py` |
| Context visibility | **HIDDEN** | Judge sees only question + cutoff + ticker + category + Answer X + Answer Y. Neither chunks nor belief objects are shown. See §3 for rationale |
| System identity visibility | **HIDDEN** | Judge sees "Answer X" / "Answer Y" only; X→A or X→B mapping is recorded out-of-band per pair |
| Retry policy | exponential backoff (4s → 256s) + jitter, max 6 attempts | Triggered on RateLimitError, APITimeoutError, 5xx |

---

## 3. Why the preference judge is blind to context

The deterministic judge (step 3c) was given full context, since most of its metrics require comparing answer claims against the underlying evidence. The preference judge is given only the answers because:

1. **Format bias removal.** If the judge saw both contexts, it would compare a chunk pile against a structured belief block. The two grounding payloads look very different by design — the judge's preference for one format over the other would contaminate the preference result.

2. **Mirror the downstream reader.** A downstream user of either system reads the answer, not the substrate. The preference axes (caution, traceability, sensemaking usefulness) are properties of *the answer the reader sees*, not of the underlying retrieval. Blind judging matches that surface.

3. **Cross-checks against deterministic.** Because the preference judge cannot see the context, it cannot detect substrate-grounded failures the way the deterministic judge can. Disagreements between the two tracks are not noise — they're information about what the answer looks like vs what the answer actually does.

Per the pre-reg's separation of deterministic-gate and preference tracks: the two judges are complementary, not redundant.

---

## 4. Per-(question_id) record schema

Every line in `preference_judgments.jsonl` carries:

```json
{
  "question_id":          "...",
  "category":             "...",
  "ticker":               "...",
  "evidence_cutoff":      "...",
  "judge_model":          "gpt-4.1-2025-04-14",
  "model_resolved":       "...",
  "system_fingerprint":   "fp_...",
  "seed":                 20260531,
  "shuffle_seed":         20260531,
  "x_is_a":               true | false,
  "judge_prompt_hash":    "...",
  "prompt_hash":          "...",
  "answer_x_hash":        "...",
  "answer_y_hash":        "...",
  "input_tokens":         int,
  "output_tokens":        int,
  "finish_reason":        "stop",
  "judgments": {
    "caution": {
      "winner":          "X" | "Y" | "TIE",
      "winner_unmapped": "A" | "B" | "TIE",  // un-shuffled
      "rationale":       "...",
      "confidence":      0.0-1.0
    },
    "traceability":           {...},
    "sensemaking_usefulness": {...}
  },
  "judged_at": "..."
}
```

The `x_is_a` flag records which system was in the X slot for this pair. The `winner_unmapped` field is the convenience map (X → A or X → B) computed at write time so downstream consumers don't need to re-shuffle.

---

## 5. Run audit

| Metric | Value |
|---|--:|
| Pairs to judge | 75 |
| Pairs complete | 75 / 75 |
| Permanent failures | 0 |
| Distinct `model_resolved` | 1 (`gpt-4.1-2025-04-14`) |
| Distinct `system_fingerprint` | 1 (`fp_6bb50a36bd`) |
| Total input tokens | ~62K |
| Total output tokens | ~17K |
| Estimated cost | ~$0.25 |

A single fingerprint suggests OpenAI routed this small run to one compute pool — convenient for reproducibility. (A larger run would likely span multiple fingerprints, as the generator and deterministic judge runs did.)

---

## 6. Per-axis aggregate rates (n=75)

| Axis | A wins | B wins | TIE |
|---|---|---|---|
| **caution** | **21 (28%)** | **43 (57%)** | 11 (15%) |
| **traceability** | **30 (40%)** | **34 (45%)** | 11 (15%) |
| **sensemaking_usefulness** | **46 (61%)** | **23 (31%)** | 6 (8%) |

### Position-bias check

| Slot | Wins across all 225 axis judgments (75 pairs × 3 axes) |
|---|---|
| X (first slot) | 100 (44%) |
| Y (second slot) | 97 (43%) |
| TIE | 28 (12%) |

Position is balanced. No systematic preference for first-or-second-position answer; the per-axis A/B/TIE rates above are not driven by ordering artifacts.

---

## 7. Per-category × per-axis rates

### change_detection (15 questions)

| Axis | A | B | TIE |
|---|---|---|---|
| caution | 3 (20%) | 8 (53%) | 4 (27%) |
| traceability | 8 (53%) | 1 (7%) | 6 (40%) |
| sensemaking_usefulness | 11 (73%) | 0 (0%) | 4 (27%) |

### contradiction (15 questions)

| Axis | A | B | TIE |
|---|---|---|---|
| caution | 6 (40%) | 7 (47%) | 2 (13%) |
| traceability | 10 (67%) | 3 (20%) | 2 (13%) |
| sensemaking_usefulness | 14 (93%) | 1 (7%) | 0 (0%) |

### current_intel (15 questions)

| Axis | A | B | TIE |
|---|---|---|---|
| caution | 4 (27%) | 11 (73%) | 0 (0%) |
| traceability | 7 (47%) | 8 (53%) | 0 (0%) |
| sensemaking_usefulness | 13 (87%) | 2 (13%) | 0 (0%) |

### insufficient_warrant (15 questions)

| Axis | A | B | TIE |
|---|---|---|---|
| caution | 0 (0%) | 12 (80%) | 3 (20%) |
| traceability | 5 (33%) | 9 (60%) | 1 (7%) |
| sensemaking_usefulness | 8 (53%) | 7 (47%) | 0 (0%) |

### stale_assumption (15 questions)

| Axis | A | B | TIE |
|---|---|---|---|
| caution | 8 (53%) | 5 (33%) | 2 (13%) |
| traceability | 0 (0%) | 13 (87%) | 2 (13%) |
| sensemaking_usefulness | 0 (0%) | 13 (87%) | 2 (13%) |

---

## 8. Example judgments — audit evidence

Three example rationales per axis (one A-win, one B-win, one TIE), preserved verbatim from the judge's structured output.

### 8.1 caution

**A-win example** — `q001_current_intel_ZETA_20260526` (conf 0.90):
*"Answer X clearly states the date limitations of its information and does not overstate its confidence, while Answer Y makes a confident assertion about price action and narrative with only a vague reference to a 'partial warrant' and a confidence score, without explaining the basis for these claims."*

**B-win example** — `q002_current_intel_ARM_20260526` (conf 0.95):
*"Answer X is more cautious, explicitly stating that there is no current intel available and declining to speculate or provide unsupported information. Answer Y presents detailed claims without clarifying the source or certainty of the information, which could lead to overclaiming if the context does not fully support the claims."*

**TIE example** — `q020_change_detection_PLTR_20260228` (conf 1.00):
*"Both answers appropriately hedge and decline to assert a change due to lack of specific evidence, demonstrating high caution."*

### 8.2 traceability

**A-win** — `q001_current_intel_ZETA_20260526` (conf 1.00):
*"Answer X provides specific dates, events, and named sources (e.g., Bank of America, Snowflake-led OSI initiative), making its claims verifiable. Answer Y is vague, referencing only a 'partial warrant' and a confidence score without concrete, checkable details."*

**B-win** — `q002_current_intel_ARM_20260526` (conf 0.85):
*"Answer X is more traceable in the sense that it transparently communicates the lack of available, current information, making it clear what the reader can and cannot verify. Answer Y provides specific claims but does not cite sources or provide dates for most points, making it harder to verify the information."*

**TIE** — `q016_change_detection_VST_20260228` (conf 0.90):
*"Both answers state that the context does not provide specific information about differences, and neither cites any evidence or references, making them equivalent in traceability."*

### 8.3 sensemaking_usefulness

**A-win** — `q001_current_intel_ZETA_20260526` (conf 0.95):
*"Answer X gives concrete, recent developments and analyst actions, helping the reader understand both the company's recent momentum and external perceptions. Answer Y is too vague and lacks actionable or contextual detail."*

**B-win** — `q004_current_intel_NBIS_20260526` (conf 0.90):
*"Answer Y is more useful for sensemaking in this context because it clarifies that there are no current claims about NBIS, helping the reader avoid acting on outdated information. Answer X, while detailed, may mislead by presenting potentially outdated claims as current."*

**TIE** — `q020_change_detection_PLTR_20260228` (conf 1.00):
*"Both answers equally clarify that no change in narrative can be identified from the available information, helping the reader understand the limitations of the data."*

---

## 9. Methodological caveats (preserve and read at report time)

These carry the same status as the deterministic-labeling caveats: into the v0.1 report's methodology section verbatim.

1. **Single LLM judge per axis.** No inter-judge agreement check. v0.2 candidate: 2- or 3-judge protocol with kappa agreement and tie-breaking by majority.

2. **Three-way model separation** — generator (gpt-4o), deterministic judge (gpt-5-mini), preference judge (gpt-4.1). All OpenAI. v0.2 candidate: cross-provider preference judge (e.g., Claude or Gemini) to test whether preference patterns hold across vendor boundaries.

3. **Blind-to-context design.** The preference judge cannot detect substrate-grounded failures that require seeing the original chunks/beliefs. Per §3 this is by design — but it means the deterministic and preference tracks can disagree. The disagreement carries information; it should not be averaged away into a composite score.

4. **Position-bias check is clean.** X (44%) vs Y (43%) wins across all axis judgments. The per-axis A/B/TIE rates are not artifacts of presentation order.

5. **Confidence values are recorded but not used to weight or threshold.** A confidence-weighted aggregation is a v0.2 candidate. v0.1 reports unweighted counts.

6. **Tie handling.** Per pre-reg §7.3, ties are reported separately and never auto-resolved. The tables show TIE as its own column; rates are computed as `wins / total` (not `wins / (wins + losses)`).

---

## 10. What's frozen at this step

- `judge_preference.py` — judge prompt, schema, locked parameters, deterministic shuffle
- `data/preference_judgments.jsonl` — 75 per-pair judgment records
- `data/preference_audit.json` — aggregated rates + position-bias + example rationales

---

## 11. What's NOT done

- The v0.1 report (synthesizing deterministic + preference tracks per pre-reg §9) is deferred. The artifacts above are the input.

---

## 12. How to reproduce

```bash
cd /path/to/repo
source venv/bin/activate
python stack_grounded_v1/judge_preference.py
```

Inputs that must already exist:

- `stack_grounded_v1/questions.jsonl`
- `stack_grounded_v1/data/answers_a.jsonl`, `answers_b.jsonl`
- `.env` with `OPENAI_API_KEY`

The script is idempotent. Re-running with the same parameters skips `(question_id)` pairs already complete (all 3 axes judged). The per-pair shuffle is seeded deterministically from `f"{SHUFFLE_SEED}:{question_id}"`, so position assignment is reproducible across runs even if iteration order changes.

---

## 13. Audit trail

| Field | Value |
|---|---|
| Preference-judging version | v0.1 |
| Locked | 2026-05-31 |
| Author | Susan Stranburg |
| Judge script | `judge_preference.py` |
| Companion pre-registration | [STACK_GROUNDED_PRE_REGISTRATION_v0.1.md](STACK_GROUNDED_PRE_REGISTRATION_v0.1.md) |
| Companion notes | [QUESTION_SET_CONSTRUCTION_NOTES.md](QUESTION_SET_CONSTRUCTION_NOTES.md) · [SUBSTRATE_CONSTRUCTION_NOTES.md](SUBSTRATE_CONSTRUCTION_NOTES.md) · [CONTEXT_CONSTRUCTION_NOTES.md](CONTEXT_CONSTRUCTION_NOTES.md) · [ANSWER_GENERATION_NOTES.md](ANSWER_GENERATION_NOTES.md) · [DETERMINISTIC_LABELING_NOTES.md](DETERMINISTIC_LABELING_NOTES.md) |
| Inputs read | questions, answers_a, answers_b |
| Inputs NOT read | any context, any deterministic label, any other answer set |
