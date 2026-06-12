#!/usr/bin/env python3
"""
Belief Stack v0.4a — Context builder for the 5-arm mechanism ablation.

LOCKED v0.4a setup (per pre-registration §1, §2, §3):

  Arm A — Raw K=20 log + strong baseline:
    Identical to v0.3 Arm A. K=20 raw recent turns, tool-output cap 500.
    Strong reconstruction prompt applied at generation time, not here.

  Arm B — LLM-generated free-form prose summary at matched budget:
    For each (session, T), the same generator (gpt-4o-2024-08-06, T=0,
    seed 20260601) is asked to produce a prose summary of "what is
    currently true" from the same active-belief evidence Arms C/D/E
    read from. Output capped at ~285 input tokens. The competing
    hypothesis ("maintained-state-in-any-shape beats structure") gets
    its strongest case at the matched budget.

  Arm C — Structured claims only:
    `belief_type :: operational_claim` per cluster. No lifecycle marker,
    no warrant fields. §3.5a dedup + ranking machinery as in v0.2.2/v0.3.

  Arm D — Claims + warrants (no lifecycle marker):
    `belief_type :: operational_claim (auth=AUTH, evidence=[T1,T2,...],
    decay=DECAY, last=LAST_UPDATED)`. No `[lifecycle]` prefix.

  Arm E — Full discipline (claims + warrants + lifecycle):
    `[LIFECYCLE] belief_type :: operational_claim (auth=AUTH,
    evidence=[T1,T2,...], decay=DECAY, last=LAST_UPDATED)`. Each step
    above D adds the lifecycle stage marker, surfacing the full
    Belief Stack discipline.

All four belief-based arms (B/C/D/E) target ~285 input tokens ± 10%.
Header reserve computed against worst-case render so the budget is
honestly enforced (same discipline as v0.2.2 §3.2 / §3.5).

ANTI-CURATION DISCIPLINE: this script generates ALL 75 × 5 = 375
contexts BEFORE any answer generation. No iterative tuning. Once
written, the contexts feed `generate_v4a_answers.py` unchanged.

Outputs:
  belief_stack_v0_4a/data/contexts_arm_a.jsonl
  belief_stack_v0_4a/data/contexts_arm_b.jsonl
  belief_stack_v0_4a/data/contexts_arm_c.jsonl
  belief_stack_v0_4a/data/contexts_arm_d.jsonl
  belief_stack_v0_4a/data/contexts_arm_e.jsonl
  belief_stack_v0_4a/data/context_construction_audit.json
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from collections import Counter, defaultdict

import tiktoken

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent
V1_ROOT = STORM_ROOT / "operational_belief_v1"
V2_ROOT = STORM_ROOT / "operational_belief_v2"

# Reuse v0.1 raw-log infrastructure (Arm A unchanged from v0.3)
sys.path.insert(0, str(V1_ROOT))
from build_log_context_a import (  # noqa: E402
    K as K_V1,
    TOKENIZER,
    TOOL_OUTPUT_CAP,
    load_jsonl,
    load_sessions,
    render_raw_log_payload,
)

# Reuse v0.2.2 lifecycle / clustering / ranking machinery
sys.path.insert(0, str(V2_ROOT))
from build_overlay_context_b_v2 import (  # noqa: E402
    AUTH_ABBR,
    AUTH_RANK,
    INCLUDED_LIFECYCLE_STATES,
    at_T_lifecycle,
    at_T_authority,
    cluster_candidates,
    cluster_sort_key,
    is_out_of_window,
)

# OpenAI client for Arm B summarization (LOCKED generator)
from openai import OpenAI, APIError, RateLimitError, APITimeoutError, APIStatusError
from dotenv import load_dotenv

# Load .env from storm root (same pattern as v0.3)
load_dotenv(STORM_ROOT / ".env")

QUESTIONS_PATH = V1_ROOT / "questions.jsonl"
BELIEFS_PATH = V1_ROOT / "data" / "operational_beliefs.jsonl"

OUT_DIR = ROOT / "data"
OUT_A = OUT_DIR / "contexts_arm_a.jsonl"
OUT_B = OUT_DIR / "contexts_arm_b.jsonl"
OUT_C = OUT_DIR / "contexts_arm_c.jsonl"
OUT_D = OUT_DIR / "contexts_arm_d.jsonl"
OUT_E = OUT_DIR / "contexts_arm_e.jsonl"
OUT_AUDIT = OUT_DIR / "context_construction_audit.json"

# ─── LOCKED v0.4a parameters ───────────────────────────────────────────
ARM_A_K          = 20      # Same as v0.3 Arm A
BUDGET_TOKENS    = 285     # Matched budget for B/C/D/E per D4 lock
SUMMARY_MAX_OUT  = 285     # Arm B LLM output cap
SUMMARIZER_MODEL = "gpt-4o-2024-08-06"
SUMMARIZER_TEMP  = 0
SUMMARIZER_SEED  = 20260601

# Retry config for the summarizer LLM calls
RETRY_MAX        = 5
RETRY_INITIAL    = 4.0     # seconds

enc = tiktoken.get_encoding(TOKENIZER)


# ─── Per-arm line renderers ────────────────────────────────────────────

def render_arm_c_line(cluster: dict, T: int) -> str:
    """Arm C: claims only — `belief_type :: claim` (no warrant, no lifecycle)."""
    rep = cluster["representative"]
    claim_short = (rep.get("operational_claim") or "")[:80]
    base = f"{rep['belief_type']} :: {claim_short}"
    if cluster["cluster_count"] > 1:
        base += f" (n={cluster['cluster_count']})"
    return base


def render_arm_d_line(cluster: dict, T: int) -> str:
    """Arm D: claims + warrants — `belief_type :: claim (auth=..., evidence=..., decay=..., last=...)`.

    No lifecycle stage marker.
    """
    rep = cluster["representative"]
    claim_short = (rep.get("operational_claim") or "")[:80]
    auth_abbr = AUTH_ABBR.get(cluster["cluster_authority"], cluster["cluster_authority"])
    ev_turns = rep.get("warrant_evidence_turns") or []
    ev_turns_at_T = [t for t in ev_turns if t <= T][:3]  # cap to 3 most recent for budget
    ev_str = "[" + ",".join(str(t) for t in ev_turns_at_T) + "]" if ev_turns_at_T else "[]"
    decay = rep.get("decay_status") or "unknown"
    last = cluster["cluster_last_updated"]
    base = (
        f"{rep['belief_type']} :: {claim_short} "
        f"(auth={auth_abbr}, evidence={ev_str}, decay={decay}, last={last}"
    )
    if cluster["cluster_count"] > 1:
        base += f", n={cluster['cluster_count']}"
    return base + ")"


def render_arm_e_line(cluster: dict, T: int) -> str:
    """Arm E: full discipline — `[LIFECYCLE] belief_type :: claim (auth, evidence, decay, last)`."""
    rep = cluster["representative"]
    claim_short = (rep.get("operational_claim") or "")[:80]
    auth_abbr = AUTH_ABBR.get(cluster["cluster_authority"], cluster["cluster_authority"])
    ev_turns = rep.get("warrant_evidence_turns") or []
    ev_turns_at_T = [t for t in ev_turns if t <= T][:3]
    ev_str = "[" + ",".join(str(t) for t in ev_turns_at_T) + "]" if ev_turns_at_T else "[]"
    decay = rep.get("decay_status") or "unknown"
    last = cluster["cluster_last_updated"]
    state = cluster["state"]
    base = (
        f"[{state}] {rep['belief_type']} :: {claim_short} "
        f"(auth={auth_abbr}, evidence={ev_str}, decay={decay}, last={last}"
    )
    if cluster["cluster_count"] > 1:
        base += f", n={cluster['cluster_count']}"
    return base + ")"


# ─── Header renderers ──────────────────────────────────────────────────

def make_header(arm_letter: str, budget: int, used: int, omitted: int,
                clusters_admitted: int, K_window: int) -> str:
    return (
        f"=== Belief overlay (v0.4a Arm {arm_letter}, "
        f"budget: {budget} tokens, used: {used}, omitted: {omitted}, "
        f"clusters: {clusters_admitted}, K={K_window}) ==="
    )


def header_reserve_tokens(arm_letter: str, budget: int, K_window: int) -> int:
    """Worst-case header reserve, computed up front to honor the cap."""
    placeholder = make_header(arm_letter, budget, 9999, 99, 99, K_window)
    return len(enc.encode(placeholder)) + 1


# ─── Belief candidate construction (shared across C/D/E + input to B) ──

def build_candidates_and_clusters(
    beliefs_for_session: list[dict], T: int, K_window: int = K_V1
) -> tuple[list[dict], list[dict]]:
    """Return (candidates, clusters) — same machinery as v0.2.2 §3.0 + §3.5a.

    Candidates: per-belief tuples filtered to {active, weakened, contradicted}.
    Clusters: §3.5a deduped + §3.0/§3.4 sorted.
    """
    candidates_raw = []
    for b in beliefs_for_session:
        state = at_T_lifecycle(b, T)
        if state is None or state not in INCLUDED_LIFECYCLE_STATES:
            continue
        last_updated = b.get("turn_last_updated", b["turn_first_seen"])
        if last_updated > T:
            rt = [ev["turn"] for ev in (b.get("revision_trail") or []) if ev["turn"] <= T]
            last_updated = max(rt) if rt else b["turn_first_seen"]
        oow = is_out_of_window(b, T, K_window)
        candidates_raw.append((b, state, last_updated, oow))

    clusters = cluster_candidates(candidates_raw, T)
    clusters.sort(key=cluster_sort_key)
    return candidates_raw, clusters


# ─── Generic overlay builder for arms C/D/E ────────────────────────────

def build_arm_overlay(
    arm_letter: str,
    clusters: list[dict],
    T: int,
    budget: int,
    K_window: int,
    render_fn,
) -> tuple[str, dict]:
    """Build a budgeted overlay for one arm using its line renderer.

    Mirrors v0.2.2 build_overlay structure but with per-arm rendering.
    """
    reserve = header_reserve_tokens(arm_letter, budget, K_window)
    body_budget = max(0, budget - reserve)

    admitted: list[dict] = []
    omitted: list[dict] = []
    body_used = 0

    for cluster in clusters:
        line = render_fn(cluster, T)
        line_tokens = len(enc.encode(line)) + 1  # +1 for newline
        if body_used + line_tokens <= body_budget:
            admitted.append(cluster)
            body_used += line_tokens
        else:
            omitted.append(cluster)

    header = make_header(arm_letter, budget, body_used, len(omitted), len(admitted), K_window)
    lines = [header]
    for c in admitted:
        lines.append(render_fn(c, T))

    # Add omitted-counts summary if it fits
    omitted_by_type = Counter(c["belief_type"] for c in omitted)
    if omitted_by_type:
        omitted_line = "# omitted clusters: " + ", ".join(
            f"{t}={n}" for t, n in sorted(omitted_by_type.items())
        )
        trial = "\n".join(lines + [omitted_line])
        if len(enc.encode(trial)) <= budget:
            lines.append(omitted_line)

    overlay = "\n".join(lines)
    overlay_tokens = len(enc.encode(overlay))

    admitted_by_type = Counter(c["belief_type"] for c in admitted)
    meta = {
        "arm":                      arm_letter,
        "overlay_tokens":           overlay_tokens,
        "budget_tokens":            budget,
        "K_window":                 K_window,
        "admitted_cluster_count":   len(admitted),
        "omitted_cluster_count":    len(omitted),
        "admitted_member_count":    sum(c["cluster_count"] for c in admitted),
        "omitted_member_count":     sum(c["cluster_count"] for c in omitted),
        "admitted_clusters_by_type": dict(admitted_by_type),
        "omitted_clusters_by_type":  dict(omitted_by_type),
        "lifecycle_at_T_counts":    dict(Counter(c["state"] for c in admitted)),
    }
    return overlay, meta


# ─── Arm B: LLM-summarized prose ───────────────────────────────────────

ARM_B_SYSTEM_PROMPT = """You receive a list of beliefs describing the current state of a coding-assistant session at a specific turn T. Each belief carries its type, claim, lifecycle stage at T, authority, evidence turns, and last-updated turn.

