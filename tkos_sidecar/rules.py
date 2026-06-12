"""TKOS write-path rule dispatch.

Implements the RULES_SPEC v0.3.2 §2.1 supported subset only:
fix_attempted, validation_pending, validation_complete, pipeline_running,
pipeline_failed, user_approval_pending, and report_ready.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass


VALIDATION_TOOLS = {
    "pytest", "npm_test", "cargo_test", "go_test", "jest", "mocha",
    "lint", "typecheck", "mypy", "tsc", "eslint", "rubocop",
    "build", "make", "cargo_build", "go_build",
}

VALIDATION_COMMAND_PATTERNS = [
    re.compile(r"^pytest\b"),
    re.compile(r"^npm (run )?test\b"),
    re.compile(r"^cargo test\b"),
    re.compile(r"^go test\b"),
    re.compile(r"^npx jest\b"),
    re.compile(r"^mypy\b"),
    re.compile(r"^npx tsc\b"),
    re.compile(r"^eslint\b"),
    re.compile(r"^npm (run )?build\b"),
    re.compile(r"^make\b"),
    re.compile(r"^cargo build\b"),
    re.compile(r"^go build\b"),
]

EDIT_TOOLS = {"write_file", "edit_file", "apply_patch"}
APPROVAL_REQUEST_PATTERNS = [
    re.compile(r"should I (proceed|continue|deploy|commit|push|run|delete|drop)", re.I),
    re.compile(r"can I (proceed|continue|deploy|commit|push|run|delete|drop)", re.I),
    re.compile(r"are you ok with", re.I),
    re.compile(r"do you want me to", re.I),
    re.compile(r"shall I", re.I),
    re.compile(r"awaiting (your )?approval", re.I),
]
APPROVAL_GRANT_PATTERNS = [
    re.compile(r"^(yes|sure|go ahead|approved|proceed|do it|ok|okay)\b", re.I),
    re.compile(r"\bsounds good\b", re.I),
    re.compile(r"\bplease (do|proceed|continue)\b", re.I),
]
APPROVAL_DENY_PATTERNS = [
    re.compile(r"^(no|stop|hold on|wait|don't|do not|cancel)\b", re.I),
    re.compile(r"\b(reject|denied|refuse)\b", re.I),
]
REPORT_PATH_PATTERNS = [
    re.compile(r"report\.html$"),
    re.compile(r"report\.pdf$"),
    re.compile(r"report\.md$"),
    re.compile(r"REPORT[_\-].*\.md$"),
    re.compile(r"/reports/"),
    re.compile(r"summary\.(md|html|pdf)$"),
]


@dataclass(frozen=True)
class RuleEvent:
    event_id: int
    source_event_id: str
    session_id: str
    turn_idx: int
    event_type: str
    tool_name: str | None = None
    command: str | None = None
    exit_code: int | None = None
    parent_event_id: str | None = None
    output: str | None = None
    stderr_first_line: str | None = None
    content: str | None = None
    paths: tuple[str, ...] = ()


class RuleApplicationError(Exception):
    """Wraps a rule exception with the rule name for durable failure logging."""

    def __init__(self, rule_name: str, original: Exception):
        super().__init__(str(original))
        self.rule_name = rule_name
        self.original = original


def dispatch(conn: sqlite3.Connection, event: RuleEvent) -> list[str]:
    """Run applicable rules inside the caller's open transaction."""
    fired: list[str] = []
    for rule_name, fn in _rules_for(event):
        try:
            if fn(conn, event):
                fired.append(rule_name)
        except Exception as exc:  # pragma: no cover - exercised by integration failures
            raise RuleApplicationError(rule_name, exc) from exc

    if event.event_type == "tool_result" and event.exit_code not in (None, 0):
        # pipeline_failed born/strengthened share a trigger and have mutually
        # exclusive preconditions. Decide once against pre-event active state;
        # evaluating born and then strengthened independently would let the
        # strengthened rule observe the belief just minted by born.
        signature = failure_signature(event)
        match = _active_pipeline_failed_match(conn, event.session_id, signature)
        rule_name, fn = (
            ("pipeline_failed_strengthened", pipeline_failed_strengthened)
            if match is not None
            else ("pipeline_failed_born", pipeline_failed_born)
        )
        try:
            if not fn(conn, event, signature=signature, belief_id=match):
                raise RuntimeError(
                    f"mutual-exclusion winner {rule_name} did not fire"
                )
            fired.append(rule_name)
        except Exception as exc:
            raise RuleApplicationError(rule_name, exc) from exc
    return fired


