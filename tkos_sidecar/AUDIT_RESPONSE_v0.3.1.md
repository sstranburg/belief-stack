# Audit Response v0.3.1 — Changelog & Readiness Checklist

**Date:** 2026-06-06
**Status:** LOCKED. Patches v0.2.1 → v0.3.1 across the TKOS write-path spec stack. Scope: patches only; no scope broadening.
**Predecessor audit responses:** [`AUDIT_RESPONSE_2026-06-06.md`](./AUDIT_RESPONSE_2026-06-06.md) (first audit, v0.2 → v0.2.1).

This document is the second audit-response cycle. The first audit resolved 11 conceptual findings; this second audit resolved 7 executable-contract-level findings.

---

## Changelog (brief)

| Fix | What changed | Where | Doc version |
|---|---|---|---|
| 1 | SQLite migration sequence rewritten: add nullable → backfill → unique index → enforce non-null in app code. `turn` column name preserved at SQL level (referenced as `turn_idx` conceptually). | TKOS scope §8.1; read-path migration §1.2 | TKOS_WRITE_PATH_SCOPE_v0.3.1 + TKOS_READ_PATH_MIGRATION_v0.3.1 |
| 2 | Codex ignored-known taxonomy expanded: `response_item(payload.type=message, role=user)` and `role=developer` added as duplicates/context. | TKOS scope §4.1 ignored-known set | TKOS_WRITE_PATH_SCOPE_v0.3.1 |
| 3 | Atomicity invariant replaced with single `ingest_source_line(raw_line)` operation. Single transaction: persists `raw_lines`, classifies, optionally normalizes event + runs rules. Eliminates the "who writes raw_lines and when" ambiguity. | TKOS scope §6.1 | TKOS_WRITE_PATH_SCOPE_v0.3.1 |
| 4 | K=3 retro-mint locked to subsequent **turns**, not events. Eliminates false-firing on Codex parallel tool dispatch. | RULES_SPEC §3.4 | RULES_SPEC_v0.3.1 |
| 5 | Codex `apply_patch` paths extracted from patch headers (`*** Add/Update/Delete/Move File:`). `tool_result` explicitly inherits `tool_name` and `command` from parent `tool_call`. | INTEGRATION_PATTERN §3.5 | INTEGRATION_PATTERN_v0.1.2 |
| 6 | Synthetic `action_blocked` record carries full field shape compatibility (`state`, `warrant_turns`, `last_updated_turn`, `created_turn`, `authority`); authority comparison uses explicit `AUTH_RANK`, not lexicographic max. | read-path migration §1.4 | TKOS_READ_PATH_MIGRATION_v0.3.1 |
| 7 | Acceptance test 6 uses belief-event-sequence equivalence (not final `active_beliefs`); test 9 uses chronological ordering (not lexicographic `source_event_id`); completeness check count normalized to five. | TKOS scope §7 | TKOS_WRITE_PATH_SCOPE_v0.3.1 |

---

## Files in this revision cycle

**New v0.3.1 files (this audit response):**

| File | Supersedes | Fixes carried |
|---|---|---|
| `TKOS_WRITE_PATH_SCOPE_v0.3.1.md` | v0.2.1 | 1, 2, 3, 7 |
| `RULES_SPEC_v0.3.1.md` | v0.2.1 | 4 |
| `TKOS_READ_PATH_MIGRATION_v0.3.1.md` | v0.2 | 1 (read-path aspect), 6 |
| `INTEGRATION_PATTERN_v0.1.2.md` | v0.1.1 | 5 |
| `AUDIT_RESPONSE_v0.3.1.md` (this file) | — | meta |

**Older versions retained as audit-trail artifacts (do not implement against):**

- `TKOS_WRITE_PATH_SCOPE_v0.1.md` (SUPERSEDED marker added)
- `TKOS_WRITE_PATH_SCOPE_v0.2.md` (carries v0.2.1 amendment log inline)
- `RULES_SPEC_v0.2.md` (carries v0.2.1 amendment log inline)
- `TKOS_READ_PATH_MIGRATION_v0.2.md` (the v0.2 first draft)
- `INTEGRATION_PATTERN_v0.1.md` (carries v0.1.1 amendment log inline)

---

## Final implementation-readiness checklist

Each item below is a precondition for code to begin. All seven boxes must be checked.

- [x] **Executable SQLite migrations.** Every ALTER TABLE, CREATE INDEX, and backfill step in scope §8.1 and read-path migration §1.2 is valid SQLite that runs against the existing `tkos.py` schema. App-layer non-null enforcement documented.
- [x] **Complete Codex line taxonomy.** Every line type that appears in real Codex rollouts (`session_meta`, `turn_context`, `event_msg` subtypes, `response_item` subtypes including `role=user` and `role=developer` messages) is classified as Mapped or Ignored-known. Capture completeness checks pass on real sessions.
- [x] **Atomic ingestion protocol.** `ingest_source_line(raw_line)` is the single entry point; its transactional sequence covers `raw_lines` write, classification, event creation (when mapped), rule firing, and `ingest_log` write. No "who writes raw_lines and when" ambiguity.
- [x] **K=3 unit is turns.** `pipeline_running` retro-mint fires only after three subsequent *turns* with no matching `tool_result`. Codex parallel tool dispatch within a turn does not trigger false fires.
- [x] **Codex path enrichment.** `exec_command` paths extracted via shell-command parsing. `apply_patch` paths extracted via patch-header regex on `*** Add/Update/Delete/Move File:`. `tool_result` inherits `tool_name` and `command` from parent `tool_call`.
- [x] **`action_blocked` shape compatibility.** Synthetic record carries every field the existing `tkos.py` renderer reads. Authority comparison uses `AUTH_RANK` explicitly.
- [x] **Acceptance tests correctly specified.** Test 6 compares belief-event sequences (not just final `active_beliefs`); test 9 sorts chronologically; capture completeness count is five throughout the spec.

All boxes checked.

---

## What remains explicitly OPEN (not blocking code)

- **Performance characteristics.** v0.3.1 does not specify query latency targets, write throughput, or any benchmark. v0.4b will measure end-to-end runtime economics on the substrate; v0.5 may add performance tuning.
- **Codex per-action `risk()` filtering.** Per-action blocker filtering is named in read-path migration §1.4 as "v0.3 work." v0.3.1 default: all blockers are relevant to all actions.
- **Failure signature beyond `exit_code + stderr_first_line`.** v0.3 candidate; deferred from v0.2.

---

## What remains explicitly OUT of scope (this entire program)

Per `project_v04c2_substrate_separation.md` (locked Option A): the TKOS sidecar v0.3.1 build is **software-only**. Its captured traces are NOT the v0.4c2 substrate. A separate fresh Codex project starts the v0.4c2 substrate work after this software's trace capture is verified to work end-to-end against the v0.3.1 spec.

---

*The discipline did its job for the second time. The first audit caught 11 conceptual issues; this second audit caught 7 executable-contract issues that were invisible at the conceptual level. Every finding was addressable in a focused patch; no scope broadening was required. Code can now begin against the v0.3.1 stack.*
