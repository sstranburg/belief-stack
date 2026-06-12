#!/usr/bin/env python3
"""
F-023 Phase 2 step 2: state-level belief tracker.

Walks each session's full turn sequence and maintains timelines of the
8 state-level beliefs defined in PHASE2_PRE_REGISTRATION_v0.1.md §2.

Each belief is identified by (belief_name, anchor). For v0.1, the
anchor is the UUID of the turn that birthed the belief.

Per the pre-registration, all 8 beliefs use exponential decay against
their per-belief half-life:

  weight(t) = initial_confidence * exp(-ln(2) * elapsed_seconds / half_life_seconds)

Active threshold:                 weight >= 0.3
Suppressed-threshold (=v0.2 rename: intervention authority threshold): weight >= 0.7
Stale → automatic retirement when weight < 0.3 with no refresh.

Output:
  data/phase2_belief_timelines.jsonl
    one record per belief instance over its lifecycle:
      {session_id, belief_name, anchor_uuid, birth_ts, last_refresh_ts,
       retired_ts, retired_reason, events:[{turn_idx, event_type, ts}]}
"""

from __future__ import annotations

import json
import math
import pathlib
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable

ROOT = pathlib.Path(__file__).resolve().parent
IN_PATH = ROOT / "data" / "sessions_classified.jsonl"
OUT_PATH = ROOT / "data" / "phase2_belief_timelines.jsonl"

RULES_VERSION = "v0.1"
LN2 = 0.6931471805599453

# Thresholds (PHASE2_PRE_REGISTRATION_v0.1.md §2.9)
ACTIVE_THRESHOLD = 0.3
SUPPRESSED_THRESHOLD = 0.7  # see PHASE2_AMENDMENTS_FOR_V02.md A-001 (rename for v0.2)
INITIAL_CONFIDENCE = 1.0


# ─── Belief specifications (PRE-REGISTERED §2) ──────────────────────────────

BELIEF_SPECS = {
    "pipeline_running": {
        "half_life_seconds": 30 * 60,        # 30 min
    },
    "pipeline_failed": {
        "half_life_seconds": 60 * 60,        # 60 min
    },
    "issue_under_diagnosis": {
        "half_life_seconds": 45 * 60,        # 45 min
    },
    "fix_attempted": {
        "half_life_seconds": 15 * 60,        # 15 min
    },
    "validation_pending": {
        "half_life_seconds": 10 * 60,        # 10 min
    },
    "deploy_pending": {
        "half_life_seconds": 60 * 60,        # 60 min
    },
    "report_ready": {
        "half_life_seconds": 4 * 60 * 60,    # 4 hours
    },
    "user_approval_required": {
        "half_life_seconds": 30 * 60,        # 30 min
    },
}


# ─── Pattern banks (from §2 birth/refresh/retire/contradict conditions) ─────
# These are exact transcriptions of the pre-registered conditions. No
# liberal interpretation. Ambiguities go to PHASE2_ISSUES_LOG.md.

# Long-running scripts that birth pipeline_running
PIPELINE_SCRIPTS = re.compile(
    r"scripts/run_pipeline\.py|scripts/build_backtest_history\.py|"
    r"generate_ai_compass\.py|generate_actor_detail\.py|"
    r"generate_leaderboard\.py|run_shadow_tracking\.py",
    re.IGNORECASE,
)

PIPELINE_STATUS_CHECK = re.compile(
    r"\bps aux\b.*pipeline|\btail .*\.output\b|\btail -.*log\b",
    re.IGNORECASE,
)

PIPELINE_COMPLETE_HINT = re.compile(
    r"pipeline complete|✅ pipeline|background command .* completed|exit code 0",
    re.IGNORECASE,
)

PIPELINE_FAILURE_HINT = re.compile(
    r"pipeline.{0,30}failed|exit code [1-9]|status.{0,5}failed|traceback",
    re.IGNORECASE,
)

# Substantive change tools/patterns for fix_attempted (must follow issue_under_diagnosis)
FIX_TOOLS = {"Edit", "Write", "MultiEdit"}

