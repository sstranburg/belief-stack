#!/usr/bin/env python3
"""
Belief Stack v0.4a.1 — Multi-arm answer generator (A, B, C, D, E).

LOCKED v0.4a.1 generation parameters (per pre-reg §4):

  - Model:              gpt-4o-2024-08-06
  - Temperature:        0.0
  - Top-p:              1.0
  - Max output tokens:  1500
  - Seed:               20260601
  - Generation order:   SHUFFLED across (question, arm) pairs with fixed seed
                        — anti-curation discipline per §4 lock
  - Resume policy:      per (question_id, arm) idempotent
  - Context-too-long:   pre-declared skip with `context_too_long` finish_reason

Per §4 strong-baseline-A design + the 5-arm ablation, each arm has a
system prompt describing the format of context it receives. Prompts
describe FORMAT, not analysis instruction — the ablation tests whether
the format itself supports better planning judgment.

  A — Raw K=20 log: strong baseline, explicitly instructs reconstruction
      from raw history (same prompt as v0.3 Arm A).
  B — LLM prose summary: free-form summary of current state.
  C — Structured claims only: type + claim per belief.
  D — Claims + warrants: type + claim + authority/evidence/decay/last.
  E — Full discipline: lifecycle + type + claim + warrants.

Outputs:
  belief_stack_v0_4a/data/answers_arm_a.jsonl
  belief_stack_v0_4a/data/answers_arm_b.jsonl
  belief_stack_v0_4a/data/answers_arm_c.jsonl
  belief_stack_v0_4a/data/answers_arm_d.jsonl
  belief_stack_v0_4a/data/answers_arm_e.jsonl
  belief_stack_v0_4a/data/answer_generation_audit.json
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import random
import sys
import time
from collections import Counter

import tiktoken
from dotenv import load_dotenv
from openai import OpenAI, APIError, RateLimitError, APIStatusError, APITimeoutError

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent
V1_ROOT = STORM_ROOT / "operational_belief_v1"

QUESTIONS_PATH = V1_ROOT / "questions.jsonl"
AUDIT_PATH = ROOT / "data" / "answer_generation_audit.json"

ARMS = ["A", "B", "C", "D", "E", "A_prime"]
CONTEXT_PATHS = {
    "A":       ROOT / "data" / "contexts_arm_a.jsonl",
    "B":       ROOT / "data" / "contexts_arm_b.jsonl",
    "C":       ROOT / "data" / "contexts_arm_c.jsonl",
    "D":       ROOT / "data" / "contexts_arm_d.jsonl",
    "E":       ROOT / "data" / "contexts_arm_e.jsonl",
    "A_prime": ROOT / "data" / "contexts_arm_a_prime.jsonl",  # v0.4a.2
}
ANSWER_PATHS = {
    "A":       ROOT / "data" / "answers_arm_a.jsonl",
    "B":       ROOT / "data" / "answers_arm_b.jsonl",
    "C":       ROOT / "data" / "answers_arm_c.jsonl",
    "D":       ROOT / "data" / "answers_arm_d.jsonl",
    "E":       ROOT / "data" / "answers_arm_e.jsonl",
    "A_prime": ROOT / "data" / "answers_arm_a_prime.jsonl",   # v0.4a.2
}

MODEL_ID         = "gpt-4o-2024-08-06"
TEMPERATURE      = 0.0
TOP_P            = 1.0
MAX_OUTPUT_TOKENS = 1500
SEED             = 20260601
SHUFFLE_SEED     = 20260601  # Anti-curation shuffle of (qid, arm) pairs

CONTEXT_LIMIT     = 125_000
CONTEXT_INPUT_CAP = CONTEXT_LIMIT - MAX_OUTPUT_TOKENS - 200

MAX_RETRIES        = 6
RETRY_INITIAL_DELAY = 4.0

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
    "D": (
        "You answer the user's question using only the information in the "
        "provided context. The context is a structured list of currently-"
        "held operational beliefs about a coding-assistant workflow. Each "
        "entry has the form `belief_type :: claim (auth=AUTHORITY, "
        "evidence=[turn_ids], decay=DECAY, last=TURN)`. The authority "
        "indicates who established the belief (assistant / user / tool). "
        "The evidence turns are where supporting evidence was observed. "
        "Decay indicates freshness; last indicates the most recent update. "
        "Use these beliefs and their warrants to answer the question "
        "precisely. If the beliefs do not support an answer, say so."
    ),
    "E": (
        "You answer the user's question using only the information in the "
        "provided context. The context is a structured list of currently-"
        "held operational beliefs about a coding-assistant workflow. Each "
        "entry has the form `[LIFECYCLE_STATE] belief_type :: claim "
        "(auth=AUTHORITY, evidence=[turn_ids], decay=DECAY, last=TURN)`. "
        "The lifecycle state (active / weakened / contradicted) indicates "
        "whether the belief still holds. The authority indicates who "
        "established the belief (assistant / user / tool). The evidence "
        "turns are where supporting evidence was observed. Decay indicates "
        "freshness; last indicates the most recent update. Use these "
        "beliefs together with their warrants and lifecycle stages to "
        "answer the question precisely. If the beliefs do not support an "
        "answer, say so."
    ),
    # Arm A' shares Arm B's answer-time system prompt by design: at answer
    # time, both arms receive prose summaries describing "what is currently
    # true." The model is intentionally blind to whether the source was the
    # raw session log (A') or the maintained-state substrate (B). The whole
    # point of A' is to hold answer-time framing constant while varying the
    # source the summary was generated from.
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

load_dotenv(STORM_ROOT / ".env")
enc = tiktoken.get_encoding("cl100k_base")


def load_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(l) for l in path.open()]


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def build_user_prompt(question: str, grounding_payload: str) -> str:
    return USER_PROMPT_TEMPLATE.format(grounding_payload=grounding_payload, question=question)


def load_existing_answers(path: pathlib.Path) -> set[str]:
    """Return set of (qid, arm) keys already in the answers file (for resume)."""
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


def generate_one(client: OpenAI, system_prompt: str, user_prompt: str) -> dict:
    """One call with retries. Returns the resolved response payload."""
    t0 = time.time()
    delay = RETRY_INITIAL_DELAY
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=MODEL_ID,
                temperature=TEMPERATURE,
                top_p=TOP_P,
                max_tokens=MAX_OUTPUT_TOKENS,
                seed=SEED,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
            )
            wall = time.time() - t0
            choice = resp.choices[0]
            return {
                "model_resolved":     resp.model,
                "system_fingerprint": getattr(resp, "system_fingerprint", None),
                "input_tokens":       resp.usage.prompt_tokens,
                "output_tokens":      resp.usage.completion_tokens,
                "finish_reason":      choice.finish_reason,
                "answer_text":        choice.message.content or "",
                "wall_seconds":       wall,
                "retry_attempts":     attempt - 1,
            }
        except (RateLimitError, APITimeoutError) as e:
            last_err = e
            sleep_for = delay + random.uniform(0, delay * 0.5)
            print(f"    retry {attempt}/{MAX_RETRIES} after {type(e).__name__}; sleeping {sleep_for:.1f}s",
                  flush=True)
            time.sleep(sleep_for)
            delay *= 2
        except APIStatusError as e:
            if 500 <= getattr(e, "status_code", 0) < 600:
                last_err = e
                sleep_for = delay + random.uniform(0, delay * 0.5)
                print(f"    retry {attempt}/{MAX_RETRIES} after {e.status_code}; sleeping {sleep_for:.1f}s",
                      flush=True)
                time.sleep(sleep_for)
                delay *= 2
            else:
                raise
    raise last_err if last_err is not None else RuntimeError("retries exhausted")


def stats(arr):
    if not arr:
        return {"min": None, "mean": None, "p50": None, "p90": None, "max": None}
    s = sorted(arr)
    n = len(s)
    return {
        "min":  s[0],
        "mean": sum(arr) / n,
        "p50":  s[n // 2],
        "p90":  s[min(n - 1, int(n * 0.9))],
        "max":  s[-1],
    }


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    print("Loading inputs…")
    questions = {q["question_id"]: q for q in load_jsonl(QUESTIONS_PATH)}
    contexts_by_arm: dict[str, dict[str, dict]] = {}
    for arm in ARMS:
        ctxs = load_jsonl(CONTEXT_PATHS[arm])
        contexts_by_arm[arm] = {c["question_id"]: c for c in ctxs}
    print(f"  questions: {len(questions)}")
    for arm in ARMS:
        print(f"  contexts arm {arm}: {len(contexts_by_arm[arm])}")

    # Build the shuffled (qid, arm) work list — anti-curation per §4 lock
    rng = random.Random(SHUFFLE_SEED)
    pairs: list[tuple[str, str]] = [
        (qid, arm) for qid in sorted(questions.keys()) for arm in ARMS
    ]
    rng.shuffle(pairs)
    print(f"  total (qid, arm) pairs to process: {len(pairs)}")
    print(f"  generation order seeded with {SHUFFLE_SEED} (deterministic)")

    # Existing answers — load per arm for resume
    existing: dict[str, set[str]] = {arm: load_existing_answers(ANSWER_PATHS[arm]) for arm in ARMS}
    already = sum(len(s) for s in existing.values())
    if already:
        print(f"  resume: {already} (qid, arm) pairs already complete; skipping those")

    # Open output files
    ANSWER_PATHS["A"].parent.mkdir(exist_ok=True)
    fouts = {arm: ANSWER_PATHS[arm].open("a") for arm in ARMS}

    system_prompt_hashes = {arm: sha256(SYSTEM_PROMPTS[arm]) for arm in ARMS}

    print(f"\nLocked v0.4a.1 parameters:")
    print(f"  model:        {MODEL_ID}")
    print(f"  temperature:  {TEMPERATURE}")
    print(f"  top_p:        {TOP_P}")
    print(f"  max_tokens:   {MAX_OUTPUT_TOKENS}")
    print(f"  seed:         {SEED}")
    print(f"  shuffle seed: {SHUFFLE_SEED}")
    print(f"  System prompt hashes:")
    for arm in ARMS:
        print(f"    {arm}: {system_prompt_hashes[arm][:16]}…")
    print()

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    completed = {arm: 0 for arm in ARMS}
    failed    = {arm: 0 for arm in ARMS}
    skipped   = {arm: 0 for arm in ARMS}
    ctx_too_long = {arm: 0 for arm in ARMS}
    total_retries = {arm: 0 for arm in ARMS}
    arm_records: dict[str, list[dict]] = {arm: [] for arm in ARMS}
    arm_wall:    dict[str, list[float]] = {arm: [] for arm in ARMS}

    t_start = time.time()
    try:
        for i, (qid, arm) in enumerate(pairs, start=1):
            # Resume: skip if already done
            if qid in existing[arm]:
                skipped[arm] += 1
                continue

            ctx = contexts_by_arm[arm].get(qid)
            if ctx is None:
                print(f"  [{i}/{len(pairs)}] {qid} arm {arm}: MISSING context — skipping", flush=True)
                failed[arm] += 1
                continue

            if ctx.get("rendered") == "(session not found)":
                rec = {
                    "question_id": qid, "arm": arm,
                    "model_requested": MODEL_ID,
                    "system_prompt_hash": system_prompt_hashes[arm],
                    "input_tokens": 0, "output_tokens": 0,
                    "finish_reason": "missing_session",
                    "answer_text": "",
                    "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
                    "wall_seconds": 0.0,
                }
                fouts[arm].write(json.dumps(rec) + "\n"); fouts[arm].flush()
                skipped[arm] += 1
                continue

            question_text = questions[qid]["question"]
            grounding_payload = ctx["rendered"]
            user_prompt = build_user_prompt(question_text, grounding_payload)
            prompt_hash = sha256(SYSTEM_PROMPTS[arm] + "\n---\n" + user_prompt)
            context_hash = sha256(grounding_payload)

            estimated_input = len(enc.encode(SYSTEM_PROMPTS[arm])) + len(enc.encode(user_prompt))
            if estimated_input > CONTEXT_INPUT_CAP:
                ctx_too_long[arm] += 1
                rec = {
                    "question_id": qid, "arm": arm,
                    "model_requested": MODEL_ID,
                    "system_prompt_hash": system_prompt_hashes[arm],
                    "input_tokens": estimated_input, "output_tokens": 0,
                    "finish_reason": "context_too_long",
                    "answer_text": "",
                    "error": f"estimated input {estimated_input} > cap {CONTEXT_INPUT_CAP}",
                    "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
                    "wall_seconds": 0.0,
                }
                fouts[arm].write(json.dumps(rec) + "\n"); fouts[arm].flush()
                print(f"  [{i}/{len(pairs)}] {qid} arm {arm}: SKIP context_too_long", flush=True)
                continue

            try:
                gen = generate_one(client, SYSTEM_PROMPTS[arm], user_prompt)
                total_retries[arm] += gen["retry_attempts"]
            except APIError as e:
                failed[arm] += 1
                rec = {
                    "question_id": qid, "arm": arm,
                    "model_requested": MODEL_ID,
                    "system_prompt_hash": system_prompt_hashes[arm],
                    "input_tokens": None, "output_tokens": None,
                    "finish_reason": f"api_error:{type(e).__name__}",
                    "answer_text": "",
                    "error": str(e)[:500],
                    "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
                    "wall_seconds": None,
                }
                fouts[arm].write(json.dumps(rec) + "\n"); fouts[arm].flush()
                print(f"  [{i}/{len(pairs)}] {qid} arm {arm}: FAILED {type(e).__name__}", flush=True)
                continue

            rec = {
                "question_id":        qid,
                "arm":                arm,
                "model_requested":    MODEL_ID,
                "model_resolved":     gen["model_resolved"],
                "system_fingerprint": gen["system_fingerprint"],
                "temperature":        TEMPERATURE,
                "top_p":              TOP_P,
                "max_output_tokens":  MAX_OUTPUT_TOKENS,
                "seed":               SEED,
                "prompt_hash":        prompt_hash,
                "context_hash":       context_hash,
                "system_prompt_hash": system_prompt_hashes[arm],
                "input_tokens":       gen["input_tokens"],
                "output_tokens":      gen["output_tokens"],
                "finish_reason":      gen["finish_reason"],
                "answer_text":        gen["answer_text"],
                "generated_at":       datetime.datetime.utcnow().isoformat() + "Z",
                "wall_seconds":       gen["wall_seconds"],
                "retry_attempts":     gen["retry_attempts"],
            }
            fouts[arm].write(json.dumps(rec) + "\n"); fouts[arm].flush()
            completed[arm] += 1
            arm_records[arm].append(rec)
            arm_wall[arm].append(gen["wall_seconds"])

            if i % 25 == 0 or i == len(pairs):
                elapsed = time.time() - t_start
                done_total = sum(completed.values()) + sum(skipped.values())
                eta_remaining = (len(pairs) - i) * (elapsed / max(1, i))
                print(f"  [{i:3d}/{len(pairs)}] elapsed {elapsed:.0f}s, ETA {eta_remaining:.0f}s | "
                      f"done={dict(completed)} fail={dict(failed)} skip={dict(skipped)}",
                      flush=True)

    finally:
        for f in fouts.values():
            f.close()

    # ─── Audit ──────────────────────────────────────────────────────────
    print()
    print(f"Total elapsed: {time.time() - t_start:.0f}s")
    print()
    print(f"Per-arm completion: " + ", ".join(f"{arm}={completed[arm]}" for arm in ARMS))
    print(f"Per-arm skipped:    " + ", ".join(f"{arm}={skipped[arm]}" for arm in ARMS))
    print(f"Per-arm failed:     " + ", ".join(f"{arm}={failed[arm]}" for arm in ARMS))
    print(f"Per-arm ctx_too_long: " + ", ".join(f"{arm}={ctx_too_long[arm]}" for arm in ARMS))

    audit = {
        "schema_version": "v0.4a.1",
        "stage":          "answer generation (5-arm mechanism ablation)",
        "locked_parameters": {
            "model":              MODEL_ID,
            "temperature":        TEMPERATURE,
            "top_p":              TOP_P,
            "max_output_tokens":  MAX_OUTPUT_TOKENS,
            "seed":               SEED,
            "shuffle_seed":       SHUFFLE_SEED,
            "context_limit":      CONTEXT_LIMIT,
            "context_input_cap":  CONTEXT_INPUT_CAP,
            "max_retries":        MAX_RETRIES,
            "retry_initial_delay": RETRY_INITIAL_DELAY,
        },
        "system_prompt_hashes": system_prompt_hashes,
        "per_arm": {
            arm: {
                "completed":  completed[arm],
                "skipped":    skipped[arm],
                "failed":     failed[arm],
                "ctx_too_long": ctx_too_long[arm],
                "total_retries": total_retries[arm],
                "input_token_stats":   stats([r["input_tokens"] for r in arm_records[arm] if r.get("input_tokens")]),
                "output_token_stats":  stats([r["output_tokens"] for r in arm_records[arm] if r.get("output_tokens")]),
                "wall_seconds_stats":  stats(arm_wall[arm]),
            }
            for arm in ARMS
        },
        "questions_processed": len(questions),
    }
    AUDIT_PATH.parent.mkdir(exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(audit, indent=2))
    print(f"\nWrote {AUDIT_PATH}")


if __name__ == "__main__":
    main()
