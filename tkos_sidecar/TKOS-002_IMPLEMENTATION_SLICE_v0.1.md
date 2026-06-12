# TKOS-002 — Implementation Slice v0.1 (read-path only)

**Status:** Documented, not implemented.
**Date drafted:** 2026-06-02
**Companions:** [`TKOS_SIDECAR_SKETCH_v0.1.md`](./TKOS_SIDECAR_SKETCH_v0.1.md) (substrate + runtime API) · [`TKOS-002_HUMAN_OBSERVABILITY_SURFACE_v0.1.md`](./TKOS-002_HUMAN_OBSERVABILITY_SURFACE_v0.1.md) (human surface sketch).

**Framing:** *the morning epiphany — belief observability.* The AI and the human are peer consumers of the same belief-state substrate. This slice proves that framing on the read path before any write-path complexity is built.

---

## 1. What this slice is

The smallest end-to-end thing that proves:

- The shared substrate exists.
- A human consumer can query it.
- Time travel works against `belief_events` replay — not against a hand-written active-state snapshot.

It is **read-path only.** No event ingestion. No rule engine. No overlay. One CLI command. One hand-written fixture session.

If `tkos state demo-session --turn T` returns the correct active set for every T in the fixture, the slice has succeeded.

---

## 2. SQLite DDL

Five tables, matching TKOS-001 §5. `action_checks` is included as a DDL stub only — it stays empty in this slice.

```sql
-- 2.1 events: append-only event log
CREATE TABLE events (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT    NOT NULL,
    turn           INTEGER NOT NULL,
    event_type     TEXT    NOT NULL,
    timestamp      TEXT    NOT NULL,
    payload_json   TEXT    NOT NULL
);
CREATE INDEX idx_events_session_turn ON events(session_id, turn);

-- 2.2 belief_instances: every belief minted, append-only
CREATE TABLE belief_instances (
    belief_id            TEXT    PRIMARY KEY,
    session_id           TEXT    NOT NULL,
    belief_type          TEXT    NOT NULL,
    claim                TEXT    NOT NULL,
    created_turn         INTEGER NOT NULL,
    created_by_event_id  INTEGER REFERENCES events(event_id)
);
CREATE INDEX idx_bi_session ON belief_instances(session_id);

-- 2.3 belief_events: lifecycle audit trail, append-only
-- kind ∈ ('born','refreshed','weakened','contradicted','confirmed','superseded','retired')
CREATE TABLE belief_events (
    belief_event_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    belief_id        TEXT    NOT NULL REFERENCES belief_instances(belief_id),
    event_id         INTEGER REFERENCES events(event_id),
    kind             TEXT    NOT NULL,
    at_turn          INTEGER NOT NULL,
    authority        TEXT    NOT NULL,  -- 'asserted_by_assistant' | 'confirmed_by_tool' | 'confirmed_by_user'
    note             TEXT
);
CREATE INDEX idx_be_belief ON belief_events(belief_id);
CREATE INDEX idx_be_turn ON belief_events(at_turn);

-- 2.4 active_beliefs: VIEW over belief_events at latest turn
-- The CLI does NOT read this view for --turn T queries; it runs the
-- replay query inline (see §4.2) so that time-travel queries reconstruct
-- state from the audit trail. This view is for the "current state"
-- common case only.
CREATE VIEW active_beliefs AS
SELECT
    bi.belief_id,
    bi.session_id,
    bi.belief_type,
    bi.claim,
    -- Lifecycle: derive from most recent belief_events row per belief_id
    (SELECT be.kind
       FROM belief_events be
      WHERE be.belief_id = bi.belief_id
      ORDER BY be.at_turn DESC, be.belief_event_id DESC
      LIMIT 1) AS last_kind,
    (SELECT be.at_turn
       FROM belief_events be
      WHERE be.belief_id = bi.belief_id
      ORDER BY be.at_turn DESC, be.belief_event_id DESC
      LIMIT 1) AS last_updated_turn,
    (SELECT be.authority
       FROM belief_events be
      WHERE be.belief_id = bi.belief_id
        AND be.authority = 'confirmed_by_tool'
      ORDER BY be.at_turn DESC LIMIT 1)
      IS NOT NULL                                        AS tool_confirmed
FROM belief_instances bi
WHERE NOT EXISTS (
    SELECT 1
      FROM belief_events be
     WHERE be.belief_id = bi.belief_id
       AND be.kind IN ('retired','contradicted','superseded')
);

-- 2.5 action_checks: DDL stub, unused in this slice
CREATE TABLE action_checks (
    check_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id                TEXT    NOT NULL,
    at_turn                   INTEGER NOT NULL,
    action                    TEXT    NOT NULL,
    blocker_belief_ids_json   TEXT    NOT NULL,
    rationale                 TEXT    NOT NULL,
    timestamp                 TEXT    NOT NULL
);
```

