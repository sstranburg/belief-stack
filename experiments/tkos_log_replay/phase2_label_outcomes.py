#!/usr/bin/env python3
"""
F-023 Phase 2 step 4: TP / FP / FN / TN labeling.

Per PHASE2_PRE_REGISTRATION_v0.1.md §5:
  - Look-ahead window: 5 turns after the evaluation point
  - "User correction" patterns:
      ^no,?\\s+(that|that's|this|wait)\\b
      \\bwrong\\b
      \\bthat'?s not right\\b
      \\blet me correct\\b
      \\bactually,?\\s+(no|that|i mean)\\b
      \\bcan you fix\\b
  - "Loop continued": further tool_error within 5-turn window for same signature
  - UNCERTAIN per I-004: final turn of session (no look-ahead available)

Truth table (§5.2):
  SUPPRESS + problem      → TP
  SUPPRESS + no problem   → FP
  ALLOW    + problem      → FN
  ALLOW    + no problem   → TN

Inputs:
  data/phase2_intervention_verdicts.jsonl
  data/sessions_classified.jsonl

Output:
  data/phase2_labeled_outcomes.jsonl
"""

from __future__ import annotations

import json
import pathlib
import re
from collections import defaultdict
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent
VERDICTS_PATH = ROOT / "data" / "phase2_intervention_verdicts.jsonl"
SESSIONS_PATH = ROOT / "data" / "sessions_classified.jsonl"
OUT_PATH      = ROOT / "data" / "phase2_labeled_outcomes.jsonl"

RULES_VERSION = "v0.1"
LOOKAHEAD_TURNS = 5

# §5.3 user-correction patterns
USER_CORRECTION = re.compile(
    r"\bno,?\s+(that|that's|this|wait)\b|"
    r"\bwrong\b|"
    r"\bthat'?s not right\b|"
    r"\blet me correct\b|"
    r"\bactually,?\s+(no|that|i mean)\b|"
    r"\bcan you fix\b",
    re.IGNORECASE,
)


