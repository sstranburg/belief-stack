# TKOS Read-Path Migration — Scope v0.3.3

**Date:** 2026-06-06 (v0.2 → v0.3.1 → v0.3.2 → v0.3.3, this version)
**Status:** LOCKED at v0.3.3. Scope artifact for the read-path code changes that v0.3.3 of the write-path requires.

**v0.3.2 → v0.3.3 patch (one fix in this doc):**
- **Fix VI — Synthetic `action_blocked` count semantics locked.** §1.4 — the synthetic record is correctly shaped and sort-safe per fixes 6 and 4, but it was not specified whether `reconstruct_state()` and `build_overlay()` return it counted as one of the active beliefs. v0.3.3 locks: **yes, the synthetic `action_blocked` IS counted** in `len(reconstruct_state(...))`. Consumers wanting a persisted-only count can filter with `b["is_synthetic"] is not True`. The overlay budget accounting (per the existing `build_overlay` ranking) also counts the synthetic: its rendered string occupies tokens like any other belief.

**v0.3.1 → v0.3.2 patch (one fix in this doc):**
- **Fix 4 — Synthetic `action_blocked` `belief_id` must be a string, not `None`.** §1.4 — The existing `tkos.py` `build_overlay` ranking sorts by composite key including `belief_id`. When a blocker and the synthetic `action_blocked` tie on preceding fields, Python's sort compares `None` with `str` and raises `TypeError`. v0.3.2 locks the synthetic `belief_id` to a deterministic string: `"synthetic:action_blocked:{session_id}:{query_turn}"`. The synthetic flag (`is_synthetic=True`) still distinguishes from persisted beliefs; the string ID just keeps sort comparisons type-consistent.

**v0.2 → v0.3.1 patches (two fixes in this doc):**
- **Fix 1 (read-path migration aspect) — SQLite executable migration.** §1.2 `belief_events` schema amendment: `DEFAULT at_turn` is not a valid column-dependent SQLite default. Migration sequence rewritten: add nullable → backfill in app code → constraint enforcement.
- **Fix 6 — Synthetic action_blocked record must be read-path compatible.** §1.4 synthetic record updated to include all fields the existing overlay/state renderers expect (`state`, `warrant_turns`, `last_updated_turn`, `created_turn`). Authority ranking corrected to use `AUTH_RANK` (lexicographic max on the enum strings happens to give the wrong order — `confirmed_by_tool` < `confirmed_by_user` < `asserted_by_assistant` alphabetically, which inverts the actual authority hierarchy).
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

### §1.2 `belief_events.effective_turn` filtering (v0.3.1 — fix 1 executable migration)

SQLite does not support column-dependent DEFAULTs in `ALTER TABLE ADD COLUMN`. Migration sequence:

```sql
-- Step A: add nullable column
ALTER TABLE belief_events ADD COLUMN effective_turn INTEGER;
```

```sql
-- Step B: backfill in app code (Python migration script)
UPDATE belief_events SET effective_turn = at_turn WHERE effective_turn IS NULL;
```

```sql
-- Step C: optionally enforce non-null via table rebuild (NOT REQUIRED)
-- v0.3.1 default: enforce non-null at the application layer in rules.py.
-- Every insert into belief_events writes effective_turn explicitly.
```

A startup integrity check verifies no `belief_events` row has null `effective_turn`. For non-retro rules, `effective_turn = at_turn` (= `observed_at_turn`) — the migration backfill plus the application-layer enforcement together preserve the invariant.

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

### §1.4 Synthetic `action_blocked` rendering (v0.3.1 — fix 6 shape compatibility)

After the persisted active beliefs are loaded for a query, compute and append `action_blocked` per RULES_SPEC §3.8.

The synthetic record must include **every field** the existing `build_overlay` and `state` renderers expect. The existing `tkos.py` consumers read at least: `state`, `belief_id`, `belief_type`, `claim`, `warrant_turns`, `last_updated_turn`, `created_turn`, `authority`. Omitting any of these raises a KeyError in rendering. The v0.3.1 synthetic record carries all of them.

