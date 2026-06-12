#!/usr/bin/env python3
"""
F-023 Phase 2 step 3: intervention catalog.

Applies the 4 pre-registered intervention rules (PHASE2_PRE_REGISTRATION_v0.1.md §3)
to each turn in the stratified sample (data/phase2_sample.json), evaluating
against the reconstructed belief state at that turn.

Inputs:
  data/phase2_sample.json           — 20,190 (session, turn) evaluation points
  data/phase2_belief_timelines.jsonl — 11,262 belief instances across 164 sessions
  data/sessions_classified.jsonl     — full classified turn ledger

Output:
  data/phase2_intervention_verdicts.jsonl
    One record per (session_id, turn_idx, rule) where the rule is applicable:
      {
        session_id, turn_idx, uuid, ts, l1_region, rule,
        applicable: true,
        verdict: "SUPPRESS" | "ALLOW",
        intervention_action: "suppress_retry" | "suppress_deploy" |
                             "require_status_check" | "retire_fix_prior",
        evidence: {…},
      }

Ambiguities encountered are documented in PHASE2_ISSUES_LOG.md (I-002, I-003).
"""

from __future__ import annotations

import json
import math
import pathlib
import re
from collections import defaultdict
from datetime import datetime
from typing import Iterable

ROOT = pathlib.Path(__file__).resolve().parent
SAMPLE_PATH       = ROOT / "data" / "phase2_sample.json"
TIMELINES_PATH    = ROOT / "data" / "phase2_belief_timelines.jsonl"
SESSIONS_PATH     = ROOT / "data" / "sessions_classified.jsonl"
OUT_PATH          = ROOT / "data" / "phase2_intervention_verdicts.jsonl"

RULES_VERSION         = "v0.1"
LN2                   = 0.6931471805599453
ACTIVE_THRESHOLD      = 0.3   # §2.9
SUPPRESSED_THRESHOLD  = 0.7   # §2.9 (v0.2: intervention authority threshold)
INITIAL_CONFIDENCE    = 1.0

# §3.3 stale_pipeline_prior trigger threshold: 2× expected duration (10 min)
STALE_PIPELINE_SECONDS = 20 * 60

# §3.1 repeated_failure_loop window: 10 turns, threshold 3 same-signature failures
LOOP_WINDOW            = 10
LOOP_THRESHOLD         = 3

# §3.1 signature-match operationalization (see PHASE2_ISSUES_LOG.md I-003)
ERROR_KEYWORD_LEN      = 80

# Half-lives (mirror phase2_belief_tracker.py §2)
BELIEF_HALF_LIFE: dict[str, int] = {
    "pipeline_running":        30 * 60,
    "pipeline_failed":         60 * 60,
    "issue_under_diagnosis":   45 * 60,
    "fix_attempted":           15 * 60,
    "validation_pending":      10 * 60,
    "deploy_pending":          60 * 60,
    "report_ready":         4 * 60 * 60,
    "user_approval_required":  30 * 60,
}

# Pipeline status-check pattern — mirrors phase2_belief_tracker.PIPELINE_STATUS_CHECK
PIPELINE_STATUS_CHECK = re.compile(
    r"\bps aux\b.*pipeline|\btail .*\.output\b|\btail -.*log\b",
    re.IGNORECASE,
)

# Deploy action patterns — mirrors phase2_belief_tracker.DEPLOY_ACTION
DEPLOY_ACTION = re.compile(
    r"\bgit push\b|\bvercel\b.*--prod\b",
    re.IGNORECASE,
)

# Validation tool patterns — mirrors phase2_belief_tracker.VALIDATION_PATTERNS
VALIDATION_PATTERNS = re.compile(
    r"\bpytest\b|\bnpm test\b|\btsc\b|--check\b|--validate\b|--noEmit\b|"
    r"\bgit (status|diff)\b",
    re.IGNORECASE,
)

# Substantive change tools — used as "material action" for §3.1 loop detection
FIX_TOOLS = {"Edit", "Write", "MultiEdit"}


