# Operational Belief Substrate — Construction Notes

_Locked as part of step 5b of the operational v0.1 lock sequence._

This document records how `operational_beliefs.jsonl` is derived from TKOS Phase 2 artifacts, what each field means, and what the substrate's actual shape looks like once persisted. The substrate is read-only after this step.

---

## 1. What 5b is and is not

**Is:**
- Persists the 11 belief types from §2.3 of the pre-registration to `data/operational_beliefs.jsonl`, in the locked schema, in topological order.
- Uses the same derivation logic the scorer (5a) applied in-memory; the algorithm is in `score_operational_label.py`, the artifact is in `operational_beliefs.jsonl`.

**Is not:**
- Question construction (that's 5c, blind to this file)
- Answer generation
- Any LLM call
- A re-derivation of the upstream TKOS belief substrate (which stays as-is in `phase2_belief_timelines.jsonl`)

---

## 2. Inputs

| File | Purpose |
|---|---|
| `tkos_log_replay/data/sessions_normalized.jsonl` | Per-turn ledger with text + tool_uses + tool_results |
| `tkos_log_replay/data/reasoning_ledger.jsonl` | Classified ledger (operation_type, warrant) |
| `tkos_log_replay/data/phase2_belief_timelines.jsonl` | The 8 existing TKOS belief types with events |
| `tkos_log_replay/data/phase2_sample.json` | Eligible session set (164 sessions) |

The substrate restricts to sessions in `phase2_sample.json` that also have rows in `sessions_normalized.jsonl` — 164 sessions, all matching, all eligible.

---

## 3. Topological construction order (locked)

1. **Primary beliefs** (8 TKOS types projected into v0.1 schema with `user_approval_required → user_approval_pending` rename, plus `validation_complete` derived as a primary born at validation-tool-success turns).
2. **Composites** (`action_ready` / `action_blocked`) — one belief instance per action-proposal turn, classified at-T against active blockers.
3. **`failure_signature_active`** — born at the first turn where a signature reaches ≥3 occurrences within K=20 turns; retired when the signature ages out or is replaced.

Topological ordering matters because composites read primary state, and the signature recurrence rule reads tool-error timing. Reordering would yield stale composites.

---

## 4. Locked schema per belief instance

Each line of `operational_beliefs.jsonl` is one belief instance. **All 13 schema fields below are present in every record.** Four `_underscore_prefixed` fields are private metadata for audit / debugging, not part of the locked schema.

| Field | Type | Source |
|---|---|---|
| `belief_id` | string | `bel-{12 hex of sha256(session\|type\|birth_turn\|anchor)}`; stable per instance |
| `session_id` | string | TKOS session id (e.g. `main::32a6ee2f-...`) |
| `belief_type` | string | one of the 11 |
| `operational_claim` | string | the locked claim text per type (see §5) |
| `holder` | `"assistant"` | single-holder v0.1 |
| `turn_first_seen` | int | birth turn of this belief instance |
| `turn_last_updated` | int | most recent event affecting this instance (refresh / retire / contradict) |
| `lifecycle_state` | enum | `active` \| `weakened` \| `contradicted` \| `retired` |
| `warrant_evidence_turns` | list[int] | turns where event_type ∈ {born, refreshed, reconfirmed} |
| `counterevidence_turns` | list[int] | turns where event_type ∈ {weakened, contradicted} |
| `decay_status` | enum | `fresh` \| `decaying` \| `stale` (at retirement or session-end if still active) |
| `revision_trail` | list[obj] | per-event diff: `{turn, prior_state, new_state, trigger}` |
| `current_authority` | enum | `asserted_by_assistant` \| `confirmed_by_tool` \| `confirmed_by_user` |

Private metadata (audit-only):
- `_origin`: `tkos_phase2_projection` / `derived_new` / `derived_composite` / `derived_signature`
- `_active_blockers` (composites): which blocker beliefs were active at proposal turn
- `_half_life_turns` (composites): the half-life used for decay calc
- `_signature` (failure_signature_active): the matched `(tool_name, normalized_args, normalized_error)` triple

---

## 5. Operational claim text per type (locked)

The `operational_claim` is fixed text per `belief_type`. This is the propositional content of the belief — what is being asserted, in substrate-agnostic language. Locked here once; the rendering layer (5c+) reads it from each belief instance verbatim.

| belief_type | operational_claim |
|---|---|
| pipeline_running | a long-running pipeline action is currently executing |
| pipeline_failed | the most recent pipeline action ended in failure |
| issue_under_diagnosis | the assistant is actively investigating an error |
| fix_attempted | a fix has been applied but not yet validated |
| validation_pending | validation has not yet been observed for the most recent fix |
| validation_complete | validation has been observed successfully for the most recent fix |
| user_approval_pending | the assistant has requested approval and has not received it |
| action_ready | the assistant believes preconditions for the proposed next action are met |
| action_blocked | the assistant believes one or more preconditions block proceeding with the proposed action |
| report_ready | an output artifact is ready for user review |
| failure_signature_active | the same failure signature has recurred at least 3 times in the recent window |

---

## 6. Field derivation rules

### 6.1 `lifecycle_state`

The terminal event of the belief's event list determines the lifecycle state:

- `born` / `refreshed` / `reconfirmed` (last event) → `active`
- `weakened` (last event) → `weakened`
- `contradicted` (last event) → `contradicted`
- `retired` (last event) → `retired`

For NEW types derived during this step:
- `validation_complete`: `contradicted` if a subsequent `fix_attempted` belief is born after the VC's birth_turn (because a new fix invalidates the prior validation); else `active`.
- `action_ready` / `action_blocked`: always `active` at their birth turn (composites are point-in-time signals — they don't have refresh events in v0.1).
- `failure_signature_active`: `retired` if the signature ages out (no recurrence for K turns) or is replaced by a different recurrent signature; `active` otherwise.

Note: `weakened` doesn't appear in the persisted substrate because TKOS Phase 2's existing events don't use it as a terminal event type. Recorded in the audit as a near-zero count.

### 6.2 `warrant_evidence_turns` vs `counterevidence_turns`

For TKOS-projected beliefs, derived from the events list:
- warrant: turns where `event_type ∈ {born, refreshed, reconfirmed}`
- counterevidence: turns where `event_type ∈ {weakened, contradicted}`

For NEW types: warrant turns are the supporting moments (validation-tool-success turn for VC; proposal turn for composites; recurrence turns for signature). Counterevidence turns are the contradicting events (subsequent fix_attempted for VC; none for composites in v0.1; not currently used for signature).

### 6.3 `decay_status`

Computed at construction time as `age_turns / half_life_turns`:
- `< 0.5` → `fresh`
- `0.5 to 1.0` → `decaying`
- `≥ 1.0` → `stale`

`age_turns = turn_at_evaluation − turn_last_updated`, where `turn_at_evaluation = session_end` for active beliefs and `turn_last_updated` itself for retired (i.e., decay locked at retirement).

For TKOS-projected beliefs, the half_life is converted from the upstream `half_life_seconds` field using the coarse conversion **1 turn ≈ 30 seconds**. This is a rough approximation; precise per-turn timing requires the `timestamp` field on each turn and is out of scope for v0.1.

For NEW types, half-lives are locked:
- `validation_complete`: 60 turns (~30 min)
- `action_ready` / `action_blocked`: 5 turns
- `failure_signature_active`: 10 turns

### 6.4 `revision_trail`

The list of lifecycle events, each with:
- `turn`: turn_idx of the event
- `prior_state`: the previous `event_type` (or null at birth)
- `new_state`: this event's `event_type`
- `trigger`: the reason or source (e.g., `lifecycle_event`, `validation_tool_success`, `signature_aged_out`, `action_proposal; blockers_active=[validation_pending]`)

This is the substrate field most likely to be useful for downstream answer-grounding: it captures WHAT changed and WHY, in a form an LLM can read without prompt scaffolding.

### 6.5 `current_authority`

Default authority per belief type, fixed in `DEFAULT_AUTHORITY`:

- `confirmed_by_tool`: pipeline_running, pipeline_failed, validation_complete, failure_signature_active (these are derived from tool output observation)
- `asserted_by_assistant`: issue_under_diagnosis, fix_attempted, validation_pending, user_approval_pending, action_ready, action_blocked, report_ready (these are assistant-asserted operational state)
- `confirmed_by_user`: not used in v0.1 (would require modeling user-approval events as authority transitions; deferred to v0.2)

**Authority is set at birth and not updated for lifecycle transitions in v0.1.** A `user_approval_pending` belief retired by `user_provided_approval` keeps its birth-time `asserted_by_assistant` authority. v0.2 candidate: time-varying authority field that updates on lifecycle events.

---

## 7. Substrate audit — actual shape

| Statistic | Value |
|---|--:|
| Total belief instances | **13,646** |
| Sessions with at least one belief | 147 / 164 |
| Sessions with zero beliefs | 17 (short or non-action sessions) |

### By belief_type

| belief_type | instances |
|---|--:|
| fix_attempted | **7,263** (the dominant type — assistant code-change actions) |
| action_blocked | 1,651 |
| issue_under_diagnosis | 1,340 |
| validation_pending | 1,119 |
| user_approval_pending | 526 |
| action_ready | 430 |
| pipeline_running | 422 |
| validation_complete | 288 |
| pipeline_failed | 252 |
| report_ready | 175 |
| **failure_signature_active** | **15** (deliberately sparse — see §8) |

### By lifecycle_state

| state | instances | share |
|---|--:|--:|
| retired | 9,861 | 72% |
| active | 3,216 | 24% |
| contradicted | 569 | 4% |
| weakened | 0 | 0% (TKOS events don't use weakened as terminal) |

### By current_authority

| authority | instances | share |
|---|--:|--:|
| asserted_by_assistant | 12,669 | 93% |
| confirmed_by_tool | 977 | 7% |
| confirmed_by_user | 0 | 0% (deferred to v0.2) |

---

## 8. Sparsity notes (rules NOT loosened)

Per the locked discipline, no scoring rule was loosened during substrate persistence. Sparsity is reported here as a constraint on 5c construction, not as a reason to relax detection.

### 8.1 `failure_signature_active` — 15 instances across 147 sessions

Per the scorer audit at 5a, only 3 positive-oracle sample points existed across 480 quartile T-positions. Persisting the full belief timeline across all turns yielded 15 instances. This is consistent: most TKOS sessions don't contain a 3-recurrence failure signature within any 20-turn window.

For 5c construction targeting 5+ positive `repeated_failure` candidates per category, this means:
- The construction script will need to scan **every turn** of every session for failure_signature_active windows, not just quartile T-positions.
- If the 15 instances span fewer than 5 distinct sessions, the per-session cap of 3 may bind. The audit confirms session-coverage of the 15 instances; if too concentrated, the construction script will document the constraint and use however many positive candidates exist.

### 8.2 `action_blocked` >> `action_ready` (1,651 vs 430)

In TKOS sessions, when assistants propose actions, the operational state usually has at least one active blocker (validation_pending, user_approval_pending, etc.). This is informative about the assistant-workflow domain rather than a defect: action proposals are often made under pending state.

For 5c construction targeting `approval_status` balance: positive candidates (`action_blocked`) are abundant; negative candidates (`action_ready`) are 430 across 147 sessions, still well above the 5-question target.

### 8.3 No `confirmed_by_user` authorities

The DEFAULT_AUTHORITY mapping does not currently emit `confirmed_by_user`. Reaching this state would require modeling user-acknowledgement events (e.g., user message after `user_approval_pending` confirms approval). This is deferred to v0.2 — for v0.1, every user-related approval transition appears under `asserted_by_assistant` (the original assertion authority) and surfaces in `revision_trail` as `user_provided_approval` triggers.

---

## 9. How a downstream consumer reads this

**Query at turn T**: "What beliefs are active at turn T for session S?"

```
active = [
    b for b in operational_beliefs
    if b.session_id == S
    and b.turn_first_seen <= T
    and (b.lifecycle_state == "active" OR b.turn_last_updated >= T)
]
```

**Variant: filter to a specific lifecycle**

```
should_pause_triggers = [
    b for b in active
    if b.belief_type in {"failure_signature_active", "action_blocked"}
    or b.lifecycle_state == "contradicted"
]
```

For richer reading (timeline of revisions), iterate `revision_trail`. For warrant inspection, read `warrant_evidence_turns` and `counterevidence_turns`. For the propositional content of the belief itself, read `operational_claim`.

---

## 10. What's frozen / not frozen

**Frozen at 5b lock:**

- `build_operational_belief_substrate.py` — the construction script
- `data/operational_beliefs.jsonl` — 13,646 belief instances (gitignored per repo convention; reproducible from the script + TKOS inputs)
- `data/operational_belief_substrate_audit.json` — audit summary including all the stats above

**Not frozen yet:**

- Question construction (`construct_questions.py`) — step 5c
- Construction-script log of files-opened — generated when 5c runs
- Belief-overlay rendering function for System B's context — locked alongside engineering parameters in §5.4

---

## 11. How to reproduce

```bash
cd /Users/sue/Documents/git/storm
source venv/bin/activate
python operational_belief_v1/build_operational_belief_substrate.py
```

Inputs that must exist (all already in the repo):
- `tkos_log_replay/data/sessions_normalized.jsonl`
- `tkos_log_replay/data/reasoning_ledger.jsonl`
- `tkos_log_replay/data/phase2_belief_timelines.jsonl`
- `tkos_log_replay/data/phase2_sample.json`

Re-running is deterministic: same inputs → identical output `.jsonl` (modulo stable sort order). The script does not read `operational_beliefs.jsonl` on re-run; it always rebuilds from upstream.

---

## 12. Audit trail

| Field | Value |
|---|---|
| Construction version | v0.1 |
| Locked | 2026-06-01 |
| Author | Susan Stranburg |
| Builder script | `build_operational_belief_substrate.py` |
| Companion pre-registration | [OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md](OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.1.md) |
| Companion scorer | [score_operational_label.py](score_operational_label.py) (5a) |
| Inputs read | TKOS Phase 2 artifacts (see §2) |
| Inputs NOT read | any 5c construction output, any LLM endpoint, any answer artifact |
