"""TKOS-002 read-path slice v0.1.

Implements the smallest end-to-end demonstration of belief observability:

  - SQLite DDL for the shared belief-state substrate (5 tables).
  - One hand-written fixture: a 12-turn coding-assistant session with 8 beliefs.
  - One CLI command: `tkos state <session_id> --turn T`.

State at turn T is reconstructed by replaying `belief_events` ordered by
`at_turn`. There is no per-turn snapshot table; the audit trail is the
source of truth.

Per `TKOS-002_IMPLEMENTATION_SLICE_v0.1.md`. Read-path only — no event
ingestion, no rule engine, no overlay ranking, no agent integration.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).parent / "tkos.db"

AUTH_RANK = {
    "asserted_by_assistant": 1,
    "confirmed_by_user":     2,
    "confirmed_by_tool":     3,
}

AUTH_ABBR = {
    "asserted_by_assistant": "assistant",
    "confirmed_by_user":     "user",
    "confirmed_by_tool":     "tool",
}

# Each belief_events.kind maps to the lifecycle state the belief is in
# immediately AFTER that event.
KIND_TO_STATE = {
    "born":         "active",
    "refreshed":    "active",
    "confirmed":    "active",
    "weakened":     "contradicted",
    "contradicted": "contradicted",
    "superseded":   "retired",
    "retired":      "retired",
}

WARRANT_KINDS = ("born", "refreshed", "confirmed")

# OB-002 §3.1 tier 1 — active blockers (highest within-pool priority)
ACTIVE_BLOCKER_TYPES = frozenset({
    "action_blocked",
    "validation_pending",
    "pipeline_failed",
    "pipeline_running",
    "user_approval_pending",
})

# K=20 raw-log window per OB-002 §3.0 (the recent-log window that
# System A already sees; overlay's distinctive value is carrying state
# whose evidence has scrolled past this window).
K_DEFAULT = 20


# ─── DDL ────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS events (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT    NOT NULL,
    turn           INTEGER NOT NULL,
    event_type     TEXT    NOT NULL,
    timestamp      TEXT    NOT NULL,
    payload_json   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_session_turn ON events(session_id, turn);

CREATE TABLE IF NOT EXISTS belief_instances (
    belief_id            TEXT    PRIMARY KEY,
    session_id           TEXT    NOT NULL,
    belief_type          TEXT    NOT NULL,
    claim                TEXT    NOT NULL,
    created_turn         INTEGER NOT NULL,
    created_by_event_id  INTEGER REFERENCES events(event_id)
);
CREATE INDEX IF NOT EXISTS idx_bi_session ON belief_instances(session_id);

CREATE TABLE IF NOT EXISTS belief_events (
    belief_event_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    belief_id        TEXT    NOT NULL REFERENCES belief_instances(belief_id),
    event_id         INTEGER REFERENCES events(event_id),
    kind             TEXT    NOT NULL,
    at_turn          INTEGER NOT NULL,
    authority        TEXT    NOT NULL,
    note             TEXT
);
CREATE INDEX IF NOT EXISTS idx_be_belief ON belief_events(belief_id);
CREATE INDEX IF NOT EXISTS idx_be_turn   ON belief_events(at_turn);

CREATE TABLE IF NOT EXISTS action_checks (
    check_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id                TEXT    NOT NULL,
    at_turn                   INTEGER NOT NULL,
    action                    TEXT    NOT NULL,
    blocker_belief_ids_json   TEXT    NOT NULL,
    rationale                 TEXT    NOT NULL,
    timestamp                 TEXT    NOT NULL
);
"""


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    conn.commit()


# ─── Fixture: demo-session ──────────────────────────────────────────────

DEMO_SESSION_ID = "demo-session"

# (belief_id, belief_type, claim, created_turn)
DEMO_BELIEF_INSTANCES = [
    ("b_001", "fix_attempted",       "patch applied to module_x at turn 3",     3),
    ("b_002", "validation_pending",  "pytest invoked, awaiting result",         4),
    ("b_003", "action_blocked",      "deploy blocked until validation_complete", 4),
    ("b_004", "pipeline_failed",     "pytest exit 1 at turn 5",                 5),
    ("b_005", "fix_attempted",       "patch applied to module_x at turn 7",     7),
    ("b_006", "validation_pending",  "pytest invoked, awaiting result",         8),
    ("b_007", "validation_complete", "pytest exit 0 at turn 9",                 9),
    ("b_008", "report_ready",        "deploy artifact written at turn 11",     11),
]

