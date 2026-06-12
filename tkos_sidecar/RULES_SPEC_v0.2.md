# Belief Derivation Spec — RULES_SPEC_v0.2.1

**Date:** 2026-06-06 (v0.2 locked; amended to v0.2.1 same day per [`AUDIT_RESPONSE_2026-06-06.md`](./AUDIT_RESPONSE_2026-06-06.md))
**Status:** LOCKED at v0.2.1. This is the lock-before-code artifact for the TKOS write-path build.
**Implementations:** the streaming engine in `tkos_sidecar/rules.py` and the batch engine in `operational_belief_v1/build_operational_belief_substrate.py` (restricted to the v0.2 belief subset) must both implement this spec. Equivalence is defined here, not in either codebase.

**v0.2 → v0.2.1 amendments:** finding 8 (deterministic rule conflict on repeated failures): tightened `pipeline_failed_born` precondition to require no matching active belief. Findings 1, 5, and 10 are bridged here with notes pointing to TKOS scope v0.2.1 §4.1 (the adapter taxonomy / ignored-known accounting) and INTEGRATION_PATTERN v0.1.1 §3.5 (adapter normalization rules). RULES_SPEC §3.8 (computed `action_blocked`) is unchanged; its read-path rendering is scoped in `TKOS_READ_PATH_MIGRATION_v0.2.md`.

**Predecessors:**
- [`TKOS_WRITE_PATH_SCOPE_v0.2.md`](./TKOS_WRITE_PATH_SCOPE_v0.2.md) — the software scope this spec serves.
- [`operational_belief_v1/build_operational_belief_substrate.py`](../operational_belief_v1/build_operational_belief_substrate.py) — the v0.1 batch engine to be restricted to this subset.
- [`TKOS_SIDECAR_SKETCH_v0.1.md`](./TKOS_SIDECAR_SKETCH_v0.1.md) §3 — the original belief typology this spec formalizes.

---

## Purpose

This document answers one question:

> *Given a normalized event stream, how does a belief enter, evolve, and leave state?*

It does not describe a sidecar. It does not describe SQL. It does not describe a streaming engine. Those are implementations of this spec.

If two engineers implement what is below independently, they should produce the same `belief_events` trace on the same event stream. That is the load-bearing claim of the document.

The spec is the system definition. Everything downstream is plumbing.

---

## §1 Canonical event contract

Every event the rule engine sees is a record over these fields. Rules cannot reference fields outside this contract. Implementations cannot inject runtime context (wallclock now, environment variables, etc.) into rule evaluation.

**Adapter responsibility (v0.2.1 clarification per finding 5):** the canonical contract below is what the *rule engine* sees. The *adapter* is responsible for translating source-specific records (e.g., Codex `function_call` / `function_call_output` envelopes) into events that match this contract. Field derivation rules for the Codex adapter are locked in [`INTEGRATION_PATTERN_v0.1.1.md`](./INTEGRATION_PATTERN_v0.1.md) §3.5. Rules in §3 always read from the canonical contract, never from source-native fields directly.

| Field | Type | Required | Description |
|---|---|---|---|
| `source_event_id` | string | yes | Stable, deterministic identity (`sha256` of source line + provenance, or native ID if the source provides one). Primary key. |
| `session_id` | string | yes | Session-local scope. Beliefs are session-local in v0.2. |
| `turn_idx` | int | yes | Monotonic per session. Increments on `user_message` OR `task_start`, whichever comes first. |
| `event_idx` | int | yes | Monotonic within a turn. Resets to 0 at each turn boundary. |
| `event_type` | enum | yes | One of: `user_message`, `assistant_message`, `assistant_reasoning`, `tool_call`, `tool_result`, `task_start`, `task_completion`. |
| `timestamp` | ISO 8601 string | yes | From the source. Rules do not compare wallclock; ordering is by `(session_id, turn_idx, event_idx)`. |
| `actor` | enum | yes | One of: `user`, `assistant`, `tool`, `system`. Derived from `event_type`. |
| `tool_name` | string | optional | Required when `event_type ∈ {tool_call, tool_result}`. |
| `command` | string | optional | The exact command run; required for shell `tool_call` and shell `tool_result`. |
| `exit_code` | int | optional | Required when `event_type = tool_result` for shell commands. |
| `paths` | string[] | optional | List of file paths touched (writes, edits, reads). Empty list when no paths. |
| `payload` | object | optional | Event-type-specific content (message text, reasoning content, etc.). Type-scoped fields described in §1.1. |
| `parent_event_id` | string | optional | The `source_event_id` of a logically preceding event in the same causal chain — e.g., a `tool_result`'s parent is its `tool_call`. Null when no parent. |

