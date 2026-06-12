#!/usr/bin/env python3
"""
Belief Stack v0.4c1.1 — Multi-model answer generator.

LOCKED v0.4c1.1 generation parameters (per pre-reg §3 + §4 + §11):

  Models (4):     gpt-4o-2024-08-06, claude-opus-4-7,
                  gemini-2.5-pro, claude-haiku-4-5-20251001
  Arms (4):       A / A' / B / C
  Cells:          75 questions × 4 arms × 4 models = 1,200 cells
  Generation order: SHUFFLED across (qid, arm, model) tuples with fixed
                    seed 20260601 — anti-curation per §8
  Resume:         per (qid, arm, model) idempotent
  Context-too-long: pre-declared skip with finish_reason="context_too_long"

Per-provider answer-generation configurations:

  gpt-4o-2024-08-06   (OpenAI):    T=0, seed=20260601, max_tokens=1500
  claude-opus-4-7     (Anthropic): NO temperature param, max_tokens=1500,
                                   NO seed
  gemini-2.5-pro      (Gemini):    T=0, seed=20260601, thinking_budget=2048,
                                   max_output_tokens=2048+1500=3548
  claude-haiku-4-5-20251001 (Anthropic): T=0, max_tokens=1500, NO seed

System prompts per arm (locked from v0.4a; SAME across all four models):
  A:       raw-log reconstruction strong-baseline
  A_prime: prose summary of session state ("what's currently true")
  B:       prose summary of belief state ("currently held beliefs")
  C:       structured claims list ("belief_type :: claim")

These prompts are arm-specific; they describe the format of context the
arm received, not how to plan. Cross-model comparison varies the
generator only.

NO context modification. NO prompt tuning. NO scoring.

CLI:
  python generate_v4c1_answers.py            # full 1,200 cells
  python generate_v4c1_answers.py --limit 1  # smoke test on first
                                             # 1 question (16 cells)
  python generate_v4c1_answers.py --clear-first  # delete existing
                                                  # answer files first
                                                  # (use before full
                                                  # run after smoke)
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import random
import sys
import time
from collections import Counter, defaultdict
from typing import Any

import tiktoken
from dotenv import load_dotenv

from openai import OpenAI, RateLimitError as OAIRateLimit
from openai import APITimeoutError as OAITimeout, APIStatusError as OAIStatus
from openai import APIError as OAIError
from anthropic import Anthropic, RateLimitError as AnthRateLimit
from anthropic import APIStatusError as AnthStatus, APIError as AnthError
from google import genai
from google.genai import types as gen_types
from google.genai import errors as gen_errors

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent
V1_ROOT = STORM_ROOT / "operational_belief_v1"

load_dotenv(STORM_ROOT / ".env")
enc = tiktoken.get_encoding("cl100k_base")

QUESTIONS_PATH = V1_ROOT / "questions.jsonl"
DATA_DIR = ROOT / "data"
AUDIT_PATH = DATA_DIR / "answer_generation_audit.json"

# ─── LOCKED v0.4c1.1 generation parameters ─────────────────────────────

MAX_OUTPUT_TOKENS_ANSWER = 1500
SEED                     = 20260601
SHUFFLE_SEED             = 20260601

# Estimated upper bound on combined system + user prompt token count for
# each model's input context window. Used only for pre-flight
# context_too_long detection; not a hard cap enforced at the API level.
CONTEXT_LIMIT = 125_000
CONTEXT_INPUT_CAP = CONTEXT_LIMIT - MAX_OUTPUT_TOKENS_ANSWER - 200

# Per pre-reg §3 v0.4c1.1
MODELS = [
    {
        "id":              "gpt-4o-2024-08-06",
        "provider":        "openai",
        "temperature":     0,
        "seed":            SEED,
        "thinking_budget": None,
        "supports_temperature": True,
        "supports_seed":   True,
    },
    {
        "id":              "claude-opus-4-7",
        "provider":        "anthropic",
        "temperature":     None,    # NOT SUPPORTED
        "seed":            None,    # NOT SUPPORTED
        "thinking_budget": None,
        "supports_temperature": False,
        "supports_seed":   False,
    },
    {
        "id":              "gemini-2.5-pro",
        "provider":        "gemini",
        "temperature":     0,
        "seed":            SEED,
        "thinking_budget": 2048,
        "supports_temperature": True,
        "supports_seed":   True,
    },
    {
        "id":              "claude-haiku-4-5-20251001",
        "provider":        "anthropic",
        "temperature":     0,
        "seed":            None,    # NOT SUPPORTED
        "thinking_budget": None,
        "supports_temperature": True,
        "supports_seed":   False,
    },
]

ARMS = ["A", "B", "C", "A_prime"]

# Locked arm-specific system prompts (FROM v0.4a; SAME across all models)
SYSTEM_PROMPTS = {
    "A": (
        "You answer the user's question using only the information in the "
        "provided context. The context is a coding-assistant session "
        "transcript. Before answering, carefully reconstruct the current "
        "workflow state from the raw history: identify active assumptions, "
        "prior attempts and their outcomes, constraints, pending "
        "validations, and unresolved errors. Use that reconstructed state "
        "to answer the question precisely. If the context does not support "
        "an answer, say so."
    ),
    "B": (
        "You answer the user's question using only the information in the "
        "provided context. The context is a prose summary describing what "
        "is currently true at a specific point in a coding-assistant "
        "session. Use the summary to answer the question precisely. If the "
        "summary does not support an answer, say so."
    ),
    "C": (
        "You answer the user's question using only the information in the "
        "provided context. The context is a structured list of currently-"
        "held operational beliefs about a coding-assistant workflow. Each "
        "entry has the form `belief_type :: claim`. Use these beliefs to "
        "answer the question precisely. If the beliefs do not support an "
        "answer, say so."
    ),
    "A_prime": (
        "You answer the user's question using only the information in the "
        "provided context. The context is a prose summary describing what "
        "is currently true at a specific point in a coding-assistant "
        "session. Use the summary to answer the question precisely. If the "
        "summary does not support an answer, say so."
    ),
}

USER_PROMPT_TEMPLATE = (
    "CONTEXT:\n"
    "{grounding_payload}\n"
    "\n"
    "QUESTION:\n"
    "{question}"
)

RETRY_MAX     = 5
RETRY_INITIAL = 4.0


# ─── Helpers ───────────────────────────────────────────────────────────

def load_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(l) for l in path.open()]


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def context_path(model_id: str, arm: str) -> pathlib.Path:
    arm_part = "a_prime" if arm == "A_prime" else arm.lower()
    return DATA_DIR / f"contexts_{model_id}_arm_{arm_part}.jsonl"


def answer_path(model_id: str, arm: str) -> pathlib.Path:
    arm_part = "a_prime" if arm == "A_prime" else arm.lower()
    return DATA_DIR / f"answers_{model_id}_arm_{arm_part}.jsonl"


def build_user_prompt(question: str, grounding_payload: str) -> str:
    return USER_PROMPT_TEMPLATE.format(grounding_payload=grounding_payload, question=question)


def load_existing_answers(path: pathlib.Path) -> set[str]:
    """Return set of question_ids that already have valid answers (for resume)."""
    if not path.exists():
        return set()
    keys: set[str] = set()
    with path.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("answer_text") is not None and r.get("finish_reason") not in (None, "api_error",):
                keys.add(r["question_id"])
    return keys


def stats(arr):
    if not arr:
        return {"min": None, "p50": None, "p90": None, "max": None, "mean": None}
    s = sorted(arr); n = len(s)
    return {"min": s[0], "p50": s[n // 2],
            "p90": s[min(n - 1, int(n * 0.9))], "max": s[-1],
            "mean": sum(arr) / n}


# ─── Provider answer-generation dispatchers ────────────────────────────

def _retry(fn, label):
    delay = RETRY_INITIAL
    last_err: Exception | None = None
    for attempt in range(1, RETRY_MAX + 1):
        try:
            return fn()
        except (OAIRateLimit, OAITimeout, AnthRateLimit) as e:
            last_err = e
            print(f"    {label} retry {attempt}/{RETRY_MAX} after {type(e).__name__}; sleeping {delay:.1f}s", flush=True)
            time.sleep(delay); delay *= 2
        except (OAIStatus, AnthStatus) as e:
            code = getattr(e, "status_code", 0)
            if 500 <= code < 600:
                last_err = e
                print(f"    {label} retry {attempt}/{RETRY_MAX} after {code}; sleeping {delay:.1f}s", flush=True)
                time.sleep(delay); delay *= 2
            else:
                raise
        except gen_errors.APIError as e:
            code = getattr(e, "code", 0) or 0
            if 500 <= code < 600 or code == 429:
                last_err = e
                print(f"    {label} retry {attempt}/{RETRY_MAX} after Gemini {code}; sleeping {delay:.1f}s", flush=True)
                time.sleep(delay); delay *= 2
            else:
                raise
    raise last_err if last_err else RuntimeError(f"{label} retries exhausted")


def generate_openai(client: OpenAI, model_cfg: dict, system_prompt: str, user_prompt: str) -> dict:
    def _do():
        return client.chat.completions.create(
            model=model_cfg["id"],
            temperature=model_cfg["temperature"],
            seed=model_cfg["seed"],
            max_tokens=MAX_OUTPUT_TOKENS_ANSWER,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
        )
    t0 = time.time()
    resp = _retry(_do, label=f"openai/{model_cfg['id']}")
    wall = time.time() - t0
    choice = resp.choices[0]
    return {
        "answer_text":          choice.message.content or "",
        "input_tokens":         resp.usage.prompt_tokens,
        "output_tokens":        resp.usage.completion_tokens,
        "thoughts_token_count": None,
        "model_resolved":       resp.model,
        "system_fingerprint":   getattr(resp, "system_fingerprint", None),
        "finish_reason":        choice.finish_reason,
        "wall_seconds":         wall,
    }


def generate_anthropic(client: Anthropic, model_cfg: dict, system_prompt: str, user_prompt: str) -> dict:
    kwargs = {
        "model":      model_cfg["id"],
        "max_tokens": MAX_OUTPUT_TOKENS_ANSWER,
        "system":     system_prompt,
        "messages":   [{"role": "user", "content": user_prompt}],
    }
    if model_cfg["supports_temperature"]:
        kwargs["temperature"] = model_cfg["temperature"]

    def _do():
        return client.messages.create(**kwargs)
    t0 = time.time()
    resp = _retry(_do, label=f"anthropic/{model_cfg['id']}")
    wall = time.time() - t0
    text = ""
    for block in resp.content:
        if hasattr(block, "text"):
            text += block.text
    return {
        "answer_text":          text,
        "input_tokens":         resp.usage.input_tokens,
        "output_tokens":        resp.usage.output_tokens,
        "thoughts_token_count": None,
        "model_resolved":       resp.model,
        "system_fingerprint":   None,
        "finish_reason":        resp.stop_reason,
        "wall_seconds":         wall,
    }


def generate_gemini(client, model_cfg: dict, system_prompt: str, user_prompt: str) -> dict:
    # Same Gemini fix as in build script: max_output_tokens is total cap
    # including thinking; give the model headroom for thinking + 1500-token answer.
    if model_cfg["thinking_budget"] is not None:
        effective_max_output = model_cfg["thinking_budget"] + MAX_OUTPUT_TOKENS_ANSWER
    else:
        effective_max_output = MAX_OUTPUT_TOKENS_ANSWER

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
    resp = _retry(_do, label=f"gemini/{model_cfg['id']}")
    wall = time.time() - t0
    text = resp.text or ""
    usage = resp.usage_metadata
    finish = resp.candidates[0].finish_reason if resp.candidates else None
    return {
        "answer_text":          text,
        "input_tokens":         (usage.prompt_token_count or 0) if usage else 0,
        "output_tokens":        (usage.candidates_token_count or 0) if usage else 0,
        "thoughts_token_count": (usage.thoughts_token_count or 0) if usage else 0,
        "model_resolved":       model_cfg["id"],
        "system_fingerprint":   None,
        "finish_reason":        str(finish) if finish else None,
        "wall_seconds":         wall,
    }


def generate(clients: dict, model_cfg: dict, system_prompt: str, user_prompt: str) -> dict:
    provider = model_cfg["provider"]
    if provider == "openai":
        return generate_openai(clients["openai"], model_cfg, system_prompt, user_prompt)
    if provider == "anthropic":
        return generate_anthropic(clients["anthropic"], model_cfg, system_prompt, user_prompt)
    if provider == "gemini":
        return generate_gemini(clients["gemini"], model_cfg, system_prompt, user_prompt)
    raise ValueError(f"unknown provider: {provider}")


# ─── Main ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only the first N questions (smoke test). "
                             "Omit for full 75.")
    parser.add_argument("--clear-first", action="store_true",
                        help="Delete all answers_*.jsonl files before running. "
                             "Use after smoke test to reset for full run.")
    args = parser.parse_args()

    # Verify all three provider keys
    missing = [k for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")
               if not os.environ.get(k)]
    if missing:
        print(f"ERROR: missing env vars: {missing}", file=sys.stderr)
        sys.exit(1)

    if args.clear_first:
        n_cleared = 0
        for p in sorted(DATA_DIR.glob("answers_*.jsonl")):
            p.unlink(); n_cleared += 1
        print(f"--clear-first: removed {n_cleared} answer files\n")

    clients = {
        "openai":    OpenAI(api_key=os.environ["OPENAI_API_KEY"]),
        "anthropic": Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"]),
        "gemini":    genai.Client(api_key=os.environ["GEMINI_API_KEY"]),
    }

    print("Loading inputs...")
    questions = {q["question_id"]: q for q in load_jsonl(QUESTIONS_PATH)}
    if args.limit:
        first_qids = sorted(questions.keys())[: args.limit]
        questions = {qid: questions[qid] for qid in first_qids}
        print(f"  --limit {args.limit}: smoke test on {len(questions)} questions ({len(questions) * 16} cells)")

    # Load all 16 per-(model, arm) context files
    contexts_by_model_arm: dict[tuple[str, str], dict[str, dict]] = {}
    for m in MODELS:
        for arm in ARMS:
            cp = context_path(m["id"], arm)
            if not cp.exists():
                print(f"ERROR: context file missing: {cp}", file=sys.stderr)
                sys.exit(1)
            contexts_by_model_arm[(m["id"], arm)] = {c["question_id"]: c for c in load_jsonl(cp)}

    # Verify all context files have the expected number of records
    for (mid, arm), ctxs in contexts_by_model_arm.items():
        if not args.limit and len(ctxs) != 75:
            print(f"ERROR: context file {mid}/{arm} has {len(ctxs)} records (expected 75)", file=sys.stderr)
            sys.exit(1)

    # Build the shuffled (qid, arm, model) work list — anti-curation per §8
    rng = random.Random(SHUFFLE_SEED)
    pairs: list[tuple[str, str, str]] = [
        (qid, arm, m["id"])
        for qid in sorted(questions.keys())
        for arm in ARMS
        for m in MODELS
    ]
    rng.shuffle(pairs)
    print(f"  total cells to consider: {len(pairs)} = {len(questions)} q × 4 arms × 4 models")
    print(f"  shuffle seed: {SHUFFLE_SEED}")

    # Existing answers per (model, arm) for resume
    existing: dict[tuple[str, str], set[str]] = {}
    for m in MODELS:
        for arm in ARMS:
            existing[(m["id"], arm)] = load_existing_answers(answer_path(m["id"], arm))
    already_done = sum(len(s) for s in existing.values())
    if already_done:
        print(f"  resume: {already_done} cells already complete; skipping those\n")

    # Open output files
    DATA_DIR.mkdir(exist_ok=True)
    fouts: dict[tuple[str, str], Any] = {
        (m["id"], arm): answer_path(m["id"], arm).open("a")
        for m in MODELS for arm in ARMS
    }

    cfg_by_mid = {m["id"]: m for m in MODELS}
    system_prompt_hash = {arm: sha256(SYSTEM_PROMPTS[arm]) for arm in ARMS}

    print(f"\nLocked v0.4c1.1 parameters:")
    print(f"  shuffle seed:   {SHUFFLE_SEED}")
    print(f"  max output:     {MAX_OUTPUT_TOKENS_ANSWER}")
    print(f"  models:         {[m['id'] for m in MODELS]}")
    print(f"  arms:           {ARMS}")
    print()

    # Counters
    completed:    dict[tuple[str, str], int] = defaultdict(int)
    skipped:      dict[tuple[str, str], int] = defaultdict(int)
    failed:       dict[tuple[str, str], int] = defaultdict(int)
    ctx_too_long: dict[tuple[str, str], int] = defaultdict(int)
    arm_records:  dict[tuple[str, str], list[dict]] = defaultdict(list)

    t_start = time.time()
    try:
        for i, (qid, arm, mid) in enumerate(pairs, start=1):
            cfg = cfg_by_mid[mid]
            key = (mid, arm)

            # Resume: skip already-done cells
            if qid in existing[key]:
                skipped[key] += 1
                continue

            ctx = contexts_by_model_arm[key].get(qid)
            if ctx is None or ctx.get("rendered") == "(session not found)":
                rec = {
                    "question_id": qid, "arm": arm, "model": mid,
                    "system_prompt_hash": system_prompt_hash[arm],
                    "input_tokens": 0, "output_tokens": 0,
                    "finish_reason": "missing_session_or_context",
                    "answer_text": "",
                    "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
                    "wall_seconds": 0.0,
                }
                fouts[key].write(json.dumps(rec) + "\n"); fouts[key].flush()
                skipped[key] += 1
                continue

            question_text = questions[qid]["question"]
            grounding_payload = ctx["rendered"]
            user_prompt = build_user_prompt(question_text, grounding_payload)

            # Pre-flight context-too-long check
            est = len(enc.encode(SYSTEM_PROMPTS[arm])) + len(enc.encode(user_prompt))
            if est > CONTEXT_INPUT_CAP:
                ctx_too_long[key] += 1
                rec = {
                    "question_id": qid, "arm": arm, "model": mid,
                    "system_prompt_hash": system_prompt_hash[arm],
                    "input_tokens": est, "output_tokens": 0,
                    "finish_reason": "context_too_long",
                    "answer_text": "",
                    "error": f"estimated input {est} > cap {CONTEXT_INPUT_CAP}",
                    "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
                    "wall_seconds": 0.0,
                }
                fouts[key].write(json.dumps(rec) + "\n"); fouts[key].flush()
                print(f"  [{i:4d}/{len(pairs)}] {qid} {arm} {mid}: SKIP context_too_long", flush=True)
                continue

            try:
                gen = generate(clients, cfg, SYSTEM_PROMPTS[arm], user_prompt)
            except (OAIError, AnthError, gen_errors.APIError, Exception) as e:
                failed[key] += 1
                rec = {
                    "question_id": qid, "arm": arm, "model": mid,
                    "system_prompt_hash": system_prompt_hash[arm],
                    "input_tokens": None, "output_tokens": None,
                    "finish_reason": f"api_error:{type(e).__name__}",
                    "answer_text": "",
                    "error": str(e)[:500],
                    "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
                    "wall_seconds": None,
                }
                fouts[key].write(json.dumps(rec) + "\n"); fouts[key].flush()
                print(f"  [{i:4d}/{len(pairs)}] {qid} {arm} {mid}: FAILED {type(e).__name__}", flush=True)
                continue

            rec = {
                "question_id":        qid,
                "arm":                arm,
                "model":              mid,
                "system_prompt_hash": system_prompt_hash[arm],
                "provider":           cfg["provider"],
                "temperature":        cfg["temperature"],
                "seed":               cfg["seed"],
                "thinking_budget":    cfg["thinking_budget"],
                "max_output_tokens":  MAX_OUTPUT_TOKENS_ANSWER,
                "input_tokens":       gen["input_tokens"],
                "output_tokens":      gen["output_tokens"],
                "thoughts_token_count": gen["thoughts_token_count"],
                "finish_reason":      gen["finish_reason"],
                "answer_text":        gen["answer_text"],
                "model_resolved":     gen["model_resolved"],
                "system_fingerprint": gen["system_fingerprint"],
                "generated_at":       datetime.datetime.utcnow().isoformat() + "Z",
                "wall_seconds":       gen["wall_seconds"],
            }
            fouts[key].write(json.dumps(rec) + "\n"); fouts[key].flush()
            completed[key] += 1
            arm_records[key].append(rec)

            if i % 25 == 0 or i == len(pairs):
                elapsed = time.time() - t_start
                done_total = sum(completed.values())
                skip_total = sum(skipped.values())
                fail_total = sum(failed.values())
                print(f"  [{i:4d}/{len(pairs)}] elapsed {elapsed:.0f}s, done={done_total} skip={skip_total} fail={fail_total}",
                      flush=True)

    finally:
        for f in fouts.values():
            f.close()

    # ─── Audit ──────────────────────────────────────────────────────────
    print()
    print("=" * 92)
    print("v0.4c1.1 ANSWER GENERATION SUMMARY")
    print("=" * 92)

    print(f"\nTotal elapsed: {time.time() - t_start:.0f}s")
    print(f"\nPer-model × per-arm completion:")
    print(f"{'Model':<35} {'Arm':<8} {'Done':>5} {'Skip':>5} {'Fail':>5} {'CTooLong':>9}")
    for m in MODELS:
        for arm in ARMS:
            key = (m["id"], arm)
            print(f"{m['id']:<35} {arm:<8} {completed[key]:>5} {skipped[key]:>5} {failed[key]:>5} {ctx_too_long[key]:>9}")

    audit = {
        "schema_version":   "v0.4c1.1",
        "stage":            "multi-model answer generation",
        "pre_reg":          "BELIEF_STACK_PRE_REGISTRATION_v0.4c1.md (locked v0.4c1.1)",
        "locked_parameters": {
            "models":             MODELS,
            "arms":               ARMS,
            "max_output_tokens":  MAX_OUTPUT_TOKENS_ANSWER,
            "shuffle_seed":       SHUFFLE_SEED,
            "context_limit":      CONTEXT_LIMIT,
            "context_input_cap":  CONTEXT_INPUT_CAP,
        },
        "system_prompt_hashes": system_prompt_hash,
        "per_model_per_arm": {
            f"{mid}/{arm}": {
                "completed":    completed[(mid, arm)],
                "skipped":      skipped[(mid, arm)],
                "failed":       failed[(mid, arm)],
                "ctx_too_long": ctx_too_long[(mid, arm)],
                "input_token_stats":  stats([r["input_tokens"] for r in arm_records[(mid, arm)] if r.get("input_tokens")]),
                "output_token_stats": stats([r["output_tokens"] for r in arm_records[(mid, arm)] if r.get("output_tokens")]),
                "thoughts_token_stats": stats(
                    [r["thoughts_token_count"] for r in arm_records[(mid, arm)] if r.get("thoughts_token_count")]
                ),
                "wall_seconds_stats":  stats([r["wall_seconds"] for r in arm_records[(mid, arm)] if r.get("wall_seconds")]),
            }
            for m in MODELS for arm in ARMS
            for mid in [m["id"]]
        },
        "questions_processed": len(questions),
    }
    AUDIT_PATH.write_text(json.dumps(audit, indent=2))
    print(f"\nWrote {AUDIT_PATH}")
    print(f"\nNo scoring has flowed. Per pre-reg, that is gated separately.")


if __name__ == "__main__":
    main()
