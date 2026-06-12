#!/usr/bin/env python3
"""
F-023 Phase 2 v0.2: TP/FP/FN/TN labeling.

Labeling logic is unchanged from v0.1 (§5 of pre-registration).
Inputs/outputs are parallel _v0_2 files.
"""

from __future__ import annotations

import json
import pathlib
import re
from collections import defaultdict
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent
VERDICTS_PATH = ROOT / "data" / "phase2_intervention_verdicts_v0_2.jsonl"
SESSIONS_PATH = ROOT / "data" / "sessions_classified.jsonl"
OUT_PATH      = ROOT / "data" / "phase2_labeled_outcomes_v0_2.jsonl"

LOOKAHEAD_TURNS = 5

USER_CORRECTION = re.compile(
    r"\bno,?\s+(that|that's|this|wait)\b|"
    r"\bwrong\b|"
    r"\bthat'?s not right\b|"
    r"\blet me correct\b|"
    r"\bactually,?\s+(no|that|i mean)\b|"
    r"\bcan you fix\b",
    re.IGNORECASE,
)


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def has_tool_error(turn):
    return any(tr.get("is_error") for tr in (turn.get("tool_results") or []))


def user_correction_in_turn(turn):
    if turn.get("role") != "user":
        return False
    text = turn.get("text") or ""
    if isinstance(text, list):
        text = " ".join(t.get("text", "") if isinstance(t, dict) else str(t) for t in text)
    return bool(USER_CORRECTION.search(text))


def assistant_bash_first_tokens(turn):
    out = set()
    for tu in turn.get("tool_uses", []) or []:
        if tu.get("name") == "Bash":
            inp = tu.get("input_summary", "") or ""
            tok = inp.strip().split(None, 1)[0].lower() if inp.strip() else ""
            if tok:
                out.add(tok)
    return out


def load_sessions():
    by_session = defaultdict(list)
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


def load_verdicts():
    out = []
    with VERDICTS_PATH.open() as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def detect_problem(verdict, eval_turn, follow_turns):
    for ft in follow_turns:
        if user_correction_in_turn(ft):
            return True, "user_correction"
    if verdict.get("rule") == "repeated_failure_loop":
        eval_tokens = assistant_bash_first_tokens(eval_turn)
        for ft in follow_turns:
            if has_tool_error(ft) and (assistant_bash_first_tokens(ft) & eval_tokens):
                return True, "loop_continued_same_command"
    for ft in follow_turns:
        if has_tool_error(ft):
            return True, "tool_error_within_window"
    return False, None


def label_outcome(verdict_label, problem):
    if verdict_label == "SUPPRESS" and problem:
        return "TP"
    if verdict_label == "SUPPRESS" and not problem:
        return "FP"
    if verdict_label == "ALLOW" and problem:
        return "FN"
    if verdict_label == "ALLOW" and not problem:
        return "TN"
    return "UNCERTAIN"


def main():
    print("Loading verdicts (v0.2)…")
    verdicts = load_verdicts()
    print(f"  loaded {len(verdicts):,} verdicts")

    print("Loading classified sessions…")
    sessions = load_sessions()

    turn_index = {(sid, t["turn_idx"]): t for sid, ts in sessions.items() for t in ts}

    out_records = []
    label_counts = defaultdict(lambda: defaultdict(int))
    uncertain_counts = defaultdict(int)

    print(f"\nLabeling {len(verdicts):,} verdicts (lookahead={LOOKAHEAD_TURNS})…")
    for v in verdicts:
        sid = v["session_id"]
        tidx = v["turn_idx"]
        rule = v["rule"]
        verdict_label = v["verdict"]
        eval_turn = turn_index.get((sid, tidx))
        if eval_turn is None:
            continue
        session_turns = sessions[sid]
        pos = next((i for i, t in enumerate(session_turns) if t["turn_idx"] == tidx), None)
        if pos is None:
            continue
        follow_turns = session_turns[pos + 1 : pos + 1 + LOOKAHEAD_TURNS]
        if len(follow_turns) == 0:
            label = "UNCERTAIN"
            problem = None
            why = "no_followup_turns_in_session"
        else:
            problem, why = detect_problem(v, eval_turn, follow_turns)
            label = label_outcome(verdict_label, problem)
        out_records.append({
            "session_id":          sid,
            "turn_idx":            tidx,
            "uuid":                v.get("uuid"),
            "ts":                  v.get("ts"),
            "l1_region":           v.get("l1_region"),
            "rule":                rule,
            "verdict":             verdict_label,
            "intervention_action": v.get("intervention_action"),
            "label":               label,
            "problem":             problem,
            "why":                 why,
            "lookahead_n":         len(follow_turns),
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
    print("OUTCOME LABEL COUNTS PER RULE (rules v0.2)")
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
    print("DETECTION & FALSE-POSITIVE RATES")
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
        det = f"{tp/(tp+fn):.3f}" if (tp+fn) > 0 else "n/a"
        fpr = f"{fp/(fp+tn):.3f}" if (fp+tn) > 0 else "n/a"
        print(f"  {rule:30s}  detection={det:>8}   FPR={fpr:>8}   (TP={tp}, FN={fn}, FP={fp}, TN={tn})")
    print()


if __name__ == "__main__":
    main()
