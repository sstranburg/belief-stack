# TKOS-002 — Human Belief-State Observability Surface (DRAFT)

**Status:** Design sketch. Not implementation.
**Date drafted:** 2026-06-02
**Companion to:** [`TKOS_SIDECAR_SKETCH_v0.1.md`](./TKOS_SIDECAR_SKETCH_v0.1.md) — TKOS-001 covers the runtime sidecar (observe / state / overlay / risk). This document covers the *human-facing* surface over the same substrate.

---

## 1. Motivation

The Operational Belief v0.1 result showed that a maintained belief-state layer reduces workflow-state errors when injected into an LLM's context. That is the **AI-facing** value: compact, ranked, budgeted grounding payload that the model can consume at action time.

The same substrate has a second consumer: **the human watching the assistant.** A user, an engineer, an oncall ops person — anyone who needs to answer "what does the system think is still pending?" or "why is this action blocked?" The recent log alone does not answer those questions either; it shows what happened, not what is still true.

The right design move is one belief-state substrate, two **peer** query surfaces. Not two products. Not a separate observability store. Same `state()` truth layer, two rendering paths optimized for two different consumers.

**The AI and the human are peer consumers of the same belief-state substrate.**

The wedge against existing AI observability tools (Langfuse, Helicone, LangSmith, Braintrust, Arize, etc.) is clean: they all store the log. TKOS-002 surfaces *derived state from the log* — what's still pending, blocked, contradicted, unvalidated. That is a layer above prompt/response logging.

---

## 2. Shared substrate

There is exactly one substrate. It is defined in TKOS-001 §5 and is **not modified** by TKOS-002.

- `events` — append-only event log.
- `belief_instances` — every belief minted, append-only.
- `belief_events` — lifecycle audit trail: `born / refreshed / weakened / contradicted / confirmed / superseded / retired`.
- `active_beliefs` — materialized view of currently-active beliefs.
- `action_checks` — audit log of every `risk()` call.

SQLite-backed, single store. The AI surface and the human surface both read through `state()`.

**Invariant: do not fork the substrate.** No human-only tables. No human-only columns. No human-only ingestion path. If the human surface ever needs a derived index for performance, that is a *cached projection* of the existing five tables, not a new source of truth.

---

## 3. AI-facing surface

> **AI-facing `overlay()` compresses state for action-time grounding.**

This surface is fully specified in TKOS-001 §2.3, §3, §4. Recap only:

- `overlay(session_id, budget_tokens, action=None, question_type=None) → rendered overlay string`
- Lexicographic priority tiers (active blockers → contradicted → action-relevant → recently updated → tool-confirmed → active → omitted-counts summary).
- Hard token budget; partial-belief rendering is forbidden; budget overruns surface as ranked dropouts (counted) or `api_error:RateLimitError` (recorded).
- Optimized for an LLM consumer at action time. Compact, ranked, lossy by design.

TKOS-002 does not modify this surface. It does, however, expose it for human inspection via `tkos overlay` (see §6.3) — so the operator can see what payload the AI would have received.

---

## 4. Human-facing surface

> **Human-facing trace viewer exposes state for inspection, debugging, and audit.**

The human surface answers a different question than the AI surface. The AI asks *"what should I be grounded on, in 1000 tokens"*. The human asks *"what is the system tracking, why, and since when"*.

The human surface is, in one phrase, an **epistemic debugger**: it lets you step through a session and ask what the belief layer thought at each turn, and why.

### 4.1 Required capabilities

- **Time travel.** Query state as-of any turn T, not only "now." Implementation: replay `belief_events` ordered by `at_turn`; reconstruct `active_beliefs as of T`. No new tables required.
- **Filtering.** By `belief_type`, `lifecycle_state`, `authority`, `evidence_event_id`, `turn_range`. All five fields already exist on the underlying tables.
- **Drill-down.** Click any belief → see its full `belief_events` history with linked source events.
- **Diff.** What changed between turn T-1 and turn T.
- **AI-payload preview.** Render what the AI surface would have produced at a given turn and budget — without invoking the LLM.

### 4.2 Filter dimensions

Composable filters, no new schema:

- `belief_type` — e.g. show only `validation_pending` beliefs.
- `lifecycle_state` — `active` / `superseded` / `contradicted` / `retired`.
- `authority` — `confirmed_by_tool` / `confirmed_by_user` / `asserted_by_assistant`.
- `evidence_event_id` — find every belief whose warrant or counter-evidence references a given event.
- `turn_range` — restrict to belief activity between turns T1 and T2.

### 4.3 Output discipline

