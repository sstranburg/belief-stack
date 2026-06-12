# Audit Response v0.3.2 — Changelog & Readiness Checklist

**Date:** 2026-06-06
**Status:** LOCKED. Patches v0.3.1 → v0.3.2 (with INTEGRATION_PATTERN at v0.1.3). Scope: patches only.
**Predecessor audit responses:**
- [`AUDIT_RESPONSE_2026-06-06.md`](./AUDIT_RESPONSE_2026-06-06.md) — first audit (v0.2 → v0.2.1)
- [`AUDIT_RESPONSE_v0.3.1.md`](./AUDIT_RESPONSE_v0.3.1.md) — second audit (v0.2.1 → v0.3.1)

Third audit cycle. Found 6 issues after the v0.3.1 lock: 1 critical, 3 high, 1 medium, 1 low. All addressed in this revision cycle.

---

## Changelog (brief)

| Fix | Severity | What changed | Where | Doc version |
|---|---|---|---|---|
| A | Critical | `ingest_source_line()` now checks for an existing `raw_lines` row before INSERT. Hash match → no-op (idempotent replay); hash mismatch → `SourceMutationError`. | TKOS scope §6.1 | TKOS_WRITE_PATH_SCOPE_v0.3.2 |
| B | High | New `finalize_session(session_id, rollout_path)` operation: computes `raw_rollout_sha256` over the source file's full bytes, sets `total_line_count` and `capture_ended_at`. Triggered after batch-replay end or live-mode finalization. `session_status` hash columns nullable until finalize runs. | TKOS scope §6.1a + §8.3 | TKOS_WRITE_PATH_SCOPE_v0.3.2 |
| C | High | `event_idx` counts **mapped events only**. Ignored-known and unrecognized lines have `event_idx=NULL` in `raw_lines` and are not consumed in the per-turn sequence. Without this, real-session sequence validation fails wherever ignored-known lines interleave. | TKOS scope §4.4 + §6.2 | TKOS_WRITE_PATH_SCOPE_v0.3.2 |
| 4 | High | Synthetic `action_blocked` `belief_id` is now a deterministic string (`synthetic:action_blocked:{session_id}:{query_turn}`), not `None`. Prevents `TypeError` on `None` vs `str` in overlay sort tie-breaking. | read-path migration §1.4 | TKOS_READ_PATH_MIGRATION_v0.3.2 |
| 5 | Medium | Codex `apply_patch` Move grammar corrected. Regex now recognizes `*** Move to: <path>` as a separate header line; the source path is collected from the preceding `*** Update File:`. v0.1.2's `*** Move File: from -> to` assumption was incorrect. | integration §3.5 | INTEGRATION_PATTERN_v0.1.3 |
| D | Low | Two stale "four checks" references in TKOS scope §9 step 3 and §10 invariants updated to "five". | TKOS scope §9, §10 | TKOS_WRITE_PATH_SCOPE_v0.3.2 |

---

## Files in this revision cycle

**New v0.3.2 files (this audit response):**

| File | Supersedes | Fixes carried |
|---|---|---|
| `TKOS_WRITE_PATH_SCOPE_v0.3.2.md` | v0.3.1 | A, B, C, D |
| `TKOS_READ_PATH_MIGRATION_v0.3.2.md` | v0.3.1 | 4 |
| `INTEGRATION_PATTERN_v0.1.3.md` | v0.1.2 | 5 |
| `AUDIT_RESPONSE_v0.3.2.md` (this file) | — | meta |

**Unchanged this cycle:**

- `RULES_SPEC_v0.3.1.md` — no rule-level changes in this cycle; remains the canonical RULES_SPEC.

---

## Final implementation-readiness checklist (third pass)

- [x] **Replay-safe `ingest_source_line()`.** Existing `raw_lines` row + matching hash → no-op. Mismatched hash → `SourceMutationError`. Acceptance test 5 (replay idempotency) can pass.
- [x] **Session finalization defined.** `finalize_session()` computes the full-file hash, sets `total_line_count`, and stamps `capture_ended_at`. Without it, `tkos verify` fails check 4; with it, hash verification is concrete and runnable.
- [x] **`event_idx` counts mapped events only.** Ignored-known lines have `event_idx=NULL`. Sequence validation (§6.2 check 3) passes on real sessions with interleaved ignored-known lines.
- [x] **Synthetic `action_blocked` sort-safe.** Deterministic string `belief_id`; no `None` in sort keys.
- [x] **`apply_patch` Move parsing matches Codex grammar.** `*** Move to:` correctly captured.
- [x] **No stale "four" references** in the canonical scope's completeness language.

All six boxes checked.

---

## What remains explicitly OPEN (not blocking code)

Unchanged from `AUDIT_RESPONSE_v0.3.1.md`:

- Performance characteristics (latency targets, write throughput, benchmarks) — v0.4b / v0.5.
- Codex per-action `risk()` filtering — v0.3 (read-path) follow-on work.
- Failure-signature richness beyond `exit_code + stderr_first_line` — v0.3 candidate.

---

## What remains explicitly OUT of scope

Unchanged from prior audit responses. The TKOS sidecar v0.3.2 build is **software-only**. Its captured traces are NOT the v0.4c2 substrate. A separate fresh Codex project starts the v0.4c2 substrate work once trace capture is verified end-to-end against the v0.3.2 spec.

---

*Third cycle of the discipline. First found conceptual issues; second found executable-contract issues; third found protocol-completion issues (idempotency on replay, session-end finalization, mapped-event sequence integrity, sort-key type stability, real patch grammar). Each cycle has been tighter and more targeted. Code can now begin against the v0.3.2 stack.*
