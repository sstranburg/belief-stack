# Audit Response — 2026-06-06

**Status:** LOCKED resolutions to a pre-implementation audit of v0.2 of the TKOS write-path scope, RULES_SPEC v0.2, and INTEGRATION_PATTERN v0.1.
**Audit date:** 2026-06-06 (Codex review).
**Resolution date:** 2026-06-06.

This document is the amendment log. It enumerates every audit finding, the locked resolution, and which artifact carries the change. Per the build-time-audit discipline, surfaced contradictions become explicit re-versions, not silent fixes.

**Outputs of this resolution cycle:**
- `TKOS_WRITE_PATH_SCOPE_v0.2.md` → v0.2.1 (six finding fixes)
- `RULES_SPEC_v0.2.md` → v0.2.1 (four finding fixes)
- `INTEGRATION_PATTERN_v0.1.md` → v0.1.1 (one finding fix)
- New: `TKOS_READ_PATH_MIGRATION_v0.2.md` — separate scope for the read-path code changes that the audit revealed are necessary (issue 3).

---

## Critical findings (four)

### Finding 1: Real Codex sessions fail capture completeness

**Issue:** TKOS scope's taxonomy declares any unmatched rollout line disqualifying. Actual rollouts contain `session_meta`, `turn_context`, `token_count`, and other lines that aren't events in our model. Every session would fail.

**Resolution.** Introduce three categories for rollout lines:

| Category | Definition | Persistence | Counts toward completeness? |
|---|---|---|---|
| **Mapped** | Translates to a §4.1 event_type per the adapter normalization rules | `events` table | Yes |
| **Ignored-known** | Type is explicitly recognized as non-event (e.g., session_meta, turn_context, token_count, duplicate agent_message) | New `raw_lines` table | Yes |
| **Unrecognized** | Type is not in either category | New `raw_lines` table with `flag=unrecognized` | Yes; flips admissibility to false |

Every raw line in the rollout JSONL is persisted to `raw_lines` regardless of category. Capture completeness requires:

- Every line was persisted to `raw_lines` (count match).
- No line has `flag=unrecognized`.
- Mapped lines also appear in `events` table with consistent `(source_event_id, source_line_number)`.

The v0.2 ignored-known set (locked):

```
session_meta
turn_context
event_msg(type=token_count)
event_msg(type=agent_message)   # duplicate of response_item(type=message)
```

Applied to: **TKOS scope §4.1, §6.2 (capture completeness), §8 (new raw_lines table)**.

### Finding 2: Transcript hash cannot work as specified

**Issue:** v0.2 §6.2 compares the raw rollout file's SHA256 against a reconstruction from normalized persisted events. Normalization drops `ignored-known` lines and transforms `mapped` lines, so the bytes cannot match.

**Resolution.** Store two distinct hashes; verification checks both:

- `raw_rollout_sha256` — SHA256 of the original rollout JSONL file bytes. Captured at ingest time; recomputed at verify time directly from the source file.
- `line_hash_chain` — a deterministic chain `H_n = sha256(H_{n-1} ‖ raw_line_n_bytes)`, computed over every raw line (mapped, ignored-known, and unrecognized) in source-line order. Captured at ingest by hashing each line as it arrives; recomputed at verify time by replaying the persisted `raw_lines` table in `source_line_number` order.

Both must match between ingest and verify. The chain check guarantees no line was dropped, reordered, mutated, or inserted post-ingest.

Applied to: **TKOS scope §6.2, §8 (new session_status columns)**.

### Finding 3: Read-path is NOT unchanged

**Issue:** TKOS scope claims the read-path is unchanged and supports `effective_turn`. The existing `tkos.py` `reconstruct_state()` filters by `at_turn` only, and maps `weakened` to `contradicted` (excluding it from active state). RULES_SPEC §4 / §8 expect `weakened` to remain active.

**Resolution.** Scope a separate read-path migration explicitly. Create `TKOS_READ_PATH_MIGRATION_v0.2.md` covering:

- Add `effective_turn` to `belief_events` schema.
- Update `reconstruct_state(session, turn=Q)` to filter by `effective_turn <= Q`, not `at_turn <= Q`.
- Update lifecycle filtering: `weakened` remains active (per RULES_SPEC §4.2 / §8); `contradicted` and `retired` exclude.
- Render computed `action_blocked` synthetically at query time (per finding 10).
- Add migration tests to `test_tkos.py` covering retro-minted belief retrieval, weakened belief inclusion, and action_blocked synthesis.