### §1.1 Payload shape per event_type

| `event_type` | Required `payload` fields |
|---|---|
| `user_message` | `content: string` |
| `assistant_message` | `content: string` |
| `assistant_reasoning` | `content: string` |
| `tool_call` | (none — `tool_name` and `command` are top-level) |
| `tool_result` | `output: string`, `stderr_first_line: string \| null` |
| `task_start` | `task_name: string` |
| `task_completion` | `final_status: string` |

Rules can reference `payload.content`, `payload.output`, etc. by name. No deeper nesting is permitted.

### §1.2 What rules may NOT do

- Read fields outside this contract.
- Compute wallclock time. Use only `timestamp` from the event.
- Call out to external services (LLMs, databases beyond the substrate, web).
- Mutate the event. Events are immutable from rule perspective.
- Reference future events. Rules see only the event currently being processed and the current `active_beliefs` state derived from prior events.

---

## §2 Supported belief types (v0.2)

Seven primitive belief types plus one computed belief.

### §2.1 Primitives (minted/retired by event-triggered rules)

| Type | One-line meaning |
|---|---|
| `fix_attempted` | A change has been made intended to address an identified failure. |
| `validation_pending` | A validation has been initiated and has not yet returned. |
| `validation_complete` | A validation has returned successfully and has not been invalidated. |
| `pipeline_running` | A long-running tool call has started and has not yet returned (retro-minted). |
| `pipeline_failed` | A tool call has returned a failure (non-zero exit). |
| `user_approval_pending` | The assistant has asked the user for explicit approval and has not received a response. |
| `report_ready` | A report or artifact has been produced. |

### §2.2 Computed beliefs (derived from primitives at query time)

| Type | One-line meaning |
|---|---|
| `action_blocked` | At least one blocker primitive is active. Composed at `overlay()` / `risk()` / `state()` time; not minted by any event. Derivation in §3.8. |

### §2.3 Deferred to v0.3+

- `failure_signature_active` — a recurring failure mode that has reappeared in the session. Requires nontrivial signature matching; deferred.

### §2.4 Belief record shape

Every belief instance in the substrate carries:

| Field | Type | Description |
|---|---|---|
| `belief_id` | string | Stable identity (e.g., UUID generated at birth). |
| `session_id` | string | Session scope. |
| `belief_type` | enum | One of §2.1's primitive types. Computed beliefs are not persisted. |
| `claim` | string | Short rendered string (e.g., "validation pending — pytest at turn 14"). |
| `lifecycle_state` | enum | One of: `active`, `weakened`, `contradicted`, `retired`. |
| `authority` | enum | One of: `asserted_by_assistant`, `confirmed_by_tool`, `confirmed_by_user`. Highest authority observed so far. |
| `created_turn` | int | The `effective_turn` at birth (§4). |
| `last_updated_turn` | int | The `observed_at_turn` of the most recent transition. |
| `created_by_event_id` | string | `source_event_id` of the event that minted this belief. |
| `revision_trail` | list | Reference to `belief_events` rows for this `belief_id`. |

---

## §3 Derivation rules (per primitive belief type)

Each rule uses the format:

