"""TKOS write-path ingestion and initial rule dispatch.

Implements the five behaviors locked in Sue's 2026-06-06 directive:

    1. Raw-line HTTP envelope: ingest_source_line() takes (session_id,
       source_line_number, raw_line). The HTTP layer is a thin wrapper that
       parses JSON {session_id, source_line_number, raw_line} and calls in.
    2. Session initialization / finalized rejection.
    3. Read-path compatibility — see tkos.py reconstruct_state contract.
    4. Non-shell tool-result success/failure: explicit success marker required;
       otherwise outcome=unknown and no report_ready (rules are stubs in Step 1).
    5. Ordered source-line ingestion — non-contiguous source_line_number raises.

Belief derivation is limited to the RULES_SPEC v0.3.2 §2.1 supported subset.
No v0.4c2-admissible trace capture.
The audit-trail rationale for each choice lives in the v0.3.3 spec docs.
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import sqlite3
import time
from dataclasses import dataclass

from rules import RuleApplicationError, RuleEvent, dispatch, dispatch_turn_boundary


# ─── DDL extensions (additive to tkos.py's existing schema) ─────────────

DDL_EXTENSIONS = """
-- v0.3.4 events column additions (per write-path scope §8.1 fix 1)
-- SQLite ALTER TABLE rejects NOT NULL UNIQUE in one step, so columns are
-- nullable; non-null is enforced at the application layer in ingest_source_line.
-- These are guarded so re-init is idempotent.

-- raw_lines: every line of every rollout, regardless of category
CREATE TABLE IF NOT EXISTS raw_lines (
    raw_line_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id         TEXT    NOT NULL,
    source_line_number INTEGER NOT NULL,
    raw_line_bytes     BLOB    NOT NULL,
    raw_line_sha256    TEXT    NOT NULL,
    category           TEXT    NOT NULL,    -- mapped | ignored-known | unrecognized
    flag               TEXT,                 -- reason for unrecognized
    turn_idx           INTEGER NOT NULL DEFAULT -1,
    event_idx          INTEGER,              -- non-null only for mapped (per fix C)
    event_id           INTEGER,              -- FK to events.event_id for mapped
    UNIQUE(session_id, source_line_number)
);

-- session_status: per-session capture metadata + finalization marks
CREATE TABLE IF NOT EXISTS session_status (
    session_id              TEXT PRIMARY KEY,
    source_rollout_path     TEXT,
    raw_rollout_sha256      TEXT,                -- nullable until finalize_session
    line_hash_chain         TEXT,                -- updated per ingest
    total_line_count        INTEGER,             -- nullable until finalize_session
    capture_started_at      TEXT NOT NULL,
    capture_ended_at        TEXT,                -- nullable until finalize_session
    capture_started_at_turn INTEGER NOT NULL DEFAULT 0,
    admissibility_eligible  INTEGER NOT NULL DEFAULT 1,
    failure_reasons         TEXT
);

-- ingest_log: per-line audit of ingest activity (committed/rolled_back)
CREATE TABLE IF NOT EXISTS ingest_log (
    ingest_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_event_id    TEXT,
    session_id         TEXT NOT NULL,
    source_line_number INTEGER NOT NULL,
    category           TEXT NOT NULL,
    received_at        TEXT NOT NULL,
    transaction_status TEXT NOT NULL    -- committed | idempotent_replay | rolled_back
);

