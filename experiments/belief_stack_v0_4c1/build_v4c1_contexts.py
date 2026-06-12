#!/usr/bin/env python3
"""
Belief Stack v0.4c1.1 — Multi-model context builder.

LOCKED v0.4c1.1 setup (per pre-registration §1, §2, §3 + §11 amendment):

  Arm A:  Raw K=20 log + strong baseline. Deterministic — same across
          models. Generated once, copied per-model for audit symmetry.

  Arm A': LLM prose summary of raw K=20 log at ~285-token cap.
          Per-model summarizer (each model summarizes its own raw log).

  Arm B:  LLM prose summary of §3.5a-clustered active substrate at
          ~285-token cap. Per-model summarizer.

  Arm C:  Bare `belief_type :: claim` per cluster, dedup-ranked,
          ~285-token budget. Substrate-side deterministic rendering —
          same across models. Generated once, copied per-model.

Per-provider configurations (v0.4c1.1 §3):

  gpt-4o-2024-08-06   (OpenAI):    T=0, seed=20260601, full v0.4a parity
  claude-opus-4-7     (Anthropic): NO temperature param; default sampling
  gemini-2.5-pro      (Gemini):    T=0, seed=20260601, thinking_budget=2048
  claude-haiku-4-5-20251001 (Anthropic): T=0, no seed support

ANTI-CURATION DISCIPLINE: this script generates ALL 1,200 contexts
(75 questions × 4 arms × 4 models, with A and C shared across models)
BEFORE any answer generation. No iterative tuning. No retry-with-
different-prompts. Failures recorded honestly.

Outputs:
  belief_stack_v0_4c1/data/contexts_<model_id>_arm_a.jsonl
  belief_stack_v0_4c1/data/contexts_<model_id>_arm_a_prime.jsonl
  belief_stack_v0_4c1/data/contexts_<model_id>_arm_b.jsonl
  belief_stack_v0_4c1/data/contexts_<model_id>_arm_c.jsonl
  belief_stack_v0_4c1/data/context_construction_audit.json

CLI:
  python build_v4c1_contexts.py            # full 75 questions
  python build_v4c1_contexts.py --limit 3  # smoke test on first 3
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from collections import defaultdict
from typing import Any

import tiktoken
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent
V1_ROOT = STORM_ROOT / "operational_belief_v1"
V2_ROOT = STORM_ROOT / "operational_belief_v2"
V4A_ROOT = STORM_ROOT / "belief_stack_v0_4a"

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

# Reuse v0.2.2 §3.5a clustering / lifecycle machinery
sys.path.insert(0, str(V2_ROOT))
from build_overlay_context_b_v2 import (  # noqa: E402
    AUTH_ABBR,
    INCLUDED_LIFECYCLE_STATES,
    at_T_lifecycle,
    cluster_candidates,
    cluster_sort_key,
    is_out_of_window,
)

# Reuse v0.4a Arm C renderer + summarizer prompts
sys.path.insert(0, str(V4A_ROOT))
from build_v4a_contexts import (  # noqa: E402
    BUDGET_TOKENS,
    SUMMARY_MAX_OUT,
    render_arm_c_line,
    build_arm_overlay,
    build_candidates_and_clusters,
    ARM_B_SYSTEM_PROMPT,
    make_arm_b_user_prompt,
)
from build_arm_a_prime_contexts import (  # noqa: E402
    ARM_A_PRIME_SYSTEM_PROMPT,
    make_arm_a_prime_user_prompt,
)

# Provider SDKs
from openai import OpenAI, RateLimitError as OAIRateLimit, APITimeoutError as OAITimeout, APIStatusError as OAIStatus
from anthropic import Anthropic
from anthropic import RateLimitError as AnthRateLimit, APIStatusError as AnthStatus
from google import genai
from google.genai import types as gen_types
from google.genai import errors as gen_errors

load_dotenv(STORM_ROOT / ".env")
enc = tiktoken.get_encoding(TOKENIZER)

QUESTIONS_PATH = V1_ROOT / "questions.jsonl"
BELIEFS_PATH = V1_ROOT / "data" / "operational_beliefs.jsonl"

OUT_DIR = ROOT / "data"
OUT_AUDIT = OUT_DIR / "context_construction_audit.json"

# ─── LOCKED v0.4c1.1 model configurations ──────────────────────────────

ARM_A_K          = 20      # Same as v0.3 / v0.4a Arm A
SUMMARIZER_SEED  = 20260601

# Per-pre-reg §3, locked at v0.4c1.1 amendment
MODELS = [
    {
        "id":              "gpt-4o-2024-08-06",
        "provider":        "openai",
        "temperature":     0,
        "seed":            SUMMARIZER_SEED,
        "thinking_budget": None,
        "supports_temperature": True,
        "supports_seed":   True,
    },
    {
        "id":              "claude-opus-4-7",
        "provider":        "anthropic",
        "temperature":     None,    # NOT SUPPORTED by this model
        "seed":            None,    # NOT SUPPORTED by Anthropic API
        "thinking_budget": None,
        "supports_temperature": False,
        "supports_seed":   False,
    },
    {
        "id":              "gemini-2.5-pro",
        "provider":        "gemini",
        "temperature":     0,
        "seed":            SUMMARIZER_SEED,
        "thinking_budget": 2048,    # REQUIRED — model rejects budget=0
        "supports_temperature": True,
        "supports_seed":   True,
    },
    {
        "id":              "claude-haiku-4-5-20251001",
        "provider":        "anthropic",
        "temperature":     0,
        "seed":            None,    # NOT SUPPORTED by Anthropic API
        "thinking_budget": None,
        "supports_temperature": True,
        "supports_seed":   False,
    },
]

RETRY_MAX     = 5
RETRY_INITIAL = 4.0


# ─── Provider-specific summarizer dispatchers ──────────────────────────

def _retry_call(fn, *args, label="call", **kwargs):
    """Generic retry wrapper for transient API failures."""
    delay = RETRY_INITIAL
    last_err: Exception | None = None
    for attempt in range(1, RETRY_MAX + 1):
        try:
            return fn(*args, **kwargs)
        except (OAIRateLimit, OAITimeout, AnthRateLimit) as e:
            last_err = e
            print(f"    {label} retry {attempt}/{RETRY_MAX} after {type(e).__name__}; sleeping {delay:.1f}s", flush=True)
            time.sleep(delay); delay *= 2
        except OAIStatus as e:
            if 500 <= getattr(e, "status_code", 0) < 600:
                last_err = e
                print(f"    {label} retry {attempt}/{RETRY_MAX} after {e.status_code}; sleeping {delay:.1f}s", flush=True)
                time.sleep(delay); delay *= 2
            else:
                raise
        except AnthStatus as e:
            if 500 <= getattr(e, "status_code", 0) < 600:
                last_err = e
                print(f"    {label} retry {attempt}/{RETRY_MAX} after {e.status_code}; sleeping {delay:.1f}s", flush=True)
                time.sleep(delay); delay *= 2
            else:
                raise
        except gen_errors.APIError as e:
            code = getattr(e, "code", 0) or 0
            if 500 <= code < 600 or 429 == code:
                last_err = e
                print(f"    {label} retry {attempt}/{RETRY_MAX} after Gemini {code}; sleeping {delay:.1f}s", flush=True)
                time.sleep(delay); delay *= 2
            else:
                raise
    raise last_err if last_err else RuntimeError(f"{label} retries exhausted")


def summarize_openai(client: OpenAI, model_cfg: dict, system_prompt: str, user_prompt: str) -> dict:
    def _do():
        return client.chat.completions.create(
            model=model_cfg["id"],
            temperature=model_cfg["temperature"],
            seed=model_cfg["seed"],
            max_tokens=SUMMARY_MAX_OUT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
        )
    t0 = time.time()
    resp = _retry_call(_do, label=f"openai/{model_cfg['id']}")
    wall = time.time() - t0
    choice = resp.choices[0]
    return {
        "summary_text":            choice.message.content or "",
        "summary_tokens":          resp.usage.completion_tokens,
        "summarizer_input_tokens": resp.usage.prompt_tokens,
        "model_resolved":          resp.model,
        "finish_reason":           choice.finish_reason,
        "wall_seconds":            wall,
    }


def summarize_anthropic(client: Anthropic, model_cfg: dict, system_prompt: str, user_prompt: str) -> dict:
    kwargs = {
        "model":      model_cfg["id"],
        "max_tokens": SUMMARY_MAX_OUT,
        "system":     system_prompt,
        "messages":   [{"role": "user", "content": user_prompt}],
    }
    if model_cfg["supports_temperature"]:
        kwargs["temperature"] = model_cfg["temperature"]
    # No seed param on Anthropic API.

    def _do():
        return client.messages.create(**kwargs)
    t0 = time.time()
    resp = _retry_call(_do, label=f"anthropic/{model_cfg['id']}")
    wall = time.time() - t0
    text = ""
    for block in resp.content:
        if hasattr(block, "text"):
            text += block.text
    return {
        "summary_text":            text,
        "summary_tokens":          resp.usage.output_tokens,
        "summarizer_input_tokens": resp.usage.input_tokens,
        "model_resolved":          resp.model,
        "finish_reason":           resp.stop_reason,
        "wall_seconds":            wall,
    }


def summarize_gemini(client, model_cfg: dict, system_prompt: str, user_prompt: str) -> dict:
    # Gemini's max_output_tokens is a TOTAL cap including thinking tokens.
    # When thinking is enabled, raise the cap to thinking_budget + SUMMARY_MAX_OUT
    # so the model has headroom to produce the actual summary after thinking.
    # The summary itself is still constrained by the prompt's target length.
    if model_cfg["thinking_budget"] is not None:
        effective_max_output = model_cfg["thinking_budget"] + SUMMARY_MAX_OUT
    else:
        effective_max_output = SUMMARY_MAX_OUT

    cfg_kwargs: dict[str, Any] = {
        "temperature":       model_cfg["temperature"],
        "max_output_tokens": effective_max_output,
        "system_instruction": system_prompt,
    }
    if model_cfg["seed"] is not None and model_cfg["supports_seed"]:
        cfg_kwargs["seed"] = model_cfg["seed"]
    if model_cfg["thinking_budget"] is not None:
        cfg_kwargs["thinking_config"] = gen_types.ThinkingConfig(
            thinking_budget=model_cfg["thinking_budget"]
        )
    config = gen_types.GenerateContentConfig(**cfg_kwargs)

    def _do():
        return client.models.generate_content(
            model=model_cfg["id"],
            contents=user_prompt,
            config=config,
        )
    t0 = time.time()
    resp = _retry_call(_do, label=f"gemini/{model_cfg['id']}")
    wall = time.time() - t0
    text = resp.text or ""
    usage = resp.usage_metadata
    finish = resp.candidates[0].finish_reason if resp.candidates else None
    return {
        "summary_text":            text,
        "summary_tokens":          (usage.candidates_token_count or 0) if usage else 0,
        "summarizer_input_tokens": (usage.prompt_token_count or 0) if usage else 0,
        "thoughts_token_count":    (usage.thoughts_token_count or 0) if usage else 0,
        "model_resolved":          model_cfg["id"],
        "finish_reason":           str(finish) if finish else None,
        "wall_seconds":            wall,
    }


def summarize(clients: dict, model_cfg: dict, system_prompt: str, user_prompt: str) -> dict:
    provider = model_cfg["provider"]
    if provider == "openai":
        return summarize_openai(clients["openai"], model_cfg, system_prompt, user_prompt)
    if provider == "anthropic":
        return summarize_anthropic(clients["anthropic"], model_cfg, system_prompt, user_prompt)
    if provider == "gemini":
        return summarize_gemini(clients["gemini"], model_cfg, system_prompt, user_prompt)
    raise ValueError(f"unknown provider: {provider}")


# ─── Stats helper ──────────────────────────────────────────────────────

def stats(arr):
    if not arr:
        return {"min": None, "p50": None, "p90": None, "max": None, "mean": None}
    s = sorted(arr); n = len(s)
    return {"min": s[0], "p50": s[n // 2],
            "p90": s[min(n - 1, int(n * 0.9))], "max": s[-1],
            "mean": sum(arr) / n}


# ─── Main ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only the first N questions (for smoke test). "
                             "Omit for full 75.")
    args = parser.parse_args()

    # Verify all three provider keys present
    missing = [k for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")
               if not os.environ.get(k)]
    if missing:
        print(f"ERROR: missing env vars: {missing}", file=sys.stderr)
        sys.exit(1)

    clients = {
        "openai":    OpenAI(api_key=os.environ["OPENAI_API_KEY"]),
        "anthropic": Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"]),
        "gemini":    genai.Client(api_key=os.environ["GEMINI_API_KEY"]),
    }

    print("Loading inputs...")
    questions = load_jsonl(QUESTIONS_PATH)
    if args.limit:
        questions = questions[: args.limit]
        print(f"  --limit {args.limit}: processing first {len(questions)} questions only")
    sessions = load_sessions()
    beliefs_by_session: dict[str, list[dict]] = defaultdict(list)
    with BELIEFS_PATH.open() as f:
        for line in f:
            b = json.loads(line)
            beliefs_by_session[b["session_id"]].append(b)
    beliefs_by_session = dict(beliefs_by_session)
    print(f"  {len(questions)} questions × 4 arms × 4 models")
    print(f"  Per-model summarization calls: {len(questions)} × 2 arms × 4 models = {len(questions) * 2 * 4}")

    OUT_DIR.mkdir(exist_ok=True)

    # ─── Phase 1: Arm A and Arm C (deterministic, same across models) ──
    print("\nPhase 1: building deterministic arms (A, C) shared across models...")
    arm_a_records: list[dict] = []
    arm_c_records: list[dict] = []
    arm_a_tokens: list[int] = []
    arm_c_tokens: list[int] = []
    arm_c_admitted: list[int] = []
    missing_sessions = 0

    for q in questions:
        sid = q["session_id"]; T = q["turn_idx"]; qid = q["question_id"]
        category = q["category"]
        turns = sessions.get(sid, [])
        if not turns:
            missing_sessions += 1
            for arr in (arm_a_records, arm_c_records):
                arr.append({"question_id": qid, "session_id": sid, "turn_idx": T,
                            "category": category, "rendered": "(session not found)",
                            "token_count": 0})
            continue

        # Arm A: raw K=20 log
        log_a, log_a_meta = render_raw_log_payload(turns, T, ARM_A_K)
        a_tok = len(enc.encode(log_a))
        arm_a_records.append({
            "question_id": qid, "session_id": sid, "turn_idx": T, "category": category,
            "arm": "A", "rendering": f"raw_log_K{ARM_A_K}_cap{TOOL_OUTPUT_CAP}_strong_baseline",
            "rendered": log_a, "token_count": a_tok,
            "log_tokens": log_a_meta["tokens"],
            "turns_in_window": log_a_meta["turns_in_window"],
            "tool_outputs_truncated": log_a_meta["tool_outputs_truncated"],
        })
        arm_a_tokens.append(a_tok)

        # Arm C: structured claims only, dedup-ranked, budget-bounded
        beliefs_for_session = beliefs_by_session.get(sid, [])
        _, clusters = build_candidates_and_clusters(beliefs_for_session, T, K_V1)
        rendered_c, meta_c = build_arm_overlay(
            "C", clusters, T, BUDGET_TOKENS, K_V1, render_arm_c_line
        )
        c_tok = meta_c["overlay_tokens"]
        arm_c_records.append({
            "question_id": qid, "session_id": sid, "turn_idx": T, "category": category,
            "arm": "C", "rendering": f"claims_only_budget{BUDGET_TOKENS}",
            "rendered": rendered_c, "token_count": c_tok,
            "overlay_meta": meta_c,
        })
        arm_c_tokens.append(c_tok)
        arm_c_admitted.append(meta_c["admitted_cluster_count"])

    print(f"  Arm A: {len(arm_a_records)} contexts, mean {stats(arm_a_tokens)['mean']:.0f} tokens")
    print(f"  Arm C: {len(arm_c_records)} contexts, mean {stats(arm_c_tokens)['mean']:.0f} tokens, "
          f"median {stats(arm_c_admitted)['p50']} clusters admitted")

    # Write Arm A and Arm C files per model (same content, per-model filename for audit symmetry)
    for model_cfg in MODELS:
        mid = model_cfg["id"]
        with (OUT_DIR / f"contexts_{mid}_arm_a.jsonl").open("w") as f:
            for rec in arm_a_records:
                f.write(json.dumps({**rec, "model": mid}) + "\n")
        with (OUT_DIR / f"contexts_{mid}_arm_c.jsonl").open("w") as f:
            for rec in arm_c_records:
                f.write(json.dumps({**rec, "model": mid}) + "\n")

    # ─── Phase 2: Arm A' and Arm B (per-model summarization) ───────────
    print("\nPhase 2: building per-model summarized arms (A', B)...")
    per_model_telemetry: dict[str, dict] = {}

    for model_cfg in MODELS:
        mid = model_cfg["id"]
        print(f"\n  Model: {mid} (provider={model_cfg['provider']})")

        ap_tokens: list[int] = []
        ap_wall:   list[float] = []
        ap_finish: list[str] = []
        b_tokens:  list[int] = []
        b_wall:    list[float] = []
        b_finish:  list[str] = []
        gemini_thoughts_a_prime: list[int] = []
        gemini_thoughts_b:       list[int] = []

        # First pass: collect clusters per question (deterministic)
        clusters_by_qid: dict[str, list[dict]] = {}
        for q in questions:
            sid = q["session_id"]; T = q["turn_idx"]; qid = q["question_id"]
            beliefs_for_session = beliefs_by_session.get(sid, [])
            _, clusters = build_candidates_and_clusters(beliefs_for_session, T, K_V1)
            clusters_by_qid[qid] = clusters

        # Arm A': summarize raw log per-model
        ap_records: list[dict] = []
        b_records:  list[dict] = []

        for i, q in enumerate(questions, start=1):
            sid = q["session_id"]; T = q["turn_idx"]; qid = q["question_id"]
            category = q["category"]
            turns = sessions.get(sid, [])
            if not turns:
                ap_records.append({"question_id": qid, "session_id": sid, "turn_idx": T,
                                   "category": category, "rendered": "(session not found)",
                                   "token_count": 0})
                b_records.append({"question_id": qid, "session_id": sid, "turn_idx": T,
                                  "category": category, "rendered": "(session not found)",
                                  "token_count": 0})
                continue

            if i == 1 or i % 10 == 0 or i == len(questions):
                print(f"    [{i:3d}/{len(questions)}] {qid}  T={T}", flush=True)

            # Arm A' (LLM summary of raw K=20 log)
            log_a, _ = render_raw_log_payload(turns, T, ARM_A_K)
            ap_meta = summarize(
                clients, model_cfg,
                ARM_A_PRIME_SYSTEM_PROMPT,
                make_arm_a_prime_user_prompt(log_a, T),
            )
            ap_text = ap_meta["summary_text"]
            ap_tok = len(enc.encode(ap_text))
            ap_records.append({
                "question_id": qid, "session_id": sid, "turn_idx": T,
                "category": category, "arm": "A_prime", "model": mid,
                "rendering": f"llm_summary_of_raw_log_K{ARM_A_K}_max{SUMMARY_MAX_OUT}_{mid}",
                "rendered": ap_text, "token_count": ap_tok,
                "summarizer_meta": ap_meta,
            })
            ap_tokens.append(ap_tok)
            ap_wall.append(ap_meta["wall_seconds"])
            ap_finish.append(str(ap_meta.get("finish_reason")))
            if model_cfg["provider"] == "gemini":
                gemini_thoughts_a_prime.append(ap_meta.get("thoughts_token_count", 0))

            # Arm B (LLM summary of substrate-clustered active beliefs)
            clusters = clusters_by_qid[qid]
            b_meta = summarize(
                clients, model_cfg,
                ARM_B_SYSTEM_PROMPT,
                make_arm_b_user_prompt(clusters, T),
            )
            b_text = b_meta["summary_text"]
            b_tok = len(enc.encode(b_text))
            b_records.append({
                "question_id": qid, "session_id": sid, "turn_idx": T,
                "category": category, "arm": "B", "model": mid,
                "rendering": f"llm_summary_of_substrate_max{SUMMARY_MAX_OUT}_{mid}",
                "rendered": b_text, "token_count": b_tok,
                "summarizer_meta": b_meta,
            })
            b_tokens.append(b_tok)
            b_wall.append(b_meta["wall_seconds"])
            b_finish.append(str(b_meta.get("finish_reason")))
            if model_cfg["provider"] == "gemini":
                gemini_thoughts_b.append(b_meta.get("thoughts_token_count", 0))

        # Write per-model A' and B files
        with (OUT_DIR / f"contexts_{mid}_arm_a_prime.jsonl").open("w") as f:
            for rec in ap_records:
                f.write(json.dumps(rec) + "\n")
        with (OUT_DIR / f"contexts_{mid}_arm_b.jsonl").open("w") as f:
            for rec in b_records:
                f.write(json.dumps(rec) + "\n")

        print(f"    Arm A' mean tokens: {stats(ap_tokens)['mean']:.0f}; wall total {sum(ap_wall):.1f}s")
        print(f"    Arm B  mean tokens: {stats(b_tokens)['mean']:.0f}; wall total {sum(b_wall):.1f}s")

        from collections import Counter
        per_model_telemetry[mid] = {
            "provider":          model_cfg["provider"],
            "config":            {k: model_cfg[k] for k in
                                  ("temperature", "seed", "thinking_budget",
                                   "supports_temperature", "supports_seed")},
            "arm_a_prime": {
                "n":               len(ap_records),
                "input_token_stats": stats(ap_tokens),
                "wall_seconds_stats": stats(ap_wall),
                "wall_seconds_total": sum(ap_wall),
                "finish_reasons":  dict(Counter(ap_finish)),
                "gemini_thoughts_token_stats":
                    stats(gemini_thoughts_a_prime) if gemini_thoughts_a_prime else None,
            },
            "arm_b": {
                "n":               len(b_records),
                "input_token_stats": stats(b_tokens),
                "wall_seconds_stats": stats(b_wall),
                "wall_seconds_total": sum(b_wall),
                "finish_reasons":  dict(Counter(b_finish)),
                "gemini_thoughts_token_stats":
                    stats(gemini_thoughts_b) if gemini_thoughts_b else None,
            },
        }

    # ─── Audit ──────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("v0.4c1.1 CONTEXT CONSTRUCTION SUMMARY")
    print("=" * 80)
    print(f"\nQuestions processed:   {len(questions)}")
    print(f"Missing sessions:      {missing_sessions}")
    print(f"\nPer-arm shared across models (Arm A, Arm C):")
    print(f"  Arm A: mean {stats(arm_a_tokens)['mean']:.0f} tokens (p50={stats(arm_a_tokens)['p50']}, p90={stats(arm_a_tokens)['p90']})")
    print(f"  Arm C: mean {stats(arm_c_tokens)['mean']:.0f} tokens (p50={stats(arm_c_tokens)['p50']}, p90={stats(arm_c_tokens)['p90']})")
    print(f"         median clusters admitted: {stats(arm_c_admitted)['p50']}")

    print(f"\nPer-model summarized arms (Arm A', Arm B):")
    print(f"{'Model':<35} {'A_prime mean':>12} {'B mean':>10} {'A_prime wall':>13} {'B wall':>9}")
    for mid, tel in per_model_telemetry.items():
        apm = tel["arm_a_prime"]["input_token_stats"]["mean"]
        bm  = tel["arm_b"]["input_token_stats"]["mean"]
        aw  = tel["arm_a_prime"]["wall_seconds_total"]
        bw  = tel["arm_b"]["wall_seconds_total"]
        print(f"{mid:<35} {apm:>12.0f} {bm:>10.0f} {aw:>12.1f}s {bw:>8.1f}s")

    audit = {
        "schema_version":   "v0.4c1.1",
        "stage":            "multi-model context construction",
        "pre_reg":          "BELIEF_STACK_PRE_REGISTRATION_v0.4c1.md (locked v0.4c1.1)",
        "locked_parameters": {
            "arm_a_K":              ARM_A_K,
            "budget_tokens_b_c":    BUDGET_TOKENS,
            "summary_max_output":   SUMMARY_MAX_OUT,
            "tokenizer":            TOKENIZER,
            "summarizer_seed":      SUMMARIZER_SEED,
            "tool_output_cap":      TOOL_OUTPUT_CAP,
        },
        "models":           MODELS,
        "questions_processed":  len(questions),
        "missing_sessions":     missing_sessions,
        "shared_arms": {
            "arm_a": {
                "input_token_stats": stats(arm_a_tokens),
                "rendering":         f"raw_log_K{ARM_A_K}_cap{TOOL_OUTPUT_CAP}",
                "note":              "deterministic; same content across all models",
            },
            "arm_c": {
                "input_token_stats":  stats(arm_c_tokens),
                "clusters_admitted":  stats(arm_c_admitted),
                "rendering":          f"claims_only_budget{BUDGET_TOKENS}",
                "note":               "deterministic; same content across all models",
            },
        },
        "per_model": per_model_telemetry,
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"\nWrote {OUT_AUDIT}")
    print("\nNo answer generation has flowed. Per pre-reg, that is gated separately.")


if __name__ == "__main__":
    main()
