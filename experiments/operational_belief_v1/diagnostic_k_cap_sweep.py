#!/usr/bin/env python3
"""
Operational Belief v0.1 — Pre-lock diagnostic: K x tool_cap sweep.

Non-outcome diagnostic. NOT a tuning step. Reports coverage and budget
properties of (K, tool_cap) combinations against the TKOS substrate so
the engineering parameters can be locked empirically rather than by gut.

For each (K, cap) in {10, 20, 50} x {250, 500, 1000}, this script computes
on a sample of (session, T) anchor points:

  - coverage_supporting:   % of belief-supporting turns in [0, T] that fall in [T-K+1, T]
  - coverage_error:        % of error turns in [0, T] that fall in [T-K+1, T]
  - tokens_median/p90/max: distribution of System A context token counts
  - overflow_rate:         % of contexts whose token count > BUDGET (6000 reference)
  - truncation_rate:       % of tool_results in the window that exceed `cap`

Does NOT: generate answers, judge outputs, or examine answer quality.

Output:
  operational_belief_v1/data/diagnostic_k_cap_sweep.json
"""

from __future__ import annotations

import json
import pathlib
import random
from collections import defaultdict

import tiktoken

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent
TKOS_DATA = STORM_ROOT / "tkos_log_replay" / "data"

NORMALIZED = TKOS_DATA / "sessions_normalized.jsonl"
BELIEFS    = TKOS_DATA / "phase2_belief_timelines.jsonl"
OUT_PATH   = ROOT / "data" / "diagnostic_k_cap_sweep.json"

K_VALUES        = [10, 20, 50]
CAP_VALUES      = [250, 500, 1000]
BUDGET_REFERENCE = 6000
SAMPLE_SEED     = 20260601
SAMPLE_PER_SESSION = 3      # T at 25%, 50%, 75% of session length

enc = tiktoken.get_encoding("cl100k_base")


def load_turns_by_session() -> dict[str, list[dict]]:
    """Return {session_id: [turns sorted by turn_idx]}."""
    sessions: dict[str, list[dict]] = defaultdict(list)
    with NORMALIZED.open() as f:
        for line in f:
            t = json.loads(line)
            sessions[t["session_id"]].append(t)
    for sid in sessions:
        sessions[sid].sort(key=lambda x: x["turn_idx"])
    return dict(sessions)


def load_beliefs_by_session() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    with BELIEFS.open() as f:
        for line in f:
            b = json.loads(line)
            out[b["session_id"]].append(b)
    return dict(out)


def render_turn(t: dict, tool_cap: int) -> tuple[str, list[tuple[int, int]]]:
    """
    Render a single turn into a string. Returns (rendered_text, per_tool_token_counts).
    Per-tool counts are (pre_cap, post_cap) for the truncation rate.
    """
    role = t.get("role", "?")
    parts = [f"[turn {t['turn_idx']} / {role}]"]
    text = (t.get("text") or "").strip()
    thinking = (t.get("thinking") or "").strip()
    if text:
        parts.append(text)
    # thinking is internal — include compactly (mirrors what an assistant trace would carry)
    if thinking:
        parts.append(f"<thinking>{thinking}</thinking>")
    # tool_uses
    for tu in (t.get("tool_uses") or []):
        name = tu.get("name", "?")
        inp = tu.get("input_summary") or ""
        parts.append(f"<tool_use {name}>{inp}</tool_use>")
    # tool_results (these are the load-bearing ones for the cap)
    per_tool_counts: list[tuple[int, int]] = []
    for tr in (t.get("tool_results") or []):
        out_sum = (tr.get("output_summary") or "")
        is_err  = tr.get("is_error", False)
        pre_toks = len(enc.encode(out_sum))
        if pre_toks > tool_cap:
            # truncate to head + elision marker (token-aware via re-encoding the prefix)
            head_tokens = enc.encode(out_sum)[:tool_cap]
            out_sum = enc.decode(head_tokens) + f"\n[+{pre_toks - tool_cap} tokens elided]"
        post_toks = len(enc.encode(out_sum))
        per_tool_counts.append((pre_toks, post_toks))
        err_tag = " is_error=true" if is_err else ""
        parts.append(f"<tool_result{err_tag}>{out_sum}</tool_result>")
    return "\n".join(parts), per_tool_counts


def turn_is_error(t: dict) -> bool:
    if t.get("has_error"):
        return True
    for tr in (t.get("tool_results") or []):
        if tr.get("is_error"):
            return True
    return False


def supporting_turn_indices(beliefs: list[dict]) -> set[int]:
    """
    Return the set of turn_idx values that are belief-supporting events
    (born / refreshed / retired / contradicted) across all beliefs in
    the session.
    """
    out: set[int] = set()
    for b in beliefs:
        for ev in (b.get("events") or []):
            ti = ev.get("turn_idx")
            if ti is not None:
                out.add(ti)
    return out


