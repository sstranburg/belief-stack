# Rendering Sensitivity Prototype C1 — Notes

_Locked alongside the v0.1 artifacts on 2026-06-01._

**This is NOT v0.2.** It is a single-variable sensitivity prototype that tests whether the v0.1 System B failure was caused by structured-record rendering rather than the belief-state substrate. Same beliefs, same selection, same judges, same generator — only the rendering changed.

Companion artifacts: the v0.1 [pre-registration](STACK_GROUNDED_PRE_REGISTRATION_v0.1.md), [v0.1 report](STACK_GROUNDED_REPORT_v0.1.md), and all earlier notes documents are unchanged. This document supplements them with the C1 result.

---

## 1. What this prototype tests (and what it does not)

**Tests:**
- Whether changing belief-context rendering from compact structured records to substrate-agnostic narrative prose — while holding every other variable constant — moves System B's deterministic and preference outcomes toward A.

**Does not test:**
- v0.2 architectural alternatives (L0 inlining, consumption-contract semantics like `current_status` / `warrant_status`, actors.json site-level synthesis). These are downstream prototypes that this result will inform.
- Whether the *substrate* (belief_objects.jsonl) is correct. Substrate stays exactly as v0.1 locked it.
- A new question set, a new judge, a new generator, or new evidence sources.

---

## 2. Locked C1 parameters

| Parameter | Value | Notes |
|---|---|---|
| Substrate | `belief_objects.jsonl` | Identical to v0.1; read-only |
| Item selection | inherited verbatim from `contexts_b.jsonl` | Same beliefs per question as v0.1 System B |
| Cutoff enforcement | inherited from v0.1 | 0 violations |
| Token budget | 6000 (cl100k_base) | Identical to v0.1 |
| Generator | `gpt-4o-2024-08-06`, T=0, seed=20260531, max_tokens=1500 | Identical to v0.1 |
| Generation prompt | locked v0.1 prompt (hash `4cd185152eb5c43d…`) | Unchanged |
| Deterministic judge | `gpt-5-mini-2025-08-07`, reasoning=medium, seed=20260531 | Identical to v0.1 |
| Preference judge | `gpt-4.1-2025-04-14`, T=0, seed=20260531 | Identical to v0.1 |
| Pref-judge view | blind to context, position-randomized | Identical to v0.1 |

The *only* changed variable: the per-context rendering. `build_belief_context_c1.py` produces a substrate-agnostic narrative-prose briefing from the same belief items.

### 2.1 Rendering discipline (explicit)

The C1 rendering must NOT contain any TopicSpace-specific vocabulary:
- No NDS, narrative score, `rel_5d`
- No state labels (DIVERGENCE / MACRO / REPRICING / CONFIRMATION)
- No "read" field strings ("moving with tape", etc.)
- No `actors.json` data of any kind
- No `narrative_pressure.jsonl` data
- No site-level synthesis

The rendering uses only generic vocabulary: lifecycle terms (active/born/reconfirmed/weakened/contradicted/retired), warrant terms (sufficient/partial/out-of-distribution, confidence, supporting observations), generic timestamps, source counts, evidence_ref IDs. Claim text passes through verbatim from the substrate (any pipeline-flavored vocabulary inside a quoted claim is owned by the data, not the framing).

Verified in `data/context_c1_audit.json`:
- `topicspace_jargon_excluded: true`
- `actors_json_consulted: false`
- `narrative_pressure_consulted: false`
- `claim_text_passes_through_verbatim: true`

### 2.2 Render structure

The narrative briefing per actor:

1. **Currently active beliefs** (born / active / reconfirmed) — each enumerated with claim, recorded date, support_n, warrant level, confidence, sources, evidence refs.
2. **Weakened / contradicted beliefs** — separate section if any.
3. **Recently closed beliefs** (last 30 days before the query cutoff) — enumerated similarly, with closed-out dates.
4. **Older closed beliefs** — summarized by month with top claim examples.
5. **Related beliefs about other actors** (theme-mates) — same structure, grouped by actor.

