# TKOS Sidecar — Architecture Sketch v0.1 (DRAFT)

**Status:** Thin sketch. Not a platform spec. Not implementation.
**Date drafted:** 2026-06-01
**Predecessors:**
- [`operational_belief_v1/OPERATIONAL_BELIEF_REPORT_v0.1.md`](../operational_belief_v1/OPERATIONAL_BELIEF_REPORT_v0.1.md) — the empirical evidence that an additive belief overlay reduces workflow-state errors.
- [`operational_belief_v2/OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.2.md`](../operational_belief_v2/OPERATIONAL_BELIEF_PRE_REGISTRATION_v0.2.md) — the next-step design that drives the *budgeted-overlay* requirement here.
- [`topicspace-site/app/research/belief-stack/page.tsx`](../topicspace-site/app/research/belief-stack/page.tsx) — the Belief Stack pattern definition.

---

## 1. Positioning

> TKOS sidecar is **not a memory store** and **not a governance system.**
> It is a **runtime operational-state layer.**
> The recent log shows what happened; TKOS tracks what is still true.

The sidecar's job in one line: observe assistant workflow events as they happen, maintain a small set of active operational beliefs, and on request return either a compact grounding overlay or an advisory risk check.

What this is **not** doing:

- It is not summarizing the conversation.
- It is not deciding when to interrupt the assistant.
- It is not a long-term knowledge base.
- It is not a policy / safety / governance layer.

The product-shaped claim is narrower: **a maintained state layer adds value beyond the recent log**, as shown empirically in Operational Belief v0.1. The sidecar is the runtime form of that overlay.

---

## 2. Core API sketch

Four endpoints. Everything else is internal.

### 2.1 `observe(event)`

Ingest a single assistant-session event and update belief state.

**Accepted event types (v0.1):**
- `user_message`
- `assistant_message`
- `tool_call`
- `tool_result`
- `file_edit`
- `command_run`
- `validation_event`
- `approval_request`
- `approval_response`

**Required fields per event:**
- `session_id`
- `turn`
- `event_type`
- `timestamp`
- `payload` — opaque blob containing whatever the event type carries (tool name + args, message text, command + stdout/stderr + exit code, file path + diff, etc.).

**Side effects:**
- Append to `events` table.
- Run deterministic belief-update rules. Each rule that fires writes to `belief_events`; the materialized `active_beliefs` view is refreshed.

### 2.2 `state(session_id, turn=None)`

Return the active operational belief set as of the current turn or a target historical turn.

**Returns:** list of belief records, each with:
- `belief_id`
- `belief_type` (from §3 typology)
- `claim` — short rendered string
- `lifecycle_state` — `active` / `superseded` / `retired` / `contradicted`
- `authority` — `asserted_by_assistant` / `confirmed_by_tool` / `confirmed_by_user`
- `warrant_turns` — list of event turn indices that *support* the belief
- `counterevidence_turns` — list of event turn indices that *weaken or contradict* the belief
- `last_updated` — turn index

This is the audit surface — it returns the *full* set, unbudgeted. It is not meant for prompt injection.

### 2.3 `overlay(session_id, budget_tokens=1000, action=None, question_type=None)`

Return a ranked, budgeted overlay suitable for LLM grounding.

**Parameters:**
- `session_id` — required.
- `budget_tokens` — required; integer; the hard cap on overlay rendered tokens.
- `action` — optional; the action being considered (e.g. `claim_complete`, `commit`, `deploy`). Used only to **rank-boost** beliefs that are blockers of that action.
- `question_type` — optional; reserved for future use (mirrors the Operational Belief v0.2 §3.3 category-aware ranking decision).

**Returns:** rendered overlay string, ranked per §4, capped at `budget_tokens`.

**Invariant:** the returned overlay is never longer than `budget_tokens`. Beliefs that don't fit are dropped, and a one-line `omitted_counts` summary is included if budget allows.

**Invariant:** the overlay is **never the full state**. If a caller wants the full state, they call `state()`, not `overlay()`. This separation is intentional — overlay is for grounding, state is for audit.

### 2.4 `risk(session_id, action)`

Return an advisory check on a proposed action.

**Parameters:**
- `session_id` — required.
- `action` — required; one of: `claim_complete`, `commit`, `push`, `deploy`, `send`, `proceed`.