- Tabular text by default; `--json` on every command for scripting.
- Structured, not narrative. The human surface does not synthesize prose explanations; it surfaces the substrate cleanly.
- Whenever a row references an event or a turn, render the event/turn id so the operator can chase it.

---

## 5. Example user questions

These are the questions an operator would actually type into the CLI. They are the acceptance test for the human surface. If any of them cannot be answered cleanly, the surface has failed its job.

| # | Question | Answered by |
|---|---|---|
| Q1 | "What beliefs were active at turn 16?" | `tkos state <session> --turn 16` |
| Q2 | "What changed between turn 15 and turn 16?" | `tkos timeline <session> --diff 15 16` |
| Q3 | "Why does the system think validation is pending?" | `tkos explain <belief_id>` for the pending belief |
| Q4 | "Which belief caused `action_blocked` on the last deploy attempt?" | `tkos timeline <session>` → find the `risk_check` row → `tkos explain <blocker_belief_id>` |
| Q5 | "What evidence retired or contradicted this belief?" | `tkos explain <belief_id>` (shows `contradicted` / `retired` events with linked source `event_id`) |
| Q6 | "What grounding payload would the AI have received at turn 16 with a 1000-token budget?" | `tkos overlay <session> --turn 16 --budget 1000` |
| Q7 | "Show me every `validation_pending` belief in this session, including retired ones." | `tkos timeline <session> --type validation_pending --include-retired` |
| Q8 | "When was this belief first born, and what event caused it?" | `tkos explain <belief_id>` (the first `born` row) |

If a feature does not answer one of Q1–Q8, it is bloat and should be cut.

---

## 6. Minimal POC scope

CLI first, not full dashboard. Four commands. All four read from the same substrate.

### 6.1 `tkos state <session_id> --turn T`

Active belief set at turn T. Default turn = latest.

```
$ tkos state demo-session --turn 16
session: demo-session   turn: 16

BELIEF_TYPE             CLAIM                                                          STATE       AUTH        LAST_UPDATED
user_approval_pending   approve deploy at turn 14                                      active      assistant   14
validation_complete     pipeline `pytest` passed at turn 13                            active      tool        13
fix_attempted           patch applied to module X at turn 11                           active      assistant   11
report_ready            master_report.html written at turn …                           active      tool        …

  4 active   |   2 retired (use --include-retired)   |   0 contradicted
```

Flags: `--turn T` (negative = relative-to-latest), `--type`, `--lifecycle`, `--authority`, `--include-retired`, `--json`.

Primary question answered: **Q1**.

### 6.2 `tkos timeline <session_id>`

Chronological belief-events stream. Answers Q2, Q4, Q7 directly.

```
$ tkos timeline demo-session --since-turn 12 --type validation_pending
session: demo-session   range: turn 12 → 17

TURN  KIND          BELIEF                                  AUTH        SOURCE_EVENT
12    born          validation_pending: pipeline pending    assistant   ev#4711 (tool_call pytest)
13    confirmed     validation_pending → validation_complete tool       ev#4712 (tool_result pytest exit 0)
13    retired       validation_pending                       —           (superseded by validation_complete)
```

Flags: `--since-turn T` / `--until-turn T`, `--diff T1 T2`, `--type`, `--authority`, `--belief-id`, `--show-evidence`, `--include-risk-checks` (default on), `--json`.

Primary questions answered: **Q2, Q4, Q7**.

### 6.3 `tkos overlay <session_id> --turn T --budget 1000`

Render what the AI surface would have produced at turn T with the given budget. Same code path as the runtime `overlay()` call — no synthesis, no parallel implementation. The point is to let humans inspect what the AI saw.

```
$ tkos overlay demo-session --turn 16 --budget 1000
session: demo-session   turn: 16   budget: 1000   used: 612   omitted_summary: 0

# Operational belief overlay (budget: 1000 tokens, used: 612)

## Active blockers
- user_approval_pending: approve deploy at turn 14 [asserted_by_assistant, last_updated turn 14]

## Tool-confirmed active
- validation_complete: pipeline `pytest` passed at turn 13 [confirmed_by_tool, last_updated turn 13]
…
```

Flags: `--turn T`, `--budget N`, `--action <name>`, `--question-type <name>`, `--json` (returns rank, budget accounting, and rendered string).

Primary question answered: **Q6**. This is the bridge between the AI and human surfaces: same data, same rendering, just shown to the human instead of injected into the model.

### 6.4 `tkos explain <belief_id>`

Single belief's full life story.

