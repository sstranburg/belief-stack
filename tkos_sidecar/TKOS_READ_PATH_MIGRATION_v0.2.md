# TKOS Read-Path Migration — Scope v0.2

**Date:** 2026-06-06
**Status:** LOCKED. Scope artifact for the read-path code changes that v0.2.1 of the write-path requires.
**Predecessors:**
- [`AUDIT_RESPONSE_2026-06-06.md`](./AUDIT_RESPONSE_2026-06-06.md) — finding 3 (read-path is NOT unchanged) and finding 10 (action_blocked rendering).
- [`TKOS_WRITE_PATH_SCOPE_v0.2.md`](./TKOS_WRITE_PATH_SCOPE_v0.2.md) v0.2.1 — the write-path scope this read-path migration aligns with.
- [`RULES_SPEC_v0.2.md`](./RULES_SPEC_v0.2.md) v0.2.1 — the spec whose temporal semantics this migration honors.
- [`tkos.py`](./tkos.py) — the existing read-path slice being migrated.

---

## Purpose

The original v0.2 write-path scope claimed the read-path was unchanged. It was wrong. The existing `tkos.py` `reconstruct_state()`:

- Filters and orders solely by `at_turn` (no `effective_turn` support).
- Maps `weakened` to `contradicted` (excludes weakened beliefs from the active set).
- Has no rendering for computed beliefs (no `action_blocked` synthesis).

RULES_SPEC v0.2.1 requires:

- Filter by `effective_turn` (per §4.2): retro-minted beliefs visible at the turns where they were *effectively* true, not just where they were *observed*.
- `weakened` remains active in lifecycle_state filtering (per §4.2 / §8): weakened means "evidence suggests but doesn't yet contradict" — still an active belief.
- Computed beliefs rendered synthetically at query time (per §3.8): `action_blocked` derives from active blocker beliefs and appears in projection results.

This migration is a code change to `tkos_sidecar/tkos.py`. It is **not** a spec change. It ships alongside (or just before) the write-path build's step 5 of `TKOS_WRITE_PATH_SCOPE_v0.2.md` §9.

---

## §1 In-scope changes

### §1.1 `events` schema query support

The read-path queries the v0.2.1 augmented `events` table (per write-path scope §8.1). Specifically:

- `events.event_idx` is now a real column. Queries that previously used only `(session_id, turn_idx)` should expand to `(session_id, turn_idx, event_idx)` where relevant.
- `events.source_event_id` is available for joining when needed; the read-path can continue using the integer `event_id` for internal joins.

### §1.2 `belief_events.effective_turn` filtering

Add `effective_turn INTEGER NOT NULL DEFAULT at_turn` to `belief_events`. Existing rows backfill `effective_turn = at_turn` (which is correct for non-retro beliefs — finding 3 noted this is already the default).

Update `reconstruct_state(session_id, turn=Q)`:

```python
# Old:
SELECT ... FROM belief_events WHERE at_turn <= Q ORDER BY at_turn

# New:
SELECT ... FROM belief_events WHERE effective_turn <= Q ORDER BY effective_turn
```

Tie-breaking when multiple belief_events for the same belief have the same `effective_turn`: order by `at_turn` (which is now `observed_at_turn`) ascending, then by `belief_event_id` ascending. This is deterministic and replayable.

### §1.3 Weakened lifecycle filtering

Update the lifecycle_state mapping in `reconstruct_state`:

| `belief_events.kind` | Current `tkos.py` behavior | v0.2 required behavior |
|---|---|---|
| `born` | active | active |
| `refreshed` | active | active |
| `confirmed` | active | active |
| `weakened` | **contradicted (excluded)** | **active (included, but flagged)** |
| `contradicted` | contradicted (excluded) | contradicted (excluded) |
| `superseded` | excluded | excluded (renamed to `retired` in v0.2) |
| `retired` | excluded | excluded |

The `weakened` beliefs are still part of the active set per RULES_SPEC §4 / §8 / §3.3 `validation_complete_weakened_by_edit`. The read-path may surface them with reduced ranking priority in `build_overlay`, but they must not be filtered out.

### §1.4 Synthetic `action_blocked` rendering

After the persisted active beliefs are loaded for a query, compute and append `action_blocked` per RULES_SPEC §3.8.

In `reconstruct_state` (or wrapping it):

