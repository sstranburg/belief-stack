#!/usr/bin/env python3
"""
F-023 Phase 2 v0.2: intervention catalog.

Implements rules per PHASE2_PRE_REGISTRATION_v0.2.md (locked 2026-05-29).
v0.1 artifacts are NOT touched. v0.2 reads the same sample, beliefs, and
session ledger as v0.1, and writes parallel _v0_2.jsonl outputs.

Changes from v0.1:
  - Threshold name: intervention_authority_threshold (rename of suppressed_threshold) [A-001]
  - §3.1 signature match: disjunction of (tool+Jaccard≥0.5), (file∩+cmd∩), (exception class) [A-003]
  - §3.1 material action: any Edit/Write/MultiEdit (unchanged from v0.1 in code; spec clarified) [A-003]
  - §3.2 stale_deploy_prior: SUPPRESS when user_approval_required active AND weight ≥ 0.7 [A-002]
  - §3.3 stale_pipeline_prior: threshold 30 min (up from 20) [A-005]
  - §3.4 contradicted_fix_prior: applicability requires touched-file OR command-family OR validation context overlap [A-004]
"""

from __future__ import annotations

import json
import math
import pathlib
import re
from collections import defaultdict
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent
SAMPLE_PATH       = ROOT / "data" / "phase2_sample.json"
TIMELINES_PATH    = ROOT / "data" / "phase2_belief_timelines.jsonl"
SESSIONS_PATH     = ROOT / "data" / "sessions_classified.jsonl"
OUT_PATH          = ROOT / "data" / "phase2_intervention_verdicts_v0_2.jsonl"

RULES_VERSION              = "v0.2"
LN2                        = 0.6931471805599453
ACTIVE_THRESHOLD           = 0.3
INTERVENTION_AUTHORITY_THR = 0.7   # A-001 rename of suppressed_threshold
INITIAL_CONFIDENCE         = 1.0

# §3.3 stale_pipeline_prior trigger threshold: 30 min (A-005)
STALE_PIPELINE_SECONDS     = 30 * 60

# §3.1 repeated_failure_loop
LOOP_WINDOW                = 10
LOOP_THRESHOLD             = 3
JACCARD_THRESHOLD          = 0.5   # A-003

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

PIPELINE_STATUS_CHECK = re.compile(
    r"\bps aux\b.*pipeline|\btail .*\.output\b|\btail -.*log\b",
    re.IGNORECASE,
)
DEPLOY_ACTION = re.compile(
    r"\bgit push\b|\bvercel\b.*--prod\b",
    re.IGNORECASE,
)

# §3.4 (c) validation pattern set, v0.2 expanded
VALIDATION_PATTERNS_V02 = re.compile(
    r"\bpytest\b|\bnpm test\b|\btsc\b|--check\b|--validate\b|--noEmit\b|"
    r"\bgit (status|diff)\b|\bmypy\b|\bruff\b|\beslint\b|\bprettier\b",
    re.IGNORECASE,
)
ERROR_INDICATOR_RE = re.compile(
    r"traceback|exception|\berror:|non-zero exit|exit code [1-9]",
    re.IGNORECASE,
)

FIX_TOOLS = {"Edit", "Write", "MultiEdit"}

# Exception-class regex (Python/JS): "ValueError", "TypeError", etc.
EXCEPTION_CLASS_RE = re.compile(r"\b[A-Z][a-zA-Z]*Error\b")

# Small English stopword list for Jaccard error-gist similarity
STOPWORDS = {
    "the","a","an","and","or","but","is","are","was","were","be","been","being",
    "have","has","had","do","does","did","will","would","should","could","can",
    "may","might","must","shall","of","at","by","for","with","about","against",
    "between","into","through","during","before","after","above","below","to",
    "from","up","down","in","out","on","off","over","under","again","further",
    "then","once","here","there","when","where","why","how","all","any","both",
    "each","few","more","most","other","some","such","no","nor","not","only",
    "own","same","so","than","too","very","s","t","just","don","now","i","me",
    "my","myself","we","our","ours","ourselves","you","your","yours","yourself",
    "he","him","his","himself","she","her","hers","herself","it","its","itself",
    "they","them","their","theirs","themselves","what","which","who","whom","this",
    "that","these","those","am","if","as","because","until","while",
}


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
    return any(DEPLOY_ACTION.search(c) for c in assistant_bash_summaries(turn))