```
RULE: rule_name
TRIGGERS_ON: <event_type>
PRECONDITIONS:
  - <constraint on the event>
  - <constraint on active_beliefs state, if any>
ACTION:
  - <transition>
EFFECTIVE_TURN: <expression>
OBSERVED_AT_TURN: <expression>
AUTHORITY: <enum>
NOTE_TEMPLATE: "<string>"
```

For each belief type, the full set of rules that operate on it is enumerated. If two rules can fire on the same event, both fire (no implicit ordering); their effects are independent.

### §3.1 `fix_attempted`

**Born.**

```
RULE: fix_attempted_born_from_edit
TRIGGERS_ON: tool_call WHERE tool_name in {"write_file", "edit_file", "apply_patch"}
PRECONDITIONS:
  - paths is non-empty
  - There exists at least one active belief of type pipeline_failed OR validation_pending OR validation_complete (the failure context being addressed)
ACTION:
  - Mint fix_attempted with paths = event.paths, claim references the most recent failure or validation context
EFFECTIVE_TURN: event.turn_idx
OBSERVED_AT_TURN: event.turn_idx
AUTHORITY: asserted_by_assistant
NOTE_TEMPLATE: "fix attempted via {tool_name} on {paths} at turn {turn_idx}"
```

**Retired.**

```
RULE: fix_attempted_retired_by_validation
TRIGGERS_ON: tool_result WHERE event.exit_code == 0 AND event.parent_event_id matches a tool_call that ran validation
PRECONDITIONS:
  - Active fix_attempted belief exists whose paths overlap with the validation's scope
ACTION:
  - Retire all matching fix_attempted beliefs
EFFECTIVE_TURN: event.turn_idx
OBSERVED_AT_TURN: event.turn_idx
NOTE_TEMPLATE: "fix attempt validated at turn {turn_idx}"
```

```
RULE: fix_attempted_superseded
TRIGGERS_ON: tool_call WHERE tool_name in {"write_file", "edit_file", "apply_patch"}
PRECONDITIONS:
  - Active fix_attempted belief exists
  - The new event's paths overlap with an existing fix_attempted belief's paths
ACTION:
  - Retire the prior overlapping fix_attempted belief (the new one will be minted by fix_attempted_born_from_edit)
EFFECTIVE_TURN: event.turn_idx
OBSERVED_AT_TURN: event.turn_idx
NOTE_TEMPLATE: "fix attempt superseded by new edit at turn {turn_idx}"
```

### §3.2 `validation_pending`

**Born.**

```
RULE: validation_pending_born
TRIGGERS_ON: tool_call WHERE tool_name in VALIDATION_TOOLS or command matches VALIDATION_COMMAND_PATTERNS
ACTION:
  - Mint validation_pending with claim referencing tool_name and command
EFFECTIVE_TURN: event.turn_idx
OBSERVED_AT_TURN: event.turn_idx
AUTHORITY: asserted_by_assistant
NOTE_TEMPLATE: "validation pending — {tool_name} {command} initiated at turn {turn_idx}"
```

`VALIDATION_TOOLS` and `VALIDATION_COMMAND_PATTERNS` are spec constants defined in §6.

**Contradicted.**

```
RULE: validation_pending_contradicted_by_failure
TRIGGERS_ON: tool_result WHERE event.exit_code != 0
PRECONDITIONS:
  - There exists an active validation_pending whose claim references a tool_call with matching parent_event_id (or matching tool_name + command if parent_event_id is null)
ACTION:
  - Contradict the matching validation_pending
EFFECTIVE_TURN: event.turn_idx
OBSERVED_AT_TURN: event.turn_idx
NOTE_TEMPLATE: "validation pending contradicted — failed at turn {turn_idx}"
```

**Retired.**

