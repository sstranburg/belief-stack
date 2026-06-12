#!/usr/bin/env python3
"""
Belief Stack v0.4c1.1 — Cross-model deterministic scoring.

LOCKED v0.4c1.1 scoring parameters (per pre-reg §5, §6, §7):

  Judge:                gpt-5-mini-2025-08-07
  Reasoning effort:     medium
  Seed:                 20260601
  Policy:               oracle wins on disagreement (combine_oracle_and_judge,
                         identical to v0.3 / v0.4a)
  Sample:               n=75 paired observations per (model, arm-pair)
  Effect threshold:     3 pp advancement; 2 pp noise floor

JUDGE HELD CONSTANT — only the generator varies across models.

Per-model 5-class outcome (§7):
  1. Full replication:        B>A AND C>A AND B>A' AND C>A' (each ≥ 3 pp)
  2. Partial replication:     B OR C beats A AND A' by ≥ 3 pp (not both)
  3. Compression-equivalent:  B and/or C tie A' (within 2 pp); A' ≥ A by ≥ 3 pp
  4. No effect:               B and C tie A within 2 pp noise floor
  5. Reversal:                A or A' beats B and/or C by ≥ 3 pp

Cross-model outcome (§7):
  - All N in class 1:         cross-model claim defended at full strength
  - N-1 in class 1 + 1 cls 2: mostly defended; one partial
  - ≥ 1 in class 3:           compression-equivalent doesn't generalize
  - ≥ 1 in class 4:           thesis fails on at least one model
  - ≥ 1 in class 5:           halt and audit

Outputs:
  belief_stack_v0_4c1/data/deterministic_labels.jsonl
  belief_stack_v0_4c1/data/deterministic_label_audit.json
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

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent
V1_ROOT = STORM_ROOT / "operational_belief_v1"

sys.path.insert(0, str(V1_ROOT))
from score_operational_label import Scorer  # noqa: E402
from deterministic_label import (  # noqa: E402
    JUDGE_SYSTEM_PROMPT,
    LABEL_SCHEMA,
    METRICS,
    combine_oracle_and_judge,
)

QUESTIONS_PATH = V1_ROOT / "questions.jsonl"

MODELS = [
    "gpt-4o-2024-08-06",
    "claude-opus-4-7",
    "gemini-2.5-pro",
    "claude-haiku-4-5-20251001",
]
ARMS = ["A", "A_prime", "B", "C"]

DATA_DIR = ROOT / "data"
OUT_LABELS = DATA_DIR / "deterministic_labels.jsonl"
OUT_AUDIT  = DATA_DIR / "deterministic_label_audit.json"

JUDGE_MODEL           = "gpt-5-mini-2025-08-07"
REASONING_EFFORT      = "medium"
TOP_P                 = 1.0
SEED                  = 20260601
MAX_COMPLETION_TOKENS = 5000
MAX_RETRIES           = 6
RETRY_INITIAL_DELAY   = 4.0

# Pre-registered effect-size thresholds per pre-reg §7
MIN_EFFECT_PP = 3.0
NOISE_FLOOR_PP = 2.0

CATEGORY_METRIC_MAP = {
    "validation_check":  "stale_validation_assumption",
    "repeated_failure":  "repeated_failure_loop",
    "approval_status":   "premature_action",
    "completion_check":  "false_completion_claim",
    "readiness_check":   "missing_pause",
}

load_dotenv(STORM_ROOT / ".env")


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


def build_user_prompt(q, ctx, arm_label, answer_text, oracle_summary):
    grounding = ctx["rendered"]
    oracle_block = json.dumps(oracle_summary, indent=2)
    return (
        f"question_id:    {q['question_id']}\n"
        f"category:       {q['category']}\n"
        f"system:         {arm_label}   (shown for tracking only — do not use as a classification criterion)\n"
        f"session_id:     {q['session_id']}\n"
        f"turn_idx:       {q['turn_idx']}\n"
        f"\n"
        f"QUESTION:\n{q['question']}\n"
        f"\n"
        f"CONTEXT (what the LLM saw at generation time):\n{grounding}\n"
        f"\n"
        f"ANSWER:\n{answer_text}\n"
        f"\n"
        f"ORACLE GROUND TRUTH (computed programmatically; do NOT recompute):\n{oracle_block}\n"
    )


def load_existing_labels(path):
    """Return dict keyed by (qid, arm, model) for resume."""
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
                arm = r.get("arm") or r.get("system")
                model = r.get("model")
                out[(r["question_id"], arm, model)] = r
    return out


def judge_one(client, user_prompt):
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
                parsed = json.loads(content) if content else {}
            except json.JSONDecodeError:
                parsed = {}
            details = resp.usage.completion_tokens_details
            return {
                "answer_classification": parsed,
                "model_resolved":        resp.model,
                "system_fingerprint":    getattr(resp, "system_fingerprint", None),
                "input_tokens":          resp.usage.prompt_tokens,
                "output_tokens":         resp.usage.completion_tokens,
                "reasoning_tokens":      getattr(details, "reasoning_tokens", None),
                "finish_reason":         choice.finish_reason,
                "wall_seconds":          wall,
                "retry_attempts":        attempt - 1,
                "raw_content":           content,
            }
        except (RateLimitError, APITimeoutError) as e:
            last_err = e
            sleep_for = delay + random.uniform(0, delay * 0.5)
            print(f"    retry {attempt}/{MAX_RETRIES} after {type(e).__name__}; sleeping {sleep_for:.1f}s", flush=True)
            time.sleep(sleep_for); delay *= 2
        except APIStatusError as e:
            if 500 <= getattr(e, "status_code", 0) < 600:
                last_err = e
                sleep_for = delay + random.uniform(0, delay * 0.5)
                print(f"    retry {attempt}/{MAX_RETRIES} after {e.status_code}; sleeping {sleep_for:.1f}s", flush=True)
                time.sleep(sleep_for); delay *= 2
            else:
                raise
    raise last_err if last_err is not None else RuntimeError("retries exhausted")


def aggregate_op_error(records):
    """Aggregate planning correctness across all metrics for a record set."""
    total_yes = total_app = 0
    for m in METRICS:
        applicable = [r for r in records if r["labels"][m]["label"] != "NA"]
        yes = sum(1 for r in applicable if r["labels"][m]["label"] == "YES")
        total_yes += yes
        total_app += len(applicable)
    return {
        "total_yes":        total_yes,
        "total_applicable": total_app,
        "error_rate":       (total_yes / total_app) if total_app else None,
        "correctness_rate": (1 - total_yes / total_app) if total_app else None,
    }


# ─── §7 per-model 5-class classifier ────────────────────────────────────

def classify_per_model(rates: dict[str, float]) -> dict:
    """Apply the pre-registered §7 per-model 5-class outcome classifier.

    rates: dict with keys A, A_prime, B, C → correctness rate (0-1)
    Returns dict with class, label, deltas, and qualifying flags.
    """
    if not all(k in rates for k in ("A", "A_prime", "B", "C")):
        return {"class": None, "label": "incomplete", "deltas": {}}

    a  = rates["A"]       * 100
    ap = rates["A_prime"] * 100
    b  = rates["B"]       * 100
    c  = rates["C"]       * 100

    deltas = {
        "B-A":      b - a,
        "C-A":      c - a,
        "B-A'":     b - ap,
        "C-A'":     c - ap,
        "A'-A":     ap - a,
        "C-B":      c - b,
        "B-A'_eq":  abs(b - ap),
        "C-A'_eq":  abs(c - ap),
    }

    def gt(x): return x >= MIN_EFFECT_PP
    def near(x): return abs(x) < NOISE_FLOOR_PP

    full_replication = (
        gt(deltas["B-A"]) and gt(deltas["C-A"])
        and gt(deltas["B-A'"]) and gt(deltas["C-A'"])
    )
    if full_replication:
        return {"class": 1, "label": "full_replication",
                "deltas": deltas, "rates": {"A": a, "A_prime": ap, "B": b, "C": c},
                "interpretation":
                    "Maintained-state arms beat both reconstruction baselines by ≥ 3 pp on this model. "
                    "The v0.4a thesis replicates fully on this model."}

    # Class 2 — partial: B XOR C beats both A and A' by ≥ 3 pp
    b_beats_both     = gt(deltas["B-A"]) and gt(deltas["B-A'"])
    c_beats_both     = gt(deltas["C-A"]) and gt(deltas["C-A'"])
    if b_beats_both != c_beats_both:  # XOR
        winner = "B" if b_beats_both else "C"
        return {"class": 2, "label": "partial_replication",
                "deltas": deltas, "rates": {"A": a, "A_prime": ap, "B": b, "C": c},
                "interpretation":
                    f"Only Arm {winner} beat both reconstruction baselines by ≥ 3 pp. "
                    f"The thesis partially replicates on this model; the other substrate-derived "
                    f"arm fails to clear the threshold."}

    # Class 5 — reversal: A or A' beats B and/or C by ≥ 3 pp
    a_beats_b = gt(-deltas["B-A"])
    a_beats_c = gt(-deltas["C-A"])
    ap_beats_b = gt(-deltas["B-A'"])
    ap_beats_c = gt(-deltas["C-A'"])
    if a_beats_b or a_beats_c or ap_beats_b or ap_beats_c:
        return {"class": 5, "label": "reversal",
                "deltas": deltas, "rates": {"A": a, "A_prime": ap, "B": b, "C": c},
                "interpretation":
                    "A reconstruction baseline (A or A') beat a substrate-derived arm (B or C) "
                    "by ≥ 3 pp on this model. Investigate root cause before drawing conclusions."}

    # Class 3 — compression-equivalent: B and/or C tie A' (within 2 pp); A' ≥ A by ≥ 3 pp
    b_ties_ap = deltas["B-A'_eq"] < NOISE_FLOOR_PP
    c_ties_ap = deltas["C-A'_eq"] < NOISE_FLOOR_PP
    if (b_ties_ap or c_ties_ap) and gt(deltas["A'-A"]):
        return {"class": 3, "label": "compression_equivalent",
                "deltas": deltas, "rates": {"A": a, "A_prime": ap, "B": b, "C": c},
                "interpretation":
                    "On this model, compression alone (A') reaches similar correctness to "
                    "substrate-derived arms. The v0.4a.2 compression-control finding does "
                    "not replicate on this model on this substrate."}

    # Class 4 — no effect: B and C tie A within 2 pp
    if near(deltas["B-A"]) and near(deltas["C-A"]):
        return {"class": 4, "label": "no_effect",
                "deltas": deltas, "rates": {"A": a, "A_prime": ap, "B": b, "C": c},
                "interpretation":
                    "On this model, neither B nor C separates from A above noise. The maintained-state "
                    "thesis fails to replicate on this model."}

    return {"class": 0, "label": "unclassified",
            "deltas": deltas, "rates": {"A": a, "A_prime": ap, "B": b, "C": c},
            "interpretation":
                "The per-model deltas did not fit any pre-registered outcome class. "
                "Report shape directly; do not classify post-hoc."}


def classify_cross_model(per_model_outcomes: dict[str, dict]) -> dict:
    """Apply the pre-registered §7 cross-model outcome classifier.

    Lock-time action commitments:
      - All N in class 1: cross-model claim defended at full strength
      - N-1 in class 1 + 1 in class 2: mostly defended; one partial
      - ≥ 1 in class 3: compression-equivalent doesn't generalize
      - ≥ 1 in class 4: thesis fails on ≥ 1 model
      - ≥ 1 in class 5: halt and audit
    """
    classes = Counter(o.get("class") for o in per_model_outcomes.values())
    N = len(per_model_outcomes)

    if classes.get(5):
        return {"label": "reversal_halt_and_audit",
                "interpretation":
                    "≥ 1 model shows a reversal (A or A' beat B/C by ≥ 3 pp). "
                    "Halt and audit before drawing conclusions. May indicate methodological "
                    "issue rather than model-variance finding.",
                "class_counts": dict(classes), "N": N}
    if classes.get(4):
        return {"label": "thesis_fails_on_at_least_one_model",
                "interpretation":
                    "≥ 1 model exhibits no measurable effect (B and C tie A within 2 pp). "
                    "Cross-model claim substantially weakens; the empirical claim becomes scoped "
                    "to 'models on which the effect replicates.'",
                "class_counts": dict(classes), "N": N}
    if classes.get(3):
        return {"label": "compression_finding_does_not_generalize",
                "interpretation":
                    "≥ 1 model exhibits the v0.4a.2 compression confound. The maintained-state-vs-raw "
                    "lift holds across models, but compression-vs-substrate isolation depends on "
                    "model behavior. Paper section becomes 'maintained state beats raw context across "
                    "models; compression-vs-substrate distinguishes only on some models.'",
                "class_counts": dict(classes), "N": N}
    if classes.get(1) == N:
        return {"label": "full_cross_model_replication",
                "interpretation":
                    "All N models in class 1 (full replication). Cross-model claim defended at full strength. "
                    "Paper goes to v0.3 with cross-model section reporting all N models as supporting evidence.",
                "class_counts": dict(classes), "N": N}
    if classes.get(1) == N - 1 and classes.get(2) == 1:
        return {"label": "mostly_full_plus_one_partial",
                "interpretation":
                    "N-1 models in class 1; one in class 2 (partial replication). Cross-model claim "
                    "mostly defended; the partial-replication model is reported as a noted caveat.",
                "class_counts": dict(classes), "N": N}
    return {"label": "mixed",
            "interpretation":
                "The per-model class distribution does not fit any single pre-registered cross-model "
                "outcome cleanly. Report the per-model class counts directly.",
            "class_counts": dict(classes), "N": N}


# ─── Main ──────────────────────────────────────────────────────────────

def main() -> None:
    print("Loading inputs...")
    questions = {q["question_id"]: q for q in load_jsonl(QUESTIONS_PATH)}
    contexts: dict[tuple[str, str], dict] = {}  # (model, arm) → {qid → ctx}
    answers:  dict[tuple[str, str], dict] = {}  # (model, arm) → {qid → ans}
    for mid in MODELS:
        for arm in ARMS:
            cp = context_path(mid, arm); ap = answer_path(mid, arm)
            if not cp.exists() or not ap.exists():
                print(f"ERROR: missing {cp} or {ap}", file=sys.stderr); sys.exit(1)
            contexts[(mid, arm)] = {c["question_id"]: c for c in load_jsonl(cp)}
            answers[(mid, arm)]  = {r["question_id"]: r for r in load_jsonl(ap) if r.get("answer_text")}
            n_ctx = len(contexts[(mid, arm)]); n_ans = len(answers[(mid, arm)])
            if n_ctx != 75 or n_ans != 75:
                print(f"  warn: {mid}/{arm}: {n_ctx} contexts, {n_ans} answers (expected 75 each)")

    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr); sys.exit(1)

    print("\nLoading oracle (scorer)...")
    scorer = Scorer()

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    judge_prompt_hash = sha256(JUDGE_SYSTEM_PROMPT)
    print(f"\nLocked judge config:")
    print(f"  model:             {JUDGE_MODEL}")
    print(f"  reasoning_effort:  {REASONING_EFFORT}")
    print(f"  seed:              {SEED}")
    print(f"  judge_prompt_hash: {judge_prompt_hash[:16]}...")

    existing = load_existing_labels(OUT_LABELS)
    print(f"\nResume: {len(existing)} already-labeled (qid, arm, model) tuples found")

    OUT_LABELS.parent.mkdir(exist_ok=True)
    fout = OUT_LABELS.open("a")

    # Build work list — iterate all (qid, arm, model) cells where answer exists
    work_items = []
    for mid in MODELS:
        for arm in ARMS:
            for qid in sorted(questions.keys()):
                if qid in answers[(mid, arm)] and qid in contexts[(mid, arm)]:
                    work_items.append((qid, arm, mid))

    total = len(work_items)
    completed = skipped = failed = 0
    t_start = time.time()
    print(f"\nLabeling {total} (qid, arm, model) cells across {len(MODELS)} models × {len(ARMS)} arms...\n")

    for i, (qid, arm, mid) in enumerate(work_items, start=1):
        key = (qid, arm, mid)
        if key in existing:
            skipped += 1
            if i % 50 == 0 or i == total:
                print(f"  [{i}/{total}] skipped={skipped}, done={completed}, failed={failed}", flush=True)
            continue

        q       = questions[qid]
        ctx_rec = contexts[(mid, arm)][qid]
        ans_rec = answers[(mid, arm)][qid]
        q_metric = CATEGORY_METRIC_MAP.get(q["category"])
        oracle_result = scorer.score(q["session_id"], q["turn_idx"], q["category"])

        oracle_per_metric = {}
        for m in METRICS:
            if m == q_metric:
                oracle_per_metric[m] = {
                    "applicability":  oracle_result.applicability,
                    "oracle_class":   oracle_result.oracle_class,
                    "oracle_state":   oracle_result.oracle_state,
                    "rationale":      oracle_result.rationale,
                    "supporting_turns":      oracle_result.supporting_turns,
                    "counterevidence_turns": oracle_result.counterevidence_turns,
                }
            else:
                oracle_per_metric[m] = {
                    "applicability":  "NA",
                    "oracle_class":   None,
                    "oracle_state":   None,
                    "rationale":      f"metric not applicable to questions of category={q['category']}",
                    "supporting_turns":      [],
                    "counterevidence_turns": [],
                }

        oracle_summary = {
            m: {k: oracle_per_metric[m][k] for k in ("applicability", "oracle_class", "oracle_state", "rationale")}
            for m in METRICS
        }
        user_prompt = build_user_prompt(q, ctx_rec, arm, ans_rec["answer_text"], oracle_summary)
        prompt_hash = sha256(JUDGE_SYSTEM_PROMPT + "\n---\n" + user_prompt)

        try:
            res = judge_one(client, user_prompt)
        except APIError as e:
            failed += 1
            err = {
                "question_id": qid, "arm": arm, "model": mid, "category": q["category"],
                "judge_model": JUDGE_MODEL, "judge_prompt_hash": judge_prompt_hash,
                "prompt_hash": prompt_hash, "labels": {},
                "error": f"{type(e).__name__}: {str(e)[:300]}",
                "labeled_at": datetime.datetime.utcnow().isoformat() + "Z",
            }
            fout.write(json.dumps(err) + "\n"); fout.flush()
            print(f"  [{i}/{total}] FAILED {qid}/{arm}/{mid}: {type(e).__name__}", flush=True)
            continue

        ac = res["answer_classification"]
        if not all(m in ac for m in METRICS):
            failed += 1
            err = {
                "question_id": qid, "arm": arm, "model": mid, "category": q["category"],
                "judge_model": JUDGE_MODEL, "judge_prompt_hash": judge_prompt_hash,
                "prompt_hash": prompt_hash, "labels": ac,
                "error": "incomplete_classification",
                "raw_content": res.get("raw_content", "")[:1000],
                "finish_reason": res["finish_reason"],
                "labeled_at": datetime.datetime.utcnow().isoformat() + "Z",
            }
            fout.write(json.dumps(err) + "\n"); fout.flush()
            print(f"  [{i}/{total}] FAILED {qid}/{arm}/{mid}: incomplete", flush=True)
            continue

        final_labels = {}
        conflicts = []
        for m in METRICS:
            judge_metric = ac[m]
            label, conflict = combine_oracle_and_judge(oracle_per_metric[m], judge_metric, m)
            if conflict:
                conflicts.append(m)
            final_labels[m] = {
                "label": label,
                "oracle_applicability": oracle_per_metric[m]["applicability"],
                "oracle_class":         oracle_per_metric[m]["oracle_class"],
                "oracle_state":         oracle_per_metric[m]["oracle_state"],
                "answer_commits_failure_mode":  judge_metric.get("answer_commits_failure_mode"),
                "answer_quote":         judge_metric.get("answer_quote", "")[:400],
                "rationale":            judge_metric.get("rationale", "")[:400],
                "confidence":           judge_metric.get("confidence"),
                "judge_oracle_conflict": (m in conflicts),
            }

        record = {
            "question_id": qid, "arm": arm, "model": mid, "category": q["category"],
            "turn_idx": q["turn_idx"], "session_id": q["session_id"],
            "judge_model": JUDGE_MODEL, "model_resolved": res["model_resolved"],
            "system_fingerprint": res["system_fingerprint"],
            "reasoning_effort": REASONING_EFFORT, "seed": SEED,
            "judge_prompt_hash": judge_prompt_hash, "prompt_hash": prompt_hash,
            "input_tokens": res["input_tokens"], "output_tokens": res["output_tokens"],
            "reasoning_tokens": res["reasoning_tokens"],
            "finish_reason": res["finish_reason"], "wall_seconds": res["wall_seconds"],
            "retry_attempts": res["retry_attempts"],
            "labels": final_labels, "judge_oracle_conflicts": conflicts,
            "labeled_at": datetime.datetime.utcnow().isoformat() + "Z",
        }
        fout.write(json.dumps(record) + "\n"); fout.flush()
        completed += 1
        if i % 25 == 0 or i == total:
            elapsed = time.time() - t_start
            print(f"  [{i}/{total}] elapsed {elapsed:.0f}s, done={completed}, skipped={skipped}, failed={failed}", flush=True)

    fout.close()

    # ─── Aggregate ─────────────────────────────────────────────────────
    print("\nRe-reading labels for audit aggregation...")
    all_records = load_jsonl(OUT_LABELS)
    by_cell = {}
    for r in all_records:
        if all(m in (r.get("labels") or {}) for m in METRICS):
            by_cell[(r["question_id"], r["arm"], r["model"])] = r

    # Per-model per-arm correctness
    per_model_correctness: dict[str, dict[str, float]] = {}
    per_model_arm_summary: dict[str, dict] = {}
    for mid in MODELS:
        per_model_correctness[mid] = {}
        per_model_arm_summary[mid] = {}
        for arm in ARMS:
            arm_records = [r for r in by_cell.values()
                           if r["arm"] == arm and r["model"] == mid]
            agg = aggregate_op_error(arm_records)
            per_model_correctness[mid][arm] = agg["correctness_rate"] if agg["correctness_rate"] is not None else 0
            per_model_arm_summary[mid][arm] = {
                "n":              len(arm_records),
                "aggregate":      agg,
            }

    # Per-model 5-class
    per_model_outcomes: dict[str, dict] = {}
    for mid in MODELS:
        per_model_outcomes[mid] = classify_per_model(per_model_correctness[mid])

    cross_model_outcome = classify_cross_model(per_model_outcomes)

    # Audit
    conflict_count_total = sum(len(r.get("judge_oracle_conflicts", [])) for r in by_cell.values())
    conflict_by_model = defaultdict(int)
    conflict_by_arm = defaultdict(int)
    for r in by_cell.values():
        conflict_by_model[r["model"]] += len(r.get("judge_oracle_conflicts", []))
        conflict_by_arm[r["arm"]]   += len(r.get("judge_oracle_conflicts", []))

    audit = {
        "schema_version":         "v0.4c1.1",
        "stage":                  "v0.4c1.1 cross-model deterministic scoring",
        "judge_model":            JUDGE_MODEL,
        "reasoning_effort":       REASONING_EFFORT,
        "seed":                   SEED,
        "judge_prompt_hash":      judge_prompt_hash,
        "metrics":                METRICS,
        "models":                 MODELS,
        "arms":                   ARMS,
        "min_effect_pp":          MIN_EFFECT_PP,
        "noise_floor_pp":         NOISE_FLOOR_PP,
        "cells_labeled":          len(by_cell),
        "per_model_arm_summary":  per_model_arm_summary,
        "per_model_correctness":  per_model_correctness,
        "per_model_outcomes":     per_model_outcomes,
        "cross_model_outcome":    cross_model_outcome,
        "judge_oracle_conflict_count":      conflict_count_total,
        "judge_oracle_conflict_by_model":   dict(conflict_by_model),
        "judge_oracle_conflict_by_arm":     dict(conflict_by_arm),
        "this_run":               {"completed": completed, "skipped": skipped, "failed": failed},
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"\nWrote {OUT_AUDIT}")

    # ─── Print final report ────────────────────────────────────────────
    print()
    print("=" * 100)
    print(f"v0.4c1.1 CROSS-MODEL DETERMINISTIC SCORING SUMMARY (paired n=75 per model)")
    print("=" * 100)

    print(f"\nPer-model planning correctness (1 - aggregate error rate):")
    print(f"{'Model':<35} {'A':>8} {'A_prime':>10} {'B':>8} {'C':>8}")
    for mid in MODELS:
        r = per_model_correctness[mid]
        print(f"{mid:<35} {r['A']*100:>7.1f}% {r['A_prime']*100:>9.1f}% {r['B']*100:>7.1f}% {r['C']*100:>7.1f}%")

    print(f"\nPer-step deltas (in pp) per model:")
    bp = "B-A'"; cp = "C-A'"; ap = "A'-A"
    print(f"{'Model':<35} {'B-A':>7} {'C-A':>7} {bp:>7} {cp:>7} {ap:>7}")
    for mid in MODELS:
        d = per_model_outcomes[mid]["deltas"]
        print(f"{mid:<35} {d['B-A']:>+6.1f} {d['C-A']:>+6.1f} {d[bp]:>+6.1f} {d[cp]:>+6.1f} {d[ap]:>+6.1f}")

    print(f"\nPer-model outcome class:")
    for mid in MODELS:
        o = per_model_outcomes[mid]
        print(f"  {mid}")
        print(f"    Class: {o['class']} — {o['label']}")
        print(f"    {o['interpretation']}")

    print(f"\nCross-model outcome:")
    co = cross_model_outcome
    print(f"  Label: {co['label']}")
    print(f"  Class counts: {co['class_counts']}  (N={co['N']})")
    print(f"  {co['interpretation']}")

    print(f"\nJudge↔oracle conflicts (total): {conflict_count_total}")
    print(f"  by model: {dict(conflict_by_model)}")
    print(f"  by arm:   {dict(conflict_by_arm)}")


if __name__ == "__main__":
    main()