def dispatch_turn_boundary(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    current_turn: int,
    trigger_event_id: int,
) -> list[str]:
    """Run rules whose trigger is turn-boundary advancement, not event_type."""
    try:
        count = pipeline_running_born_retroactive(
            conn,
            session_id=session_id,
            current_turn=current_turn,
            trigger_event_id=trigger_event_id,
        )
    except Exception as exc:
        raise RuleApplicationError("pipeline_running_born_retroactive", exc) from exc
    return ["pipeline_running_born_retroactive"] if count else []


def _rules_for(event: RuleEvent):
    if event.event_type == "tool_call":
        yield "validation_pending_born", validation_pending_born
        # Supersede first so it cannot retire the new belief minted below.
        yield "fix_attempted_superseded", fix_attempted_superseded
        yield "fix_attempted_born_from_edit", fix_attempted_born_from_edit
    elif event.event_type == "tool_result":
        yield "validation_pending_retired_by_success", validation_pending_retired_by_success
        yield "validation_pending_contradicted_by_failure", validation_pending_contradicted_by_failure
        yield "validation_complete_born", validation_complete_born
        yield "fix_attempted_retired_by_validation", fix_attempted_retired_by_validation
        yield "report_ready_born", report_ready_born
        yield "report_ready_retired_by_replacement", report_ready_retired_by_replacement
    elif event.event_type == "assistant_message":
        yield "user_approval_pending_born", user_approval_pending_born
    elif event.event_type == "user_message":
        yield "user_approval_pending_retired_by_approval", user_approval_pending_retired_by_approval
        yield "user_approval_pending_contradicted_by_denial", user_approval_pending_contradicted_by_denial


def is_validation_call(tool_name: str | None, command: str | None) -> bool:
    if tool_name in VALIDATION_TOOLS:
        return True
    command = command or ""
    return any(pattern.search(command) for pattern in VALIDATION_COMMAND_PATTERNS)


def failure_signature(event: RuleEvent) -> str:
    """Derive RULES_SPEC v0.3.2 §3.5.1's intentionally simple signature."""
    if event.exit_code is None:
        raise ValueError("failure_signature requires an exit_code")
    detail = _first_nonempty_line(event.stderr_first_line)
    if detail is None:
        detail = _first_nonempty_line(event.output)
    return f"{event.exit_code}:{detail or ''}"