```
RULE: validation_pending_retired_by_success
TRIGGERS_ON: tool_result WHERE event.exit_code == 0
PRECONDITIONS:
  - There exists an active validation_pending whose claim references a matching tool_call (parent_event_id match or tool_name+command match)
ACTION:
  - Retire the matching validation_pending (validation_complete will be minted by its own rule)
EFFECTIVE_TURN: event.turn_idx
OBSERVED_AT_TURN: event.turn_idx
NOTE_TEMPLATE: "validation pending retired — succeeded at turn {turn_idx}"
```

### §3.3 `validation_complete`

**Born.**

```
RULE: validation_complete_born
TRIGGERS_ON: tool_result WHERE event.exit_code == 0
PRECONDITIONS:
  - The event's parent tool_call matched VALIDATION_TOOLS or VALIDATION_COMMAND_PATTERNS
ACTION:
  - Mint validation_complete referencing the tool_name, command, and the parent tool_call's turn_idx
EFFECTIVE_TURN: event.turn_idx
OBSERVED_AT_TURN: event.turn_idx
AUTHORITY: confirmed_by_tool
NOTE_TEMPLATE: "validation complete — {tool_name} {command} passed at turn {turn_idx}"
```

**Weakened.**

```
RULE: validation_complete_weakened_by_edit
TRIGGERS_ON: tool_call WHERE tool_name in {"write_file", "edit_file", "apply_patch"}
PRECONDITIONS:
  - Active validation_complete belief exists
  - The edit's paths overlap with the validation's scope (the paths reported in the prior tool_result's output, or the workspace if scope is unspecified)
ACTION:
  - Weaken the matching validation_complete (it remains active but its lifecycle_state becomes `weakened` — read-path may de-prioritize)
EFFECTIVE_TURN: event.turn_idx
OBSERVED_AT_TURN: event.turn_idx
NOTE_TEMPLATE: "validation potentially invalidated by edit to {paths} at turn {turn_idx}"
```

**Retired.**

```
RULE: validation_complete_retired_by_superseding_validation
TRIGGERS_ON: validation_complete_born firing
PRECONDITIONS:
  - An older validation_complete belief covers the same scope (same tool_name + overlapping paths)
ACTION:
  - Retire the older validation_complete
EFFECTIVE_TURN: event.turn_idx
OBSERVED_AT_TURN: event.turn_idx
NOTE_TEMPLATE: "validation superseded by newer pass at turn {turn_idx}"
```

### §3.4 `pipeline_running`

The only belief type that uses retro-minting in v0.2.

**Born (retro-minted).**

```
RULE: pipeline_running_born_retroactive
TRIGGERS_ON: scan after each event ingest
PRECONDITIONS:
  - There exists a tool_call event E whose turn_idx is T
  - No tool_result with parent_event_id == E.source_event_id has been observed within the next K=3 events
  - No pipeline_running belief already exists referencing E.source_event_id
ACTION:
  - Mint pipeline_running referencing E
EFFECTIVE_TURN: T  (the original tool_call's turn)
OBSERVED_AT_TURN: current event's turn_idx  (when the retro-mint condition is met)
AUTHORITY: asserted_by_assistant
NOTE_TEMPLATE: "pipeline_running — {tool_name} {command} from turn {effective_turn} (observed at turn {observed_at_turn})"
```

Note: `effective_turn` strictly less than `observed_at_turn` is the v0.2 retro-mint signature. The read-path returns `pipeline_running` for any `state(turn=Q)` where `effective_turn <= Q`, even when `observed_at_turn > Q`.

**Contradicted / Retired.**

```
RULE: pipeline_running_resolved
TRIGGERS_ON: tool_result
PRECONDITIONS:
  - There exists an active pipeline_running belief whose referenced tool_call has source_event_id == event.parent_event_id
ACTION:
  - If event.exit_code == 0: retire the pipeline_running
  - If event.exit_code != 0: contradict the pipeline_running
EFFECTIVE_TURN: event.turn_idx
OBSERVED_AT_TURN: event.turn_idx
NOTE_TEMPLATE: "pipeline_running resolved — exit {exit_code} at turn {turn_idx}"
```

