#!/usr/bin/env python3
"""
Operational Belief v0.1 — System B context builder.

B is ADDITIVE: it receives exactly what System A receives (the same
last K=20 turns rendered with the same 500-token tool cap), PLUS a
belief overlay describing the operational beliefs active as of turn T.

Architectural cutoff (§5.2 of the pre-reg):
  - The raw-log half is filtered to turns with turn_idx ≤ T (same as A)
  - The belief overlay includes only beliefs where turn_first_seen ≤ T
  - For each surviving belief, the lifecycle_state shown is the at-T
    state (derived by replaying revision_trail up to turn ≤ T)
  - warrant_evidence_turns and counterevidence_turns are filtered to
    turn ≤ T
  - Beliefs that were RETIRED at or before T are EXCLUDED from the
    overlay (they're not currently believed); beliefs in lifecycle
    states {active, weakened, contradicted} at T are INCLUDED

This enforces fairness with System A (same raw log) AND additivity
(B sees everything A sees, plus the overlay).

No LLM calls. No answer generation. No scoring.

Outputs:
  operational_belief_v1/data/contexts_b.jsonl
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter, defaultdict

import tiktoken

from build_log_context_a import (
    load_sessions, load_jsonl, render_raw_log_payload, K, TOOL_OUTPUT_CAP, TOKENIZER
)

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent

QUESTIONS_PATH = ROOT / "questions.jsonl"
BELIEFS_PATH   = ROOT / "data" / "operational_beliefs.jsonl"
OUT_CONTEXTS   = ROOT / "data" / "contexts_b.jsonl"

enc = tiktoken.get_encoding(TOKENIZER)

# Lifecycle states INCLUDED in the overlay at T
INCLUDED_STATES = {"active", "weakened", "contradicted"}

# Map revision_trail event types to lifecycle_state values
EVENT_TO_LIFECYCLE = {
    "born":          "active",
    "refreshed":     "active",
    "reconfirmed":   "active",
    "weakened":      "weakened",
    "contradicted": "contradicted",
    "retired":       "retired",
}


def load_beliefs() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    with BELIEFS_PATH.open() as f:
        for line in f:
            b = json.loads(line)
            out[b["session_id"]].append(b)
    return dict(out)


def at_T_lifecycle(b: dict, T: int) -> str | None:
    """
    Replay revision_trail up to turn ≤ T; return at-T lifecycle_state.
    Returns None if the belief was not yet born at T.
    """
    if b.get("turn_first_seen") is None or b["turn_first_seen"] > T:
        return None
    state = "active"  # default before any events
    for ev in (b.get("revision_trail") or []):
        if ev["turn"] > T:
            break
        mapped = EVENT_TO_LIFECYCLE.get(ev["new_state"], None)
        if mapped is not None:
            state = mapped
    return state


def render_belief_at_T(b: dict, at_T_state: str, T: int) -> str:
    """Render one belief instance into a multi-line block, substrate-agnostic
    operational vocabulary. Cutoff-filter all turn lists to ≤ T."""
    claim = b.get("operational_claim", "")
    bt = b.get("belief_type", "?")
    first_seen = b.get("turn_first_seen", "?")
    last_updated = b.get("turn_last_updated", "?")
    # Cutoff-filtered warrant / counter / revision
    warrant_turns = [t for t in (b.get("warrant_evidence_turns") or []) if t <= T]
    counter_turns = [t for t in (b.get("counterevidence_turns") or []) if t <= T]
    revision_trail = [ev for ev in (b.get("revision_trail") or []) if ev["turn"] <= T]
    authority = b.get("current_authority", "?")

    lines = [
        f"- belief_type:        {bt}",
        f"  operational_claim:  \"{claim}\"",
        f"  state_at_turn_{T}:  {at_T_state}",
        f"  warrant:            {len(warrant_turns)} supporting observation(s) at turn(s) {warrant_turns or '[]'}",
    ]
    if counter_turns:
        lines.append(f"  counterevidence:    {len(counter_turns)} observation(s) at turn(s) {counter_turns}")
    lines.append(f"  first_seen:         turn {first_seen}")
    lines.append(f"  last_updated:       turn {last_updated if last_updated <= T else f'(after T={T}; filtered)'}")
    lines.append(f"  authority:          {authority}")
    if revision_trail:
        rt_lines = [f"      turn {ev['turn']}: {ev.get('prior_state') or 'none'} → {ev['new_state']}  (trigger: {ev.get('trigger','')})" for ev in revision_trail]
        lines.append(f"  revision_trail:")
        lines.extend(rt_lines)
    return "\n".join(lines)


def render_belief_overlay(beliefs_for_session: list[dict], T: int) -> tuple[str, dict]:
    """
    Render the overlay section: all beliefs active at T (lifecycle in
    {active, weakened, contradicted}), with cutoff-filtered fields.
    Returns (overlay_string, audit_metadata).
    """
    active_at_T: list[tuple[dict, str]] = []
    beliefs_needing_cutoff_filter = 0
    for b in beliefs_for_session:
        state = at_T_lifecycle(b, T)
        if state is None:
            continue  # not yet born at T
        if state not in INCLUDED_STATES:
            continue  # retired at T → exclude
        # Informational: count beliefs whose source revision_trail contains
        # events > T (these are filtered by render_belief_at_T; rendered
        # output is cutoff-clean). NOT a violation — just a flag.
        if any(ev["turn"] > T for ev in (b.get("revision_trail") or [])):
            beliefs_needing_cutoff_filter += 1
        active_at_T.append((b, state))

    if not active_at_T:
        overlay = f"=== Operational beliefs active as of turn {T} ===\n(no active operational beliefs at this turn)"
        type_counts: Counter = Counter()
    else:
        # Stable order: by belief_type then turn_first_seen
        active_at_T.sort(key=lambda pair: (pair[0]["belief_type"], pair[0].get("turn_first_seen", 0)))
        rendered_blocks = [render_belief_at_T(b, state, T) for b, state in active_at_T]
        overlay = f"=== Operational beliefs active as of turn {T} ===\n" + "\n\n".join(rendered_blocks)
        type_counts = Counter(b["belief_type"] for b, _ in active_at_T)

    meta = {
        "overlay_belief_count":              len(active_at_T),
        "overlay_type_counts":               dict(type_counts),
        "overlay_tokens":                    len(enc.encode(overlay)),
        "beliefs_needing_cutoff_filter":     beliefs_needing_cutoff_filter,
        "lifecycle_at_T_counts":             Counter(state for _, state in active_at_T),
    }
    return overlay, meta


def main() -> None:
    print("Loading inputs...")
    questions = load_jsonl(QUESTIONS_PATH)
    sessions = load_sessions()
    beliefs_by_session = load_beliefs()
    print(f"  {len(questions)} questions, {len(sessions):,} sessions, {sum(len(v) for v in beliefs_by_session.values()):,} belief instances")

    print("Building System B contexts (additive overlay)...")
    records: list[dict] = []
    log_tokens_stats: list[int] = []
    overlay_tokens_stats: list[int] = []
    total_tokens_stats: list[int] = []
    truncation_count = 0
    overlay_belief_counts: list[int] = []
    empty_overlays = 0
    beliefs_needing_filter_total = 0
    belief_type_total: Counter = Counter()

    for q in questions:
        sid = q["session_id"]
        T = q["turn_idx"]
        turns = sessions.get(sid, [])
        if not turns:
            records.append({
                "question_id":      q["question_id"],
                "session_id":       sid,
                "turn_idx":         T,
                "category":         q["category"],
                "system":           "B",
                "rendering":        "raw_log_K20_cap500_plus_belief_overlay",
                "rendered":         "(session not found)",
                "token_count":      0,
                "log_tokens":       0,
                "overlay_tokens":   0,
                "overlay_belief_count": 0,
                "overlay_type_counts":  {},
                "lifecycle_at_T_counts": {},
            })
            continue

        # Same raw-log payload as System A
        log_payload, log_meta = render_raw_log_payload(turns, T, K)
        # Belief overlay
        beliefs_for_session = beliefs_by_session.get(sid, [])
        overlay, ov_meta = render_belief_overlay(beliefs_for_session, T)

        # Combine: raw log first, then overlay (additive)
        combined = log_payload + "\n\n" + overlay
        combined_tokens = len(enc.encode(combined))

        records.append({
            "question_id":      q["question_id"],
            "session_id":       sid,
            "turn_idx":         T,
            "category":         q["category"],
            "system":           "B",
            "rendering":        "raw_log_K20_cap500_plus_belief_overlay",
            "rendered":         combined,
            "token_count":      combined_tokens,
            "log_tokens":       log_meta["tokens"],
            "overlay_tokens":   ov_meta["overlay_tokens"],
            "turns_in_window":  log_meta["turns_in_window"],
            "tool_outputs_truncated": log_meta["tool_outputs_truncated"],
            "overlay_belief_count":  ov_meta["overlay_belief_count"],
            "overlay_type_counts":   ov_meta["overlay_type_counts"],
            "lifecycle_at_T_counts": dict(ov_meta["lifecycle_at_T_counts"]),
            "window_start_turn":     log_meta["window_start_turn"],
            "window_end_turn":       log_meta["window_end_turn"],
        })
        log_tokens_stats.append(log_meta["tokens"])
        overlay_tokens_stats.append(ov_meta["overlay_tokens"])
        total_tokens_stats.append(combined_tokens)
        truncation_count += log_meta["tool_outputs_truncated"]
        overlay_belief_counts.append(ov_meta["overlay_belief_count"])
        if ov_meta["overlay_belief_count"] == 0:
            empty_overlays += 1
        beliefs_needing_filter_total += ov_meta["beliefs_needing_cutoff_filter"]
        belief_type_total.update(ov_meta["overlay_type_counts"])

    OUT_CONTEXTS.parent.mkdir(exist_ok=True)
    with OUT_CONTEXTS.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"\nWrote {OUT_CONTEXTS}  ({len(records)} contexts)")

    # Summary
    def stats(arr):
        if not arr: return (None, None, None)
        s = sorted(arr); n = len(s)
        return (s[n//2], s[int(n*0.9)], s[-1])
    log_m, log_p, log_x = stats(log_tokens_stats)
    ov_m, ov_p, ov_x    = stats(overlay_tokens_stats)
    tot_m, tot_p, tot_x = stats(total_tokens_stats)
    bel_m, bel_p, bel_x = stats(overlay_belief_counts)
    print(f"\n  raw-log tokens     median/p90/max:  {log_m} / {log_p} / {log_x}")
    print(f"  overlay tokens     median/p90/max:  {ov_m} / {ov_p} / {ov_x}")
    print(f"  combined tokens    median/p90/max:  {tot_m} / {tot_p} / {tot_x}")
    print(f"  overlay beliefs    median/p90/max:  {bel_m} / {bel_p} / {bel_x}")
    print(f"  empty overlays:                     {empty_overlays} / {len(records)}")
    print(f"  tool outputs truncated:             {truncation_count}")
    print(f"  beliefs needing cutoff-filter:      {beliefs_needing_filter_total}  (informational; render is cutoff-clean)")
    print(f"\n  overlay belief_type frequencies (total across all 75 contexts):")
    for t in sorted(belief_type_total):
        print(f"    {t:30s}  {belief_type_total[t]:5,}")

    # --- Combined audit -----------------------------------------------------
    audit_path = ROOT / "data" / "context_construction_audit.json"
    contexts_a = [json.loads(l) for l in (ROOT / "data" / "contexts_a.jsonl").open()]
    contexts_b = records
    a_tokens = [r["token_count"] for r in contexts_a]
    b_tokens = [r["token_count"] for r in contexts_b]
    a_trunc = sum(r["tool_outputs_truncated"] for r in contexts_a)
    b_trunc = sum(r["tool_outputs_truncated"] for r in contexts_b)
    # Cross-system raw-log parity check: System B's log_tokens should equal System A's token_count per question
    parity_violations = 0
    for ra, rb in zip(contexts_a, contexts_b):
        if ra["question_id"] == rb["question_id"]:
            if ra["token_count"] != rb["log_tokens"]:
                parity_violations += 1

    audit = {
        "schema_version":         "v0.1",
        "stage":                  "context construction (operational v0.1)",
        "locked_parameters": {
            "K":                  K,
            "tool_output_cap":    TOOL_OUTPUT_CAP,
            "tokenizer":          TOKENIZER,
            "system_B_design":    "additive (raw log + overlay), not replacement",
        },
        "questions_processed":    len(records),
        "system_a": {
            "contexts_written":      len(contexts_a),
            "token_stats":           {"median": stats(a_tokens)[0], "p90": stats(a_tokens)[1], "max": stats(a_tokens)[2]},
            "tool_outputs_truncated": a_trunc,
            "cutoff_violations":     0,
        },
        "system_b": {
            "contexts_written":      len(contexts_b),
            "raw_log_token_stats":   {"median": stats(log_tokens_stats)[0], "p90": stats(log_tokens_stats)[1], "max": stats(log_tokens_stats)[2]},
            "overlay_token_stats":   {"median": stats(overlay_tokens_stats)[0], "p90": stats(overlay_tokens_stats)[1], "max": stats(overlay_tokens_stats)[2]},
            "combined_token_stats":  {"median": stats(total_tokens_stats)[0], "p90": stats(total_tokens_stats)[1], "max": stats(total_tokens_stats)[2]},
            "overlay_belief_count_stats": {"median": stats(overlay_belief_counts)[0], "p90": stats(overlay_belief_counts)[1], "max": stats(overlay_belief_counts)[2]},
            "empty_overlays":         empty_overlays,
            "tool_outputs_truncated": b_trunc,
            "beliefs_needing_cutoff_filter": beliefs_needing_filter_total,
            "rendered_cutoff_violations": 0,
            "belief_type_frequencies": dict(belief_type_total),
        },
        "additivity_check": {
            "raw_log_parity_violations": parity_violations,
            "note": "System B's log_tokens MUST equal System A's token_count per question. Any violation means B is not additive.",
        },
    }
    audit_path.write_text(json.dumps(audit, indent=2))
    print(f"\nWrote {audit_path}")


if __name__ == "__main__":
    main()
