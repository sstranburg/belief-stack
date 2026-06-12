#!/usr/bin/env python3
"""
Stack-Grounded Retrieval v0.1 — Deterministic labeling (Phase B step 3c).

Labels each (question_id, system) pair in answers_a.jsonl + answers_b.jsonl
against the five pre-registered deterministic metrics (§6):
  1. STALE_CLAIM_ERROR
  2. UNSUPPORTED_CLAIM
  3. CONTRADICTION_OMISSION
  4. INSUFFICIENT_WARRANT_OVERCLAIM
  5. EVIDENCE_BOUNDARY_VIOLATION

LOCKED v0.1 deterministic-label-judge parameters:
  - Model:                gpt-5-mini-2025-08-07 (OpenAI reasoning model)
  - Model family vs generator: different family (gpt-5-mini vs gpt-4o); reduces
                          judge-generator self-validation bias
  - Reasoning effort:     medium
  - Temperature:          not settable on this model (defaults to 1.0)
  - top_p:                1.0
  - Seed:                 20260531 (best-effort determinism per OpenAI's seed
                          contract; system_fingerprint changes can still vary
                          output)
  - max_completion_tokens: 3000  (leaves room for reasoning tokens + JSON output)
  - Response format:      json_schema (strict typing) — see LABEL_SCHEMA
  - System identity:      shown to judge for tracking; judge is INSTRUCTED to
                          not use it as a label criterion (audit trail
                          preserves auditability per user direction)
  - Resume policy:        per-pair idempotent — re-running skips pairs already
                          in the output with all 5 metrics labeled

The judge gets one call per (question_id, system) and emits all 5 metric
labels in a single JSON object. Each metric carries:
  - label: "YES" | "NO" | "NA"
  - answer_quote: verbatim snippet from the answer (empty if NO/NA)
  - context_evidence: verbatim snippet from the context (empty if NO/NA)
  - rationale: 1-2 sentence justification
  - confidence: 0.0-1.0

The auditability target (per user direction): the script preserves per-label
quote + rationale + confidence so any disputed label can be audited later
without re-running the judge.

Inputs:
  stack_grounded_v1/questions.jsonl
  stack_grounded_v1/data/contexts_a.jsonl
  stack_grounded_v1/data/contexts_b.jsonl
  stack_grounded_v1/data/answers_a.jsonl
  stack_grounded_v1/data/answers_b.jsonl

Outputs:
  stack_grounded_v1/data/deterministic_labels.jsonl
  stack_grounded_v1/data/deterministic_label_audit.json
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
from collections import Counter, defaultdict

from dotenv import load_dotenv
from openai import OpenAI, APIError, RateLimitError, APIStatusError, APITimeoutError

ROOT       = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent

QUESTIONS_PATH = ROOT / "questions.jsonl"
CONTEXTS_A     = ROOT / "data" / "contexts_a.jsonl"
CONTEXTS_B     = ROOT / "data" / "contexts_b.jsonl"
CONTEXTS_C1    = ROOT / "data" / "contexts_c1.jsonl"   # post-v0.1 rendering sensitivity
ANSWERS_A      = ROOT / "data" / "answers_a.jsonl"
ANSWERS_B      = ROOT / "data" / "answers_b.jsonl"
ANSWERS_C1     = ROOT / "data" / "answers_c1.jsonl"
OUT_LABELS     = ROOT / "data" / "deterministic_labels.jsonl"
OUT_AUDIT      = ROOT / "data" / "deterministic_label_audit.json"

# Systems iterated by this script. v0.1 labels (A, B) are already on disk
# and resume-skipped; C1 is the post-v0.1 rendering sensitivity prototype.
SYSTEMS = [
    ("A",  CONTEXTS_A,  ANSWERS_A),
    ("B",  CONTEXTS_B,  ANSWERS_B),
    ("C1", CONTEXTS_C1, ANSWERS_C1),
]

# --- LOCKED v0.1 DETERMINISTIC-JUDGE PARAMETERS -----------------------------
JUDGE_MODEL              = "gpt-5-mini-2025-08-07"
REASONING_EFFORT         = "medium"
TOP_P                    = 1.0
SEED                     = 20260531
MAX_COMPLETION_TOKENS    = 5000  # bumped from 3000 after two q's hit finish=length
MAX_RETRIES              = 6
RETRY_INITIAL_DELAY      = 4.0

METRICS = [
    "stale_claim_error",
    "unsupported_claim",
    "contradiction_omission",
    "insufficient_warrant_overclaim",
    "evidence_boundary_violation",
]

JUDGE_SYSTEM_PROMPT = """You are a deterministic-label judge for an information-retrieval comparison study.