### §3.5 `pipeline_failed`

**Born.**

```
RULE: pipeline_failed_born
TRIGGERS_ON: tool_result WHERE event.exit_code != 0
PRECONDITIONS:
  - NO active pipeline_failed belief exists whose failure_signature matches this event's failure_signature
ACTION:
  - Mint pipeline_failed with claim referencing the failure_signature (§3.5.1)
EFFECTIVE_TURN: event.turn_idx
OBSERVED_AT_TURN: event.turn_idx
AUTHORITY: confirmed_by_tool
NOTE_TEMPLATE: "pipeline_failed — {tool_name} exit {exit_code} signature '{failure_signature}' at turn {turn_idx}"
```

The `pipeline_failed_born` and `pipeline_failed_strengthened` preconditions are mutually exclusive: on any failing `tool_result`, exactly one of the two rules fires. This pattern (mint-vs-refresh disambiguation) applies whenever the spec specifies both a born rule and a strengthened rule for the same belief type.

**Retired.**

```
RULE: pipeline_failed_retired_by_success
TRIGGERS_ON: tool_result WHERE event.exit_code == 0
PRECONDITIONS:
  - Active pipeline_failed belief exists for the same tool_name and overlapping command/paths
ACTION:
  - Retire the matching pipeline_failed
EFFECTIVE_TURN: event.turn_idx
OBSERVED_AT_TURN: event.turn_idx
NOTE_TEMPLATE: "pipeline_failed retired — subsequent success at turn {turn_idx}"
```

**Strengthened (same failure repeats).**

```
RULE: pipeline_failed_strengthened
TRIGGERS_ON: tool_result WHERE event.exit_code != 0
PRECONDITIONS:
  - Active pipeline_failed belief exists whose failure_signature matches this event's failure_signature
ACTION:
  - Mark the existing pipeline_failed as refreshed (no new belief minted; revision_trail updated)
EFFECTIVE_TURN: event.turn_idx
OBSERVED_AT_TURN: event.turn_idx
NOTE_TEMPLATE: "pipeline_failed refreshed — same signature recurred at turn {turn_idx}"
```

#### §3.5.1 Failure signature (v0.2 simple definition)

For a `tool_result` with non-zero exit:

```
failure_signature = exit_code + ":" + stderr_first_line
```

If `stderr_first_line` is null or empty, use `exit_code + ":" + output_first_line`. If both are null/empty, use `exit_code + ":"`.

Two `pipeline_failed` beliefs share a `failure_signature` if their signatures string-match exactly. This is intentionally crude for v0.2; richer signature matching is `failure_signature_active`'s problem and is deferred.

### §3.6 `user_approval_pending`

**Born.**

```
RULE: user_approval_pending_born
TRIGGERS_ON: assistant_message
PRECONDITIONS:
  - payload.content matches APPROVAL_REQUEST_PATTERNS (§6)
ACTION:
  - Mint user_approval_pending with claim including the matched request fragment
EFFECTIVE_TURN: event.turn_idx
OBSERVED_AT_TURN: event.turn_idx
AUTHORITY: asserted_by_assistant
NOTE_TEMPLATE: "user_approval_pending — '{request_excerpt}' at turn {turn_idx}"
```

**Retired (approved).**

```
RULE: user_approval_pending_retired_by_approval
TRIGGERS_ON: user_message
PRECONDITIONS:
  - Active user_approval_pending belief exists
  - payload.content matches APPROVAL_GRANT_PATTERNS
ACTION:
  - Retire the matching user_approval_pending; update its authority to confirmed_by_user
EFFECTIVE_TURN: event.turn_idx
OBSERVED_AT_TURN: event.turn_idx
NOTE_TEMPLATE: "user_approval_pending retired — approved at turn {turn_idx}"
```

**Contradicted (denied).**