# Validation tool patterns (used by validation_pending refresh/retire)
VALIDATION_PATTERNS = re.compile(
    r"\bpytest\b|\bnpm test\b|\btsc\b|--check\b|--validate\b|--noEmit\b|"
    r"\bgit (status|diff)\b",
    re.IGNORECASE,
)

# Deploy-action patterns (deploy_pending retirement)
DEPLOY_ACTION = re.compile(
    r"\bgit push\b|\bvercel\b.*--prod\b",
    re.IGNORECASE,
)

# Deploy intent (user side) — same as §5.3 pre-registered
DEPLOY_INTENT = re.compile(
    r"^\s*deploy\s*!?\s*$|^\s*ship it\s*!?\s*$|"
    r"\b(deploy|ship) (it|now|when|please)\b",
    re.IGNORECASE | re.MULTILINE,
)

# User explicit hold
DEPLOY_HOLD = re.compile(
    r"^\s*(wait|not yet|hold|don'?t|pause)\b",
    re.IGNORECASE | re.MULTILINE,
)

# Report file extensions
REPORT_FILE_PATTERN = re.compile(r"\.(html|pdf|md)$", re.IGNORECASE)

# User correction patterns (per §5.3, also used for contradiction)
USER_CORRECTION = re.compile(
    r"\bno,?\s+(that|that's|this|wait)\b|\bwrong\b|"
    r"\bthat'?s not right\b|\blet me correct\b|"
    r"\bactually,?\s+(no|that|i mean)\b|\bcan you fix\b",
    re.IGNORECASE,
)


# ─── Belief instance ─────────────────────────────────────────────────────────

class BeliefInstance:
    """One live belief — born, possibly refreshed, eventually retired."""
    __slots__ = (
        "belief_name", "anchor_uuid", "session_id",
        "birth_ts", "last_refresh_ts",
        "retired_ts", "retired_reason",
        "events",
    )

    def __init__(self, belief_name: str, anchor_uuid: str, session_id: str,
                 birth_ts: datetime, turn_idx: int):
        self.belief_name = belief_name
        self.anchor_uuid = anchor_uuid
        self.session_id = session_id
        self.birth_ts = birth_ts
        self.last_refresh_ts = birth_ts
        self.retired_ts: datetime | None = None
        self.retired_reason: str | None = None
        self.events: list[dict] = [{
            "turn_idx": turn_idx, "event_type": "born",
            "ts": birth_ts.isoformat(),
        }]

    @property
    def active(self) -> bool:
        return self.retired_ts is None

    def refresh(self, ts: datetime, turn_idx: int, source: str) -> None:
        self.last_refresh_ts = ts
        self.events.append({
            "turn_idx": turn_idx, "event_type": "refreshed",
            "ts": ts.isoformat(), "source": source,
        })

    def retire(self, ts: datetime, turn_idx: int, reason: str) -> None:
        if not self.active:
            return
        self.retired_ts = ts
        self.retired_reason = reason
        self.events.append({
            "turn_idx": turn_idx, "event_type": "retired",
            "ts": ts.isoformat(), "reason": reason,
        })

    def contradict(self, ts: datetime, turn_idx: int, source: str) -> None:
        if not self.active:
            return
        self.retired_ts = ts
        self.retired_reason = "contradicted"
        self.events.append({
            "turn_idx": turn_idx, "event_type": "contradicted",
            "ts": ts.isoformat(), "source": source,
        })

    def weight_at(self, ts: datetime) -> float:
        """Current authority weight using exponential decay from last_refresh_ts."""
        if not self.active:
            return 0.0
        spec = BELIEF_SPECS[self.belief_name]
        elapsed = (ts - self.last_refresh_ts).total_seconds()
        if elapsed <= 0:
            return INITIAL_CONFIDENCE
        half_life = spec["half_life_seconds"]
        return INITIAL_CONFIDENCE * math.exp(-LN2 * elapsed / half_life)

    def to_dict(self) -> dict:
        return {
            "session_id":       self.session_id,
            "belief_name":      self.belief_name,
            "anchor_uuid":      self.anchor_uuid,
            "birth_ts":         self.birth_ts.isoformat(),
            "last_refresh_ts":  self.last_refresh_ts.isoformat(),
            "retired_ts":       self.retired_ts.isoformat() if self.retired_ts else None,
            "retired_reason":   self.retired_reason,
            "events":           self.events,
            "half_life_seconds": BELIEF_SPECS[self.belief_name]["half_life_seconds"],
        }