# (belief_id, kind, at_turn, authority, note)
DEMO_BELIEF_EVENTS = [
    # b_001 fix_attempted #1 → superseded by b_005 at turn 7
    ("b_001", "born",         3,  "asserted_by_assistant", "initial patch"),
    ("b_001", "superseded",   7,  "asserted_by_assistant", "superseded by b_005"),

    # b_002 validation_pending #1 → contradicted then retired by tool at turn 5
    ("b_002", "born",         4,  "asserted_by_assistant", "pytest invoked"),
    ("b_002", "contradicted", 5,  "confirmed_by_tool",     "pytest exit 1"),
    ("b_002", "retired",      5,  "confirmed_by_tool",     "validation failed"),

    # b_003 action_blocked → retired once validation_complete at turn 9
    ("b_003", "born",         4,  "asserted_by_assistant", "validation precondition"),
    ("b_003", "retired",      9,  "confirmed_by_tool",     "validation_complete cleared block"),

    # b_004 pipeline_failed → retired once subsequent run passes at turn 9
    ("b_004", "born",         5,  "confirmed_by_tool",     "pytest exit 1"),
    ("b_004", "retired",      9,  "confirmed_by_tool",     "later run passed"),

    # b_005 fix_attempted #2 → still active at turn 12
    ("b_005", "born",         7,  "asserted_by_assistant", "second patch attempt"),

    # b_006 validation_pending #2 → confirmed then retired at turn 9
    ("b_006", "born",         8,  "asserted_by_assistant", "pytest invoked"),
    ("b_006", "confirmed",    9,  "confirmed_by_tool",     "pytest exit 0"),
    ("b_006", "retired",      9,  "confirmed_by_tool",     "validation_complete reached"),

    # b_007 validation_complete → active at turn 12
    ("b_007", "born",         9,  "confirmed_by_tool",     "pytest exit 0"),

    # b_008 report_ready → active at turn 12
    ("b_008", "born",        11,  "confirmed_by_tool",     "deploy artifact written"),
]


def load_demo_fixture(conn: sqlite3.Connection, session_id: str = DEMO_SESSION_ID) -> bool:
    """Insert demo session rows directly into the substrate. Idempotent."""
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM belief_instances WHERE session_id = ? LIMIT 1",
        (session_id,),
    )
    if cur.fetchone():
        return False

    for belief_id, btype, claim, created_turn in DEMO_BELIEF_INSTANCES:
        cur.execute(
            "INSERT INTO belief_instances "
            "(belief_id, session_id, belief_type, claim, created_turn, created_by_event_id) "
            "VALUES (?, ?, ?, ?, ?, NULL)",
            (belief_id, session_id, btype, claim, created_turn),
        )
    for belief_id, kind, at_turn, authority, note in DEMO_BELIEF_EVENTS:
        cur.execute(
            "INSERT INTO belief_events "
            "(belief_id, event_id, kind, at_turn, authority, note) "
            "VALUES (?, NULL, ?, ?, ?, ?)",
            (belief_id, kind, at_turn, authority, note),
        )
    conn.commit()
    return True


def _belief_events_has_effective_turn(conn: sqlite3.Connection) -> bool:
    cur = conn.execute("PRAGMA table_info(belief_events)")
    return any(row[1] == "effective_turn" for row in cur.fetchall())


# ─── State reconstruction (the load-bearing read-path query) ────────────