```
RULE: user_approval_pending_contradicted_by_denial
TRIGGERS_ON: user_message
PRECONDITIONS:
  - Active user_approval_pending belief exists
  - payload.content matches APPROVAL_DENY_PATTERNS
ACTION:
  - Contradict the matching user_approval_pending; update its authority to confirmed_by_user
EFFECTIVE_TURN: event.turn_idx
OBSERVED_AT_TURN: event.turn_idx
NOTE_TEMPLATE: "user_approval_pending contradicted — denied at turn {turn_idx}"
```

### §3.7 `report_ready`

**Born.**

```
RULE: report_ready_born
TRIGGERS_ON: tool_call WHERE tool_name in {"write_file", "edit_file", "apply_patch"}
PRECONDITIONS:
  - Any path in paths matches REPORT_PATH_PATTERNS (§6)
ACTION:
  - Mint report_ready with claim referencing the matched path
EFFECTIVE_TURN: event.turn_idx
OBSERVED_AT_TURN: event.turn_idx
AUTHORITY: asserted_by_assistant
NOTE_TEMPLATE: "report_ready — {path} produced at turn {turn_idx}"
```

**Retired.**

```
RULE: report_ready_retired_by_replacement
TRIGGERS_ON: report_ready_born firing
PRECONDITIONS:
  - An older report_ready belief references the same path
ACTION:
  - Retire the older report_ready
EFFECTIVE_TURN: event.turn_idx
OBSERVED_AT_TURN: event.turn_idx
NOTE_TEMPLATE: "report_ready replaced by newer write at turn {turn_idx}"
```

### §3.8 `action_blocked` (computed, not minted)

`action_blocked` is not persisted in `belief_instances`. It is computed on demand by `overlay()`, `risk()`, and `state()` queries.

**Derivation:**

```
COMPUTED: action_blocked
WHEN_QUERIED_AT_TURN: Q
DEFINITION:
  Let blockers = active beliefs at turn Q whose belief_type ∈ {validation_pending, user_approval_pending, pipeline_failed}
  If blockers is non-empty:
    Return a synthetic action_blocked belief with claim listing the blocker types and counts
  Else:
    Return no action_blocked belief
```

The computed belief has no `belief_id`, no `revision_trail`, and is not minted into `belief_events`. It is purely a query-time derivation.

The `risk(action)` query may further filter blockers by action — only blockers relevant to the proposed action contribute to the returned `action_blocked` derivation.

---

## §4 Temporal semantics

### §4.1 The two times

| Field | Meaning |
|---|---|
| `effective_turn` | The turn at which the belief is asserted to actually be true. |
| `observed_at_turn` | The turn at which the rule fired and the belief transition was recorded. |

For most rules in §3, the two are equal. For retro-minted beliefs (the v0.2 example: `pipeline_running`), `observed_at_turn > effective_turn`.

### §4.2 Read-path semantics

A query `state(session_id, turn=Q)` returns the set of beliefs that satisfy:

- The belief's most recent belief_event with `effective_turn <= Q` puts it in lifecycle_state ∈ {`active`, `weakened`}.
- No subsequent belief_event with `effective_turn <= Q` transitions it to `contradicted` or `retired`.