-- rule_failures: out-of-transaction audit of rule exceptions (Step 1: stub; no
-- rules fire here, but the table exists so Step 2+ can use it without DDL churn)
CREATE TABLE IF NOT EXISTS rule_failures (
    failure_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id        TEXT NOT NULL,
    source_event_id   TEXT NOT NULL,
    rule_name         TEXT NOT NULL,
    exception_class   TEXT NOT NULL,
    exception_message TEXT,
    logged_at         TEXT NOT NULL
);
"""


# Best-effort additive columns on events. SQLite ALTER TABLE ADD COLUMN cannot
# add NOT NULL UNIQUE in one step (per audit finding 1); we add nullable then
# enforce at the application layer.
EVENTS_ADD_COLUMNS = [
    "ALTER TABLE events ADD COLUMN source_event_id TEXT",
    "ALTER TABLE events ADD COLUMN event_idx INTEGER",
    "ALTER TABLE events ADD COLUMN source_rollout_path TEXT",
    "ALTER TABLE events ADD COLUMN source_line_number INTEGER",
    "ALTER TABLE events ADD COLUMN turn_id TEXT",
    "ALTER TABLE events ADD COLUMN call_id TEXT",
    "ALTER TABLE events ADD COLUMN parent_event_id TEXT",
    "ALTER TABLE events ADD COLUMN tool_name TEXT",
    "ALTER TABLE events ADD COLUMN command TEXT",
    "ALTER TABLE events ADD COLUMN exit_code INTEGER",
    "ALTER TABLE events ADD COLUMN outcome_status TEXT",
    "ALTER TABLE events ADD COLUMN content TEXT",
    "ALTER TABLE events ADD COLUMN paths_json TEXT",
]

BELIEF_EVENTS_ADD_COLUMNS = [
    "ALTER TABLE belief_events ADD COLUMN effective_turn INTEGER",
]

INGEST_LOG_ADD_COLUMNS = [
    "ALTER TABLE ingest_log ADD COLUMN rules_fired TEXT",
]

EVENTS_ADD_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_source_event_id ON events(source_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_session_turn_event ON events(session_id, turn, event_idx)",
]


def init_extended_db(conn: sqlite3.Connection) -> None:
    """Idempotent DDL setup. Safe to call repeatedly."""
    conn.executescript(DDL_EXTENSIONS)
    for stmt in EVENTS_ADD_COLUMNS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists
    for stmt in BELIEF_EVENTS_ADD_COLUMNS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists
    for stmt in INGEST_LOG_ADD_COLUMNS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists
    for stmt in EVENTS_ADD_INDEXES:
        conn.execute(stmt)
    conn.commit()


# ─── Exception types ────────────────────────────────────────────────────


class IngestError(Exception):
    """Base class for ingest-layer errors."""


class SessionAlreadyFinalizedError(IngestError):
    """ingest_source_line was called on a session whose capture_ended_at is set."""


class OutOfOrderError(IngestError):
    """source_line_number was not prev_max_for_session + 1."""


class SourceMutationError(IngestError):
    """An existing raw_lines row exists with a different raw_line_sha256."""


class RuleDispatchError(IngestError):
    """Rule dispatch failed after event persistence inside the ingest transaction."""

    def __init__(self, rule_name: str, original: Exception):
        super().__init__(str(original))
        self.rule_name = rule_name
        self.original = original


# ─── Helpers: hashing, classification, outcome inference ────────────────


def compute_source_event_id(session_id: str, source_line_number: int, raw_line_bytes: bytes) -> str:
    """Machine-stable hash per v0.3.1 fix 6.

    Inputs:
      session_id || \\n || str(source_line_number) || \\n || sha256(raw_line_bytes)

    Absolute paths are deliberately excluded so the same rollout produces the
    same id across machines.
    """
    line_sha = hashlib.sha256(raw_line_bytes).hexdigest()
    payload = f"{session_id}\n{source_line_number}\n{line_sha}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# Codex ignored-known taxonomy (per scope §4.1 fix 2)
IGNORED_KNOWN_TOP_TYPES = frozenset({
    "session_meta",
    "turn_context",
    # v0.3.3+ (extended from real-data capture 2026-06-08):
    "compacted",          # Codex internal context-compaction marker
})
IGNORED_KNOWN_EVENT_MSG_SUBTYPES = frozenset({
    "token_count",
    "agent_message",      # duplicate of response_item(payload.type=message)
    # v0.3.3+ (extended from real-data capture 2026-06-08):
    "patch_apply_end",    # redundant with function_call_output for apply_patch
    "context_compacted",  # Codex internal context-management notification
})
IGNORED_KNOWN_RESPONSE_ITEM_ROLES = frozenset({"user", "developer"})

# Codex mapped taxonomy
MAPPED_EVENT_MSG_TO_EVENT_TYPE = {
    "user_message":   "user_message",
    "task_started":   "task_start",
    "task_complete":  "task_completion",
}
MAPPED_RESPONSE_ITEM_TO_EVENT_TYPE = {
    "function_call":            "tool_call",
    "function_call_output":     "tool_result",
    "reasoning":                "assistant_reasoning",
    # v0.3.3+ (extended from real-data capture 2026-06-08):
    "custom_tool_call":         "tool_call",    # Codex custom-tool envelope, same shape as function_call
    "custom_tool_call_output":  "tool_result",  # Codex custom-tool result, same shape as function_call_output
    # "message" with role=assistant maps; user/developer are ignored-known above
}


@dataclass(frozen=True)
class Classification:
    category: str  # "mapped" | "ignored-known" | "unrecognized"
    event_type: str | None  # set iff category=="mapped"
    flag: str | None  # set iff category=="unrecognized"
    turn_id: str | None  # the Codex turn_id if present anywhere on this line


def _extract_turn_id(parsed: dict) -> str | None:
    """Codex carries turn_id in event_msg.payload.turn_id and turn_context.payload.turn_id.
    Lines without their own turn_id inherit the most recent prior turn_id at the
    adapter level; see ingest_source_line for adjacency-inheritance handling.
    """
    payload = parsed.get("payload") or {}
    if isinstance(payload, dict):
        tid = payload.get("turn_id")
        if isinstance(tid, str):
            return tid
    return None


def classify_line(raw_line: str) -> Classification:
    """Classify a single rollout JSONL line per v0.3.3 §4.1.

    Raises json.JSONDecodeError if the line isn't valid JSON.
    """
    parsed = json.loads(raw_line)
    if not isinstance(parsed, dict):
        return Classification(category="unrecognized", event_type=None,
                              flag="not_a_json_object", turn_id=None)

    top_type = parsed.get("type")
    payload = parsed.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    sub_type = payload.get("type") if isinstance(payload, dict) else None
    turn_id = _extract_turn_id(parsed)

    # Top-level ignored-known
    if top_type in IGNORED_KNOWN_TOP_TYPES:
        return Classification(category="ignored-known", event_type=None,
                              flag=None, turn_id=turn_id)

    # event_msg dispatch
    if top_type == "event_msg":
        if sub_type in IGNORED_KNOWN_EVENT_MSG_SUBTYPES:
            return Classification(category="ignored-known", event_type=None,
                                  flag=None, turn_id=turn_id)
        if sub_type in MAPPED_EVENT_MSG_TO_EVENT_TYPE:
            return Classification(
                category="mapped",
                event_type=MAPPED_EVENT_MSG_TO_EVENT_TYPE[sub_type],
                flag=None,
                turn_id=turn_id,
            )
        return Classification(category="unrecognized", event_type=None,
                              flag=f"event_msg:{sub_type}", turn_id=turn_id)

    # response_item dispatch
    if top_type == "response_item":
        if sub_type == "message":
            role = payload.get("role")
            if role == "assistant":
                return Classification(category="mapped",
                                      event_type="assistant_message",
                                      flag=None, turn_id=turn_id)
            if role in IGNORED_KNOWN_RESPONSE_ITEM_ROLES:
                return Classification(category="ignored-known", event_type=None,
                                      flag=None, turn_id=turn_id)
            return Classification(category="unrecognized", event_type=None,
                                  flag=f"response_item:message:role={role}",
                                  turn_id=turn_id)
        if sub_type in MAPPED_RESPONSE_ITEM_TO_EVENT_TYPE:
            return Classification(
                category="mapped",
                event_type=MAPPED_RESPONSE_ITEM_TO_EVENT_TYPE[sub_type],
                flag=None, turn_id=turn_id,
            )
        return Classification(category="unrecognized", event_type=None,
                              flag=f"response_item:{sub_type}", turn_id=turn_id)

    return Classification(category="unrecognized", event_type=None,
                          flag=f"top_type:{top_type}", turn_id=turn_id)


# Tool-outcome inference (Fix δ from audit 5):
# Shell exec_command tool_results have "Process exited with code N" in output.
# Non-shell tool_results need explicit success markers; otherwise unknown.

_SHELL_EXIT_RE = re.compile(r"Process exited with code (\d+)", re.MULTILINE)

# Explicit success markers for non-shell tools (intentionally conservative).
# Failed apply_patch typically does NOT produce these.
_NONSHELL_SUCCESS_MARKERS = (
    "Patch applied",
    "Successfully applied",
    "Wrote file",
    "Created file",
    "Updated file",
    "Done.",
)


def classify_tool_outcome(tool_name: str, output: str) -> str:
    """Return "success" | "failure" | "unknown" for a tool_result.

    Shell tools (exec_command): parse exit code from "Process exited with code N".
    Non-shell tools: success only when an explicit marker is present in output;
    otherwise unknown. This prevents Fix V's report_ready_born from firing on
    failed apply_patch calls that lack the shell exit marker.

    TODO(post-Step-1): richer apply_patch parsing — Codex's actual apply_patch
    response grammar should be inspected and codified rather than relying on
    string markers.
    """
    m = _SHELL_EXIT_RE.search(output or "")
    if m:
        return "success" if int(m.group(1)) == 0 else "failure"

    if tool_name == "exec_command":
        # Shell tool but no exit marker — output may be truncated; play it safe.
        return "unknown"

    # Non-shell: explicit success markers only.
    for marker in _NONSHELL_SUCCESS_MARKERS:
        if marker in (output or ""):
            return "success"
    return "unknown"


def _exit_code_from_output(output: str) -> int | None:
    m = _SHELL_EXIT_RE.search(output or "")
    return int(m.group(1)) if m else None


def _stderr_first_line(output: str) -> str | None:
    """Apply the locked Codex adapter's conservative stderr heuristic."""
    for line in (output or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(
            ("Output:", "Chunk ID", "Process exited")
        ):
            continue
        if any(
            marker in stripped.lower()
            for marker in ("error:", "traceback", "exception:", "stderr:")
        ):
            return stripped
    return None


def _normalize_event_fields(
    conn: sqlite3.Connection,
    session_id: str,
    event_type: str,
    payload_json: str,
) -> dict:
    """Derive the canonical fields needed by the §3.2 validation rules."""
    parsed = json.loads(payload_json)
    payload = parsed.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}

    fields = {
        "call_id": None,
        "parent_event_id": None,
        "tool_name": None,
        "command": None,
        "exit_code": None,
        "outcome_status": None,
        "output": None,
        "stderr_first_line": None,
        "content": None,
        "paths": (),
    }

    if event_type in {"assistant_message", "user_message"}:
        fields["content"] = _message_content(payload)
        return fields

    if event_type == "tool_call":
        fields["call_id"] = payload.get("call_id")
        source_tool_name = payload.get("name")
        arguments = payload.get("arguments") or "{}"
        try:
            arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
        except json.JSONDecodeError:
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}

        if source_tool_name == "exec_command":
            command = arguments.get("cmd") or ""
            try:
                tokens = shlex.split(command)
            except ValueError:
                tokens = command.split()
            fields["tool_name"] = tokens[0] if tokens else "exec_command"
            fields["command"] = command
        else:
            fields["tool_name"] = source_tool_name
            fields["command"] = ""
        fields["paths"] = _tool_call_paths(source_tool_name, arguments)
        return fields

    if event_type == "tool_result":
        fields["call_id"] = payload.get("call_id")
        parent = conn.execute(
            """
            SELECT source_event_id, tool_name, command, paths_json
            FROM events
            WHERE session_id = ? AND call_id = ?
            ORDER BY event_id DESC
            LIMIT 1
            """,
            (session_id, fields["call_id"]),
        ).fetchone()
        if parent is not None:
            fields["parent_event_id"], fields["tool_name"], fields["command"], paths_json = parent
            fields["paths"] = tuple(json.loads(paths_json or "[]"))

        output = payload.get("output") or ""
        fields["output"] = output
        fields["stderr_first_line"] = _stderr_first_line(output)
        fields["outcome_status"] = classify_tool_outcome(fields["tool_name"] or "", output)
        fields["exit_code"] = _exit_code_from_output(output)
        if fields["exit_code"] is None and fields["outcome_status"] == "success":
            fields["exit_code"] = 0
        return fields

    return fields