**Returns:** `{ blockers: [...], rationale: "..." }` where blockers is a list of active belief records that should block the action under deterministic rules, and rationale is a short human-readable explanation.

**Invariant:** `risk()` is advisory only. It does not stop the action, log a violation, or notify anyone. It returns information; the calling system decides what to do with it.

This separation — advisory vs intervention — is the line between "sidecar" and "governance system." The sidecar stays on the advisory side in v0.1.

---

## 3. Minimum belief types (v0.1 sidecar POC)

The first sidecar POC operates on a small typology. These map directly onto the Operational Belief v0.1 substrate.

| Type | Meaning | Example claim |
|---|---|---|
| `fix_attempted` | Assistant has tried a specific fix for a specific failure. | "fix attempted for ImportError in module X via patch at turn 14" |
| `validation_pending` | A fix or change has been made but not yet validated by tests, lint, type-check, or a tool. | "validation pending — pipeline run not started after edit at turn 22" |
| `validation_complete` | A pending validation has been confirmed. | "validation complete — pipeline run passed at turn 25" |
| `pipeline_running` | A long-running tool / process is in flight. | "pipeline_running — `npm run build` started turn 17, not yet returned" |
| `pipeline_failed` | A pipeline-class action returned a failure. | "pipeline_failed — `pytest` exit 1 at turn 30" |
| `action_blocked` | A precondition for an action is not met. | "action_blocked — cannot deploy until validation_complete" |
| `user_approval_pending` | The assistant has asked the user for approval and has not received a response. | "user_approval_pending — approve migration at turn 41" |
| `report_ready` | A report or artifact has been produced and is ready to be delivered. | "report_ready — master_report.html written at turn 50" |

**Optional, deferred to v0.2 sidecar if useful:**
- `failure_signature_active` — a recurring failure mode that has reappeared in the session (echoes v0.1 `repeated_failure_loop`).

The typology is intentionally small. Any belief type that isn't in this list is out of scope for the v0.1 POC.

---

## 4. Ranking policy

The overlay rank is the same lexicographic-by-tier policy as Operational Belief v0.2 §3:

1. Active blockers (`action_blocked`, `validation_pending`, `pipeline_failed`, `pipeline_running`, `user_approval_pending`).
2. Contradicted / weakened beliefs.
3. (If `action` is given) beliefs that are blockers of the named action — promoted into tier 1 for that call only.
4. Recently updated beliefs.
5. `confirmed_by_tool` > `asserted_by_assistant`.
6. `active` > `superseded` > `retired`.
7. `omitted_counts` summary line, if budget permits.

Action-aware ranking via the `action` parameter is the sidecar's one concession to query awareness — and it is bounded to *promoting blockers*, not selecting belief content based on the question.

---

## 5. Data model

SQLite. Five tables. Schema below is a sketch — column names and types are illustrative, not locked.

### 5.1 `events`

| Column | Type | Notes |
|---|---|---|
| event_id | INTEGER PRIMARY KEY | autoincrement |
| session_id | TEXT NOT NULL | |
| turn | INTEGER NOT NULL | per-session monotonic |
| event_type | TEXT NOT NULL | one of the v0.1 event types |
| timestamp | TEXT NOT NULL | ISO 8601 |
| payload_json | TEXT NOT NULL | opaque blob |

Index on `(session_id, turn)`.

### 5.2 `belief_instances`

The append-only record of every belief-instance creation.

| Column | Type | Notes |
|---|---|---|
| belief_id | TEXT PRIMARY KEY | UUID; stable across the lifecycle of a belief |
| session_id | TEXT NOT NULL | |
| belief_type | TEXT NOT NULL | from §3 |
| claim | TEXT NOT NULL | short rendered string |
| created_turn | INTEGER NOT NULL | |
| created_by_event_id | INTEGER REFERENCES events(event_id) | the event that minted it |

### 5.3 `belief_events`

The lifecycle audit trail. Append-only.

| Column | Type | Notes |
|---|---|---|
| belief_event_id | INTEGER PRIMARY KEY | |
| belief_id | TEXT REFERENCES belief_instances(belief_id) | |
| event_id | INTEGER REFERENCES events(event_id) | the triggering event |
| kind | TEXT NOT NULL | one of: `born`, `refreshed`, `weakened`, `contradicted`, `confirmed`, `superseded`, `retired` |
| at_turn | INTEGER NOT NULL | |
| authority | TEXT NOT NULL | `asserted_by_assistant` / `confirmed_by_tool` / `confirmed_by_user` |
| note | TEXT | optional short reason |

