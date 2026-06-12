#!/usr/bin/env python3
"""
Belief Stack v0.4a.2 — Arm A' context builder.

Builds the Arm A' contexts: LLM-generated prose summary of the
*raw K=20 log* (same source as Arm A) at a ~285 token cap (same
budget as Arm B).

PURPOSE: Holds compression constant and varies source. v0.4a.1
established that compressed maintained-state context (Arm B) beats
raw context (Arm A) by 5.3 pp. The B-A delta is confounded between
(i) compression and (ii) substrate transformation. Arm A' isolates
the contribution of compression alone by summarizing the raw log
under the same protocol that produced Arm B from the maintained
substrate.

Same generator as Arm B (gpt-4o-2024-08-06, T=0, seed 20260601).
Same output token cap (~285).
Different SOURCE: raw K=20 log instead of clustered active beliefs.

Outputs:
  belief_stack_v0_4a/data/contexts_arm_a_prime.jsonl
  belief_stack_v0_4a/data/context_construction_audit_a_prime.json
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from collections import defaultdict

import tiktoken

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent
V1_ROOT = STORM_ROOT / "operational_belief_v1"

sys.path.insert(0, str(V1_ROOT))
from build_log_context_a import (  # noqa: E402
    K as K_V1,
    TOKENIZER,
    TOOL_OUTPUT_CAP,
    load_jsonl,
    load_sessions,
    render_raw_log_payload,
)

from openai import OpenAI, RateLimitError, APITimeoutError, APIStatusError
from dotenv import load_dotenv

load_dotenv(STORM_ROOT / ".env")

QUESTIONS_PATH = V1_ROOT / "questions.jsonl"
OUT_DIR = ROOT / "data"
OUT_A_PRIME = OUT_DIR / "contexts_arm_a_prime.jsonl"
OUT_AUDIT   = OUT_DIR / "context_construction_audit_a_prime.json"

# LOCKED v0.4a.2 parameters — matched to Arm B's protocol
ARM_A_K          = 20          # Same as v0.3 Arm A and v0.4a.1 Arm A
SUMMARY_MAX_OUT  = 285         # Matched to Arm B's cap
SUMMARIZER_MODEL = "gpt-4o-2024-08-06"
SUMMARIZER_TEMP  = 0
SUMMARIZER_SEED  = 20260601

RETRY_MAX        = 5
RETRY_INITIAL    = 4.0

enc = tiktoken.get_encoding(TOKENIZER)


# ─── Arm A' summarizer system prompt ───────────────────────────────────
# Matches the spirit and length of Arm B's prompt, but instructs
# summarization of raw session history rather than a structured belief list.

ARM_A_PRIME_SYSTEM_PROMPT = """You receive the last 20 turns of a coding-assistant session transcript at a specific turn T. The transcript shows user messages, assistant messages, and tool outputs in chronological order.

Your task: write a concise prose summary of what is currently true at this point in the session.