def main() -> None:
    OUT_PATH.parent.mkdir(exist_ok=True)
    random.seed(SAMPLE_SEED)

    print("Loading sessions...")
    sessions = load_turns_by_session()
    beliefs  = load_beliefs_by_session()
    print(f"  {len(sessions):,} sessions, {sum(len(t) for t in sessions.values()):,} total turns")

    # Build sample points: T at 25%, 50%, 75% of session length for each
    # session with at least max(K_VALUES) turns so the window is meaningful.
    min_len = max(K_VALUES) + 1
    eligible = [sid for sid, turns in sessions.items() if len(turns) >= min_len]
    print(f"  {len(eligible):,} sessions long enough for sampling (>= {min_len} turns)")

    sample_points: list[tuple[str, int]] = []
    for sid in eligible:
        n = len(sessions[sid])
        for frac in (0.25, 0.50, 0.75):
            T = max(min_len - 1, int(n * frac) - 1)
            T = min(T, n - 1)
            sample_points.append((sid, T))
    print(f"  {len(sample_points):,} sample points (sessions x 3 T positions)")

    # For each (K, cap), compute metrics over all sample points
    results: dict[str, dict] = {}
    for K in K_VALUES:
        for cap in CAP_VALUES:
            key = f"K={K} cap={cap}"
            print(f"\n--- {key} ---")

            tokens_list: list[int] = []
            cov_sup_list: list[float] = []
            cov_err_list: list[float] = []
            truncation_per_tool: list[int] = []  # 1 if truncated, 0 if not
            overflow_count = 0
            ctx_with_zero_supporting = 0
            ctx_with_zero_errors = 0

            for sid, T in sample_points:
                turns = sessions[sid]
                turn_by_idx = {t["turn_idx"]: t for t in turns}
                belief_list = beliefs.get(sid, [])
                supp_idx = supporting_turn_indices(belief_list)

                window_start = T - K + 1
                window_indices = [i for i in range(window_start, T + 1) if i in turn_by_idx]

                # Render context for this sample point at this (K, cap)
                rendered_parts: list[str] = []
                for ti in window_indices:
                    body, tool_counts = render_turn(turn_by_idx[ti], cap)
                    rendered_parts.append(body)
                    for pre, post in tool_counts:
                        truncation_per_tool.append(1 if pre > cap else 0)
                full = "\n\n".join(rendered_parts)
                ntoks = len(enc.encode(full))
                tokens_list.append(ntoks)
                if ntoks > BUDGET_REFERENCE:
                    overflow_count += 1

                # Coverage: belief-supporting turns
                supp_in_window = sum(1 for ti in window_indices if ti in supp_idx)
                supp_in_history = sum(1 for ti in supp_idx if ti <= T)
                if supp_in_history > 0:
                    cov_sup_list.append(supp_in_window / supp_in_history)
                else:
                    ctx_with_zero_supporting += 1
                    cov_sup_list.append(None)

                # Coverage: error turns
                err_indices = [ti for ti in range(0, T + 1) if ti in turn_by_idx and turn_is_error(turn_by_idx[ti])]
                err_in_window = sum(1 for ti in err_indices if ti >= window_start)
                if err_indices:
                    cov_err_list.append(err_in_window / len(err_indices))
                else:
                    ctx_with_zero_errors += 1
                    cov_err_list.append(None)

            # Aggregate
            applicable_sup = [x for x in cov_sup_list if x is not None]
            applicable_err = [x for x in cov_err_list if x is not None]
            tokens_sorted = sorted(tokens_list)
            n = len(tokens_list)
            median_tok = tokens_sorted[n // 2]
            p90_tok    = tokens_sorted[int(n * 0.9)]
            max_tok    = tokens_sorted[-1]
            n_tools    = len(truncation_per_tool)
            trunc_rate = (sum(truncation_per_tool) / n_tools) if n_tools else 0.0

            res = {
                "K":                              K,
                "tool_cap":                       cap,
                "sample_points":                  n,
                "coverage_supporting_mean":       (sum(applicable_sup) / len(applicable_sup)) if applicable_sup else None,
                "coverage_supporting_applicable": len(applicable_sup),
                "ctx_with_zero_supporting_in_history": ctx_with_zero_supporting,
                "coverage_error_mean":            (sum(applicable_err) / len(applicable_err)) if applicable_err else None,
                "coverage_error_applicable":      len(applicable_err),
                "ctx_with_zero_errors_in_history":ctx_with_zero_errors,
                "tokens_median":                  median_tok,
                "tokens_p90":                     p90_tok,
                "tokens_max":                     max_tok,
                "overflow_rate_vs_budget6000":    overflow_count / n,
                "n_tool_outputs_seen":            n_tools,
                "tool_truncation_rate":           trunc_rate,
            }
            results[key] = res
            print(f"  cov_sup_mean: {res['coverage_supporting_mean']:.2%}  (applicable={res['coverage_supporting_applicable']})")
            print(f"  cov_err_mean: {res['coverage_error_mean']:.2%}  (applicable={res['coverage_error_applicable']})")
            print(f"  tokens median/p90/max: {median_tok} / {p90_tok} / {max_tok}")
            print(f"  overflow vs 6000: {res['overflow_rate_vs_budget6000']:.2%}")
            print(f"  tool truncation rate: {trunc_rate:.2%} (of {n_tools:,} tool outputs)")

    OUT_PATH.write_text(json.dumps({
        "sample_seed":         SAMPLE_SEED,
        "sample_per_session":  SAMPLE_PER_SESSION,
        "sample_total":        len(sample_points),
        "budget_reference":    BUDGET_REFERENCE,
        "results":             results,
    }, indent=2))
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()