This is the table that makes belief history reconstructable for any past turn.

### 5.4 `active_beliefs`

A *materialized view* (or a view backed by a periodic refresh job) computed from `belief_instances` and `belief_events`. Holds one row per currently-active belief.

| Column | Type | Notes |
|---|---|---|
| belief_id | TEXT PRIMARY KEY REFERENCES belief_instances(belief_id) | |
| session_id | TEXT NOT NULL | |
| belief_type | TEXT NOT NULL | |
| claim | TEXT NOT NULL | |
| lifecycle_state | TEXT NOT NULL | `active` / `superseded` / `contradicted` |
| authority | TEXT NOT NULL | highest authority observed so far |
| last_updated_turn | INTEGER NOT NULL | from most recent `belief_events` row |

`state(session_id)` reads from here directly.

### 5.5 `action_checks`

Audit log for every `risk()` call. Append-only.

| Column | Type | Notes |
|---|---|---|
| check_id | INTEGER PRIMARY KEY | |
| session_id | TEXT NOT NULL | |
| at_turn | INTEGER NOT NULL | |
| action | TEXT NOT NULL | from the §2.4 enum |
| blocker_belief_ids_json | TEXT NOT NULL | JSON array of belief_id |
| rationale | TEXT NOT NULL | the returned rationale string |
| timestamp | TEXT NOT NULL | |

This table is what makes the sidecar's advisory behavior auditable — every `risk()` call is recoverable after the fact.

---

## 6. Design principles

These are the v0.1 invariants. Violating any of them changes the system into something other than a sidecar.

- **Deterministic / auditable rules first.** Every belief lifecycle transition has a named rule, an event trigger, and a recorded `belief_events` row.
- **LLM extraction is optional and future, not required for v0.1.** Belief instances in v0.1 come from deterministic rules over event payloads, not from LLM scoring.
- **Belief lifecycle is central.** Beliefs are born, refreshed, contradicted, retired. They are not key-value flags.
- **Authority matters.** `confirmed_by_tool` > `asserted_by_assistant`. `risk()` weights confirmed beliefs differently from asserted ones.
- **Overlay must be ranked and budgeted.** No unbounded overlay return path. Ever.
- **Advisory before intervention.** `risk()` returns information, never blocks an action. Intervention is a different layer.
- **No "agent safety platform" claims.** This is a state-tracker, not a safety system.

---

## 7. First demo scenario

A scripted coding-assistant workflow that exercises every belief type:

1. **Turn 1–5.** User reports a failing test. Assistant proposes a fix.
2. **Turn 6.** Assistant edits a file. → `fix_attempted` is born.
3. **Turn 7.** Assistant runs the test. → `validation_pending` is born.
4. **Turn 8.** Test fails. → `pipeline_failed` is born; `validation_pending` is *contradicted*.
5. **Turn 9–11.** Assistant proposes a different fix; edits again. → new `fix_attempted` (the old one is *retired*).
6. **Turn 12.** Assistant runs the test. → new `validation_pending`.
7. **Turn 13.** Test passes. → `validation_complete` is born; `validation_pending` is *confirmed* and retired.
8. **Turn 14.** Assistant asks the user "can I deploy?" → `user_approval_pending` is born.
9. **Turn 15.** Caller invokes `risk("deploy")`. → returns `{ blockers: [user_approval_pending], rationale: "deploy blocked — pending user approval at turn 14" }`.
10. **Turn 16.** User says "yes." → `user_approval_pending` is confirmed and retired.
11. **Turn 17.** Caller invokes `risk("deploy")`. → returns `{ blockers: [], rationale: "no blockers — most recent validation_complete at turn 13" }`.
12. **Turn 18.** Assistant deploys. Produces a report. → `report_ready` is born.

**Comparison demonstration:**

- Run the same scripted workflow through a raw-log baseline (no sidecar). Ask: "Can this be called done at turn 16?" — measure whether the answer notices the pending approval.
- Then ask the same question against the assistant with an `overlay(turn=16, budget_tokens=1000)` injected. Measure whether the grounded answer correctly flags the pending approval.

