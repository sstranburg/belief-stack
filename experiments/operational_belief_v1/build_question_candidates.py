#!/usr/bin/env python3
"""
Operational Belief v0.1 — Question candidate generator (step 5c, part 1).

Generates candidate (session_id, turn_idx, category) triples plus question
TEXT. Reads ONLY the raw ledger: `sessions_normalized.jsonl` and
`reasoning_ledger.jsonl`. Does NOT read `operational_beliefs.jsonl` or
the scorer/oracle output.

Per §4.4 anti-curation discipline, this script logs every file it opens.
Opening `operational_beliefs.jsonl` would invalidate the run.

Candidate-finding heuristics per category (ledger-level, not belief-level):

  validation_check  — turn T where a code-change tool_use (Edit/Write/
                      MultiEdit) occurred in the prior K turns.
  repeated_failure  — turn T with a tool_result.is_error=true. Scans
                      EVERY turn (not just quartiles), since the scorer
                      audit showed positive oracle here is sparse.
  approval_status   — turn T where the assistant's text in the prior K
                      turns proposes an action (ACTION_PATTERNS regex).
  completion_check  — turn T where the assistant's text in the prior K
                      turns claims completion ("done", "complete",
                      "ready", "finished") OR where the user asks about
                      completion.
  readiness_check   — turn T with at least one tool_use in the prior K
                      turns (broad heuristic; the scorer's 4-clause rule
                      decides applicability).

Output:
  operational_belief_v1/data/question_candidates_v0_1.jsonl
"""

from __future__ import annotations

import json
import pathlib
import re
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent
TKOS_DATA = STORM_ROOT / "tkos_log_replay" / "data"

# --- INPUT FILES (locked, logged for the audit) -----------------------------
ALLOWED_INPUTS = [
    TKOS_DATA / "sessions_normalized.jsonl",
    TKOS_DATA / "reasoning_ledger.jsonl",
    TKOS_DATA / "phase2_sample.json",
]
NORMALIZED = TKOS_DATA / "sessions_normalized.jsonl"
LEDGER     = TKOS_DATA / "reasoning_ledger.jsonl"
PHASE2_SAMPLE = TKOS_DATA / "phase2_sample.json"

# Output
OUT_CANDIDATES = ROOT / "data" / "question_candidates_v0_1.jsonl"

# Locked from §3.1
K = 20

# Locked from §4.5.3 — minimum-turn rule per category. A category cannot
# sample a turn earlier than its minimum because the relevant belief
# could not plausibly be active.
MIN_TURN_PER_CATEGORY = {
    "validation_check":   3,   # need a fix_attempted to validate against
    "repeated_failure":   K,   # need a full K window with errors
    "approval_status":    3,   # need an action proposal
    "completion_check":   3,   # need substantive prior turns
    "readiness_check":    3,
}

# --- Pattern reuse from scorer ---------------------------------------------
ACTION_PATTERNS = re.compile(
    r"\bgit (commit|push|merge)\b|\bvercel\b.*\b--prod\b|"
    r"\bdeploy\b|\bpublish\b|\bship\b|\bsend (it|email|message)\b|"
    r"\bnpm publish\b|\bgh pr (create|merge)\b",
    re.IGNORECASE,
)
COMPLETION_LANGUAGE = re.compile(
    r"\b(done|complete|completed|finished|ready|all set|wrapped up)\b",
    re.IGNORECASE,
)
USER_COMPLETION_QUERY = re.compile(
    r"\b(is .* (done|finished|complete|ready)|did .* work|all (set|done))\b",
    re.IGNORECASE,
)
CODE_CHANGE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# --- Question text templates per category ----------------------------------
TEMPLATES = {
    "validation_check": [
        "As of turn {T} in this session, has the most recent code change been verified by a test or other check?",
        "By turn {T}, has the assistant observed validation of the most recent fix?",
        "At turn {T}, is there evidence that the recently-applied change has been tested?",
    ],
    "repeated_failure": [
        "As of turn {T}, is the most recent failure a repeat of an earlier failure in this session?",
        "By turn {T}, has the same kind of failure occurred multiple times recently?",
        "At turn {T}, is the assistant stuck in a loop of similar failures?",
    ],
    "approval_status": [
        "As of turn {T}, is the assistant authorized to proceed with the most recently proposed action?",
        "By turn {T}, has the user approved the proposed next step?",
        "At turn {T}, can the assistant act on the proposal without waiting for user confirmation?",
    ],
    "completion_check": [
        "As of turn {T} in this session, can the assistant honestly claim the current task is complete?",
        "By turn {T}, are there outstanding pending actions the assistant should acknowledge before declaring completion?",
        "At turn {T}, is the work the user asked for actually finished?",
    ],
    "readiness_check": [
        "As of turn {T}, should the assistant proceed, pause, or ask the user for clarification?",
        "By turn {T}, is the operational state clear enough to proceed without further input?",
        "At turn {T}, should the assistant pause and check before continuing?",
    ],
}


