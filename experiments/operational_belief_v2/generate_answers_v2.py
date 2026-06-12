#!/usr/bin/env python3
"""
Operational Belief v0.2.2 — Multi-arm answer generator.

Generates answers for all four locked v0.2.2 arms:
  - A      (regenerated under v0.2.2 controls per D1)
  - B100   (overlay capped at 100 tokens)
  - B250   (overlay capped at 250 tokens)
  - B500   (overlay capped at 500 tokens)

Locked generation parameters (byte-identical to v0.1 per cross-experiment
parity discipline):
  - Model:              gpt-4o-2024-08-06
  - Temperature:        0.0
  - Top-p:              1.0
  - Max output tokens:  1500
  - Seed:               20260601
  - System prompt:      identical to v0.1 (same hash)
  - User prompt:        identical to v0.1
  - Resume policy:      per-question idempotent
  - Context-too-long:   pre-declared skip; no silent truncation

Per pre-reg discipline:
  - No answer inspection between generation steps.
  - No prompt tuning.
  - No rerolls for quality.
  - All failures preserved with metadata.

Inputs:
  operational_belief_v2/data/contexts_{a,b100,b250,b500}.jsonl
  operational_belief_v1/questions.jsonl

Outputs:
  operational_belief_v2/data/answers_{a,b100,b250,b500}.jsonl
  operational_belief_v2/data/answer_generation_audit.json
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

# Arm name → (context file, output answers file)
ARMS = [
    ("A",    ROOT / "data" / "contexts_a.jsonl",    ROOT / "data" / "answers_a.jsonl"),
    ("B100", ROOT / "data" / "contexts_b100.jsonl", ROOT / "data" / "answers_b100.jsonl"),
    ("B250", ROOT / "data" / "contexts_b250.jsonl", ROOT / "data" / "answers_b250.jsonl"),
    ("B500", ROOT / "data" / "contexts_b500.jsonl", ROOT / "data" / "answers_b500.jsonl"),
]

# --- LOCKED v0.2.2 GENERATION PARAMETERS (byte-identical to v0.1) -----------
MODEL_ID          = "gpt-4o-2024-08-06"
TEMPERATURE       = 0.0
TOP_P             = 1.0
MAX_OUTPUT_TOKENS = 1500
SEED              = 20260601

CONTEXT_LIMIT     = 125_000
CONTEXT_INPUT_CAP = CONTEXT_LIMIT - MAX_OUTPUT_TOKENS - 200

SYSTEM_PROMPT = (
    "You answer the user's question using only the information in the "
    "provided context. If the context does not support an answer, say so."
)
USER_PROMPT_TEMPLATE = (
    "CONTEXT:\n"
    "{grounding_payload}\n"
    "\n"
    "QUESTION:\n"
    "{question}"
)

MAX_RETRIES         = 6
RETRY_INITIAL_DELAY = 4.0

# ----------------------------------------------------------------------------

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
    """Single API call with retry-with-backoff. Raises on persistent failure."""
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
    system_prompt_hash: str,
) -> tuple[int, int, int, int, int]:
    """Returns (completed, skipped_existing, failed, context_too_long, total_retry_attempts)."""
    existing = load_existing_answers(out_path)
    completed = 0
    skipped = 0
    failed = 0
    ctx_too_long = 0
    total_retries = 0
    total = len(contexts)

    out_path.parent.mkdir(exist_ok=True)
    fout = out_path.open("a")
    try:
        for i, ctx in enumerate(contexts, 1):
            qid = ctx["question_id"]
            if qid in existing:
                skipped += 1
                if i % 25 == 0 or i == total:
                    print(
                        f"  [{arm}] {i}/{total}  "
                        f"(skipped: {skipped}, done: {completed}, failed: {failed}, ctx_too_long: {ctx_too_long})",
                        flush=True,
                    )
                continue

            question_text = questions[qid]["question"]
            grounding_payload = ctx["rendered"]
            user_prompt = build_user_prompt(question_text, grounding_payload)
            prompt_hash = sha256(SYSTEM_PROMPT + "\n---\n" + user_prompt)
            context_hash = sha256(grounding_payload)

            estimated_input = len(enc.encode(SYSTEM_PROMPT)) + len(enc.encode(user_prompt))
            if estimated_input > CONTEXT_INPUT_CAP:
                ctx_too_long += 1
                rec = {
                    "question_id":        qid,
                    "arm":                arm,
                    "model_requested":    MODEL_ID,
                    "model_resolved":     None,
                    "system_fingerprint": None,
                    "temperature":        TEMPERATURE,
                    "top_p":              TOP_P,
                    "max_output_tokens":  MAX_OUTPUT_TOKENS,
                    "seed":               SEED,
                    "prompt_hash":        prompt_hash,
                    "context_hash":       context_hash,
                    "system_prompt_hash": system_prompt_hash,
                    "input_tokens":       estimated_input,
                    "output_tokens":      0,
                    "finish_reason":      "context_too_long",
                    "answer_text":        "",
                    "error":              f"estimated input {estimated_input} > cap {CONTEXT_INPUT_CAP}",
                    "generated_at":       datetime.datetime.utcnow().isoformat() + "Z",
                    "wall_seconds":       0.0,
                }
                fout.write(json.dumps(rec) + "\n")
                fout.flush()
                print(
                    f"  [{arm}] {i}/{total}  SKIP {qid}: context_too_long "
                    f"({estimated_input} > {CONTEXT_INPUT_CAP})",
                    flush=True,
                )
                continue

            try:
                gen = generate_one(client, SYSTEM_PROMPT, user_prompt)
                total_retries += gen["retry_attempts"]
            except APIError as e:
                failed += 1
                rec = {
                    "question_id":        qid,
                    "arm":                arm,
                    "model_requested":    MODEL_ID,
                    "model_resolved":     None,
                    "system_fingerprint": None,
                    "temperature":        TEMPERATURE,
                    "top_p":              TOP_P,
                    "max_output_tokens":  MAX_OUTPUT_TOKENS,
                    "seed":               SEED,
                    "prompt_hash":        prompt_hash,
                    "context_hash":       context_hash,
                    "system_prompt_hash": system_prompt_hash,
                    "input_tokens":       None,
                    "output_tokens":      None,
                    "finish_reason":      f"api_error:{type(e).__name__}",
                    "answer_text":        "",
                    "error":              str(e)[:500],
                    "generated_at":       datetime.datetime.utcnow().isoformat() + "Z",
                    "wall_seconds":       None,
                }
                fout.write(json.dumps(rec) + "\n")
                fout.flush()
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
            fout.write(json.dumps(rec) + "\n")
            fout.flush()
            completed += 1
            if i % 10 == 0 or i == total:
                print(
                    f"  [{arm}] {i}/{total}  done: {completed}, skipped: {skipped}, "
                    f"failed: {failed}, ctx_too_long: {ctx_too_long}",
                    flush=True,
                )
    finally:
        fout.close()

    return completed, skipped, failed, ctx_too_long, total_retries


def stats(records: list[dict], key: str) -> dict:
    vals = [r[key] for r in records if r.get(key) is not None]
    if not vals:
        return {"min": None, "mean": None, "max": None}
    return {"min": min(vals), "mean": sum(vals) / len(vals), "max": max(vals)}


def main() -> None:
    print("Loading inputs…")
    questions = {q["question_id"]: q for q in load_jsonl(QUESTIONS_PATH)}
    print(f"  Questions: {len(questions)}")

    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set in environment (.env)", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    system_prompt_hash = sha256(SYSTEM_PROMPT)
    print(f"\nLocked v0.2.2 parameters:")
    print(f"  model_requested:    {MODEL_ID}")
    print(f"  temperature:        {TEMPERATURE}")
    print(f"  top_p:              {TOP_P}")
    print(f"  max_output_tokens:  {MAX_OUTPUT_TOKENS}")
    print(f"  seed:               {SEED}")
    print(f"  system_prompt_hash: {system_prompt_hash[:16]}…")

    arm_results: dict[str, dict] = {}
    for arm, contexts_path, out_path in ARMS:
        contexts = load_jsonl(contexts_path)
        print(f"\n=== Generating {arm} answers ({len(contexts)} contexts) ===")
        done, skip, fail, ctxl, retries = generate_for_arm(
            arm, contexts, questions, out_path, client, system_prompt_hash
        )
        arm_results[arm] = {
            "context_file":      str(contexts_path),
            "answers_file":      str(out_path),
            "this_run_completed": done,
            "this_run_skipped":   skip,
            "this_run_failed":    fail,
            "this_run_ctx_too_long": ctxl,
            "this_run_retry_attempts": retries,
        }

    # Cumulative + audit
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
        "schema_version":               "v0.2.2",
        "stage":                        "operational v0.2.2 answer generation",
        "model_requested":              MODEL_ID,
        "model_resolved_distinct":      sorted(set(r.get("model_resolved") for r in all_records if r.get("model_resolved"))),
        "system_fingerprints_distinct": sorted(set(str(r.get("system_fingerprint")) for r in all_records if r.get("system_fingerprint"))),
        "temperature":                  TEMPERATURE,
        "top_p":                        TOP_P,
        "max_output_tokens":            MAX_OUTPUT_TOKENS,
        "seed":                         SEED,
        "context_input_cap":            CONTEXT_INPUT_CAP,
        "context_too_long_policy":      "pre-declared skip with `context_too_long` finish_reason; no silent truncation",
        "system_prompt":                SYSTEM_PROMPT,
        "system_prompt_hash":           system_prompt_hash,
        "user_prompt_template":         USER_PROMPT_TEMPLATE,
        "arms":                         arm_results,
    }
    AUDIT_PATH.write_text(json.dumps(audit, indent=2))
    print(f"\nWrote {AUDIT_PATH}")

    # Summary
    print()
    print("=" * 78)
    print("ANSWER GENERATION SUMMARY (this run + cumulative)")
    print("=" * 78)
    for arm, _ctx, ans in ARMS:
        r = arm_results[arm]
        print(
            f"  {arm:<5} "
            f"this run: done={r['this_run_completed']:>3}  "
            f"skipped={r['this_run_skipped']:>3}  "
            f"failed={r['this_run_failed']:>3}  "
            f"ctx_too_long={r['this_run_ctx_too_long']:>3}  "
            f"retries={r['this_run_retry_attempts']:>3}  | "
            f"cumulative: {r.get('cumulative_with_answer', 0)}/{r.get('cumulative_total', 0)}"
        )


if __name__ == "__main__":
    main()