```
$ tkos explain b_8f3a2
session: demo-session   belief: b_8f3a2   type: user_approval_pending

CLAIM:            approve deploy at turn 14
CURRENT STATE:    active
AUTHORITY:        asserted_by_assistant
CREATED:          turn 14, by ev#4719 (assistant_message asking for deploy approval)

LIFECYCLE EVENTS:
  TURN  KIND       AUTH       NOTE                                                  SOURCE_EVENT
  14    born       assistant  initial assertion                                     ev#4719
  16    refreshed  assistant  reasserted at deploy attempt                          ev#4732

WARRANT TURNS:           14, 16
COUNTER-EVIDENCE TURNS:  —

REFERENCED BY:
  - risk_check #c_2201 at turn 16: action=deploy → blockers=[b_8f3a2]
```

Flags: `--json`, `--with-events` (expand each linked source event's full payload).

Primary questions answered: **Q3, Q5, Q8**.

### 6.5 Optional — local HTML trace viewer

Build only if cheap. A single-page static viewer at `http://localhost:PORT/<session_id>` that:

- Renders the `tkos timeline` table with collapse/expand on evidence.
- Has a turn-anchor slider that drives the `tkos state` view (Q1 with scrubbing).
- Inline `tkos overlay` preview at the current turn (Q6 with budget slider).
- Click-through from any belief in `state` to its first `born` event in `timeline` (Q3, Q5, Q8).
- Click-through from any `risk_check` row to the blocker beliefs (Q4).

**Implementation budget:** if it is more than a few hundred lines using the simplest available local server + static HTML, defer it. The four CLI commands are the v0.1 requirement; the viewer is the v0.1 stretch.

No remote service. No framework dependency. No CSS framework. No accounts. No persistence beyond the existing SQLite store.

---

## 7. Non-goals (v0.1 human surface)

The following are explicitly **out of scope** for v0.1:

- **No full SaaS dashboard.** No hosted version, no auth, no multi-tenant, no team accounts.
- **No governance / blocking enforcement.** The human surface inspects; it does not intervene. Intervention remains advisory through `risk()` per TKOS-001 §2.4.
- **No multi-agent / multi-session views.** v0.1 is one session at a time.
- **No separate human-only data model.** Everything reads from the substrate defined in TKOS-001 §5.
- **No metrics / dashboards / charts.** Belief-state is structured, not numeric. Aggregations (% sessions with pending validations, etc.) are a v0.2+ question and live in a different surface.
- **No alerting / notifications.** Pull, not push.
- **No log ingestion from arbitrary AI platforms.** v0.1 inherits TKOS-001's event-adapter scope.
- **No replay-into-live-agent.** v0.1 is inspect-only.
- **No `tkos_trace_viewer.py` implementation in this doc.** Sketch only.
- **No terminal UI (TUI).** Plain CLI output only. Curses / Textual / Rich-pretty-tables are v0.2+.
- **No full runtime spec.** TKOS-001 is the sidecar sketch; TKOS-002 is the observability sketch. Neither is the runtime spec.

Several of these — SaaS dashboard, alerting, multi-session views, TUI — are obvious v0.2+ candidates. Listing them as non-goals keeps v0.1 honest.

---

## 8. Risks

Three risks specific to having two peer consumers off one substrate.

### 8.1 AI-facing budget concerns erase human inspectability

The `overlay()` design optimizes for token budget. If the substrate is silently trimmed (e.g. retired beliefs garbage-collected from `belief_events` to keep the SQLite store small), the human surface loses its ability to answer Q5 and Q8 ("what evidence retired this belief", "when was this belief first born").

**Mitigation:** the substrate retains every `belief_events` row indefinitely. Compaction is a v0.2+ question and must be designed against both consumers, not just the AI one.

### 8.2 Dashboard / product instincts bloat the runtime sidecar

If the human-surface team wants a metric (% sessions with stale validations), the temptation will be to add a column to `active_beliefs` or a new table. That is the start of forking the substrate.

**Mitigation:** any new human-surface feature must read from the existing five tables. Derived metrics go in a separate **view layer**, not the source-of-truth schema. If a view layer becomes necessary, it is a v0.2 deliverable with its own design doc.

### 8.3 Either surface becomes second-class by accident

Default failure mode: build the AI surface first (because it has v0.1 evidence behind it), ship it, declare victory, never give the human surface real design attention. Inverse failure mode: build a beautiful trace viewer, lose interest in the budgeted overlay, end up as yet another LangSmith.

**Mitigation:** TKOS-001 and TKOS-002 are co-equal sketches. The v0.1 POC for the human surface (four CLI commands) is small enough to ship alongside the TKOS-001 POC without delaying it. If the human surface keeps getting deferred past TKOS-001 v0.1, that is a signal that the dual-consumer framing has collapsed in practice, and we should re-examine.

---

*End of sketch. No implementation. Co-equal companion to TKOS-001.*