Empty contexts (12 of B's 75 had 0 items) render as `(no beliefs in the substrate match this query as of the cutoff date.)`.

---

## 3. Context build results

| Stat | C1 | B (reference) |
|---|---|---|
| Contexts emitted | 75/75 | 75/75 |
| Cutoff violations | 0 | 0 |
| Over-budget contexts | 0 | 0 |
| Tokens per context (min/mean/max) | 14 / 1281 / 4730 | 0 / 4752 / 5999 |

Same item count per context (mean 28.1, same in both). C1's narrative prose is ~3.7× denser than B's structured records, leaving substantial token-budget headroom. **Fairness constraint is the ceiling, not the floor.**

---

## 4. Deterministic results (all three systems, same judge)

Per-metric YES-rate among applicable (NA excluded from denominator):

| Metric | System A | System B | **System C1** |
|---|---|---|---|
| stale_claim_error (primary) | 1 / 74 (1%) | 8 / 65 (12%) | **17 / 67 (25%)** |
| unsupported_claim | 10 / 70 (14%) | 18 / 65 (28%) | **11 / 63 (17%)** |
| contradiction_omission | 17 / 71 (24%) | 21 / 59 (36%) | **19 / 58 (33%)** |
| insufficient_warrant_overclaim | 1 / 70 (1%) | 6 / 75 (8%) | **8 / 74 (11%)** |
| evidence_boundary_violation | 1 / 73 (1%) | 0 / 72 (0%) | **0 / 73 (0%)** |

Movement from B to C1, metric by metric:
- `stale_claim_error`: 12% → 25%. **Worse**.
- `unsupported_claim`: 28% → 17%. **Better** — closer to A.
- `contradiction_omission`: 36% → 33%. Slightly better.
- `insufficient_warrant_overclaim`: 8% → 11%. **Worse**.
- `evidence_boundary_violation`: 0% → 0%. Same.

Rendering moved errors around. It did not eliminate the deterministic gap with A. C1 is still worse than A on every metric where A had nonzero error mass.

---

## 5. Preference results (three comparisons, same judge)

### 5.1 Aggregate per-axis rates

**A vs B** (v0.1, included for reference):

| Axis | A | B | TIE |
|---|---|---|---|
| caution | 21 (28%) | 43 (57%) | 11 (15%) |
| traceability | 30 (40%) | 34 (45%) | 11 (15%) |
| sensemaking_usefulness | 46 (61%) | 23 (31%) | 6 (8%) |

**A vs C1** (new):

| Axis | A | C1 | TIE |
|---|---|---|---|
| caution | 22 (29%) | 42 (56%) | 11 (15%) |
| traceability | 34 (45%) | 35 (47%) | 6 (8%) |
| sensemaking_usefulness | 45 (60%) | 24 (32%) | 6 (8%) |

→ C1 against A looks essentially indistinguishable from B against A. C1 wins caution, A wins sensemaking_usefulness, traceability is close. Rendering did not move A-vs-belief-system preferences.

**B vs C1** (the head-to-head — the critical comparison):

| Axis | B | C1 | TIE |
|---|---|---|---|
| caution | 25 (33%) | 21 (28%) | 29 (39%) |
| traceability | 19 (25%) | **36 (48%)** | 20 (27%) |
| sensemaking_usefulness | 20 (27%) | **37 (49%)** | 18 (24%) |

→ C1 wins B head-to-head on traceability and sensemaking_usefulness; caution is roughly tied (high TIE rate). On the axes where C1 wins B, the margin is decisive.

### 5.2 Position-bias check per comparison

| Comparison | X wins | Y wins | TIE |
|---|---|---|---|
| A_vs_B | 100 (44%) | 97 (43%) | 28 |
| A_vs_C1 | 93 (41%) | 109 (48%) | 23 |
| B_vs_C1 | 79 (35%) | 79 (35%) | 67 |

All balanced. The B-vs-C1 high TIE rate is real (the judge often saw them as similar), not a position artifact.

### 5.3 B vs C1 per category (the rendering swap, by question type)

| Category | Axis | B wins | C1 wins | TIE |
|---|---|---|---|---|
| change_detection | caution | 8 (53%) | 2 (13%) | 5 (33%) |
| change_detection | traceability | 1 (7%) | 9 (60%) | 5 (33%) |
| change_detection | sensemaking_usefulness | 0 (0%) | 10 (67%) | 5 (33%) |
| contradiction | caution | 5 (33%) | 3 (20%) | 7 (47%) |
| contradiction | traceability | 3 (20%) | 9 (60%) | 3 (20%) |
| contradiction | sensemaking_usefulness | 5 (33%) | 9 (60%) | 1 (7%) |
| current_intel | caution | 5 (33%) | 7 (47%) | 3 (20%) |
| current_intel | traceability | 2 (13%) | 13 (87%) | 0 (0%) |
| current_intel | sensemaking_usefulness | 3 (20%) | 11 (73%) | 1 (7%) |
| insufficient_warrant | caution | 4 (27%) | 2 (13%) | 9 (60%) |
| insufficient_warrant | traceability | 3 (20%) | 3 (20%) | 9 (60%) |
| insufficient_warrant | sensemaking_usefulness | 5 (33%) | 3 (20%) | 7 (47%) |
| stale_assumption | caution | 3 (20%) | 7 (47%) | 5 (33%) |
| stale_assumption | traceability | **10 (67%)** | 2 (13%) | 3 (20%) |
| stale_assumption | sensemaking_usefulness | 7 (47%) | 4 (27%) | 4 (27%) |

C1's preference wins concentrate in `current_intel`, `change_detection`, and `contradiction`. B's strongest category — `stale_assumption` — flips: B wins traceability there 67% vs C1's 13%. That category was already B's strongest on v0.1; it remains B's strongest against C1 too. C1 cannot read it more usefully because B's compact `state: retired` records were the cleanest input for "what was once supported but isn't anymore" questions.

---

## 6. What the result is (data only — no premature conclusion)

The single-variable rendering change produced these effects:

1. **B→C1 preference shift on traceability and sensemaking_usefulness is real and large.** Head-to-head, C1 wins both axes decisively in the categories where v0.1 had revealed B's failure mode (`current_intel`, `change_detection`, `contradiction`). The narrative rendering made the belief field meaningfully more usable to the LLM on those queries — when judged blind to context.

2. **A's deterministic lead is not closed.** A still wins stale_claim_error (1% vs C1 25%), insufficient_warrant_overclaim (1% vs C1 11%), and contradiction_omission (24% vs C1 33%). On the primary deterministic metric (stale-claim), C1 is *worse* than B (25% vs 12%).

3. **Rendering moved errors around rather than eliminating them.** unsupported_claim dropped from 28% (B) to 17% (C1), but stale_claim_error rose from 12% to 25%. One hypothesis worth testing in a future prototype: the prominent "currently active" header pulls the model toward asserting active-belief claims more confidently, which raises the rate at which active-belief claims that turn out to be stale get cited as current.

4. **The deterministic-vs-preference gap from v0.1 reproduces with C1.** A still wins deterministic; the belief-state system (whether B or C1) still wins caution and loses sensemaking_usefulness against A. The cross-track disagreement that was the headline finding of v0.1 holds.

5. **Categorical pattern is consistent across B and C1**: `stale_assumption` is the only question type where the belief-state system reliably beats A. Other categories show the surface-vs-grounding gap in both B and C1.

**Translation of the data into a sentence:** v0.1's failure was not *just* rendering. Rendering helped some axes (B→C1 head-to-head traceability and usefulness; reduced unsupported-claim) but harmed others (raised stale-claim). The deterministic gap with A persists. The next prototype is not C2-with-more-rendering-tweaks; it should test a different lever (L0 inlining, consumption-contract semantics, or something architectural).

---

## 7. Methodological caveats

1. **Single-judge protocol** carries through from v0.1 (deterministic: gpt-5-mini; preference: gpt-4.1). No inter-judge agreement check on C1. Adding multi-judge agreement remains a v0.2 candidate.

2. **C1's rendering increased token-budget headroom by ~3.7×.** The selection-set was held fixed (same beliefs as B), so this is a free benefit of the prose density. If a future prototype packed *more* beliefs into the saved headroom, that would be a different experiment (rendering + retrieval changes) and would need its own pre-reg.

3. **The B-vs-C1 head-to-head used the same locked preference judge as v0.1.** No new judge calibration. The position-bias check (35/35/30) is balanced; the high TIE rate (39% on caution) is real, not artifact.

4. **C1 still does not include L0 content** — `evidence_refs` are IDs only, as in v0.1. That dimension is untested by C1 and stays open.

5. **Claim text passes through verbatim**, so some quoted claims still contain pipeline-flavored vocabulary ("Repricing Amidst…", "Navigating Early State Amidst…"). This is the substrate's record of what the pipeline observed, not framing C1 added. A future prototype that cleans claim text would conflate substrate content with rendering and is out of scope here.

6. **`gpt-5-mini` deterministic judge** does not honor `temperature=0`; reproducibility is seed + system_fingerprint. Recorded per-call.

---

## 8. What's frozen at C1

- `build_belief_context_c1.py`
- `data/contexts_c1.jsonl` (75 narrative-prose contexts, gitignored)
- `data/context_c1_audit.json`
- `data/answers_c1.jsonl` (75 answers, gitignored)
- The C1 rows of `data/deterministic_labels.jsonl` and `data/preference_judgments.jsonl`
- This document

The v0.1 artifacts (questions, substrate, contexts_a/b, answers_a/b, original A-vs-B preference judgments) are unchanged.

---

## 9. What's NOT done — open levers for future prototypes

- **L0 inlining (C2 candidate)**: same C1 rendering plus the underlying chunk text inlined beneath each belief's `evidence_refs`. Tests whether the missing dimension is "the model needs to see the underlying evidence text, not just IDs."
- **Consumption-contract semantics (C3 candidate)**: extend the belief schema with `current_status` / `warrant_status` / `claim_scope` derived fields. Tests vocabulary as a separate lever.
- **Multi-judge protocol (C-multi candidate)**: replicate either C1 or a future prototype under 2- or 3-judge agreement to address the single-judge caveat.
- **Cross-vendor judge (C-cross candidate)**: replicate with a non-OpenAI judge to address the three-way-but-same-vendor caveat.

Each lever should be tested in isolation, same as C1. None of these are pre-registered; they would each become their own dated prototype.

---

## 10. How to reproduce

```bash
cd /path/to/repo
source venv/bin/activate

# Build C1 contexts (deterministic from belief_objects + contexts_b)
python stack_grounded_v1/build_belief_context_c1.py

# Generate answers — A and B skip via resume; only C1 runs
python stack_grounded_v1/generate_answers.py

# Deterministic labels — A and B skip; only the 75 C1 pairs run
python stack_grounded_v1/deterministic_label.py

# Preference judging — A_vs_B skips; the 150 new pairs (A_vs_C1, B_vs_C1) run
python stack_grounded_v1/judge_preference.py
```

Inputs that must already exist:
- All v0.1 artifacts in `stack_grounded_v1/data/` (contexts_a/b, answers_a/b, deterministic_labels.jsonl, preference_judgments.jsonl)
- `.env` with `OPENAI_API_KEY`

Re-runs of each script are idempotent via the resume policy.

---

## 11. Audit trail

| Field | Value |
|---|---|
| Prototype version | C1 (post-v0.1 rendering sensitivity) |
| Locked | 2026-06-01 |
| Author | Susan Stranburg |
| Build script | `build_belief_context_c1.py` |
| Generation, labeling, preference scripts | `generate_answers.py`, `deterministic_label.py`, `judge_preference.py` (updated to support multiple systems and comparison pairs; v0.1 outputs preserved via resume) |
| Companion artifacts | v0.1 pre-reg + report + all locked notes (unchanged) |
| Combined incremental cost | ~$2.50 (generation + det labels + preference for 150 new pairs) |
| Result framing | Mixed — rendering helped some axes, harmed others; deterministic gap with A persists; the v0.1 failure was not just rendering |
