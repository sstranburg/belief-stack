#!/usr/bin/env python3
"""
Operational Belief v0.2.1 — System B context builder (budgeted, ranked, deduped).

Implements OB-002 §3.0–§3.5 + §3.5a:
  - §3.0 Out-of-window meta-rule (apply tiers within the out-of-window
    pool first; in-window pool only after that is exhausted).
  - §3.1 Lexicographic priority tiers within each pool.
  - §3.4 Tiebreaks: out-of-window → last_updated desc → authority → hash.
  - §3.5 Compressed serialization: one compact line per belief.
  - §3.5a Type+claim duplication collapse (added v0.2.1): groups
    candidate beliefs by (belief_type, operational_claim) and renders
    one line per cluster with n=cluster_count.
  - §3.2 Strict token budget with header reserve + omitted-summary gated
    on fit.

The raw-log payload is the same as System A (K=20, 500-token tool cap)
to preserve additivity. Only the overlay portion differs by arm.

Usage:
  python build_overlay_context_b_v2.py --budget 500
  python build_overlay_context_b_v2.py --budget 1000
  python build_overlay_context_b_v2.py --budget 2000

Outputs:
  operational_belief_v2/data/contexts_b{budget}.jsonl
  operational_belief_v2/data/context_construction_audit_b{budget}.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from collections import Counter, defaultdict

import tiktoken

# Reuse v0.1 infrastructure for raw-log rendering — preserves parity with
# System A across both experiments.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "operational_belief_v1"))
from build_log_context_a import (  # noqa: E402
    K,
    TOKENIZER,
    TOOL_OUTPUT_CAP,
    load_jsonl,
    load_sessions,
    render_raw_log_payload,
)

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent
V1_ROOT = STORM_ROOT / "operational_belief_v1"

# Inputs (reusing v0.1 question set + belief substrate)
QUESTIONS_PATH = V1_ROOT / "questions.jsonl"
BELIEFS_PATH = V1_ROOT / "data" / "operational_beliefs.jsonl"

enc = tiktoken.get_encoding(TOKENIZER)

# ─── OB-002 ranking constants ──────────────────────────────────────────

# §3.1 tier 1 — active blockers
ACTIVE_BLOCKER_TYPES = frozenset({
    "action_blocked",
    "validation_pending",
    "pipeline_failed",
    "pipeline_running",
    "user_approval_pending",
})

# Map v0.1 revision_trail new_state → lifecycle category
NEW_STATE_TO_LIFECYCLE = {
    "born":         "active",
    "active":       "active",
    "refreshed":    "active",
    "reconfirmed":  "active",
    "weakened":     "weakened",
    "contradicted": "contradicted",
    "retired":      "retired",
}

# §3.5 included states (exclude retired)
INCLUDED_LIFECYCLE_STATES = {"active", "weakened", "contradicted"}

# Warrant-bearing kinds (used for §3.0 out-of-window computation)
WARRANT_BEARING_NEW_STATES = {"born", "active", "refreshed", "reconfirmed"}

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


# ─── Lifecycle reconstruction at T ──────────────────────────────────────

def at_T_lifecycle(b: dict, T: int) -> str | None:
    """Replay revision_trail up to T; return at-T lifecycle category.

    Returns None if the belief was not yet born at T.
    Identical to v0.1 logic for cross-experiment parity.
    """
    if b.get("turn_first_seen") is None or b["turn_first_seen"] > T:
        return None
    state = "active"
    for ev in (b.get("revision_trail") or []):
        if ev["turn"] > T:
            break
        mapped = NEW_STATE_TO_LIFECYCLE.get(ev["new_state"])
        if mapped is not None:
            state = mapped
    return state


def latest_warrant_turn(b: dict, T: int) -> int:
    """Latest warrant-bearing turn ≤ T for §3.0 out-of-window check.

    Includes the birth turn, any warrant_evidence_turns ≤ T, and any
    revision_trail event with warrant-bearing new_state.
    """
    candidates = [b["turn_first_seen"]]
    candidates.extend(t for t in (b.get("warrant_evidence_turns") or []) if t <= T)
    candidates.extend(
        ev["turn"]
        for ev in (b.get("revision_trail") or [])
        if ev["turn"] <= T and ev["new_state"] in WARRANT_BEARING_NEW_STATES
    )
    return max(candidates)


def at_T_authority(b: dict, T: int) -> str:
    """Highest-rank authority observed at any belief_event with at_turn ≤ T."""
    observed = set()
    if b.get("current_authority"):
        observed.add(b["current_authority"])
    # v0.1 substrate doesn't carry per-event authority, so we use the
    # belief-level current_authority as the proxy. (Same approximation
    # used implicitly by v0.1.)
    if not observed:
        observed.add("asserted_by_assistant")
    return max(observed, key=lambda a: AUTH_RANK.get(a, 0))


# ─── §3.0 + §3.1 + §3.4 ranking ─────────────────────────────────────────

def is_out_of_window(b: dict, T: int, K_window: int) -> bool:
    """OB-002 §3.0: born and latest warrant both at turn ≤ (T - K)."""
    cutoff = T - K_window
    return b["turn_first_seen"] <= cutoff and latest_warrant_turn(b, T) <= cutoff


def tier(b: dict, at_T_state: str) -> int:
    """OB-002 §3.1 priority tier (lower = higher priority)."""
    if b["belief_type"] in ACTIVE_BLOCKER_TYPES:
        return 1
    if at_T_state in {"weakened", "contradicted"}:
        return 2
    return 5  # default (active, non-blocker, no other special property)


def hash_key(belief_id: str) -> str:
    """Deterministic final tiebreak — hash of belief_id (no randomness)."""
    return hashlib.sha256(belief_id.encode()).hexdigest()


def sort_key(entry: tuple[dict, str, int, bool]) -> tuple:
    """Lexicographic sort key per OB-002 §3.0 + §3.4."""
    b, state, last_updated, oow = entry
    return (
        0 if oow else 1,                           # §3.0: out-of-window first
        tier(b, state),                            # §3.1: priority tier
        -last_updated,                             # §3.4: last_updated desc
        -AUTH_RANK.get(at_T_authority(b, last_updated), 0),  # authority desc
        hash_key(b["belief_id"]),                  # final hash tiebreak
    )


# ─── §3.5 compressed serialization ──────────────────────────────────────

def render_belief_line(
    representative: dict,
    at_T_state: str,
    T: int,
    cluster_count: int,
    cluster_last_updated: int,
    cluster_authority: str,
) -> str:
    """One compact line per cluster (OB-002 §3.5 + §3.5a).

    Format:
      [lifecycle_state] belief_type :: claim_short (auth=authority, last=last_updated[, n=cluster_count])

    The `n=` field is omitted when cluster_count == 1 for visual cleanliness.
    """
    claim_short = (representative.get("operational_claim") or "")[:80]
    base = (
        f"[{at_T_state}] {representative['belief_type']} :: {claim_short} "
        f"(auth={AUTH_ABBR.get(cluster_authority, cluster_authority)}, last={cluster_last_updated}"
    )
    if cluster_count > 1:
        base += f", n={cluster_count}"
    return base + ")"


def cluster_candidates(
    candidates: list[tuple[dict, str, int, bool]],
    T: int,
) -> list[dict]:
    """Apply OB-002 §3.5a: group by (belief_type, operational_claim).

    Returns a list of cluster dicts with:
      - representative   : the most recently updated active member
      - belief_type      : shared across cluster
      - operational_claim: shared across cluster
      - cluster_count    : number of members
      - state            : representative's at-T lifecycle
      - cluster_last_updated: max last_updated across the cluster
      - cluster_authority: highest authority rank across the cluster
      - cluster_is_oow   : true iff every member is out-of-window
      - member_belief_ids: list of belief_ids in the cluster
    """
    groups: dict[tuple[str, str], list[tuple[dict, str, int, bool]]] = {}
    for entry in candidates:
        b, state, last_updated, oow = entry
        key = (b["belief_type"], b.get("operational_claim") or "")
        groups.setdefault(key, []).append(entry)

    clusters: list[dict] = []
    for (belief_type, claim), members in groups.items():
        # Representative = most recently updated active member;
        # fall back to any most-recent if no active members.
        active_members = [m for m in members if m[1] == "active"]
        pick_pool = active_members if active_members else members
        representative_entry = max(pick_pool, key=lambda e: e[2])  # max by last_updated
        rep, rep_state, rep_last, _ = representative_entry
        cluster_last = max(m[2] for m in members)
        cluster_auth = max(
            (at_T_authority(m[0], T) for m in members),
            key=lambda a: AUTH_RANK.get(a, 0),
        )
        clusters.append({
            "representative":       rep,
            "belief_type":          belief_type,
            "operational_claim":    claim,
            "cluster_count":        len(members),
            "state":                rep_state,
            "cluster_last_updated": cluster_last,
            "cluster_authority":    cluster_auth,
            "cluster_is_oow":       all(m[3] for m in members),
            "member_belief_ids":    [m[0]["belief_id"] for m in members],
        })
    return clusters


def cluster_sort_key(cluster: dict) -> tuple:
    """Lexicographic sort key over clusters per §3.0 + §3.4."""
    return (
        0 if cluster["cluster_is_oow"] else 1,
        tier(cluster["representative"], cluster["state"]),
        -cluster["cluster_last_updated"],
        -AUTH_RANK.get(cluster["cluster_authority"], 0),
        hash_key(cluster["representative"]["belief_id"]),
    )


# ─── Overlay builder ────────────────────────────────────────────────────

def build_overlay(
    beliefs_for_session: list[dict],
    T: int,
    budget_tokens: int,
    K_window: int = K,
) -> tuple[str, dict]:
    """Build a ranked, budgeted overlay for one (session, T, budget) triple.

    Returns (overlay_text, audit_metadata).
    """
    # Reconstruct at-T state for every belief; drop retired and not-yet-born.
    candidates: list[tuple[dict, str, int, bool]] = []
    for b in beliefs_for_session:
        state = at_T_lifecycle(b, T)
        if state is None or state not in INCLUDED_LIFECYCLE_STATES:
            continue
        last_updated = b.get("turn_last_updated", b["turn_first_seen"])
        if last_updated > T:
            rt = [ev["turn"] for ev in (b.get("revision_trail") or []) if ev["turn"] <= T]
            last_updated = max(rt) if rt else b["turn_first_seen"]
        oow = is_out_of_window(b, T, K_window)
        candidates.append((b, state, last_updated, oow))

    # §3.5a: collapse identical (belief_type, operational_claim) clusters.
    clusters = cluster_candidates(candidates, T)
    clusters.sort(key=cluster_sort_key)

    # Worst-case header reserve, computed up front so the cap is honest.
    placeholder_header = (
        f"=== Operational belief overlay "
        f"(budget: {budget_tokens} tokens, used: 9999, omitted: 99, "
        f"clusters: 99, K={K_window}) ==="
    )
    header_reserve_tokens = len(enc.encode(placeholder_header)) + 1
    body_budget = max(0, budget_tokens - header_reserve_tokens)

    admitted: list[dict] = []
    omitted: list[dict] = []
    body_used_tokens = 0

    for cluster in clusters:
        line = render_belief_line(
            cluster["representative"],
            cluster["state"],
            T,
            cluster["cluster_count"],
            cluster["cluster_last_updated"],
            cluster["cluster_authority"],
        )
        line_tokens = len(enc.encode(line)) + 1  # +1 for newline
        if body_used_tokens + line_tokens <= body_budget:
            admitted.append(cluster)
            body_used_tokens += line_tokens
        else:
            omitted.append(cluster)

    admitted_clusters_by_type = Counter(c["belief_type"] for c in admitted)
    omitted_clusters_by_type = Counter(c["belief_type"] for c in omitted)
    admitted_members_by_type = Counter()
    omitted_members_by_type = Counter()
    for c in admitted:
        admitted_members_by_type[c["belief_type"]] += c["cluster_count"]
    for c in omitted:
        omitted_members_by_type[c["belief_type"]] += c["cluster_count"]
    oow_admitted = sum(1 for c in admitted if c["cluster_is_oow"])
    iw_admitted = len(admitted) - oow_admitted

    header = (
        f"=== Operational belief overlay "
        f"(budget: {budget_tokens} tokens, used: {body_used_tokens}, "
        f"omitted: {len(omitted)}, clusters: {len(admitted)}, K={K_window}) ==="
    )
    lines = [header]
    for c in admitted:
        lines.append(render_belief_line(
            c["representative"],
            c["state"],
            T,
            c["cluster_count"],
            c["cluster_last_updated"],
            c["cluster_authority"],
        ))

    # §3.1 tier 6: omitted-counts summary at cluster granularity, only if it still fits.
    if omitted_clusters_by_type:
        omitted_line = "# omitted clusters: " + ", ".join(
            f"{t}={n}" for t, n in sorted(omitted_clusters_by_type.items())
        )
        trial = "\n".join(lines + [omitted_line])
        if len(enc.encode(trial)) <= budget_tokens:
            lines.append(omitted_line)

    overlay = "\n".join(lines)
    overlay_tokens = len(enc.encode(overlay))

    meta = {
        "overlay_tokens":            overlay_tokens,
        "budget_tokens":             budget_tokens,
        "K_window":                  K_window,
        "admitted_cluster_count":    len(admitted),
        "omitted_cluster_count":     len(omitted),
        "admitted_member_count":     sum(c["cluster_count"] for c in admitted),
        "omitted_member_count":      sum(c["cluster_count"] for c in omitted),
        "admitted_clusters_by_type": dict(admitted_clusters_by_type),
        "omitted_clusters_by_type":  dict(omitted_clusters_by_type),
        "admitted_members_by_type":  dict(admitted_members_by_type),
        "omitted_members_by_type":   dict(omitted_members_by_type),
        "out_of_window_admitted":    oow_admitted,
        "in_window_admitted":        iw_admitted,
        "candidates_total_clusters": len(clusters),
        "candidates_total_members":  len(candidates),
        "lifecycle_at_T_counts":     dict(Counter(c["state"] for c in admitted)),
    }
    return overlay, meta


# ─── Main driver ────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--budget",
        type=int,
        required=True,
        help="Overlay token budget (500 / 1000 / 2000 per OB-002 §2)",
    )
    args = parser.parse_args()
    budget = args.budget

    out_contexts = ROOT / "data" / f"contexts_b{budget}.jsonl"
    out_audit = ROOT / "data" / f"context_construction_audit_b{budget}.json"
    out_contexts.parent.mkdir(exist_ok=True)

    print(f"Loading inputs (budget={budget})...")
    questions = load_jsonl(QUESTIONS_PATH)
    sessions = load_sessions()
    beliefs_by_session: dict[str, list[dict]] = defaultdict(list)
    with BELIEFS_PATH.open() as f:
        for line in f:
            b = json.loads(line)
            beliefs_by_session[b["session_id"]].append(b)
    beliefs_by_session = dict(beliefs_by_session)
    total_beliefs = sum(len(v) for v in beliefs_by_session.values())
    print(
        f"  {len(questions)} questions, {len(sessions):,} sessions, "
        f"{total_beliefs:,} belief instances"
    )

    print(f"Building System B{budget} contexts (ranked, budgeted, deduped overlay)...")
    records: list[dict] = []
    log_tokens_stats: list[int] = []
    overlay_tokens_stats: list[int] = []
    total_tokens_stats: list[int] = []
    admitted_cluster_counts: list[int] = []
    admitted_member_counts: list[int] = []
    omitted_cluster_counts: list[int] = []
    truncation_count = 0
    empty_overlays = 0
    over_budget = 0
    admitted_clusters_by_type_total: Counter = Counter()
    admitted_members_by_type_total: Counter = Counter()
    oow_admitted_total = 0
    iw_admitted_total = 0

    for q in questions:
        sid = q["session_id"]
        T = q["turn_idx"]
        turns = sessions.get(sid, [])
        if not turns:
            records.append({
                "question_id":  q["question_id"],
                "session_id":   sid,
                "turn_idx":     T,
                "category":     q["category"],
                "system":       f"B{budget}",
                "rendering":    f"raw_log_K{K}_cap{TOOL_OUTPUT_CAP}_plus_ranked_overlay_budget{budget}",
                "rendered":     "(session not found)",
                "token_count":  0,
                "log_tokens":   0,
                "overlay_tokens": 0,
                "overlay_meta": {},
            })
            continue

        log_payload, log_meta = render_raw_log_payload(turns, T, K)
        overlay, ov_meta = build_overlay(beliefs_by_session.get(sid, []), T, budget)

        combined = log_payload + "\n\n" + overlay
        combined_tokens = len(enc.encode(combined))

        records.append({
            "question_id":      q["question_id"],
            "session_id":       sid,
            "turn_idx":         T,
            "category":         q["category"],
            "system":           f"B{budget}",
            "rendering":        f"raw_log_K{K}_cap{TOOL_OUTPUT_CAP}_plus_ranked_overlay_budget{budget}",
            "rendered":         combined,
            "token_count":      combined_tokens,
            "log_tokens":       log_meta["tokens"],
            "overlay_tokens":   ov_meta["overlay_tokens"],
            "turns_in_window":  log_meta["turns_in_window"],
            "tool_outputs_truncated": log_meta["tool_outputs_truncated"],
            "window_start_turn":     log_meta["window_start_turn"],
            "window_end_turn":       log_meta["window_end_turn"],
            "overlay_meta":          ov_meta,
        })
        log_tokens_stats.append(log_meta["tokens"])
        overlay_tokens_stats.append(ov_meta["overlay_tokens"])
        total_tokens_stats.append(combined_tokens)
        truncation_count += log_meta["tool_outputs_truncated"]
        admitted_cluster_counts.append(ov_meta["admitted_cluster_count"])
        admitted_member_counts.append(ov_meta["admitted_member_count"])
        omitted_cluster_counts.append(ov_meta["omitted_cluster_count"])
        if ov_meta["admitted_cluster_count"] == 0:
            empty_overlays += 1
        if ov_meta["overlay_tokens"] > budget:
            over_budget += 1
        admitted_clusters_by_type_total.update(ov_meta["admitted_clusters_by_type"])
        admitted_members_by_type_total.update(ov_meta["admitted_members_by_type"])
        oow_admitted_total += ov_meta["out_of_window_admitted"]
        iw_admitted_total += ov_meta["in_window_admitted"]

    with out_contexts.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"\nWrote {out_contexts}  ({len(records)} contexts)")

    def stats(arr):
        if not arr:
            return (None, None, None)
        s = sorted(arr)
        n = len(s)
        return (s[n // 2], s[int(n * 0.9)], s[-1])

    log_m, log_p, log_x = stats(log_tokens_stats)
    ov_m, ov_p, ov_x = stats(overlay_tokens_stats)
    tot_m, tot_p, tot_x = stats(total_tokens_stats)
    adm_cm, adm_cp, adm_cx = stats(admitted_cluster_counts)
    adm_mm, adm_mp, adm_mx = stats(admitted_member_counts)
    om_cm, om_cp, om_cx = stats(omitted_cluster_counts)
    print(f"\n  raw-log tokens         median/p90/max:  {log_m} / {log_p} / {log_x}")
    print(f"  overlay tokens         median/p90/max:  {ov_m} / {ov_p} / {ov_x}")
    print(f"  combined tokens        median/p90/max:  {tot_m} / {tot_p} / {tot_x}")
    print(f"  admitted clusters      median/p90/max:  {adm_cm} / {adm_cp} / {adm_cx}")
    print(f"  admitted members       median/p90/max:  {adm_mm} / {adm_mp} / {adm_mx}")
    print(f"  omitted clusters       median/p90/max:  {om_cm} / {om_cp} / {om_cx}")
    print(f"  empty overlays:                     {empty_overlays} / {len(records)}")
    print(f"  over-budget renderings:             {over_budget} / {len(records)}")
    print(f"  tool outputs truncated:             {truncation_count}")
    print(f"  OOW clusters admitted (total):      {oow_admitted_total}")
    print(f"  IW  clusters admitted (total):      {iw_admitted_total}")
    print(f"\n  admitted clusters by type (total):")
    for t in sorted(admitted_clusters_by_type_total):
        print(
            f"    {t:30s}  clusters={admitted_clusters_by_type_total[t]:4,}  "
            f"members={admitted_members_by_type_total[t]:5,}"
        )

    audit = {
        "schema_version":  "v0.2.1",
        "stage":           f"context construction (operational v0.2.1 — B{budget})",
        "locked_parameters": {
            "K":                K,
            "tool_output_cap":  TOOL_OUTPUT_CAP,
            "tokenizer":        TOKENIZER,
            "overlay_budget":   budget,
            "ranking":          "OB-002 §3.0 meta-rule + §3.1 lexicographic tiers + §3.4 tiebreaks",
            "serialization":    "OB-002 §3.5 compressed line + §3.5a type+claim cluster dedup",
        },
        "questions_processed":           len(records),
        "raw_log_token_stats":           {"median": log_m, "p90": log_p, "max": log_x},
        "overlay_token_stats":           {"median": ov_m, "p90": ov_p, "max": ov_x},
        "combined_token_stats":          {"median": tot_m, "p90": tot_p, "max": tot_x},
        "admitted_cluster_stats":        {"median": adm_cm, "p90": adm_cp, "max": adm_cx},
        "admitted_member_stats":         {"median": adm_mm, "p90": adm_mp, "max": adm_mx},
        "omitted_cluster_stats":         {"median": om_cm, "p90": om_cp, "max": om_cx},
        "empty_overlays":                empty_overlays,
        "over_budget":                   over_budget,
        "tool_outputs_truncated":        truncation_count,
        "out_of_window_clusters_total":  oow_admitted_total,
        "in_window_clusters_total":      iw_admitted_total,
        "admitted_clusters_by_type_total": dict(admitted_clusters_by_type_total),
        "admitted_members_by_type_total":  dict(admitted_members_by_type_total),
    }
    out_audit.write_text(json.dumps(audit, indent=2))
    print(f"\nWrote {out_audit}")


if __name__ == "__main__":
    main()