# ─── Per-session belief walker ──────────────────────────────────────────────

def parse_ts(s: str) -> datetime | None:
    if not s: return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def assistant_bash_summaries(turn: dict) -> list[str]:
    """Return all Bash command summaries from an assistant turn."""
    out = []
    for tu in turn.get("tool_uses", []) or []:
        if tu.get("name") == "Bash":
            out.append(tu.get("input_summary", "") or "")
    return out


def has_tool_error(turn: dict) -> bool:
    return any(tr.get("is_error") for tr in (turn.get("tool_results") or []))


def turn_makes_substantive_change(turn: dict) -> bool:
    """For fix_attempted birth: assistant turn with an Edit/Write/MultiEdit."""
    return any(tu.get("name") in FIX_TOOLS for tu in (turn.get("tool_uses") or []))


def turn_is_validation(turn: dict) -> tuple[bool, str | None]:
    """
    Returns (is_validation, validation_status).
    validation_status is "PASS"/"FAIL"/None.
    """
    cmds = assistant_bash_summaries(turn)
    is_val = any(VALIDATION_PATTERNS.search(c) for c in cmds)
    if not is_val:
        return False, None
    # Determine status from tool_results
    results = turn.get("tool_results") or []
    if any(r.get("is_error") for r in results):
        return True, "FAIL"
    if results:
        return True, "PASS"
    return True, None


def turn_is_pipeline_birth(turn: dict) -> bool:
    if turn.get("l1_region") != "pipeline_run":
        return False
    cmds = assistant_bash_summaries(turn)
    return any(PIPELINE_SCRIPTS.search(c) for c in cmds)


def turn_is_deploy_action(turn: dict) -> bool:
    cmds = assistant_bash_summaries(turn)
    return any(DEPLOY_ACTION.search(c) for c in cmds)


def turn_is_report_write(turn: dict) -> bool:
    for tu in turn.get("tool_uses", []) or []:
        if tu.get("name") in ("Write", "Edit"):
            inp = tu.get("input_summary", "") or ""
            if REPORT_FILE_PATTERN.search(inp) and "report" in inp.lower():
                return True
    return False