# ─── Utility ─────────────────────────────────────────────────────────────────

def parse_ts(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def assistant_bash_summaries(turn: dict) -> list[str]:
    out = []
    for tu in turn.get("tool_uses", []) or []:
        if tu.get("name") == "Bash":
            out.append(tu.get("input_summary", "") or "")
    return out


def has_tool_error(turn: dict) -> bool:
    return any(tr.get("is_error") for tr in (turn.get("tool_results") or []))


def turn_is_deploy_action(turn: dict) -> bool:
    cmds = assistant_bash_summaries(turn)
    return any(DEPLOY_ACTION.search(c) for c in cmds)


def turn_is_status_check(turn: dict) -> bool:
    cmds = assistant_bash_summaries(turn)
    return any(PIPELINE_STATUS_CHECK.search(c) for c in cmds)


def turn_is_validation(turn: dict) -> tuple[bool, str | None]:
    cmds = assistant_bash_summaries(turn)
    is_val = any(VALIDATION_PATTERNS.search(c) for c in cmds)
    if not is_val:
        return False, None
    results = turn.get("tool_results") or []
    if any(r.get("is_error") for r in results):
        return True, "FAIL"
    if results:
        return True, "PASS"
    return True, None


def turn_makes_material_change(turn: dict) -> bool:
    """For §3.1 'material action' between failures.

    Operationalization: any tool_use whose name is Edit/Write/MultiEdit OR a
    Bash whose first-token differs from prior failures. Conservative reading:
    treat any FIX_TOOLS use as material; Bash material-ness is judged in the
    loop logic where we already track first-token sequences.
    """
    for tu in turn.get("tool_uses", []) or []:
        if tu.get("name") in FIX_TOOLS:
            return True
    return False


# ─── Signature extraction (§3.1, per I-003) ──────────────────────────────────

def extract_error_keyword(turn: dict) -> str | None:
    """First 80 chars of the first error message, lowercased + stripped."""
    for tr in turn.get("tool_results") or []:
        if tr.get("is_error"):
            msg = (tr.get("content") or tr.get("output") or "") or ""
            if isinstance(msg, list):
                # content may be a list of blocks
                msg = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in msg)
            msg = msg.strip().lower()[:ERROR_KEYWORD_LEN]
            if msg:
                return msg
    return None


def extract_tool_names(turn: dict) -> set[str]:
    return {tu.get("name", "") for tu in (turn.get("tool_uses") or []) if tu.get("name")}


def extract_file_paths(turn: dict) -> set[str]:
    """Pull file_path-like fields from all tool_uses."""
    paths = set()
    for tu in turn.get("tool_uses") or []:
        inp = tu.get("input_summary", "") or ""
        # Conservative: pull anything that looks like a path token
        for tok in re.findall(r"[\w./\-]+\.[a-zA-Z]{1,6}\b", inp):
            paths.add(tok.lower())
    return paths


def extract_command_first_tokens(turn: dict) -> set[str]:
    """First whitespace token of each Bash command."""
    out = set()
    for cmd in assistant_bash_summaries(turn):
        cmd = cmd.strip()
        if not cmd:
            continue
        first = cmd.split(None, 1)[0].lower()
        out.add(first)
    return out


def turn_signature(turn: dict) -> dict:
    """Return a dict of signature components for §3.1 matching."""
    return {
        "tools":       extract_tool_names(turn),
        "error_kw":    extract_error_keyword(turn),
        "file_paths":  extract_file_paths(turn),
        "cmd_tokens":  extract_command_first_tokens(turn),
    }


def signatures_match(sig_a: dict, sig_b: dict) -> bool:
    """§3.1: same tool AND same error_kw, OR same file path AND same command pattern."""
    same_tool = bool(sig_a["tools"] & sig_b["tools"])
    same_err  = sig_a["error_kw"] and sig_b["error_kw"] and sig_a["error_kw"] == sig_b["error_kw"]
    if same_tool and same_err:
        return True
    same_path = bool(sig_a["file_paths"] & sig_b["file_paths"])
    same_cmd  = bool(sig_a["cmd_tokens"] & sig_b["cmd_tokens"])
    if same_path and same_cmd:
        return True
    return False