**Notes:**

- The `active_beliefs` view answers "what is active now?" It does **not** parameterize on a turn — it always reflects the latest turn. Turn-T queries route through the inline replay in §4.2.
- `belief_events.event_id` is nullable because some lifecycle transitions (e.g. `superseded` when a new belief of the same type lands) may not have a single triggering event row.

---

## 3. Hand-written fixture

One coding-assistant session, ~12 turns, exercises six belief types. No event ingestion; the rows below are inserted directly into the SQLite store at fixture-load time.

### 3.1 Session walkthrough

| Turn | What happens | Belief lifecycle |
|------|-------------|------------------|
| 1 | User reports failing test in `module_x` | — |
| 2 | Assistant proposes a fix | — |
| 3 | Assistant edits `module_x.py` | `fix_attempted #1` **born** (asserted) |
| 4 | Assistant runs `pytest`; deploy not allowed while unvalidated | `validation_pending #1` **born** (asserted); `action_blocked (deploy)` **born** (asserted) |
| 5 | Tool returns: pytest exit 1 | `pipeline_failed` **born** (tool); `validation_pending #1` **contradicted → retired** |
| 6 | (state inspection turn) | — |
| 7 | Assistant edits `module_x.py` again | `fix_attempted #2` **born** (asserted); `fix_attempted #1` **superseded → retired** |
| 8 | Assistant runs `pytest` | `validation_pending #2` **born** (asserted) |
| 9 | Tool returns: pytest exit 0 | `validation_complete` **born** (tool); `validation_pending #2` **confirmed → retired**; `pipeline_failed` **superseded → retired**; `action_blocked (deploy)` **superseded → retired** |
| 10 | (state inspection turn) | — |
| 11 | Assistant deploys; report written | `report_ready` **born** (tool) |
| 12 | (state inspection turn) | — |

### 3.2 Belief inventory (final state)

| belief_id | type | active at turn 12 | created_turn | last_updated_turn |
|---|---|---|---|---|
| b_001 | fix_attempted | retired | 3 | 7 |
| b_002 | validation_pending | retired | 4 | 5 |
| b_003 | action_blocked | retired | 4 | 9 |
| b_004 | pipeline_failed | retired | 5 | 9 |
| b_005 | fix_attempted | **active** | 7 | 7 |
| b_006 | validation_pending | retired | 8 | 9 |
| b_007 | validation_complete | **active** | 9 | 9 |
| b_008 | report_ready | **active** | 11 | 11 |

(All within `session_id = 'demo-session'`.)

### 3.3 Fixture loader

Implementation: a single Python module `tkos_fixtures/demo_session.py` that:

- Opens / creates the SQLite store.
- Runs the DDL from §2 if tables don't exist.
- Inserts rows directly into `events`, `belief_instances`, `belief_events`. No rule engine. No event-to-belief derivation.

The `events` table can be left empty in this slice or populated with one synthetic row per source event referenced by `belief_events.event_id`. Either is acceptable; populating events is preferable so that `--show-evidence`-style flags will work when added later, but it is not required for the §6 acceptance test.

---

## 4. CLI command

One command. One subcommand. No flags beyond what is listed.

### 4.1 Command surface

```
tkos state <session_id> --turn T [--include-retired] [--json]
```