```python
def reconstruct_state(conn, session_id, turn=None):
    persisted = _persisted_active_beliefs(conn, session_id, turn)
    synthetic = _compute_action_blocked(persisted)
    return persisted + synthetic

def _compute_action_blocked(persisted):
    blockers = [b for b in persisted if b["belief_type"] in
                ("validation_pending", "user_approval_pending", "pipeline_failed")
                and b["lifecycle_state"] == "active"]
    if not blockers:
        return []
    return [{
        "belief_id": None,                     # synthetic — no persisted identity
        "belief_type": "action_blocked",
        "claim": f"action_blocked — {len(blockers)} blocker(s): " +
                 ", ".join(b["belief_type"] for b in blockers),
        "lifecycle_state": "active",
        "authority": max(b["authority"] for b in blockers),  # highest blocker authority
        "warrant_belief_ids": [b["belief_id"] for b in blockers],
        "is_synthetic": True,
    }]
```

The synthetic belief carries `is_synthetic=True` to distinguish from persisted beliefs. It has no `belief_id` and no `revision_trail`. `build_overlay` and `state` consumers should handle synthetic beliefs identically to persisted ones for ranking/rendering but never attempt to mutate or persist them.

The `risk(session_id, action)` query may further filter blockers by action — only blockers relevant to the proposed action contribute to the returned `action_blocked` derivation. v0.2.1 default: all blockers are relevant to all actions; per-action filtering is v0.3 work.

### §1.5 Demo fixture updates

The existing demo fixture in `tkos.py` `load_demo_fixture` was constructed before computed `action_blocked`. The demo's expected behavior at turn 15 (the `risk("deploy")` call) currently includes a persisted `action_blocked` belief. Update the fixture to:

- Remove the persisted `action_blocked` row.
- The demo's `state(turn=15)` will then synthesize `action_blocked` from the active `user_approval_pending` blocker.
- The expected fixture results in `test_tkos.py` update accordingly.

### §1.6 Test updates

In `test_tkos.py`, add or update tests covering:

1. **Retro-minted belief at effective_turn.** Insert a belief_event with `effective_turn=5, observed_at_turn=8`; verify `state(turn=6)` returns it; verify `state(turn=4)` does not.
2. **Weakened belief is active.** Mint a belief; weaken it; verify `state(turn=Q)` includes it with lifecycle_state="weakened" (or "active" with a "weakened" flag — implementation choice as long as it's not excluded).
3. **Synthetic action_blocked appears with blocker.** Mint a `validation_pending` belief; verify `state(turn=Q)` returns it plus a synthetic `action_blocked`.
4. **Synthetic action_blocked absent without blockers.** Mint and retire a `validation_pending`; verify `state(turn=Q)` does not include `action_blocked`.
5. **Synthetic action_blocked never persisted.** After several queries that synthesize `action_blocked`, verify `belief_instances` and `belief_events` contain no rows of type `action_blocked`.

These join the existing six acceptance tests in `test_tkos.py` (which are unrelated to the migration); the migration's five new tests sit alongside them.

---

## §2 Out-of-scope

- Adding new belief types beyond what RULES_SPEC v0.2.1 §2 enumerates.
- Performance optimization of the read-path queries (e.g., materialized active_beliefs view) — implementation choice.
- Cross-session queries.
- The `risk()` per-action filter beyond "all blockers are relevant" (v0.3 work).

---

## §3 Implementation order

1. Add `effective_turn` column to `belief_events` schema (DDL).
2. Backfill `effective_turn = at_turn` for existing rows (one-shot migration).
3. Update `reconstruct_state` to filter by `effective_turn` (§1.2).
4. Update lifecycle mapping to keep `weakened` active (§1.3).
5. Add `_compute_action_blocked` and wire it into `reconstruct_state` (§1.4).
6. Update `load_demo_fixture` (§1.5).
7. Add the five new tests (§1.6).
8. Run `test_tkos.py`; all original six tests + five new tests must pass.

---

## §4 What this migration does NOT touch

- `build_overlay` ranking policy (unchanged).
- `render_overlay_line` rendering (unchanged).
- `cmd_state` / `cmd_overlay` CLI handlers (unchanged; they call into `reconstruct_state` which carries the migration).
- The HTTP endpoint / write-path code (separate scope).

---

*The read-path migration is a discrete, bounded code change. The write-path scope v0.2.1 references this as a parallel work item; both ship together. The audit finding that revealed this was load-bearing: claiming the read-path was unchanged would have produced silent incorrect query results once the write-path started writing retro-minted beliefs and weakened lifecycle states. The migration makes those semantics explicit and tested.*