# ─── Belief state reconstruction ─────────────────────────────────────────────

def reconstruct_state_at(
    timelines: list[dict],
    eval_ts: datetime,
) -> dict[str, list[dict]]:
    """
    Given all belief instances for a session, compute (active, retired) states
    as of eval_ts. Returns a dict keyed by belief_name with a list of
    {anchor_uuid, weight, last_refresh_ts, status} entries.

    status ∈ {"active", "retired_before"}.
    Weight is computed against last_refresh_ts ≤ eval_ts and excludes events
    strictly after eval_ts.
    """
    out: dict[str, list[dict]] = defaultdict(list)
    for inst in timelines:
        bname = inst["belief_name"]
        birth_ts = parse_ts(inst["birth_ts"])
        if birth_ts is None or birth_ts > eval_ts:
            continue  # not yet born at eval time
        # Walk events in order to find last refresh ≤ eval_ts and any retire ≤ eval_ts
        last_refresh = birth_ts
        retired_at = None
        for ev in inst.get("events", []):
            ev_ts = parse_ts(ev.get("ts", ""))
            if ev_ts is None or ev_ts > eval_ts:
                continue
            etype = ev.get("event_type")
            if etype == "refreshed":
                last_refresh = ev_ts
            elif etype in ("retired", "contradicted"):
                retired_at = ev_ts
        if retired_at is not None:
            out[bname].append({
                "anchor_uuid":      inst["anchor_uuid"],
                "weight":           0.0,
                "last_refresh_ts":  last_refresh.isoformat(),
                "retired_ts":       retired_at.isoformat(),
                "status":           "retired_before",
            })
            continue
        # Active branch — compute decayed weight
        half_life = BELIEF_HALF_LIFE[bname]
        elapsed = (eval_ts - last_refresh).total_seconds()
        if elapsed <= 0:
            weight = INITIAL_CONFIDENCE
        else:
            weight = INITIAL_CONFIDENCE * math.exp(-LN2 * elapsed / half_life)
        # §2.9 stale_decay: weight < 0.3 with no refresh → considered retired
        if weight < ACTIVE_THRESHOLD:
            out[bname].append({
                "anchor_uuid":      inst["anchor_uuid"],
                "weight":           weight,
                "last_refresh_ts":  last_refresh.isoformat(),
                "retired_ts":       None,
                "status":           "stale",
            })
            continue
        out[bname].append({
            "anchor_uuid":      inst["anchor_uuid"],
            "weight":           weight,
            "last_refresh_ts":  last_refresh.isoformat(),
            "retired_ts":       None,
            "status":           "active",
        })
    return out


def latest_belief(state: dict, name: str, statuses: tuple[str, ...] = ("active",)) -> dict | None:
    """Return the most recently refreshed instance of `name` whose status is in `statuses`."""
    candidates = [b for b in state.get(name, []) if b["status"] in statuses]
    if not candidates:
        return None
    return max(candidates, key=lambda b: b["last_refresh_ts"])


def any_instance_exists(state: dict, name: str) -> bool:
    """True if name has been instantiated in this session at any point before eval_ts."""
    return name in state and len(state[name]) > 0


# ─── Rule evaluation ─────────────────────────────────────────────────────────

