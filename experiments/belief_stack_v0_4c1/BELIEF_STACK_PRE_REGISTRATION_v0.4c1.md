# Belief Stack v0.4c1 — Cross-Model Replication Pre-Registration

**Date:** 2026-06-04
**Status:** **LOCKED 2026-06-04 as v0.4c1; AMENDED + RE-LOCKED 2026-06-04 as v0.4c1.1** (provider API discoveries — `gemini-2.5-pro` requires thinking mode; `claude-opus-4-7` does not accept `temperature` parameter). See §11 Amendment log.
**Lineage:** OB-001 (v0.1) → OB-002 (v0.2.2) → Belief Stack v0.3 → v0.4a.1 → v0.4a.2 → **v0.4c1.1 (cross-model replication, this document)** → v0.4c2 (cross-substrate replication)

---

## §0 The question

**Does v0.4a's finding — *maintained state beats reconstruction* — replicate across LLM model families?**

v0.3 and v0.4a held the generator fixed at `gpt-4o-2024-08-06` (T=0, seed 20260601). The first reviewer question for any single-model result is: *how do we know this is not a model-specific artifact?* v0.4c1 holds the substrate and the experimental design constant and varies the generator across multiple models. Per the locked paper-scope-discipline memory, cross-model replication is one of two required experiments before the empirical claim earns its full generality in publication.

**Specifically, v0.4c1 tests the thesis (maintained state beats reconstruction), not the mechanism (which rendering of maintained state wins).** The mechanism question from v0.4a.1 is held as substrate-and-model-specific; this experiment focuses on the thesis. The pre-registered arm set is `A / A' / B / C` — sufficient to test the thesis across models without re-running the full mechanism ablation per model.

---

## §1 Decisions

| # | Topic | Status | Resolution |
|---|---|---|---|
| **D1** | Substrate | **RESOLVED** | Reuse v0.1 / v0.2.2 / v0.3 / v0.4a substrate unchanged. 75 paired single-next-action planning questions, derived from 164 Claude Code session logs (~20,190 evaluation turns). Same 5 categories. Maximizes cross-experiment comparability. |
| **D2** | Number of arms | **RESOLVED** | 4 (A / A' / B / C). Drops D and E from v0.4a's ladder because their result (E ≈ B; D ≈ C, both slightly below) was substrate-and-budget-specific; re-running them across models is mechanism-question scope, not thesis scope. v0.4c1 tests the thesis. |
| **D3** | **Models** | **RESOLVED** | Four models locked: <br/>1. `gpt-4o-2024-08-06` (parity check; same as v0.3 / v0.4a) <br/>2. `claude-opus-4-7` (frontier-class, different family) <br/>3. `gemini-2.5-pro` (frontier-class, different family) <br/>4. `claude-haiku-4-5-20251001` (smaller; scale-variance question)<br/><br/>**Rationale:** *"does this hold on frontier alternatives?"* and *"does this hold on cheaper models?"* are separate questions and both worth answering. Three would be the minimum defensible; the fourth model (Haiku) addresses scale variance and is worth the additional cost. |
| **D4** | Per-model generator configurations | **RESOLVED (v0.4c1.1 amendment)** | All models: `temperature=0` where supported, top_p 1.0, max output 1500 tokens. Seed is set to `20260601` where the provider supports it. Per-provider behavior documented in §3 — three real provider-specific divergences are now recorded:<br/><br/>• `gpt-4o-2024-08-06`: full v0.4a parity (T=0, seed supported).<br/>• `claude-opus-4-7`: the API rejects `temperature` (deprecated for this model). Uses Anthropic's default sampling. Seed not supported.<br/>• `claude-haiku-4-5-20251001`: accepts T=0; seed not supported.<br/>• `gemini-2.5-pro`: the API requires thinking mode (`thinking_budget=0` returns 400). Run with `thinking_budget=2048` to give the model headroom for internal reasoning. Seed supported as a config parameter.<br/><br/>Cross-model parity is not perfect; the divergences are recorded honestly and surfaced as paper limitations. Per-provider config is locked here; no further variation at run time. |
| **D5** | Context budgets | **RESOLVED** | Match v0.4a's locked budget cap of ~285 tokens for B and C. Arm A's raw K=20 log unchanged. Arm A''s LLM summary cap matched to B at ~285 tokens. The §3.5a dedup-ranking machinery from v0.4a is the canonical projection pipeline; same code, same parameters across all models. |
| **D6** | Scoring | **RESOLVED** | **Hold the judge constant; only the generator varies.** Reuse v0.4a's deterministic oracle (`score_operational_label.Scorer`) + LLM judge (`gpt-5-mini-2025-08-07`, reasoning_effort=medium, seed 20260601). Same `combine_oracle_and_judge` policy (oracle wins on disagreement). Holding the judge constant isolates the generator question from any judge-variance confound. |
| **D7** | Primary outcome metric | **RESOLVED** | Per-model paired planning correctness. n = 75 paired observations per (model, arm pair). Pre-registered minimum effect size for "advancement" between arms: **3 percentage points**. |
| **D8** | Interpretation rules | **RESOLVED** | See §7 below. Per-model five-class outcome classifier locked; cross-model outcome classes locked with explicit action commitments. Locked BEFORE any data flows. No amendments after results without re-lock and re-version. |

**All eight decisions resolved.** Pre-registration is LOCKED. Sue's sign-off on D3 (4 models), D4 (accept residual non-determinism; record per-provider seed support; do not let seed parity block), and D8 (interpretation rules as drafted) recorded 2026-06-04.

---

## §2 The four arms (per model)

For each model in §3, the same four arms are run:

| Arm | Context shape | What it tests |
|---|---|---|
| **A** | Raw K=20 log + strong-baseline reconstruction prompt | The pre-maintained-state baseline (v0.3 Arm A unchanged) |
| **A'** | LLM prose summary of raw K=20 log at ~285-token cap, same protocol as Arm B | Compression-control: rules out "compression alone explains the lift" (v0.4a.2 Arm A' unchanged) |
| **B** | LLM prose summary of substrate-clustered active beliefs at ~285-token cap | The v0.4a Arm B (substrate-derived prose projection) |
| **C** | Bare `belief_type :: claim` per active cluster, dedup-ranked, ~285-token budget cap | The v0.4a Pareto-winner (sparse structured names) |