- `<session_id>` — required positional.
- `--turn T` — required for the slice (no default; force the operator to commit to a turn so time travel is exercised). Accepts integer ≥ 1. Negative `T = -k` semantics are deferred to a later slice.
- `--include-retired` — also show beliefs whose last lifecycle event was `retired`, `contradicted`, or `superseded`. Off by default.
- `--json` — emit JSON instead of the tabular text. Same content, different rendering.

### 4.2 Reconstruction query

For each (`session_id`, `turn` = T):

1. Find all `belief_instances` with `session_id = S` and `created_turn ≤ T`.
2. For each such belief, find its **latest** `belief_events` row with `at_turn ≤ T` (ordered by `at_turn DESC, belief_event_id DESC`).
3. The belief's lifecycle state at T is the `kind` of that row, mapped to a state:
   - `born`, `refreshed`, `confirmed` → `active`
   - `weakened`, `contradicted` → `contradicted`
   - `superseded`, `retired` → `retired`
4. Exclude rows whose mapped state is `retired` or `contradicted`, unless `--include-retired` is set.

The CLI **must not** read the `active_beliefs` view for `--turn T` queries. The view is latest-turn only; turn-T queries replay against `belief_events` per the algorithm above. This separation is the load-bearing acceptance criterion.

### 4.3 Authority resolution

For each surviving belief, compute:

- `authority` = highest-rank authority observed in `belief_events` for this belief at `at_turn ≤ T`, rank `confirmed_by_tool > confirmed_by_user > asserted_by_assistant`.
- `warrant_turns` = ordered list of `at_turn` from all `belief_events` rows with `kind ∈ ('born', 'refreshed', 'confirmed')` at `at_turn ≤ T`.
- `last_updated_turn` = the `at_turn` of the latest matching row.

---

## 5. Expected output

### 5.1 Tabular (default)

```
$ tkos state demo-session --turn 8
session: demo-session   turn: 8

BELIEF_TYPE          CLAIM                                              STATE    AUTH        WARRANT  LAST_UPDATED
fix_attempted        patch applied to module_x at turn 7                active   assistant   [7]      7
validation_pending   pytest invoked, awaiting result                    active   assistant   [8]      8
action_blocked       deploy blocked until validation_complete           active   assistant   [4]      4

  3 active   |   3 retired (use --include-retired)   |   0 contradicted
```

Columns:
- `BELIEF_TYPE` — from `belief_instances.belief_type`.
- `CLAIM` — from `belief_instances.claim`.
- `STATE` — lifecycle state at the queried turn (`active` only, unless `--include-retired`).
- `AUTH` — `tool` / `user` / `assistant`, abbreviated from the authority resolution in §4.3.
- `WARRANT` — list of `warrant_turns` (e.g. `[4,7]` for a belief born at 4 and refreshed at 7).
- `LAST_UPDATED` — `last_updated_turn`.

Footer counts include `retired` and `contradicted` populations even when filtered out, so the operator knows what they're hiding.

### 5.2 JSON

```json
{
  "session_id": "demo-session",
  "turn": 8,
  "active": [
    {
      "belief_id": "b_005",
      "belief_type": "fix_attempted",
      "claim": "patch applied to module_x at turn 7",
      "state": "active",
      "authority": "asserted_by_assistant",
      "warrant_turns": [7],
      "last_updated_turn": 7,
      "created_turn": 7
    },
    {
      "belief_id": "b_006",
      "belief_type": "validation_pending",
      "claim": "pytest invoked, awaiting result",
      "state": "active",
      "authority": "asserted_by_assistant",
      "warrant_turns": [8],
      "last_updated_turn": 8,
      "created_turn": 8
    },
    {
      "belief_id": "b_003",
      "belief_type": "action_blocked",
      "claim": "deploy blocked until validation_complete",
      "state": "active",
      "authority": "asserted_by_assistant",
      "warrant_turns": [4],
      "last_updated_turn": 4,
      "created_turn": 4
    }
  ],
  "counts": { "active": 3, "retired": 3, "contradicted": 0 }
}
```

---

## 6. Acceptance test

Three turn-anchor assertions, executed against the fixture.

### 6.1 Test A — pre-validation (turn 8)