def rule_repeated_failure_loop(
    eval_turn: dict,
    prior_turns: list[dict],
) -> dict | None:
    """
    §3.1: ≥3 same-signature failures in 10-turn window, no material action between.

    Applicability: eval_turn is itself a failure_diagnosis OR has tool_error.
    Trigger: count of prior same-signature failure turns (within LOOP_WINDOW,
    incl. eval_turn) ≥ LOOP_THRESHOLD AND no material change turn sits between
    earliest and latest failure in that streak.
    """
    eval_is_failure = (
        eval_turn.get("l1_region") == "failure_diagnosis"
        or has_tool_error(eval_turn)
    )
    if not eval_is_failure:
        return None  # not applicable

    # Pull the last LOOP_WINDOW-1 prior turns + eval_turn (chronological)
    window = (prior_turns + [eval_turn])[-LOOP_WINDOW:]
    eval_sig = turn_signature(eval_turn)
    matched = [eval_turn]
    for t in reversed(window[:-1]):
        t_is_failure = (
            t.get("l1_region") == "failure_diagnosis"
            or has_tool_error(t)
        )
        if not t_is_failure:
            continue
        if signatures_match(eval_sig, turn_signature(t)):
            matched.append(t)
    # Check material action between matched turns (in original window order)
    matched_by_idx = {t["turn_idx"]: t for t in matched}
    matched_idxs = sorted(matched_by_idx.keys())
    if len(matched_idxs) < LOOP_THRESHOLD:
        return {
            "applicable":  True,
            "verdict":     "ALLOW",
            "intervention_action": "suppress_retry",
            "evidence":    {
                "matched_turn_count": len(matched_idxs),
                "loop_threshold":     LOOP_THRESHOLD,
                "window_size":        LOOP_WINDOW,
            },
        }
    # Check material action between matched failures
    material_between = False
    for t in window:
        if matched_idxs[0] < t["turn_idx"] < matched_idxs[-1] and turn_makes_material_change(t):
            material_between = True
            break
    if material_between:
        return {
            "applicable":  True,
            "verdict":     "ALLOW",
            "intervention_action": "suppress_retry",
            "evidence":    {
                "matched_turn_count":   len(matched_idxs),
                "material_action_seen": True,
            },
        }
    return {
        "applicable":  True,
        "verdict":     "SUPPRESS",
        "intervention_action": "suppress_retry",
        "evidence":    {
            "matched_turn_count":   len(matched_idxs),
            "matched_turn_idxs":    matched_idxs,
            "window_size":          LOOP_WINDOW,
            "error_keyword":        eval_sig["error_kw"],
            "shared_tools":         sorted(eval_sig["tools"]),
        },
    }


def rule_stale_deploy_prior(
    eval_turn: dict,
    state: dict,
) -> dict | None:
    """
    §3.2 (literal reading, see I-002):

    Trigger:
      - deploy_pending active
      - turn is a deploy action
      - user_approval_required EXISTS at this point AND its weight < SUPPRESSED_THRESHOLD
    """
    if not turn_is_deploy_action(eval_turn):
        return None  # not applicable
    deploy_pending = latest_belief(state, "deploy_pending", statuses=("active",))
    if deploy_pending is None:
        return {
            "applicable":  True,
            "verdict":     "ALLOW",
            "intervention_action": "suppress_deploy",
            "evidence":    {"deploy_pending_active": False},
        }
    if not any_instance_exists(state, "user_approval_required"):
        # No requirement was ever raised; rule does not fire (see I-002 decision)
        return {
            "applicable":  True,
            "verdict":     "ALLOW",
            "intervention_action": "suppress_deploy",
            "evidence":    {
                "deploy_pending_active":         True,
                "user_approval_required_exists": False,
            },
        }
    # Pick most recent user_approval_required (active or stale or retired)
    candidates = state.get("user_approval_required", [])
    latest_uar = max(candidates, key=lambda b: b["last_refresh_ts"])
    weight = latest_uar["weight"]
    if weight < SUPPRESSED_THRESHOLD:
        return {
            "applicable":  True,
            "verdict":     "SUPPRESS",
            "intervention_action": "suppress_deploy",
            "evidence":    {
                "deploy_pending_active":           True,
                "deploy_pending_weight":           deploy_pending["weight"],
                "user_approval_required_weight":   weight,
                "user_approval_required_status":   latest_uar["status"],
                "suppressed_threshold":            SUPPRESSED_THRESHOLD,
            },
        }
    return {
        "applicable":  True,
        "verdict":     "ALLOW",
        "intervention_action": "suppress_deploy",
        "evidence":    {
            "deploy_pending_active":           True,
            "user_approval_required_weight":   weight,
            "above_suppressed_threshold":      True,
        },
    }