The **summarizer model** for arms B and A' is the same as the per-model generator under test (i.e., each model summarizes its own input). This holds the *full pipeline* constant per model and tests whether a given model can both (a) summarize the substrate to produce Arm B's context AND (b) plan from it correctly.

---

## §3 Models and locked configurations

All four models locked. Per-provider seed support recorded; residual non-determinism accepted where seed is unsupported per D4.

All four models locked. Per-provider configurations updated per the v0.4c1.1 amendment after build-time API verification.

```
Model 1: gpt-4o-2024-08-06         (provider: OpenAI)
  temperature:      0
  top_p:            1.0
  max_tokens:       1500
  seed:             20260601                  (supported)
  thinking:         n/a (model has no thinking phase)
  parity note:      reproduces v0.4a exactly; any drift > 2 pp on
                    any arm prompts sanity audit before cross-model
                    interpretation

Model 2: claude-opus-4-7            (provider: Anthropic)
  temperature:      NOT SUPPORTED — API rejects this parameter for
                    this model; default sampling is used
  top_p:            not explicitly set
  max_tokens:       1500
  seed:             NOT SUPPORTED
  thinking:         n/a — model uses Anthropic-internal sampling
  notes:            this model has the most provider divergence from
                    v0.4a parity. Residual non-determinism + non-zero
                    effective temperature both accepted. Will be the
                    arm most likely to show run-to-run variation.

Model 3: gemini-2.5-pro             (provider: Google / Gemini API)
  temperature:      0
  top_p:            1.0
  max_tokens:       1500     (final answer cap)
  seed:             20260601                  (supported)
  thinking_budget:  2048      (REQUIRED — API rejects thinking_budget=0
                              with 'This model only works in thinking
                              mode.' v0.4c1.1 sets a fixed budget that
                              gives the model headroom for internal
                              reasoning before producing the final
                              answer.)
  notes:            Gemini has a larger effective compute envelope per
                    call than the other three models. Documented as a
                    paper limitation. The cross-model claim becomes
                    'maintained state beats reconstruction on three
                    non-thinking models AND on one thinking model
                    with internal reasoning budget' — itself an
                    architecturally interesting comparison.

Model 4: claude-haiku-4-5-20251001  (provider: Anthropic)
  temperature:      0                         (supported)
  top_p:            1.0
  max_tokens:       1500
  seed:             NOT SUPPORTED
  thinking:         n/a
  notes:            standard Anthropic sampling at T=0 minus seed.
                    Residual non-determinism accepted.
```

**Audit requirement:** the build script captures actual per-provider behavior in the audit JSON (request configs sent, responses received, any provider-specific telemetry). The four divergences from a hypothetical "perfect parity" config are documented in the audit + the paper. The paper's "single model family" caveat in v0.4a becomes "models in this family, with per-provider sampling and (for Gemini) thinking-mode notes" in v0.4c1.

