# Context Construction Notes — Operational Belief v0.1

_Locked as part of the context-construction step (pre-answer-generation)._

This document records how the per-question grounding payloads were assembled for System A (raw log only) and System B (raw log + operational belief overlay). The architectural decision under test is whether the **additive** belief overlay reduces stale-state errors compared with the same raw log alone.

---

## 1. Scope and discipline

**Does:**
- Build per-question contexts for both systems against the frozen `questions.jsonl` (75 questions).
- For System A: render the last K=20 turns of the session up to turn T, with the locked 500-token cap per tool_result.
- For System B: render exactly the same raw-log payload PLUS a belief overlay describing operational beliefs active at T.
- Emit context records and a combined audit covering token distributions, truncations, cutoff compliance, overlay shapes, and belief-type representation.

**Does not:**
- Generate any answers.
- Make any LLM call.
- Score or judge anything.
- Inspect answer quality (no answers exist yet to inspect).

---

## 2. Locked parameters (§3.1 of the pre-reg)

| Parameter | Value |
|---|---|
| K (recent-turn window) | **20** |
| Tool output cap | **500 tokens** per tool_result (cl100k_base) |
| Tokenizer | cl100k_base (tiktoken) |
| System B design | **additive** — raw log + overlay; never replacement |

---

## 3. Architectural cutoff enforcement (§5.2)

For each question with target turn T:

- **System A**: the raw-log render includes only turns with `turn_idx ≤ T`. Verified at render-time with an assertion that raises on any leak; audit reports 0 violations.
- **System B raw-log half**: identical to System A's payload (additivity guarantee), so same compliance.
- **System B overlay**: a belief is INCLUDED only if `turn_first_seen ≤ T` AND its at-T lifecycle is one of `{active, weakened, contradicted}`. The at-T lifecycle is computed by replaying `revision_trail` up to events with `turn ≤ T`. Beliefs retired at or before T are EXCLUDED (they aren't currently believed). The belief's `warrant_evidence_turns`, `counterevidence_turns`, and `revision_trail` fields shown in the render are filtered to entries ≤ T.

Audit counters:

- `system_a.cutoff_violations`: **0**
- `system_b.rendered_cutoff_violations`: **0**
- `system_b.beliefs_needing_cutoff_filter`: **400** — informational only. This counts beliefs whose source `revision_trail` had at least one event > T (so the filter had work to do). The rendered output is cutoff-clean; this number is a transparency hook, not a violation.

---

## 4. Additivity guarantee

The pre-reg's lock states: *"System B must be additive. It receives everything System A receives, plus the belief overlay. Do not replace raw log context with beliefs."*

Verified programmatically:

- The B builder imports `render_raw_log_payload()` directly from the A builder. No alternate raw-log render path exists.
- Per-question audit check: `contexts_b[q].log_tokens == contexts_a[q].token_count`. Audit reports `raw_log_parity_violations = 0` across all 75 questions.

This is the architectural lever the spec's §"Empirical status" specifically calls out as the one Stack-Grounded v0.1 did not test.

---

## 5. Rendering — System A

Each turn renders as:

```
[turn N / role]
<text>
<thinking>...</thinking>           (only if present)
<tool_use TOOL_NAME>input_summary</tool_use>
<tool_result is_error=true>output_summary (capped to 500 tokens with "[+M tokens elided]")</tool_result>
```

Multiple turns concatenated with `\n\n`. The window is the last K turns up to and including T. If the session has fewer than K turns ending at T, the payload includes whatever exists (no padding).

**Tool output cap behavior**: 0 tool outputs were truncated across all 75 contexts. Upstream `parse_sessions.py` already truncates `output_summary` to ~600 chars (~150 tokens), so the 500-token cap is non-binding on the current substrate. This matches the K/cap diagnostic from the lock-sequence step 2. Cap is locked at 500 as the design ceiling, not the binding constraint.

---

## 6. Rendering — System B overlay

After the raw-log payload, the overlay section is appended:

```
=== Operational beliefs active as of turn T ===
- belief_type:        validation_pending
  operational_claim:  "validation has not yet been observed for the most recent fix"
  state_at_turn_T:    active
  warrant:            2 supporting observation(s) at turn(s) [12, 15]
  first_seen:         turn 12
  last_updated:       turn 15
  authority:          asserted_by_assistant
  revision_trail:
      turn 12: none → born  (trigger: lifecycle_event)
      turn 15: born → refreshed  (trigger: status_check)
- belief_type:        action_blocked
  ...
```

For each belief currently active at T (lifecycle ∈ `{active, weakened, contradicted}`), the overlay shows the locked schema fields. Substrate-agnostic vocabulary: no TopicSpace jargon, no NDS, no market-domain terms.

**Empty-overlay sentinel**: if no beliefs are active at T, the overlay reads `"(no active operational beliefs at this turn)"`. 0 of 75 questions hit this case (every question has at least one active belief at T).

---

## 7. Distribution stats

### 7.1 System A — raw-log payload

| Metric | Value |
|---|---|
| Contexts written | 75 / 75 |
| Tokens — median / p90 / max | 1,662 / 3,416 / 4,637 |
| Tool outputs truncated | 0 |
| Cutoff violations | 0 |

### 7.2 System B — raw log + overlay (additive)

| Metric | Value |
|---|---|
| Contexts written | 75 / 75 |
| Raw-log tokens (same as A) — median / p90 / max | 1,662 / 3,416 / 4,637 |
| Overlay tokens — median / p90 / max | 1,331 / 6,240 / **42,362** |
| Combined tokens — median / p90 / max | 3,348 / 7,078 / **43,203** |
| Active beliefs at T — median / p90 / max | 11 / 46 / **355** |
| Empty overlays | 0 |
| Tool outputs truncated | 0 |
| Beliefs needing cutoff-filter (informational) | 400 |
| Rendered cutoff violations | 0 |

**Overlay-size flag**: the maximum overlay is 42,362 tokens — a single session-turn with 355 simultaneously-active operational beliefs. This is consistent with the locked additive design: the overlay includes every belief active at T, with no curation or truncation. Long sessions with high concurrent operational state will have large overlays.

This is a substantive observation, not a defect. The architectural test is whether the additive overlay helps the LLM under realistic conditions. If the answer-generation step finds that 40K+ token overlays degrade performance (or hit context-window limits), that's itself a finding — and the choice between "let the overlay be unbounded" vs "cap and prioritize beliefs" becomes a v0.2 design question rather than a v0.1 issue to patch.

For v0.1: no overlay truncation. The locked design is honored.

### 7.3 Overlay belief-type representation (across all 75 contexts)

| belief_type | total appearances |
|---|--:|
| action_blocked | 839 |
| fix_attempted | 295 |
| action_ready | 229 |
| validation_complete | 162 |
| pipeline_running | 131 |
| pipeline_failed | 51 |
| report_ready | 44 |
| issue_under_diagnosis | 42 |
| validation_pending | 37 |
| user_approval_pending | 25 |
| failure_signature_active | 6 |

All 11 locked belief types are represented in at least one context overlay. Sparse types (`failure_signature_active` at 6; `user_approval_pending` at 25) reflect the substrate-level sparsity surfaced in the 5b audit — rules were not loosened.

---

## 8. Substrate cleanup surfaced during context build

During the first run of the context builder, the overlay showed 5 instances of belief_type `deploy_pending`. The locked §2.3 typology had REPLACED `deploy_pending` with the more generic `action_ready` / `action_blocked` composites — meaning `deploy_pending` should not appear in `operational_beliefs.jsonl` at all.

The bug was in step 5b's `project_existing_beliefs` function: it projected ALL TKOS belief types without filtering to the locked 11-type typology. Fix applied: an `ALLOWED_TKOS_TYPES` whitelist of the 7 TKOS types that map directly to v0.1 types. `deploy_pending` is excluded; the operational variant captures similar moments via the `ACTION_PATTERNS` regex inside the `action_ready` / `action_blocked` composite derivation.

Substrate rebuilt: 13,646 → 13,481 instances (165 TKOS `deploy_pending` instances dropped). All other counts unchanged. Audit refreshed.

---

## 9. What's frozen at this step

- `build_log_context_a.py`
- `build_belief_overlay_context_b.py`
- `data/contexts_a.jsonl` (75 records; gitignored, reproducible)
- `data/contexts_b.jsonl` (75 records; gitignored, reproducible)
- `data/context_construction_audit.json`
- The locked rendering format for both systems

---

## 10. What's NOT done at this step (deferred to next)

- Answer generation (model + prompt + temperature + seed + max_tokens) — these get locked at first-run alongside the answer-generation script.
- Deterministic scoring of generated answers.
- Preference judging of paired answers.

Per the user's locked rhythm: build, audit, pause. Next step is answer generation only, against these frozen contexts.

---

## 11. How to reproduce

```bash
cd /Users/sue/Documents/git/storm
source venv/bin/activate

# Substrate (if not already built)
python operational_belief_v1/build_operational_belief_substrate.py

# Context A then B (B imports A's render function for parity)
python operational_belief_v1/build_log_context_a.py
python operational_belief_v1/build_belief_overlay_context_b.py
```

Inputs that must exist:

- `operational_belief_v1/questions.jsonl` (frozen at step 5c)
- `operational_belief_v1/data/operational_beliefs.jsonl` (rebuilt at step 5b after the deploy_pending fix)
- `tkos_log_replay/data/sessions_normalized.jsonl`

Both context builders are deterministic.

---

## 12. Audit trail

| Field | Value |
|---|---|
| Construction version | v0.1 |
| Locked | 2026-06-01 |
| Author | Susan Stranburg |
| A builder | `build_log_context_a.py` |
| B builder | `build_belief_overlay_context_b.py` (imports `render_raw_log_payload` from A for parity) |
| Companion pre-registration | [OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md](OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md) |
| Companion notes | [OPERATIONAL_BELIEF_SUBSTRATE_NOTES.md](OPERATIONAL_BELIEF_SUBSTRATE_NOTES.md), [QUESTION_SET_CONSTRUCTION_NOTES.md](QUESTION_SET_CONSTRUCTION_NOTES.md) |
| Inputs read | `questions.jsonl`, `operational_beliefs.jsonl`, `sessions_normalized.jsonl` |
| Inputs NOT read | any answer artifact, any judge artifact, any scorer output |