def walk_session(session_turns: list[dict]) -> list[BeliefInstance]:
    """
    Walk a session's turns chronologically, updating belief state.
    Returns the full list of BeliefInstances produced during the session.
    """
    instances: list[BeliefInstance] = []

    def active_of(name: str) -> BeliefInstance | None:
        # Most recent active instance of the named belief
        for inst in reversed(instances):
            if inst.belief_name == name and inst.active:
                return inst
        return None

    def auto_retire_stale(now_ts: datetime, turn_idx: int) -> None:
        """Apply §2.9 stale rule: weight < 0.3 with no refresh → automatic retirement."""
        for inst in instances:
            if inst.active and inst.weight_at(now_ts) < ACTIVE_THRESHOLD:
                inst.retire(now_ts, turn_idx, "stale_decay")

    for turn in session_turns:
        ts = parse_ts(turn.get("timestamp", ""))
        if ts is None:
            continue
        turn_idx = turn["turn_idx"]
        uuid = turn["uuid"]
        role = turn.get("role")
        text = turn.get("text", "") or ""
        region = turn.get("l1_region", "UNCLASSIFIED")

        # Apply stale-decay retirements before processing this turn's events
        auto_retire_stale(ts, turn_idx)

        # ──────────── pipeline_running ────────────────────────────────────
        if role == "assistant" and turn_is_pipeline_birth(turn):
            # Birth a new instance unless an active one already exists for the same script
            inst = active_of("pipeline_running")
            if inst is None:
                instances.append(BeliefInstance("pipeline_running", uuid, turn["session_id"], ts, turn_idx))

        if role == "assistant":
            cmds = assistant_bash_summaries(turn)
            for c in cmds:
                if PIPELINE_STATUS_CHECK.search(c):
                    pr = active_of("pipeline_running")
                    if pr: pr.refresh(ts, turn_idx, "status_check")
                if PIPELINE_COMPLETE_HINT.search(c) or any(
                    PIPELINE_COMPLETE_HINT.search(tr.get("output_summary", "") or "")
                    for tr in (turn.get("tool_results") or [])
                ):
                    pr = active_of("pipeline_running")
                    if pr: pr.retire(ts, turn_idx, "completion_evidence")

        # tool error in pipeline-tooling Bash → contradicts pipeline_running, births pipeline_failed
        if role == "user" and has_tool_error(turn):
            pr = active_of("pipeline_running")
            if pr:
                pr.contradict(ts, turn_idx, "tool_error_in_window")
                instances.append(BeliefInstance("pipeline_failed", uuid, turn["session_id"], ts, turn_idx))

        # ──────────── pipeline_failed ─────────────────────────────────────
        # Refresh on continued diagnosis; retire on successful new pipeline_run
        if region == "failure_diagnosis":
            pf = active_of("pipeline_failed")
            if pf: pf.refresh(ts, turn_idx, "continued_diagnosis")

        if role == "assistant" and turn_is_pipeline_birth(turn):
            pf = active_of("pipeline_failed")
            if pf:
                # Could later contradict if the retry succeeds; for now just refresh anchor
                pass

        # ──────────── issue_under_diagnosis ───────────────────────────────
        if region == "failure_diagnosis":
            iud = active_of("issue_under_diagnosis")
            if iud is None:
                instances.append(BeliefInstance("issue_under_diagnosis", uuid, turn["session_id"], ts, turn_idx))
            else:
                iud.refresh(ts, turn_idx, "continued_diagnosis")

        # transition to fix_attempted → retires issue_under_diagnosis
        if role == "assistant" and turn_makes_substantive_change(turn):
            iud = active_of("issue_under_diagnosis")
            if iud:
                iud.retire(ts, turn_idx, "transitioned_to_fix_attempted")

        # ──────────── fix_attempted ───────────────────────────────────────
        if role == "assistant" and turn_makes_substantive_change(turn):
            # Birth only if an issue_under_diagnosis was active OR very recently retired
            # (per pre-registration: "after issue_under_diagnosis was active")
            # We approximate "was active" as: instance exists at all for this session,
            # within the last 10 turns. To keep things simple, just check if any
            # issue_under_diagnosis exists at all in this session up to now.
            had_iud = any(i.belief_name == "issue_under_diagnosis" for i in instances)
            if had_iud:
                instances.append(BeliefInstance("fix_attempted", uuid, turn["session_id"], ts, turn_idx))

        # validation result → retires or contradicts fix_attempted
        if role == "assistant":
            is_val, val_status = turn_is_validation(turn)
            if is_val:
                fa = active_of("fix_attempted")
                if fa:
                    if val_status == "PASS":
                        fa.retire(ts, turn_idx, "validation_passed")
                    elif val_status == "FAIL":
                        fa.contradict(ts, turn_idx, "validation_failed")

        # ──────────── validation_pending ──────────────────────────────────
        # Birth: fix_attempted with no immediate validation in same/next turn
        # Simpler implementation: born when fix_attempted is born, retired
        # when next validation event observed.
        if role == "assistant" and turn_makes_substantive_change(turn):
            had_iud = any(i.belief_name == "issue_under_diagnosis" for i in instances)
            if had_iud:
                vp = active_of("validation_pending")
                if vp is None:
                    instances.append(BeliefInstance("validation_pending", uuid, turn["session_id"], ts, turn_idx))

        if role == "assistant":
            is_val, val_status = turn_is_validation(turn)
            if is_val:
                vp = active_of("validation_pending")
                if vp:
                    vp.retire(ts, turn_idx, f"validation_observed_{val_status}")

        # ──────────── report_ready ────────────────────────────────────────
        if role == "assistant" and (turn_is_report_write(turn) or region == "report_generation"):
            rr = active_of("report_ready")
            if rr is None:
                instances.append(BeliefInstance("report_ready", uuid, turn["session_id"], ts, turn_idx))
            else:
                rr.refresh(ts, turn_idx, "new_report_artifact")

        if role == "user" and USER_CORRECTION.search(text):
            rr = active_of("report_ready")
            if rr:
                rr.contradict(ts, turn_idx, "user_correction_on_report")

        # ──────────── deploy_pending ──────────────────────────────────────
        # Birth: report_ready active + deploy intent expressed
        if role == "user" and DEPLOY_INTENT.search(text):
            rr = active_of("report_ready")
            if rr is not None or active_of("deploy_pending") is None:
                instances.append(BeliefInstance("deploy_pending", uuid, turn["session_id"], ts, turn_idx))

        if role == "user" and DEPLOY_HOLD.search(text):
            dp = active_of("deploy_pending")
            if dp:
                dp.contradict(ts, turn_idx, "user_hold")

        if role == "assistant" and turn_is_deploy_action(turn):
            dp = active_of("deploy_pending")
            if dp:
                dp.retire(ts, turn_idx, "deploy_executed")

        # ──────────── user_approval_required ──────────────────────────────
        # Birth: assistant proposes risky action AND no prior approval
        # In v0.1 we treat: deploy-action assistant turn → if no recent
        # deploy intent from user (within 5 turns), birth approval_required
        if role == "assistant" and turn_is_deploy_action(turn):
            # Look at user-side history for recent approval
            # Simplification: if no DEPLOY_INTENT in any prior user turn for this
            # session in last 5 turns → birth user_approval_required.
            # Since we don't carry the prior_turns array, approximate by checking
            # whether deploy_pending is active. If it is, user already approved.
            if active_of("deploy_pending") is None:
                instances.append(BeliefInstance("user_approval_required", uuid, turn["session_id"], ts, turn_idx))

        if role == "user" and DEPLOY_INTENT.search(text):
            uar = active_of("user_approval_required")
            if uar:
                uar.retire(ts, turn_idx, "user_provided_approval")

        # Apply stale-decay retirements after this turn's events (for any belief
        # that should have aged out during this turn's processing window)
        auto_retire_stale(ts, turn_idx)

    return instances


