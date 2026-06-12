# TKOS Write-Path Sidecar — Scope v0.3.2

**Date:** v0.2 → v0.2.1 → v0.3.1 → v0.3.2 (this version, 2026-06-06)
**Status:** LOCKED at v0.3.2 — implementation-ready at executable-contract level. Supersedes v0.3.1.

**v0.3.1 → v0.3.2 patches (four scope-level fixes in this doc):**
- **Fix A — Replay idempotency on `raw_lines`.** §6.1 `ingest_source_line()` previously did a plain INSERT, which conflicts with `raw_lines.UNIQUE(session_id, source_line_number)` on replay. Locked behavior: if the existing row's `raw_line_sha256` matches the incoming, return a no-op (do NOT rerun rules); if it differs, raise `SourceMutationError` and refuse the ingest.
- **Fix B — Session finalization.** §6.1 + §8.3 — added explicit `finalize_session(session_id, rollout_path)` operation. Computes `raw_rollout_sha256` from the source file bytes, sets `total_line_count` and `capture_ended_at`, validates `line_hash_chain` against accumulated value. Triggered after `task_completion` ingest (live) or last-line ingest (batch). Without this, `session_status` non-null final-hash columns are unreachable.
- **Fix C — `event_idx` counts mapped events only.** §4.4 + §6.2 — `event_idx` is monotonic within a turn counting only **mapped** events. Ignored-known lines do not get an `event_idx` (left null in `raw_lines`). Without this, the §6.2 sequence-validation check fails on real sessions where ignored-known lines interleave with mapped events.
- **Fix D — Normalize stale "four" references.** §7 + §11 (§9 build-plan + closing summary) — every reference to the completeness check count now reads **five**.

Cross-doc patches in this v0.3.2 revision cycle: Fix 4 (synthetic action_blocked belief_id) → `TKOS_READ_PATH_MIGRATION_v0.3.2.md`; Fix 5 (apply_patch Move-to header) → `INTEGRATION_PATTERN_v0.1.3.md`. RULES_SPEC stays at v0.3.1 (no rule-level changes in this cycle).

---

**v0.2.1 → v0.3.1 patches (retained from previous cycle for trace):**

**v0.2.1 → v0.3.1 patches (four issues addressed in this doc; cross-doc patches noted below):**
- **Fix 1 — SQLite migration must execute.** §8.1 SQLite ALTER cannot add a `NOT NULL UNIQUE` column directly, and column-dependent DEFAULTs are not valid. Migration sequence rewritten: add nullable → backfill → create unique index → enforce non-null in app code. Index references corrected.
- **Fix 2 — Codex ignored-known taxonomy.** §4.1 ignored-known set expanded to include `response_item(payload.type=message, role=user)` and `role=developer`. Both are duplicates/context of `event_msg(type=user_message)` and developer-instruction headers respectively.
- **Fix 3 — Source-line ingestion protocol.** §6.1 atomicity invariant rewritten as a single `ingest_source_line(raw_line)` operation that atomically persists `raw_lines`, classifies, optionally normalizes and persists an event, and runs rules.
- **Fix 7 — Stale completion criteria.** §7 acceptance test 6 uses belief-event-sequence equivalence (per RULES_SPEC §5); test 9 uses chronological ordering; completeness check count normalized to five everywhere.

Cross-doc patches in this revision cycle: Fix 4 (K=3 turns) → `RULES_SPEC_v0.3.1.md`; Fix 5 (path enrichment) → `INTEGRATION_PATTERN_v0.1.2.md`; Fix 6 (action_blocked render) → `TKOS_READ_PATH_MIGRATION_v0.3.1.md`.

**v0.2 → v0.2.1 amendments (six findings):**
- **Finding 1** (raw-line accounting): three categories — Mapped / Ignored-known / Unrecognized — applied in §4.1 and §6.2; new `raw_lines` table in §8.
- **Finding 2** (transcript hash): replaced single-hash check with two distinct hashes (`raw_rollout_sha256` + `line_hash_chain`); applied in §6.2 and §8.3.
- **Finding 3** (read-path is NOT unchanged): explicit acknowledgment in §2; full migration scope split into new [`TKOS_READ_PATH_MIGRATION_v0.2.md`](./TKOS_READ_PATH_MIGRATION_v0.2.md).
- **Finding 4** (SQLite ALTER limits): §8.1 now keeps `event_id` integer PK and adds `source_event_id TEXT NOT NULL UNIQUE`; no ALTER PRIMARY KEY.
- **Finding 6** (machine-stable hash): §3.1 hash inputs no longer include absolute path.
- **Finding 7** (turn boundary): §3.2 + §4.4 use Codex native `turn_id` with deterministic mapping; fallback rule documented.
- **Finding 9** (export ordering): §10 Q6 sorts by `(turn_idx, event_idx, source_line_number)`, not lexicographic `source_event_id`.
**Predecessors:**
- [`TKOS_WRITE_PATH_SCOPE_v0.1.md`](./TKOS_WRITE_PATH_SCOPE_v0.1.md) — v0.1 / v0.1.1; superseded by this document. v0.1.1 conflated software scope, v0.4c2 substrate admissibility, and streaming/batch correctness in ways that a build-time audit (Codex review, 2026-06-05) found contradictory before any code flowed.
- [`TKOS_SIDECAR_SKETCH_v0.1.md`](./TKOS_SIDECAR_SKETCH_v0.1.md) — architectural sketch from 2026-06-01. Still load-bearing for §2 API shape and the design principles.
- [`TKOS-002_IMPLEMENTATION_SLICE_v0.1.md`](./TKOS-002_IMPLEMENTATION_SLICE_v0.1.md) — the read-path slice (existing `tkos.py`).
- [`operational_belief_v1/build_operational_belief_substrate.py`](../operational_belief_v1/build_operational_belief_substrate.py) — the v0.1 batch rule engine.
- ``reference_codex_trace_storage.md`` (internal memory note) — Codex rollout JSONL location and structure.
- ``project_v04c2_substrate_separation.md`` (internal memory note) — the locked decision separating this software build from v0.4c2 substrate work.