def _message_content(payload: dict) -> str:
    content = payload.get("message", payload.get("content", ""))
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            text = item.get("text") or item.get("content")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _tool_call_paths(tool_name: str | None, arguments: dict) -> tuple[str, ...]:
    paths: list[str] = []
    for key in ("path", "file_path"):
        value = arguments.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    value = arguments.get("paths")
    if isinstance(value, list):
        paths.extend(path for path in value if isinstance(path, str) and path)

    if tool_name == "apply_patch":
        patch = arguments.get("input") or arguments.get("patch") or ""
        if isinstance(patch, str):
            for match in re.finditer(
                r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$",
                patch,
                re.MULTILINE,
            ):
                paths.append(match.group(1).strip())
    return tuple(dict.fromkeys(paths))


# ─── Core: ingest_source_line ───────────────────────────────────────────


@dataclass
class IngestResult:
    status: str           # "committed" | "idempotent_replay"
    category: str         # "mapped" | "ignored-known" | "unrecognized"
    source_event_id: str
    event_type: str | None
    turn_idx: int


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _ensure_session_row(conn: sqlite3.Connection, session_id: str) -> dict:
    """INSERT OR IGNORE the session_status row (fix β). Returns the current row
    after the INSERT, with capture_ended_at indicating finalization state.
    """
    conn.execute(
        """
        INSERT OR IGNORE INTO session_status
            (session_id, capture_started_at, line_hash_chain)
        VALUES (?, ?, '')
        """,
        (session_id, _now_iso()),
    )
    cur = conn.execute(
        "SELECT capture_ended_at, line_hash_chain FROM session_status WHERE session_id=?",
        (session_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise IngestError(f"session_status row missing after INSERT OR IGNORE for {session_id}")
    return {"capture_ended_at": row[0], "line_hash_chain": row[1] or ""}


def _max_source_line_number(conn: sqlite3.Connection, session_id: str) -> int:
    cur = conn.execute(
        "SELECT COALESCE(MAX(source_line_number), 0) FROM raw_lines WHERE session_id=?",
        (session_id,),
    )
    return cur.fetchone()[0]


def _existing_raw_line(conn: sqlite3.Connection, session_id: str, source_line_number: int):
    cur = conn.execute(
        "SELECT raw_line_sha256, category, event_id FROM raw_lines "
        "WHERE session_id=? AND source_line_number=?",
        (session_id, source_line_number),
    )
    return cur.fetchone()


def _next_event_idx_for_turn(conn: sqlite3.Connection, session_id: str, turn_idx: int) -> int:
    cur = conn.execute(
        "SELECT COALESCE(MAX(event_idx), -1) + 1 FROM events "
        "WHERE session_id=? AND turn=?",
        (session_id, turn_idx),
    )
    return cur.fetchone()[0]


def _max_turn_idx(conn: sqlite3.Connection, session_id: str) -> int:
    cur = conn.execute(
        "SELECT COALESCE(MAX(turn), -1) FROM events WHERE session_id=?",
        (session_id,),
    )
    return cur.fetchone()[0]


def _resolve_turn(
    conn: sqlite3.Connection,
    session_id: str,
    classification: Classification,
) -> tuple[int, str | None]:
    """Map Codex turn_id → monotonic per-session turn_idx (fix 7).

    Lines without turn_id inherit the most recent prior turn_id (adjacency
    inheritance). If no prior turn_id has been observed and this line lacks one,
    turn_idx = -1 (the line will not become an event regardless of category;
    only ignored-known lines should reach this path).
    """
    if classification.turn_id is None:
        # Inherit from the most recent prior mapped event for this session, if any
        cur = conn.execute(
            "SELECT turn, turn_id FROM events WHERE session_id=? "
            "ORDER BY event_id DESC LIMIT 1",
            (session_id,),
        )
        prev = cur.fetchone()
        return (prev[0], prev[1]) if prev else (-1, None)

    # Has a turn_id; map it to an integer.
    cur = conn.execute(
        "SELECT turn FROM events WHERE session_id=? "
        "AND turn_id=? "
        "ORDER BY event_id LIMIT 1",
        (session_id, classification.turn_id),
    )
    existing = cur.fetchone()
    if existing:
        return existing[0], classification.turn_id
    # New turn_id — assign the next int.
    cur = conn.execute(
        "SELECT COALESCE(MAX(turn), -1) + 1 FROM events WHERE session_id=?",
        (session_id,),
    )
    return cur.fetchone()[0], classification.turn_id


def ingest_source_line(
    conn: sqlite3.Connection,
    session_id: str,
    source_line_number: int,
    raw_line: str,
) -> IngestResult:
    """Atomic ingest of one raw rollout JSONL line.

    Order of operations (per scope v0.3.3 §6.1 + v0.3.4 fixes α, β, γ):

      0. Session-status init: INSERT OR IGNORE the session row (fix β).
      1. Finalized-rejection: if session_status.capture_ended_at IS NOT NULL,
         raise SessionAlreadyFinalizedError (fix β).
      2. Replay-idempotency: if (session_id, source_line_number) already
         exists in raw_lines with matching hash → no-op return; mismatch →
         SourceMutationError.
      3. Ordered-delivery: source_line_number must equal prev_max + 1; otherwise
         OutOfOrderError (fix γ).
      4. Classify the line into Mapped / Ignored-known / Unrecognized.
      5. Insert raw_lines row.
      6. Extend line_hash_chain in same transaction (fix III).
      7. If Mapped: insert events row, derive event_idx (mapped-only sequence,
         per fix C), attach to raw_lines.event_id.
      8. If Unrecognized: flip session_status.admissibility_eligible = 0.
      9. Append ingest_log.

    All inside one transaction, including applicable rule-derived belief writes.
    """
    raw_line_bytes = raw_line.encode("utf-8")
    source_event_id = compute_source_event_id(session_id, source_line_number, raw_line_bytes)
    raw_line_sha = hashlib.sha256(raw_line_bytes).hexdigest()
    rule_failure: RuleDispatchError | None = None

    # Serialize the finalized, replay, ordering, and write checks together.
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Step 0: session init
        session_row = _ensure_session_row(conn, session_id)

        # Step 1: finalized rejection. Once finalized, every ingest call is
        # rejected, including a replay of an existing line.
        if session_row["capture_ended_at"] is not None:
            raise SessionAlreadyFinalizedError(
                f"session {session_id} was finalized at {session_row['capture_ended_at']}; "
                f"cannot ingest source_line_number={source_line_number}"
            )

        # Step 2: replay-idempotency check
        existing = _existing_raw_line(conn, session_id, source_line_number)
        if existing is not None:
            existing_sha, existing_category, _existing_event_id = existing
            if existing_sha == raw_line_sha:
                conn.rollback()
                return IngestResult(
                    status="idempotent_replay",
                    category=existing_category,
                    source_event_id=source_event_id,
                    event_type=None,
                    turn_idx=-1,
                )
            raise SourceMutationError(
                f"raw_lines row at ({session_id}, {source_line_number}) exists with "
                f"hash {existing_sha[:12]}…; incoming hash {raw_line_sha[:12]}… differs."
            )

        # Step 3: ordered delivery
        prev_max = _max_source_line_number(conn, session_id)
        expected = prev_max + 1
        if source_line_number != expected:
            raise OutOfOrderError(
                f"session {session_id}: expected source_line_number={expected}, "
                f"got {source_line_number}"
            )

        # Step 4: classify
        try:
            classification = classify_line(raw_line)
        except json.JSONDecodeError as exc:
            classification = Classification(
                category="unrecognized", event_type=None,
                flag=f"json_decode_error:{exc.msg}", turn_id=None,
            )

        # Step 4a (mapped only): resolve turn_idx
        turn_idx = -1
        event_idx = None
        new_event_id = None
        resolved_turn_id = None
        prior_max_turn = _max_turn_idx(conn, session_id)
        if classification.category == "mapped":
            turn_idx, resolved_turn_id = _resolve_turn(conn, session_id, classification)
        elif classification.turn_id is not None:
            # Ignored-known lines with a turn_id (e.g., turn_context) get tagged
            # with the inherited turn_idx for grouping, but don't consume event_idx.
            turn_idx, resolved_turn_id = _resolve_turn(conn, session_id, classification)

        # Step 5: insert raw_lines
        conn.execute(
            """
            INSERT INTO raw_lines
                (session_id, source_line_number, raw_line_bytes, raw_line_sha256,
                 category, flag, turn_idx, event_idx, event_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, source_line_number, raw_line_bytes, raw_line_sha,
             classification.category, classification.flag, turn_idx,
             event_idx, new_event_id),
        )

        # Step 6: extend line_hash_chain in same transaction
        prev_chain = session_row["line_hash_chain"] or ""
        new_chain = hashlib.sha256(prev_chain.encode("utf-8") + raw_line_bytes).hexdigest()
        conn.execute(
            "UPDATE session_status SET line_hash_chain=? WHERE session_id=?",
            (new_chain, session_id),
        )

        # Step 7: mapped → insert event
        rules_fired: list[str] = []
        if classification.category == "mapped":
            event_idx = _next_event_idx_for_turn(conn, session_id, turn_idx)
            timestamp = json.loads(raw_line).get("timestamp") or _now_iso()
            payload_json = raw_line
            normalized = _normalize_event_fields(
                conn,
                session_id,
                classification.event_type,
                payload_json,
            )
            cur = conn.execute(
                """
                INSERT INTO events
                    (session_id, turn, event_type, timestamp, payload_json,
                     source_event_id, event_idx, source_line_number, turn_id, call_id,
                     parent_event_id, tool_name, command, exit_code, outcome_status,
                     content, paths_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, turn_idx, classification.event_type, timestamp,
                 payload_json, source_event_id, event_idx, source_line_number,
                 resolved_turn_id,
                 normalized["call_id"], normalized["parent_event_id"],
                 normalized["tool_name"], normalized["command"],
                 normalized["exit_code"], normalized["outcome_status"],
                 normalized["content"], json.dumps(normalized["paths"])),
            )
            new_event_id = cur.lastrowid
            conn.execute(
                "UPDATE raw_lines SET event_idx=?, event_id=? "
                "WHERE session_id=? AND source_line_number=?",
                (event_idx, new_event_id, session_id, source_line_number),
            )

            # Step 7b: rule dispatch. Event persistence and belief transitions
            # commit or roll back together.
            event = RuleEvent(
                event_id=new_event_id,
                source_event_id=source_event_id,
                session_id=session_id,
                turn_idx=turn_idx,
                event_type=classification.event_type,
                tool_name=normalized["tool_name"],
                command=normalized["command"],
                exit_code=normalized["exit_code"],
                parent_event_id=normalized["parent_event_id"],
                output=normalized["output"],
                stderr_first_line=normalized["stderr_first_line"],
                content=normalized["content"],
                paths=normalized["paths"],
            )
            try:
                if turn_idx > prior_max_turn:
                    rules_fired.extend(dispatch_turn_boundary(
                        conn,
                        session_id=session_id,
                        current_turn=turn_idx,
                        trigger_event_id=new_event_id,
                    ))
                rules_fired.extend(dispatch(conn, event))
            except RuleApplicationError as exc:
                rule_failure = RuleDispatchError(exc.rule_name, exc.original)
                raise rule_failure

        # Step 8: unrecognized → flip admissibility
        if classification.category == "unrecognized":
            conn.execute(
                """
                UPDATE session_status
                SET admissibility_eligible = 0,
                    failure_reasons = COALESCE(failure_reasons, '') ||
                        CASE WHEN failure_reasons IS NULL OR failure_reasons = ''
                             THEN ?
                             ELSE ',' || ? END
                WHERE session_id = ?
                """,
                (f"unrecognized_line:{source_line_number}",
                 f"unrecognized_line:{source_line_number}",
                 session_id),
            )

        # Step 9: ingest_log
        conn.execute(
            """
            INSERT INTO ingest_log
                (source_event_id, session_id, source_line_number, category,
                 received_at, transaction_status, rules_fired)
            VALUES (?, ?, ?, ?, ?, 'committed', ?)
            """,
            (source_event_id, session_id, source_line_number,
             classification.category, _now_iso(), json.dumps(rules_fired)),
        )

        conn.commit()
        return IngestResult(
            status="committed",
            category=classification.category,
            source_event_id=source_event_id,
            event_type=classification.event_type,
            turn_idx=turn_idx,
        )
    except Exception:
        conn.rollback()
        if rule_failure is not None:
            _log_rule_failure(
                conn,
                session_id=session_id,
                source_event_id=source_event_id,
                rule_name=rule_failure.rule_name,
                original=rule_failure.original,
            )
        raise


def _log_rule_failure(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    source_event_id: str,
    rule_name: str,
    original: Exception,
) -> None:
    """Persist a rule exception after the ingest transaction has rolled back."""
    conn.execute(
        """
        INSERT INTO rule_failures
            (session_id, source_event_id, rule_name, exception_class,
             exception_message, logged_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            source_event_id,
            rule_name,
            original.__class__.__name__,
            str(original),
            _now_iso(),
        ),
    )
    conn.commit()


def _derive_outcome_status(event_type: str | None, payload_json: str) -> str | None:
    """For tool_result events, derive success/failure/unknown per fix δ.

    For other event types, returns None.
    """
    if event_type != "tool_result":
        return None
    try:
        parsed = json.loads(payload_json)
    except json.JSONDecodeError:
        return "unknown"
    payload = parsed.get("payload") or {}
    output = payload.get("output", "") if isinstance(payload, dict) else ""
    # The tool_name lives on the parent function_call event in real Codex
    # rollouts; we can't resolve it here without a DB lookup. For Step 1's
    # outcome heuristic, look at the output text itself — if "Process exited"
    # is present, treat as shell-like; otherwise as non-shell.
    tool_name = "exec_command" if _SHELL_EXIT_RE.search(output) else "other"
    return classify_tool_outcome(tool_name, output)


# ─── finalize_session ──────────────────────────────────────────────────


def finalize_session(conn: sqlite3.Connection, session_id: str, rollout_path: str) -> None:
    """Per scope §6.1a — populate raw_rollout_sha256, total_line_count,
    capture_ended_at. Explicit-only in live mode; auto-called at the end of
    batch replay.
    """
    with open(rollout_path, "rb") as fh:
        rollout_bytes = fh.read()
    rollout_sha = hashlib.sha256(rollout_bytes).hexdigest()
    line_count = sum(1 for line in rollout_bytes.split(b"\n") if line.strip())

    conn.execute(
        """
        UPDATE session_status
        SET raw_rollout_sha256  = ?,
            total_line_count    = ?,
            capture_ended_at    = ?,
            source_rollout_path = ?
        WHERE session_id = ?
        """,
        (rollout_sha, line_count, _now_iso(), str(rollout_path), session_id),
    )
    conn.commit()


# ─── HTTP envelope handler (skeleton; thin wrapper around ingest_source_line) ──


def handle_ingest_envelope(conn: sqlite3.Connection, envelope: dict) -> IngestResult:
    """Step 1 fix α: HTTP body is the envelope:
        {"session_id": "...", "source_line_number": N, "raw_line": "..."}

    The HTTP server (whatever we use) parses JSON and calls this. No HTTP
    framework is required in Step 1 for tests — the tests call this directly.
    """
    if not isinstance(envelope, dict):
        raise IngestError("envelope must be a JSON object")

    required = ("session_id", "source_line_number", "raw_line")
    missing = [k for k in required if k not in envelope]
    if missing:
        raise IngestError(f"envelope missing required keys: {missing}")

    session_id = envelope["session_id"]
    source_line_number = envelope["source_line_number"]
    raw_line = envelope["raw_line"]
    if not isinstance(session_id, str) or not session_id:
        raise IngestError("envelope session_id must be a non-empty string")
    if (
        not isinstance(source_line_number, int)
        or isinstance(source_line_number, bool)
        or source_line_number < 1
    ):
        raise IngestError("envelope source_line_number must be a positive integer")
    if not isinstance(raw_line, str):
        raise IngestError("envelope raw_line must be a string")

    return ingest_source_line(
        conn,
        session_id=session_id,
        source_line_number=source_line_number,
        raw_line=raw_line,
    )
