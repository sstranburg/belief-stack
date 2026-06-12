# TKOS Write-Path Sidecar — Scope v0.1.1 (SUPERSEDED by v0.2 / v0.2.1)

> **Note 2026-06-06:** Superseded by `TKOS_WRITE_PATH_SCOPE_v0.2.md` and amended in `AUDIT_RESPONSE_2026-06-06.md`. Retained as the artifact of what was originally locked; do not implement against this version.

---



**Date:** 2026-06-05 (v0.1 locked; amended to v0.1.1 same day for §10 Q2 resolution)
**Status:** Scope draft. Not implementation.
**Predecessors:**
- [`TKOS_SIDECAR_SKETCH_v0.1.md`](./TKOS_SIDECAR_SKETCH_v0.1.md) — the architectural sketch from 2026-06-01. This document extends §2.1 (`observe()`) into a concrete write-path build.
- [`TKOS-002_IMPLEMENTATION_SLICE_v0.1.md`](./TKOS-002_IMPLEMENTATION_SLICE_v0.1.md) — the read-path slice (existing `tkos.py`).
- [`experiments/operational_belief_v1/build_operational_belief_substrate.py`](../experiments/operational_belief_v1/build_operational_belief_substrate.py) — the v0.1 rule engine in batch form. The write-path ports these derivations to streaming.
- The v0.4c2 substrate admission criteria (internal) — the gates the resulting trace capture must satisfy.

**v0.1 → v0.1.1 amendment (2026-06-05):** §10 Q2 (Codex transcript location) resolved. The rollout JSONL at `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` is the source. Investigation surfaced that the rollout contains **multiple events per conversational turn**, which forces a schema-level change: event identity becomes `(session_id, turn_idx, event_idx)` instead of `(session_id, turn_idx)`. This amendment threads that change through §4, §5 test 5, §6, §8, §10 Q1, and §10 Q6. No code has been written; this is a pre-implementation re-lock per the build-time-audit discipline.

---

## Purpose

The TKOS sidecar already has a read-path slice: given a fixtured belief substrate, it reconstructs state at any past turn and renders both sparse (planner) and rich (human) projections. The write-path is the missing piece — the engine that takes a live event stream and produces the substrate the read-path consumes.

This document scopes **v0.1 of the write-path** as a small, shippable, real piece of software. It is also the chosen Codex substrate project for v0.4c2 cross-substrate replication (per the locked admission criteria above).

Two things at once:

1. **Engineering artifact.** Turns Belief Stack from "fixtured research result" into a runtime architecture you can actually instrument an agent with.
2. **v0.4c2 substrate.** Codex sessions building this software become the second operational corpus. The sidecar's own trace capture (Codex events flowing into `observe()`) is the trace-capture mechanism for v0.4c2 §1.

---

## 1. Scope

### 1.1 In-scope (v0.1)

A single-process Python service that exposes `observe(event)`, persists events and beliefs to SQLite, and shares its DB with the existing read-path slice for projections.

Specifically:

- HTTP ingestion endpoint accepting one event per POST.
- Persistent storage of raw events (the trace) in the same SQLite DB the read-path reads.
- A streaming port of the v0.1 rule engine that fires on each ingested event and writes `belief_events` rows (born / refreshed / weakened / contradicted / confirmed / retired).
- A materialized `active_beliefs` view that the existing read-path's `reconstruct_state` and `build_overlay` queries read from unchanged.
- A trace adapter for **Codex sessions**: a thin script that watches the Codex transcript output and POSTs one event per turn into the sidecar.
- A CLI: `tkos serve` (start the sidecar), `tkos replay <trace.jsonl>` (replay a saved trace, idempotent), `tkos export <session_id>` (export a session's events + beliefs as the v0.4c2-admissible trace artifact).
- Eight acceptance tests in the style of the existing read-path's six.

### 1.2 Out-of-scope (v0.1)

The following are explicitly **not** in v0.1, even though the sketch lists some as future:

- LLM-driven belief extraction. v0.1 uses deterministic rules only.
- Auth, multi-tenant, network protocols beyond local HTTP.
- Trace viewer UI. CLI only.
- Live integration with any IDE or assistant other than Codex.
- Cross-session reasoning ("across all my sessions, what's still pending?").
- Tool registration to the assistant itself. The sidecar is passive observer only.
- Overlay auto-injection. The host decides what to do with `overlay()` output; the sidecar never reaches back.
- Performance optimization beyond "fast enough for one user's coding sessions."
- Postgres / replication / clustering.

These deferrals are not negotiable for v0.1. If the project starts requiring any of them, the scope has drifted; stop and re-scope before continuing.

---

## 2. Reference architecture

The existing TKOS read-path slice (`tkos_sidecar/tkos.py`) already implements:

- SQLite DDL for `events`, `belief_instances`, `belief_events`, `action_checks`.
- `reconstruct_state(session_id, turn)` — replays the lifecycle audit trail to reconstruct active beliefs at any past turn.
- `build_overlay(state, budget_tokens, action, K)` — produces the ranked, budgeted projection.
- A CLI for `state` and `overlay`.

The read-path is *not modified* by the write-path. The two components share the SQLite schema; the write-path adds rows that the read-path consumes via existing queries. This is the substrate-vs-projection split made operational.

The write-path adds:

- `ingest.py` — HTTP server, event normalization, calls into the rule engine.
- `rules.py` — streaming port of the v0.1 derivations.
- `trace_adapter_codex.py` — Codex-specific event mapping.

Layout:

```
tkos_sidecar/
├── tkos.py                    (existing, unchanged — read-path)
├── test_tkos.py               (existing, unchanged)
├── ingest.py                  (new — HTTP + dispatcher)
├── rules.py                   (new — streaming rule engine)
├── trace_adapter_codex.py     (new — Codex event mapping)
├── test_ingest.py             (new)
├── test_rules.py              (new)
├── test_trace_adapter.py      (new)
└── tkos.db                    (existing schema, populated by write-path)
```

---

## 3. The rule engine

This is the heart of the write-path and the section that needs the most care.

### 3.1 Streaming form of the v0.1 derivations

The v0.1 batch rule engine
([`operational_belief_v1/build_operational_belief_substrate.py`](../operational_belief_v1/build_operational_belief_substrate.py))
has derivation functions that take all sessions and return all beliefs:

- `derive_validation_complete_beliefs(...)`
- `derive_action_composite_beliefs(...)`
- `derive_failure_signature_beliefs(...)`

The streaming version operates on **one new event at a time** against the current per-session state. For each new event, the rule engine asks: *what beliefs should be minted, refreshed, weakened, contradicted, or retired by this event?* and writes the corresponding `belief_events` rows.

The streaming rule engine is correct iff: for any session, replaying its events in order through the streaming engine yields the same final `active_beliefs` set as running the batch engine on the full session.

This equivalence is the load-bearing correctness check (acceptance test §5.6 below).

### 3.2 Event-to-rule dispatch

Each accepted event type maps to a small fixed set of rules. From the sketch §2.1:

| Event type | Rules to consider |
|---|---|
| `tool_call` | mint `pipeline_running` if long-running; refresh / contradict matching `validation_pending` |
| `tool_result` | confirm or retire `pipeline_running`; mint `pipeline_failed` on non-zero exit; mint / confirm `validation_complete` |
| `file_edit` | mint `fix_attempted` anchored to current failure signature; retire prior `validation_complete` for affected scope |
| `command_run` | same family as `tool_call` |
| `validation_event` | confirm / weaken `validation_pending`; mint `validation_complete` on pass; mint `pipeline_failed` on fail |
| `approval_request` | mint `user_approval_pending` |
| `approval_response` | confirm / contradict matching `user_approval_pending` |
| `user_message` / `assistant_message` | low-firing in v0.1; reserved for future LLM-extraction layer |

Each rule has: a predicate over current state + this event, a lifecycle action (born / refreshed / weakened / contradicted / confirmed / retired), and a one-line note recorded in `belief_events.note` for audit.

### 3.3 What v0.1 does NOT do

- No LLM scoring inside rules.
- No probabilistic belief weights. Lifecycle states are categorical.
- No retroactive rule changes (no "this past event would have minted this belief if rules had been different"). If rules change, the whole stream is replayed from event 1.
- No fuzzy belief matching across sessions. Beliefs are session-local in v0.1.

### 3.4 Determinism guarantee

Given the same event stream and the same rule set, the engine must produce the same `belief_events` rows in the same order. This is what makes `tkos replay <trace.jsonl>` reproducible and what makes the write-path comparable to the v0.1 batch engine.

---

## 4. The Codex trace adapter

The §1 capture mechanism for v0.4c2 admission.

### 4.1 What the adapter does

Reads a Codex session's structured output (transcript / tool-call history / file-edit log) and emits one well-formed event per turn into `observe()`. The mapping is:

| Codex output | Sidecar event |
|---|---|
| User message | `user_message` |
| Assistant message | `assistant_message` |
| Shell command (run) | `command_run` |
| Shell command (output) | `tool_result` with the matching `command_run` event referenced |
| File edit (apply patch / write) | `file_edit` |
| Tool invocation (other) | `tool_call` |
| Tool output | `tool_result` |

Each emitted event carries the v0.4c2-required fields per the admission criteria §1:

- `session_id`
- `turn_idx` (monotonic per session; a new turn begins on each new user message or each task start/completion boundary — final rule documented in the adapter)
- `event_idx` (monotonic within a turn; required because Codex rollout JSONL emits multiple events per conversational turn — assistant reasoning, tool calls, tool results, assistant messages)
- `timestamp` (ISO 8601)
- `event_type`
- `payload` (the raw Codex content for that event)
- `call_id` (when applicable; correlates tool_call with tool_result per the rollout JSONL schema)
- `file_paths_touched` (when applicable)
- `terminal_output` (when applicable)

### 4.2 Two modes

- **Live mode.** A long-running process that watches the Codex transcript output as it grows and POSTs new events to the running sidecar in near-real-time.
- **Batch mode.** A one-shot script that takes a saved Codex transcript and replays it through `observe()`. Useful for re-processing earlier sessions if rules change.

Both modes write to the same SQLite DB. Both modes preserve the original Codex transcript verbatim in `events.payload_json`.

### 4.3 Capture invariant

The adapter must capture **every turn** of a Codex session or none of it. Partial capture (started mid-session, stopped early) is logged as a capture failure and the session is marked admissible=false in a separate `session_status` table (see §6.5). This honors the admission criteria §4 hard rule.

---

## 5. Acceptance tests

Nine tests, in the style of the existing read-path's six. Each is concrete, runnable, and fails clearly when broken.

1. **Single-event ingest.** POST one `tool_call` event; verify it appears in `events` table with correct schema; verify no beliefs minted (correct behavior: this event type alone doesn't mint anything without a preceding context).
2. **End-to-end demo session.** Replay the sketch §7 demo scenario (18 turns) through `observe()`. Verify the final `active_beliefs` contains exactly the beliefs the sketch enumerates as the end-state (post-deploy: `report_ready` active, all others retired or confirmed).
3. **Lifecycle transitions.** Replay the same scenario and verify each `belief_events` row matches the expected lifecycle transition (born → contradicted → retired for the first fix's `validation_pending`).
4. **Out-of-window beliefs survive.** Replay a longer (50-turn) synthetic session in which a `user_approval_pending` belief is minted at turn 5 and not addressed until turn 48. Verify `state(session, turn=48)` returns it (the lifecycle audit trail makes this possible even though raw event K=20 windowing would have lost it).
5. **Replay idempotency.** Run `tkos replay <trace.jsonl>` twice; verify the second run produces zero new `belief_events` rows (idempotent ingestion based on `(session_id, turn_idx, event_idx)` primary key).
6. **Batch-equivalence.** Take a real Claude Code session from the v0.1 corpus; replay it through the streaming rule engine; verify the resulting `active_beliefs` matches what the batch v0.1 rule engine produces for the same session. This is the correctness check that makes v0.4c2 a defensible cross-substrate run.
7. **Codex adapter round-trip.** Capture a real Codex session in live mode; replay the same captured trace in batch mode; verify identical results.
8. **Read-path compatibility.** After the write-path has populated the DB from a Codex session, call the existing read-path's `reconstruct_state` and `build_overlay` against it. Verify both queries return well-formed results with no schema mismatches. This is the test that the substrate-vs-projection split actually holds.
9. **Export determinism.** Capture a session and run `tkos export <session_id>` twice with no intervening DB changes. The two output files must be **byte-identical**. This is what makes the v0.4c2 substrate artifact stable: the same DB state always produces the same export, so a reviewer comparing two exports diffs only what actually changed. Requires the export serializer to use a stable ordering (sort by `(session_id, turn_idx)` everywhere, sort belief lists by `belief_id`) and to exclude any non-deterministic fields (e.g., wallclock-now timestamps in headers).

Tests 6, 8, and 9 are the load-bearing ones. They are what make the write-path *correct* (not just runnable), and what make the v0.4c2 substrate artifact defensible.

---

## 6. Data model additions

The read-path's existing tables get one additive change (an `event_idx` column on `events`); existing read-path queries continue to work unchanged. The write-path adds two new operational tables.

### 6.0 `events` schema amendment

Existing `events` table from the read-path slice has primary key on `(session_id, turn)`. Amendment: add `event_idx INTEGER NOT NULL DEFAULT 0` and change the natural key to `(session_id, turn_idx, event_idx)`. Existing fixtured rows backfill with `event_idx = 0` — non-breaking because the fixture is one event per turn. Read-path queries that ignore `event_idx` continue to return the same results.

### 6.1 `session_status` (new)

Tracks per-session capture state. Required by §4.3.

| Column | Type | Notes |
|---|---|---|
| session_id | TEXT PRIMARY KEY | |
| capture_started_at | TEXT NOT NULL | ISO 8601 |
| capture_ended_at | TEXT | nullable until session is closed |
| capture_started_at_turn | INTEGER NOT NULL | must be 0 for admissible sessions |
| admissible | INTEGER NOT NULL | 0 or 1; defaults to 1 unless capture started after turn 0 |
| note | TEXT | reason for inadmissibility, if applicable |

### 6.2 `ingest_log` (new, optional)

Append-only audit of every `observe()` call, for debugging. Not required for correctness; included if cheap.

| Column | Type | Notes |
|---|---|---|
| ingest_id | INTEGER PRIMARY KEY | |
| session_id | TEXT NOT NULL | |
| turn_idx | INTEGER NOT NULL | |
| event_type | TEXT NOT NULL | |
| received_at | TEXT NOT NULL | |
| rules_fired | TEXT | JSON array of rule names that fired on this event |

---

## 7. Build plan (suggested order for Codex)

Build in this order so each step has a working preceding step to test against.

1. **Bootstrap.** Set up the new files (`ingest.py`, `rules.py`, `trace_adapter_codex.py`) and the corresponding test files. Add `session_status` and `ingest_log` tables to the existing DDL (additive, doesn't break read-path).
2. **Trace capture, no rules.** Implement the HTTP endpoint and event persistence. Get `tkos serve` and `tkos replay` working with events flowing into the `events` table. **Wire Codex trace adapter at this point** so trace capture from session 1 is real and not just promised. The adapter reads `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` line-by-line, assigns `event_idx` monotonically within each `turn_idx`, and POSTs one event per line. Pass acceptance test 1. *§10 Q2 resolved (2026-06-05) — step 2 can proceed without further investigation.*
3. **First rule pair.** Implement the two simplest rules (`validation_pending` minted from `tool_call`; `validation_complete` minted from `tool_result`). Pass acceptance tests 2 and 3 partially (for these two belief types only).
4. **Remaining rules.** Add the remaining rule families from §3.2. Pass acceptance tests 2 and 3 fully.
5. **Long-session correctness.** Pass acceptance test 4 (out-of-window beliefs).
6. **Idempotency.** Pass acceptance test 5.
7. **Batch-equivalence.** Pass acceptance test 6 — port the v0.1 batch derivations and compare. This is the hardest test; expect iteration.
8. **Codex adapter polish.** Pass acceptance tests 7 and 8.
9. **CLI completion.** Finish `tkos export <session_id>` for v0.4c2 trace artifact export.

**Critical:** Step 2 ships Codex trace capture *before* the rule engine. This means real Codex sessions from step 2 onward become part of the v0.4c2 corpus. Steps 1 and any pre-step-2 exploration are software work, but their traces are not admissible (the hard rule).

---

## 8. Invariants

These hold across v0.1 and constrain refactors:

- **Read-path is read-only of the write-path's output.** The write-path writes to `events`, `belief_instances`, `belief_events`, `session_status`, `ingest_log`. The read-path reads from `events`, `belief_instances`, `belief_events`. Neither reaches into the other's code path.
- **Every belief lifecycle transition has a `belief_events` row.** No silent state mutations.
- **No event is processed twice.** `(session_id, turn_idx, event_idx)` is the idempotency key.
- **Streaming-equals-batch.** Acceptance test 6 must pass; if it doesn't, the rule engine is wrong.
- **Trace capture is binary.** A session is either fully captured (admissible=1) or it isn't (admissible=0). No partial-capture-with-asterisks.

---

## 9. Failure modes (what should never happen silently)

- A Codex event arrives but the adapter has no mapping for it → log explicitly, drop, mark session admissible=0. Do not invent a mapping at runtime.
- A rule throws an exception on an event → log the rule name + event; do not silently swallow. The session stays admissible but the engine state is now suspect; surface this in `tkos export` output.
- The DB schema diverges from what the read-path expects → fail loudly on startup. Do not "best-effort" continue.
- Two sessions are interleaved through the same HTTP endpoint at once → supported (sessions are session_id-scoped) but log if interleaving exceeds a configurable rate.

---

## 10. Decisions locked before code starts

Five of six are now locked. Q2 remains open and is an explicit gate on §7 step 2.

- **Q1. HTTP framing.** ✅ *Locked: one event per POST.* No batching semantics in v0.1.
- **Q2. Codex transcript location.** ✅ *Resolved (2026-06-05):* primary trace is `~/.codex/sessions/YYYY/MM/DD/rollout-{timestamp}-{uuid}.jsonl` (live JSONL appended by Codex during the session). The trace adapter reads this file. Adjacent stores (`session_index.jsonl`, `state_5.sqlite`) are useful for thread metadata but not required. **Schema implication:** the rollout JSONL contains multiple events per conversational turn, forcing the event identity from `(session_id, turn_idx)` to `(session_id, turn_idx, event_idx)`. Threaded through §4, §5 test 5, §6, §8 above. Full details in `reference_codex_trace_storage.md` memory.
- **Q3. Long-running tool detection.** ✅ *Locked: K=3 unmatched-result retro-mint rule.* If a `tool_call` has no matching `tool_result` within K=3 subsequent turns, retro-mint `pipeline_running` at the original turn. Simpler than guessing at ingest time.
- **Q4. Failure signature derivation.** ✅ *Locked: simple `exit code + first stderr line` matcher for v0.1.* Full v0.1 signature derivation (the more sophisticated batch-engine version) moves to v0.2.
- **Q5. Multi-process safety.** ✅ *Locked: SQLite WAL mode + startup lock file.* Constraint documented; no distributed-safety work in v0.1.
- **Q6. v0.4c2-specific export format.** ✅ *Locked (v0.1.1 amendment): JSONL per session, **one line per event** (not per turn), with the v0.4c2 §1 required fields including `event_idx` plus the matching `active_beliefs` snapshot computed up-to-and-including that event.* The end-of-turn snapshot is naturally available as the last event's snapshot in each turn. Stable ordering and deterministic content per acceptance test 9.

The locks above were chosen on 2026-06-05 against this scope. Any change to a locked answer during the build is an explicit re-version of this document (per the program's amendment discipline), not a silent code edit.

---

## 11. Deliverables at v0.1 close

When all eight acceptance tests pass and §1 in-scope items ship:

- A running `tkos serve` that ingests Codex events from a real coding session.
- A working `tkos replay` that idempotently re-processes saved traces.
- A working `tkos export` that produces v0.4c2-admissible session artifacts.
- The existing read-path's `tkos state` and `tkos overlay` queries work against the write-path's output without modification.
- An updated TKOS sketch (v0.2 of the sidecar sketch) folding the write-path results back.
- The Codex sessions captured during this build are the start of the v0.4c2 substrate corpus.

Expected timeline: 3–4 weeks of focused Codex-assisted work for a competent Python developer.

---

## 12. What this does NOT commit to

- The v0.4c2 pre-registration. That document is written separately once an admissible corpus exists.
- A v0.2 sidecar roadmap. v0.1 ships first; v0.2 questions are accumulated in an internal sidecar backlog.
- LLM-driven belief extraction. Out of scope for v0.1; tracked as a separate research direction.
- IDE / agent integration beyond Codex. The Codex adapter is sufficient for the substrate goal.

---

*This scope is small enough to ship and large enough to be the actual write-path the spec promises. The rule engine is the only hard part; the rest is plumbing. The build doubles as the v0.4c2 substrate, so trace capture is wired at step 2 — before the rule engine itself — to honor the admission §1 hard rule.*