---

## v0.1.1 → v0.2 amendment log

Nine substantive changes; the rest is restructuring around them.

1. **Software/substrate separation.** This scope is now software-only. It does not produce the v0.4c2 substrate. A fresh Codex project will start that work after this software's trace capture is verified.
2. **Canonical event identity changed.** `source_event_id` is now the primary identity; `(session_id, turn_idx, event_idx)` are derived fields.
3. **Normalized event schemas locked before rules.** Each event type has a typed schema fixed in §4 before any rule references it.
4. **Streaming/batch equivalence narrowed.** Test scope is the *shared canonical derivation spec over the v0.1 belief subset*, not full pipeline equality.
5. **Atomicity invariant added.** Event persistence + rule effects are wrapped in a single transaction.
6. **Capture completeness checks added.** Sequence validation + transcript hash, not "we tried to capture everything."
7. **Retro-minting uses `effective_turn` and `observed_at_turn`** as separate fields, not one timestamp doing double duty.
8. **Event identity is hash-derived if Codex lacks native IDs**, deterministic across replays.
9. **Acceptance tests = nine explicit.** The export-determinism test from v0.1.1 stays; renumbered against the new structure.

---

## §1 Purpose and scope

### §1.1 What this is

The TKOS read-path slice already implements substrate-to-projection queries. The write-path is the missing piece: a streaming engine that converts a live event stream into the substrate the read-path consumes.

This document scopes **v0.2 of the write-path as software-only**. The chosen input source is the Codex rollout JSONL. The deliverable is working software that ingests Codex events, mints and updates beliefs deterministically, and exposes the same SQLite schema the read-path queries.

### §1.2 What this is NOT

This software's captured traces are **not the v0.4c2 substrate**. The v0.4c2 substrate is a separate fresh Codex project that begins after this software is verified to capture traces correctly (see `project_v04c2_substrate_separation.md`).

The reason: any exploratory work, scaffolding, or pre-capture activity in this project necessarily violates the v0.4c2 admission §4 hard rule. Trying to do both at once was the v0.1.1 mistake.

### §1.3 In-scope (v0.2)

- HTTP ingestion endpoint accepting one event per POST.
- Persistent event storage in SQLite (same DB as the read-path).
- A streaming port of the v0.1 rule engine that fires per event and writes `belief_events` rows under transactional guarantees.
- A materialized `active_beliefs` view backed by `belief_instances` + `belief_events`.
- A Codex trace adapter that reads `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` line-by-line and POSTs one event per line.
- CLI: `tkos serve`, `tkos replay <trace.jsonl>`, `tkos verify <session_id>` (the new capture-completeness check), `tkos export <session_id>`.
- Nine acceptance tests (§7).

### §1.4 Out-of-scope (v0.2)

Unchanged from v0.1.1:

- LLM-driven belief extraction.
- Auth, multi-tenant, network protocols beyond local HTTP.
- Trace viewer UI; CLI only.
- IDE integration beyond Codex.
- Cross-session reasoning.
- Tool registration to the assistant.
- Overlay auto-injection.
- Performance optimization beyond single-user workloads.
- Postgres / replication / clustering.
- Production-grade observability of the sidecar itself.

---

## §2 Reference architecture

The existing TKOS read-path (`tkos_sidecar/tkos.py`) requires a v0.2-aligned migration (v0.2.1 — finding 3 fix). The migration is scoped in [`TKOS_READ_PATH_MIGRATION_v0.2.md`](./TKOS_READ_PATH_MIGRATION_v0.2.md) and ships alongside the write-path build's step 5 of §9. Specifically: `reconstruct_state` must filter by `effective_turn` (not `at_turn`), `weakened` must remain in active state, and `action_blocked` must be rendered synthetically at query time. The original v0.2 claim that the read-path was unchanged was wrong; this v0.2.1 explicitly recognizes the migration as a parallel work item.

The write-path adds three new files:

```
tkos_sidecar/
├── tkos.py                    (existing, unchanged)
├── test_tkos.py               (existing, unchanged)
├── ingest.py                  (new — HTTP + atomic-write dispatcher)
├── rules.py                   (new — streaming rule engine)
├── trace_adapter_codex.py     (new — Codex rollout JSONL → ingest)
├── test_ingest.py             (new)
├── test_rules.py              (new)
├── test_trace_adapter.py      (new)
├── test_capture_completeness.py (new)
└── tkos.db                    (existing schema + additive write-path columns)
```

Read-path is read-only of the write-path's output: write-path adds rows to `events`, `belief_instances`, `belief_events`, and new operational tables; read-path queries these tables via existing functions.

---

## §3 Canonical event identity

