"""Acceptance tests for TKOS-002 read-path slice v0.1.

Per `TKOS-002_IMPLEMENTATION_SLICE_v0.1.md` §6.

The acceptance criteria from the user spec:
  A. Before validation succeeds: validation_pending and action_blocked active.
  B. After validation succeeds: validation_pending retired,
     validation_complete active.
  C. State reconstruction comes from belief_events replay, not from a
     hand-written active-state snapshot.

Run:
  python test_tkos.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tkos import (  # noqa: E402
    ACTIVE_BLOCKER_TYPES,
    DEMO_SESSION_ID,
    build_overlay,
    init_db,
    load_demo_fixture,
    reconstruct_state,
)


def fresh_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    load_demo_fixture(conn)
    return conn


def active_types(beliefs: list[dict]) -> set[str]:
    return {b["belief_type"] for b in beliefs if b["state"] == "active"}


# ─── Test A — pre-validation (turn 8) ───────────────────────────────────

def test_A_pre_validation() -> None:
    conn = fresh_db()
    beliefs, _ = reconstruct_state(conn, DEMO_SESSION_ID, 8)
    types = active_types(beliefs)

    assert "validation_pending" in types, (
        f"Test A: expected validation_pending active at turn 8; got {types}"
    )
    assert "action_blocked" in types, (
        f"Test A: expected action_blocked active at turn 8; got {types}"
    )
    assert "fix_attempted" in types, (
        f"Test A: expected fix_attempted active at turn 8; got {types}"
    )
    assert "validation_complete" not in types, (
        f"Test A: validation_complete should NOT be active at turn 8; got {types}"
    )
    print(f"  Test A passed  (turn 8 actives: {sorted(types)})")


# ─── Test B — post-validation (turn 10) ─────────────────────────────────

def test_B_post_validation() -> None:
    conn = fresh_db()
    beliefs, counts = reconstruct_state(conn, DEMO_SESSION_ID, 10)
    types = active_types(beliefs)

    assert "validation_pending" not in types, (
        f"Test B: validation_pending should be retired at turn 10; got {types}"
    )
    assert "action_blocked" not in types, (
        f"Test B: action_blocked should be retired at turn 10; got {types}"
    )
    assert "validation_complete" in types, (
        f"Test B: validation_complete should be active at turn 10; got {types}"
    )
    assert "fix_attempted" in types, (
        f"Test B: fix_attempted should still be active at turn 10; got {types}"
    )
    # Retired count should include the cleared validation_pending +
    # action_blocked + pipeline_failed + first fix_attempted + first
    # validation_pending = at least 5.
    assert counts.get("retired", 0) >= 5, (
        f"Test B: expected >= 5 retired beliefs at turn 10; got {counts}"
    )
    print(f"  Test B passed  (turn 10 actives: {sorted(types)}; counts={counts})")


# ─── Test C — substrate provenance ──────────────────────────────────────

def test_C_substrate_provenance() -> None:
    """Reconstruction comes from belief_events replay, not from a snapshot.

    Two checks:
      1. No state-snapshot table exists in the schema.
      2. Re-running Test A and Test B with the active_beliefs VIEW removed
         must still produce the correct results, proving the --turn T
         code path does not depend on the view.
    """
    conn = fresh_db()
    cur = conn.cursor()

    # 1. No snapshot tables.
    cur.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
    objs = {row[0] for row in cur.fetchall()}
    forbidden = {
        name for name in objs
        if "snapshot" in name.lower() or "active_state" in name.lower()
    }
    assert forbidden == set(), (
        f"Test C: found forbidden snapshot objects: {forbidden}"
    )

    # 2. Replay still works without any active_beliefs view present
    #    (the slice does not create one, so this is trivially true; we
    #    assert it explicitly so a future change that adds a view does
    #    not silently couple --turn T to it).
    assert "active_beliefs" not in objs, (
        "Test C: this slice intentionally does not create active_beliefs; "
        f"present objects: {sorted(objs)}"
    )

    # Re-run A and B against the same conn to confirm the reconstruct
    # path is self-contained.
    beliefs_a, _ = reconstruct_state(conn, DEMO_SESSION_ID, 8)
    beliefs_b, _ = reconstruct_state(conn, DEMO_SESSION_ID, 10)
    assert "validation_pending" in active_types(beliefs_a)
    assert "validation_complete" in active_types(beliefs_b)
    print(f"  Test C passed  (no snapshot tables; replay-only reconstruction)")


# ─── Test D — overlay at turn 8 (AI-facing read path) ───────────────────

def test_D_overlay_pre_validation() -> None:
    """At turn 8 with budget=1000, overlay includes the active blockers."""
    conn = fresh_db()
    rendered, meta = build_overlay(conn, DEMO_SESSION_ID, 8, budget_tokens=1000)

    assert "validation_pending" in rendered, (
        f"Test D: expected validation_pending in overlay; got:\n{rendered}"
    )
    assert "action_blocked" in rendered, (
        f"Test D: expected action_blocked in overlay; got:\n{rendered}"
    )
    # "pipeline_failed or blocker-relevant state"
    blocker_present = any(t in rendered for t in ACTIVE_BLOCKER_TYPES)
    assert blocker_present, (
        f"Test D: expected at least one active blocker in overlay; got:\n{rendered}"
    )
    assert meta["tokens_used"] <= meta["budget_tokens"], (
        f"Test D: overlay over budget — used {meta['tokens_used']} of {meta['budget_tokens']}"
    )
    print(f"  Test D passed  (turn 8 overlay: {meta['admitted_count']} admitted, "
          f"{meta['tokens_used']}/{meta['budget_tokens']} tokens)")


# ─── Test E — overlay at turn 10 ────────────────────────────────────────

def test_E_overlay_post_validation() -> None:
    """At turn 10 with budget=1000, overlay reflects post-validation state."""
    conn = fresh_db()
    rendered, meta = build_overlay(conn, DEMO_SESSION_ID, 10, budget_tokens=1000)

    # validation_pending was retired; it must not appear in default overlay.
    # (Match on the structured `belief_type ::` to avoid false positives
    # from substring matches inside other belief lines.)
    assert "validation_pending ::" not in rendered, (
        f"Test E: validation_pending should be retired at turn 10; got:\n{rendered}"
    )
    assert "validation_complete" in rendered, (
        f"Test E: expected validation_complete in overlay; got:\n{rendered}"
    )
    assert meta["tokens_used"] <= meta["budget_tokens"], (
        f"Test E: overlay over budget — used {meta['tokens_used']} of {meta['budget_tokens']}"
    )
    print(f"  Test E passed  (turn 10 overlay: {meta['admitted_count']} admitted, "
          f"{meta['tokens_used']}/{meta['budget_tokens']} tokens)")


# ─── Test F — budget behavior ───────────────────────────────────────────

def test_F_overlay_budget_behavior() -> None:
    """Tight budget admits fewer beliefs; omitted counts reported; no partial lines.

    Active blockers are ranked to land first under any positive budget.
    """
    conn = fresh_db()

    # Spacious budget should admit everything available at turn 8.
    _, meta_big = build_overlay(conn, DEMO_SESSION_ID, 8, budget_tokens=1000)

    # Tight budget — small enough that only ~1-2 beliefs fit after the
    # header reserve. 50 tokens covers header (~22) + ~1 belief (~24).
    rendered_tiny, meta_tiny = build_overlay(conn, DEMO_SESSION_ID, 8, budget_tokens=50)

    assert meta_tiny["admitted_count"] < meta_big["admitted_count"], (
        f"Test F: tight budget should admit fewer beliefs; "
        f"tiny={meta_tiny['admitted_count']} big={meta_big['admitted_count']}"
    )
    assert meta_tiny["omitted_count"] > 0, (
        f"Test F: tight budget should report omissions; got meta={meta_tiny}"
    )
    # Every belief line in the tiny overlay must be a complete one-liner
    # ending in the closing ')' of the meta block — no partial renderings.
    belief_lines = [
        ln for ln in rendered_tiny.split("\n")
        if ln.startswith("[")
    ]
    for line in belief_lines:
        assert "::" in line and line.endswith(")"), (
            f"Test F: partial belief line in tiny overlay: {line!r}"
        )
    # Active blockers should be ranked first; if any belief admitted,
    # at least one should be a blocker.
    if meta_tiny["admitted_count"] > 0:
        admitted_blockers = {
            t for t in meta_tiny["admitted_by_type"] if t in ACTIVE_BLOCKER_TYPES
        }
        assert admitted_blockers, (
            f"Test F: tight budget should admit blockers first; "
            f"admitted_by_type={meta_tiny['admitted_by_type']}"
        )
    # Budget cap strictly respected.
    assert meta_tiny["tokens_used"] <= meta_tiny["budget_tokens"], (
        f"Test F: tight overlay over budget — "
        f"used {meta_tiny['tokens_used']} of {meta_tiny['budget_tokens']}"
    )
    print(f"  Test F passed  (tight=50tok admits {meta_tiny['admitted_count']}, "
          f"omits {meta_tiny['omitted_count']}, "
          f"tokens={meta_tiny['tokens_used']}/{meta_tiny['budget_tokens']})")


# ─── Runner ─────────────────────────────────────────────────────────────

def main() -> int:
    print("TKOS-002 read-path slice — acceptance tests")
    print("-" * 60)
    try:
        test_A_pre_validation()
        test_B_post_validation()
        test_C_substrate_provenance()
        test_D_overlay_pre_validation()
        test_E_overlay_post_validation()
        test_F_overlay_budget_behavior()
    except AssertionError as exc:
        print()
        print(f"FAIL: {exc}")
        return 1
    print()
    print("All acceptance tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