def reconstruct_state(
    conn: sqlite3.Connection,
    session_id: str,
    turn: int,
    include_retired: bool = False,
) -> tuple[list[dict], dict[str, int]]:
    """Reconstruct active belief set as of turn T by replaying belief_events.

    The view `active_beliefs` (latest-turn only) is intentionally NOT used
    here. Turn-T queries must replay the audit trail, not read a snapshot.
    """
    cur = conn.cursor()
    has_effective_turn = _belief_events_has_effective_turn(conn)
    turn_expr = "COALESCE(effective_turn, at_turn)" if has_effective_turn else "at_turn"
    cur.execute(
        "SELECT belief_id, belief_type, claim, created_turn "
        "FROM belief_instances "
        "WHERE session_id = ? AND created_turn <= ? "
        "ORDER BY created_turn ASC, belief_id ASC",
        (session_id, turn),
    )
    rows = cur.fetchall()

    beliefs: list[dict] = []
    counts = {"active": 0, "retired": 0, "contradicted": 0}

    for belief_id, btype, claim, created_turn in rows:
        # Latest lifecycle event with effective_turn <= T determines current state.
        cur.execute(
            f"SELECT kind, at_turn, {turn_expr} FROM belief_events "
            f"WHERE belief_id = ? AND {turn_expr} <= ? "
            f"ORDER BY {turn_expr} DESC, at_turn DESC, belief_event_id DESC LIMIT 1",
            (belief_id, turn),
        )
        last = cur.fetchone()
        if last is None:
            continue
        last_kind, observed_at_turn, effective_turn = last
        state = KIND_TO_STATE[last_kind]
        counts[state] = counts.get(state, 0) + 1

        if state != "active" and not include_retired:
            continue

        cur.execute(
            f"SELECT {turn_expr} FROM belief_events "
            f"WHERE belief_id = ? AND {turn_expr} <= ? "
            "AND kind IN ('born','refreshed','confirmed') "
            f"ORDER BY {turn_expr} ASC, at_turn ASC, belief_event_id ASC",
            (belief_id, turn),
        )
        warrant_turns = [r[0] for r in cur.fetchall()]

        cur.execute(
            "SELECT authority FROM belief_events "
            f"WHERE belief_id = ? AND {turn_expr} <= ?",
            (belief_id, turn),
        )
        observed_auths = [r[0] for r in cur.fetchall()]
        authority = (
            max(observed_auths, key=lambda a: AUTH_RANK[a])
            if observed_auths
            else "asserted_by_assistant"
        )

        beliefs.append({
            "belief_id":          belief_id,
            "belief_type":        btype,
            "claim":              claim,
            "state":              state,
            "authority":          authority,
            "warrant_turns":      warrant_turns,
            "last_updated_turn":  observed_at_turn,
            "observed_at_turn":   observed_at_turn,
            "effective_turn":     effective_turn,
            "created_turn":       created_turn,
        })

    # Synthetic action_blocked (read-path migration §1.4, fixes 6 + 4 + VI).
    # Computed at query time from currently-active blocker beliefs. Carries a
    # deterministic string belief_id so overlay sort tie-breaking stays
    # type-safe. Counts toward counts["active"].
    synthetic = _compute_action_blocked(beliefs, session_id=session_id, query_turn=turn)
    if synthetic is not None:
        beliefs.append(synthetic)
        counts["active"] = counts.get("active", 0) + 1

    return beliefs, counts


# Read-path migration §1.4 / fix VI: synthetic action_blocked.
# Returns a single belief dict whose belief_id is a deterministic string
# (never None — prevents TypeError on None vs str sort comparisons).
_BLOCKER_TYPES = ("validation_pending", "user_approval_pending", "pipeline_failed")


def _compute_action_blocked(persisted: list[dict], session_id: str, query_turn: int) -> dict | None:
    blockers = [
        b for b in persisted
        if b.get("belief_type") in _BLOCKER_TYPES
        and b.get("state") in ("active", "weakened")
    ]
    if not blockers:
        return None

    highest_authority = max(
        (b["authority"] for b in blockers),
        key=lambda a: AUTH_RANK.get(a, 0),
    )

    warrant_turns: list[int] = []
    for b in blockers:
        wt = b.get("warrant_turns") or []
        if wt:
            warrant_turns.extend(wt)
        elif b.get("last_updated_turn") is not None:
            warrant_turns.append(b["last_updated_turn"])

    created = min((b.get("created_turn", query_turn) for b in blockers), default=query_turn)
    last_upd = max((b.get("last_updated_turn", query_turn) for b in blockers), default=query_turn)

    return {
        "belief_id":         f"synthetic:action_blocked:{session_id}:{query_turn}",
        "belief_type":       "action_blocked",
        "claim":             "action_blocked — " + ", ".join(b["belief_type"] for b in blockers),
        "state":             "active",
        "authority":         highest_authority,
        "warrant_turns":     warrant_turns,
        "last_updated_turn": last_upd,
        "created_turn":      created,
        "is_synthetic":      True,
    }


# ─── Overlay: AI-facing surface (peer to state) ─────────────────────────

