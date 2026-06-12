"""TKOS write-path verify + export — completeness checks and substrate-grade JSONL export.

Verify implements the §6.2 five-check completeness validation:
  1. Line-count completeness — raw_lines count matches total_line_count
  2. No unrecognized lines
  3. Sequence validation — event_idx contiguous per turn (mapped only)
  4. Hash verification — both raw_rollout_sha256 and line_hash_chain match
  5. No rule failures

Export implements §10 Q6: one JSONL line per event, sorted by
(turn_idx, event_idx, source_line_number), with active_beliefs snapshot
per event. Stable ordering, deterministic content. The export is the
substrate artifact the v0.4c2 backtest would consume.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from tkos import reconstruct_state


# ─── Verify ────────────────────────────────────────────────────────────


class VerifyResult:
    """Result of running the §6.2 five-check completeness validation."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.passed = True
        self.checks: list[dict[str, Any]] = []

    def record(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"check": name, "ok": ok, "detail": detail})
        if not ok:
            self.passed = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "passed": self.passed,
            "checks": self.checks,
        }


def verify_session(conn: sqlite3.Connection, session_id: str) -> VerifyResult:
    """Run the five-check completeness validation per scope §6.2.

    A session passes only if all five checks pass. The result includes
    per-check detail for diagnosing failures.
    """
    result = VerifyResult(session_id)
    cur = conn.cursor()

    # Fetch session_status row
    cur.execute(
        """
        SELECT total_line_count, raw_rollout_sha256, line_hash_chain,
               capture_ended_at, source_rollout_path
        FROM session_status WHERE session_id = ?
        """,
        (session_id,),
    )
    sess = cur.fetchone()
    if sess is None:
        result.record("session_exists", False,
                      f"no session_status row for {session_id}")
        return result
    total_line_count, raw_rollout_sha256, line_hash_chain, capture_ended_at, source_path = sess

    # Check 1: line-count completeness
    cur.execute(
        "SELECT COUNT(*) FROM raw_lines WHERE session_id = ?",
        (session_id,),
    )
    raw_count = cur.fetchone()[0]
    if total_line_count is None:
        result.record("line_count", False,
                      "session not finalized (total_line_count is NULL)")
    elif raw_count != total_line_count:
        result.record("line_count", False,
                      f"raw_lines count {raw_count} != total_line_count {total_line_count}")
    else:
        result.record("line_count", True,
                      f"raw_lines={raw_count}, total_line_count={total_line_count}")

    # Check 2: no unrecognized lines
    cur.execute(
        "SELECT COUNT(*) FROM raw_lines WHERE session_id = ? AND category = 'unrecognized'",
        (session_id,),
    )
    unrecog = cur.fetchone()[0]
    result.record("no_unrecognized", unrecog == 0,
                  f"unrecognized_count={unrecog}")

    # Check 3: sequence validation (events.event_idx contiguous per turn)
    cur.execute(
        """
        SELECT turn, event_idx FROM events
        WHERE session_id = ?
        ORDER BY turn, event_idx
        """,
        (session_id,),
    )
    seen_per_turn: dict[int, list[int]] = {}
    for turn, event_idx in cur.fetchall():
        seen_per_turn.setdefault(turn, []).append(event_idx)
    seq_ok = True
    seq_detail = []
    for turn, idxs in seen_per_turn.items():
        if turn < 0:
            continue  # ignored-known lines with turn_idx=-1 don't go through events
        expected = list(range(len(idxs)))
        if idxs != expected:
            seq_ok = False
            seq_detail.append(f"turn={turn}: got {idxs}, expected {expected}")
    result.record("sequence_validation", seq_ok,
                  "; ".join(seq_detail) if not seq_ok else f"{len(seen_per_turn)} turns OK")

    # Check 4: hash verification
    hash_detail = []
    hash_ok = True

    # 4a. raw_rollout_sha256 recompute from source file
    if raw_rollout_sha256 is None or source_path is None:
        hash_ok = False
        hash_detail.append("raw_rollout_sha256 or source_path missing (not finalized)")
    else:
        try:
            with open(source_path, "rb") as fh:
                computed_sha = hashlib.sha256(fh.read()).hexdigest()
            if computed_sha != raw_rollout_sha256:
                hash_ok = False
                hash_detail.append(
                    f"raw_rollout_sha256 mismatch (stored={raw_rollout_sha256[:12]}…, "
                    f"computed={computed_sha[:12]}…)"
                )
        except (OSError, FileNotFoundError) as exc:
            hash_ok = False
            hash_detail.append(f"could not read source file: {exc}")

    # 4b. line_hash_chain recompute from raw_lines
    cur.execute(
        """
        SELECT raw_line_bytes FROM raw_lines
        WHERE session_id = ?
        ORDER BY source_line_number
        """,
        (session_id,),
    )
    chain = ""
    for (raw_line_bytes,) in cur.fetchall():
        chain = hashlib.sha256(chain.encode("utf-8") + raw_line_bytes).hexdigest()
    if chain != (line_hash_chain or ""):
        hash_ok = False
        hash_detail.append(
            f"line_hash_chain mismatch (stored={(line_hash_chain or '')[:12]}…, "
            f"computed={chain[:12]}…)"
        )

    if not hash_detail:
        hash_detail.append("raw_rollout_sha256 + line_hash_chain both match")
    result.record("hash_verification", hash_ok, "; ".join(hash_detail))

    # Check 5: no rule failures
    cur.execute(
        "SELECT COUNT(*) FROM rule_failures WHERE session_id = ?",
        (session_id,),
    )
    rule_fails = cur.fetchone()[0]
    result.record("no_rule_failures", rule_fails == 0,
                  f"rule_failures_count={rule_fails}")

    return result