```
$ tkos state demo-session --turn 8 --json | jq '.active | map({type:.belief_type, state})'
```

Expected (order-independent):

```json
[
  { "type": "fix_attempted",      "state": "active" },
  { "type": "validation_pending", "state": "active" },
  { "type": "action_blocked",     "state": "active" }
]
```

`validation_pending` and `action_blocked` MUST both be active. This is the failure mode the substrate is supposed to catch.

### 6.2 Test B — post-validation (turn 10)

```
$ tkos state demo-session --turn 10 --json | jq '.active | map({type:.belief_type, state})'
```

Expected (order-independent):

```json
[
  { "type": "fix_attempted",       "state": "active" },
  { "type": "validation_complete", "state": "active" }
]
```

`validation_pending` MUST be absent (retired at turn 9). `action_blocked` MUST be absent (retired at turn 9). `validation_complete` MUST be active.

### 6.3 Test C — substrate provenance

The reconstruction must come from `belief_events` replay, not from a stored snapshot. Verifiable two ways:

1. **No state-snapshot table.** The DDL in §2 defines no per-turn snapshot table. If one is added later, this test fails by inspection.
2. **Drop-and-recompute.** Running `DROP VIEW active_beliefs` and re-running both Test A and Test B must still pass. The view is for the "current state" common case only; it is not on the `--turn T` code path.

### 6.4 Honesty checks

Every test must run against the fixture loaded fresh from §3.3. No hand-edited active-state file. No manual SQL inserts into `active_beliefs` (it's a view, so this would fail anyway — but the constraint is named here explicitly).

---

## 7. Non-goals (this slice)

- **No rule engine.** No event → belief derivation. Beliefs are inserted by the fixture loader.
- **No event ingestion.** No adapter for Claude Code logs, Cursor logs, or any real event source.
- **No overlay ranking.** `tkos overlay` is not implemented; the AI surface is out of scope for this slice.
- **No `tkos timeline`, `tkos explain`, or any other CLI command.** Just `tkos state`.
- **No TUI.** Plain tabular text or `--json`. No curses, Textual, Rich, or color.
- **No dashboard.** No HTML viewer. Stretch goal from TKOS-002 §6.5 is explicitly deferred.
- **No agent integration.** Nothing calls `tkos` from inside an assistant. Operator inspection only.
- **No governance / risk / action checks.** `action_checks` DDL exists; no logic touches it.
- **No write path beyond fixture loading.** No `observe()`. No `tkos observe`. Reads only.

---

## 8. Rationale

This slice proves the **shared substrate** and the **human time-travel read path** before any write-path complexity is built.

The dual-consumer framing in TKOS-002 ("AI and human are peer consumers of the same belief-state substrate") is empirically meaningless until you can demonstrate at least one consumer querying the substrate end-to-end. Building the rule engine first inverts the order: you'd be proving the write path before knowing whether the read path actually answers a human's question.

By starting on the read path with a fixture, two things become true:

1. **The substrate's shape is validated.** If `tkos state --turn T` cannot cleanly answer the §6 tests against the fixture, the schema is wrong. Better to discover that before any deterministic-rule code is written against it.
2. **The dual-consumer claim has a single concrete demonstration.** Once `tkos state` works, the next slice (`tkos timeline` against the same store) and the slice after (`tkos overlay` against the same store) become incremental work — each one is "render the substrate differently for a different consumer."

The rule engine can come last. It's the same write-path code regardless of how many consumers exist; postponing it loses nothing about the dual-consumer framing.

If `tkos state` lands and the §6 tests pass, the read path is proven. From there:

- **Slice 2.** Add `tkos timeline` (same store, different render).
- **Slice 3.** Add `tkos overlay` (same store, ranking + token budget — bridges to the AI surface).
- **Slice 4.** Add `tkos explain` (same store, single-belief drill-down).
- **Slice 5.** Replace the fixture with a real ingestion path: events arrive via `observe()`, rule engine derives `belief_instances` + `belief_events`. Fixtures stay as test data.

Each slice extends without forking the substrate.

---

*End of implementation slice. Not implemented yet. Approved-for-build when reviewed.*
