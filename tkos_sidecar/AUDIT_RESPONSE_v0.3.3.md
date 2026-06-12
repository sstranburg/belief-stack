# Audit Response v0.3.3 — Changelog & Readiness Checklist

**Date:** 2026-06-06
**Status:** LOCKED. Patches v0.3.2 → v0.3.3 (scope + read-path) and RULES_SPEC v0.3.1 → v0.3.2. Scope: patches only.

**Predecessor audit responses:**
- [`AUDIT_RESPONSE_2026-06-06.md`](./AUDIT_RESPONSE_2026-06-06.md) — first audit
- [`AUDIT_RESPONSE_v0.3.1.md`](./AUDIT_RESPONSE_v0.3.1.md) — second audit
- [`AUDIT_RESPONSE_v0.3.2.md`](./AUDIT_RESPONSE_v0.3.2.md) — third audit

Fourth audit cycle. Found 6 issues after the v0.3.2 lock: 4 high (all protocol-level blockers) + 2 medium. All addressed in this revision cycle.

---

## Changelog (brief)

| Fix | Severity | What changed | Where | Doc version |
|---|---|---|---|---|
| I | High | Finalization is now **explicit-only in live mode**. The v0.3.2 "task_completion + 60s inactivity" auto-finalize trigger was unsafe: Codex rollouts can contain multiple task cycles. `ingest_source_line()` raises `SessionAlreadyFinalizedError` if called after `finalize_session()`. Batch mode still auto-finalizes at end-of-file. | TKOS scope §6.1a | TKOS_WRITE_PATH_SCOPE_v0.3.3 |
| II | High | HTTP endpoint payload locked: **one raw rollout JSONL line per POST**, not a parsed event. §1.3 + §10 Q1 + §7 acceptance test 1 updated to match. The server parses + dispatches via `ingest_source_line()`. | TKOS scope §1.3, §7, §10 | TKOS_WRITE_PATH_SCOPE_v0.3.3 |
| III | High | `line_hash_chain` update is now inside the same atomic transaction as the `raw_lines` insert (step 1a of `ingest_source_line()`). Replay no-ops do NOT extend the chain. Mismatched-hash mutations raise before any chain update. | TKOS scope §6.1 | TKOS_WRITE_PATH_SCOPE_v0.3.3 |
| IV | High | `pipeline_running_born_retroactive` dispatch path concretized: triggered by `ingest_source_line()` when a mapped event arrives whose `turn_idx` is strictly greater than the prior max for the session (turn-boundary advance). Scan runs in same transaction, before the event's own rules. SQL example included. | RULES_SPEC §3.4 | RULES_SPEC_v0.3.2 |
| V | Medium | `report_ready` born trigger moved from `tool_call` to `tool_result` with `exit_code = 0` AND the parent `tool_call`'s paths match `REPORT_PATH_PATTERNS`. Authority upgraded to `confirmed_by_tool`. Prevents minting on failed `apply_patch`. | RULES_SPEC §3.7 | RULES_SPEC_v0.3.2 |
| VI | Medium | Synthetic `action_blocked` IS counted in `len(reconstruct_state(...))` results. Consumers wanting persisted-only counts filter via `is_synthetic`. Overlay budget accounting also includes synthetic. | read-path migration §1.4 | TKOS_READ_PATH_MIGRATION_v0.3.3 |

---

## Files in this revision cycle

**New v0.3.3 / v0.3.2 files:**

| File | Supersedes | Fixes carried |
|---|---|---|
| `TKOS_WRITE_PATH_SCOPE_v0.3.3.md` | v0.3.2 | I, II, III |
| `RULES_SPEC_v0.3.2.md` | v0.3.1 | IV, V |
| `TKOS_READ_PATH_MIGRATION_v0.3.3.md` | v0.3.2 | VI |
| `AUDIT_RESPONSE_v0.3.3.md` (this file) | — | meta |

**Unchanged this cycle:** `INTEGRATION_PATTERN_v0.1.3.md`.

---

## Implementation-readiness checklist (fourth pass)

- [x] **Finalization timing safe.** Explicit-only in live mode; auto at batch-replay EOF. `SessionAlreadyFinalizedError` raised on any post-finalize ingest. Multi-task Codex sessions cannot self-finalize prematurely.
- [x] **HTTP contract locked.** One raw rollout JSONL line per POST throughout the scope (§1.3, §7 test 1, §10 Q1, and the §6.1 pseudocode all aligned).
- [x] **Hash chain in atomic sequence.** `line_hash_chain` updated in same transaction as `raw_lines` insert; replay no-ops skip the update (chain already includes the line from original ingest); mismatch raises `SourceMutationError` before any chain change.
- [x] **`pipeline_running` dispatch executable.** Triggered by turn-boundary advance during `ingest_source_line()`. SQL query specified. Scan + event rules + hash-chain update + raw_lines write all commit atomically.
- [x] **`report_ready` requires successful write.** Trigger moved to `tool_result(exit_code=0)`; failed writes do not produce the belief; authority is `confirmed_by_tool`.
- [x] **Synthetic count semantics specified.** `action_blocked` is counted in `len(reconstruct_state())` and in overlay budget accounting; `is_synthetic` flag available for consumers that want persisted-only views.

All six boxes checked.

---

## What remains explicitly OPEN (not blocking code)

Unchanged from prior audit responses:

- Performance characteristics (latency targets, write throughput, benchmarks) — v0.4b / v0.5.
- Codex per-action `risk()` filtering — v0.3 (read-path) follow-on work.
- Failure-signature richness beyond `exit_code + stderr_first_line` — v0.3 candidate.

---

## What remains explicitly OUT of scope

Unchanged. TKOS sidecar v0.3.3 build is software-only. Its traces are NOT the v0.4c2 substrate.

---

*Fourth audit cycle. Issue trajectory: 11 (conceptual) → 7 (executable contract) → 6 (protocol completion) → 6 (protocol-edge cases: multi-task finalization, endpoint payload form, atomic hash-chain timing, retroactive rule dispatch path, real-failure handling, count semantics). Convergence pattern intact: each cycle has produced lighter, more localized findings against an underlying stack that is otherwise sound. Code can now begin against the v0.3.3 stack.*
