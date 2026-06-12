#!/usr/bin/env python3
"""
F-023 Phase 1: parse Claude session JSONLs into a normalized representation.

Input:  ~/.claude/projects/<project>/ (5 main sessions)
        ~/.claude/projects/<project>/subagents/ (159 subagent traces)

Output: tkos_log_replay/data/sessions_normalized.jsonl
        tkos_log_replay/data/sessions_inventory.json

What this does NOT do (deferred to later phases):
- L1 region classification (data_fetch / pipeline_run / etc.) — Phase 1 step 4
- Warrant assignment (DecayingWarrant / InvariantWarrant) — Phase 2
- Replay / intervention catalog — Phase 3

The output of this script is a clean intermediate representation: one
record per (assistant or user) turn, with timestamps, text content,
tool calls, tool results, and threading metadata preserved. Phase 1
step 4 will read these records and add L1 region labels.

Methodology discipline (per F-023 backlog):
- Random sample, not failure-cherry-picking.
- This pass parses ALL sessions; sampling happens at a later phase
  with a documented seed.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field, asdict
from collections import Counter
from datetime import datetime
from typing import Iterable

CLAUDE_PROJECTS = pathlib.Path.home() / ".claude/projects/<project>"
# Subagent traces live under per-session subdirs:
# <CLAUDE_PROJECTS>/<session-id>/subagents/*.jsonl

OUT_DIR = pathlib.Path(__file__).resolve().parent / "data"
OUT_NORMALIZED = OUT_DIR / "sessions_normalized.jsonl"
OUT_INVENTORY = OUT_DIR / "sessions_inventory.json"

# Top-level JSONL entry types that carry assistant/user turns.
# Other types (queue-operation, attachment, file-history-snapshot,
# last-prompt, ai-title, system) are framework metadata and do not
# represent reasoning steps.
TURN_TYPES = {"assistant", "user"}


@dataclass
class ToolUse:
    name: str
    tool_use_id: str
    input_summary: str  # truncated stringified input (don't store full file contents)


@dataclass
class ToolResult:
    tool_use_id: str
    output_summary: str  # truncated stringified output
    is_error: bool


@dataclass
class Turn:
    """Normalized turn — one assistant or user message."""
    session_id: str
    turn_idx: int
    uuid: str
    parent_uuid: str | None
    timestamp: str  # ISO 8601
    role: str       # "user" | "assistant"
    text: str       # concatenated text blocks
    thinking: str   # concatenated thinking blocks (assistant only)
    tool_uses: list[ToolUse] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    cwd: str | None = None
    git_branch: str | None = None
    is_sidechain: bool = False
    is_meta: bool = False  # /command invocations, system-injected reminders, etc.

    def to_dict(self) -> dict:
        d = asdict(self)
        # asdict doesn't recurse into nested dataclass lists cleanly in some
        # versions; ensure all nested are also dicts.
        d["tool_uses"] = [asdict(t) for t in self.tool_uses]
        d["tool_results"] = [asdict(t) for t in self.tool_results]
        return d


# ─── Parsing helpers ─────────────────────────────────────────────────────────

def truncate(s: str, n: int = 500) -> str:
    s = s if isinstance(s, str) else str(s)
    if len(s) <= n:
        return s
    return s[:n] + f"… [+{len(s)-n} chars]"


def summarize_tool_input(name: str, inp: dict | str | None) -> str:
    if inp is None:
        return ""
    if isinstance(inp, str):
        return truncate(inp, 300)
    # Specific tools — keep the salient fields, not whole file contents
    if name == "Bash":
        return truncate(inp.get("command", ""), 400)
    if name in ("Edit", "Write", "MultiEdit"):
        return f"file={inp.get('file_path', '?')}"
    if name == "Read":
        return f"file={inp.get('file_path', '?')}"
    if name == "Grep":
        return f"pattern={inp.get('pattern', '?')[:120]}"
    if name == "Glob":
        return f"pattern={inp.get('pattern', '?')}"
    if name == "ScheduleWakeup":
        return f"delay={inp.get('delaySeconds')}s reason={truncate(inp.get('reason',''), 120)}"
    return truncate(json.dumps(inp, default=str), 300)


def summarize_tool_result(content) -> tuple[str, bool]:
    """Return (summary, is_error). tool_result content can be string, list of blocks, or dict."""
    if content is None:
        return "", False
    if isinstance(content, str):
        return truncate(content, 600), False
    if isinstance(content, list):
        # Concatenate any text blocks.
        parts = []
        is_err = False
        for blk in content:
            if isinstance(blk, dict):
                if blk.get("type") == "text":
                    parts.append(blk.get("text", ""))
                if blk.get("is_error"):
                    is_err = True
            elif isinstance(blk, str):
                parts.append(blk)
        return truncate("\n".join(parts), 600), is_err
    return truncate(str(content), 400), False


# ─── Core turn extraction ────────────────────────────────────────────────────

def extract_turn(raw: dict, session_id: str, turn_idx: int) -> Turn | None:
    """Return a normalized Turn from a raw JSONL row, or None to skip."""
    if raw.get("type") not in TURN_TYPES:
        return None

    msg = raw.get("message")
    if not isinstance(msg, dict):
        return None

    role = msg.get("role")
    if role not in ("user", "assistant"):
        return None

    text_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_uses: list[ToolUse] = []
    tool_results: list[ToolResult] = []

    content = msg.get("content")
    if isinstance(content, str):
        text_parts.append(content)
    elif isinstance(content, list):
        for blk in content:
            if not isinstance(blk, dict):
                if isinstance(blk, str):
                    text_parts.append(blk)
                continue
            btype = blk.get("type")
            if btype == "text":
                text_parts.append(blk.get("text", ""))
            elif btype == "thinking":
                thinking_parts.append(blk.get("thinking", ""))
            elif btype == "tool_use":
                tool_uses.append(ToolUse(
                    name=blk.get("name", "UNKNOWN"),
                    tool_use_id=blk.get("id", ""),
                    input_summary=summarize_tool_input(blk.get("name", ""), blk.get("input")),
                ))
            elif btype == "tool_result":
                summary, is_err_inner = summarize_tool_result(blk.get("content"))
                # is_error can be set at the block level OR inside content blocks
                is_err = bool(blk.get("is_error")) or is_err_inner
                tool_results.append(ToolResult(
                    tool_use_id=blk.get("tool_use_id", ""),
                    output_summary=summary,
                    is_error=is_err,
                ))

    text = "\n".join(p for p in text_parts if p).strip()
    thinking = "\n".join(p for p in thinking_parts if p).strip()

    # Detect meta turns: /command invocations, system reminders.
    is_meta = False
    if role == "user" and text.startswith("<command-message>"):
        is_meta = True
    if role == "user" and text.startswith("<system-reminder>"):
        is_meta = True

    return Turn(
        session_id=session_id,
        turn_idx=turn_idx,
        uuid=raw.get("uuid", ""),
        parent_uuid=raw.get("parentUuid"),
        timestamp=raw.get("timestamp", ""),
        role=role,
        text=truncate(text, 4000),
        thinking=truncate(thinking, 4000),
        tool_uses=tool_uses,
        tool_results=tool_results,
        cwd=raw.get("cwd"),
        git_branch=raw.get("gitBranch"),
        is_sidechain=bool(raw.get("isSidechain", False)),
        is_meta=is_meta,
    )


# ─── Per-session iteration + summary ────────────────────────────────────────

def session_id_for(path: pathlib.Path) -> str:
    """Build a session_id from the path.
       Main sessions:    <project>/<id>.jsonl
       Subagent traces:  <project>/<session-id>/subagents/agent-<id>.jsonl
    """
    parent = path.parent.name
    stem = path.stem
    if parent == "subagents":
        # Tag with the parent session so we can group later
        parent_session = path.parent.parent.name[:8]
        return f"subagent::{parent_session}::{stem}"
    return f"main::{stem}"


def iter_session_turns(path: pathlib.Path) -> Iterable[Turn]:
    sid = session_id_for(path)
    turn_idx = 0
    with path.open() as f:
        for line in f:
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            turn = extract_turn(raw, sid, turn_idx)
            if turn is None:
                continue
            yield turn
            turn_idx += 1


def summarize_session(turns: list[Turn]) -> dict:
    if not turns:
        return {"n_turns": 0}
    ts = [t.timestamp for t in turns if t.timestamp]
    role_counts = Counter(t.role for t in turns)
    tool_counts: Counter = Counter()
    n_errors = 0
    for t in turns:
        for tu in t.tool_uses:
            tool_counts[tu.name] += 1
        for tr in t.tool_results:
            if tr.is_error:
                n_errors += 1
    n_meta = sum(1 for t in turns if t.is_meta)
    n_sidechain = sum(1 for t in turns if t.is_sidechain)
    return {
        "n_turns":           len(turns),
        "n_user":            int(role_counts.get("user", 0)),
        "n_assistant":       int(role_counts.get("assistant", 0)),
        "n_meta_turns":      n_meta,
        "n_sidechain_turns": n_sidechain,
        "n_tool_uses":       sum(tool_counts.values()),
        "tool_counts":       dict(tool_counts.most_common()),
        "n_tool_errors":     n_errors,
        "first_timestamp":   min(ts) if ts else None,
        "last_timestamp":    max(ts) if ts else None,
    }


def session_duration_days(summary: dict) -> float | None:
    a = summary.get("first_timestamp")
    b = summary.get("last_timestamp")
    if not (a and b): return None
    try:
        ta = datetime.fromisoformat(a.replace("Z","+00:00"))
        tb = datetime.fromisoformat(b.replace("Z","+00:00"))
        return round((tb - ta).total_seconds() / 86400, 2)
    except Exception:
        return None


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    main_paths = sorted(CLAUDE_PROJECTS.glob("*.jsonl"))
    subagent_paths = sorted(CLAUDE_PROJECTS.glob("*/subagents/*.jsonl"))
    all_paths = main_paths + subagent_paths
    print(f"Found {len(main_paths)} main sessions + {len(subagent_paths)} subagent traces "
          f"= {len(all_paths)} JSONL files")

    inventory: dict = {
        "as_of":         datetime.now().isoformat(timespec="seconds"),
        "claude_projects_dir": str(CLAUDE_PROJECTS),
        "n_main_sessions":     len(main_paths),
        "n_subagent_traces":   len(subagent_paths),
        "sessions":            {},
        "aggregate": {
            "total_turns":     0,
            "total_user":      0,
            "total_assistant": 0,
            "total_tool_uses": 0,
            "total_errors":    0,
            "tool_counts":     {},
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    total_written = 0

    with OUT_NORMALIZED.open("w") as out_f:
        for path in all_paths:
            sid = session_id_for(path)
            turns = list(iter_session_turns(path))
            for t in turns:
                out_f.write(json.dumps(t.to_dict()) + "\n")
                total_written += 1
            summary = summarize_session(turns)
            summary["duration_days"] = session_duration_days(summary)
            summary["source_path"] = str(path)
            summary["file_size_bytes"] = path.stat().st_size
            inventory["sessions"][sid] = summary

            agg = inventory["aggregate"]
            agg["total_turns"]     += summary["n_turns"]
            agg["total_user"]      += summary["n_user"]
            agg["total_assistant"] += summary["n_assistant"]
            agg["total_tool_uses"] += summary["n_tool_uses"]
            agg["total_errors"]    += summary["n_tool_errors"]
            for name, n in summary.get("tool_counts", {}).items():
                agg["tool_counts"][name] = agg["tool_counts"].get(name, 0) + n

    # Reorder tool_counts in aggregate
    inventory["aggregate"]["tool_counts"] = dict(
        sorted(inventory["aggregate"]["tool_counts"].items(), key=lambda kv: -kv[1])
    )

    OUT_INVENTORY.write_text(json.dumps(inventory, indent=2, default=str))

    # Print summary
    print(f"\nWrote {OUT_NORMALIZED}  ({total_written:,} normalized turns)")
    print(f"Wrote {OUT_INVENTORY}")

    agg = inventory["aggregate"]
    print()
    print("=" * 72)
    print("CORPUS INVENTORY")
    print("=" * 72)
    print(f"  Sessions / subagent traces: {inventory['n_main_sessions']} / {inventory['n_subagent_traces']}")
    print(f"  Total turns:                {agg['total_turns']:>8,}")
    print(f"  - User turns:               {agg['total_user']:>8,}")
    print(f"  - Assistant turns:          {agg['total_assistant']:>8,}")
    print(f"  - Tool uses:                {agg['total_tool_uses']:>8,}")
    print(f"  - Tool errors:              {agg['total_errors']:>8,}")
    print(f"\nTop tools:")
    for name, n in list(agg["tool_counts"].items())[:12]:
        print(f"    {name:<20s} {n:>6,}")

    # Per-session quick-look (main sessions only — subagents are too numerous)
    print()
    print("MAIN SESSIONS")
    print("-" * 72)
    print(f"  {'session':<24s} {'turns':>7s} {'tools':>7s} {'days':>7s}  {'first → last'}")
    for sid in sorted(inventory["sessions"].keys()):
        if not sid.startswith("main::"): continue
        s = inventory["sessions"][sid]
        short = sid.replace("main::", "")[:8]
        first = s.get("first_timestamp", "")[:10] if s.get("first_timestamp") else "?"
        last = s.get("last_timestamp", "")[:10] if s.get("last_timestamp") else "?"
        dur = s.get("duration_days")
        dur_s = f"{dur:>6.1f}" if dur is not None else "    ?"
        print(f"  {short:<24s} {s['n_turns']:>7,} {s['n_tool_uses']:>7,} {dur_s}  {first} → {last}")


if __name__ == "__main__":
    main()
