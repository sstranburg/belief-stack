#!/usr/bin/env python3
"""
Belief Stack v0.3 — Multi-arm answer generator (A, B, C).

LOCKED v0.3 generation parameters (byte-identical to v0.1 / v0.2.2 generator
config, with arm-specific system prompts per §4 strong-baseline-A design):

  - Model:              gpt-4o-2024-08-06
  - Temperature:        0.0
  - Top-p:              1.0
  - Max output tokens:  1500
  - Seed:               20260601
  - Resume policy:      per (question_id, arm) idempotent
  - Context-too-long:   pre-declared skip with `context_too_long` finish_reason

Arm-specific system prompts (per §4, with Arm A as the strong baseline that
explicitly instructs reconstruction):

  A — Raw Context Large (strong baseline):
      Tells the model to reconstruct workflow state from raw history.

  B — Belief Overlay Small:
      Tells the model the context is a maintained belief state.

  C — Belief Overlay + Minimal Evidence:
      Tells the model the context is belief state + recent scratchpad.

Telemetry (per §6.2):
  - input_tokens, output_tokens, wall_seconds per call
  - aggregated to per-arm mean/p50/p90/max in audit

Outputs:
  belief_stack_v0_3/data/answers_a.jsonl
  belief_stack_v0_3/data/answers_b.jsonl
  belief_stack_v0_3/data/answers_c.jsonl
  belief_stack_v0_3/data/answer_generation_audit.json
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

from dotenv import load_dotenv
from openai import OpenAI, APIError, RateLimitError, APIStatusError, APITimeoutError

import tiktoken

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent
V1_ROOT = STORM_ROOT / "operational_belief_v1"

QUESTIONS_PATH = V1_ROOT / "questions.jsonl"
AUDIT_PATH = ROOT / "data" / "answer_generation_audit.json"

ARMS = [
    ("A", ROOT / "data" / "contexts_arm_a.jsonl", ROOT / "data" / "answers_a.jsonl"),
    ("B", ROOT / "data" / "contexts_arm_b.jsonl", ROOT / "data" / "answers_b.jsonl"),
    ("C", ROOT / "data" / "contexts_arm_c.jsonl", ROOT / "data" / "answers_c.jsonl"),
]

MODEL_ID = "gpt-4o-2024-08-06"
TEMPERATURE = 0.0
TOP_P = 1.0
MAX_OUTPUT_TOKENS = 1500
SEED = 20260601

CONTEXT_LIMIT = 125_000
CONTEXT_INPUT_CAP = CONTEXT_LIMIT - MAX_OUTPUT_TOKENS - 200

# Per §4, system prompt differs by arm. User prompt template is the same.
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
        "provided context. The context is a set of active operational "
        "beliefs about a coding-assistant workflow. Each belief carries "
        "its lifecycle state (active / contradicted / weakened), the "
        "belief type, a claim, the authority for the claim "
        "(confirmed_by_tool, confirmed_by_user, asserted_by_assistant), "
        "and the turn it was last updated. Use these maintained beliefs "
        "to answer the question precisely. If the beliefs do not support "
        "an answer, say so."
    ),
    "C": (
        "You answer the user's question using only the information in the "
        "provided context. The context has two parts: (1) a set of active "
        "operational beliefs about a coding-assistant workflow — each with "
        "lifecycle state, claim, authority, and last-updated turn; and "
        "(2) the last few turns of the session for execution-time "
        "scratchpad. Use both to answer the question precisely. If the "
        "context does not support an answer, say so."
    ),
}

USER_PROMPT_TEMPLATE = (
    "CONTEXT:\n"
    "{grounding_payload}\n"
    "\n"
    "QUESTION:\n"
    "{question}"
)

MAX_RETRIES = 6
RETRY_INITIAL_DELAY = 4.0

load_dotenv(STORM_ROOT / ".env")
enc = tiktoken.get_encoding("cl100k_base")


def load_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(l) for l in path.open()]


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def build_user_prompt(question: str, grounding_payload: str) -> str:
    return USER_PROMPT_TEMPLATE.format(grounding_payload=grounding_payload, question=question)


def load_existing_answers(path: pathlib.Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with path.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("answer_text"):
                out[r["question_id"]] = r
    return out


def generate_one(client: OpenAI, system_prompt: str, user_prompt: str) -> dict:
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
            print(f"    retry {attempt}/{MAX_RETRIES} after {type(e).__name__}; sleeping {sleep_for:.1f}s", flush=True)
            time.sleep(sleep_for)
            delay *= 2
        except APIStatusError as e:
            if 500 <= getattr(e, "status_code", 0) < 600:
                last_err = e
                sleep_for = delay + random.uniform(0, delay * 0.5)
                print(f"    retry {attempt}/{MAX_RETRIES} after {e.status_code}; sleeping {sleep_for:.1f}s", flush=True)
                time.sleep(sleep_for)
                delay *= 2
            else:
                raise
    raise last_err if last_err is not None else RuntimeError("retries exhausted")


def generate_for_arm(
    arm: str,
    contexts: list[dict],
    questions: dict[str, dict],
    out_path: pathlib.Path,
    client: OpenAI,
    system_prompt: str,
    system_prompt_hash: str,
) -> tuple[int, int, int, int, int]:
    existing = load_existing_answers(out_path)
    completed = skipped = failed = ctx_too_long = total_retries = 0
    total = len(contexts)

    out_path.parent.mkdir(exist_ok=True)
    fout = out_path.open("a")
    try:
        for i, ctx in enumerate(contexts, 1):
            qid = ctx["question_id"]
            if qid in existing:
                skipped += 1
                if i % 25 == 0 or i == total:
                    print(f"  [{arm}] {i}/{total}  skipped={skipped}, done={completed}, failed={failed}, ctx_too_long={ctx_too_long}", flush=True)
                continue

            question_text = questions[qid]["question"]
            grounding_payload = ctx["rendered"]
            user_prompt = build_user_prompt(question_text, grounding_payload)
            prompt_hash = sha256(system_prompt + "\n---\n" + user_prompt)
            context_hash = sha256(grounding_payload)

            estimated_input = len(enc.encode(system_prompt)) + len(enc.encode(user_prompt))
            if estimated_input > CONTEXT_INPUT_CAP:
                ctx_too_long += 1
                rec = {
                    "question_id":        qid,
                    "arm":                arm,
                    "model_requested":    MODEL_ID,
                    "system_prompt_hash": system_prompt_hash,
                    "input_tokens":       estimated_input,
                    "output_tokens":      0,
                    "finish_reason":      "context_too_long",
                    "answer_text":        "",
                    "error":              f"estimated input {estimated_input} > cap {CONTEXT_INPUT_CAP}",
                    "generated_at":       datetime.datetime.utcnow().isoformat() + "Z",
                    "wall_seconds":       0.0,
                }
                fout.write(json.dumps(rec) + "\n"); fout.flush()
                print(f"  [{arm}] {i}/{total}  SKIP {qid}: context_too_long", flush=True)
                continue

            try:
                gen = generate_one(client, system_prompt, user_prompt)
                total_retries += gen["retry_attempts"]
            except APIError as e:
                failed += 1
                rec = {
                    "question_id":        qid,
                    "arm":                arm,
                    "model_requested":    MODEL_ID,
                    "system_prompt_hash": system_prompt_hash,
                    "input_tokens":       None,
                    "output_tokens":      None,
                    "finish_reason":      f"api_error:{type(e).__name__}",
                    "answer_text":        "",
                    "error":              str(e)[:500],
                    "generated_at":       datetime.datetime.utcnow().isoformat() + "Z",
                    "wall_seconds":       None,
                }
                fout.write(json.dumps(rec) + "\n"); fout.flush()
                print(f"  [{arm}] {i}/{total}  FAILED {qid}: {type(e).__name__}", flush=True)
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
                "system_prompt_hash": system_prompt_hash,
                "input_tokens":       gen["input_tokens"],
                "output_tokens":      gen["output_tokens"],
                "finish_reason":      gen["finish_reason"],
                "answer_text":        gen["answer_text"],
                "generated_at":       datetime.datetime.utcnow().isoformat() + "Z",
                "wall_seconds":       gen["wall_seconds"],
                "retry_attempts":     gen["retry_attempts"],
            }
            fout.write(json.dumps(rec) + "\n"); fout.flush()
            completed += 1
            if i % 10 == 0 or i == total:
                print(f"  [{arm}] {i}/{total}  done={completed}, skipped={skipped}, failed={failed}, ctx_too_long={ctx_too_long}", flush=True)
    finally:
        fout.close()

    return completed, skipped, failed, ctx_too_long, total_retries


def stats(records: list[dict], key: str) -> dict:
    vals = [r[key] for r in records if r.get(key) is not None]
    if not vals:
        return {"min": None, "mean": None, "p50": None, "p90": None, "max": None}
    s = sorted(vals)
    n = len(s)
    return {
        "min":  min(vals),
        "mean": sum(vals) / len(vals),
        "p50":  s[n // 2],
        "p90":  s[min(n - 1, int(n * 0.9))],
        "max":  max(vals),
    }


def main() -> None:
    print("Loading inputs…")
    questions = {q["question_id"]: q for q in load_jsonl(QUESTIONS_PATH)}
    print(f"  questions: {len(questions)}")

    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    system_prompt_hashes = {arm: sha256(SYSTEM_PROMPTS[arm]) for arm, _, _ in ARMS}
    print(f"\nLocked v0.3 parameters:")
    print(f"  model_requested:    {MODEL_ID}")
    print(f"  temperature:        {TEMPERATURE}")
    print(f"  seed:               {SEED}")
    print(f"  arm-specific system prompts (per §4 strong-baseline-A design):")
    for arm, _, _ in ARMS:
        print(f"    arm {arm} hash: {system_prompt_hashes[arm][:16]}…")

    arm_results: dict[str, dict] = {}
    for arm, contexts_path, out_path in ARMS:
        contexts = load_jsonl(contexts_path)
        print(f"\n=== Generating arm {arm} ({len(contexts)} contexts) ===")
        done, skip, fail, ctxl, retries = generate_for_arm(
            arm, contexts, questions, out_path,
            client, SYSTEM_PROMPTS[arm], system_prompt_hashes[arm],
        )
        arm_results[arm] = {
            "context_file":             str(contexts_path),
            "answers_file":             str(out_path),
            "this_run_completed":       done,
            "this_run_skipped":         skip,
            "this_run_failed":          fail,
            "this_run_ctx_too_long":    ctxl,
            "this_run_retry_attempts":  retries,
        }

    all_records: list[dict] = []
    for arm, _ctx, ans in ARMS:
        if ans.exists():
            recs = load_jsonl(ans)
            ok = [r for r in recs if r.get("answer_text")]
            arm_results[arm]["cumulative_total"] = len(recs)
            arm_results[arm]["cumulative_with_answer"] = len(ok)
            arm_results[arm]["input_tokens"]  = stats(ok, "input_tokens")
            arm_results[arm]["output_tokens"] = stats(ok, "output_tokens")
            arm_results[arm]["wall_seconds"]  = stats(ok, "wall_seconds")
            arm_results[arm]["finish_reasons"] = dict(Counter(r.get("finish_reason") for r in recs))
            all_records.extend(recs)

    audit = {
        "schema_version":               "v0.3",
        "stage":                        "v0.3 answer generation",
        "model_requested":              MODEL_ID,
        "model_resolved_distinct":      sorted(set(r.get("model_resolved") for r in all_records if r.get("model_resolved"))),
        "temperature":                  TEMPERATURE,
        "seed":                         SEED,
        "context_input_cap":            CONTEXT_INPUT_CAP,
        "system_prompts":               SYSTEM_PROMPTS,
        "system_prompt_hashes":         system_prompt_hashes,
        "arms":                         arm_results,
    }
    AUDIT_PATH.write_text(json.dumps(audit, indent=2))
    print(f"\nWrote {AUDIT_PATH}")

    print()
    print("=" * 92)
    print("v0.3 ANSWER GENERATION SUMMARY")
    print("=" * 92)
    for arm, _ctx, ans in ARMS:
        r = arm_results[arm]
        print(
            f"  {arm}  this: done={r['this_run_completed']:>3}  "
            f"skipped={r['this_run_skipped']:>3}  failed={r['this_run_failed']:>3}  "
            f"ctx_too_long={r['this_run_ctx_too_long']:>3}  retries={r['this_run_retry_attempts']:>3}  | "
            f"cum {r.get('cumulative_with_answer', 0)}/{r.get('cumulative_total', 0)}"
        )
    print()
    print("Telemetry per arm — input tokens (mean) | wall_seconds (mean) | output tokens (mean):")
    for arm, _, _ in ARMS:
        r = arm_results[arm]
        it = r.get("input_tokens", {}).get("mean")
        ws = r.get("wall_seconds", {}).get("mean")
        ot = r.get("output_tokens", {}).get("mean")
        print(f"  {arm}: input={it:.0f}  wall={ws:.2f}s  output={ot:.0f}" if it else f"  {arm}: (no data)")


if __name__ == "__main__":
    main()