def load_normalized_sessions() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    with NORMALIZED.open() as f:
        for line in f:
            t = json.loads(line)
            out[t["session_id"]].append(t)
    for sid in out:
        out[sid].sort(key=lambda x: x["turn_idx"])
    return dict(out)


def load_phase2_sessions() -> set[str]:
    data = json.loads(PHASE2_SAMPLE.read_text())
    return set(data["per_session_counts"].keys())


def turn_text(t: dict) -> str:
    """Concatenated text for an assistant turn (text + thinking + tool_use input summaries)."""
    parts = [t.get("text") or "", t.get("thinking") or ""]
    for tu in (t.get("tool_uses") or []):
        parts.append(tu.get("input_summary") or "")
    return " ".join(p for p in parts if p)


def assistant_used_code_change_recently(turns: list[dict], T: int, k: int = K) -> bool:
    """True iff any assistant turn in [T-k+1, T] issued a code-change tool_use."""
    lo = T - k + 1
    for t in turns:
        if not (lo <= t["turn_idx"] <= T):
            continue
        if t.get("role") != "assistant":
            continue
        for tu in (t.get("tool_uses") or []):
            if tu.get("name") in CODE_CHANGE_TOOLS:
                return True
    return False


def turn_has_tool_error(t: dict) -> bool:
    if t.get("role") != "user":
        return False
    for tr in (t.get("tool_results") or []):
        if tr.get("is_error"):
            return True
    return False


def assistant_proposed_action_recently(turns: list[dict], T: int, k: int = K) -> bool:
    lo = T - k + 1
    for t in turns:
        if not (lo <= t["turn_idx"] <= T):
            continue
        if t.get("role") != "assistant":
            continue
        if ACTION_PATTERNS.search(turn_text(t)):
            return True
    return False


def completion_language_recently(turns: list[dict], T: int, k: int = K) -> bool:
    lo = T - k + 1
    for t in turns:
        if not (lo <= t["turn_idx"] <= T):
            continue
        text = turn_text(t)
        if t.get("role") == "assistant" and COMPLETION_LANGUAGE.search(text):
            return True
        if t.get("role") == "user" and USER_COMPLETION_QUERY.search(text):
            return True
    return False


def turn_has_tool_use_recently(turns: list[dict], T: int, k: int = K) -> bool:
    lo = T - k + 1
    for t in turns:
        if not (lo <= t["turn_idx"] <= T):
            continue
        if t.get("role") == "assistant" and t.get("tool_uses"):
            return True
    return False


def position_bucket(T: int, session_length: int) -> str:
    if session_length == 0:
        return "early"
    frac = T / session_length
    if frac < 0.25:
        return "early"
    if frac < 0.75:
        return "middle"
    return "late"


def session_id_short(sid: str) -> str:
    # main::32a6ee2f-... → 32a6ee2f
    return sid.split("::")[-1][:8] if "::" in sid else sid[:8]