def rule_stale_pipeline_prior(
    eval_turn: dict,
    state: dict,
    eval_ts: datetime,
) -> dict | None:
    """
    §3.3: pipeline_running older than 20 min without fresh evidence; require
    explicit status check before continuing other operations.

    Applicability: any turn that is NOT itself a status check.
    Trigger: pipeline_running active AND (eval_ts - last_refresh_ts) > 20 min.
    """
    if turn_is_status_check(eval_turn):
        return None  # the rule's whole point is to require a status check; one happening is fine
    pipeline_running = latest_belief(state, "pipeline_running", statuses=("active",))
    if pipeline_running is None:
        return None  # not applicable
    last_refresh = parse_ts(pipeline_running["last_refresh_ts"])
    if last_refresh is None:
        return None
    age_seconds = (eval_ts - last_refresh).total_seconds()
    if age_seconds <= STALE_PIPELINE_SECONDS:
        return {
            "applicable":  True,
            "verdict":     "ALLOW",
            "intervention_action": "require_status_check",
            "evidence":    {
                "pipeline_age_seconds":   age_seconds,
                "stale_threshold_seconds": STALE_PIPELINE_SECONDS,
                "pipeline_running_weight": pipeline_running["weight"],
            },
        }
    return {
        "applicable":  True,
        "verdict":     "SUPPRESS",
        "intervention_action": "require_status_check",
        "evidence":    {
            "pipeline_age_seconds":      age_seconds,
            "stale_threshold_seconds":   STALE_PIPELINE_SECONDS,
            "pipeline_running_weight":   pipeline_running["weight"],
            "last_refresh_ts":           pipeline_running["last_refresh_ts"],
        },
    }


def rule_contradicted_fix_prior(
    eval_turn: dict,
    state: dict,
) -> dict | None:
    """
    §3.4: validation FAIL fires while fix_attempted active → RETIRE fix's
    implicit "fix succeeded" sub-belief.

    Applicability: turn IS a validation with FAIL status.
    Trigger: fix_attempted active at evaluation time.
    """
    is_val, vstatus = turn_is_validation(eval_turn)
    if not (is_val and vstatus == "FAIL"):
        return None  # not applicable
    fix_attempted = latest_belief(state, "fix_attempted", statuses=("active",))
    if fix_attempted is None:
        return {
            "applicable":  True,
            "verdict":     "ALLOW",
            "intervention_action": "retire_fix_prior",
            "evidence":    {"fix_attempted_active": False, "validation_status": "FAIL"},
        }
    return {
        "applicable":  True,
        "verdict":     "SUPPRESS",
        "intervention_action": "retire_fix_prior",
        "evidence":    {
            "fix_attempted_active":   True,
            "fix_attempted_weight":   fix_attempted["weight"],
            "validation_status":      "FAIL",
        },
    }


# ─── Main pipeline ───────────────────────────────────────────────────────────

def load_timelines() -> dict[str, list[dict]]:
    by_session: dict[str, list[dict]] = defaultdict(list)
    with TIMELINES_PATH.open() as f:
        for line in f:
            try:
                t = json.loads(line)
            except json.JSONDecodeError:
                continue
            by_session[t["session_id"]].append(t)
    return by_session


def load_sessions() -> dict[str, list[dict]]:
    by_session: dict[str, list[dict]] = defaultdict(list)
    with SESSIONS_PATH.open() as f:
        for line in f:
            try:
                t = json.loads(line)
            except json.JSONDecodeError:
                continue
            by_session[t["session_id"]].append(t)
    # Sort by turn_idx
    for sid in by_session:
        by_session[sid].sort(key=lambda t: t["turn_idx"])
    return by_session