Total expected API calls: 75 questions × 4 arms × 4 models = **1,200 generation calls** + **1,200 judge calls** (judge held constant on `gpt-5-mini-2025-08-07`). Estimated wall-clock: 6-12 hours depending on per-provider rate limits. Estimated cost: ~$30-80 across all model APIs.

---

## §4 Context construction

Per-model context construction reuses the v0.4a code paths with the per-model summarizer for arms A' and B.

**Anti-curation discipline:** all contexts for all (model, arm, question) cells are constructed BEFORE any answer-generation calls flow. This means:

1. Generate A contexts (75 questions × 4 models = 300; identical text across models since A is raw log — but generated per-model to preserve audit trail of the per-model summarizer being unused for A).
2. Generate A' contexts (75 questions × 4 models = 300; each model summarizes its own raw log).
3. Generate B contexts (75 questions × 4 models = 300; each model summarizes its own substrate input).
4. Generate C contexts (75 questions × 4 models = 300; deterministic — substrate-side §3.5a rendering, same across models, generated once and copied; or per-model for symmetric audit).

Total contexts: 1,200 (or 900 if C is generated once and shared across models). Audit JSON records per-arm token statistics and per-model summarizer telemetry.

---

## §5 Scoring

Per D6:

- **Primary metric:** paired planning correctness — per-(model, question) oracle agreement from `score_operational_label.Scorer`.
- **Judge:** `gpt-5-mini-2025-08-07`, reasoning_effort=medium, seed 20260601, same prompt hash as v0.3 / v0.4a / v0.4a.1 / v0.4a.2.
- **Policy:** oracle wins on disagreement (`combine_oracle_and_judge` unchanged from v0.3).
- **Sample:** n = 75 paired observations per (model, arm-pair) comparison.
- **Cross-model comparison:** *per-model* correctness rates are the primary unit; cross-model differences in absolute correctness are a secondary observation, not a primary outcome.

---

## §6 Pre-registered predictions

**Per-model prediction (committed):**

For each model `m`, the planning-correctness rates satisfy:

> **B(m) > A(m)** by ≥ 3 percentage points
> **C(m) > A(m)** by ≥ 3 percentage points
> **B(m) > A'(m)** by ≥ 3 percentage points
> **C(m) > A'(m)** by ≥ 3 percentage points

That is: on each model independently, both substrate-derived projections (B and C) beat both reconstruction baselines (A and A') by a meaningful margin.

**Reference predictions (per-model):**

- For `gpt-4o-2024-08-06` (the parity-check model), the results should reproduce v0.4a closely. Drift from v0.4a's reported rates beyond ~2 pp is unexpected and would prompt a sanity audit (substrate, scoring, or API behavior change).
- Per-model absolute rates are not pre-registered. The prediction is on the *shape* (B > A, C > A on each model), not the *level*.

---

## §7 Pre-registered interpretation rules (DRAFTED — needs lock)

**Per-model outcome classes** — each model's pattern of arm comparisons is classified independently. The cross-model conclusion is a function of the per-model classifications.

For each model `m`, the per-model class is one of:

1. **Full replication (m):** B(m) > A(m) AND C(m) > A(m) AND B(m) > A'(m) AND C(m) > A'(m), each ≥ 3 pp.
2. **Partial replication (m):** B *or* C beats A *and* A' by ≥ 3 pp, but not both.
3. **Compression-equivalent (m):** B and/or C tie A' (within 2 pp); A' ≥ A by ≥ 3 pp. This model exhibits the v0.4a.2 compression-confound that v0.4a.2 ruled out on gpt-4o.
4. **No effect (m):** B and C tie A within the 2 pp noise floor.
5. **Reversal (m):** A or A' beats B and/or C by ≥ 3 pp.

**Cross-model outcome classes** (locked):

| Cross-model result | Architectural reading | Action |
|---|---|---|
| **All N models in class 1** (Full replication) | Cross-model claim defended at full strength. Thesis generalizes across the model field. | Paper goes to v0.3 with cross-model section reporting all N models as supporting evidence. |
| **N-1 of N in class 1, 1 in class 2** (Mostly full; one partial) | Cross-model claim mostly defended; one model shows a weaker effect. Report honestly; thesis still defensible. | Paper goes to v0.3 with cross-model section reporting the partial-replication model as a noted caveat. |
| **≥ 1 model in class 3** (Compression-equivalent) | v0.4a.2's compression-control finding does not generalize across models on this substrate. This is informative; the thesis weakens for that model class. | Paper goes to v0.3 with explicit per-model caveat. Cross-model claim becomes "the maintained-state lift over raw context holds across models, but compression-vs-substrate isolation depends on model behavior." |
| **≥ 1 model in class 4** (No effect) | The thesis fails to replicate on at least one model. Cross-model claim substantially weakens. | Paper amendment required; report the failure honestly. Empirical claim becomes scoped to "models on which the effect replicates." |
| **≥ 1 model in class 5** (Reversal) | Paper claim does not hold on that model. Investigate root cause (API behavior, substrate-model mismatch, etc.) before drawing conclusions. | Halt and audit. May indicate methodological issue rather than model-variance finding. |

**The actions above lock now.** They are not amended after seeing results.

---

## §8 Anti-curation discipline

Same as v0.4a:

- All contexts for all (model, arm, question) cells generated before any answer-generation calls flow. No iterative tuning.
- **No prompt tuning after seeing outputs.** System prompts for each arm are locked at this pre-reg's lock time. Per-model summarizer prompts (for arms A' and B) are locked here.
- All seeds, model IDs, and configuration values are in source control before the first API call.
- **No silent truncation.** Budget cap enforced by §3.5a dedup-ranking with explicit `omitted: N` counter.
- **Failures reported honestly.** If a TPM cap drops a (model, question) pair for an arm, that cell is excluded from paired comparison for that arm pair on that model (n < 75 reported with explicit count).
- **Per-model parity check:** the `gpt-4o-2024-08-06` results should reproduce v0.4a closely; drift > 2 pp on any arm prompts a sanity audit before proceeding to cross-model interpretation.