This is the architectural primitive everything else relies on.

### §3.1 `source_event_id` is primary

Every ingested event has a stable, deterministic `source_event_id`. This is the primary key for idempotency, replay, deduplication, and audit.

**If Codex emits native event IDs in the rollout JSONL:** use those.

**Otherwise (the v0.2.1 default — finding 6 fix):**

```
source_event_id = sha256(
    session_id          + "\n" +
    str(source_line_number) + "\n" +
    sha256(raw_line_bytes)
)
```

Where `session_id` is the Codex session UUID (from the rollout's `session_meta` payload `id` field), `source_line_number` is the 1-indexed line number, and `raw_line_bytes` is the exact byte content of the JSONL line (UTF-8, no trailing newline). Absolute paths are deliberately excluded — they differ across machines for the same conceptual session.

Same Codex rollout JSONL → same `source_event_id` for each line, regardless of which machine reads it.

### §3.2 Derived identity tuple

`(session_id, turn_idx, event_idx)` are **derived** fields, useful for reasoning, grouping, and queries, but they are not the primary key.

- `session_id`: stable within a rollout file (the Codex session UUID from `session_meta.payload.id`).
- `turn_idx`: derived from Codex's native `turn_id` per §4.4. `turn_idx = -1` for lines without an associated turn (e.g., `session_meta`).
- `event_idx`: monotonic within a turn_idx, assigned by the adapter in source-line order.

If the adapter recomputes these from the same rollout, it gets the same values. They are deterministic but secondary; the hash is what enforces uniqueness.

### §3.3 Why this matters

Two reasons:

- **Idempotency at the rollout-line layer.** Replaying the same rollout produces the same `source_event_id`s. Inserting an already-present `source_event_id` is a no-op. No need to reason about turn boundaries to know if you've seen an event.
- **Cross-source compatibility.** When a future adapter (e.g., a Claude Code adapter, or any other agent harness) is built, it uses the same identity scheme. The substrate doesn't care where events came from; the read-path's queries work uniformly.

---

## §4 Normalized event schema (locked before rules)

The rule engine fires against this schema. Locking it first prevents the rules from drifting against undefined event shapes.

### §4.1 Rollout line categories (v0.2.1 — finding 1 fix)

Every line in a Codex rollout JSONL falls into exactly one of three categories. All three count toward capture completeness; only the first becomes an event.

| Category | Definition | Persistence | Becomes event? |
|---|---|---|---|
| **Mapped** | Translates to an event_type below per the adapter normalization rules (INTEGRATION_PATTERN §3.5) | `events` table (and `raw_lines`) | Yes |
| **Ignored-known** | Source type is explicitly recognized as non-event | `raw_lines` table only | No |
| **Unrecognized** | Source type matches neither | `raw_lines` with `flag=unrecognized` | No; flips admissibility to false |

**Ignored-known set (v0.3.1, locked — fix 2 expands):**

```
session_meta
turn_context
event_msg(payload.type == token_count)
event_msg(payload.type == agent_message)                              # duplicate of response_item(payload.type == message)
response_item(payload.type == message, role == user)                  # NEW (fix 2): duplicate of event_msg(type=user_message)
response_item(payload.type == message, role == developer)             # NEW (fix 2): developer-instruction header / context, not a substrate event
```

Any source line whose type is not Mapped or Ignored-known is Unrecognized.

**Mapped event_types:**

| `event_type`        | Required fields beyond identity | Optional |
|---|---|---|
| `user_message`      | `content` (string) | — |
| `assistant_message` | `content` (string) | — |
| `assistant_reasoning` | `content` (string) | — |
| `tool_call`         | `tool_name`, `command` (when shell), `call_id` | `paths` (list) |
| `tool_result`       | `call_id`, `output`, `exit_code` | `stderr_first_line`, `paths` |
| `task_start`        | `task_name` | `task_id` |
| `task_completion`   | `task_id` | `final_status` |

Adapter rules for deriving these fields from Codex rollout records are locked in [`INTEGRATION_PATTERN_v0.1.md`](./INTEGRATION_PATTERN_v0.1.md) §3.5.

### §4.2 Event record shape

Every persisted event row carries:

```
{
  source_event_id:      str,    # primary key, hash from §3.1
  session_id:           str,
  turn_idx:             int,    # derived
  event_idx:            int,    # derived, monotonic within turn
  event_type:           str,    # from §4.1 taxonomy
  timestamp:            str,    # ISO 8601, from rollout
  payload:              dict,   # event-type-specific fields per §4.1
  source_rollout_path:  str,    # for replay + audit
  source_line_number:   int,    # for replay + audit
  call_id:              str | null,  # for tool_call/tool_result correlation
}
```

### §4.3 Schema validation at ingest

The HTTP endpoint validates every incoming event against §4.1 before persistence. Validation failures are logged with the source line number; the offending event is rejected; the session is marked `admissibility-eligible=false`. Validation has no fuzzy paths — a missing required field is a hard reject.

### §4.4 Turn-boundary rule (v0.2.1 — finding 7 fix)

`turn_idx` is derived from Codex's native `turn_id`. The locked derivation:

1. Track each distinct `turn_id` observed in the rollout as it first appears.
2. The first `turn_id` observed maps to `turn_idx = 0`. The next new `turn_id` maps to `turn_idx = 1`. And so on.
3. All lines associated with the same `turn_id` share the same `turn_idx`.
4. `event_idx` is monotonic within a `turn_idx`, assigned in source-line order starting at 0, **counting only Mapped events (v0.3.2 — fix C)**. Ignored-known and Unrecognized lines do not consume `event_idx` values. Their `event_idx` is null in `raw_lines`. This is what makes the §6.2 sequence-validation check pass on real sessions where ignored-known lines interleave with mapped events.
5. Lines with no associated `turn_id` (e.g., `session_meta`, `turn_context`) are persisted to `raw_lines` with `turn_idx = -1` and do not become events.

`turn_id` is found in:
- `event_msg.payload.turn_id` (for `task_started`, `task_complete`)
- `turn_context.payload.turn_id`

Adjacent `response_item` and `event_msg` lines inherit the most-recent prior `turn_id` observed in the stream.

Fallback (for non-Codex adapters whose source doesn't provide native turn_ids): increment `turn_idx` on `user_message` OR `task_start` with alternation enforcement. That fallback lives in the adapter's own spec; the Codex adapter uses native `turn_id` per the rules above.

---

## §5 Streaming rule engine

### §5.1 Shared canonical derivation spec

The streaming engine and the v0.1 batch engine each implement a **derivation spec**: for each belief type in their supported subset, what events mint, refresh, weaken, contradict, confirm, or retire it.

The v0.2 streaming engine implements a strict subset of the v0.1 batch engine's belief types. For belief types in the streaming subset, **both engines must use the same derivation spec** — same predicates, same lifecycle transitions, same authority handling.

This shared spec is the load-bearing artifact for §7 acceptance test 6. It lives at:

```
tkos_sidecar/RULES_SPEC_v0.2.md
```

(A separate document to be written before rule code. The spec is the locked contract; the code is its implementation.)

### §5.2 v0.2 supported belief subset

The minimum set sufficient for end-to-end demonstration:

- `fix_attempted`
- `validation_pending`
- `validation_complete`
- `pipeline_running`
- `pipeline_failed`
- `action_blocked`
- `user_approval_pending`
- `report_ready`

These are the eight from the sketch §3, unchanged. The optional `failure_signature_active` is deferred to a later version.

### §5.3 Event-to-rule dispatch

Per event type, the engine evaluates a small fixed set of rules. Each rule has:

- A predicate over current `active_beliefs` plus the incoming event.
- A lifecycle action: `born` / `refreshed` / `weakened` / `contradicted` / `confirmed` / `retired`.
- A one-line `note` recorded in `belief_events.note` for audit.

The dispatch table is enumerated explicitly in `RULES_SPEC_v0.2.md`. Rules cannot reference event fields outside the §4.1 schema for their event type.

### §5.4 `effective_turn` and `observed_at_turn` for retro-minting

Some rules fire retroactively. The canonical example: minting `pipeline_running` after K=3 turns without a matching `tool_result`. The belief was effectively true at the original `tool_call` turn, but only observable as `pipeline_running` once enough subsequent turns have passed without resolution.

The audit trail records both:

- `effective_turn` — the turn at which the belief is asserted to be true.
- `observed_at_turn` — the turn at which the rule fired and the belief was minted.

For non-retro rules, the two values are equal. For retro-minted rules, `observed_at_turn > effective_turn`. The read-path's `reconstruct_state(turn=T)` should include retro-minted beliefs whose `effective_turn ≤ T`, even if `observed_at_turn > T`. (This is a read-path semantic decision; the read-path's existing `reconstruct_state` already supports it once the new column is present.)

### §5.5 What v0.2 does NOT do

- No LLM scoring inside rules.
- No probabilistic belief weights. Lifecycle states are categorical.
- No retroactive rule changes (rule code updates require a full replay from event 1 to take effect).
- No fuzzy belief matching across sessions. Beliefs are session-local.

### §5.6 Determinism guarantee

Given the same locked `RULES_SPEC_v0.2.md` and the same event stream (identified by `source_event_id`), the engine produces the same `belief_events` rows in the same order. This is what makes `tkos replay` reproducible and acceptance test 5 verifiable.

---

## §6 Atomicity and capture completeness

### §6.1 Source-line ingestion protocol (v0.3.1 — fix 3 rewrite)

The atomic unit of ingestion is `ingest_source_line(raw_line)`, NOT `observe(event)`. The HTTP endpoint takes one raw rollout line per POST and performs the following inside a single SQLite transaction:

```
def ingest_source_line(raw_line: bytes, session_id, source_line_number):
    raw_line_sha = sha256(raw_line)
    source_event_id = compute_source_event_id(
        session_id, source_line_number, raw_line_sha)

    # 0. Replay-idempotency check (v0.3.2 — fix A)
    #    raw_lines has UNIQUE(session_id, source_line_number).
    #    If a row already exists, compare hashes:
    #      - match: this is a replay of the same source line; no-op.
    #      - mismatch: the source has mutated; hard-fail.
    existing = SELECT raw_line_sha256, category FROM raw_lines
        WHERE session_id=:session_id AND source_line_number=:source_line_number
    if existing is not None:
        if existing.raw_line_sha256 == raw_line_sha:
            # idempotent replay — rules already fired (or were not applicable);
            # return early without rerunning.
            return IngestResult(status="idempotent_replay",
                                category=existing.category)
        else:
            raise SourceMutationError(
                f"raw_lines row at ({session_id}, {source_line_number}) "
                f"exists with hash {existing.raw_line_sha256}; incoming "
                f"hash {raw_line_sha} differs. Refusing ingest."
            )

    # 1. Persist raw_lines (first time)
    parsed = parse_json(raw_line)
    category = classify(parsed)   # mapped / ignored-known / unrecognized
    INSERT INTO raw_lines (session_id, source_line_number, raw_line_bytes,
                           raw_line_sha256, category, flag, turn_idx,
                           event_idx)
    # event_idx is null for ignored-known and unrecognized; computed below for mapped
    # (per fix C, event_idx counts MAPPED events only)

    if category == "mapped":
        # 2a. Normalize and persist the event (adapter rules)
        event = adapter_normalize(parsed)
        INSERT INTO events (source_event_id, session_id, turn, event_idx,
                            event_type, timestamp, payload, ...)
        UPDATE raw_lines SET event_id = last_inserted_event_id
          WHERE session_id=:session_id AND source_line_number=:source_line_number

        # 2b. Run all applicable rules
        for rule in dispatch(event.event_type):
            transition = rule.evaluate(event, current_active_beliefs)
            if transition:
                INSERT INTO belief_events (...)
                # belief_instances upserted as needed

        # 2c. Update active_beliefs view
        recompute_active_for(event.session_id)

        # 2d. Append ingest_log
        INSERT INTO ingest_log (source_event_id, session_id, received_at,
                                rules_fired, transaction_status='committed')

    elif category == "unrecognized":
        # Mark session ineligible within same transaction
        UPDATE session_status SET admissibility_eligible=0,
          failure_reasons = json_append(failure_reasons,
            'unrecognized_line:' || source_line_number)
        WHERE session_id=:session_id

    # category == "ignored-known": nothing further; raw_lines write is the whole effect
```

The entire sequence either commits or rolls back as one. The DB is never in a half-applied state. Specifically:

- `raw_lines` is always written (whether or not an event is created).
- For mapped lines: the event row + all rule-derived `belief_events` rows + `active_beliefs` update + `ingest_log` row all commit together.
- For ignored-known lines: only `raw_lines` commits.
- For unrecognized lines: `raw_lines` + `session_status.admissibility_eligible=0` commit together.

If a rule throws an unhandled exception inside step 2b, the entire transaction rolls back. The rule failure is logged to `rule_failures` (separate non-transactional write path so it survives the rollback). The HTTP endpoint returns 500 with the rule name. The session is marked `admissibility-eligible=false` on the next successful ingest of any line for the same session, or via an out-of-band update.

**Concurrency:** v0.3.2 assumes single-writer per session. Multiple sessions can ingest in parallel; same-session interleaving is not in scope.

### §6.1a `finalize_session()` (v0.3.2 — fix B)

`ingest_source_line()` is per-line and runs incrementally. It does not know whether more lines will follow. Finalizing the session — computing `raw_rollout_sha256` over the full file, locking `total_line_count`, setting `capture_ended_at` — is a separate explicit operation:

```
def finalize_session(session_id, rollout_path):
    # Compute hash over the source file's complete bytes
    raw_rollout_sha256 = sha256_of_file(rollout_path)
    total_line_count = count_non_empty_lines(rollout_path)

    # Validate line_hash_chain against accumulated raw_lines (no-op if it has been
    # kept in sync incrementally; included here as a safety check)
    chain = compute_line_hash_chain_from_raw_lines(session_id)

    BEGIN TRANSACTION
    UPDATE session_status
      SET raw_rollout_sha256 = :raw_rollout_sha256,
          total_line_count = :total_line_count,
          line_hash_chain = :chain,
          capture_ended_at = now()
      WHERE session_id = :session_id
    COMMIT
```

`finalize_session()` is triggered:

- **Batch mode (`tkos replay <trace.jsonl>`):** automatically after the last line of the rollout has been ingested.
- **Live mode:** explicitly via CLI (`tkos finalize <session_id> <rollout_path>`) or programmatically after a `task_completion` event has been ingested AND the rollout file has not been written to for a configurable inactivity window (default: 60 seconds).

A session that has never been finalized has `raw_rollout_sha256 = NULL`, `total_line_count = NULL`, and `capture_ended_at = NULL`. `tkos verify` against such a session fails check 4 (hash verification) — the session is treated as still-open and not yet verifiable.

### §6.2 Capture completeness checks (v0.2.1 — findings 1 + 2 fix; v0.3.2 — fix C tightens check 3)

A session is **capture-complete** if and only if all five checks pass after the rollout file has been ingested AND `finalize_session()` has been called (per §6.1a):

1. **Line-count completeness.** The count of rows in `raw_lines` for this session equals `session_status.total_line_count`, which equals the count of non-empty lines in the source rollout JSONL.
2. **No Unrecognized lines.** Zero rows in `raw_lines` for this session with `flag=unrecognized`.
3. **Sequence validation (v0.3.2 — fix C tightened).** Within each `turn_idx ≥ 0`, `event_idx` values in the **`events`** table form the sequence `[0, 1, 2, ...]` — no gaps, no duplicates. `event_idx` counts only **mapped** events; ignored-known and unrecognized lines in `raw_lines` do not get an `event_idx` (their `event_idx` is NULL) and do not break the sequence.
4. **Hash verification (both must match):**
   - `raw_rollout_sha256` recomputed from the source file at verify time matches the value stored in `session_status` at ingest time.
   - `line_hash_chain` recomputed by replaying `raw_lines` rows in `source_line_number` order matches the value stored in `session_status` at ingest time.
5. **No rule failures.** No rows in `rule_failures` for this session.

The CLI command `tkos verify <session_id>` runs all five checks and returns pass/fail with the specific failure mode if any fail. A session is `admissibility-eligible=true` only if all five pass.

**Hash chain definition:** `line_hash_chain` is computed iteratively:
```
H_0 = "" (empty)
H_n = sha256(H_{n-1} || raw_line_n_bytes)
```
where `||` is byte concatenation and `raw_line_n_bytes` is the exact byte content of the n-th line (UTF-8, no trailing newline). The final `H_N` (after the last line) is `line_hash_chain`. This chain guarantees that no line was dropped, reordered, mutated, or inserted post-ingest — any single-byte change anywhere in the rollout would propagate to a different final hash.

### §6.3 What admissibility-eligibility means here

In v0.2, `admissibility-eligible=true` means "this session's traces meet all the technical conditions that would be required for v0.4c2 admission, *if* this project were the v0.4c2 substrate project, *which it is not*."

This software-side admissibility check is exercised against the sidecar's own traces during the build, validating that the capture mechanism works. The v0.4c2 substrate project, when it starts, will rely on the same checks against its own traces.

---

## §7 Acceptance tests (nine, locked)

Each test is concrete, runnable, and fails clearly when broken.

1. **Single-event ingest.** POST one valid `tool_call` event; verify it appears in `events` with all §4.2 fields populated; verify the transaction succeeded.
2. **End-to-end demo session.** Replay the sketch §7 demo scenario (18 turns) through `observe()`. Verify the final `active_beliefs` contains exactly the beliefs the demo specifies (post-deploy: `report_ready` active, others retired or confirmed).
3. **Lifecycle transitions.** Replay the same scenario and verify each `belief_events` row matches the expected lifecycle transition per `RULES_SPEC_v0.2.md`.
4. **Out-of-window beliefs survive.** Replay a 50-turn synthetic session in which a `user_approval_pending` belief is minted at turn 5 and not addressed until turn 48. Verify `state(session, turn=48)` returns it.
5. **Replay idempotency.** Run `tkos replay <trace.jsonl>` twice; verify the second run inserts zero new rows. Idempotency is keyed on `source_event_id`.
6. **Streaming/batch belief-event-sequence equivalence (v0.3.1 — fix 7).** Take a real Claude Code session from the v0.1 corpus; run it through the streaming engine with `RULES_SPEC_v0.3.1.md`; run it through the batch engine restricted to the same belief subset and the same spec; verify the **belief-event sequence** matches for the supported belief types — same `(belief_type, claim_template, lifecycle_state, effective_turn, authority)` tuples in the same order. Comparing only final `active_beliefs` is insufficient per RULES_SPEC §5; the engines must agree on *when* each transition happened, not just the end state. Belief types outside the shared subset are excluded from the comparison.
7. **Codex adapter round-trip.** Capture a Codex session in live mode; replay the captured rollout JSONL through batch mode; verify identical resulting state.
8. **Read-path compatibility.** After write-path populates the DB from a Codex session, call the existing read-path's `reconstruct_state` and `build_overlay` against it. Verify both queries return well-formed results with no schema mismatches.
9. **Export determinism (v0.3.1 — fix 7).** Capture a session and run `tkos export <session_id>` twice with no DB changes between runs. The two output files must be byte-identical. Requires **chronological ordering** by `(turn, event_idx, source_line_number)` per §10 Q6 (NOT lexicographic `source_event_id`, which was the v0.2 original — that ordering randomizes events vs the session timeline). No non-deterministic fields in the export.

Tests 5, 6, 8, and 9 are the load-bearing ones. They define what "correct" means.

---

## §8 Data model additions

The read-path's existing tables get additive changes (new columns); the read-path migration is a separate scope (see `TKOS_READ_PATH_MIGRATION_v0.2.md`) because the existing `reconstruct_state` semantics need updating regardless.

### §8.1 `events` schema amendment (v0.3.1 — fix 1: executable SQLite migration)

SQLite's `ALTER TABLE ADD COLUMN` cannot add a column that is simultaneously `NOT NULL` and `UNIQUE`, and column-dependent DEFAULTs (referring to another column) are not valid. The v0.3.1 migration sequence:

**Step A — Add columns as nullable.** SQLite allows this without restriction.

```sql
ALTER TABLE events ADD COLUMN source_event_id TEXT;
ALTER TABLE events ADD COLUMN event_idx INTEGER;
ALTER TABLE events ADD COLUMN source_rollout_path TEXT;
ALTER TABLE events ADD COLUMN source_line_number INTEGER;
ALTER TABLE events ADD COLUMN call_id TEXT;
```

Note: the existing column is named `turn` (per `tkos.py` DDL). v0.3.1 keeps the column name `turn` and treats it as the storage label for the conceptual `turn_idx`. References in the spec to `turn_idx` mean `events.turn` at the SQL level. The internal integer PK `event_id` is unchanged.

**Step B — Backfill in application code.** For each existing row:

```sql
-- Pseudo-SQL; actual migration runs in Python with computed values
UPDATE events
SET source_event_id = :computed_source_event_id,
    event_idx = 0,
    source_rollout_path = NULL,
    source_line_number = NULL,
    call_id = NULL
WHERE event_id = :event_id;
```

Where `:computed_source_event_id` is `sha256("fixture:" + session_id + ":" + str(turn) + ":0")` for fixtured rows. After this step, every row has a non-null `source_event_id` and `event_idx = 0`.

**Step C — Create the unique index after backfill.** Now safe because every row has a non-null value.

```sql
CREATE UNIQUE INDEX idx_events_source_event_id ON events(source_event_id);
CREATE INDEX idx_events_session_turn_event ON events(session_id, turn, event_idx);
```

**Step D — Enforce non-null in app code.** SQLite cannot enforce `NOT NULL` on an existing nullable column without rebuilding the table. v0.3.1 enforces non-null at the application layer: every `ingest_source_line()` (per §6.1) writes a non-null `source_event_id` and `event_idx`. A startup integrity check verifies no rows have null in either column.

(For a clean implementation that prefers DDL-level enforcement, table rebuild is available: `CREATE TABLE events_new (...) AS SELECT ... FROM events; DROP TABLE events; ALTER TABLE events_new RENAME TO events`. This is acceptable but not required. The app-code enforcement is the v0.3.1 default.)

**Foreign keys.** Internal references (e.g., `belief_events.event_id → events.event_id`) stay on the integer PK; substrate-level identity for spec conformance is `source_event_id`.

### §8.1a `raw_lines` (new — finding 1 fix)

Every line of every ingested rollout JSONL is persisted here regardless of category. This is what the line-count and hash-chain checks in §6.2 verify against.

| Column | Type | Notes |
|---|---|---|
| raw_line_id | INTEGER PRIMARY KEY | autoincrement |
| session_id | TEXT NOT NULL | |
| source_line_number | INTEGER NOT NULL | 1-indexed line in the rollout |
| raw_line_bytes | BLOB NOT NULL | the exact bytes of the JSONL line |
| raw_line_sha256 | TEXT NOT NULL | precomputed hash for chain verification |
| category | TEXT NOT NULL | `mapped` / `ignored-known` / `unrecognized` |
| flag | TEXT | reason for `unrecognized` if applicable |
| event_id | INTEGER | foreign key to `events.event_id` if `category=mapped`; null otherwise |
| turn_idx | INTEGER NOT NULL | -1 for lines with no associated turn_id |

UNIQUE constraint on `(session_id, source_line_number)`.

### §8.2 `belief_events` schema amendment

Add `effective_turn INTEGER` (nullable, defaults to `at_turn`). The existing `at_turn` field is renamed semantically to `observed_at_turn` (column name unchanged for compatibility). For non-retro rules, `effective_turn = observed_at_turn` is enforced at write time.

### §8.3 `session_status` (new — v0.2.1 finding 2 fix; v0.3.2 — fix B clarifies timing)

| Column | Type | Notes |
|---|---|---|
| session_id | TEXT PRIMARY KEY | |
| source_rollout_path | TEXT NOT NULL | the path Codex wrote, for audit only — not in any hash |
| raw_rollout_sha256 | TEXT | **nullable until `finalize_session()` runs (v0.3.2)**; sha256 of the source file's complete bytes |
| line_hash_chain | TEXT | updated incrementally during ingestion; finalized at `finalize_session()` |
| total_line_count | INTEGER | **nullable until `finalize_session()` runs (v0.3.2)** |
| capture_started_at | TEXT NOT NULL | ISO 8601 |
| capture_ended_at | TEXT | nullable until `finalize_session()` runs |
| capture_started_at_turn | INTEGER NOT NULL | must be 0 for admissibility-eligible |
| admissibility_eligible | INTEGER NOT NULL DEFAULT 1 | flipped to 0 by any §6.2 failure |
| failure_reasons | TEXT | JSON list of reasons if admissibility_eligible = 0 |

A session row is inserted into `session_status` on first `ingest_source_line()` call for that session_id, with the three nullable columns above set to NULL. `finalize_session()` populates them.

### §8.4 `rule_failures` (new)

Append-only audit of rule-engine exceptions. Outside the atomic transaction so it survives rollbacks.

| Column | Type | Notes |
|---|---|---|
| failure_id | INTEGER PRIMARY KEY | |
| session_id | TEXT NOT NULL | |
| source_event_id | TEXT NOT NULL | the event being processed when the rule failed |
| rule_name | TEXT NOT NULL | |
| exception_class | TEXT NOT NULL | |
| exception_message | TEXT | |
| logged_at | TEXT NOT NULL | ISO 8601 |

### §8.5 `ingest_log` (new, retained from v0.1.1)

Append-only audit of every `observe()` call.

| Column | Type | Notes |
|---|---|---|
| ingest_id | INTEGER PRIMARY KEY | |
| source_event_id | TEXT NOT NULL | |
| session_id | TEXT NOT NULL | |
| received_at | TEXT NOT NULL | |
| rules_fired | TEXT | JSON list of rule names |
| transaction_status | TEXT NOT NULL | `committed` / `rolled_back` |

---

## §9 Build plan

Each step's traces remain non-admissible for v0.4c2 (the sidecar build is software-only per §1.2).

1. **Bootstrap.** Create the new files; lock `RULES_SPEC_v0.2.md`; add `session_status`, `rule_failures`, `ingest_log` tables to DDL; backfill `source_event_id` for existing fixtures.
2. **Trace capture, no rules.** Implement the HTTP endpoint with §4.3 schema validation and §6.1 atomicity. Get `tkos serve` and `tkos replay` working. Wire the Codex trace adapter (§3 hash-based identity; §4.4 turn-boundary rule). Pass acceptance test 1.
3. **Capture-completeness checks.** Implement `tkos verify` and `finalize_session()`. Pass §6.2's five checks against a known-good captured session.
4. **First rule pair.** Implement `validation_pending` mint from `tool_call` and `validation_complete` mint from `tool_result`. Pass tests 2 and 3 for these two belief types.
5. **Remaining rules.** Implement the rest of §5.2's belief subset. Pass tests 2 and 3 fully.
6. **Long-session correctness.** Pass test 4.
7. **Idempotency.** Pass test 5.
8. **Streaming/batch equivalence over the shared subset.** Pass test 6. Hardest test; expect iteration. This is what validates `RULES_SPEC_v0.2.md`.
9. **Codex adapter polish + read-path compatibility.** Pass tests 7 and 8.
10. **Export.** Implement `tkos export` with stable ordering. Pass test 9.
11. **Software ships.** Verify `tkos verify` passes against multiple captured Codex sessions of varying lengths. Document the verified-working state.
12. **(Separate project) v0.4c2 substrate begins.** A fresh Codex project starts; trace capture is wired from session 1; the v0.4c2 admission criteria apply to that fresh project. This is not part of v0.2 of the sidecar.

---

## §10 Invariants

These hold across v0.2 and constrain refactors:

- **Read-path is read-only of the write-path's output.** No reach-back.
- **Every belief lifecycle transition has a `belief_events` row.** No silent state mutations.
- **`source_event_id` is unique.** Two rows with the same hash represent the same source event.
- **Atomicity.** Event persistence + rule effects commit or roll back together.
- **Streaming-equals-batch over the shared subset.** Acceptance test 6.
- **Capture completeness is binary.** A session passes all five §6.2 checks or it doesn't. No partial admissibility.
- **Software-only.** The sidecar's own captured traces are not the v0.4c2 substrate.

---

## §11 Failure modes (what should never happen silently)

- A rollout line doesn't match any §4.1 event type → log, drop, mark session `admissibility-eligible=false`. Do not invent a mapping.
- A rule throws an exception on an event → roll back the transaction, log to `rule_failures`, return 500, mark session `admissibility-eligible=false`.
- The DB schema diverges from what the read-path expects → fail loudly on startup.
- Two sessions interleaved on the same HTTP endpoint → supported (sessions are id-scoped) but log if interleaving rate exceeds a configurable threshold.
- A `source_event_id` collision (same hash, different content) → in practice impossible with sha256, but on detection: hard fail.
- A capture-completeness check fails → the session is admissibility-eligible=false and a `tkos verify` report explains why.

---

## §12 Locked decisions (carried from v0.1.1, refined)

- **Q1. HTTP framing:** one event per POST. Unchanged.
- **Q2. Codex transcript location:** `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`. Resolved.
- **Q3. Long-running tool detection:** K=3 unmatched-result rule, with `effective_turn` = original `tool_call` turn, `observed_at_turn` = retro-mint turn. Refined per §5.4.
- **Q4. Failure signature:** simple `exit code + first stderr line` matcher.
- **Q5. Multi-process safety:** SQLite WAL + startup lock file.
- **Q6. Export format (v0.2.1 — finding 9 fix):** JSONL per session, one line per event, sorted by `(turn_idx, event_idx, source_line_number)`. Each line carries the event record (§4.2) plus the `active_beliefs` snapshot computed up-to-and-including that event. The order matches the session timeline, making the snapshot semantically meaningful. Stable ordering (deterministic sort key) and deterministic content per acceptance test 9. Hash-based ordering (the v0.2 original) was rejected because it randomized event order vs the session timeline, making the snapshot misleading.

---

## §13 What this scope does NOT commit to

- The v0.4c2 pre-registration (written after the substrate exists).
- LLM-driven belief extraction (separate research direction).
- IDE integration beyond Codex (out of scope).
- Live integration with Claude Code (the Claude Code corpus is fixtured; the streaming engine can ingest a Claude Code rollout via a separate adapter, but that adapter is not in v0.2).
- `failure_signature_active` belief type (deferred).
- Production-grade hosting (single-user, local-process only).

---

## §14 Deliverables at v0.2 close

When all nine acceptance tests pass and the build plan steps 1–11 complete:

- A running `tkos serve` ingesting Codex events.
- A working `tkos replay` re-processing saved traces idempotently.
- A working `tkos verify` checking capture completeness.
- A working `tkos export` producing byte-identical artifacts.
- Existing read-path queries return correct results against write-path-populated DB.
- `RULES_SPEC_v0.2.md` locked and verified against the v0.1 batch engine over the shared subset.
- A verified-working trace-capture mechanism, ready for a separate v0.4c2 substrate project to begin against.

Expected timeline: 3–4 weeks of focused Codex-assisted work for a competent Python developer.

---

*This scope is implementation-ready. The decoupling from v0.4c2 substrate work, the `source_event_id` identity primitive, the locked event schemas before rules, the narrowed equivalence test, the atomicity invariant, and the capture-completeness checks each came from a build-time audit (Codex review of v0.1.1, 2026-06-05) that found contradictions before code flowed. The audit doing its job is what makes this version safer to build against.*