The read-path migration is a code change to `tkos.py`, not a spec amendment. The new doc captures the migration as a discrete work item that ships alongside (or just before) the write-path build's step 5 of §9.

Applied to: **TKOS scope §2 (acknowledge read-path migration as separate work item), new TKOS_READ_PATH_MIGRATION_v0.2.md**.

### Finding 4: SQLite schema amendment is not directly valid

**Issue:** Existing `events` table has `event_id INTEGER PRIMARY KEY`. SQLite cannot ALTER TABLE to swap primary keys. Foreign keys reference integer `event_id`.

**Resolution.** Preserve internal integer identity; add external string identity as UNIQUE.

```sql
ALTER TABLE events ADD COLUMN source_event_id TEXT NOT NULL UNIQUE;
ALTER TABLE events ADD COLUMN event_idx INTEGER NOT NULL DEFAULT 0;
ALTER TABLE events ADD COLUMN source_rollout_path TEXT;
ALTER TABLE events ADD COLUMN source_line_number INTEGER;
ALTER TABLE events ADD COLUMN call_id TEXT;
CREATE INDEX idx_events_source_event_id ON events(source_event_id);
CREATE INDEX idx_events_session_turn_event ON events(session_id, turn_idx, event_idx);
```

The internal integer `event_id` remains the storage-level primary key. The substrate-level identity (and the equivalence-test identity per RULES_SPEC §5) is `source_event_id`. Foreign keys can stay on `event_id` for storage efficiency, or migrate to `source_event_id` per implementation choice.

Backfill: existing fixtured rows get `source_event_id = sha256("fixture:" + session_id + ":" + turn + ":0")` and `event_idx = 0`.

Applied to: **TKOS scope §8.1 (events schema amendment), §6.0 (renamed and clarified)**.

---

## High findings (five)

### Finding 5: Codex source mapping does not match real rollout records

**Issue:** RULES_SPEC §1 expects `tool_name`, `command`, `exit_code`, `paths` as direct fields. Codex provides `function_call` (with name = wrapper like "exec_command" + arguments JSON) and `function_call_output` (with output as embedded human-readable text containing the exit code).

**Resolution.** Specify adapter normalization rules explicitly in INTEGRATION_PATTERN v0.1.1 §3.5 (new "Adapter normalization rules — Codex"). The locked v0.2 mapping:

**Codex → mapped event types:**

| Codex source | event_type | Field derivation |
|---|---|---|
| `response_item(type=function_call)` where `name == "exec_command"` | `tool_call` | `tool_name` = `arguments.cmd.split()[0]` (the first shell token); `command` = `arguments.cmd`; `paths` = parse from `arguments.cmd` (heuristic — see below) |
| `response_item(type=function_call)` where `name != "exec_command"` | `tool_call` | `tool_name` = `name`; `command` = empty; `paths` = parse from `arguments.path`/`arguments.paths`/`arguments.file_path` if present |
| `response_item(type=function_call_output)` | `tool_result` | `parent_event_id` = source_event_id of the function_call with matching `call_id`; `exit_code` = parse from output (regex: `Process exited with code (\d+)` or treat absence as 0); `stderr_first_line` = parse from output (heuristic: first line after "Error:" or stderr-flagged section); `paths` = unchanged from parent tool_call; `output` = the raw output text |
| `response_item(type=message)` where `role == "assistant"` | `assistant_message` | `content` = the message content |
| `response_item(type=reasoning)` | `assistant_reasoning` | `content` = `summary` field (or `encrypted_content` decrypted if available) |
| `event_msg(type=user_message)` | `user_message` | `content` = `message` field |
| `event_msg(type=task_started)` | `task_start` | `task_name` = derived from `turn_id` and `started_at` |
| `event_msg(type=task_complete)` | `task_completion` | `final_status` = "ok" if `last_agent_message` present, else "incomplete" |

**Path extraction from shell commands (heuristic, v0.2):**

- Match flag-arguments to known file-touching commands: `nl`, `cat`, `head`, `tail`, `less`, `grep` (read); `cp`, `mv`, `rm`, `ln`, `chmod`, `chown`, `touch`, `mkdir`, `rmdir` (write); `git`, `sed -i`, `awk -i inplace` (modify).
- Extract path-shaped tokens (containing `/` or starting with `.`) from the command after the tool name.
- Filter out tokens that look like flags (`--foo`, `-f`).
- Return the list; empty if no path-shaped tokens found.

