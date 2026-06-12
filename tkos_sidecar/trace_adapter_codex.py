"""Codex rollout JSONL trace adapter.

Reads a Codex session rollout JSONL file (typically at
~/.codex/sessions/YYYY/MM/DD/rollout-{timestamp}-{uuid}.jsonl) and feeds
each line into the TKOS write-path sidecar via ingest_source_line().

This is the v0.4c2-grade capture entry point: the rollout file is the
source of truth, the session_id comes from the rollout's session_meta
header, and finalize_session() runs automatically when the last line is
processed (batch mode per scope §6.1a).

Per project_v04c2_substrate_separation.md: this adapter captures
software-side traces. Whether those captured traces are v0.4c2
ADMISSIBLE is a separate question — admissibility requires capture
from session 1 of a fresh Codex project, not retro-capture of an
existing session. The adapter itself doesn't check that; the v0.4c2
admission criteria (§1 hard rule) do.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from ingest import (
    IngestError,
    finalize_session,
    ingest_source_line,
)


class RolloutAdapterError(Exception):
    """Adapter-level failure (missing session_id, malformed first line, etc.)."""


def extract_session_id(rollout_path: str | Path) -> str:
    """Read the first line of the rollout JSONL and extract session_id from
    the session_meta header.

    Raises RolloutAdapterError if the first line is not a session_meta or
    if no id is present. Per Codex's rollout format, the first line is
    always session_meta with payload.id = the session UUID.
    """
    p = Path(rollout_path)
    with p.open("r", encoding="utf-8") as fh:
        first = fh.readline().strip()
    if not first:
        raise RolloutAdapterError(f"rollout file is empty: {rollout_path}")
    try:
        parsed = json.loads(first)
    except json.JSONDecodeError as exc:
        raise RolloutAdapterError(
            f"rollout first line is not valid JSON: {exc.msg}"
        ) from exc
    if parsed.get("type") != "session_meta":
        raise RolloutAdapterError(
            f"rollout first line is not session_meta (got type={parsed.get('type')!r}); "
            "the adapter requires the rollout file to begin with session_meta"
        )
    payload = parsed.get("payload") or {}
    sid = payload.get("id")
    if not isinstance(sid, str) or not sid:
        raise RolloutAdapterError(
            f"session_meta payload has no usable id (got {sid!r})"
        )
    return sid


def ingest_rollout(
    conn: sqlite3.Connection,
    rollout_path: str | Path,
    session_id: Optional[str] = None,
    finalize: bool = True,
) -> dict:
    """Ingest an entire Codex rollout JSONL into the sidecar.

    Args:
        conn: SQLite connection with both tkos.py and ingest.py DDL applied
            (init_db + init_extended_db).
        rollout_path: filesystem path to the rollout JSONL.
        session_id: optional explicit session_id. If omitted, derived from
            the rollout's session_meta header.
        finalize: when True (default), calls finalize_session() after the
            last line is ingested. Set False for live-mode partial ingest
            where the rollout is still being appended.

    Returns:
        Summary dict with counts and per-category tallies.

    Raises:
        RolloutAdapterError: if the rollout is malformed or session_id can't
            be determined.
        IngestError (and subclasses): if any individual line ingestion fails
            in a way that should propagate (e.g., SourceMutationError on
            mid-replay mutation).
    """
    p = Path(rollout_path)
    if not p.exists():
        raise RolloutAdapterError(f"rollout file not found: {rollout_path}")

    sid = session_id or extract_session_id(p)

    counts = {"mapped": 0, "ignored-known": 0, "unrecognized": 0,
              "idempotent_replay": 0}
    total = 0

    with p.open("r", encoding="utf-8") as fh:
        for lineno, raw_line in enumerate(fh, start=1):
            stripped = raw_line.rstrip("\n")
            if not stripped:
                continue
            total += 1
            try:
                result = ingest_source_line(conn, sid, lineno, stripped)
            except IngestError:
                raise
            counts[result.status if result.status == "idempotent_replay"
                   else result.category] += 1

    if finalize:
        finalize_session(conn, sid, str(p))

    return {
        "session_id": sid,
        "rollout_path": str(p),
        "lines_processed": total,
        "categories": counts,
        "finalized": finalize,
    }