This mirrors the v0.1 deterministic gate, just at single-session resolution.

---

## 8. POC scope

The v0.1 sidecar POC builds the smallest end-to-end path:

1. Event adapter for **one** input source (see §10 Q1) → `observe()`.
2. Deterministic rules covering the §3 belief types.
3. SQLite-backed implementation of the §5 schema.
4. `state(session_id)` returning the active set.
5. `overlay(session_id, budget_tokens, action=None)` returning the ranked, budgeted overlay string.
6. `risk(session_id, action)` covering at minimum `claim_complete` and `deploy`.
7. CLI for inspection: `tkos state <session>`, `tkos overlay <session> --budget 1000`, `tkos risk <session> --action deploy`.
8. The demo scenario in §7, scripted and reproducible.

That is the entire POC. No UI beyond the CLI. No remote service. No multi-user. No live integration.

---

## 9. Non-goals (v0.1 sidecar)

The following are explicitly **out of scope** for v0.1:

- Live integration with Claude Code, Cursor, or any IDE.
- LLM-based belief extraction.
- Multi-session reasoning ("across all my sessions, what's still pending?").
- Memory persistence beyond a single session.
- Network API / HTTP server.
- Authentication / multi-tenant isolation.
- A trace viewer UI.
- Policy / governance / blocking enforcement.
- Automatic injection of `overlay()` into a running assistant.

Several of these (live integration, trace viewer, network API) are obvious v0.2+ candidates. Listing them here as non-goals is meant to keep v0.1 scoped to the narrowest demonstration.

---

## 10. Open questions before lock

- **Q1.** Which event adapter ships first?
  - (a) **Claude Code logs** — closest fit to the Operational Belief v0.1 substrate, and Sue already has the tooling and parsers in place.
  - (b) Cursor logs.
  - (c) A terminal wrapper that observes user shell sessions.
  - (d) A purely synthetic trace player that replays a JSON event stream.

  **Default proposal: (d) synthetic + (a) Claude Code logs.** The synthetic player guarantees a reproducible demo; the Claude Code adapter is the first real-world data source and reuses v0.1 infrastructure.

- **Q2.** Should the sidecar be a passive observer or a tool-callable service?
  - For v0.1: **passive observer only**, with a CLI for `state()`, `overlay()`, `risk()`. No tool registration to the assistant.
  - "Tool-callable" is a v0.2+ question once we know whether the assistant *should* be calling its own grounding layer.

- **Q3.** Should overlay injection be always-on or trigger-based?
  - v0.1: **not injected at all.** The demo compares overlay-grounded vs raw-log answers offline. Live injection is a v0.2+ question.

- **Q4.** What ranking policy does v0.1 use?
  - The §4 policy. Locked once §5 D4 of the Operational Belief v0.2 pre-reg is decided.

- **Q5.** How to handle belief explosion in long sessions?
  - v0.1 mitigations: lifecycle-driven retirement (retired beliefs drop out of `active_beliefs`), and the overlay budget itself.
  - v0.2+: per-session compaction policy (rolling window on `belief_events`).

- **Q6.** Smallest useful UI?
  - v0.1: **CLI** only — `tkos state | overlay | risk`. JSON output supported via `--json`.
  - A web trace viewer is v0.2+.

- **Q7.** Where is the boundary between sidecar and host application?
  - The sidecar owns: events, belief lifecycle, overlay rendering, risk checks.
  - The host owns: which events to send, what to do with overlay output, whether to act on `risk()` blockers.
  - The sidecar never reaches back into the host. This is the line that keeps "sidecar" from sliding into "platform."

---

## 11. Deliverables (for this draft)

- ✅ Architecture sketch (this document).
- ✅ API contract draft (§2).
- ✅ Minimal data model (§5).
- ✅ First POC scope (§8).
- ✅ Non-goals list (§9).
- ⏳ Demo trace JSON (deferred — written when POC starts).
- ⏳ CLI usage examples (deferred — written when POC starts).

**Explicitly not in this draft, by user instruction:**

- Any code.
- A full runtime spec.
- Integration plan.
- Performance targets.
- Roadmap beyond POC.

---

*End of sketch. This is a thin vertical-slice design intended to ground the next conversation about which adapter to build first. No code, no runtime spec, no platform claims.*