This is intentionally crude for v0.2. Path extraction precision is not load-bearing for the v0.2 acceptance tests; it becomes load-bearing only if rules predicates depend on path overlap, which only `fix_attempted` (§3.1), `validation_complete` (§3.3 weakened), and `report_ready` (§3.7) do. For those rules in v0.2, conservative path matching (overlap requires shared prefix) is acceptable.

**Exit code extraction:**

```python
import re
EXIT_RE = re.compile(r"Process exited with code (\d+)", re.MULTILINE)
def exit_code_from_output(output: str) -> int:
    m = EXIT_RE.search(output)
    return int(m.group(1)) if m else 0  # absence = success per Codex convention
```

**Stderr first line extraction (heuristic):**

```python
def stderr_first_line(output: str) -> str | None:
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("Output:") or stripped.startswith("Chunk ID"):
            continue
        if stripped.startswith("Process exited"):
            continue
        if any(marker in stripped.lower() for marker in ("error:", "traceback", "exception:", "stderr:")):
            return stripped
    return None
```

Applied to: **INTEGRATION_PATTERN v0.1.1 §3.5 (new), and RULES_SPEC v0.2.1 §1 (note about adapter responsibility)**.

### Finding 6: `source_event_id` is not stable across machines

**Issue:** The hash includes the absolute rollout path. Different machines have different absolute paths even for the same conceptual session.

**Resolution.** Remove absolute path from the hash inputs. Use:

```
source_event_id = sha256(
    session_id + "\n" +
    str(source_line_number) + "\n" +
    sha256(raw_line_bytes)
)
```

Where `session_id` is the Codex session UUID (from the `session_meta` payload `id`), which is already machine-independent. `source_line_number` is 1-indexed. `raw_line_bytes` is the exact byte content of the JSONL line as read from disk (UTF-8, no trailing newline).

The same Codex rollout file moved to a different machine produces identical `source_event_id`s for every line.

Applied to: **TKOS scope §3.1 (hash derivation)**.

### Finding 7: Turn-boundary semantics are ambiguous against real Codex ordering

**Issue:** Real sessions contain `task_started` followed by a user message. The v0.2 rule (increment on either) increments twice for one interaction round.

**Resolution.** Use Codex's native `turn_id`.

Codex provides `turn_id` in `event_msg(type=task_started)`, `turn_context`, and `event_msg(type=task_complete)` payloads. The locked turn-derivation rule:

- Each distinct `turn_id` observed in the rollout maps to a `turn_idx` in the order it first appears, starting from 0.
- `event_idx` is monotonic within a `turn_id`'s first-to-last-event range, starting from 0 at the turn's first line.
- Lines with no associated `turn_id` (e.g., `session_meta`, `turn_context`) are persisted with `turn_idx = -1` in `raw_lines` and do NOT appear in `events`.

Fallback for adapters whose source doesn't have native turn_ids (future Claude Code adapter, custom): the v0.1.1 fallback rule (increment on `user_message` OR `task_start`, but with alternation enforcement) — left to the adapter spec for that source.

Applied to: **TKOS scope §3.2 (renamed: derived identity tuple) + §4.4 (turn-boundary rule rewrite)**.

### Finding 8: Rule set is not deterministic on repeated failures

**Issue:** `pipeline_failed_born` (RULES_SPEC §3.5) fires unconditionally on any failing `tool_result`. `pipeline_failed_strengthened` also fires when an active matching belief exists. Both fire → new belief minted AND old refreshed.

**Resolution.** Mutually exclusive preconditions.

`pipeline_failed_born` precondition (new):

```
PRECONDITIONS:
  - NO active pipeline_failed belief exists whose failure_signature matches this event's failure_signature
```

`pipeline_failed_strengthened` precondition (existing, retained):

```
PRECONDITIONS:
  - Active pipeline_failed belief exists whose failure_signature matches this event's failure_signature
```

At most one of the two rules fires per matching `tool_result` event. Same pattern applied to any future rule pair with this structure (mint-vs-refresh).

Applied to: **RULES_SPEC v0.2.1 §3.5 (born precondition)**.

### Finding 9: Export ordering destroys event chronology

**Issue:** TKOS scope §10 Q6 sorts the export by lexicographic `source_event_id` (which is hash-derived). Hash order is random vs the session timeline, making "active beliefs up-to-and-including event" misleading.

**Resolution.** Sort by `(turn_idx, event_idx, source_line_number)`.

