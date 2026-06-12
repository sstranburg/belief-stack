#!/usr/bin/env python3
"""
Operational Belief v0.2.2 — Preference judging across 6 pairwise comparisons.

Comparisons (locked):
  primary:   B100 vs A
  secondary: B250 vs A
             B500 vs A
             B100 vs B250
             B100 vs B500
             B250 vs B500

LOCKED v0.1 preference-judge parameters (byte-identical):
  - Model:                 gpt-4.1-2025-04-14
  - Temperature:           0.0
  - top_p:                 1.0
  - Seed:                  20260601
  - Shuffle seed:          20260601 (per-pair per-comparison)
  - max_completion_tokens: 1500
  - Response format:       json_schema (strict)
  - Judge prompt:          BYTE-IDENTICAL to v0.1 (same hash)
  - Blind to context:      YES
  - Blind to system ID:    YES (judge sees Answer X / Answer Y only)

Per pre-reg discipline:
  - No context shown to the judge.
  - No system identity shown.
  - Position randomized per (qid, comparison).
  - No answer regeneration; no deterministic relabeling.
  - All failures preserved.

Outputs:
  operational_belief_v2/data/preference_judgments.jsonl
  operational_belief_v2/data/preference_audit.json
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

# Reuse the byte-identical v0.1 judge prompt + schema.
sys.path.insert(0, str(V1_ROOT))
from judge_preference import (  # noqa: E402
    AXES,
    JUDGE_SYSTEM_PROMPT,
    PREF_SCHEMA,
    WINNERS,
)

QUESTIONS_PATH = V1_ROOT / "questions.jsonl"

ANSWER_PATHS = {
    "A":    ROOT / "data" / "answers_a.jsonl",
    "B100": ROOT / "data" / "answers_b100.jsonl",
    "B250": ROOT / "data" / "answers_b250.jsonl",
    "B500": ROOT / "data" / "answers_b500.jsonl",
}

# (comparison_name, system_left, system_right)
# Convention: when reporting win-rates we report system_left's win rate.
COMPARISONS = [
    ("B100_vs_A",     "B100", "A"),     # PRIMARY
    ("B250_vs_A",     "B250", "A"),
    ("B500_vs_A",     "B500", "A"),
    ("B100_vs_B250",  "B100", "B250"),
    ("B100_vs_B500",  "B100", "B500"),
    ("B250_vs_B500",  "B250", "B500"),
]

OUT_JUDGMENTS = ROOT / "data" / "preference_judgments.jsonl"
OUT_AUDIT = ROOT / "data" / "preference_audit.json"

# --- LOCKED JUDGE PARAMETERS (byte-identical to v0.1) -----------------------
JUDGE_MODEL          = "gpt-4.1-2025-04-14"
TEMPERATURE          = 0.0
TOP_P                = 1.0
SEED                 = 20260601
SHUFFLE_SEED         = 20260601
MAX_COMPLETION_TOKENS = 1500
MAX_RETRIES          = 6
RETRY_INITIAL_DELAY  = 4.0

load_dotenv(STORM_ROOT / ".env")


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def load_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(l) for l in path.open()]


def build_user_prompt(q: dict, answer_x: str, answer_y: str) -> str:
    return (
        f"question_id:    {q['question_id']}\n"
        f"category:       {q['category']}\n"
        f"session_id:     {q['session_id']}\n"
        f"turn_idx:       {q['turn_idx']}\n"
        f"\n"
        f"QUESTION:\n{q['question']}\n"
        f"\n"
        f"ANSWER X:\n{answer_x}\n"
        f"\n"
        f"ANSWER Y:\n{answer_y}\n"
    )


def x_is_left_for(qid: str, comparison_name: str) -> bool:
    """Deterministic per-(comparison, qid) position randomization."""
    seeded = random.Random(f"{SHUFFLE_SEED}:{comparison_name}:{qid}")
    return seeded.random() < 0.5


def unmap_winner(winner: str, x_is_left: bool, system_left: str, system_right: str) -> str:
    if winner == "TIE":
        return "TIE"
    if winner == "X":
        return system_left if x_is_left else system_right
    if winner == "Y":
        return system_right if x_is_left else system_left
    return "INVALID"


def load_existing(path: pathlib.Path) -> set[tuple]:
    if not path.exists():
        return set()
    out: set[tuple] = set()
    with path.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            judg = r.get("judgments") or {}
            if all(a in judg and "winner" in judg[a] for a in AXES):
                out.add((r["question_id"], r["comparison"]))
    return out


def judge_one(client: OpenAI, user_prompt: str) -> dict:
    t0 = time.time()
    delay = RETRY_INITIAL_DELAY
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=JUDGE_MODEL,
                temperature=TEMPERATURE,
                top_p=TOP_P,
                seed=SEED,
                max_tokens=MAX_COMPLETION_TOKENS,
                response_format={"type": "json_schema", "json_schema": PREF_SCHEMA},
                messages=[
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
            )
            wall = time.time() - t0
            choice = resp.choices[0]
            content = choice.message.content or ""
            try:
                judgments = json.loads(content) if content else {}
            except json.JSONDecodeError:
                judgments = {}
            return {
                "judgments":          judgments,
                "model_resolved":     resp.model,
                "system_fingerprint": getattr(resp, "system_fingerprint", None),
                "input_tokens":       resp.usage.prompt_tokens,
                "output_tokens":      resp.usage.completion_tokens,
                "finish_reason":      choice.finish_reason,
                "wall_seconds":       wall,
                "retry_attempts":     attempt - 1,
                "raw_content":        content,
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
    answers: dict[str, dict[str, dict]] = {}
    for arm, path in ANSWER_PATHS.items():
        answers[arm] = {r["question_id"]: r for r in load_jsonl(path) if r.get("answer_text")}
        print(f"  {arm}: {len(answers[arm])} answers")

    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    judge_prompt_hash = sha256(JUDGE_SYSTEM_PROMPT)
    print(f"\nLocked judge:")
    print(f"  model:                {JUDGE_MODEL}")
    print(f"  temperature:          {TEMPERATURE}")
    print(f"  top_p:                {TOP_P}")
    print(f"  seed:                 {SEED}")
    print(f"  shuffle_seed:         {SHUFFLE_SEED}")
    print(f"  max_completion_tokens:{MAX_COMPLETION_TOKENS}")
    print(f"  judge_prompt_hash:    {judge_prompt_hash[:16]}...")

    existing = load_existing(OUT_JUDGMENTS)
    print(f"\nResume: {len(existing)} already-judged (qid, comparison) pairs found")

    OUT_JUDGMENTS.parent.mkdir(exist_ok=True)
    fout = OUT_JUDGMENTS.open("a")

    # Build work items: every (comparison, qid) where both sides have answers.
    work_items: list[tuple] = []
    for comparison_name, sys_left, sys_right in COMPARISONS:
        common = sorted(
            set(answers[sys_left]) & set(answers[sys_right]) & set(questions)
        )
        for qid in common:
            work_items.append((comparison_name, sys_left, sys_right, qid))

    total = len(work_items)
    completed = 0
    skipped = 0
    failed = 0
    print(f"\nJudging {total} (qid, comparison) pairs across {len(COMPARISONS)} comparisons...")

    for i, (comp_name, sys_left, sys_right, qid) in enumerate(work_items, 1):
        if (qid, comp_name) in existing:
            skipped += 1
            if i % 50 == 0 or i == total:
                print(f"  [{i}/{total}] skipped: {skipped}, done: {completed}, failed: {failed}", flush=True)
            continue

        q = questions[qid]
        ans_left = answers[sys_left][qid]["answer_text"]
        ans_right = answers[sys_right][qid]["answer_text"]

        x_is_left = x_is_left_for(qid, comp_name)
        answer_x = ans_left if x_is_left else ans_right
        answer_y = ans_right if x_is_left else ans_left

        user_prompt = build_user_prompt(q, answer_x, answer_y)
        prompt_hash = sha256(JUDGE_SYSTEM_PROMPT + "\n---\n" + user_prompt)
        x_hash = sha256(answer_x)
        y_hash = sha256(answer_y)

        try:
            res = judge_one(client, user_prompt)
        except APIError as e:
            failed += 1
            err = {
                "question_id":          qid,
                "comparison":           comp_name,
                "system_left":          sys_left,
                "system_right":         sys_right,
                "category":             q["category"],
                "session_id":           q["session_id"],
                "turn_idx":             q["turn_idx"],
                "judge_model":          JUDGE_MODEL,
                "shuffle_seed":         SHUFFLE_SEED,
                "x_is_left":            x_is_left,
                "judge_prompt_hash":    judge_prompt_hash,
                "prompt_hash":          prompt_hash,
                "answer_x_hash":        x_hash,
                "answer_y_hash":        y_hash,
                "judgments":            {},
                "error":                f"{type(e).__name__}: {str(e)[:300]}",
                "judged_at":            datetime.datetime.utcnow().isoformat() + "Z",
            }
            fout.write(json.dumps(err) + "\n"); fout.flush()
            print(f"  [{i}/{total}] FAILED {qid}/{comp_name}: {type(e).__name__}", flush=True)
            continue

        judgments = res["judgments"]
        if not all(a in judgments for a in AXES):
            failed += 1
            err = {
                "question_id":          qid,
                "comparison":           comp_name,
                "system_left":          sys_left,
                "system_right":         sys_right,
                "category":             q["category"],
                "session_id":           q["session_id"],
                "turn_idx":             q["turn_idx"],
                "judge_model":          JUDGE_MODEL,
                "shuffle_seed":         SHUFFLE_SEED,
                "x_is_left":            x_is_left,
                "judge_prompt_hash":    judge_prompt_hash,
                "prompt_hash":          prompt_hash,
                "answer_x_hash":        x_hash,
                "answer_y_hash":        y_hash,
                "judgments":            judgments,
                "error":                "incomplete_axis_set",
                "raw_content":          res.get("raw_content", "")[:1000],
                "finish_reason":        res["finish_reason"],
                "judged_at":            datetime.datetime.utcnow().isoformat() + "Z",
            }
            fout.write(json.dumps(err) + "\n"); fout.flush()
            print(f"  [{i}/{total}] FAILED {qid}/{comp_name}: incomplete axes", flush=True)
            continue

        # Un-shuffle to (system_left, system_right, TIE)
        unmapped = {a: dict(judgments[a]) for a in AXES}
        for a in AXES:
            unmapped[a]["winner_unmapped"] = unmap_winner(
                judgments[a]["winner"], x_is_left, sys_left, sys_right
            )

        record = {
            "question_id":          qid,
            "comparison":           comp_name,
            "system_left":          sys_left,
            "system_right":         sys_right,
            "category":             q["category"],
            "session_id":           q["session_id"],
            "turn_idx":             q["turn_idx"],
            "judge_model":          JUDGE_MODEL,
            "model_resolved":       res["model_resolved"],
            "system_fingerprint":   res["system_fingerprint"],
            "seed":                 SEED,
            "shuffle_seed":         SHUFFLE_SEED,
            "x_is_left":            x_is_left,
            "judge_prompt_hash":    judge_prompt_hash,
            "prompt_hash":          prompt_hash,
            "answer_x_hash":        x_hash,
            "answer_y_hash":        y_hash,
            "input_tokens":         res["input_tokens"],
            "output_tokens":        res["output_tokens"],
            "finish_reason":        res["finish_reason"],
            "wall_seconds":         res["wall_seconds"],
            "retry_attempts":       res["retry_attempts"],
            "judgments":            unmapped,
            "judged_at":            datetime.datetime.utcnow().isoformat() + "Z",
        }
        fout.write(json.dumps(record) + "\n"); fout.flush()
        completed += 1
        if i % 25 == 0 or i == total:
            print(f"  [{i}/{total}] done: {completed}, skipped: {skipped}, failed: {failed}", flush=True)

    fout.close()

    # --- Aggregate ---------------------------------------------------------
    print()
    print("Re-reading judgments for audit aggregation...")
    all_records = load_jsonl(OUT_JUDGMENTS)
    by_key: dict[tuple, dict] = {}
    for r in all_records:
        if all(a in (r.get("judgments") or {}) for a in AXES):
            by_key[(r["question_id"], r["comparison"])] = r
    print(f"  complete judgments: {len(by_key)} pairs")

    def axis_rates(records: list[dict], axis: str, sys_left: str, sys_right: str) -> dict:
        counts = Counter(r["judgments"][axis].get("winner_unmapped") for r in records)
        n = sum(counts.values())
        return {
            "n":                   n,
            "left_wins":           counts.get(sys_left, 0),
            "right_wins":          counts.get(sys_right, 0),
            "ties":                counts.get("TIE", 0),
            "left_rate":           counts.get(sys_left, 0) / n if n else None,
            "right_rate":          counts.get(sys_right, 0) / n if n else None,
            "tie_rate":            counts.get("TIE", 0) / n if n else None,
        }

    comparison_summary: dict[str, dict] = {}
    for comp_name, sys_left, sys_right in COMPARISONS:
        subset = [
            r for r in by_key.values()
            if r["comparison"] == comp_name
        ]
        per_axis = {
            a: axis_rates(subset, a, sys_left, sys_right) for a in AXES
        }
        # Per-category breakdown
        per_category: dict[str, dict[str, dict]] = defaultdict(dict)
        for cat in sorted(set(r["category"] for r in subset)):
            cat_subset = [r for r in subset if r["category"] == cat]
            for a in AXES:
                per_category[cat][a] = axis_rates(cat_subset, a, sys_left, sys_right)
        comparison_summary[comp_name] = {
            "n":                len(subset),
            "system_left":      sys_left,
            "system_right":     sys_right,
            "per_axis":         per_axis,
            "per_category":     {cat: dict(am) for cat, am in per_category.items()},
        }

    # Position-bias check (raw X vs Y across all axes / all comparisons)
    pos_counts: Counter = Counter()
    for r in by_key.values():
        for a in AXES:
            w = r["judgments"][a].get("winner")
            pos_counts[w] += 1
    total_pos = sum(pos_counts.values())
    position_bias = {
        "X_wins":   pos_counts.get("X", 0),
        "Y_wins":   pos_counts.get("Y", 0),
        "TIE":      pos_counts.get("TIE", 0),
        "X_rate":   pos_counts.get("X", 0) / total_pos if total_pos else None,
        "Y_rate":   pos_counts.get("Y", 0) / total_pos if total_pos else None,
        "TIE_rate": pos_counts.get("TIE", 0) / total_pos if total_pos else None,
        "n":        total_pos,
    }

    audit = {
        "schema_version":           "v0.2.2",
        "stage":                    "operational v0.2.2 preference judging (6 comparisons)",
        "judge_model":              JUDGE_MODEL,
        "model_resolved_distinct":  sorted(set(r.get("model_resolved") for r in by_key.values() if r.get("model_resolved"))),
        "temperature":              TEMPERATURE,
        "top_p":                    TOP_P,
        "seed":                     SEED,
        "shuffle_seed":             SHUFFLE_SEED,
        "judge_prompt_hash":        judge_prompt_hash,
        "judge_prompt_byte_identical_to_v0_1": True,
        "axes":                     AXES,
        "blind_to_context":         True,
        "blind_to_system_identity": True,
        "comparisons":              [
            {"name": n, "system_left": l, "system_right": r}
            for n, l, r in COMPARISONS
        ],
        "input_files": {
            "questions": str(QUESTIONS_PATH),
            "answers":   {arm: str(p) for arm, p in ANSWER_PATHS.items()},
        },
        "output_file":              str(OUT_JUDGMENTS),
        "pairs_total":              total,
        "pairs_complete":           len(by_key),
        "this_run":                 {"completed": completed, "skipped": skipped, "failed": failed},
        "comparison_summary":       comparison_summary,
        "position_bias_check":      position_bias,
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"Wrote {OUT_AUDIT}")

    # Pretty-print
    print()
    print("=" * 88)
    print("PREFERENCE JUDGMENT SUMMARY")
    print("=" * 88)
    for comp_name, sys_left, sys_right in COMPARISONS:
        s = comparison_summary[comp_name]
        print(f"\n  {comp_name}  (n={s['n']})  [{sys_left} vs {sys_right}]")
        print(f"    {'axis':28s}    {sys_left+'_wins':>10s}   {sys_right+'_wins':>10s}   {'TIE':>6s}")
        for a in AXES:
            r = s["per_axis"][a]
            lw = (r["left_rate"] or 0) * 100
            rw = (r["right_rate"] or 0) * 100
            tw = (r["tie_rate"] or 0) * 100
            print(
                f"    {a:28s}    "
                f"{r['left_wins']:3d} ({lw:>4.0f}%)   "
                f"{r['right_wins']:3d} ({rw:>4.0f}%)   "
                f"{r['ties']:3d} ({tw:>4.0f}%)"
            )

    print()
    print("Position-bias check (raw X vs Y wins across all axes / all comparisons):")
    print(f"  X (first slot):  {position_bias['X_wins']:4d} ({(position_bias['X_rate'] or 0)*100:.1f}%)")
    print(f"  Y (second slot): {position_bias['Y_wins']:4d} ({(position_bias['Y_rate'] or 0)*100:.1f}%)")
    print(f"  TIE:             {position_bias['TIE']:4d} ({(position_bias['TIE_rate'] or 0)*100:.1f}%)")
    print(f"  total judgments: {position_bias['n']:4d}")


if __name__ == "__main__":
    main()