# ─── Main ────────────────────────────────────────────────────────────────────

def iter_classified() -> Iterable[dict]:
    with IN_PATH.open() as f:
        for line in f:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def main() -> None:
    # Group by session
    by_session: dict[str, list[dict]] = defaultdict(list)
    for t in iter_classified():
        by_session[t["session_id"]].append(t)

    print(f"Walking {len(by_session)} sessions for belief tracking…")

    n_instances = 0
    by_belief = defaultdict(int)
    by_outcome = defaultdict(int)

    with OUT_PATH.open("w") as out_f:
        for sid in sorted(by_session.keys()):
            turns = sorted(by_session[sid], key=lambda x: x["turn_idx"])
            instances = walk_session(turns)
            for inst in instances:
                out_f.write(json.dumps(inst.to_dict()) + "\n")
                by_belief[inst.belief_name] += 1
                if inst.retired_reason:
                    by_outcome[inst.retired_reason] += 1
                else:
                    by_outcome["still_active_at_session_end"] += 1
                n_instances += 1

    print(f"Wrote {OUT_PATH}  ({n_instances:,} belief instances)")
    print()
    print("=" * 72)
    print("BELIEF INSTANCE COUNTS (rules v0.1)")
    print("=" * 72)
    for belief, n in sorted(by_belief.items(), key=lambda kv: -kv[1]):
        print(f"  {belief:<28s} {n:>6,}")
    print()
    print("Lifecycle outcomes (retirement reasons):")
    for reason, n in sorted(by_outcome.items(), key=lambda kv: -kv[1]):
        print(f"  {reason:<32s} {n:>6,}")


if __name__ == "__main__":
    main()