def pipeline_running_born_retroactive(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    current_turn: int,
    trigger_event_id: int,
) -> int:
    """Retro-mint pipeline_running after K=3 subsequent turns.

    This is intentionally not part of event_type dispatch. It runs only when
    ingest advances to the first mapped event of a new turn.
    """
    candidates = conn.execute(
        """
        SELECT E.event_id, E.source_event_id, E.turn, E.tool_name, E.command
        FROM events E
        LEFT JOIN events R
          ON R.session_id = E.session_id
         AND R.event_type = 'tool_result'
         AND R.call_id = E.call_id
         AND R.turn <= ?
        WHERE E.session_id = ?
          AND E.event_type = 'tool_call'
          AND E.turn <= ?
          AND R.event_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM belief_instances B
              WHERE B.belief_type = 'pipeline_running'
                AND B.created_by_event_id = E.event_id
          )
        ORDER BY E.turn ASC, E.event_idx ASC, E.event_id ASC
        """,
        (current_turn - 1, session_id, current_turn - 3),
    ).fetchall()

    for event_id, source_event_id, effective_turn, tool_name, command in candidates:
        claim = (
            f"pipeline_running — {tool_name or ''} {command or ''} "
            f"from turn {effective_turn} (observed at turn {current_turn})"
        )
        belief_id = _belief_id(session_id, "pipeline_running", source_event_id)
        conn.execute(
            """
            INSERT INTO belief_instances
                (belief_id, session_id, belief_type, claim, created_turn, created_by_event_id)
            VALUES (?, ?, 'pipeline_running', ?, ?, ?)
            """,
            (belief_id, session_id, claim, effective_turn, event_id),
        )
        conn.execute(
            """
            INSERT INTO belief_events
                (belief_id, event_id, kind, at_turn, effective_turn, authority, note)
            VALUES (?, ?, 'born', ?, ?, 'asserted_by_assistant', ?)
            """,
            (
                belief_id,
                trigger_event_id,
                current_turn,
                effective_turn,
                claim,
            ),
        )
    return len(candidates)


def validation_pending_born(conn: sqlite3.Connection, event: RuleEvent) -> bool:
    if not is_validation_call(event.tool_name, event.command):
        return False

    claim = (
        f"validation pending — {event.tool_name or ''} "
        f"{event.command or ''} initiated at turn {event.turn_idx}"
    )
    belief_id = _belief_id(
        event.session_id,
        "validation_pending",
        event.source_event_id,
    )

    conn.execute(
        """
        INSERT INTO belief_instances
            (belief_id, session_id, belief_type, claim, created_turn, created_by_event_id)
        VALUES (?, ?, 'validation_pending', ?, ?, ?)
        """,
        (belief_id, event.session_id, claim, event.turn_idx, event.event_id),
    )
    conn.execute(
        """
        INSERT INTO belief_events
            (belief_id, event_id, kind, at_turn, effective_turn, authority, note)
        VALUES (?, ?, 'born', ?, ?, 'asserted_by_assistant', ?)
        """,
        (
            belief_id,
            event.event_id,
            event.turn_idx,
            event.turn_idx,
            claim,
        ),
    )
    return True


def validation_pending_retired_by_success(conn: sqlite3.Connection, event: RuleEvent) -> bool:
    if event.exit_code != 0:
        return False

    matches = _active_validation_pending_matches(conn, event)
    fired = False
    for belief_id in matches:
        note = f"validation pending retired — succeeded at turn {event.turn_idx}"
        conn.execute(
            """
            INSERT INTO belief_events
                (belief_id, event_id, kind, at_turn, effective_turn, authority, note)
            VALUES (?, ?, 'retired', ?, ?, 'confirmed_by_tool', ?)
            """,
            (
                belief_id,
                event.event_id,
                event.turn_idx,
                event.turn_idx,
                note,
            ),
        )
        fired = True
    return fired


def validation_pending_contradicted_by_failure(
    conn: sqlite3.Connection,
    event: RuleEvent,
) -> bool:
    if event.exit_code is None or event.exit_code == 0:
        return False

    matches = _active_validation_pending_matches(conn, event)
    fired = False
    for belief_id in matches:
        note = f"validation pending contradicted — failed at turn {event.turn_idx}"
        conn.execute(
            """
            INSERT INTO belief_events
                (belief_id, event_id, kind, at_turn, effective_turn, authority, note)
            VALUES (?, ?, 'contradicted', ?, ?, 'confirmed_by_tool', ?)
            """,
            (
                belief_id,
                event.event_id,
                event.turn_idx,
                event.turn_idx,
                note,
            ),
        )
        fired = True
    return fired