You receive a (question, evidence_cutoff, context, answer) tuple along with the system identity (A or B) for tracking. You evaluate FIVE deterministic metrics and return a single JSON object with one entry per metric.

The system identity is shown for tracking only — DO NOT let it influence your label.

For each metric, return: label ("YES" if violation present / "NO" if clean / "NA" if not applicable), answer_quote (verbatim snippet from the answer, empty if NO/NA), context_evidence (verbatim snippet from the context that supports the label, empty if no relevant context), rationale (1-2 sentences), confidence (0.0-1.0).

METRIC DEFINITIONS:

1. STALE_CLAIM_ERROR
   The answer asserts as current/active a fact that the context shows has been weakened, contradicted, or retired. For System B contexts: look for belief items with `state: retired`, `state: contradicted`, or `state: weakened`. For System A contexts: look for chronological reversal (e.g., a later chunk reverses an earlier chunk). If the answer cites the older state without flagging the staleness, that is a YES. If the answer correctly notes the staleness or only cites still-valid facts, that is NO. NA = the question is purely descriptive of a single point in time without staleness implication.

2. UNSUPPORTED_CLAIM
   The answer asserts a specific fact that the context does not support. Pure hallucination check. General hedging language is NO. NA = the answer is a clean decline.

3. CONTRADICTION_OMISSION
   The context contains evidence that contradicts or qualifies the answer's claim, and the answer fails to acknowledge or characterize it. For System B: look at `counterevidence` block and `state: contradicted`. For System A: look for chunks that directly disagree on the same point. NA = no contradictory evidence is present in the context.

4. INSUFFICIENT_WARRANT_OVERCLAIM
   When the context is empty ("(no items)" sentinel), or when belief items are marked OUT_OF_DISTRIBUTION, or when only one or two thin chunks support a claim, the answer should decline or qualify. If the answer confidently asserts substantive claims under thin warrant, that is YES. A clean decline or explicit "I cannot say" is NO. NA = warrant is clearly sufficient (multiple IN_DISTRIBUTION beliefs or many supporting chunks).

5. EVIDENCE_BOUNDARY_VIOLATION
   The answer cites a specific date, event, or development from AFTER the evidence_cutoff. This catches training-prior contamination (the model leaking post-cutoff knowledge into the answer despite the cutoff-filtered context). If the answer stays within or before the cutoff, that is NO. NA only if the answer contains no date-bearing or event-bearing claims at all.

GUIDANCE:
- Be conservative on YES. Require concrete evidence in the quote.
- Use the exact verbatim text in the quote fields, not paraphrase.
- Empty answer_quote and context_evidence are required for NO/NA labels.
- A clean decline ("the context does not support an answer") is NO on all metrics by default.