def turn_is_status_check(turn: dict) -> bool:
    return any(PIPELINE_STATUS_CHECK.search(c) for c in assistant_bash_summaries(turn))


def turn_is_validation_v02(turn: dict) -> tuple[bool, str | None]:
    cmds = assistant_bash_summaries(turn)
    is_val = any(VALIDATION_PATTERNS_V02.search(c) for c in cmds)
    if not is_val:
        return False, None
    results = turn.get("tool_results") or []
    if any(r.get("is_error") for r in results):
        return True, "FAIL"
    if results:
        return True, "PASS"
    return True, None


def turn_makes_material_change(turn: dict) -> bool:
    return any(tu.get("name") in FIX_TOOLS for tu in (turn.get("tool_uses") or []))


# ─── Signature extraction (§3.1 v0.2 disjunction) ────────────────────────────

def _result_text(turn: dict) -> str:
    out = []
    for tr in turn.get("tool_results") or []:
        content = tr.get("content") or tr.get("output") or ""
        if isinstance(content, list):
            content = " ".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in content
            )
        out.append(str(content))
    return " ".join(out)


def extract_error_word_bag(turn: dict) -> set[str]:
    text = ""
    for tr in turn.get("tool_results") or []:
        if tr.get("is_error"):
            content = tr.get("content") or tr.get("output") or ""
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") if isinstance(b, dict) else str(b) for b in content
                )
            text = str(content).lower()
            break
    if not text:
        return set()
    tokens = re.findall(r"[a-z][a-z0-9_]{2,}", text)
    return {t for t in tokens if t not in STOPWORDS}


def extract_exception_classes(turn: dict) -> set[str]:
    text = _result_text(turn)
    return set(EXCEPTION_CLASS_RE.findall(text))


def extract_tool_names(turn: dict) -> set[str]:
    return {tu.get("name", "") for tu in (turn.get("tool_uses") or []) if tu.get("name")}


def extract_file_paths(turn: dict) -> set[str]:
    paths = set()
    for tu in turn.get("tool_uses") or []:
        inp = tu.get("input_summary", "") or ""
        for tok in re.findall(r"[\w./\-]+\.[a-zA-Z]{1,6}\b", inp):
            paths.add(tok.lower())
    return paths


def extract_command_first_tokens(turn: dict) -> set[str]:
    out = set()
    for cmd in assistant_bash_summaries(turn):
        cmd = cmd.strip()
        if not cmd:
            continue
        out.add(cmd.split(None, 1)[0].lower())
    return out


def turn_signature_v02(turn: dict) -> dict:
    return {
        "tools":            extract_tool_names(turn),
        "error_words":      extract_error_word_bag(turn),
        "exception_classes": extract_exception_classes(turn),
        "file_paths":       extract_file_paths(turn),
        "cmd_tokens":       extract_command_first_tokens(turn),
    }


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def signatures_match_v02(sig_a: dict, sig_b: dict) -> bool:
    """v0.2 disjunction (A-003)."""
    # (1) same tool AND error-message Jaccard ≥ 0.5
    if sig_a["tools"] & sig_b["tools"]:
        if jaccard(sig_a["error_words"], sig_b["error_words"]) >= JACCARD_THRESHOLD:
            return True
    # (2) shared file path AND shared command first-token
    if (sig_a["file_paths"] & sig_b["file_paths"]) and (sig_a["cmd_tokens"] & sig_b["cmd_tokens"]):
        return True
    # (3) shared exception class
    if sig_a["exception_classes"] & sig_b["exception_classes"]:
        return True
    return False