def load_sample() -> dict[str, set[int]]:
    """Returns {session_id: set(turn_idxs to evaluate)}."""
    sample = json.loads(SAMPLE_PATH.read_text())["sample"]
    out: dict[str, set[int]] = defaultdict(set)
    for s in sample:
        out[s["session_id"]].add(s["turn_idx"])
    return out


def main() -> None:
    print("Loading belief timelines…")
    timelines = load_timelines()
    print(f"  loaded {sum(len(v) for v in timelines.values()):,} instances across {len(timelines):,} sessions")

    print("Loading sample…")
    sample_idxs = load_sample()
    print(f"  loaded {sum(len(v) for v in sample_idxs.values()):,} evaluation points across {len(sample_idxs)} sessions")

    print("Loading full classified sessions…")
    sessions = load_sessions()
    print(f"  loaded {sum(len(v) for v in sessions.values()):,} turns across {len(sessions)} sessions")

    out_records: list[dict] = []
    verdict_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    applicable_counts: dict[str, int] = defaultdict(int)

    print(f"\nEvaluating sample against 4 rules…")
    for sid, turn_set in sample_idxs.items():
        session_turns = sessions.get(sid, [])
        session_timelines = timelines.get(sid, [])
        if not session_turns:
            continue
        # Index by turn_idx for quick lookup
        by_idx = {t["turn_idx"]: t for t in session_turns}
        # Build a prefix sequence for §3.1 window lookups
        for tidx in sorted(turn_set):
            eval_turn = by_idx.get(tidx)
            if eval_turn is None:
                continue
            eval_ts = parse_ts(eval_turn.get("timestamp", ""))
            if eval_ts is None:
                continue
            # Prior turns in chronological order, all turns with turn_idx < tidx
            prior_turns = [t for t in session_turns if t["turn_idx"] < tidx]
            # Reconstruct belief state at eval_ts
            state = reconstruct_state_at(session_timelines, eval_ts)
            # Apply rules
            rules = {
                "repeated_failure_loop": rule_repeated_failure_loop(eval_turn, prior_turns),
                "stale_deploy_prior":    rule_stale_deploy_prior(eval_turn, state),
                "stale_pipeline_prior":  rule_stale_pipeline_prior(eval_turn, state, eval_ts),
                "contradicted_fix_prior": rule_contradicted_fix_prior(eval_turn, state),
            }
            for rule_name, result in rules.items():
                if result is None:
                    continue
                applicable_counts[rule_name] += 1
                verdict_counts[rule_name][result["verdict"]] += 1
                out_records.append({
                    "session_id":   sid,
                    "turn_idx":     tidx,
                    "uuid":         eval_turn.get("uuid"),
                    "ts":           eval_ts.isoformat(),
                    "l1_region":    eval_turn.get("l1_region", "UNCLASSIFIED"),
                    "rule":         rule_name,
                    **result,
                })

    print(f"\nWriting {OUT_PATH} ({len(out_records):,} verdicts)…")
    with OUT_PATH.open("w") as f:
        for r in out_records:
            # Convert any sets in evidence to sorted lists for JSON
            f.write(json.dumps(r, default=lambda o: sorted(o) if isinstance(o, set) else str(o)) + "\n")

    print("\n" + "=" * 72)
    print("INTERVENTION VERDICT COUNTS (rules v0.1)")
    print("=" * 72)
    for rule in [
        "repeated_failure_loop",
        "stale_deploy_prior",
        "stale_pipeline_prior",
        "contradicted_fix_prior",
    ]:
        app = applicable_counts[rule]
        s = verdict_counts[rule]["SUPPRESS"]
        a = verdict_counts[rule]["ALLOW"]
        print(f"  {rule:30s}  applicable={app:6,}  SUPPRESS={s:6,}  ALLOW={a:6,}")
    print()


if __name__ == "__main__":
    main()