---

## §9 What this experiment does NOT test

- **Not mechanism across models.** D and E are not run. Whether projection-side discipline (warrants, lifecycle markers) gains value on other models is unmeasured. v0.5+ scope.
- **Not cross-substrate.** Still single substrate (Claude Code session logs). v0.4c2 scope.
- **Not budget variance.** Still ~285-token cap. Higher budgets unmeasured.
- **Not extraction-mechanism variance.** Beliefs are fixtured from v0.1 substrate; live extraction is v0.4c.3 scope.
- **Not end-to-end economics.** Planning-side only.
- **Not single-step vs multi-step planning.** Single-next-action task only.
- **Not the contribution of the specific implementation choices.** v0.4c1 tests the thesis (maintained state vs reconstruction) using the same implementation as v0.4a; alternative implementations of maintained state are not tested.

---

## §10 Lock signature

This pre-registration is **LOCKED at v0.4c1.1.**

- [x] D1 — substrate reused from v0.1 / v0.2.2 / v0.3 / v0.4a
- [x] D2 — four arms (A / A' / B / C); no D, no E
- [x] D3 — four models (`gpt-4o-2024-08-06`, `claude-opus-4-7`, `gemini-2.5-pro`, `claude-haiku-4-5-20251001`)
- [x] D4 — **AMENDED v0.4c1.1:** per-provider configurations recorded in §3 after build-time API verification surfaced two real divergences (`claude-opus-4-7` rejects `temperature`; `gemini-2.5-pro` requires thinking mode). Residual non-determinism + thinking-mode confound accepted; both documented as paper limitations.
- [x] D5 — ~285-token budget cap matched across B and C, with the v0.4a §3.5a dedup-ranking machinery
- [x] D6 — judge held constant (`gpt-5-mini-2025-08-07`); oracle wins on disagreement; same `combine_oracle_and_judge` as v0.3 / v0.4a
- [x] D7 — paired planning correctness, 3 pp advancement threshold, 2 pp noise floor
- [x] D8 — per-model 5-class interpretation rules locked with cross-model action commitments

**v0.4c1 lock:**
- Locked by: Sue Stranburg
- Locked on: 2026-06-04
- Lock hash: commit `641edff` (initial v0.4c1 lock)

**v0.4c1.1 re-lock (this version):**
- Re-locked by: Sue Stranburg
- Re-locked on: 2026-06-04 (same day as v0.4c1 lock)
- Lock hash: [commit SHA of this re-lock — set by the git commit that lands v0.4c1.1]
- Triggered by: build-time API verification before any context generation flowed. Two provider-specific behaviors surfaced (Anthropic Opus 4.7 rejects `temperature`; Gemini 2.5 Pro requires thinking mode). Both are real API behaviors, not design choices.

After lock: no amendments without a re-lock and re-version (v0.4c1.2, etc.).

---

**Closing anchor (Sue's framing at lock time):**

> *Proceed with 4 models, lock D4 with provider-specific seed support recorded, and lock D8 as drafted. Then commit the locked pre-reg before writing any execution code.*

> *(v0.4c1.1, after Path B chosen for Gemini):* keep `gemini-2.5-pro` with thinking enabled at a fixed budget; document as per-provider behavior; the paper records this as a real fact about how Gemini's frontier model operates rather than swapping to a smaller Gemini model to chase methodology parity.

The discipline holds: locked design → committed pre-reg → only then execution code → only then data flows.

---

## §11 Amendment log

### v0.4c1 → v0.4c1.1 (2026-06-04)

**Trigger:** Build-time API verification before any context-generation calls flowed. Per the lock-before-run + build-time-audit discipline, all four provider API endpoints were exercised with the locked D3 / D4 configurations to confirm reachability and parameter acceptance.

**Two real provider-specific behaviors surfaced:**

1. **`claude-opus-4-7` does not accept the `temperature` parameter.** Anthropic deprecated `temperature` for this model. The API returns 400 with *"`temperature` is deprecated for this model."* The model must be called without `temperature`; default Anthropic sampling is used. Verified that `claude-haiku-4-5-20251001` still accepts `temperature=0` — only Opus 4.7 has this restriction.

2. **`gemini-2.5-pro` requires thinking mode.** Setting `thinking_budget=0` (to disable thinking) returns 400 with *"This model only works in thinking mode."* Confirmed `gemini-2.5-flash` accepts `thinking_budget=0` (can run without thinking) and `gemini-2.0-flash` is deprecated. The only way to use `gemini-2.5-pro` is with a non-zero thinking budget.

**Resolution paths considered:**

For the Opus issue: no alternative within the locked design — record as a per-provider behavior, accept the divergence, document as paper limitation. Not a true amendment to the experimental design; just an honest recording of provider behavior.

For the Gemini issue, three paths considered:
- *Path A:* swap `gemini-2.5-pro` → `gemini-2.5-flash` (non-thinking). Trade-off: lose frontier-class Gemini.
- *Path B:* keep `gemini-2.5-pro` with `thinking_budget=2048`. Trade-off: Gemini has more effective compute per call than the other models.
- *Path C:* include both Pro (thinking) and Flash (non-thinking). Trade-off: 25% more cost; 5 models.

**Decision (Path B):** Keep `gemini-2.5-pro` with `thinking_budget=2048`. The thinking-vs-not-thinking distinction is part of how Gemini's frontier model actually operates; swapping to Flash to chase methodology parity would be avoiding a real fact about the model field. The cross-model question becomes more interesting under Path B: *"Does maintained state still produce better planning judgments even when one model has an internal thinking phase?"* Either outcome (lift survives with thinking; lift vanishes with thinking) is informative.

**What changed in the pre-reg:**

- §1 D4 (per-model configurations): rewrote to record the per-provider divergences explicitly. Status reads `RESOLVED (v0.4c1.1 amendment)`.
- §3 (Models and locked configurations): per-model config blocks updated. `claude-opus-4-7` block notes `temperature: NOT SUPPORTED`. `gemini-2.5-pro` block records `thinking_budget: 2048 (REQUIRED)`.
- §10 lock signature: re-lock entry added; D4 marked as amended.
- Status header at top: reflects amendment to v0.4c1.1.

**What did NOT change:** D1 (substrate), D2 (arm set), D3 (which four models), D5 (budget), D6 (scoring), D7 (effect-size thresholds), D8 (interpretation rules), §2 (arm definitions), §4 (context construction protocol), §5 (scoring methodology), §6 (predictions), §7 (interpretation rules), §8 (anti-curation discipline), §9 (scope limits). The experimental design is unchanged.

**Discipline reflection:** v0.4c1.1 is a textbook application of the build-time-audit-is-discipline memory. Verifying the four provider endpoints before any data flowed surfaced two real provider behaviors that the locked design implicitly assumed away. Honoring them with an explicit amendment log is the discipline working as intended. The amendment trace is part of the experiment's provenance.

---

*Drafted 2026-06-04 as part of the paper-publication-gate experimental program. Cross-references: ``project_paper_scope_discipline.md`` (internal memory note), ``project_belief_stack_cost_frontier.md`` (internal memory note), [`paper/MAINTAINED_STATE_AS_PLANNING_PRIMITIVE_v0.2.md`](../paper/MAINTAINED_STATE_AS_PLANNING_PRIMITIVE_v0.2.md).*