# ─── Belief state reconstruction (identical to v0.1) ─────────────────────────

def reconstruct_state_at(
    timelines: list[dict],
    eval_ts: datetime,
) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for inst in timelines:
        bname = inst["belief_name"]
        birth_ts = parse_ts(inst["birth_ts"])
        if birth_ts is None or birth_ts > eval_ts:
            continue
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
                "birth_ts":         birth_ts.isoformat(),
                "status":           "retired_before",
                "events":           inst.get("events", []),
            })
            continue
        half_life = BELIEF_HALF_LIFE[bname]
        elapsed = (eval_ts - last_refresh).total_seconds()
        if elapsed <= 0:
            weight = INITIAL_CONFIDENCE
        else:
            weight = INITIAL_CONFIDENCE * math.exp(-LN2 * elapsed / half_life)
        if weight < ACTIVE_THRESHOLD:
            status = "stale"
        else:
            status = "active"
        out[bname].append({
            "anchor_uuid":      inst["anchor_uuid"],
            "weight":           weight,
            "last_refresh_ts":  last_refresh.isoformat(),
            "birth_ts":         birth_ts.isoformat(),
            "status":           status,
            "events":           inst.get("events", []),
        })
    return out


def latest_belief(state: dict, name: str, statuses: tuple[str, ...] = ("active",)) -> dict | None:
    cands = [b for b in state.get(name, []) if b["status"] in statuses]
    if not cands:
        return None
    return max(cands, key=lambda b: b["last_refresh_ts"])


# ─── Rule evaluators (v0.2) ──────────────────────────────────────────────────

def rule_repeated_failure_loop(eval_turn: dict, prior_turns: list[dict]) -> dict | None:
    """§3.1 v0.2: disjunction signature match, conservative material-action rule."""
    eval_is_failure = (
        eval_turn.get("l1_region") == "failure_diagnosis"
        or has_tool_error(eval_turn)
    )
    if not eval_is_failure:
        return None
    window = (prior_turns + [eval_turn])[-LOOP_WINDOW:]
    eval_sig = turn_signature_v02(eval_turn)
    matched = [eval_turn]
    for t in reversed(window[:-1]):
        t_is_failure = (
            t.get("l1_region") == "failure_diagnosis"
            or has_tool_error(t)
        )
        if not t_is_failure:
            continue
        if signatures_match_v02(eval_sig, turn_signature_v02(t)):
            matched.append(t)
    matched_idxs = sorted({t["turn_idx"] for t in matched})
    if len(matched_idxs) < LOOP_THRESHOLD:
        return {
            "applicable":          True,
            "verdict":             "ALLOW",
            "intervention_action": "suppress_retry",
            "evidence": {
                "matched_turn_count": len(matched_idxs),
                "loop_threshold":     LOOP_THRESHOLD,
                "window_size":        LOOP_WINDOW,
                "rule_version":       "v0.2",
            },
        }
    material_between = False
    for t in window:
        if matched_idxs[0] < t["turn_idx"] < matched_idxs[-1] and turn_makes_material_change(t):
            material_between = True
            break
    if material_between:
        return {
            "applicable":          True,
            "verdict":             "ALLOW",
            "intervention_action": "suppress_retry",
            "evidence": {
                "matched_turn_count":   len(matched_idxs),
                "material_action_seen": True,
                "rule_version":         "v0.2",
            },
        }
    return {
        "applicable":          True,
        "verdict":             "SUPPRESS",
        "intervention_action": "suppress_retry",
        "evidence": {
            "matched_turn_count":   len(matched_idxs),
            "matched_turn_idxs":    matched_idxs,
            "shared_tools":         sorted(eval_sig["tools"]),
            "shared_exception_classes": sorted(eval_sig["exception_classes"]),
            "error_word_bag_size":  len(eval_sig["error_words"]),
            "rule_version":         "v0.2",
        },
    }