def validation_complete_born(conn: sqlite3.Connection, event: RuleEvent) -> bool:
    if event.exit_code != 0:
        return False

    parent = _matching_validation_parent(conn, event)
    if parent is None:
        return False

    parent_source_event_id, tool_name, command, parent_turn = parent
    claim = (
        f"validation complete — {tool_name or ''} {command or ''} "
        f"from turn {parent_turn}"
    )
    note = (
        f"validation complete — {tool_name or ''} {command or ''} "
        f"passed at turn {event.turn_idx}"
    )
    belief_id = _belief_id(
        event.session_id,
        "validation_complete",
        event.source_event_id,
    )

    conn.execute(
        """
        INSERT INTO belief_instances
            (belief_id, session_id, belief_type, claim, created_turn, created_by_event_id)
        VALUES (?, ?, 'validation_complete', ?, ?, ?)
        """,
        (belief_id, event.session_id, claim, event.turn_idx, event.event_id),
    )
    conn.execute(
        """
        INSERT INTO belief_events
            (belief_id, event_id, kind, at_turn, effective_turn, authority, note)
        VALUES (?, ?, 'born', ?, ?, 'confirmed_by_tool', ?)
        """,
        (
            belief_id,
            event.event_id,
            event.turn_idx,
            event.turn_idx,
            note,
        ),
    )
    return True


def pipeline_failed_born(
    conn: sqlite3.Connection,
    event: RuleEvent,
    *,
    signature: str | None = None,
    belief_id: str | None = None,
) -> bool:
    if event.exit_code is None or event.exit_code == 0:
        return False
    signature = signature or failure_signature(event)
    if belief_id is not None or _active_pipeline_failed_match(
        conn, event.session_id, signature
    ) is not None:
        return False

    note = (
        f"pipeline_failed — {event.tool_name or ''} exit {event.exit_code} "
        f"signature '{signature}' at turn {event.turn_idx}"
    )
    belief_id = _belief_id(event.session_id, "pipeline_failed", event.source_event_id)
    conn.execute(
        """
        INSERT INTO belief_instances
            (belief_id, session_id, belief_type, claim, created_turn, created_by_event_id)
        VALUES (?, ?, 'pipeline_failed', ?, ?, ?)
        """,
        (belief_id, event.session_id, note, event.turn_idx, event.event_id),
    )
    conn.execute(
        """
        INSERT INTO belief_events
            (belief_id, event_id, kind, at_turn, effective_turn, authority, note)
        VALUES (?, ?, 'born', ?, ?, 'confirmed_by_tool', ?)
        """,
        (belief_id, event.event_id, event.turn_idx, event.turn_idx, note),
    )
    return True


def pipeline_failed_strengthened(
    conn: sqlite3.Connection,
    event: RuleEvent,
    *,
    signature: str | None = None,
    belief_id: str | None = None,
) -> bool:
    if event.exit_code is None or event.exit_code == 0:
        return False
    signature = signature or failure_signature(event)
    belief_id = belief_id or _active_pipeline_failed_match(
        conn, event.session_id, signature
    )
    if belief_id is None:
        return False

    note = f"pipeline_failed refreshed — same signature recurred at turn {event.turn_idx}"
    conn.execute(
        """
        INSERT INTO belief_events
            (belief_id, event_id, kind, at_turn, effective_turn, authority, note)
        VALUES (?, ?, 'refreshed', ?, ?, 'confirmed_by_tool', ?)
        """,
        (belief_id, event.event_id, event.turn_idx, event.turn_idx, note),
    )
    return True


def user_approval_pending_born(conn: sqlite3.Connection, event: RuleEvent) -> bool:
    match = _first_pattern_match(event.content, APPROVAL_REQUEST_PATTERNS)
    if match is None:
        return False
    excerpt = match.group(0)
    note = f"user_approval_pending — '{excerpt}' at turn {event.turn_idx}"
    _mint_belief(
        conn, event, "user_approval_pending", note, "asserted_by_assistant"
    )
    return True


