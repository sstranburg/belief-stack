#!/usr/bin/env python3
"""
Stack-Grounded Retrieval v0.1 — Answer generator (Phase B step 3b).

Pairs the frozen System A (chunk) and System B (belief) contexts with an
identical minimal prompt template (pre-reg §5.1) and generates one answer
per (question, system). No judging, no labeling, no comparative inspection
during generation.

LOCKED v0.1 generation parameters (recorded in audit + every per-answer record):
  - Model:                gpt-4o-2024-08-06 (OpenAI Chat Completions API)
  - Temperature:          0.0
  - Top-p:                1.0
  - Max output tokens:    1500
  - Seed:                 20260531 (deterministic seed; OpenAI returns
                          system_fingerprint per response for verification)
  - System prompt:        SYSTEM_PROMPT below (identical for A and B)
  - User prompt template: USER_PROMPT_TEMPLATE below (only grounding payload
                          differs between A and B)
  - Resume policy:        per-question idempotent — re-running skips
                          (question_id, system) pairs already in the output
                          file with answer_text != ""

Per-answer record schema:
  {
    "question_id":          str,
    "system":               "A" | "B",
    "model_requested":      str,
    "model_resolved":       str,       # what the API actually used
    "system_fingerprint":   str|null,  # OpenAI determinism token
    "temperature":          float,
    "top_p":                float,
    "max_output_tokens":    int,
    "seed":                 int,
    "prompt_hash":          str,       # sha256 of system_prompt + user_prompt
    "context_hash":         str,       # sha256 of the grounding_payload string
    "system_prompt_hash":   str,       # sha256 of system_prompt only (constant)
    "input_tokens":         int,
    "output_tokens":        int,
    "finish_reason":        str,
    "answer_text":          str,       # the model's response, exactly as returned
    "generated_at":         ISO8601 UTC,
    "wall_seconds":         float,
  }

Constraints honored:
  - System prompt is identical for A and B (only grounding_payload differs).
  - No "be cautious", "cite sources", "decline if uncertain" instructions.
    The prompt says only: answer using the provided context.
  - No comparative inspection (the script does not read both answers for a
    question; it writes them and moves on).
  - Raw answer text preserved verbatim (no trimming, no post-processing).
  - On any API error, the script records the failure and continues; failed
    answers can be re-attempted on the next run via the resume policy.
  - Empty-context records still receive a generation call; the system prompt
    instructs the model to say it cannot answer when the context does not
    support one — this is the intended behavior for the 12 zero-item
    System B contexts.

Inputs:
  stack_grounded_v1/data/contexts_a.jsonl
  stack_grounded_v1/data/contexts_b.jsonl
  stack_grounded_v1/questions.jsonl

Outputs (append-friendly; resume on rerun):
  stack_grounded_v1/data/answers_a.jsonl
  stack_grounded_v1/data/answers_b.jsonl
  stack_grounded_v1/data/answer_generation_audit.json
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import sys
import time
from collections import Counter

from dotenv import load_dotenv
from openai import OpenAI, APIError, RateLimitError, APIStatusError, APITimeoutError

ROOT       = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent

CONTEXTS_A     = ROOT / "data" / "contexts_a.jsonl"
CONTEXTS_B     = ROOT / "data" / "contexts_b.jsonl"
CONTEXTS_C1    = ROOT / "data" / "contexts_c1.jsonl"   # post-v0.1 rendering sensitivity
QUESTIONS_PATH = ROOT / "questions.jsonl"
ANSWERS_A      = ROOT / "data" / "answers_a.jsonl"
ANSWERS_B      = ROOT / "data" / "answers_b.jsonl"
ANSWERS_C1     = ROOT / "data" / "answers_c1.jsonl"
AUDIT_PATH     = ROOT / "data" / "answer_generation_audit.json"

# Systems iterated by this script. v0.1 answers (A, B) are already on disk
# and resume-skipped; C1 is the post-v0.1 rendering sensitivity prototype.
SYSTEMS = [
    ("A",  CONTEXTS_A,  ANSWERS_A),
    ("B",  CONTEXTS_B,  ANSWERS_B),
    ("C1", CONTEXTS_C1, ANSWERS_C1),
]

# --- LOCKED v0.1 GENERATION PARAMETERS --------------------------------------
MODEL_ID           = "gpt-4o-2024-08-06"
TEMPERATURE        = 0.0
TOP_P              = 1.0
MAX_OUTPUT_TOKENS  = 1500
SEED               = 20260531

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
# ----------------------------------------------------------------------------

load_dotenv(STORM_ROOT / ".env")


def load_jsonl(path: pathlib.Path) -> list[dict]:
    out = []
    with path.open() as f:
        for line in f:
            out.append(json.loads(line))
    return out


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def build_grounding_payload(context_record: dict) -> str:
    """
    Build the LLM-visible grounding payload for one context record.

    Two rendering modes are supported:
      - per-item rendering (A, B): items[].rendered is concatenated; this is
        the v0.1 path.
      - context-level rendering (C1+): the context record carries a top-level
        'rendered' string built by the C1 narrative-prose builder; used as-is.

    For zero-item contexts (e.g. System B on thin actors at early cutoffs)
    the payload is the explicit sentinel '(no items)' so the model is told
    the context is empty rather than receiving a blank string.
    """
    # Context-level rendering (C1)
    if isinstance(context_record.get("rendered"), str) and context_record["rendered"]:
        return context_record["rendered"]
    # Per-item rendering (A, B v0.1 path)
    if not context_record["items"]:
        return "(no items)"
    return "\n\n".join(item["rendered"] for item in context_record["items"])


def build_user_prompt(question: str, grounding_payload: str) -> str:
    return USER_PROMPT_TEMPLATE.format(grounding_payload=grounding_payload, question=question)


def load_existing_answers(path: pathlib.Path) -> dict[str, dict]:
    """Return {question_id: record} for completed (non-empty answer_text) entries."""
    if not path.exists():
        return {}
    out = {}
    with path.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("answer_text"):
                out[r["question_id"]] = r
    return out


MAX_RETRIES         = 6
RETRY_INITIAL_DELAY = 4.0   # seconds; doubles each attempt with jitter

def generate_one(client: OpenAI, system_prompt: str, user_prompt: str) -> dict:
    """
    Returns a dict with model_resolved, fingerprint, input/output tokens,
    finish_reason, answer_text, wall_seconds. Retries on rate limit / 5xx /
    timeout with exponential backoff + jitter; raises on persistent failure.
    """
    import random
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
            # Retry on 5xx; raise on 4xx (not our rate limit, those caught above)
            if 500 <= getattr(e, "status_code", 0) < 600:
                last_err = e
                sleep_for = delay + random.uniform(0, delay * 0.5)
                print(f"    retry {attempt}/{MAX_RETRIES} after {e.status_code}; sleeping {sleep_for:.1f}s", flush=True)
                time.sleep(sleep_for)
                delay *= 2
            else:
                raise
    # Exhausted retries
    raise last_err if last_err is not None else RuntimeError("retries exhausted")


def generate_for_system(system_label: str, contexts: list[dict], questions: dict[str, dict],
                        out_path: pathlib.Path, client: OpenAI,
                        system_prompt_hash: str) -> tuple[int, int, int]:
    existing = load_existing_answers(out_path)
    completed = 0
    skipped   = 0
    failed    = 0
    total = len(contexts)

    fout = out_path.open("a")

    for i, ctx in enumerate(contexts, 1):
        qid = ctx["question_id"]
        if qid in existing:
            skipped += 1
            if i % 25 == 0 or i == total:
                print(f"  [{system_label}] {i}/{total}  (skipped: {skipped}, done this run: {completed}, failed: {failed})", flush=True)
            continue

        question_text = questions[qid]["question"]
        grounding_payload = build_grounding_payload(ctx)
        user_prompt = build_user_prompt(question_text, grounding_payload)
        prompt_hash  = sha256(SYSTEM_PROMPT + "\n---\n" + user_prompt)
        context_hash = sha256(grounding_payload)

        try:
            gen = generate_one(client, SYSTEM_PROMPT, user_prompt)
        except APIError as e:
            failed += 1
            err_record = {
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
            fout.write(json.dumps(err_record) + "\n")
            fout.flush()
            print(f"  [{system_label}] {i}/{total}  FAILED: {qid} ({type(e).__name__})", flush=True)
            continue

        record = {
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
        }
        fout.write(json.dumps(record) + "\n")
        fout.flush()
        completed += 1
        if i % 10 == 0 or i == total:
            print(f"  [{system_label}] {i}/{total}  done this run: {completed}, skipped: {skipped}, failed: {failed}", flush=True)

    fout.close()
    return completed, skipped, failed


def main() -> None:
    print("Loading inputs…")
    questions  = {q["question_id"]: q for q in load_jsonl(QUESTIONS_PATH)}
    print(f"  Questions: {len(questions)}")
    system_state: dict[str, dict] = {}
    for sys_label, ctx_path, out_path in SYSTEMS:
        if not ctx_path.exists():
            print(f"  System {sys_label}: contexts file {ctx_path} not present, skipping this system")
            continue
        ctxs = load_jsonl(ctx_path)
        print(f"  System {sys_label} contexts: {len(ctxs)}  ({ctx_path.name})")
        system_state[sys_label] = {"contexts": ctxs, "out_path": out_path}

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
    print(f"  system_prompt_hash:   {system_prompt_hash[:16]}…")

    # Ensure output directory exists
    for sys_label, ctx_path, out_path in SYSTEMS:
        out_path.parent.mkdir(exist_ok=True)
        break

    for sys_label in [s[0] for s in SYSTEMS if s[0] in system_state]:
        st = system_state[sys_label]
        print(f"\n=== Generating System {sys_label} answers ===")
        done, skip, fail = generate_for_system(sys_label, st["contexts"], questions, st["out_path"], client, system_prompt_hash)
        st["this_run"] = {"completed": done, "skipped": skip, "failed": fail}

    # Re-read all files for audit
    for sys_label in system_state:
        st = system_state[sys_label]
        st["records"] = load_jsonl(st["out_path"])
        st["ok"] = [r for r in st["records"] if r.get("answer_text")]

    def stats(records: list[dict], key: str) -> dict:
        vals = [r[key] for r in records if r.get(key) is not None]
        if not vals:
            return {"min": None, "mean": None, "max": None}
        return {"min": min(vals), "mean": sum(vals)/len(vals), "max": max(vals)}

    audit = {
        "schema_version":         "v0.1+c1",
        "stage":                  "Phase B step 3b (generation) + post-v0.1 C1 generation",
        "model_requested":        MODEL_ID,
        "temperature":            TEMPERATURE,
        "top_p":                  TOP_P,
        "max_output_tokens":      MAX_OUTPUT_TOKENS,
        "seed":                   SEED,
        "system_prompt":          SYSTEM_PROMPT,
        "system_prompt_hash":     system_prompt_hash,
        "user_prompt_template":   USER_PROMPT_TEMPLATE,
        "systems_iterated":       [s[0] for s in SYSTEMS if s[0] in system_state],
        "per_system": {
            sys_label: {
                "contexts_path":      str(dict((s[0], s[1]) for s in SYSTEMS)[sys_label]),
                "answers_path":       str(st["out_path"]),
                "this_run":           st.get("this_run", {}),
                "total_records":      len(st["records"]),
                "records_with_answer":len(st["ok"]),
                "input_tokens_stats": stats(st["ok"], "input_tokens"),
                "output_tokens_stats":stats(st["ok"], "output_tokens"),
                "wall_seconds_stats": stats(st["ok"], "wall_seconds"),
                "finish_reasons":     dict(Counter(r.get("finish_reason") for r in st["records"])),
                "model_resolved_distinct": sorted(set(r.get("model_resolved") for r in st["ok"] if r.get("model_resolved"))),
                "system_fingerprints_distinct": sorted(set(str(r.get("system_fingerprint")) for r in st["ok"] if r.get("system_fingerprint"))),
            }
            for sys_label, st in system_state.items()
        },
    }
    AUDIT_PATH.write_text(json.dumps(audit, indent=2))
    print(f"\nWrote {AUDIT_PATH}")
    print()
    print("=" * 72)
    print("ANSWER GENERATION SUMMARY")
    print("=" * 72)
    for sys_label, st in system_state.items():
        this_run = st.get("this_run", {})
        print(f"  System {sys_label}:  {len(st['ok'])} / {len(st['contexts'])} answers complete  "
              f"(this run: {this_run.get('completed',0)} done, {this_run.get('skipped',0)} skipped, {this_run.get('failed',0)} failed)")
        per_sys_audit = audit['per_system'].get(sys_label, {})
        ot = per_sys_audit.get('output_tokens_stats', {})
        if ot and ot.get('mean') is not None:
            print(f"    output tokens mean/max:  {ot['mean']:.0f} / {ot['max']}")


if __name__ == "__main__":
    main()