Determinism is preserved (the ordering is fully derived from event metadata). The order matches the session timeline, making the active-beliefs-snapshot meaningful as a turn-by-turn audit.

Applied to: **TKOS scope §10 Q6 (export format)**.

---

## Medium findings (two)

### Finding 10: `action_blocked` conflicts with the existing read path and demo

**Issue:** RULES_SPEC §3.8 makes `action_blocked` a computed (not persisted) belief, but the existing `state()` and `overlay()` only render persisted beliefs, and the demo expected a lifecycle for `action_blocked`.

**Resolution.** Read-path migration adds synthetic rendering for computed beliefs.

Per finding 3's resolution, the read-path migration scope explicitly includes: when `overlay()`, `state()`, or `risk()` is called, after the query has loaded persisted active beliefs, compute `action_blocked` per RULES_SPEC §3.8's derivation and append it to the returned set as a synthetic belief (no `belief_id`, no `revision_trail`).

The demo's `action_blocked` expectations are updated in the read-path migration's test suite: the test no longer asserts a persisted `action_blocked` lifecycle, but asserts that querying with active blocker beliefs returns a synthetic `action_blocked` in the projection.

Applied to: **New TKOS_READ_PATH_MIGRATION_v0.2.md (synthetic rendering rules + test updates)**.

### Finding 11: Integration scope contradicts write-path scope

**Issue:** Write-path scope §1.4 excludes overlay auto-injection. INTEGRATION_PATTERN §7 (minimal viable integration) lists "Codex via TKOS write-path sidecar" as the reference integration with overlay injection at planning moments.

**Resolution.** Reclassify Codex v0.2 as capture-only.

INTEGRATION_PATTERN v0.1.1 §7.4 update: the Codex v0.2 reference integration is **capture-only**. Events flow from rollout → sidecar; the substrate is populated; the overlay is *available* via `overlay()` but is NOT automatically injected into Codex's context (Codex offers no documented hook for this in v0.2).

A separate integration milestone — possibly via a Claude Code harness adapter with planning-step interception, or a custom-built harness — would be the first live-injection integration. That work is not in v0.2 scope.

Applied to: **INTEGRATION_PATTERN v0.1.1 §7.4 (reference integration clarification), TKOS scope §1.4 (consistency check)**.

---

## What this does NOT change

- The locked positioning structure (`project_three_consequences_structure.md`).
- The locked v0.4c2 substrate-project separation decision (`project_v04c2_substrate_separation.md`) — the sidecar is still software-only; v0.4c2 substrate still requires a separate fresh Codex project.
- The locked Option A decision (sidecar build software-only, substrate project later).
- The atomicity contract (RULES_SPEC §7) — unchanged.
- The §6 spec constants — unchanged.
- The seven primitive belief types in RULES_SPEC §2.1 — unchanged.
- The streaming/batch equivalence target restriction to the v0.2 subset — unchanged.
- The §10 versioning rules — this audit-response is itself an example of the spec being re-versioned per the discipline.

---

## Sequencing for the implementation

1. The four spec amendments commit together (one Git commit per amendment doc is fine):
   - `RULES_SPEC_v0.2.md` → v0.2.1 (findings 1 note, 5 note, 8, 10 note)
   - `TKOS_WRITE_PATH_SCOPE_v0.2.md` → v0.2.1 (findings 1, 2, 4, 6, 7, 9; plus note about finding 3 separate scope)
   - `INTEGRATION_PATTERN_v0.1.md` → v0.1.1 (findings 5, 11)
   - `TKOS_READ_PATH_MIGRATION_v0.2.md` — new (findings 3, 10)
2. Code can then begin against v0.2.1 of the scope and RULES_SPEC, with the read-path migration as a parallel work item.
3. The bootstrap step (TKOS scope §9 step 1) now includes:
   - Creating the new `raw_lines` table
   - Adding `source_event_id`, `event_idx`, `source_rollout_path`, `source_line_number`, `call_id` to existing `events` table
   - Adding `effective_turn` to existing `belief_events` table
   - Adding `transcript_hash` and `line_hash_chain` to `session_status`
   - Backfilling fixtures with the new identity scheme

---

*The audit was load-bearing. Eleven findings, four critical, all addressable in spec amendments without changing the architectural commitments. The discipline of locking before code is precisely what surfaced these — and what makes the amendments traceable rather than silent. The next code-blocking artifact would be the read-path migration spec; everything else is amendment edits to the existing locked docs.*