def user_approval_pending_retired_by_approval(
    conn: sqlite3.Connection, event: RuleEvent
) -> bool:
    if _first_pattern_match(event.content, APPROVAL_GRANT_PATTERNS) is None:
        return False
    return _transition_all_active(
        conn,
        event,
        "user_approval_pending",
        "retired",
        "confirmed_by_user",
        f"user_approval_pending retired — approved at turn {event.turn_idx}",
    )


def user_approval_pending_contradicted_by_denial(
    conn: sqlite3.Connection, event: RuleEvent
) -> bool:
    if _first_pattern_match(event.content, APPROVAL_DENY_PATTERNS) is None:
        return False
    return _transition_all_active(
        conn,
        event,
        "user_approval_pending",
        "contradicted",
        "confirmed_by_user",
        f"user_approval_pending contradicted — denied at turn {event.turn_idx}",
    )


def report_ready_born(conn: sqlite3.Connection, event: RuleEvent) -> bool:
    if event.exit_code != 0 or event.tool_name not in EDIT_TOOLS:
        return False
    path = next(
        (path for path in event.paths if any(pattern.search(path) for pattern in REPORT_PATH_PATTERNS)),
        None,
    )
    if path is None:
        return False
    note = f"report_ready — {path} produced at turn {event.turn_idx} (exit 0)"
    _mint_belief(conn, event, "report_ready", note, "confirmed_by_tool")
    return True


def report_ready_retired_by_replacement(
    conn: sqlite3.Connection, event: RuleEvent
) -> bool:
    new_report = conn.execute(
        """
        SELECT belief_id, claim
        FROM belief_instances
        WHERE session_id=? AND belief_type='report_ready' AND created_by_event_id=?
        """,
        (event.session_id, event.event_id),
    ).fetchone()
    if new_report is None:
        return False
    new_belief_id, claim = new_report
    path = claim.removeprefix("report_ready — ").split(" produced at turn ", 1)[0]
    matches = [
        belief_id
        for belief_id, old_claim in _active_beliefs(conn, event.session_id, "report_ready")
        if belief_id != new_belief_id
        and old_claim.startswith(f"report_ready — {path} produced at turn ")
    ]
    return _transition_beliefs(
        conn,
        event,
        matches,
        "retired",
        "confirmed_by_tool",
        f"report_ready replaced by newer write at turn {event.turn_idx}",
    )


def fix_attempted_born_from_edit(conn: sqlite3.Connection, event: RuleEvent) -> bool:
    if event.tool_name not in EDIT_TOOLS or not event.paths:
        return False
    context = _most_recent_active_context(conn, event.session_id)
    if context is None:
        return False
    paths = json.dumps(list(event.paths), separators=(",", ":"))
    note = f"fix attempted via {event.tool_name} on {paths} at turn {event.turn_idx}"
    claim = f"{note}; context: {context}"
    _mint_belief(
        conn, event, "fix_attempted", claim, "asserted_by_assistant", note=note
    )
    return True


def fix_attempted_retired_by_validation(
    conn: sqlite3.Connection, event: RuleEvent
) -> bool:
    if event.exit_code != 0 or not is_validation_call(event.tool_name, event.command):
        return False
    matches = []
    for belief_id, claim in _active_beliefs(conn, event.session_id, "fix_attempted"):
        fix_paths = _fix_paths(claim)
        if not event.paths or any(
            _paths_overlap(fix_path, validation_path)
            for fix_path in fix_paths
            for validation_path in event.paths
        ):
            matches.append(belief_id)
    return _transition_beliefs(
        conn,
        event,
        matches,
        "retired",
        "confirmed_by_tool",
        f"fix attempt validated at turn {event.turn_idx}",
    )


def fix_attempted_superseded(conn: sqlite3.Connection, event: RuleEvent) -> bool:
    if event.tool_name not in EDIT_TOOLS or not event.paths:
        return False
    matches = []
    for belief_id, claim in _active_beliefs(conn, event.session_id, "fix_attempted"):
        if any(
            _paths_overlap(old_path, new_path)
            for old_path in _fix_paths(claim)
            for new_path in event.paths
        ):
            matches.append(belief_id)
    return _transition_beliefs(
        conn,
        event,
        matches,
        "retired",
        "asserted_by_assistant",
        f"fix attempt superseded by new edit at turn {event.turn_idx}",
    )