Authority comparison must use `AUTH_RANK` because the enum strings sort lexicographically in the wrong order (`asserted_by_assistant` < `confirmed_by_tool` < `confirmed_by_user` alphabetically — but the *operational* hierarchy goes asserted < confirmed_by_tool < confirmed_by_user, so `max(strings)` would return `confirmed_by_user` only by coincidence; for `(asserted, confirmed_by_tool)`, `max` would return `confirmed_by_tool` correctly but `(confirmed_by_user, confirmed_by_tool)` would return `confirmed_by_user` — which is also right by coincidence. The lexicographic ordering happens to be correct in this case but the alignment is fragile and not the spec's contract; use `AUTH_RANK` explicitly).

```python
AUTH_RANK = {
    "asserted_by_assistant": 0,
    "confirmed_by_tool":     1,
    "confirmed_by_user":     2,
}

def reconstruct_state(conn, session_id, turn=None):
    persisted = _persisted_active_beliefs(conn, session_id, turn)
    synthetic = _compute_action_blocked(persisted, query_turn=turn)
    return persisted + synthetic

def _compute_action_blocked(persisted, query_turn):
    blockers = [b for b in persisted
                if b["belief_type"] in ("validation_pending", "user_approval_pending", "pipeline_failed")
                and b["state"] in ("active", "weakened")]
    if not blockers:
        return []

    # Pick highest blocker authority using AUTH_RANK
    highest_blocker = max(blockers, key=lambda b: AUTH_RANK[b["authority"]])

    # Deterministic synthetic ID — string, not None — so overlay sort comparisons
    # (which include belief_id as a tie-break key) don't crash on None vs str.
    synthetic_id = f"synthetic:action_blocked:{session_id}:{query_turn}"

    return [{
        # required identity-shaped fields
        "belief_id":         synthetic_id,   # v0.3.2 — fix 4: deterministic str, not None
        "belief_type":       "action_blocked",
        "claim":             f"action_blocked — {len(blockers)} blocker(s): "
                             + ", ".join(b["belief_type"] for b in blockers),
        # state shape compatibility (matches what tkos.py builds)
        "state":             "active",       # the existing tkos.py reads `state`, not `lifecycle_state`
        "authority":         highest_blocker["authority"],
        # warrant + temporal fields the overlay renderer reads
        "warrant_turns":     [b.get("last_updated_turn", query_turn) for b in blockers],
        "counterevidence_turns": [],
        "created_turn":      min(b.get("created_turn", query_turn) for b in blockers),
        "last_updated_turn": max(b.get("last_updated_turn", query_turn) for b in blockers),
        # mark synthetic
        "is_synthetic":      True,
        "warrant_belief_ids": [b["belief_id"] for b in blockers if b["belief_id"] is not None],
    }]
```

The synthetic belief carries `is_synthetic=True` to distinguish from persisted beliefs. Its `belief_id` is a deterministic string (`synthetic:action_blocked:...`) rather than `None`, so sort comparisons remain type-safe. It has no `revision_trail`. `build_overlay` and `state` consumers handle synthetic beliefs identically to persisted ones for ranking/rendering but never attempt to mutate or persist them (a write path that receives a `belief_id` starting with `synthetic:` should treat it as a programming error and refuse).

**Count semantics (v0.3.3 — fix VI):** the synthetic `action_blocked` IS counted in `len(reconstruct_state(...))` results. Consumers wanting a persisted-only count can filter via `[b for b in result if not b.get("is_synthetic")]`. Overlay budget accounting also counts the synthetic — its rendered string occupies tokens like any other belief. This is consistent with the "treated identically to persisted" framing; the synthetic is a real query result, not a sidecar/secondary value.

**Field alignment note (fix 6 specifics):** the existing `tkos.py` uses `state` as the lifecycle field name (not `lifecycle_state`). The synthetic record must match. The existing renderer's ranking policy uses `warrant_turns` and `counterevidence_turns` to compute recency boosts; the synthetic carries the blockers' aggregated turns. Authority is the max blocker authority by `AUTH_RANK`, not lexicographic.

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