Constraints:
- Output in free-form prose. Do NOT use a structured format (no bullets, no headers, no lists).
- Aim for approximately 200-260 tokens.
- Do not invent facts not present in the transcript.
- Focus on what is currently active, pending, weakened, or contradicted — not on history.
- Write in present tense.
- Cover the situation comprehensively in whatever order best serves a reader trying to understand current session state."""


def make_arm_a_prime_user_prompt(raw_log: str, T: int) -> str:
    return (
        f"Turn T = {T}.\n\n"
        f"Recent session transcript (last {ARM_A_K} turns):\n\n"
        f"{raw_log}\n\n"
        f"Write the prose summary now."
    )


def summarize_for_arm_a_prime(client: OpenAI, raw_log: str, T: int) -> dict:
    user_prompt = make_arm_a_prime_user_prompt(raw_log, T)
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
                    {"role": "system", "content": ARM_A_PRIME_SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
            )
            wall = time.time() - t0
            choice = resp.choices[0]
            return {
                "summary_text":            choice.message.content or "",
                "summary_tokens":          resp.usage.completion_tokens,
                "summarizer_input_tokens": resp.usage.prompt_tokens,
                "model_resolved":          resp.model,
                "system_fingerprint":      getattr(resp, "system_fingerprint", None),
                "finish_reason":           choice.finish_reason,
                "wall_seconds":            wall,
                "retry_attempts":          attempt - 1,
            }
        except (RateLimitError, APITimeoutError) as e:
            last_err = e
            print(f"    A' retry {attempt}/{RETRY_MAX} after {type(e).__name__}; sleeping {delay:.1f}s", flush=True)
            time.sleep(delay); delay *= 2
        except APIStatusError as e:
            if 500 <= getattr(e, "status_code", 0) < 600:
                last_err = e
                print(f"    A' retry {attempt}/{RETRY_MAX} after {e.status_code}; sleeping {delay:.1f}s", flush=True)
                time.sleep(delay); delay *= 2
            else:
                raise
    raise last_err if last_err else RuntimeError("A' retries exhausted")


def stats(arr):
    if not arr:
        return {"min": None, "p50": None, "p90": None, "max": None, "mean": None}
    s = sorted(arr); n = len(s)
    return {"min": s[0], "p10": s[max(0, n // 10 - 1)], "p50": s[n // 2],
            "p90": s[min(n - 1, int(n * 0.9))], "max": s[-1], "mean": sum(arr) / n}


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    print("Loading inputs...")
    questions = load_jsonl(QUESTIONS_PATH)
    sessions = load_sessions()
    print(f"  {len(questions)} questions, {len(sessions):,} sessions")

    OUT_DIR.mkdir(exist_ok=True)
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    fout = OUT_A_PRIME.open("w")
    ap_tokens: list[int] = []
    ap_wall:   list[float] = []
    missing_sessions = 0

    print(f"\nGenerating {len(questions)} Arm A' contexts (LLM summarization of raw K={ARM_A_K} log)")
    print(f"  Same generator as Arm B: {SUMMARIZER_MODEL}, T={SUMMARIZER_TEMP}, seed={SUMMARIZER_SEED}")
    print(f"  Output cap: {SUMMARY_MAX_OUT} tokens (matched to Arm B)")
    print()

    for i, q in enumerate(questions, start=1):
        sid = q["session_id"]; T = q["turn_idx"]; qid = q["question_id"]
        category = q["category"]

        if i == 1 or i % 10 == 0:
            print(f"  [{i:3d}/{len(questions)}] {qid}  T={T}", flush=True)

        turns = sessions.get(sid, [])
        if not turns:
            missing_sessions += 1
            fout.write(json.dumps({
                "question_id": qid, "session_id": sid, "turn_idx": T,
                "category": category, "rendered": "(session not found)",
                "token_count": 0,
            }) + "\n")
            continue

        # Render the raw K=20 log (same as Arm A's input)
        log, log_meta = render_raw_log_payload(turns, T, ARM_A_K)
        raw_log_tokens = log_meta["tokens"]

        # LLM-summarize it
        summary_meta = summarize_for_arm_a_prime(client, log, T)
        ctx_tokens = len(enc.encode(summary_meta["summary_text"]))

        rec = {
            "question_id":   qid,
            "session_id":    sid,
            "turn_idx":      T,
            "category":      category,
            "arm":           "A_prime",
            "rendering":     f"llm_summary_of_raw_log_K{ARM_A_K}_max{SUMMARY_MAX_OUT}_{SUMMARIZER_MODEL}_T{SUMMARIZER_TEMP}_seed{SUMMARIZER_SEED}",
            "rendered":      summary_meta["summary_text"],
            "token_count":   ctx_tokens,
            "raw_log_input_tokens": raw_log_tokens,
            "summarizer_meta": summary_meta,
        }
        fout.write(json.dumps(rec) + "\n")
        ap_tokens.append(ctx_tokens)
        ap_wall.append(summary_meta["wall_seconds"])

    fout.close()

    print()
    print(f"Wrote {OUT_A_PRIME}")
    print()
    s_tok = stats(ap_tokens)
    print(f"Arm A' input-context tokens — mean/p50/p90/max: "
          f"{s_tok['mean']:.0f} / {s_tok['p50']} / {s_tok['p90']} / {s_tok['max']}")
    print(f"Arm A' summarizer wall — total {sum(ap_wall):.1f}s, per-call mean {sum(ap_wall)/max(1,len(ap_wall)):.2f}s")
    print(f"Missing sessions: {missing_sessions}")

    audit = {
        "schema_version": "v0.4a.2",
        "stage":          "Arm A' context construction (compression-vs-substrate isolation)",
        "locked_parameters": {
            "arm_a_K":                  ARM_A_K,
            "summarizer_model":         SUMMARIZER_MODEL,
            "summarizer_temperature":   SUMMARIZER_TEMP,
            "summarizer_seed":          SUMMARIZER_SEED,
            "summary_max_output":       SUMMARY_MAX_OUT,
            "tool_output_cap":          TOOL_OUTPUT_CAP,
            "tokenizer":                TOKENIZER,
            "matched_protocol_to":      "Arm B (LLM prose summary at ~285 tokens; same generator/T/seed/max)",
            "source_difference_from_B": "Arm A' summarizes the raw K=20 log; Arm B summarizes the §3.5a-clustered active belief substrate.",
        },
        "questions_processed":      len(questions),
        "missing_sessions":         missing_sessions,
        "arm_a_prime": {
            "input_token_stats":            stats(ap_tokens),
            "summarizer_wall_seconds_total": sum(ap_wall),
            "summarizer_wall_seconds_per_call": stats(ap_wall),
            "rendering_note":   "LLM-generated free-form prose from raw K=20 log input.",
        },
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"\nWrote {OUT_AUDIT}")


if __name__ == "__main__":
    main()