def rule_stale_deploy_prior(eval_turn: dict, state: dict) -> dict | None:
    """§3.2 v0.2 (A-002): fire when user_approval_required active AND weight ≥ 0.7."""
    if not turn_is_deploy_action(eval_turn):
        return None
    deploy_pending = latest_belief(state, "deploy_pending", statuses=("active",))
    if deploy_pending is None:
        return {
            "applicable":          True,
            "verdict":             "ALLOW",
            "intervention_action": "suppress_deploy",
            "evidence":            {"deploy_pending_active": False, "rule_version": "v0.2"},
        }
    uar = latest_belief(state, "user_approval_required", statuses=("active",))
    if uar is None:
        return {
            "applicable":          True,
            "verdict":             "ALLOW",
            "intervention_action": "suppress_deploy",
            "evidence": {
                "deploy_pending_active":            True,
                "user_approval_required_active":    False,
                "rule_version":                     "v0.2",
            },
        }
    if uar["weight"] >= INTERVENTION_AUTHORITY_THR:
        return {
            "applicable":          True,
            "verdict":             "SUPPRESS",
            "intervention_action": "suppress_deploy",
            "evidence": {
                "deploy_pending_active":          True,
                "deploy_pending_weight":          deploy_pending["weight"],
                "user_approval_required_active":  True,
                "user_approval_required_weight":  uar["weight"],
                "authority_threshold":            INTERVENTION_AUTHORITY_THR,
                "rule_version":                   "v0.2",
            },
        }
    return {
        "applicable":          True,
        "verdict":             "ALLOW",
        "intervention_action": "suppress_deploy",
        "evidence": {
            "deploy_pending_active":          True,
            "user_approval_required_active":  True,
            "user_approval_required_weight":  uar["weight"],
            "below_authority_threshold":      True,
            "rule_version":                   "v0.2",
        },
    }


def rule_stale_pipeline_prior(eval_turn: dict, state: dict, eval_ts: datetime) -> dict | None:
    """§3.3 v0.2 (A-005): threshold = 30 min."""
    if turn_is_status_check(eval_turn):
        return None
    pipeline_running = latest_belief(state, "pipeline_running", statuses=("active",))
    if pipeline_running is None:
        return None
    last_refresh = parse_ts(pipeline_running["last_refresh_ts"])
    if last_refresh is None:
        return None
    age_seconds = (eval_ts - last_refresh).total_seconds()
    base = {
        "pipeline_age_seconds":      age_seconds,
        "stale_threshold_seconds":   STALE_PIPELINE_SECONDS,
        "pipeline_running_weight":   pipeline_running["weight"],
        "rule_version":              "v0.2",
    }
    if age_seconds <= STALE_PIPELINE_SECONDS:
        return {
            "applicable":          True,
            "verdict":             "ALLOW",
            "intervention_action": "require_status_check",
            "evidence":            base,
        }
    base["last_refresh_ts"] = pipeline_running["last_refresh_ts"]
    return {
        "applicable":          True,
        "verdict":             "SUPPRESS",
        "intervention_action": "require_status_check",
        "evidence":            base,
    }


def _fix_anchor_context(fix_instance: dict, session_by_idx: dict) -> dict:
    """Pull touched files + Bash first-tokens from the fix's birth + refresh turns."""
    touched_files: set[str] = set()
    cmd_tokens:    set[str] = set()
    anchor_idxs = []
    for ev in fix_instance.get("events", []):
        if ev.get("event_type") in ("born", "refreshed"):
            anchor_idxs.append(ev.get("turn_idx"))
    for tidx in anchor_idxs:
        anchor_turn = session_by_idx.get(tidx)
        if not anchor_turn:
            continue
        touched_files |= extract_file_paths(anchor_turn)
        cmd_tokens    |= extract_command_first_tokens(anchor_turn)
    return {"touched_files": touched_files, "cmd_tokens": cmd_tokens}


