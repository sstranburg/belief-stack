#!/usr/bin/env python3
"""
Belief Stack v0.3 — Deterministic scoring across A, B, C.

Reuses the v0.1 programmatic oracle (`score_operational_label.Scorer`)
and the locked v0.1 / v0.2.2 judge configuration BYTE-IDENTICALLY:

  - Judge model:           gpt-5-mini-2025-08-07
  - Reasoning effort:      medium
  - Seed:                  20260601
  - max_completion_tokens: 5000
  - Response format:       json_schema strict
  - Judge prompt:          SAME HASH as v0.1 / v0.2.2

Per v0.3 §6 (D6 leaning):
  - Programmatic gate primary for planning correctness.
  - LLM judge used as the answer-side classifier under oracle-wins
    disagreement policy (same as v0.2.2).

Per pre-reg discipline:
  - Oracle is ground truth. Judge classifies the ANSWER only.
  - On disagreement, oracle wins; the conflict is logged.
  - No prompt tuning. All failures preserved.

Primary outcome: planning-correctness rate per arm = 1 - aggregate error rate.

Outputs:
  belief_stack_v0_3/data/deterministic_labels.jsonl
  belief_stack_v0_3/data/deterministic_label_audit.json
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

ARMS = [
    ("A", ROOT / "data" / "contexts_arm_a.jsonl", ROOT / "data" / "answers_a.jsonl"),
    ("B", ROOT / "data" / "contexts_arm_b.jsonl", ROOT / "data" / "answers_b.jsonl"),
    ("C", ROOT / "data" / "contexts_arm_c.jsonl", ROOT / "data" / "answers_c.jsonl"),
]

OUT_LABELS = ROOT / "data" / "deterministic_labels.jsonl"
OUT_AUDIT = ROOT / "data" / "deterministic_label_audit.json"

JUDGE_MODEL = "gpt-5-mini-2025-08-07"
REASONING_EFFORT = "medium"
TOP_P = 1.0
SEED = 20260601
MAX_COMPLETION_TOKENS = 5000
MAX_RETRIES = 6
RETRY_INITIAL_DELAY = 4.0

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


def main():
    print("Loading inputs...")
    questions = {q["question_id"]: q for q in load_jsonl(QUESTIONS_PATH)}
    contexts = {}
    answers = {}
    for arm, ctx_path, ans_path in ARMS:
        contexts[arm] = {c["question_id"]: c for c in load_jsonl(ctx_path)}
        answers[arm] = {r["question_id"]: r for r in load_jsonl(ans_path) if r.get("answer_text")}
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
    for arm, _, _ in ARMS:
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

    qids_with_all_arms = sorted(
        qid for qid in answers["A"]
        if all(qid in answers[arm] for arm, _, _ in ARMS)
    )
    print(f"  paired set (questions answered in every arm): {len(qids_with_all_arms)}")

    arm_summary = {}
    paired_qids = set(qids_with_all_arms)
    for arm, _, _ in ARMS:
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

    conflict_count_total = sum(len(r.get("judge_oracle_conflicts", [])) for r in by_pair.values())
    conflict_count_by_arm = {
        arm: sum(len(r.get("judge_oracle_conflicts", []))
                 for r in by_pair.values()
                 if (r.get("arm") or r.get("system")) == arm)
        for arm, _, _ in ARMS
    }

    # Per-question YES per arm — to enable post-hoc grounding-bankruptcy
    # candidate analysis (B fails where A and C succeed).
    by_qid_arm_failed = defaultdict(dict)
    for r in by_pair.values():
        arm = r.get("arm") or r.get("system")
        any_yes = any(r["labels"][m]["label"] == "YES" for m in METRICS)
        by_qid_arm_failed[r["question_id"]][arm] = any_yes

    grounding_bankruptcy_candidates = []
    for qid, arm_status in by_qid_arm_failed.items():
        if arm_status.get("B") is True and arm_status.get("A") is False and arm_status.get("C") is False:
            grounding_bankruptcy_candidates.append(qid)

    audit = {
        "schema_version":         "v0.3",
        "stage":                  "v0.3 deterministic scoring",
        "judge_model":            JUDGE_MODEL,
        "reasoning_effort":       REASONING_EFFORT,
        "seed":                   SEED,
        "judge_prompt_hash":      judge_prompt_hash,
        "judge_prompt_byte_identical_to_v0_1_v0_2_2": True,
        "metrics":                METRICS,
        "arms":                   [arm for arm, _, _ in ARMS],
        "pairs_labeled":          len(by_pair),
        "n_paired_all_arms":      len(paired_qids),
        "paired_question_ids":    sorted(paired_qids),
        "arm_summary":            arm_summary,
        "judge_oracle_conflict_count":  conflict_count_total,
        "judge_oracle_conflict_by_arm": conflict_count_by_arm,
        "grounding_bankruptcy_candidates": grounding_bankruptcy_candidates,
        "grounding_bankruptcy_note":
            "v0.3-specific failure mode candidates: questions where Arm B (overlay only) "
            "failed but Arm A (raw log) and Arm C (overlay + scratchpad) both succeeded. "
            "These are candidates because they suggest the model had the right belief state "
            "but lacked execution-time scratchpad detail.",
        "this_run":               {"completed": completed, "skipped": skipped, "failed": failed},
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"\nWrote {OUT_AUDIT}")

    print()
    print("=" * 92)
    print(f"v0.3 DETERMINISTIC SCORING SUMMARY (paired n={len(paired_qids)})")
    print("=" * 92)

    print(f"\n  {'metric':32s} " + "  ".join(f"{arm:>15s}" for arm, _, _ in ARMS))
    for m in METRICS:
        row = [m]
        for arm, _, _ in ARMS:
            rate = arm_summary[arm]["per_metric_paired"][m]
            if rate:
                row.append(f"{rate['yes']:2d}/{rate['applicable']:2d} ({rate['yes_rate']*100:.0f}%)")
            else:
                row.append("--")
        print(f"  {row[0]:32s} " + "  ".join(f"{c:>15s}" for c in row[1:]))

    print()
    print("  Planning correctness (paired, 1 - aggregate error rate):")
    for arm, _, _ in ARMS:
        agg = arm_summary[arm]["aggregate_paired"]
        if agg["error_rate"] is not None:
            print(f"    {arm}: {agg['total_yes']:3d}/{agg['total_applicable']:3d} errors "
                  f"= {agg['error_rate']*100:.1f}% error rate, "
                  f"{agg['correctness_rate']*100:.1f}% correctness")

    print()
    print(f"  judge↔oracle conflicts (total):  {conflict_count_total}")
    for arm, _, _ in ARMS:
        print(f"    {arm}: {conflict_count_by_arm[arm]}")

    print()
    print(f"  Grounding-bankruptcy candidates (B fails where A and C succeed): {len(grounding_bankruptcy_candidates)}")


if __name__ == "__main__":
    main()