def parse_ts(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def has_tool_error(turn: dict) -> bool:
    return any(tr.get("is_error") for tr in (turn.get("tool_results") or []))


def user_correction_in_turn(turn: dict) -> bool:
    if turn.get("role") != "user":
        return False
    text = (turn.get("text") or "")
    if isinstance(text, list):
        text = " ".join(t.get("text", "") if isinstance(t, dict) else str(t) for t in text)
    return bool(USER_CORRECTION.search(text))


def extract_first_token(cmd: str) -> str | None:
    cmd = cmd.strip()
    if not cmd:
        return None
    return cmd.split(None, 1)[0].lower()


def assistant_bash_first_tokens(turn: dict) -> set[str]:
    out = set()
    for tu in turn.get("tool_uses", []) or []:
        if tu.get("name") == "Bash":
            inp = tu.get("input_summary", "") or ""
            ft = extract_first_token(inp)
            if ft:
                out.add(ft)
    return out


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


def load_verdicts() -> list[dict]:
    out = []
    with VERDICTS_PATH.open() as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def detect_problem(
    verdict: dict,
    eval_turn: dict,
    follow_turns: list[dict],
) -> tuple[bool, str | None]:
    """Return (problem_detected, why)."""
    # §5.3 user correction within window
    for ft in follow_turns:
        if user_correction_in_turn(ft):
            return True, "user_correction"
    # §5.3 further tool_error within window — for repeated_failure_loop, same signature
    rule = verdict.get("rule")
    if rule == "repeated_failure_loop":
        eval_tokens = assistant_bash_first_tokens(eval_turn)
        for ft in follow_turns:
            if has_tool_error(ft) and (assistant_bash_first_tokens(ft) & eval_tokens):
                return True, "loop_continued_same_command"
    # generic: any tool_error within window
    for ft in follow_turns:
        if has_tool_error(ft):
            return True, "tool_error_within_window"
    return False, None


def label_outcome(verdict_label: str, problem: bool) -> str:
    """§5.2 truth table."""
    if verdict_label == "SUPPRESS" and problem:
        return "TP"
    if verdict_label == "SUPPRESS" and not problem:
        return "FP"
    if verdict_label == "ALLOW" and problem:
        return "FN"
    if verdict_label == "ALLOW" and not problem:
        return "TN"
    return "UNCERTAIN"


def main() -> None:
    print("Loading verdicts…")
    verdicts = load_verdicts()
    print(f"  loaded {len(verdicts):,} verdicts")

    print("Loading classified sessions…")
    sessions = load_sessions()
    print(f"  loaded {sum(len(v) for v in sessions.values()):,} turns across {len(sessions)} sessions")

    out_records: list[dict] = []
    label_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    uncertain_counts: dict[str, int] = defaultdict(int)

    print(f"\nLabeling {len(verdicts):,} verdicts with §5.2 truth table…")
    # Index session turns by (session_id, turn_idx) for fast lookup
    turn_index: dict[tuple[str, int], dict] = {}
    session_turn_lists: dict[str, list[dict]] = sessions
    for sid, turns in sessions.items():
        for t in turns:
            turn_index[(sid, t["turn_idx"])] = t

    for v in verdicts:
        sid = v["session_id"]
        tidx = v["turn_idx"]
        rule = v["rule"]
        verdict_label = v["verdict"]
        eval_turn = turn_index.get((sid, tidx))
        if eval_turn is None:
            continue
        session_turns = session_turn_lists[sid]
        # Find position of eval turn
        pos = next((i for i, t in enumerate(session_turns) if t["turn_idx"] == tidx), None)
        if pos is None:
            continue
        follow_turns = session_turns[pos + 1 : pos + 1 + LOOKAHEAD_TURNS]
        # I-004: UNCERTAIN iff no follow-up turns in session
        if len(follow_turns) == 0:
            label = "UNCERTAIN"
            problem = None
            why = "no_followup_turns_in_session"
        else:
            problem, why = detect_problem(v, eval_turn, follow_turns)
            label = label_outcome(verdict_label, problem)
        out_records.append({
            "session_id":   sid,
            "turn_idx":     tidx,
            "uuid":         v.get("uuid"),
            "ts":           v.get("ts"),
            "l1_region":    v.get("l1_region"),
            "rule":         rule,
            "verdict":      verdict_label,
            "intervention_action": v.get("intervention_action"),
            "label":        label,
            "problem":      problem,
            "why":          why,
            "lookahead_n":  len(follow_turns),
        })
        if label == "UNCERTAIN":
            uncertain_counts[rule] += 1
        else:
            label_counts[rule][label] += 1

    print(f"\nWriting {OUT_PATH} ({len(out_records):,} labels)…")
    with OUT_PATH.open("w") as f:
        for r in out_records:
            f.write(json.dumps(r) + "\n")

    print("\n" + "=" * 72)
    print("OUTCOME LABEL COUNTS PER RULE (rules v0.1, lookahead = 5 turns)")
    print("=" * 72)
    print(f"  {'rule':30s}  {'TP':>5} {'FP':>5} {'FN':>5} {'TN':>5} {'UNCERT':>7}")
    print("  " + "-" * 70)
    for rule in [
        "repeated_failure_loop",
        "stale_deploy_prior",
        "stale_pipeline_prior",
        "contradicted_fix_prior",
    ]:
        tp = label_counts[rule].get("TP", 0)
        fp = label_counts[rule].get("FP", 0)
        fn = label_counts[rule].get("FN", 0)
        tn = label_counts[rule].get("TN", 0)
        u  = uncertain_counts[rule]
        print(f"  {rule:30s}  {tp:>5} {fp:>5} {fn:>5} {tn:>5} {u:>7}")

    print("\n" + "=" * 72)
    print("DETECTION RATE = TP / (TP + FN);  FALSE-POSITIVE RATE = FP / (FP + TN)")
    print("=" * 72)
    for rule in [
        "repeated_failure_loop",
        "stale_deploy_prior",
        "stale_pipeline_prior",
        "contradicted_fix_prior",
    ]:
        tp = label_counts[rule].get("TP", 0)
        fp = label_counts[rule].get("FP", 0)
        fn = label_counts[rule].get("FN", 0)
        tn = label_counts[rule].get("TN", 0)
        det = f"{tp / (tp + fn):.3f}" if (tp + fn) > 0 else "n/a (no positives)"
        fpr = f"{fp / (fp + tn):.3f}" if (fp + tn) > 0 else "n/a (no negatives)"
        print(f"  {rule:30s}  detection={det:>16s}   FPR={fpr:>16s}   (TP={tp}, FN={fn}, FP={fp}, TN={tn})")
    print()


if __name__ == "__main__":
    main()