The `observed_at_turn` is recorded for audit but is NOT used to filter `state(turn=Q)` results. If a belief was retro-minted with `effective_turn=5, observed_at_turn=8`, a query at `turn=6` returns it (because its effective_turn ≤ 6, even though we didn't observe it until turn 8).

This is the correctness semantics that makes the audit trail historically accurate. The substrate represents what was true at each turn, not what we knew at each turn.

### §4.3 The single ordering

There is exactly one ordering over events: the lexicographic ordering on `(session_id, turn_idx, event_idx)`. Wallclock timestamps are recorded for audit but **never** used to order events. Two events with the same `(session_id, turn_idx, event_idx)` are an error — sequence validation (TKOS scope §6.2) catches this.

---

## §5 Streaming/batch equivalence target (locked)

> **Equivalence is defined only over the supported belief subset under this spec. Not full pipeline parity.**

Concretely:

- The streaming engine (in `tkos_sidecar/rules.py`) implements every rule in §3 over the seven primitive belief types in §2.1.
- The batch engine (in `operational_belief_v1/build_operational_belief_substrate.py`) implements derivations for many belief types. Some are in §2.1; some are not.
- The equivalence test compares the two engines' output **only for belief types in §2.1** when both are run on the same event stream.
- Belief types in the batch engine that are not in §2.1 (e.g., `validation_pending` if the batch engine doesn't emit it, or `failure_signature_active` which is deferred) are excluded from the comparison.
- For belief types in §2.1, the two engines must produce identical `(belief_type, claim_template, lifecycle_state, effective_turn, authority)` tuples for the same event stream.

The comparison granularity is the belief-event sequence, not just the final `active_beliefs`. If streaming and batch disagree about *when* a belief was retired, that's a failure even if the final state matches.

### §5.1 What is NOT in the equivalence target

- Performance characteristics (memory, wall, CPU).
- Internal data structures.
- Whether the engine processes events one-at-a-time or in batches.
- Whether the engine uses SQL or in-memory state.
- Whether the engine produces additional debug output.

If two engines disagree on something not in the equivalence target, the spec does not arbitrate. Implementations may differ.

---

## §6 Spec constants

These pattern sets are part of the spec. Implementations must use these exact sets. Changes require a re-version of this spec.

```
VALIDATION_TOOLS = {
  "pytest", "npm_test", "cargo_test", "go_test", "jest", "mocha",
  "lint", "typecheck", "mypy", "tsc", "eslint", "rubocop",
  "build", "make", "cargo_build", "go_build"
}

VALIDATION_COMMAND_PATTERNS = [
  /^pytest\b/,
  /^npm (run )?test\b/,
  /^cargo test\b/,
  /^go test\b/,
  /^npx jest\b/,
  /^mypy\b/,
  /^npx tsc\b/,
  /^eslint\b/,
  /^npm (run )?build\b/,
  /^make\b/,
  /^cargo build\b/,
  /^go build\b/
]

APPROVAL_REQUEST_PATTERNS = [
  /should I (proceed|continue|deploy|commit|push|run|delete|drop)/i,
  /can I (proceed|continue|deploy|commit|push|run|delete|drop)/i,
  /are you ok with/i,
  /do you want me to/i,
  /shall I/i,
  /awaiting (your )?approval/i
]

APPROVAL_GRANT_PATTERNS = [
  /^(yes|sure|go ahead|approved|proceed|do it|ok|okay)\b/i,
  /\bsounds good\b/i,
  /\bplease (do|proceed|continue)\b/i
]

APPROVAL_DENY_PATTERNS = [
  /^(no|stop|hold on|wait|don't|do not|cancel)\b/i,
  /\b(reject|denied|refuse)\b/i
]

REPORT_PATH_PATTERNS = [
  /report\.html$/,
  /report\.pdf$/,
  /report\.md$/,
  /REPORT[_\-].*\.md$/,
  /\/reports\//,
  /summary\.(md|html|pdf)$/
]
```

These constants are v0.2-locked. Future versions may expand them; any expansion is a re-version event.

---

## §7 Atomicity contract (locked)

The locked choice (consistent with [`TKOS_WRITE_PATH_SCOPE_v0.2.md`](./TKOS_WRITE_PATH_SCOPE_v0.2.md) §6.1):

> **Event persistence + belief transitions = a single atomic operation.**

For each ingested event, the implementation MUST wrap the following in one transaction:

1. Persist the event record.
2. Evaluate all applicable rules; for each transition, persist the corresponding `belief_events` row and update `belief_instances` as needed.
3. Update the materialized `active_beliefs` view (or invalidate it if materialized-on-read).
4. Append an `ingest_log` entry recording which rules fired.

If any step fails, the entire transaction rolls back. The substrate never observes a state where the event exists without its rule-derived belief_events, or vice versa.

The pending/complete two-phase pattern (event persisted with `processing_status=pending`, then rules applied, then `processing_status=complete`) is explicitly NOT chosen for v0.2. It is a valid pattern for asynchronous systems; this spec is synchronous.

Rule exceptions are caught by the engine, the transaction rolls back, and the failure is logged to `rule_failures` (in a separate non-transactional table per TKOS scope §8.4). The session is marked admissibility-eligible = false. The event is rejected; the harness can retry after fixing the rule.

---

## §8 Authority handling

Belief authority can only increase, never decrease. The hierarchy:

```
asserted_by_assistant   <   confirmed_by_tool   <   confirmed_by_user
```

When a rule fires that affects an existing belief:

- If the rule's `AUTHORITY` is higher than the belief's current authority, the belief's authority is upgraded.
- If the rule's `AUTHORITY` is equal or lower, the belief's authority is unchanged.

For example: a `user_approval_pending` belief is born with `asserted_by_assistant`. When a `user_message` matching `APPROVAL_GRANT_PATTERNS` retires it (per §3.6), the belief's final authority becomes `confirmed_by_user`.

Authority affects ranking in `overlay()` (per the TKOS sketch §4 ranking policy) but does not affect any rule's firing condition. Rules in §3 evaluate against `lifecycle_state` and `belief_type`, not against `authority`.

---

## §9 What this spec does NOT decide

These are implementation seams:

- **Storage technology.** SQLite, Postgres, in-memory dict — all conform if they preserve the semantics above.
- **Rule firing order within an event.** If two rules can fire on the same event, both fire; the spec does not arbitrate which writes its `belief_events` row first. Implementations may choose any deterministic order.
- **Materialized view strategy.** Eager (update on every transition) or lazy (compute on read) — both conform.
- **Garbage collection of retired/contradicted beliefs.** When (if ever) to delete old `belief_events` rows is an implementation choice. The spec requires that the audit trail be queryable; it does not require infinite retention.
- **Indexing strategy.** Performance.
- **Concurrency model.** Single-threaded, multi-threaded with locks, single-writer multi-reader — implementation choice.
- **HTTP framing, file watching, replay protocols.** TKOS write-path scope §7 deals with these.
- **Rule code organization.** One function per rule, one function per belief type, a rule-engine framework — implementation choice.

---

## §10 Versioning

This spec is v0.2. Any change to:

- §1 the event contract,
- §2 the supported belief types,
- §3 any derivation rule,
- §4 the temporal semantics,
- §5 the equivalence target,
- §6 the spec constants,
- §7 the atomicity contract,
- §8 authority handling,

constitutes a re-version. The next version is v0.3. The old version remains as a referenceable artifact; commits referencing this spec must reference the version explicitly.

Implementations declare which spec version they target. Equivalence comparisons (§5) only hold across implementations targeting the same version.

---

## §11 What to read after this

For implementers:
- [`TKOS_WRITE_PATH_SCOPE_v0.2.md`](./TKOS_WRITE_PATH_SCOPE_v0.2.md) — the software scope.
- [`INTEGRATION_PATTERN_v0.1.md`](./INTEGRATION_PATTERN_v0.1.md) — how harnesses talk to the sidecar.

For substrate consumers (read-path):
- [`tkos.py`](./tkos.py) — the existing read-path slice. Its queries continue to work over write-path output.

For researchers:
- This is the spec the v0.4c2 substrate's belief derivation must conform to (when applied to its events).
- The shared canonical derivation spec is what makes streaming/batch equivalence a meaningful claim.

---

*This is the system definition. The sidecar code, the batch script, the streaming engine — all of them are implementations of what is above. Two engineers implementing what is here independently should produce the same belief_events trace on the same event stream. That is the load-bearing claim. If they don't, the bug is here, in the spec, not in the code.*