Your task: write a concise prose summary of what is currently true at this point in the session.

Constraints:
- Output in free-form prose. Do NOT use a structured format (no bullets, no headers, no lists).
- Aim for approximately 200-260 tokens.
- Do not invent facts not present in the input.
- Focus on what is currently active, pending, weakened, or contradicted — not on history.
- Write in present tense.
- Cover all the beliefs you receive, in whatever order best serves a reader trying to understand current session state."""


def make_arm_b_user_prompt(clusters_for_input: list[dict], T: int) -> str:
    """Render the active-belief substrate as JSON-like input for the LLM summarizer.

    Cluster shape: { belief_type, operational_claim, lifecycle_state,
                     authority, evidence_turns_at_T, decay_status,
                     last_updated_turn, cluster_count }.
    """
    payload = []
    for c in clusters_for_input:
        rep = c["representative"]
        ev_turns = rep.get("warrant_evidence_turns") or []
        ev_turns_at_T = [t for t in ev_turns if t <= T]
        payload.append({
            "belief_type":       rep["belief_type"],
            "operational_claim": (rep.get("operational_claim") or "")[:120],
            "lifecycle_state":   c["state"],
            "authority":         AUTH_ABBR.get(c["cluster_authority"], c["cluster_authority"]),
            "evidence_turns":    ev_turns_at_T,
            "decay_status":      rep.get("decay_status") or "unknown",
            "last_updated_turn": c["cluster_last_updated"],
            "cluster_count":     c["cluster_count"],
        })

    return (
        f"Turn T = {T}.\n\n"
        f"Active beliefs at T (JSON list):\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        f"Write the prose summary now."
    )


def summarize_for_arm_b(client: OpenAI, clusters: list[dict], T: int) -> dict:
    """One LLM call producing Arm B's free-form summary. Retries on transient errors."""
    user_prompt = make_arm_b_user_prompt(clusters, T)
    delay = RETRY_INITIAL
    last_err = None
    for attempt in range(1, RETRY_MAX + 1):
        try:
            t0 = time.time()
            resp = client.chat.completions.create(
                model=SUMMARIZER_MODEL,
                temperature=SUMMARIZER_TEMP,
                seed=SUMMARIZER_SEED,
                max_tokens=SUMMARY_MAX_OUT,
                messages=[
                    {"role": "system", "content": ARM_B_SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
            )
            wall = time.time() - t0
            choice = resp.choices[0]
            return {
                "summary_text":       choice.message.content or "",
                "summary_tokens":     resp.usage.completion_tokens,
                "summarizer_input_tokens": resp.usage.prompt_tokens,
                "model_resolved":     resp.model,
                "system_fingerprint": getattr(resp, "system_fingerprint", None),
                "finish_reason":      choice.finish_reason,
                "wall_seconds":       wall,
                "retry_attempts":     attempt - 1,
                "clusters_in_input":  len(clusters),
            }
        except (RateLimitError, APITimeoutError) as e:
            last_err = e
            sleep_for = delay
            print(f"    arm-B retry {attempt}/{RETRY_MAX} after {type(e).__name__}; sleeping {sleep_for:.1f}s",
                  flush=True)
            time.sleep(sleep_for)
            delay *= 2
        except APIStatusError as e:
            if 500 <= getattr(e, "status_code", 0) < 600:
                last_err = e
                sleep_for = delay
                print(f"    arm-B retry {attempt}/{RETRY_MAX} after {e.status_code}; sleeping {sleep_for:.1f}s",
                      flush=True)
                time.sleep(sleep_for)
                delay *= 2
            else:
                raise
    raise last_err if last_err else RuntimeError("arm-B retries exhausted")


# ─── Stats helper ──────────────────────────────────────────────────────

def stats(arr):
    if not arr:
        return {"min": None, "p10": None, "p50": None, "p90": None, "max": None,
                "mean": None}
    s = sorted(arr)
    n = len(s)
    return {
        "min":  s[0],
        "p10":  s[max(0, n // 10 - 1)],
        "p50":  s[n // 2],
        "p90":  s[min(n - 1, int(n * 0.9))],
        "max":  s[-1],
        "mean": sum(arr) / n,
    }


# ─── Main driver ───────────────────────────────────────────────────────

def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set (required for Arm B summarization)", file=sys.stderr)
        sys.exit(1)

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
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    fa = OUT_A.open("w")
    fb = OUT_B.open("w")
    fc = OUT_C.open("w")
    fd = OUT_D.open("w")
    fe = OUT_E.open("w")

    a_tokens: list[int] = []
    b_tokens: list[int] = []
    c_tokens: list[int] = []
    d_tokens: list[int] = []
    e_tokens: list[int] = []

    c_admitted: list[int] = []
    d_admitted: list[int] = []
    e_admitted: list[int] = []

    arm_b_wall: list[float] = []
    missing_sessions = 0

    print(f"\nGenerating contexts for {len(questions)} questions × 5 arms = {len(questions) * 5}")
    print(f"  Arm B requires {len(questions)} LLM summarization calls (gpt-4o-2024-08-06, T=0)")
    print()

    for i, q in enumerate(questions, start=1):
        sid = q["session_id"]
        T = q["turn_idx"]
        qid = q["question_id"]
        category = q["category"]

        if i == 1 or i % 10 == 0:
            print(f"  [{i:3d}/{len(questions)}] {qid}  T={T}", flush=True)

        turns = sessions.get(sid, [])
        if not turns:
            missing_sessions += 1
            for f in (fa, fb, fc, fd, fe):
                f.write(json.dumps({
                    "question_id": qid, "session_id": sid, "turn_idx": T,
                    "category": category, "rendered": "(session not found)",
                    "token_count": 0,
                }) + "\n")
            continue

        # ─── Arm A: raw K=20 log + strong baseline (= v0.3 Arm A) ─────
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

        # ─── Shared belief substrate (input to B/C/D/E) ────────────────
        beliefs_for_session = beliefs_by_session.get(sid, [])
        _, clusters = build_candidates_and_clusters(beliefs_for_session, T, K_V1)

        # ─── Arm C: claims only ───────────────────────────────────────
        rendered_c, meta_c = build_arm_overlay(
            "C", clusters, T, BUDGET_TOKENS, K_V1, render_arm_c_line
        )
        c_tok = meta_c["overlay_tokens"]
        rec_c = {
            "question_id": qid, "session_id": sid, "turn_idx": T,
            "category": category, "arm": "C",
            "rendering": f"claims_only_budget{BUDGET_TOKENS}",
            "rendered": rendered_c, "token_count": c_tok,
            "overlay_meta": meta_c,
        }
        fc.write(json.dumps(rec_c) + "\n")
        c_tokens.append(c_tok)
        c_admitted.append(meta_c["admitted_cluster_count"])

        # ─── Arm D: claims + warrants (no lifecycle marker) ────────────
        rendered_d, meta_d = build_arm_overlay(
            "D", clusters, T, BUDGET_TOKENS, K_V1, render_arm_d_line
        )
        d_tok = meta_d["overlay_tokens"]
        rec_d = {
            "question_id": qid, "session_id": sid, "turn_idx": T,
            "category": category, "arm": "D",
            "rendering": f"claims_plus_warrants_budget{BUDGET_TOKENS}",
            "rendered": rendered_d, "token_count": d_tok,
            "overlay_meta": meta_d,
        }
        fd.write(json.dumps(rec_d) + "\n")
        d_tokens.append(d_tok)
        d_admitted.append(meta_d["admitted_cluster_count"])

        # ─── Arm E: full discipline ────────────────────────────────────
        rendered_e, meta_e = build_arm_overlay(
            "E", clusters, T, BUDGET_TOKENS, K_V1, render_arm_e_line
        )
        e_tok = meta_e["overlay_tokens"]
        rec_e = {
            "question_id": qid, "session_id": sid, "turn_idx": T,
            "category": category, "arm": "E",
            "rendering": f"full_discipline_budget{BUDGET_TOKENS}",
            "rendered": rendered_e, "token_count": e_tok,
            "overlay_meta": meta_e,
        }
        fe.write(json.dumps(rec_e) + "\n")
        e_tokens.append(e_tok)
        e_admitted.append(meta_e["admitted_cluster_count"])

        # ─── Arm B: LLM-summarized prose ───────────────────────────────
        summary_meta = summarize_for_arm_b(client, clusters, T)
        b_full_tokens = len(enc.encode(summary_meta["summary_text"]))
        rec_b = {
            "question_id": qid, "session_id": sid, "turn_idx": T,
            "category": category, "arm": "B",
            "rendering": f"llm_summary_max{SUMMARY_MAX_OUT}_{SUMMARIZER_MODEL}_T{SUMMARIZER_TEMP}_seed{SUMMARIZER_SEED}",
            "rendered": summary_meta["summary_text"], "token_count": b_full_tokens,
            "summarizer_meta": summary_meta,
        }
        fb.write(json.dumps(rec_b) + "\n")
        b_tokens.append(b_full_tokens)
        arm_b_wall.append(summary_meta["wall_seconds"])

    fa.close(); fb.close(); fc.close(); fd.close(); fe.close()

    # ─── Report ──────────────────────────────────────────────────────────
    print()
    print(f"Wrote {OUT_A}")
    print(f"Wrote {OUT_B}")
    print(f"Wrote {OUT_C}")
    print(f"Wrote {OUT_D}")
    print(f"Wrote {OUT_E}")
    print()
    print("Token totals (input context per arm):")
    for letter, arr in [("A", a_tokens), ("B", b_tokens), ("C", c_tokens),
                         ("D", d_tokens), ("E", e_tokens)]:
        s = stats(arr)
        print(f"  Arm {letter}  mean/p50/p90/max:  {s['mean']:.0f} / {s['p50']} / {s['p90']} / {s['max']}")

    print()
    print(f"Budget-match check (target ~{BUDGET_TOKENS} ± 10% = {int(BUDGET_TOKENS*0.9)}-{int(BUDGET_TOKENS*1.1)} tokens):")
    for letter, arr in [("B", b_tokens), ("C", c_tokens), ("D", d_tokens), ("E", e_tokens)]:
        m = sum(arr) / max(1, len(arr))
        within = abs(m - BUDGET_TOKENS) / BUDGET_TOKENS <= 0.10
        print(f"  Arm {letter} mean = {m:.0f}  {'✓ within ±10%' if within else '⚠ outside ±10% — needs investigation'}")

    print()
    print("Cluster-admission (B/C/D/E):")
    for letter, arr in [("C", c_admitted), ("D", d_admitted), ("E", e_admitted)]:
        s = stats(arr)
        print(f"  Arm {letter}  median/p90/max clusters admitted: {s['p50']} / {s['p90']} / {s['max']}")

    print()
    print(f"Arm B summarizer wall-time:  total {sum(arm_b_wall):.1f}s,  per-call mean {sum(arm_b_wall)/max(1,len(arm_b_wall)):.1f}s")
    print(f"Missing sessions: {missing_sessions}")

    audit = {
        "schema_version": "v0.4a",
        "stage":          "context construction (5-arm mechanism ablation)",
        "locked_parameters": {
            "arm_a_K":                  ARM_A_K,
            "budget_tokens_b_c_d_e":    BUDGET_TOKENS,
            "summarizer_model":         SUMMARIZER_MODEL,
            "summarizer_temperature":   SUMMARIZER_TEMP,
            "summarizer_seed":          SUMMARIZER_SEED,
            "summary_max_output":       SUMMARY_MAX_OUT,
            "tool_output_cap":          TOOL_OUTPUT_CAP,
            "tokenizer":                TOKENIZER,
            "overlay_ranking":          "OB-002 §3.0 meta-rule + §3.1 tiers + §3.4 tiebreaks",
            "overlay_serialization":    "OB-002 §3.5 + §3.5a type+claim cluster dedup",
            "shared_belief_substrate":  "All arms B/C/D/E read from the same §3.5a-clustered active beliefs at T (in {active, weakened, contradicted}). Arm B summarizer receives JSON; C/D/E receive structured renderings.",
        },
        "questions_processed":  len(questions),
        "missing_sessions":     missing_sessions,
        "arm_a": {
            "input_token_stats":    stats(a_tokens),
            "rendering_note":       "Identical to v0.3 Arm A (raw K=20 log + strong baseline applied at generation time).",
        },
        "arm_b": {
            "input_token_stats":    stats(b_tokens),
            "summarizer_wall_seconds_total":  sum(arm_b_wall),
            "summarizer_wall_seconds_per_call": stats(arm_b_wall),
            "rendering_note":       "LLM-generated free-form prose; same generator as answer generation. Input = same §3.5a-clustered active beliefs as C/D/E, presented as JSON.",
        },
        "arm_c": {
            "input_token_stats":    stats(c_tokens),
            "clusters_admitted":    stats(c_admitted),
            "rendering_note":       "Claims only: `belief_type :: claim`. No warrant fields, no lifecycle marker.",
        },
        "arm_d": {
            "input_token_stats":    stats(d_tokens),
            "clusters_admitted":    stats(d_admitted),
            "rendering_note":       "Claims + warrants: `belief_type :: claim (auth=..., evidence=..., decay=..., last=...)`. No lifecycle marker.",
        },
        "arm_e": {
            "input_token_stats":    stats(e_tokens),
            "clusters_admitted":    stats(e_admitted),
            "rendering_note":       "Full discipline: `[LIFECYCLE] belief_type :: claim (auth=..., evidence=..., decay=..., last=...)`.",
        },
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"\nWrote {OUT_AUDIT}")


if __name__ == "__main__":
    main()