def approx_tokens(text: str) -> int:
    """Approximate token count for the overlay budget.

    The OB-002 v0.2 production run will use the gpt-4o-2024-08-06
    tokenizer; this slice uses the standard 4-chars-per-token rule of
    thumb, which suffices for fixture-level budget behavior tests.
    """
    return max(1, (len(text) + 3) // 4)


def render_overlay_line(b: dict) -> str:
    """One compact line per belief, per OB-002 §3.5 serialization contract.

    Format:
      [lifecycle_state] belief_type :: claim_short (auth=authority, last=last_updated_turn)
    """
    claim_short = b["claim"][:80]
    return (
        f"[{b['state']}] {b['belief_type']} :: {claim_short} "
        f"(auth={AUTH_ABBR[b['authority']]}, last={b['last_updated_turn']})"
    )


def is_out_of_window(b: dict, current_turn: int, K: int) -> bool:
    """OB-002 §3.0: a belief is out-of-window iff both its birth and its
    most recent warrant-bearing event lie at at_turn <= (current_turn - K).
    """
    cutoff = current_turn - K
    born_turn = b["warrant_turns"][0] if b["warrant_turns"] else b["created_turn"]
    latest_warrant = b["warrant_turns"][-1] if b["warrant_turns"] else b["created_turn"]
    return born_turn <= cutoff and latest_warrant <= cutoff


def _tier(b: dict) -> int:
    """OB-002 §3.1 tier (lower = higher priority).

    The active-only beliefs from reconstruct_state never carry the
    'contradicted' lifecycle state, so tier 2 is unreachable here.
    Recently-updated (tier 3) is folded into the recency tiebreak in §3.4.
    """
    if b["belief_type"] in ACTIVE_BLOCKER_TYPES:
        return 1
    return 5  # default ("active beliefs over retired beliefs")


def rank_overlay_beliefs(
    beliefs: list[dict],
    *,
    current_turn: int,
    K: int = K_DEFAULT,
) -> list[dict]:
    """Rank active beliefs per OB-002 §3.0 (meta-rule) + §3.1 (tiers) + §3.4 (tiebreaks).

    Sort order:
      1. Out-of-window pool exhausted before in-window pool (§3.0).
      2. Within each pool: §3.1 priority tier (ascending).
      3. Within each tier: last_updated_turn descending.
      4. Then authority rank descending (tool > user > assistant).
      5. Then deterministic hash on belief_id.
    """
    return sorted(
        beliefs,
        key=lambda b: (
            0 if is_out_of_window(b, current_turn, K) else 1,
            _tier(b),
            -b["last_updated_turn"],
            -AUTH_RANK[b["authority"]],
            b["belief_id"],
        ),
    )


def build_overlay(
    conn: sqlite3.Connection,
    session_id: str,
    turn: int,
    budget_tokens: int,
    *,
    K: int = K_DEFAULT,
) -> tuple[str, dict]:
    """Build a compact, ranked, budgeted overlay over the same substrate
    that powers `state()`.

    Reads from belief_instances + belief_events via reconstruct_state.
    No model call. No rule engine.
    """
    beliefs, _ = reconstruct_state(conn, session_id, turn, include_retired=False)
    ranked = rank_overlay_beliefs(beliefs, current_turn=turn, K=K)

    # Reserve a worst-case header allowance up front so the body budget
    # is what's actually available for belief lines.
    placeholder_header = (
        f"# Operational belief overlay "
        f"(budget: {budget_tokens} tokens, used: 9999, omitted: 99, K={K})"
    )
    header_reserve = approx_tokens(placeholder_header) + 1  # +1 for newline
    body_budget = max(0, budget_tokens - header_reserve)

    admitted: list[dict] = []
    omitted: list[dict] = []
    body_used = 0

    for b in ranked:
        line_tokens = approx_tokens(render_overlay_line(b)) + 1  # +1 for newline
        if body_used + line_tokens <= body_budget:
            admitted.append(b)
            body_used += line_tokens
        else:
            omitted.append(b)

    omitted_by_type: dict[str, int] = {}
    for b in omitted:
        omitted_by_type[b["belief_type"]] = omitted_by_type.get(b["belief_type"], 0) + 1
    admitted_by_type: dict[str, int] = {}
    for b in admitted:
        admitted_by_type[b["belief_type"]] = admitted_by_type.get(b["belief_type"], 0) + 1

    header = (
        f"# Operational belief overlay "
        f"(budget: {budget_tokens} tokens, used: {body_used}, "
        f"omitted: {len(omitted)}, K={K})"
    )
    lines = [header] + [render_overlay_line(b) for b in admitted]

    # Add omitted-counts summary line only if it still fits under the
    # hard budget cap (per OB-002 §3.1 tier 6 — "only if budget allows").
    if omitted_by_type:
        omitted_line = "# omitted: " + ", ".join(
            f"{t}={n}" for t, n in sorted(omitted_by_type.items())
        )
        trial = "\n".join(lines + [omitted_line])
        if approx_tokens(trial) <= budget_tokens:
            lines.append(omitted_line)

    rendered = "\n".join(lines)

    meta = {
        "budget_tokens":   budget_tokens,
        "tokens_used":     approx_tokens(rendered),
        "admitted_count":  len(admitted),
        "omitted_count":   len(omitted),
        "admitted_by_type": admitted_by_type,
        "omitted_by_type":  omitted_by_type,
        "K":               K,
        "tokenizer":       "approx_chars_div_4",
    }
    return rendered, meta


# ─── Rendering ──────────────────────────────────────────────────────────

CLAIM_MAX = 50

def render_tabular(
    beliefs: list[dict],
    counts: dict[str, int],
    session_id: str,
    turn: int,
) -> str:
    lines = [f"session: {session_id}   turn: {turn}", ""]

    if beliefs:
        types  = [b["belief_type"] for b in beliefs]
        claims = [(b["claim"][:CLAIM_MAX]) for b in beliefs]
        type_w  = max(len("BELIEF_TYPE"), max(len(t) for t in types))
        claim_w = max(len("CLAIM"),       max(len(c) for c in claims))
        state_w = max(len("STATE"),       max(len(b["state"]) for b in beliefs))
        auth_w  = max(len("AUTH"),        max(len(AUTH_ABBR[b["authority"]]) for b in beliefs))

        lines.append(
            f"{'BELIEF_TYPE':<{type_w}}  {'CLAIM':<{claim_w}}  "
            f"{'STATE':<{state_w}}  {'AUTH':<{auth_w}}  WARRANT      LAST_UPDATED"
        )
        for b in beliefs:
            warrant_str = "[" + ",".join(str(t) for t in b["warrant_turns"]) + "]"
            lines.append(
                f"{b['belief_type']:<{type_w}}  "
                f"{b['claim'][:CLAIM_MAX]:<{claim_w}}  "
                f"{b['state']:<{state_w}}  "
                f"{AUTH_ABBR[b['authority']]:<{auth_w}}  "
                f"{warrant_str:<12} {b['last_updated_turn']}"
            )
    else:
        lines.append("  (no beliefs matching filter)")

    lines.append("")
    lines.append(
        f"  {counts.get('active',0)} active   |   "
        f"{counts.get('retired',0)} retired (use --include-retired)   |   "
        f"{counts.get('contradicted',0)} contradicted"
    )
    return "\n".join(lines)


def render_json(
    beliefs: list[dict],
    counts: dict[str, int],
    session_id: str,
    turn: int,
) -> str:
    return json.dumps({
        "session_id": session_id,
        "turn":       turn,
        "active":     beliefs,
        "counts":     counts,
    }, indent=2)


# ─── CLI ────────────────────────────────────────────────────────────────

def cmd_overlay(args: argparse.Namespace) -> None:
    conn = sqlite3.connect(args.db)
    init_db(conn)
    load_demo_fixture(conn)

    rendered, meta = build_overlay(
        conn, args.session_id, args.turn, args.budget, K=args.K,
    )

    if args.json:
        print(json.dumps({
            "session_id": args.session_id,
            "turn":       args.turn,
            "rendered":   rendered,
            "meta":       meta,
        }, indent=2))
    else:
        print(rendered)
        print()
        print(
            f"# meta: {meta['tokens_used']}/{meta['budget_tokens']} tokens · "
            f"{meta['admitted_count']} admitted · {meta['omitted_count']} omitted · "
            f"K={meta['K']}"
        )

    conn.close()


def cmd_state(args: argparse.Namespace) -> None:
    conn = sqlite3.connect(args.db)
    init_db(conn)
    load_demo_fixture(conn)

    beliefs, counts = reconstruct_state(
        conn, args.session_id, args.turn, include_retired=args.include_retired
    )

    out = render_json(beliefs, counts, args.session_id, args.turn) \
        if args.json else render_tabular(beliefs, counts, args.session_id, args.turn)
    print(out)

    conn.close()


def cmd_capture(args: argparse.Namespace) -> None:
    """Capture a Codex rollout JSONL into the sidecar substrate."""
    from ingest import init_extended_db
    from trace_adapter_codex import ingest_rollout

    conn = sqlite3.connect(args.db)
    init_db(conn)
    init_extended_db(conn)

    summary = ingest_rollout(
        conn, args.rollout_path,
        session_id=args.session_id,
        finalize=not args.no_finalize,
    )

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"session_id: {summary['session_id']}")
        print(f"rollout:    {summary['rollout_path']}")
        print(f"lines:      {summary['lines_processed']}")
        print(f"categories: {summary['categories']}")
        print(f"finalized:  {summary['finalized']}")

    conn.close()


