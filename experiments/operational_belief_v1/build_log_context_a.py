#!/usr/bin/env python3
"""
Operational Belief v0.1 — System A context builder.

For each question in questions.jsonl, renders the last K=20 turns of the
session up to turn_idx T as the raw-log grounding payload. Applies the
locked 500-token cap per tool output. Architectural cutoff: no turns
with turn_idx > T can appear in the rendering.

This is the SHARED raw-log payload — System B receives exactly this
plus a belief overlay. Cross-system rendering parity is enforced by
re-using the same render_raw_log_payload() function from this module
inside build_belief_overlay_context_b.py.

No LLM calls. No answer generation. No scoring.

Outputs:
  operational_belief_v1/data/contexts_a.jsonl
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter, defaultdict

import tiktoken

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent
TKOS_DATA = STORM_ROOT / "tkos_log_replay" / "data"

NORMALIZED      = TKOS_DATA / "sessions_normalized.jsonl"
QUESTIONS_PATH  = ROOT / "questions.jsonl"
OUT_CONTEXTS    = ROOT / "data" / "contexts_a.jsonl"

# --- LOCKED v0.1 PARAMETERS (§3.1 of the pre-reg) ---------------------------
K = 20
TOOL_OUTPUT_CAP = 500
TOKENIZER = "cl100k_base"

enc = tiktoken.get_encoding(TOKENIZER)


def load_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(l) for l in path.open()]


def load_sessions() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    with NORMALIZED.open() as f:
        for line in f:
            t = json.loads(line)
            out[t["session_id"]].append(t)
    for sid in out:
        out[sid].sort(key=lambda x: x["turn_idx"])
    return dict(out)


def truncate_tool_output(out_summary: str, cap: int = TOOL_OUTPUT_CAP) -> tuple[str, bool]:
    """Token-aware truncation. Returns (rendered, was_truncated)."""
    pre_tokens = enc.encode(out_summary)
    if len(pre_tokens) <= cap:
        return out_summary, False
    head = enc.decode(pre_tokens[:cap])
    return f"{head}\n[+{len(pre_tokens) - cap} tokens elided]", True


def render_turn(t: dict) -> tuple[str, int]:
    """Render one turn into a string. Returns (text, n_tool_outputs_truncated)."""
    role = t.get("role", "?")
    parts = [f"[turn {t['turn_idx']} / {role}]"]
    text = (t.get("text") or "").strip()
    thinking = (t.get("thinking") or "").strip()
    if text:
        parts.append(text)
    if thinking:
        parts.append(f"<thinking>{thinking}</thinking>")
    for tu in (t.get("tool_uses") or []):
        name = tu.get("name", "?")
        inp = tu.get("input_summary") or ""
        parts.append(f"<tool_use {name}>{inp}</tool_use>")
    n_truncated = 0
    for tr in (t.get("tool_results") or []):
        out_summary = tr.get("output_summary") or ""
        is_err = tr.get("is_error", False)
        rendered, was_truncated = truncate_tool_output(out_summary, TOOL_OUTPUT_CAP)
        if was_truncated:
            n_truncated += 1
        err_tag = " is_error=true" if is_err else ""
        parts.append(f"<tool_result{err_tag}>{rendered}</tool_result>")
    return "\n".join(parts), n_truncated


def render_raw_log_payload(turns: list[dict], T: int, k: int = K) -> tuple[str, dict]:
    """
    Render the last k turns up to turn_idx T as a single payload string.
    Architectural cutoff: no turn with turn_idx > T appears in the output.
    Returns (payload, audit_metadata).
    """
    window_lo = T - k + 1
    in_window = [t for t in turns if window_lo <= t["turn_idx"] <= T]
    # Sort by turn_idx ascending (already sorted upstream, but defensive)
    in_window.sort(key=lambda x: x["turn_idx"])
    rendered_parts: list[str] = []
    n_truncated = 0
    for t in in_window:
        body, trunc = render_turn(t)
        rendered_parts.append(body)
        n_truncated += trunc
    payload = "\n\n".join(rendered_parts) if rendered_parts else "(no turns in lookback window)"
    tokens = len(enc.encode(payload))
    meta = {
        "turns_in_window": len(in_window),
        "tool_outputs_truncated": n_truncated,
        "tokens": tokens,
        "window_start_turn": window_lo,
        "window_end_turn":   T,
    }
    # Cutoff sanity: assert nothing > T
    for t in in_window:
        if t["turn_idx"] > T:
            raise RuntimeError(f"cutoff violation: turn {t['turn_idx']} > T={T}")
    return payload, meta


def main() -> None:
    print("Loading inputs...")
    questions = load_jsonl(QUESTIONS_PATH)
    sessions  = load_sessions()
    print(f"  {len(questions)} questions, {len(sessions):,} sessions")

    print("Building System A contexts...")
    records: list[dict] = []
    token_stats: list[int] = []
    truncation_count = 0
    turns_in_window_stats: list[int] = []
    cutoff_violations = 0

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
                "system":           "A",
                "rendering":        "raw_log_K20_cap500",
                "rendered":         "(session not found)",
                "token_count":      0,
                "turns_in_window":  0,
                "tool_outputs_truncated": 0,
                "cutoff_violation": False,
            })
            continue
        try:
            payload, meta = render_raw_log_payload(turns, T, K)
        except RuntimeError as e:
            cutoff_violations += 1
            payload = "(cutoff violation; see audit)"
            meta = {"turns_in_window": 0, "tool_outputs_truncated": 0, "tokens": 0, "window_start_turn": T-K+1, "window_end_turn": T}

        records.append({
            "question_id":      q["question_id"],
            "session_id":       sid,
            "turn_idx":         T,
            "category":         q["category"],
            "system":           "A",
            "rendering":        "raw_log_K20_cap500",
            "rendered":         payload,
            "token_count":      meta["tokens"],
            "turns_in_window":  meta["turns_in_window"],
            "tool_outputs_truncated": meta["tool_outputs_truncated"],
            "window_start_turn": meta["window_start_turn"],
            "window_end_turn":   meta["window_end_turn"],
        })
        token_stats.append(meta["tokens"])
        truncation_count += meta["tool_outputs_truncated"]
        turns_in_window_stats.append(meta["turns_in_window"])

    OUT_CONTEXTS.parent.mkdir(exist_ok=True)
    with OUT_CONTEXTS.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"\nWrote {OUT_CONTEXTS}  ({len(records)} contexts)")

    # Quick summary
    if token_stats:
        ts_sorted = sorted(token_stats)
        n = len(ts_sorted)
        median = ts_sorted[n // 2]
        p90    = ts_sorted[int(n * 0.9)]
        mx     = ts_sorted[-1]
        print(f"\n  tokens  median / p90 / max:  {median} / {p90} / {mx}")
    print(f"  tool outputs truncated:    {truncation_count}")
    print(f"  cutoff violations:         {cutoff_violations}")


if __name__ == "__main__":
    main()