def rule_contradicted_fix_prior(
    eval_turn: dict,
    state: dict,
    session_by_idx: dict,
) -> dict | None:
    """§3.4 v0.2 (A-004): tool_error during active fix_attempted with context overlap."""
    fix = latest_belief(state, "fix_attempted", statuses=("active",))
    if fix is None:
        return None  # cannot be applicable without an active fix
    # Determine failure evidence categories
    eval_files       = extract_file_paths(eval_turn)
    eval_cmd_tokens  = extract_command_first_tokens(eval_turn)
    is_val, vstatus  = turn_is_validation_v02(eval_turn)
    error_text       = _result_text(eval_turn).lower()
    has_err          = has_tool_error(eval_turn)
    has_error_indic  = bool(ERROR_INDICATOR_RE.search(error_text)) if error_text else False
    # (c) validation context — covered if matched valdation pattern OR error indicators OR any tool_error
    in_validation_ctx = (
        (is_val and vstatus == "FAIL")
        or (has_err)
        or (has_error_indic)
    )
    if not (has_err or has_error_indic or (is_val and vstatus == "FAIL")):
        return None  # no failure evidence — rule not applicable
    # Anchor context — touched files + cmd tokens from fix's birth+refresh
    anchor_ctx = _fix_anchor_context(fix, session_by_idx)
    file_overlap = bool(eval_files & anchor_ctx["touched_files"])
    cmd_overlap  = bool(eval_cmd_tokens & anchor_ctx["cmd_tokens"])
    # (a) and (b): direct context overlap
    direct_overlap = file_overlap or cmd_overlap
    # If we have neither direct overlap nor validation context, not applicable
    if not (direct_overlap or in_validation_ctx):
        return None
    # Applicability is met; verdict is always SUPPRESS in v0.2 design (retire fix prior)
    return {
        "applicable":          True,
        "verdict":             "SUPPRESS",
        "intervention_action": "retire_fix_prior",
        "evidence": {
            "fix_attempted_active":   True,
            "fix_attempted_weight":   fix["weight"],
            "file_overlap":           file_overlap,
            "cmd_overlap":            cmd_overlap,
            "validation_match":       bool(is_val and vstatus == "FAIL"),
            "has_tool_error":         has_err,
            "has_error_indicator":    has_error_indic,
            "rule_version":           "v0.2",
        },
    }


# ─── Main ────────────────────────────────────────────────────────────────────

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
    for sid in by_session:
        by_session[sid].sort(key=lambda t: t["turn_idx"])
    return by_session


def load_sample() -> dict[str, set[int]]:
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

    print("Loading classified sessions…")
    sessions = load_sessions()
    print(f"  loaded {sum(len(v) for v in sessions.values()):,} turns across {len(sessions)} sessions")

    out_records: list[dict] = []
    verdict_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    applicable_counts: dict[str, int] = defaultdict(int)

    print("\nEvaluating sample against v0.2 rules…")
    for sid, turn_set in sample_idxs.items():
        session_turns = sessions.get(sid, [])
        session_timelines = timelines.get(sid, [])
        if not session_turns:
            continue
        by_idx = {t["turn_idx"]: t for t in session_turns}
        for tidx in sorted(turn_set):
            eval_turn = by_idx.get(tidx)
            if eval_turn is None:
                continue
            eval_ts = parse_ts(eval_turn.get("timestamp", ""))
            if eval_ts is None:
                continue
            prior_turns = [t for t in session_turns if t["turn_idx"] < tidx]
            state = reconstruct_state_at(session_timelines, eval_ts)
            rules = {
                "repeated_failure_loop":   rule_repeated_failure_loop(eval_turn, prior_turns),
                "stale_deploy_prior":      rule_stale_deploy_prior(eval_turn, state),
                "stale_pipeline_prior":    rule_stale_pipeline_prior(eval_turn, state, eval_ts),
                "contradicted_fix_prior":  rule_contradicted_fix_prior(eval_turn, state, by_idx),
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
            f.write(json.dumps(r, default=lambda o: sorted(o) if isinstance(o, set) else str(o)) + "\n")

    print("\n" + "=" * 72)
    print("INTERVENTION VERDICT COUNTS (rules v0.2)")
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