def cmd_verify(args: argparse.Namespace) -> None:
    """Run the §6.2 five-check completeness validation on a captured session."""
    from ingest import init_extended_db
    from verify_export import verify_session

    conn = sqlite3.connect(args.db)
    init_db(conn)
    init_extended_db(conn)

    result = verify_session(conn, args.session_id)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"session_id: {result.session_id}")
        print(f"verdict:    {'PASS' if result.passed else 'FAIL'}")
        for check in result.checks:
            mark = "✓" if check["ok"] else "✗"
            print(f"  {mark} {check['check']}: {check['detail']}")

    conn.close()
    if not result.passed:
        sys.exit(1)


def cmd_export(args: argparse.Namespace) -> None:
    """Produce the deterministic JSONL export per §10 Q6 (substrate artifact)."""
    from ingest import init_extended_db
    from verify_export import export_session

    conn = sqlite3.connect(args.db)
    init_db(conn)
    init_extended_db(conn)

    out = export_session(conn, args.session_id)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"exported {len(out.splitlines())} events to {args.out}")
    else:
        sys.stdout.write(out)

    conn.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tkos",
        description=(
            "TKOS write-path sidecar v0.3 — "
            "capture / verify / export Codex rollouts as belief-state substrate."
        ),
    )
    p.add_argument("--db", default=str(DEFAULT_DB_PATH),
                   help=f"SQLite store path (default: {DEFAULT_DB_PATH})")

    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("state", help="Show active beliefs at a given turn.")
    sp.add_argument("session_id")
    sp.add_argument("--turn", type=int, required=True,
                    help="Turn anchor (required; integer >= 1)")
    sp.add_argument("--include-retired", action="store_true",
                    help="Also show retired and contradicted beliefs")
    sp.add_argument("--json", action="store_true",
                    help="Emit JSON instead of tabular text")
    sp.set_defaults(func=cmd_state)

    op = sub.add_parser(
        "overlay",
        help="Render compact, ranked, budgeted overlay (AI-facing surface).",
    )
    op.add_argument("session_id")
    op.add_argument("--turn", type=int, required=True,
                    help="Turn anchor (required; integer >= 1)")
    op.add_argument("--budget", type=int, default=1000,
                    help="Token budget for the overlay (default: 1000)")
    op.add_argument("--K", type=int, default=K_DEFAULT,
                    help=f"Raw-log window size for out-of-window meta-rule "
                         f"(default: {K_DEFAULT}; per OB-002 §3.0)")
    op.add_argument("--json", action="store_true",
                    help="Emit JSON envelope with rendered overlay + metadata")
    op.set_defaults(func=cmd_overlay)

    cp = sub.add_parser(
        "capture",
        help="Ingest a Codex rollout JSONL into the sidecar substrate.",
    )
    cp.add_argument("rollout_path",
                    help="Path to the rollout JSONL "
                         "(typically ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl)")
    cp.add_argument("--session-id",
                    help="Explicit session_id (default: derive from session_meta header)")
    cp.add_argument("--no-finalize", action="store_true",
                    help="Skip finalize_session() at end (use for live-mode partial ingest)")
    cp.add_argument("--json", action="store_true",
                    help="Emit JSON summary instead of human-readable text")
    cp.set_defaults(func=cmd_capture)

    vp = sub.add_parser(
        "verify",
        help="Run §6.2 five-check completeness validation on a captured session.",
    )
    vp.add_argument("session_id")
    vp.add_argument("--json", action="store_true",
                    help="Emit JSON result instead of human-readable text")
    vp.set_defaults(func=cmd_verify)

    ep = sub.add_parser(
        "export",
        help="Produce deterministic JSONL substrate artifact for a captured session.",
    )
    ep.add_argument("session_id")
    ep.add_argument("--out",
                    help="Write export to file (default: stdout)")
    ep.set_defaults(func=cmd_export)

    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