# ─── Export ────────────────────────────────────────────────────────────


def export_session(conn: sqlite3.Connection, session_id: str) -> str:
    """Produce the deterministic JSONL export per scope §10 Q6.

    One line per event, sorted by (turn_idx, event_idx, source_line_number).
    Each line carries the event record plus the active_beliefs snapshot
    computed up-to-and-including that event.

    Returns the export as a single string (JSONL). Caller writes to a file
    if desired.

    Determinism: stable sort key, no wallclock fields in the export, no
    non-deterministic content. Re-exporting the same session yields a
    byte-identical result (acceptance test 9).
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT source_event_id, session_id, turn, event_idx, event_type,
               timestamp, payload_json, source_line_number, call_id,
               outcome_status, event_id
        FROM events
        WHERE session_id = ?
        ORDER BY turn, event_idx, source_line_number
        """,
        (session_id,),
    )
    rows = cur.fetchall()

    lines: list[str] = []
    for row in rows:
        (source_event_id, sid, turn, event_idx, event_type, timestamp,
         payload_json, source_line_number, call_id, outcome_status,
         _event_id) = row

        # Compute active_beliefs snapshot at this event's turn.
        # We use the turn-resolution semantics from tkos.reconstruct_state.
        beliefs, counts = reconstruct_state(conn, sid, turn=turn)

        record = {
            "source_event_id": source_event_id,
            "session_id": sid,
            "turn_idx": turn,
            "event_idx": event_idx,
            "source_line_number": source_line_number,
            "event_type": event_type,
            "timestamp": timestamp,
            "call_id": call_id,
            "outcome_status": outcome_status,
            "payload": json.loads(payload_json) if payload_json else None,
            "active_beliefs_at_turn": _serializable_beliefs(beliefs),
            "active_belief_counts": counts,
        }
        # sort_keys for determinism; separators trim incidental whitespace
        lines.append(json.dumps(record, sort_keys=True, separators=(",", ":")))

    return "\n".join(lines) + ("\n" if lines else "")


def _serializable_beliefs(beliefs: list[dict]) -> list[dict]:
    """Convert beliefs to a sort-deterministic form for export.

    Sorts by belief_id (which is always a string per the synthetic-action_
    blocked deterministic ID); strips no fields beyond ensuring the order
    is repeatable.
    """
    # Each belief is already a dict; ensure stable ordering by belief_id
    return sorted(beliefs, key=lambda b: (b.get("belief_id") or "", b.get("belief_type") or ""))