def _mint_belief(
    conn: sqlite3.Connection,
    event: RuleEvent,
    belief_type: str,
    claim: str,
    authority: str,
    *,
    note: str | None = None,
) -> str:
    belief_id = _belief_id(event.session_id, belief_type, event.source_event_id)
    conn.execute(
        """
        INSERT INTO belief_instances
            (belief_id, session_id, belief_type, claim, created_turn, created_by_event_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (belief_id, event.session_id, belief_type, claim, event.turn_idx, event.event_id),
    )
    conn.execute(
        """
        INSERT INTO belief_events
            (belief_id, event_id, kind, at_turn, effective_turn, authority, note)
        VALUES (?, ?, 'born', ?, ?, ?, ?)
        """,
        (belief_id, event.event_id, event.turn_idx, event.turn_idx, authority, note or claim),
    )
    return belief_id


def _transition_all_active(
    conn: sqlite3.Connection,
    event: RuleEvent,
    belief_type: str,
    kind: str,
    authority: str,
    note: str,
) -> bool:
    return _transition_beliefs(
        conn,
        event,
        [belief_id for belief_id, _claim in _active_beliefs(conn, event.session_id, belief_type)],
        kind,
        authority,
        note,
    )


def _transition_beliefs(
    conn: sqlite3.Connection,
    event: RuleEvent,
    belief_ids: list[str],
    kind: str,
    authority: str,
    note: str,
) -> bool:
    for belief_id in belief_ids:
        conn.execute(
            """
            INSERT INTO belief_events
                (belief_id, event_id, kind, at_turn, effective_turn, authority, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (belief_id, event.event_id, kind, event.turn_idx, event.turn_idx, authority, note),
        )
    return bool(belief_ids)


def _active_beliefs(
    conn: sqlite3.Connection, session_id: str, belief_type: str
) -> list[tuple[str, str]]:
    return conn.execute(
        """
        SELECT B.belief_id, B.claim
        FROM belief_instances B
        JOIN belief_events E ON E.belief_id=B.belief_id
        WHERE B.session_id=? AND B.belief_type=?
          AND E.belief_event_id=(
              SELECT E2.belief_event_id FROM belief_events E2
              WHERE E2.belief_id=B.belief_id
              ORDER BY E2.at_turn DESC, E2.belief_event_id DESC LIMIT 1
          )
          AND E.kind IN ('born', 'refreshed', 'confirmed', 'weakened')
        ORDER BY E.at_turn DESC, E.belief_event_id DESC
        """,
        (session_id, belief_type),
    ).fetchall()


def _most_recent_active_context(conn: sqlite3.Connection, session_id: str) -> str | None:
    candidates = []
    for belief_type in ("pipeline_failed", "validation_pending", "validation_complete"):
        candidates.extend(_active_beliefs(conn, session_id, belief_type))
    if not candidates:
        return None
    ids = {belief_id for belief_id, _claim in candidates}
    placeholders = ",".join("?" for _ in ids)
    row = conn.execute(
        f"""
        SELECT B.claim
        FROM belief_instances B JOIN belief_events E ON E.belief_id=B.belief_id
        WHERE B.belief_id IN ({placeholders})
        ORDER BY E.at_turn DESC, E.belief_event_id DESC LIMIT 1
        """,
        tuple(ids),
    ).fetchone()
    return row[0] if row else None


def _fix_paths(claim: str) -> tuple[str, ...]:
    match = re.search(r" on (\[.*?\]) at turn ", claim)
    if match is None:
        return ()
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError:
        return ()
    return tuple(path for path in value if isinstance(path, str))


def _paths_overlap(left: str, right: str) -> bool:
    left = left.rstrip("/")
    right = right.rstrip("/")
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def _first_pattern_match(
    content: str | None, patterns: list[re.Pattern]
) -> re.Match | None:
    for pattern in patterns:
        match = pattern.search(content or "")
        if match is not None:
            return match
    return None


def _matching_validation_parent(
    conn: sqlite3.Connection,
    event: RuleEvent,
) -> tuple[str, str | None, str | None, int] | None:
    if event.parent_event_id:
        parent = conn.execute(
            """
            SELECT source_event_id, tool_name, command, turn
            FROM events
            WHERE session_id=? AND event_type='tool_call' AND source_event_id=?
            """,
            (event.session_id, event.parent_event_id),
        ).fetchone()
        if parent is not None and is_validation_call(parent[1], parent[2]):
            return parent
        return None

    if not event.tool_name and not event.command:
        return None

    parent = conn.execute(
        """
        SELECT source_event_id, tool_name, command, turn
        FROM events
        WHERE session_id=? AND event_type='tool_call'
          AND tool_name=? AND command=?
        ORDER BY event_id DESC
        LIMIT 1
        """,
        (event.session_id, event.tool_name, event.command),
    ).fetchone()
    if parent is not None and is_validation_call(parent[1], parent[2]):
        return parent
    return None


def _active_validation_pending_matches(
    conn: sqlite3.Connection,
    event: RuleEvent,
) -> list[str]:
    params: list[object] = [event.session_id]
    where = []

    if event.parent_event_id:
        where.append("C.source_event_id = ?")
        params.append(event.parent_event_id)
    elif event.tool_name or event.command:
        where.append("(C.tool_name = ? AND C.command = ?)")
        params.extend([event.tool_name, event.command])

    if not where:
        return []

    sql = f"""
        SELECT B.belief_id
        FROM belief_instances B
        JOIN events C ON C.event_id = B.created_by_event_id
        JOIN belief_events E ON E.belief_id = B.belief_id
        WHERE B.session_id = ?
          AND B.belief_type = 'validation_pending'
          AND ({' OR '.join(where)})
          AND E.belief_event_id = (
              SELECT E2.belief_event_id
              FROM belief_events E2
              WHERE E2.belief_id = B.belief_id
              ORDER BY E2.at_turn DESC, E2.belief_event_id DESC
              LIMIT 1
          )
          AND E.kind IN ('born', 'refreshed', 'confirmed', 'weakened')
        ORDER BY B.created_turn ASC, B.belief_id ASC
    """
    return [row[0] for row in conn.execute(sql, params).fetchall()]


def _active_pipeline_failed_match(
    conn: sqlite3.Connection,
    session_id: str,
    signature: str,
) -> str | None:
    claim_fragment = f"signature '{signature}'"
    row = conn.execute(
        """
        SELECT B.belief_id
        FROM belief_instances B
        JOIN belief_events E ON E.belief_id = B.belief_id
        WHERE B.session_id = ?
          AND B.belief_type = 'pipeline_failed'
          AND instr(B.claim, ?) > 0
          AND E.belief_event_id = (
              SELECT E2.belief_event_id
              FROM belief_events E2
              WHERE E2.belief_id = B.belief_id
              ORDER BY E2.at_turn DESC, E2.belief_event_id DESC
              LIMIT 1
          )
          AND E.kind IN ('born', 'refreshed', 'confirmed', 'weakened')
        ORDER BY B.created_turn ASC, B.belief_id ASC
        LIMIT 1
        """,
        (session_id, claim_fragment),
    ).fetchone()
    return row[0] if row is not None else None


def _first_nonempty_line(value: str | None) -> str | None:
    for line in (value or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _belief_id(session_id: str, belief_type: str, source_event_id: str) -> str:
    raw = f"{session_id}\n{belief_type}\n{source_event_id}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"belief:{belief_type}:{digest}"
