#!/usr/bin/env python3
"""
Belief Stack v0.4a.1 — Deterministic scoring across A, B, C, D, E.

Reuses the v0.1 programmatic oracle (`score_operational_label.Scorer`)
and the locked v0.1 / v0.2.2 / v0.3 judge configuration BYTE-IDENTICALLY:

  - Judge model:           gpt-5-mini-2025-08-07
  - Reasoning effort:      medium
  - Seed:                  20260601
  - max_completion_tokens: 5000
  - Response format:       json_schema strict
  - Judge prompt:          SAME HASH as v0.1 / v0.2.2 / v0.3

PRE-REG INTERPRETATION NOTE (v0.4a.1 §5 ambiguity):
  The pre-reg §5 says "no LLM judge for primary outcome" AND
  "Reuse belief_stack_v0_3/score_v3.py" — those are in tension.
  v0.3's methodology is: deterministic oracle is ground truth; LLM
  judge classifies the answer's behavior on each metric; combine
  under oracle-wins-on-disagreement policy. The judge does NOT
  override the oracle; it just extracts the answer's claimed behavior
  from prose. This script uses that same v0.3-equivalent methodology
  because the alternative ("strict oracle only") is uncomputable
  without hand-labeling free-text answers.

  Interpretation: §5's "no LLM judge for primary outcome" reads as
  "the judge does not override the oracle on disagreement" — same as
  v0.3. The "Reuse score_v3.py" instruction is the operational truth.

Primary outcome: planning-correctness rate per arm = 1 - aggregate
error rate. Pre-registered minimum effect size between ladder rungs:
3 percentage points.

Outputs:
  belief_stack_v0_4a/data/deterministic_labels.jsonl
  belief_stack_v0_4a/data/deterministic_label_audit.json
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

OUT_LABELS = ROOT / "data" / "deterministic_labels.jsonl"
OUT_AUDIT  = ROOT / "data" / "deterministic_label_audit.json"

JUDGE_MODEL           = "gpt-5-mini-2025-08-07"
REASONING_EFFORT      = "medium"
TOP_P                 = 1.0
SEED                  = 20260601
MAX_COMPLETION_TOKENS = 5000
MAX_RETRIES           = 6
RETRY_INITIAL_DELAY   = 4.0

# Pre-registered minimum effect size between adjacent ladder rungs
MIN_EFFECT_PP = 3.0

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
                out[(r["question_id"], arm)] = r
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
            print(f"    retry {attempt}/{MAX_RETRIES} after {type(e).__name__}; sleeping {sleep_for:.1f}s",
                  flush=True)
            time.sleep(sleep_for); delay *= 2
        except APIStatusError as e:
            if 500 <= getattr(e, "status_code", 0) < 600:
                last_err = e
                sleep_for = delay + random.uniform(0, delay * 0.5)
                print(f"    retry {attempt}/{MAX_RETRIES} after {e.status_code}; sleeping {sleep_for:.1f}s",
                      flush=True)
                time.sleep(sleep_for); delay *= 2
            else:
                raise
    raise last_err if last_err is not None else RuntimeError("retries exhausted")


def yes_rate(records, metric):
    applicable = [r for r in records if r["labels"][metric]["label"] != "NA"]
    if not applicable:
        return None
    yes = sum(1 for r in applicable if r["labels"][metric]["label"] == "YES")
    return {
        "yes":        yes,
        "na":         sum(1 for r in records if r["labels"][metric]["label"] == "NA"),
        "applicable": len(applicable),
        "yes_rate":   yes / len(applicable),
    }


def aggregate_op_error(records):
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


def classify_a_prime_outcome(arm_correctness: dict[str, float]) -> dict:
    """Apply the pre-registered §12 (v0.4a.2) outcome classes for Arm A'.

    Three primary outcome classes locked at pre-reg time:
      • A' ≈ B/C  (within 2 pp)  → compression alone explains v0.4a.1's B-vs-A lift
      • A' < B    by ≥ 3 pp      → substrate transformation matters above compression
      • A' ≈ A    (within 2 pp)  → strongest possible support for thesis
      • Between                  → partial contribution; quantify split honestly
    """
    if not all(k in arm_correctness for k in ("A", "B", "C", "A_prime")):
        return None

    ap = arm_correctness["A_prime"] * 100
    a  = arm_correctness["A"]       * 100
    b  = arm_correctness["B"]       * 100
    c  = arm_correctness["C"]       * 100

    deltas = {
        "A_prime - A": ap - a,
        "B - A_prime": b - ap,
        "C - A_prime": c - ap,
        "A_prime - B": ap - b,
    }

    def near_b_or_c(x): return abs(x - b) < 2.0 or abs(x - c) < 2.0
    def near_a(x):      return abs(x - a) < 2.0
    def beats_b(diff):  return diff <= -MIN_EFFECT_PP   # A' < B by 3 pp

    if near_a(ap):
        return {"outcome_class": "A_prime_near_A",
                "label": "compression_of_raw_log_does_not_help",
                "deltas": deltas, "ap": ap, "a": a, "b": b, "c": c,
                "interpretation":
                    "Strongest possible support for the thesis. Compression of "
                    "raw log alone does not reach maintained-substrate "
                    "correctness — the substrate transformation is doing the "
                    "work."}

    if near_b_or_c(ap):
        return {"outcome_class": "A_prime_near_B_or_C",
                "label": "compression_alone_explains_lift",
                "deltas": deltas, "ap": ap, "a": a, "b": b, "c": c,
                "interpretation":
                    "Compression at this budget is sufficient — the substrate "
                    "transformation contributes nothing measurable beyond LLM "
                    "compression of raw history. The maintained-state "
                    "architectural distinctiveness weakens substantively."}

    if beats_b(deltas["A_prime - B"]):
        return {"outcome_class": "B_beats_A_prime_substantively",
                "label": "substrate_transformation_does_meaningful_work",
                "deltas": deltas, "ap": ap, "a": a, "b": b, "c": c,
                "interpretation":
                    "The substrate transformation does meaningful work above "
                    "and beyond prose compression. The thesis strengthens."}

    return {"outcome_class": "between",
            "label": "partial_substrate_contribution",
            "deltas": deltas, "ap": ap, "a": a, "b": b, "c": c,
            "interpretation":
                "Compression and substrate transformation each contribute "
                "partially. Magnitude tells you how much."}


def classify_outcome(arm_correctness: dict[str, float]) -> dict:
    """Apply the pre-registered §7 interpretation rules to the ladder shape.

    Returns a dict with the classified outcome (1-6) and per-step deltas.
    """
    # Per-step deltas (in percentage points)
    deltas = {
        "B-A": (arm_correctness["B"] - arm_correctness["A"]) * 100,
        "C-B": (arm_correctness["C"] - arm_correctness["B"]) * 100,
        "D-C": (arm_correctness["D"] - arm_correctness["C"]) * 100,
        "E-D": (arm_correctness["E"] - arm_correctness["D"]) * 100,
        "E-B": (arm_correctness["E"] - arm_correctness["B"]) * 100,
    }

    def gt(x): return x >= MIN_EFFECT_PP        # advancement
    def eq(x): return abs(x) < 2.0              # noise floor (≤ 2 pp)
    def lt(x): return x <= -MIN_EFFECT_PP       # regression

    a = arm_correctness["A"] * 100
    b = arm_correctness["B"] * 100
    c = arm_correctness["C"] * 100
    d = arm_correctness["D"] * 100
    e = arm_correctness["E"] * 100

    # Outcome 6: A wins overall (audit needed)
    if a > max(b, c, d, e) + MIN_EFFECT_PP:
        return {"outcome": 6, "label": "A_wins_overall_audit_needed", "deltas": deltas,
                "interpretation": "Halt and audit substrate / scoring / context construction."}

    # Outcome 1: E > D > C > B > A clean
    if gt(deltas["B-A"]) and gt(deltas["C-B"]) and gt(deltas["D-C"]) and gt(deltas["E-D"]):
        return {"outcome": 1, "label": "clean_ladder_E_gt_D_gt_C_gt_B_gt_A", "deltas": deltas,
                "interpretation": "Architecture validated at mechanism level. Lifecycle-is-novelty empirically defended."}

    # Outcome 2: E > D > C > B but B ≈ A (compression alone doesn't help)
    if gt(deltas["C-B"]) and gt(deltas["D-C"]) and gt(deltas["E-D"]) and eq(deltas["B-A"]):
        return {"outcome": 2, "label": "discipline_wins_compression_alone_does_not",
                "deltas": deltas,
                "interpretation": "Strongest result for the architecture: the discipline is what wins, not the shorter context."}

    # Outcome 3: E ≈ D > C > B > A (warrants don't add over structure-and-lifecycle)
    if eq(deltas["E-D"]) and gt(deltas["D-C"]) and gt(deltas["C-B"]) and gt(deltas["B-A"]):
        return {"outcome": 3, "label": "warrants_do_not_add_over_lifecycle",
                "deltas": deltas,
                "interpretation": "Warrants in context don't add over structure-and-lifecycle. Lifecycle implicitly carries warrant information at this budget. Proceed to v0.4b; flag warrant-in-context for v0.5."}

    # Outcome 4: E ≈ D ≈ C > B > A (structure is load-bearing; warrants + lifecycle decorative)
    if eq(deltas["E-D"]) and eq(deltas["D-C"]) and gt(deltas["C-B"]) and gt(deltas["B-A"]):
        return {"outcome": 4, "label": "structure_alone_is_load_bearing",
                "deltas": deltas,
                "interpretation": "Architecture significantly weakens; lifecycle-is-novelty needs revision."}

    # Outcome 5: E ≈ B (discipline doesn't add over maintained summaries)
    if eq(deltas["E-B"]):
        return {"outcome": 5, "label": "lifecycle_warrant_discipline_no_add_over_summary",
                "deltas": deltas,
                "interpretation": "Lifecycle/warrant discipline does not add measurable value over maintained summaries on this substrate. The lifecycle-is-novelty claim weakens substantially. (Note: NOT 'compression alone explains v0.3' — Arm B is still maintained state with current-state selection and chronology removal.)"}

    # Outcome unclassified — the ladder fits none of the pre-registered shapes
    return {"outcome": 0, "label": "unclassified_ladder_shape", "deltas": deltas,
            "interpretation": "The ladder shape did not fit any pre-registered outcome class. Report shape directly; do not classify post-hoc."}


def main():
    print("Loading inputs...")
    questions = {q["question_id"]: q for q in load_jsonl(QUESTIONS_PATH)}
    contexts = {}
    answers = {}
    for arm in ARMS:
        contexts[arm] = {c["question_id"]: c for c in load_jsonl(CONTEXT_PATHS[arm])}
        answers[arm] = {r["question_id"]: r for r in load_jsonl(ANSWER_PATHS[arm]) if r.get("answer_text")}
        print(f"  {arm}: {len(contexts[arm])} contexts, {len(answers[arm])} answers")

    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr); sys.exit(1)

    print("\nLoading oracle (scorer)...")
    scorer = Scorer()

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    judge_prompt_hash = sha256(JUDGE_SYSTEM_PROMPT)
    print(f"\nLocked judge:")
    print(f"  model:             {JUDGE_MODEL}")
    print(f"  reasoning_effort:  {REASONING_EFFORT}")
    print(f"  seed:              {SEED}")
    print(f"  judge_prompt_hash: {judge_prompt_hash[:16]}...")

    existing = load_existing_labels(OUT_LABELS)
    print(f"\nResume: {len(existing)} already-labeled (qid, arm) pairs found")

    OUT_LABELS.parent.mkdir(exist_ok=True)
    fout = OUT_LABELS.open("a")

    work_items = []
    for arm in ARMS:
        for qid in sorted(questions.keys()):
            if qid in answers[arm] and qid in contexts[arm]:
                work_items.append((qid, arm, questions[qid], answers[arm][qid], contexts[arm][qid]))

    total = len(work_items)
    completed = skipped = failed = 0
    print(f"\nLabeling {total} (question, arm) pairs across {len(ARMS)} arms...")

    for i, (qid, arm_label, q, answer_record, ctx_record) in enumerate(work_items, 1):
        if (qid, arm_label) in existing:
            skipped += 1
            if i % 50 == 0 or i == total:
                print(f"  [{i}/{total}] skipped={skipped}, done={completed}, failed={failed}", flush=True)
            continue

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
        user_prompt = build_user_prompt(q, ctx_record, arm_label, answer_record["answer_text"], oracle_summary)
        prompt_hash = sha256(JUDGE_SYSTEM_PROMPT + "\n---\n" + user_prompt)
        context_hash = sha256(ctx_record["rendered"])
        answer_hash = sha256(answer_record["answer_text"])

        try:
            res = judge_one(client, user_prompt)
        except APIError as e:
            failed += 1
            err = {
                "question_id": qid, "arm": arm_label, "category": q["category"],
                "judge_model": JUDGE_MODEL, "judge_prompt_hash": judge_prompt_hash,
                "prompt_hash": prompt_hash, "labels": {},
                "error": f"{type(e).__name__}: {str(e)[:300]}",
                "labeled_at": datetime.datetime.utcnow().isoformat() + "Z",
            }
            fout.write(json.dumps(err) + "\n"); fout.flush()
            print(f"  [{i}/{total}] FAILED {qid}/{arm_label}: {type(e).__name__}", flush=True)
            continue

        ac = res["answer_classification"]
        if not all(m in ac for m in METRICS):
            failed += 1
            err = {
                "question_id": qid, "arm": arm_label, "category": q["category"],
                "judge_model": JUDGE_MODEL, "judge_prompt_hash": judge_prompt_hash,
                "prompt_hash": prompt_hash, "labels": ac,
                "error": "incomplete_classification",
                "raw_content": res.get("raw_content", "")[:1000],
                "finish_reason": res["finish_reason"],
                "labeled_at": datetime.datetime.utcnow().isoformat() + "Z",
            }
            fout.write(json.dumps(err) + "\n"); fout.flush()
            print(f"  [{i}/{total}] FAILED {qid}/{arm_label}: incomplete", flush=True)
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
                "oracle_supporting_turns":      oracle_per_metric[m]["supporting_turns"],
                "oracle_counterevidence_turns": oracle_per_metric[m]["counterevidence_turns"],
                "answer_commits_failure_mode":  judge_metric.get("answer_commits_failure_mode"),
                "answer_quote":         judge_metric.get("answer_quote", "")[:400],
                "rationale":            judge_metric.get("rationale", "")[:400],
                "confidence":           judge_metric.get("confidence"),
                "judge_oracle_conflict": (m in conflicts),
            }

        record = {
            "question_id": qid, "arm": arm_label, "category": q["category"],
            "turn_idx": q["turn_idx"], "session_id": q["session_id"],
            "judge_model": JUDGE_MODEL, "model_resolved": res["model_resolved"],
            "system_fingerprint": res["system_fingerprint"],
            "reasoning_effort": REASONING_EFFORT, "seed": SEED,
            "judge_prompt_hash": judge_prompt_hash, "prompt_hash": prompt_hash,
            "context_hash": context_hash, "answer_hash": answer_hash,
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
            print(f"  [{i}/{total}] done={completed}, skipped={skipped}, failed={failed}", flush=True)

    fout.close()

    print("\nRe-reading labels for audit aggregation...")
    all_records = load_jsonl(OUT_LABELS)
    by_pair = {}
    for r in all_records:
        if all(m in (r.get("labels") or {}) for m in METRICS):
            arm = r.get("arm") or r.get("system")
            by_pair[(r["question_id"], arm)] = r

    # Paired set: questions answered in every arm
    qids_with_all_arms = sorted(
        qid for qid in answers["A"]
        if all(qid in answers[arm] for arm in ARMS)
    )
    print(f"  paired set (questions answered in every arm): {len(qids_with_all_arms)}")
    paired_qids = set(qids_with_all_arms)

    arm_summary = {}
    arm_correctness_rate: dict[str, float] = {}
    for arm in ARMS:
        arm_records = [r for r in by_pair.values() if (r.get("arm") or r.get("system")) == arm]
        paired_records = [r for r in arm_records if r["question_id"] in paired_qids]

        per_metric_paired = {m: yes_rate(paired_records, m) for m in METRICS}
        agg_paired = aggregate_op_error(paired_records)

        arm_summary[arm] = {
            "n_total":           len(arm_records),
            "n_paired":          len(paired_records),
            "per_metric_paired": per_metric_paired,
            "aggregate_paired":  agg_paired,
        }
        if agg_paired["correctness_rate"] is not None:
            arm_correctness_rate[arm] = agg_paired["correctness_rate"]

    # Apply pre-registered §7 interpretation rules (original 5-arm ladder)
    # Compute on A/B/C/D/E only (regardless of whether A_prime is present)
    abcde = {k: v for k, v in arm_correctness_rate.items() if k in ("A","B","C","D","E")}
    outcome = classify_outcome(abcde) if len(abcde) == 5 else None

    # Apply pre-registered §12 interpretation rules for Arm A' (if present)
    a_prime_outcome = (classify_a_prime_outcome(arm_correctness_rate)
                       if "A_prime" in arm_correctness_rate else None)

    conflict_count_total = sum(len(r.get("judge_oracle_conflicts", [])) for r in by_pair.values())
    conflict_count_by_arm = {
        arm: sum(len(r.get("judge_oracle_conflicts", []))
                 for r in by_pair.values()
                 if (r.get("arm") or r.get("system")) == arm)
        for arm in ARMS
    }

    audit = {
        "schema_version":         "v0.4a.1",
        "stage":                  "v0.4a.1 deterministic scoring (5-arm mechanism ablation)",
        "judge_model":            JUDGE_MODEL,
        "reasoning_effort":       REASONING_EFFORT,
        "seed":                   SEED,
        "judge_prompt_hash":      judge_prompt_hash,
        "judge_prompt_byte_identical_to_v0_1_v0_2_2_v0_3": True,
        "metrics":                METRICS,
        "arms":                   ARMS,
        "min_effect_pp":          MIN_EFFECT_PP,
        "pre_reg_interpretation_note": (
            "Pre-reg §5 says 'no LLM judge for primary outcome' AND 'Reuse score_v3.py'. "
            "Those statements are reconciled by reading the first as 'judge does not "
            "override oracle on disagreement' — same policy as v0.3. Oracle wins on "
            "disagreement. Judge classifies the answer's behavior. Final label per "
            "(question, arm, metric) is the combined label."
        ),
        "pairs_labeled":          len(by_pair),
        "n_paired_all_arms":      len(paired_qids),
        "paired_question_ids":    sorted(paired_qids),
        "arm_summary":            arm_summary,
        "arm_correctness_rate":   arm_correctness_rate,
        "outcome_classification": outcome,
        "a_prime_outcome_classification": a_prime_outcome,
        "judge_oracle_conflict_count":  conflict_count_total,
        "judge_oracle_conflict_by_arm": conflict_count_by_arm,
        "this_run":               {"completed": completed, "skipped": skipped, "failed": failed},
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"\nWrote {OUT_AUDIT}")

    print()
    print("=" * 92)
    print(f"v0.4a.1 DETERMINISTIC SCORING SUMMARY (paired n={len(paired_qids)})")
    print("=" * 92)

    print(f"\n  {'metric':32s} " + "  ".join(f"{arm:>15s}" for arm in ARMS))
    for m in METRICS:
        row = [m]
        for arm in ARMS:
            rate = arm_summary[arm]["per_metric_paired"][m]
            if rate:
                row.append(f"{rate['yes']:2d}/{rate['applicable']:2d} ({rate['yes_rate']*100:.0f}%)")
            else:
                row.append("--")
        print(f"  {row[0]:32s} " + "  ".join(f"{c:>15s}" for c in row[1:]))

    print()
    print("  Planning correctness (paired, 1 - aggregate error rate):")
    for arm in ARMS:
        agg = arm_summary[arm]["aggregate_paired"]
        if agg["error_rate"] is not None:
            print(f"    {arm}: {agg['total_yes']:3d}/{agg['total_applicable']:3d} errors "
                  f"= {agg['error_rate']*100:.1f}% error rate, "
                  f"{agg['correctness_rate']*100:.1f}% correctness")

    print()
    print("  Ladder shape (per-step delta in percentage points):")
    if outcome:
        deltas = outcome["deltas"]
        for step, d in deltas.items():
            mark = "↑" if d >= MIN_EFFECT_PP else ("↓" if d <= -MIN_EFFECT_PP else "≈")
            print(f"    {step}: {d:+5.1f} pp  {mark}")
        print()
        print(f"  Outcome class: #{outcome['outcome']} — {outcome['label']}")
        print(f"  Interpretation: {outcome['interpretation']}")

    if a_prime_outcome:
        print()
        print("  ─── v0.4a.2 Arm A' (compression-vs-substrate isolation) ───")
        print(f"  A':       {a_prime_outcome['ap']:.1f}% correctness")
        print(f"  A:        {a_prime_outcome['a']:.1f}% correctness")
        print(f"  B:        {a_prime_outcome['b']:.1f}% correctness")
        print(f"  C:        {a_prime_outcome['c']:.1f}% correctness")
        print(f"  A' deltas (in pp):")
        for label, d in a_prime_outcome["deltas"].items():
            mark = "↑" if d >= MIN_EFFECT_PP else ("↓" if d <= -MIN_EFFECT_PP else "≈")
            print(f"    {label}: {d:+5.1f}  {mark}")
        print(f"  Outcome class: {a_prime_outcome['outcome_class']} — {a_prime_outcome['label']}")
        print(f"  Interpretation: {a_prime_outcome['interpretation']}")

    print()
    print(f"  judge↔oracle conflicts (total):  {conflict_count_total}")
    for arm in ARMS:
        print(f"    {arm}: {conflict_count_by_arm[arm]}")


if __name__ == "__main__":
    main()
