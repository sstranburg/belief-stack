#!/usr/bin/env python3
"""
Operational Belief v0.1 — Substrate builder (step 5b).

Persists all 11 belief types per the locked §2.3 typology to
operational_beliefs.jsonl. The substrate is read-only after construction
and serves as System B's overlay input in step 5c+.

Topological construction order (locked):
  1. Primary beliefs (8 existing TKOS types projected + renamed +
     validation_complete derived as a primary)
  2. Composites (action_ready, action_blocked)
  3. failure_signature_active

The 4 NEW types are derived using the same logic the scorer applies
on-the-fly (see score_operational_label.py). 5b persists what 5a
computed in-memory — the algorithm is the same; the artifact is new.

No LLM calls. No question construction. No answer generation. Read-only
discipline: this script writes operational_beliefs.jsonl and an audit;
nothing else.

Locked v0.1 schema per belief (§2.3):
  belief_id              string  stable per instance
  session_id             string
  belief_type            string  one of 11
  operational_claim      string  fixed per type
  holder                 "assistant"  (single-holder v0.1)
  turn_first_seen        int
  turn_last_updated      int
  lifecycle_state        active | weakened | contradicted | retired
  warrant_evidence_turns [int]   turns that supported the belief
  counterevidence_turns  [int]   turns that contradicted / weakened
  decay_status           fresh | decaying | stale  (at retirement, or
                                                    session-end if still active)
  revision_trail         [{turn, prior_state, new_state, trigger}]
  current_authority      asserted_by_assistant | confirmed_by_tool | confirmed_by_user
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from collections import Counter, defaultdict
from datetime import datetime

# Reuse scorer's substrate loaders and derivation functions
from score_operational_label import (
    load_normalized_sessions,
    load_reasoning_ledger,
    load_existing_beliefs,
    load_phase2_sessions,
    derive_validation_complete_events,
    derive_action_state_at,
    signature_recurrences_at,
    turn_proposes_action,
    beliefs_active_at,
    K,
    BLOCKER_BELIEFS,
)

ROOT = pathlib.Path(__file__).resolve().parent
OUT_BELIEFS = ROOT / "data" / "operational_beliefs.jsonl"
OUT_AUDIT   = ROOT / "data" / "operational_belief_substrate_audit.json"

# ---- Locked operational claim text per type ---------------------------------
OPERATIONAL_CLAIMS = {
    "pipeline_running":         "a long-running pipeline action is currently executing",
    "pipeline_failed":          "the most recent pipeline action ended in failure",
    "issue_under_diagnosis":    "the assistant is actively investigating an error",
    "fix_attempted":            "a fix has been applied but not yet validated",
    "validation_pending":       "validation has not yet been observed for the most recent fix",
    "validation_complete":      "validation has been observed successfully for the most recent fix",
    "user_approval_pending":    "the assistant has requested approval and has not received it",
    "action_ready":             "the assistant believes preconditions for the proposed next action are met",
    "action_blocked":           "the assistant believes one or more preconditions block proceeding with the proposed action",
    "report_ready":             "an output artifact is ready for user review",
    "failure_signature_active": "the same failure signature has recurred at least 3 times in the recent window",
}

# Default current_authority per belief type (origin of the belief)
DEFAULT_AUTHORITY = {
    "pipeline_running":         "confirmed_by_tool",
    "pipeline_failed":          "confirmed_by_tool",
    "issue_under_diagnosis":    "asserted_by_assistant",
    "fix_attempted":            "asserted_by_assistant",
    "validation_pending":       "asserted_by_assistant",
    "validation_complete":      "confirmed_by_tool",
    "user_approval_pending":    "asserted_by_assistant",
    "action_ready":             "asserted_by_assistant",
    "action_blocked":           "asserted_by_assistant",
    "report_ready":             "asserted_by_assistant",
    "failure_signature_active": "confirmed_by_tool",  # signature derived from tool error patterns
}

# Half-life used to compute decay_status (in turns, since we work in turn-space)
# For TKOS-existing beliefs, the file carries half_life_seconds; we approximate
# 1 turn ≈ 30s for purposes of fresh/decaying/stale buckets. For NEW types,
# half-lives are locked in §2.3 as: validation_complete 30min ≈ 60 turns,
# action_* 5 turns, failure_signature_active 10 turns. Document this.
HALF_LIFE_TURNS_NEW = {
    "validation_complete":      60,
    "action_ready":             5,
    "action_blocked":           5,
    "failure_signature_active": 10,
}


def belief_id(session_id: str, btype: str, birth_turn: int, anchor: str = "") -> str:
    """Stable belief id: bel-{8 hex of sha256(session|type|birth|anchor)}."""
    h = hashlib.sha256(f"{session_id}|{btype}|{birth_turn}|{anchor}".encode()).hexdigest()
    return f"bel-{h[:12]}"


def decay_status_from_age(age_turns: int, half_life_turns: int) -> str:
    """fresh / decaying / stale buckets."""
    if half_life_turns <= 0:
        return "stale"
    ratio = age_turns / half_life_turns
    if ratio < 0.5:
        return "fresh"
    if ratio < 1.0:
        return "decaying"
    return "stale"


# ============================================================================
# 1) Project 8 existing TKOS types into the v0.1 schema
# ============================================================================

def project_existing_beliefs(existing_per_session: dict[str, list[dict]], sessions_per_id: dict[str, list[dict]]) -> list[dict]:
    """Convert TKOS phase2_belief_timelines.jsonl entries into v0.1 schema.

    For each existing belief instance, derive:
      lifecycle_state    — from terminal event_type
      warrant_evidence_turns / counterevidence_turns — from events
      revision_trail     — from events list (turn, prior_state, new_state, trigger)
      decay_status       — at retirement or session end
      current_authority  — DEFAULT_AUTHORITY per belief_type
    """
    # Per locked §2.3 typology, deploy_pending was REPLACED by the more
    # generic action_ready / action_blocked composites. We do not project it.
    ALLOWED_TKOS_TYPES = {
        "pipeline_running", "pipeline_failed", "issue_under_diagnosis",
        "fix_attempted", "validation_pending", "user_approval_pending",
        "report_ready",
    }
    out = []
    for sid, beliefs in existing_per_session.items():
        sess_turns = sessions_per_id.get(sid, [])
        session_end = sess_turns[-1]["turn_idx"] if sess_turns else 0
        for b in beliefs:
            if b["belief_name"] not in ALLOWED_TKOS_TYPES:
                continue
            events = sorted(b.get("events") or [], key=lambda e: e["turn_idx"])
            if not events:
                continue
            born_ev = next((e for e in events if e["event_type"] == "born"), None)
            if born_ev is None:
                continue
            birth_turn = born_ev["turn_idx"]

            # Terminal event determines lifecycle_state
            terminal = events[-1]
            term_type = terminal["event_type"]
            if term_type == "retired":
                lifecycle = "retired"
            elif term_type == "contradicted":
                lifecycle = "contradicted"
            elif term_type == "weakened":
                lifecycle = "weakened"
            else:
                # born / refreshed / reconfirmed — still active at the end of the timeline
                lifecycle = "active"

            # Warrant evidence vs counterevidence
            warrant_turns = [e["turn_idx"] for e in events if e["event_type"] in ("born", "refreshed", "reconfirmed")]
            counter_turns = [e["turn_idx"] for e in events if e["event_type"] in ("weakened", "contradicted")]
            last_updated_turn = events[-1]["turn_idx"]

            # Revision trail
            revision_trail = []
            for i, e in enumerate(events):
                prior_state = events[i - 1]["event_type"] if i > 0 else None
                revision_trail.append({
                    "turn":        e["turn_idx"],
                    "prior_state": prior_state,
                    "new_state":   e["event_type"],
                    "trigger":     e.get("reason") or e.get("source") or "lifecycle_event",
                })

            # Decay status — age from last refresh vs half_life
            half_life_seconds = b.get("half_life_seconds", 1800)
            # Approximate 30s per turn (our coarse conversion)
            half_life_turns = max(1, half_life_seconds // 30)
            age_turns = (session_end if lifecycle == "active" else last_updated_turn) - last_updated_turn
            decay = decay_status_from_age(age_turns, half_life_turns)

            belief_type = b["belief_name"]  # already renamed by loader

            out.append({
                "belief_id":              belief_id(sid, belief_type, birth_turn, b.get("anchor_uuid", "")),
                "session_id":             sid,
                "belief_type":            belief_type,
                "operational_claim":      OPERATIONAL_CLAIMS.get(belief_type, ""),
                "holder":                 "assistant",
                "turn_first_seen":        birth_turn,
                "turn_last_updated":      last_updated_turn,
                "lifecycle_state":        lifecycle,
                "warrant_evidence_turns": warrant_turns,
                "counterevidence_turns":  counter_turns,
                "decay_status":           decay,
                "revision_trail":         revision_trail,
                "current_authority":      DEFAULT_AUTHORITY.get(belief_type, "asserted_by_assistant"),
                "_origin":                "tkos_phase2_projection",
            })
    return out


# ============================================================================
# 2) Derive validation_complete as a primary belief
# ============================================================================

def derive_validation_complete_beliefs(sessions_per_id: dict[str, list[dict]],
                                       existing_per_session: dict[str, list[dict]]) -> list[dict]:
    """Each validation_complete is a separate belief instance born at the
    success-observation turn. Lifecycle: active for half_life_turns then stale."""
    out = []
    for sid, turns in sessions_per_id.items():
        beliefs = existing_per_session.get(sid, [])
        vc_turns = derive_validation_complete_events(turns, beliefs)
        for birth_turn in vc_turns:
            # Find any subsequent fix_attempted (which would contradict this VC)
            session_end = turns[-1]["turn_idx"] if turns else birth_turn
            half_life = HALF_LIFE_TURNS_NEW["validation_complete"]
            # Lifecycle: active until next fix_attempted or until session_end
            subsequent_fa = None
            for b in beliefs:
                if b["belief_name"] == "fix_attempted" and b["birth_turn"] is not None and b["birth_turn"] > birth_turn:
                    if subsequent_fa is None or b["birth_turn"] < subsequent_fa:
                        subsequent_fa = b["birth_turn"]
            if subsequent_fa is not None:
                last_updated = subsequent_fa
                lifecycle = "contradicted"
                counter = [subsequent_fa]
            else:
                last_updated = birth_turn
                lifecycle = "active"
                counter = []
            age_turns = (session_end if lifecycle == "active" else last_updated) - last_updated
            decay = decay_status_from_age(age_turns, half_life)
            revision_trail = [{"turn": birth_turn, "prior_state": None, "new_state": "born", "trigger": "validation_tool_success"}]
            if subsequent_fa is not None:
                revision_trail.append({"turn": subsequent_fa, "prior_state": "active", "new_state": "contradicted", "trigger": "new_fix_attempted"})
            out.append({
                "belief_id":              belief_id(sid, "validation_complete", birth_turn),
                "session_id":             sid,
                "belief_type":            "validation_complete",
                "operational_claim":      OPERATIONAL_CLAIMS["validation_complete"],
                "holder":                 "assistant",
                "turn_first_seen":        birth_turn,
                "turn_last_updated":      last_updated,
                "lifecycle_state":        lifecycle,
                "warrant_evidence_turns": [birth_turn],
                "counterevidence_turns":  counter,
                "decay_status":           decay,
                "revision_trail":         revision_trail,
                "current_authority":      DEFAULT_AUTHORITY["validation_complete"],
                "_origin":                "derived_new",
            })
    return out


# ============================================================================
# 3) Composites: action_ready / action_blocked
# ============================================================================

def derive_action_composite_beliefs(sessions_per_id: dict[str, list[dict]],
                                    existing_per_session: dict[str, list[dict]]) -> list[dict]:
    """A composite is birthed at any turn where the assistant proposes an
    action. Its class (ready vs blocked) is determined by active blockers at
    that turn. Lifetime: 5 turns or until belief state changes meaningfully.
    Persisted as ONE belief instance per (session, proposal_turn)."""
    out = []
    for sid, turns in sessions_per_id.items():
        beliefs = existing_per_session.get(sid, [])
        session_end = turns[-1]["turn_idx"] if turns else 0
        for t in turns:
            if not turn_proposes_action(t):
                continue
            T = t["turn_idx"]
            # Classify at this turn
            state = derive_action_state_at(turns, beliefs, T)
            if state is None:
                continue  # shouldn't happen since we just confirmed action was proposed
            half_life = HALF_LIFE_TURNS_NEW[state]
            # Lifetime: 5 turns or until session end
            last_updated = min(T + half_life, session_end)
            age_turns = 0  # at birth
            decay = "fresh"
            # Active blockers at T (for action_blocked)
            active_at_t = beliefs_active_at(beliefs, T)
            blocker_names = [b["belief_name"] for b in active_at_t if b["belief_name"] in BLOCKER_BELIEFS]
            warrant_turns = [T]
            counter_turns: list[int] = []
            revision_trail = [{
                "turn": T, "prior_state": None, "new_state": "born",
                "trigger": f"action_proposal; blockers_active={blocker_names or 'none'}",
            }]
            out.append({
                "belief_id":              belief_id(sid, state, T),
                "session_id":             sid,
                "belief_type":            state,
                "operational_claim":      OPERATIONAL_CLAIMS[state],
                "holder":                 "assistant",
                "turn_first_seen":        T,
                "turn_last_updated":      T,
                "lifecycle_state":        "active",  # composites are point-in-time; we mark them active at T
                "warrant_evidence_turns": warrant_turns,
                "counterevidence_turns":  counter_turns,
                "decay_status":           decay,
                "revision_trail":         revision_trail,
                "current_authority":      DEFAULT_AUTHORITY[state],
                "_origin":                "derived_composite",
                "_active_blockers":       blocker_names,
                "_half_life_turns":       half_life,
            })
    return out


# ============================================================================
# 4) failure_signature_active
# ============================================================================

def derive_failure_signature_beliefs(sessions_per_id: dict[str, list[dict]]) -> list[dict]:
    """A failure_signature_active belief is born at the turn where a
    signature first reaches ≥3 occurrences within K turns. Lifetime: until
    the signature stops appearing for K turns (signature_aged_out)."""
    out = []
    half_life = HALF_LIFE_TURNS_NEW["failure_signature_active"]
    for sid, turns in sessions_per_id.items():
        if len(turns) < K:
            continue
        # Walk forward; for each turn T, check if a NEW loop just emerged
        # (i.e., signature_recurrences_at returns a sig that wasn't already
        # active in the prior turn's window).
        prev_sig = None
        prev_first_seen: dict[tuple, int] = {}  # signature -> birth_turn
        active_sig_birth: dict[tuple, int] = {}  # signature -> birth_turn currently active
        for t in turns:
            T = t["turn_idx"]
            if T < K - 1:
                continue
            sig, matching_turns = signature_recurrences_at(turns, T, K)
            if sig is None:
                # No signature recurs at this point. Retire any active beliefs.
                for s, bt in list(active_sig_birth.items()):
                    out.append({
                        "belief_id":              belief_id(sid, "failure_signature_active", bt, "|".join(s)),
                        "session_id":             sid,
                        "belief_type":            "failure_signature_active",
                        "operational_claim":      OPERATIONAL_CLAIMS["failure_signature_active"],
                        "holder":                 "assistant",
                        "turn_first_seen":        bt,
                        "turn_last_updated":      T,
                        "lifecycle_state":        "retired",
                        "warrant_evidence_turns": prev_first_seen.get(s, []),
                        "counterevidence_turns":  [],
                        "decay_status":           "stale",
                        "revision_trail": [
                            {"turn": bt, "prior_state": None, "new_state": "born", "trigger": f"signature_recurrence_3x: {s[0]}"},
                            {"turn": T,  "prior_state": "active", "new_state": "retired", "trigger": "signature_aged_out"},
                        ],
                        "current_authority":      DEFAULT_AUTHORITY["failure_signature_active"],
                        "_origin":                "derived_signature",
                        "_signature":             list(s),
                    })
                active_sig_birth.clear()
                continue
            # New signature OR continuation
            if sig not in active_sig_birth:
                active_sig_birth[sig] = T
                prev_first_seen[sig] = matching_turns
            # If a different signature was previously active, retire it
            for s, bt in list(active_sig_birth.items()):
                if s != sig:
                    out.append({
                        "belief_id":              belief_id(sid, "failure_signature_active", bt, "|".join(s)),
                        "session_id":             sid,
                        "belief_type":            "failure_signature_active",
                        "operational_claim":      OPERATIONAL_CLAIMS["failure_signature_active"],
                        "holder":                 "assistant",
                        "turn_first_seen":        bt,
                        "turn_last_updated":      T,
                        "lifecycle_state":        "retired",
                        "warrant_evidence_turns": prev_first_seen.get(s, []),
                        "counterevidence_turns":  [],
                        "decay_status":           "stale",
                        "revision_trail": [
                            {"turn": bt, "prior_state": None, "new_state": "born", "trigger": f"signature_recurrence_3x: {s[0]}"},
                            {"turn": T,  "prior_state": "active", "new_state": "retired", "trigger": "signature_replaced_by_different_signature"},
                        ],
                        "current_authority":      DEFAULT_AUTHORITY["failure_signature_active"],
                        "_origin":                "derived_signature",
                        "_signature":             list(s),
                    })
                    del active_sig_birth[s]
        # Any still-active at session end
        session_end = turns[-1]["turn_idx"]
        for s, bt in active_sig_birth.items():
            out.append({
                "belief_id":              belief_id(sid, "failure_signature_active", bt, "|".join(s)),
                "session_id":             sid,
                "belief_type":            "failure_signature_active",
                "operational_claim":      OPERATIONAL_CLAIMS["failure_signature_active"],
                "holder":                 "assistant",
                "turn_first_seen":        bt,
                "turn_last_updated":      session_end,
                "lifecycle_state":        "active",
                "warrant_evidence_turns": prev_first_seen.get(s, []),
                "counterevidence_turns":  [],
                "decay_status":           decay_status_from_age(session_end - bt, half_life),
                "revision_trail": [
                    {"turn": bt, "prior_state": None, "new_state": "born", "trigger": f"signature_recurrence_3x: {s[0]}"},
                ],
                "current_authority":      DEFAULT_AUTHORITY["failure_signature_active"],
                "_origin":                "derived_signature",
                "_signature":             list(s),
            })
    return out


# ============================================================================
# Main
# ============================================================================

def main() -> None:
    print("Loading substrates...")
    sessions = load_normalized_sessions()
    ledger   = load_reasoning_ledger()
    existing = load_existing_beliefs()
    phase2_sids = load_phase2_sessions()

    eligible = phase2_sids & set(sessions.keys())
    print(f"  {len(sessions):,} sessions normalized")
    print(f"  {len(existing):,} sessions with TKOS belief timelines")
    print(f"  {len(phase2_sids):,} sessions in Phase 2 sample")
    print(f"  {len(eligible):,} sessions eligible (Phase 2 ∩ normalized)")

    # Restrict to eligible sessions
    sessions_e = {sid: sessions[sid] for sid in eligible}
    existing_e = {sid: existing.get(sid, []) for sid in eligible}

    print("\nStep 1/4: projecting 8 TKOS belief types into v0.1 schema...")
    primary_beliefs = project_existing_beliefs(existing_e, sessions_e)
    print(f"  {len(primary_beliefs):,} primary (TKOS-projected) belief instances")

    print("\nStep 2/4: deriving validation_complete as a primary...")
    vc_beliefs = derive_validation_complete_beliefs(sessions_e, existing_e)
    primary_beliefs.extend(vc_beliefs)
    print(f"  {len(vc_beliefs):,} validation_complete instances (cumulative primaries: {len(primary_beliefs):,})")

    print("\nStep 3/4: deriving action_ready / action_blocked composites...")
    composite_beliefs = derive_action_composite_beliefs(sessions_e, existing_e)
    print(f"  {len(composite_beliefs):,} composite instances")

    print("\nStep 4/4: deriving failure_signature_active...")
    signature_beliefs = derive_failure_signature_beliefs(sessions_e)
    print(f"  {len(signature_beliefs):,} signature-active instances")

    all_beliefs = primary_beliefs + composite_beliefs + signature_beliefs
    # Sort for stable file ordering: by session_id, then turn_first_seen, then belief_type
    all_beliefs.sort(key=lambda b: (b["session_id"], b["turn_first_seen"], b["belief_type"]))

    OUT_BELIEFS.parent.mkdir(exist_ok=True)
    with OUT_BELIEFS.open("w") as f:
        for b in all_beliefs:
            f.write(json.dumps(b) + "\n")
    print(f"\nWrote {OUT_BELIEFS}  ({len(all_beliefs):,} belief instances total)")

    # ---- Audit ---------------------------------------------------------------
    by_type     = Counter(b["belief_type"] for b in all_beliefs)
    by_lifecycle = Counter(b["lifecycle_state"] for b in all_beliefs)
    by_authority = Counter(b["current_authority"] for b in all_beliefs)
    by_decay     = Counter(b["decay_status"] for b in all_beliefs)
    sessions_with_beliefs = sorted(set(b["session_id"] for b in all_beliefs))
    per_session_counts = Counter(b["session_id"] for b in all_beliefs)
    # Per-type per-lifecycle breakdown
    type_x_lifecycle: dict[str, Counter] = defaultdict(Counter)
    for b in all_beliefs:
        type_x_lifecycle[b["belief_type"]][b["lifecycle_state"]] += 1

    audit = {
        "schema_version":         "v0.1",
        "stage":                  "step 5b: operational belief substrate persistence",
        "input_files": {
            "sessions_normalized": str(__import__("score_operational_label").NORMALIZED),
            "reasoning_ledger":    str(__import__("score_operational_label").LEDGER),
            "phase2_belief_timelines": str(__import__("score_operational_label").BELIEFS),
            "phase2_sample":       str(__import__("score_operational_label").PHASE2_SAMPLE),
        },
        "topological_order": [
            "primaries (TKOS projection + validation_complete)",
            "composites (action_ready / action_blocked)",
            "failure_signature_active",
        ],
        "eligible_sessions":      len(eligible),
        "sessions_with_beliefs":  len(sessions_with_beliefs),
        "total_belief_instances": len(all_beliefs),
        "by_belief_type":         dict(by_type.most_common()),
        "by_lifecycle_state":     dict(by_lifecycle.most_common()),
        "by_current_authority":   dict(by_authority.most_common()),
        "by_decay_status":        dict(by_decay.most_common()),
        "per_session_counts_stats": {
            "min":  min(per_session_counts.values()) if per_session_counts else 0,
            "mean": (sum(per_session_counts.values()) / len(per_session_counts)) if per_session_counts else 0,
            "max":  max(per_session_counts.values()) if per_session_counts else 0,
            "p90":  sorted(per_session_counts.values())[int(len(per_session_counts) * 0.9)] if per_session_counts else 0,
        },
        "type_x_lifecycle":       {t: dict(cnt) for t, cnt in type_x_lifecycle.items()},
        "excluded_sessions":      {
            "not_in_phase2":          sorted(set(sessions.keys()) - phase2_sids),
            "phase2_but_no_normalized": sorted(phase2_sids - set(sessions.keys())),
        },
        "sparsity_notes": {
            "failure_signature_active_instances": by_type.get("failure_signature_active", 0),
            "action_blocked_instances":           by_type.get("action_blocked", 0),
            "action_ready_instances":             by_type.get("action_ready", 0),
            "comment": "Per locked discipline, scoring rules were NOT loosened during substrate construction. Low counts here reflect the substrate as-is and will surface as construction-time constraints in 5c if balance targets cannot be hit.",
        },
        "schema_fields_persisted": [
            "belief_id", "session_id", "belief_type", "operational_claim", "holder",
            "turn_first_seen", "turn_last_updated", "lifecycle_state",
            "warrant_evidence_turns", "counterevidence_turns", "decay_status",
            "revision_trail", "current_authority",
        ],
        "private_fields": [
            "_origin", "_active_blockers", "_half_life_turns", "_signature",
        ],
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"Wrote {OUT_AUDIT}")

    # Pretty summary
    print()
    print("=" * 78)
    print("OPERATIONAL BELIEF SUBSTRATE SUMMARY")
    print("=" * 78)
    print(f"  Total belief instances:   {len(all_beliefs):,}")
    print(f"  Sessions with beliefs:    {len(sessions_with_beliefs):,} / {len(eligible)}")
    print(f"\n  by belief_type:")
    for t in ["pipeline_running","pipeline_failed","issue_under_diagnosis","fix_attempted",
              "validation_pending","validation_complete","user_approval_pending",
              "action_ready","action_blocked","report_ready","failure_signature_active"]:
        print(f"    {t:30s}  {by_type.get(t, 0):6,}")
    print(f"\n  by lifecycle_state:")
    for ls, n in by_lifecycle.most_common():
        print(f"    {ls:14s}  {n:6,}")
    print(f"\n  by current_authority:")
    for a, n in by_authority.most_common():
        print(f"    {a:25s}  {n:6,}")


if __name__ == "__main__":
    main()
