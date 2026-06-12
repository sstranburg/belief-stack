#!/usr/bin/env python3
"""
Operational Belief v0.1 — Answer generator.

Pairs the frozen System A (raw log) and System B (raw log + belief
overlay) contexts with an identical minimal prompt template and
generates one answer per (question, system). No judging, no labeling,
no comparative inspection during generation.

LOCKED v0.1 generation parameters (recorded in audit + every per-answer record):
  - Model:                gpt-4o-2024-08-06
  - Temperature:          0.0
  - Top-p:                1.0
  - Max output tokens:    1500
  - Seed:                 20260601
  - System prompt:        SYSTEM_PROMPT below (identical for A and B;
                          byte-identical to Stack-Grounded's v0.1 prompt)
  - User prompt template: USER_PROMPT_TEMPLATE below (only grounding
                          payload differs between A and B)
  - Resume policy:        per-question idempotent — re-running skips
                          (question_id, system) pairs already in the
                          output file with answer_text != ""
  - Context-too-long policy: if estimated input tokens + max_tokens
                          > CONTEXT_LIMIT, skip with `context_too_long`
                          failure record. NO silent truncation.

Cross-experiment parity rationale:
  Model lock matches Stack-Grounded v0.1 (gpt-4o-2024-08-06) so that
  any A-vs-B differences cannot be confounded with cross-experiment
  model differences. Same family, same prompt → the only variables
  between operational and stack-grounded are: substrate, question set,
  and the additive-vs-replacement architecture.

Constraints honored:
  - System prompt is identical for A and B (same hash).
  - No extra "be cautious" / "cite" / "decline" instructions for B.
  - No comparative inspection during generation.
  - Raw answer text preserved verbatim.
  - On any API error or context overflow, the script records the
    failure and continues; failed answers can be re-attempted on
    next run via resume.

Inputs:
  operational_belief_v1/data/contexts_a.jsonl
  operational_belief_v1/data/contexts_b.jsonl
  operational_belief_v1/questions.jsonl

Outputs (append-friendly; resume on rerun):
  operational_belief_v1/data/answers_a.jsonl
  operational_belief_v1/data/answers_b.jsonl
  operational_belief_v1/data/answer_generation_audit.json
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

CONTEXTS_A     = ROOT / "data" / "contexts_a.jsonl"
CONTEXTS_B     = ROOT / "data" / "contexts_b.jsonl"
QUESTIONS_PATH = ROOT / "questions.jsonl"
ANSWERS_A      = ROOT / "data" / "answers_a.jsonl"
ANSWERS_B      = ROOT / "data" / "answers_b.jsonl"
AUDIT_PATH     = ROOT / "data" / "answer_generation_audit.json"

# --- LOCKED v0.1 GENERATION PARAMETERS --------------------------------------
MODEL_ID           = "gpt-4o-2024-08-06"
TEMPERATURE        = 0.0
TOP_P              = 1.0
MAX_OUTPUT_TOKENS  = 1500
SEED               = 20260601

# gpt-4o context limit is 128K. Reserve room for output + system prompt.
CONTEXT_LIMIT      = 125_000
CONTEXT_INPUT_CAP  = CONTEXT_LIMIT - MAX_OUTPUT_TOKENS - 200  # ~123,300

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


def generate_for_system(system_label: str, contexts: list[dict], questions: dict[str, dict],
                        out_path: pathlib.Path, client: OpenAI,
                        system_prompt_hash: str) -> tuple[int, int, int, int]:
    """Returns (completed, skipped, failed, skipped_for_context_too_long)."""
    existing = load_existing_answers(out_path)
    completed = 0
    skipped = 0
    failed = 0
    ctx_too_long = 0
    total = len(contexts)

    fout = out_path.open("a")
    try:
        for i, ctx in enumerate(contexts, 1):
            qid = ctx["question_id"]
            if qid in existing:
                skipped += 1
                if i % 25 == 0 or i == total:
                    print(f"  [{system_label}] {i}/{total}  (skipped: {skipped}, done: {completed}, failed: {failed}, ctx_too_long: {ctx_too_long})", flush=True)
                continue

            question_text = questions[qid]["question"]
            grounding_payload = ctx["rendered"]
            user_prompt = build_user_prompt(question_text, grounding_payload)
            prompt_hash  = sha256(SYSTEM_PROMPT + "\n---\n" + user_prompt)
            context_hash = sha256(grounding_payload)

            # Pre-call context-size check (locked policy: skip, don't truncate)
            estimated_input = len(enc.encode(SYSTEM_PROMPT)) + len(enc.encode(user_prompt))
            if estimated_input > CONTEXT_INPUT_CAP:
                ctx_too_long += 1
                rec = {
                    "question_id":        qid,
                    "system":             system_label,
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
                    "error":              f"estimated input {estimated_input} tokens exceeds cap {CONTEXT_INPUT_CAP} (model limit {CONTEXT_LIMIT}); pre-declared skip policy honored",
                    "generated_at":       datetime.datetime.utcnow().isoformat() + "Z",
                    "wall_seconds":       0.0,
                }
                fout.write(json.dumps(rec) + "\n"); fout.flush()
                print(f"  [{system_label}] {i}/{total}  SKIPPED {qid}: context_too_long ({estimated_input} > {CONTEXT_INPUT_CAP})", flush=True)
                continue

            try:
                gen = generate_one(client, SYSTEM_PROMPT, user_prompt)
            except APIError as e:
                failed += 1
                rec = {
                    "question_id":        qid,
                    "system":             system_label,
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
                fout.write(json.dumps(rec) + "\n"); fout.flush()
                print(f"  [{system_label}] {i}/{total}  FAILED: {qid} ({type(e).__name__})", flush=True)
                continue

            rec = {
                "question_id":        qid,
                "system":             system_label,
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
                print(f"  [{system_label}] {i}/{total}  done: {completed}, skipped: {skipped}, failed: {failed}, ctx_too_long: {ctx_too_long}", flush=True)
    finally:
        fout.close()

    return completed, skipped, failed, ctx_too_long


def main() -> None:
    print("Loading inputs…")
    contexts_a = load_jsonl(CONTEXTS_A)
    contexts_b = load_jsonl(CONTEXTS_B)
    questions  = {q["question_id"]: q for q in load_jsonl(QUESTIONS_PATH)}
    print(f"  System A contexts: {len(contexts_a)}")
    print(f"  System B contexts: {len(contexts_b)}")
    print(f"  Questions:         {len(questions)}")

    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set in environment (.env)", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    system_prompt_hash = sha256(SYSTEM_PROMPT)
    print(f"\nLocked parameters:")
    print(f"  model_requested:      {MODEL_ID}")
    print(f"  temperature:          {TEMPERATURE}")
    print(f"  top_p:                {TOP_P}")
    print(f"  max_output_tokens:    {MAX_OUTPUT_TOKENS}")
    print(f"  seed:                 {SEED}")
    print(f"  context_input_cap:    {CONTEXT_INPUT_CAP}")
    print(f"  system_prompt_hash:   {system_prompt_hash[:16]}…")

    ANSWERS_A.parent.mkdir(exist_ok=True)

    print("\n=== Generating System A answers ===")
    a_done, a_skip, a_fail, a_ctxl = generate_for_system("A", contexts_a, questions, ANSWERS_A, client, system_prompt_hash)

    print("\n=== Generating System B answers ===")
    b_done, b_skip, b_fail, b_ctxl = generate_for_system("B", contexts_b, questions, ANSWERS_B, client, system_prompt_hash)

    # ---- Audit -----
    a_records = load_jsonl(ANSWERS_A) if ANSWERS_A.exists() else []
    b_records = load_jsonl(ANSWERS_B) if ANSWERS_B.exists() else []
    a_ok = [r for r in a_records if r.get("answer_text")]
    b_ok = [r for r in b_records if r.get("answer_text")]

    def stats(records: list[dict], key: str) -> dict:
        vals = [r[key] for r in records if r.get(key) is not None]
        if not vals:
            return {"min": None, "mean": None, "max": None}
        return {"min": min(vals), "mean": sum(vals)/len(vals), "max": max(vals)}

    audit = {
        "schema_version":          "v0.1",
        "stage":                   "operational v0.1 answer generation",
        "model_requested":         MODEL_ID,
        "model_resolved_distinct": sorted(set(r["model_resolved"] for r in a_records + b_records if r.get("model_resolved"))),
        "system_fingerprints_distinct": sorted(set(str(r.get("system_fingerprint")) for r in a_records + b_records if r.get("system_fingerprint"))),
        "temperature":             TEMPERATURE,
        "top_p":                   TOP_P,
        "max_output_tokens":       MAX_OUTPUT_TOKENS,
        "seed":                    SEED,
        "context_input_cap":       CONTEXT_INPUT_CAP,
        "context_too_long_policy": "pre-declared skip with `context_too_long` finish_reason; no silent truncation",
        "system_prompt":           SYSTEM_PROMPT,
        "system_prompt_hash":      system_prompt_hash,
        "user_prompt_template":    USER_PROMPT_TEMPLATE,
        "input_files": {
            "questions":  str(QUESTIONS_PATH),
            "contexts_a": str(CONTEXTS_A),
            "contexts_b": str(CONTEXTS_B),
        },
        "output_files": {
            "answers_a": str(ANSWERS_A),
            "answers_b": str(ANSWERS_B),
        },
        "this_run": {
            "system_a": {"completed": a_done, "skipped": a_skip, "failed": a_fail, "context_too_long": a_ctxl},
            "system_b": {"completed": b_done, "skipped": b_skip, "failed": b_fail, "context_too_long": b_ctxl},
        },
        "cumulative": {
            "system_a_total":       len(a_records),
            "system_a_with_answer": len(a_ok),
            "system_b_total":       len(b_records),
            "system_b_with_answer": len(b_ok),
        },
        "input_tokens_stats_a":  stats(a_ok, "input_tokens"),
        "output_tokens_stats_a": stats(a_ok, "output_tokens"),
        "wall_seconds_stats_a":  stats(a_ok, "wall_seconds"),
        "input_tokens_stats_b":  stats(b_ok, "input_tokens"),
        "output_tokens_stats_b": stats(b_ok, "output_tokens"),
        "wall_seconds_stats_b":  stats(b_ok, "wall_seconds"),
        "finish_reasons_a":      dict(Counter(r.get("finish_reason") for r in a_records)),
        "finish_reasons_b":      dict(Counter(r.get("finish_reason") for r in b_records)),
    }
    AUDIT_PATH.write_text(json.dumps(audit, indent=2))
    print(f"\nWrote {AUDIT_PATH}")
    print()
    print("=" * 72)
    print("ANSWER GENERATION SUMMARY")
    print("=" * 72)
    print(f"  System A:  {len(a_ok)} / {len(contexts_a)} answers complete  (this run: {a_done} done, {a_skip} skipped, {a_fail} failed, {a_ctxl} context_too_long)")
    print(f"  System B:  {len(b_ok)} / {len(contexts_b)} answers complete  (this run: {b_done} done, {b_skip} skipped, {b_fail} failed, {b_ctxl} context_too_long)")
    if a_ok:
        print(f"  System A output tokens  mean/max:  {audit['output_tokens_stats_a']['mean']:.0f} / {audit['output_tokens_stats_a']['max']}")
    if b_ok:
        print(f"  System B output tokens  mean/max:  {audit['output_tokens_stats_b']['mean']:.0f} / {audit['output_tokens_stats_b']['max']}")


if __name__ == "__main__":
    main()