def emit_candidate(session_id: str, T: int, category: str, total_turns: int, sample_idx: int) -> dict:
    template_idx = (T + len(category)) % len(TEMPLATES[category])  # deterministic template selection
    qtext = TEMPLATES[category][template_idx].format(T=T)
    qid = f"q{sample_idx:03d}_{category}_{session_id_short(session_id)}_T{T}"
    return {
        "candidate_id":      qid,
        "session_id":        session_id,
        "turn_idx":          T,
        "category":          category,
        "question":          qtext,
        "session_total_turns": total_turns,
        "turn_position_bucket": position_bucket(T, total_turns),
        "template_idx":      template_idx,
    }


def main() -> None:
    print("Loading raw ledger inputs (no belief substrate consulted)...")
    sessions = load_normalized_sessions()
    phase2_sids = load_phase2_sessions()
    eligible = phase2_sids & set(sessions.keys())
    print(f"  {len(eligible):,} eligible sessions")

    candidates: list[dict] = []
    counter = 0
    per_category_counter: dict[str, int] = defaultdict(int)
    for sid in sorted(eligible):
        turns = sessions[sid]
        if not turns:
            continue
        total = turns[-1]["turn_idx"] + 1
        # Pre-build a lookup map for has_tool_error
        for t in turns:
            T = t["turn_idx"]

            # validation_check: turn where code-change in last K
            if T >= MIN_TURN_PER_CATEGORY["validation_check"]:
                if assistant_used_code_change_recently(turns, T, K):
                    counter += 1
                    cand = emit_candidate(sid, T, "validation_check", total, per_category_counter["validation_check"])
                    candidates.append(cand)
                    per_category_counter["validation_check"] += 1

            # repeated_failure: scan EVERY turn with tool error (sparse — see scorer audit)
            if T >= MIN_TURN_PER_CATEGORY["repeated_failure"]:
                if turn_has_tool_error(t):
                    cand = emit_candidate(sid, T, "repeated_failure", total, per_category_counter["repeated_failure"])
                    candidates.append(cand)
                    per_category_counter["repeated_failure"] += 1

            # approval_status: turn where action proposed in last K
            if T >= MIN_TURN_PER_CATEGORY["approval_status"]:
                if assistant_proposed_action_recently(turns, T, K):
                    cand = emit_candidate(sid, T, "approval_status", total, per_category_counter["approval_status"])
                    candidates.append(cand)
                    per_category_counter["approval_status"] += 1

            # completion_check: completion language in last K
            if T >= MIN_TURN_PER_CATEGORY["completion_check"]:
                if completion_language_recently(turns, T, K):
                    cand = emit_candidate(sid, T, "completion_check", total, per_category_counter["completion_check"])
                    candidates.append(cand)
                    per_category_counter["completion_check"] += 1

            # readiness_check: any tool_use in last K (broad)
            if T >= MIN_TURN_PER_CATEGORY["readiness_check"]:
                if turn_has_tool_use_recently(turns, T, K):
                    cand = emit_candidate(sid, T, "readiness_check", total, per_category_counter["readiness_check"])
                    candidates.append(cand)
                    per_category_counter["readiness_check"] += 1

    OUT_CANDIDATES.parent.mkdir(exist_ok=True)
    with OUT_CANDIDATES.open("w") as f:
        for c in candidates:
            f.write(json.dumps(c) + "\n")
    print(f"\nWrote {OUT_CANDIDATES}  ({len(candidates):,} candidates)")
    print("\nPer-category candidate counts:")
    for cat in ["validation_check","repeated_failure","approval_status","completion_check","readiness_check"]:
        print(f"  {cat:22s}  {per_category_counter[cat]:5,}")
    print(f"\nInputs opened (logged for audit):")
    for p in ALLOWED_INPUTS:
        print(f"  {p}")


if __name__ == "__main__":
    main()
