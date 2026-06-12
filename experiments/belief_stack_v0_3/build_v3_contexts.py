#!/usr/bin/env python3
"""
Belief Stack v0.3 — Context builder for the 3 arms.

LOCKED v0.3 setup:
  Arm A — Raw Context Large (strong baseline):
    K=20 raw recent turns + tool-output cap (matched to v0.1 / v0.2.2)
    + strong reconstruction system prompt (in generate step)

  Arm B — Belief Overlay Small:
    Belief overlay only (§3.5a deduped, ranked, budget=500 tokens).
    NO raw log. NO scratchpad. Substitutive, not additive.

  Arm C — Belief Overlay + Minimal Evidence:
    Belief overlay (§3.5a deduped, ranked, budget=500 tokens)
    + last K=3 turns of session for execution-time scratchpad.

Reuses v0.1 substrate (75 questions, 164 sessions, 13,481 belief
instances) and v0.2.2 overlay rendering (§3.5a dedup + ranking).

Per OB-002 §0 fair-comparison constraint (v0.3 §4.1):
  Arm A receives the same underlying evidence used to derive the
  belief state — the raw session log K=20. Arms B and C receive
  the maintained-state form of that evidence.

Outputs:
  belief_stack_v0_3/data/contexts_arm_a.jsonl
  belief_stack_v0_3/data/contexts_arm_b.jsonl
  belief_stack_v0_3/data/contexts_arm_c.jsonl
  belief_stack_v0_3/data/context_construction_audit.json
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import Counter, defaultdict

import tiktoken

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent
V1_ROOT = STORM_ROOT / "operational_belief_v1"
V2_ROOT = STORM_ROOT / "operational_belief_v2"

# Reuse v0.1 raw-log infrastructure
sys.path.insert(0, str(V1_ROOT))
from build_log_context_a import (  # noqa: E402
    K as K_V1,
    TOKENIZER,
    TOOL_OUTPUT_CAP,
    load_jsonl,
    load_sessions,
    render_raw_log_payload,
)

# Reuse v0.2.2 overlay rendering (§3.5a dedup + ranking)
sys.path.insert(0, str(V2_ROOT))
from build_overlay_context_b_v2 import build_overlay  # noqa: E402

QUESTIONS_PATH = V1_ROOT / "questions.jsonl"
BELIEFS_PATH = V1_ROOT / "data" / "operational_beliefs.jsonl"

OUT_DIR = ROOT / "data"
OUT_A = OUT_DIR / "contexts_arm_a.jsonl"
OUT_B = OUT_DIR / "contexts_arm_b.jsonl"
OUT_C = OUT_DIR / "contexts_arm_c.jsonl"
OUT_AUDIT = OUT_DIR / "context_construction_audit.json"

# LOCKED v0.3 parameters
ARM_A_K = 20         # full raw log window (matches v0.1 / v0.2.2)
ARM_B_OVERLAY_BUDGET = 500   # comfortable overlay budget per OB-002 v0.2.2 lock
ARM_C_OVERLAY_BUDGET = 500
ARM_C_SCRATCHPAD_K = 3       # last K turns as execution-time scratchpad

enc = tiktoken.get_encoding(TOKENIZER)


def stats(arr):
    if not arr:
        return {"min": None, "p10": None, "p50": None, "p90": None, "max": None}
    s = sorted(arr)
    n = len(s)
    return {
        "min": s[0],
        "p10": s[max(0, n // 10 - 1)],
        "p50": s[n // 2],
        "p90": s[min(n - 1, int(n * 0.9))],
        "max": s[-1],
    }


def main() -> None:
    print("Loading inputs...")
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

    OUT_DIR.mkdir(exist_ok=True)
    fa = OUT_A.open("w")
    fb = OUT_B.open("w")
    fc = OUT_C.open("w")

    # Telemetry
    a_tokens: list[int] = []
    b_tokens: list[int] = []
    c_tokens: list[int] = []
    a_log_tokens: list[int] = []
    b_overlay_tokens: list[int] = []
    c_overlay_tokens: list[int] = []
    c_scratchpad_tokens: list[int] = []
    b_admitted_clusters: list[int] = []
    c_admitted_clusters: list[int] = []
    arm_a_truncations = 0
    arm_c_truncations = 0
    missing_sessions = 0

    for q in questions:
        sid = q["session_id"]
        T = q["turn_idx"]
        qid = q["question_id"]
        category = q["category"]

        turns = sessions.get(sid, [])
        if not turns:
            missing_sessions += 1
            # Write placeholder records so the qid line counts match across arms
            for f in (fa, fb, fc):
                f.write(
                    json.dumps({
                        "question_id": qid,
                        "session_id":  sid,
                        "turn_idx":    T,
                        "category":    category,
                        "rendered":    "(session not found)",
                        "token_count": 0,
                    })
                    + "\n"
                )
            continue

        # ─── Arm A: full raw log (K=20) ────────────────────────────────
        log_a, log_a_meta = render_raw_log_payload(turns, T, ARM_A_K)
        a_full_tokens = len(enc.encode(log_a))

        rec_a = {
            "question_id":  qid,
            "session_id":   sid,
            "turn_idx":     T,
            "category":     category,
            "arm":          "A",
            "rendering":    f"raw_log_K{ARM_A_K}_cap{TOOL_OUTPUT_CAP}_strong_baseline",
            "rendered":     log_a,
            "token_count":  a_full_tokens,
            "log_tokens":   log_a_meta["tokens"],
            "turns_in_window":        log_a_meta["turns_in_window"],
            "tool_outputs_truncated": log_a_meta["tool_outputs_truncated"],
        }
        fa.write(json.dumps(rec_a) + "\n")
        a_tokens.append(a_full_tokens)
        a_log_tokens.append(log_a_meta["tokens"])
        arm_a_truncations += log_a_meta["tool_outputs_truncated"]

        # ─── Arm B: belief overlay only (no raw log) ───────────────────
        beliefs_for_session = beliefs_by_session.get(sid, [])
        overlay_b, ov_b_meta = build_overlay(
            beliefs_for_session, T, ARM_B_OVERLAY_BUDGET, K_window=K_V1
        )
        b_full_tokens = len(enc.encode(overlay_b))

        rec_b = {
            "question_id":  qid,
            "session_id":   sid,
            "turn_idx":     T,
            "category":     category,
            "arm":          "B",
            "rendering":    f"belief_overlay_only_budget{ARM_B_OVERLAY_BUDGET}",
            "rendered":     overlay_b,
            "token_count":  b_full_tokens,
            "overlay_tokens":            ov_b_meta["overlay_tokens"],
            "overlay_meta":              ov_b_meta,
        }
        fb.write(json.dumps(rec_b) + "\n")
        b_tokens.append(b_full_tokens)
        b_overlay_tokens.append(ov_b_meta["overlay_tokens"])
        b_admitted_clusters.append(ov_b_meta["admitted_cluster_count"])

        # ─── Arm C: overlay + K=3 scratchpad ────────────────────────────
        overlay_c, ov_c_meta = build_overlay(
            beliefs_for_session, T, ARM_C_OVERLAY_BUDGET, K_window=K_V1
        )
        scratchpad_c, scratch_meta = render_raw_log_payload(turns, T, ARM_C_SCRATCHPAD_K)

        # Compose: overlay first, then scratchpad
        combined_c = overlay_c + "\n\n=== Recent scratchpad (last 3 turns) ===\n" + scratchpad_c
        c_full_tokens = len(enc.encode(combined_c))

        rec_c = {
            "question_id":  qid,
            "session_id":   sid,
            "turn_idx":     T,
            "category":     category,
            "arm":          "C",
            "rendering":    f"belief_overlay_budget{ARM_C_OVERLAY_BUDGET}_plus_K{ARM_C_SCRATCHPAD_K}_scratchpad",
            "rendered":     combined_c,
            "token_count":  c_full_tokens,
            "overlay_tokens":    ov_c_meta["overlay_tokens"],
            "scratchpad_tokens": scratch_meta["tokens"],
            "scratchpad_turns_in_window":    scratch_meta["turns_in_window"],
            "scratchpad_tool_outputs_truncated": scratch_meta["tool_outputs_truncated"],
            "overlay_meta":      ov_c_meta,
        }
        fc.write(json.dumps(rec_c) + "\n")
        c_tokens.append(c_full_tokens)
        c_overlay_tokens.append(ov_c_meta["overlay_tokens"])
        c_scratchpad_tokens.append(scratch_meta["tokens"])
        c_admitted_clusters.append(ov_c_meta["admitted_cluster_count"])
        arm_c_truncations += scratch_meta["tool_outputs_truncated"]

    fa.close()
    fb.close()
    fc.close()

    # ─── Audit ────────────────────────────────────────────────────────
    print()
    print(f"Wrote {OUT_A}, {OUT_B}, {OUT_C}")
    print()
    print("Token totals (input):")
    print(f"  Arm A  median/p90/max:  {stats(a_tokens)['p50']} / {stats(a_tokens)['p90']} / {stats(a_tokens)['max']}")
    print(f"  Arm B  median/p90/max:  {stats(b_tokens)['p50']} / {stats(b_tokens)['p90']} / {stats(b_tokens)['max']}")
    print(f"  Arm C  median/p90/max:  {stats(c_tokens)['p50']} / {stats(c_tokens)['p90']} / {stats(c_tokens)['max']}")

    a_mean = sum(a_tokens) / max(1, len(a_tokens))
    b_mean = sum(b_tokens) / max(1, len(b_tokens))
    c_mean = sum(c_tokens) / max(1, len(c_tokens))
    print()
    print("Mean input tokens (for D7 token gate):")
    print(f"  Arm A:  {a_mean:.0f}")
    print(f"  Arm B:  {b_mean:.0f}  ({b_mean/max(1,a_mean)*100:.1f}% of Arm A)")
    print(f"  Arm C:  {c_mean:.0f}  ({c_mean/max(1,a_mean)*100:.1f}% of Arm A)")
    print()
    print(f"  D7 threshold (≤ 50% of Arm A):  Arm B {'PASS' if b_mean/a_mean <= 0.5 else 'FAIL'},  Arm C {'PASS' if c_mean/a_mean <= 0.5 else 'FAIL'}")
    print()
    print(f"Missing sessions:               {missing_sessions}")
    print(f"Arm A tool outputs truncated:   {arm_a_truncations}")
    print(f"Arm C tool outputs truncated:   {arm_c_truncations}")
    print()
    print(f"Arm B admitted clusters    median/p90/max:  {stats(b_admitted_clusters)['p50']} / {stats(b_admitted_clusters)['p90']} / {stats(b_admitted_clusters)['max']}")
    print(f"Arm C admitted clusters    median/p90/max:  {stats(c_admitted_clusters)['p50']} / {stats(c_admitted_clusters)['p90']} / {stats(c_admitted_clusters)['max']}")

    audit = {
        "schema_version": "v0.3",
        "stage":          "context construction (belief stack v0.3)",
        "locked_parameters": {
            "arm_a_K":                  ARM_A_K,
            "arm_b_overlay_budget":     ARM_B_OVERLAY_BUDGET,
            "arm_c_overlay_budget":     ARM_C_OVERLAY_BUDGET,
            "arm_c_scratchpad_K":       ARM_C_SCRATCHPAD_K,
            "tool_output_cap":          TOOL_OUTPUT_CAP,
            "tokenizer":                TOKENIZER,
            "overlay_ranking":          "OB-002 §3.0 meta-rule + §3.1 tiers + §3.4 tiebreaks",
            "overlay_serialization":    "OB-002 §3.5 + §3.5a type+claim cluster dedup",
            "fair_comparison_constraint": "Arm A and Arms B/C derive from same underlying session — raw vs maintained-state form",
        },
        "questions_processed":  len(questions),
        "missing_sessions":     missing_sessions,
        "arm_a": {
            "input_token_stats":              stats(a_tokens),
            "raw_log_token_stats":            stats(a_log_tokens),
            "mean_input_tokens":              a_mean,
            "tool_outputs_truncated_total":   arm_a_truncations,
        },
        "arm_b": {
            "input_token_stats":              stats(b_tokens),
            "overlay_token_stats":            stats(b_overlay_tokens),
            "admitted_cluster_stats":         stats(b_admitted_clusters),
            "mean_input_tokens":              b_mean,
            "mean_pct_of_arm_a":              b_mean / max(1, a_mean) * 100,
            "d7_pass":                        b_mean / max(1, a_mean) <= 0.5,
        },
        "arm_c": {
            "input_token_stats":              stats(c_tokens),
            "overlay_token_stats":            stats(c_overlay_tokens),
            "scratchpad_token_stats":         stats(c_scratchpad_tokens),
            "admitted_cluster_stats":         stats(c_admitted_clusters),
            "tool_outputs_truncated_total":   arm_c_truncations,
            "mean_input_tokens":              c_mean,
            "mean_pct_of_arm_a":              c_mean / max(1, a_mean) * 100,
            "d7_pass":                        c_mean / max(1, a_mean) <= 0.5,
        },
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"\nWrote {OUT_AUDIT}")


if __name__ == "__main__":
    main()