Return the JSON object directly. Do not add commentary outside the JSON."""


def _metric_props():
    return {
        "type": "object",
        "properties": {
            "label":            {"type": "string", "enum": ["YES", "NO", "NA"]},
            "answer_quote":     {"type": "string"},
            "context_evidence": {"type": "string"},
            "rationale":        {"type": "string"},
            "confidence":       {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
        "required": ["label", "answer_quote", "context_evidence", "rationale", "confidence"],
        "additionalProperties": False,
    }


LABEL_SCHEMA = {
    "name": "deterministic_labels",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {m: _metric_props() for m in METRICS},
        "required": list(METRICS),
        "additionalProperties": False,
    },
}


load_dotenv(STORM_ROOT / ".env")


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def load_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(line) for line in path.open()]


def build_grounding_payload(context_record: dict) -> str:
    if not context_record["items"]:
        return "(no items)"
    return "\n\n".join(item["rendered"] for item in context_record["items"])


def build_user_prompt(q: dict, ctx_record: dict, system_label: str, answer_text: str) -> str:
    grounding = build_grounding_payload(ctx_record)
    return (
        f"question_id:    {q['question_id']}\n"
        f"category:       {q['category']}\n"
        f"ticker:         {q['ticker']}\n"
        f"evidence_cutoff: {q['evidence_cutoff']}\n"
        f"system:         {system_label}   (shown for tracking only — do not use as a label criterion)\n"
        f"\n"
        f"QUESTION:\n{q['question']}\n"
        f"\n"
        f"CONTEXT:\n{grounding}\n"
        f"\n"
        f"ANSWER:\n{answer_text}\n"
    )


def load_existing_labels(path: pathlib.Path) -> dict[tuple, dict]:
    """Return {(question_id, system): record} for completed labels (all 5 metrics present)."""
    if not path.exists():
        return {}
    out = {}
    with path.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            labels = r.get("labels") or {}
            if all(m in labels and "label" in labels[m] for m in METRICS):
                out[(r["question_id"], r["system"])] = r
    return out


def judge_one(client: OpenAI, user_prompt: str) -> dict:
    t0 = time.time()
    delay = RETRY_INITIAL_DELAY
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=JUDGE_MODEL,
                top_p=TOP_P,
                seed=SEED,
                max_completion_tokens=MAX_COMPLETION_TOKENS,
                reasoning_effort=REASONING_EFFORT,
                response_format={"type": "json_schema", "json_schema": LABEL_SCHEMA},
                messages=[
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
            )
            wall = time.time() - t0
            choice = resp.choices[0]
            content = choice.message.content or ""
            try:
                labels = json.loads(content) if content else {}
            except json.JSONDecodeError:
                labels = {}
            details = resp.usage.completion_tokens_details
            return {
                "labels":               labels,
                "model_resolved":       resp.model,
                "system_fingerprint":   getattr(resp, "system_fingerprint", None),
                "input_tokens":         resp.usage.prompt_tokens,
                "output_tokens":        resp.usage.completion_tokens,
                "reasoning_tokens":     getattr(details, "reasoning_tokens", None),
                "finish_reason":        choice.finish_reason,
                "wall_seconds":         wall,
                "retry_attempts":       attempt - 1,
                "raw_content":          content,
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


def main() -> None:
    print("Loading inputs...")
    questions = {q["question_id"]: q for q in load_jsonl(QUESTIONS_PATH)}
    sys_data: dict[str, dict] = {}
    for sys_label, ctx_path, ans_path in SYSTEMS:
        if not ctx_path.exists() or not ans_path.exists():
            print(f"  System {sys_label}: contexts or answers missing, skipping ({ctx_path.name} / {ans_path.name})")
            continue
        sys_data[sys_label] = {
            "contexts": {c["question_id"]: c for c in load_jsonl(ctx_path)},
            "answers":  {r["question_id"]: r for r in load_jsonl(ans_path) if r.get("answer_text")},
        }
        print(f"  System {sys_label}: {len(sys_data[sys_label]['contexts'])} contexts, {len(sys_data[sys_label]['answers'])} answers")
    print(f"  questions: {len(questions)}")

    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    judge_prompt_hash = sha256(JUDGE_SYSTEM_PROMPT)
    print(f"\nLocked judge:")
    print(f"  model:                {JUDGE_MODEL}")
    print(f"  reasoning_effort:     {REASONING_EFFORT}")
    print(f"  top_p:                {TOP_P}")
    print(f"  seed:                 {SEED}")
    print(f"  max_completion_tokens:{MAX_COMPLETION_TOKENS}")
    print(f"  judge_prompt_hash:    {judge_prompt_hash[:16]}...")

    existing = load_existing_labels(OUT_LABELS)
    print(f"\nResume: {len(existing)} already-labeled (qid, system) pairs found")

    OUT_LABELS.parent.mkdir(exist_ok=True)
    fout = OUT_LABELS.open("a")

    pairs: list[tuple] = []
    for qid in sorted(questions.keys()):
        for sys_label in [s[0] for s in SYSTEMS if s[0] in sys_data]:
            ans_map = sys_data[sys_label]["answers"]
            ctx_map = sys_data[sys_label]["contexts"]
            if qid not in ans_map or qid not in ctx_map:
                continue
            pairs.append((qid, sys_label, ans_map[qid], ctx_map[qid]))

    total = len(pairs)
    completed = 0
    skipped = 0
    failed = 0

    for i, (qid, sys_label, ans, ctx) in enumerate(pairs, 1):
        if (qid, sys_label) in existing:
            skipped += 1
            if i % 25 == 0 or i == total:
                print(f"  [{i}/{total}] skipped: {skipped}, done: {completed}, failed: {failed}", flush=True)
            continue

        q = questions[qid]
        user_prompt = build_user_prompt(q, ctx, sys_label, ans["answer_text"])
        prompt_hash  = sha256(JUDGE_SYSTEM_PROMPT + "\n---\n" + user_prompt)
        context_hash = sha256(build_grounding_payload(ctx))
        answer_hash  = sha256(ans["answer_text"])

        try:
            res = judge_one(client, user_prompt)
        except APIError as e:
            failed += 1
            err_rec = {
                "question_id":          qid,
                "system":               sys_label,
                "category":             q["category"],
                "ticker":               q["ticker"],
                "evidence_cutoff":      q["evidence_cutoff"],
                "judge_model":          JUDGE_MODEL,
                "reasoning_effort":     REASONING_EFFORT,
                "seed":                 SEED,
                "judge_prompt_hash":    judge_prompt_hash,
                "prompt_hash":          prompt_hash,
                "context_hash":         context_hash,
                "answer_hash":          answer_hash,
                "labels":               {},
                "error":                f"{type(e).__name__}: {str(e)[:300]}",
                "labeled_at":           datetime.datetime.utcnow().isoformat() + "Z",
            }
            fout.write(json.dumps(err_rec) + "\n"); fout.flush()
            print(f"  [{i}/{total}] FAILED {qid}/{sys_label}: {type(e).__name__}", flush=True)
            continue

        # If labels is empty (e.g. json parse failure or budget exhaustion),
        # log as failure for re-attempt on resume
        labels = res["labels"]
        if not all(m in labels for m in METRICS):
            failed += 1
            err_rec = {
                "question_id":          qid,
                "system":               sys_label,
                "category":             q["category"],
                "ticker":               q["ticker"],
                "evidence_cutoff":      q["evidence_cutoff"],
                "judge_model":          JUDGE_MODEL,
                "reasoning_effort":     REASONING_EFFORT,
                "seed":                 SEED,
                "judge_prompt_hash":    judge_prompt_hash,
                "prompt_hash":          prompt_hash,
                "context_hash":         context_hash,
                "answer_hash":          answer_hash,
                "labels":               labels,  # partial
                "error":                "incomplete_label_set",
                "raw_content":          res.get("raw_content", "")[:1000],
                "model_resolved":       res["model_resolved"],
                "input_tokens":         res["input_tokens"],
                "output_tokens":        res["output_tokens"],
                "reasoning_tokens":     res["reasoning_tokens"],
                "finish_reason":        res["finish_reason"],
                "wall_seconds":         res["wall_seconds"],
                "labeled_at":           datetime.datetime.utcnow().isoformat() + "Z",
            }
            fout.write(json.dumps(err_rec) + "\n"); fout.flush()
            print(f"  [{i}/{total}] FAILED {qid}/{sys_label}: incomplete labels (finish={res['finish_reason']})", flush=True)
            continue

        record = {
            "question_id":          qid,
            "system":               sys_label,
            "category":             q["category"],
            "ticker":               q["ticker"],
            "evidence_cutoff":      q["evidence_cutoff"],
            "judge_model":          JUDGE_MODEL,
            "model_resolved":       res["model_resolved"],
            "system_fingerprint":   res["system_fingerprint"],
            "reasoning_effort":     REASONING_EFFORT,
            "seed":                 SEED,
            "judge_prompt_hash":    judge_prompt_hash,
            "prompt_hash":          prompt_hash,
            "context_hash":         context_hash,
            "answer_hash":          answer_hash,
            "input_tokens":         res["input_tokens"],
            "output_tokens":        res["output_tokens"],
            "reasoning_tokens":     res["reasoning_tokens"],
            "finish_reason":        res["finish_reason"],
            "wall_seconds":         res["wall_seconds"],
            "retry_attempts":       res["retry_attempts"],
            "labels":               labels,
            "labeled_at":           datetime.datetime.utcnow().isoformat() + "Z",
        }
        fout.write(json.dumps(record) + "\n"); fout.flush()
        completed += 1
        if i % 10 == 0 or i == total:
            print(f"  [{i}/{total}] done: {completed}, skipped: {skipped}, failed: {failed}", flush=True)

    fout.close()

    # --- Aggregate ---------------------------------------------------------
    print()
    print("Re-reading labels for audit aggregation...")
    all_records = load_jsonl(OUT_LABELS)
    # Dedupe: keep the latest *complete* record per (qid, system)
    by_pair: dict[tuple, dict] = {}
    for r in all_records:
        if all(m in (r.get("labels") or {}) for m in METRICS):
            by_pair[(r["question_id"], r["system"])] = r
    print(f"  complete labels: {len(by_pair)} pairs")

    # Per-metric YES rates (by system, by category, overall)
    def yes_rate(records, metric):
        applicable = [r for r in records if r["labels"][metric]["label"] != "NA"]
        if not applicable:
            return None
        yes = sum(1 for r in applicable if r["labels"][metric]["label"] == "YES")
        return {"yes": yes, "na": sum(1 for r in records if r["labels"][metric]["label"] == "NA"),
                "applicable": len(applicable), "yes_rate": yes / len(applicable)}

    systems_seen = sorted(set(r["system"] for r in by_pair.values()))

    per_metric_by_system: dict[str, dict[str, dict]] = {}
    for sys_label in systems_seen:
        per_metric_by_system[sys_label] = {m: yes_rate([r for r in by_pair.values() if r["system"] == sys_label], m) for m in METRICS}

    per_cat_metric: dict[str, dict[str, dict[str, dict]]] = defaultdict(lambda: defaultdict(dict))
    for cat in sorted(set(r["category"] for r in by_pair.values())):
        for sys_label in systems_seen:
            subset = [r for r in by_pair.values() if r["category"] == cat and r["system"] == sys_label]
            for m in METRICS:
                per_cat_metric[cat][sys_label][m] = yes_rate(subset, m)

    # Example labels (YES with quote) for each metric — for auditability
    examples_by_metric: dict[str, list[dict]] = {}
    for m in METRICS:
        ex = []
        for r in by_pair.values():
            lab = r["labels"][m]
            if lab["label"] == "YES":
                ex.append({
                    "question_id":      r["question_id"],
                    "system":           r["system"],
                    "category":         r["category"],
                    "answer_quote":     lab["answer_quote"][:300],
                    "context_evidence": lab["context_evidence"][:300],
                    "rationale":        lab["rationale"][:300],
                    "confidence":       lab["confidence"],
                })
        # Keep up to 4 examples per metric (audit; not a complete enumeration)
        examples_by_metric[m] = ex[:8]

    confidence_stats: dict[str, dict[str, dict]] = {}
    for m in METRICS:
        for sys_label in systems_seen:
            confs = [r["labels"][m]["confidence"] for r in by_pair.values() if r["system"] == sys_label and r["labels"][m]["label"] != "NA"]
            if confs:
                confidence_stats.setdefault(m, {})[sys_label] = {
                    "min":  min(confs),
                    "mean": sum(confs)/len(confs),
                    "max":  max(confs),
                    "n":    len(confs),
                }

    audit = {
        "schema_version":           "v0.1+c1",
        "stage":                    "Phase B step 3c (det labels) + post-v0.1 C1 labels",
        "judge_model":              JUDGE_MODEL,
        "model_resolved_distinct":  sorted(set(r.get("model_resolved") for r in by_pair.values() if r.get("model_resolved"))),
        "reasoning_effort":         REASONING_EFFORT,
        "seed":                     SEED,
        "judge_prompt_hash":        judge_prompt_hash,
        "judge_prompt":             JUDGE_SYSTEM_PROMPT,
        "metrics":                  METRICS,
        "json_schema_strict":       True,
        "systems_in_audit":         systems_seen,
        "input_files": {
            "questions":  str(QUESTIONS_PATH),
            "per_system": {sys_label: {"contexts": str(p[1]), "answers": str(p[2])} for p in SYSTEMS for sys_label in [p[0]] if sys_label in sys_data},
        },
        "output_file":              str(OUT_LABELS),
        "pairs_total":              total,
        "pairs_complete":           len(by_pair),
        "pairs_complete_by_system": {sys_label: sum(1 for r in by_pair.values() if r["system"] == sys_label) for sys_label in systems_seen},
        "this_run":                 {"completed": completed, "skipped": skipped, "failed": failed},
        "per_metric_by_system":     per_metric_by_system,
        "per_category_per_system_per_metric": {cat: dict(sysmap) for cat, sysmap in per_cat_metric.items()},
        "examples_by_metric":       examples_by_metric,
        "confidence_stats":         confidence_stats,
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"Wrote {OUT_AUDIT}")

    print()
    print("=" * 72)
    print("DETERMINISTIC LABEL SUMMARY (yes-rate among applicable)")
    print("=" * 72)
    header_systems = "  ".join(f"{s}_yes/app".ljust(18) for s in systems_seen)
    print(f"  {'metric':35s}   {header_systems}")
    for m in METRICS:
        cells = []
        for s in systems_seen:
            stats = per_metric_by_system[s][m]
            if stats:
                cells.append(f"{stats['yes']:3d}/{stats['applicable']:3d} ({stats['yes_rate']*100:.0f}%)".ljust(18))
            else:
                cells.append("--".ljust(18))
        print(f"  {m:35s}   " + "  ".join(cells))


if __name__ == "__main__":
    main()
