#!/usr/bin/env python3
"""
Stack-Grounded Retrieval v0.1 — Preference judging (Phase B step 3d).

For each of 75 questions, presents the paired (System A, System B) answers
to a locked preference judge in randomized order. The judge returns a winner
(X / Y / TIE) plus rationale + confidence for each of 3 pre-registered axes:
  1. caution
  2. traceability
  3. sensemaking_usefulness

The script un-shuffles the X/Y winner back to A/B for aggregation.

LOCKED v0.1 preference-judge parameters:
  - Model:                gpt-4.1-2025-04-14
  - Model family vs generator and deterministic judge:
                          - generator:    gpt-4o-2024-08-06
                          - det judge:    gpt-5-mini-2025-08-07
                          - pref judge:   gpt-4.1-2025-04-14  (three-way separation)
  - Temperature:          0.0
  - top_p:                1.0
  - Seed:                 20260531
  - Position randomization seed: 20260531 (same; deterministic shuffle)
  - max_completion_tokens: 1500
  - Response format:      json_schema (strict typing)
  - Blind to context:     YES — the judge sees only (question, ticker, cutoff,
                          category, Answer X, Answer Y). Neither context
                          (chunks vs beliefs) is shown to the judge. This
                          removes the "context format looks better" bias and
                          mirrors how a downstream reader of just-the-answer
                          would judge.
  - System identity hidden: the judge sees "Answer X" and "Answer Y" only;
                          the X-A or X-B mapping is recorded out-of-band per
                          pair so we can un-shuffle for aggregation.

Outputs:
  stack_grounded_v1/data/preference_judgments.jsonl
  stack_grounded_v1/data/preference_audit.json
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
ANSWERS_A      = ROOT / "data" / "answers_a.jsonl"
ANSWERS_B      = ROOT / "data" / "answers_b.jsonl"
ANSWERS_C1     = ROOT / "data" / "answers_c1.jsonl"
OUT_JUDGMENTS  = ROOT / "data" / "preference_judgments.jsonl"
OUT_AUDIT      = ROOT / "data" / "preference_audit.json"

# Comparison pairs. v0.1 had only (A, B). C1 adds two more pairwise comparisons.
# Records are tagged with a `comparison` field so the audit can group them.
# Resume key = (question_id, comparison) so each pair is judged at most once
# per (question, comparison).
COMPARISONS = [
    ("A_vs_B",  "A",  ANSWERS_A,  "B",  ANSWERS_B),    # v0.1, already judged
    ("A_vs_C1", "A",  ANSWERS_A,  "C1", ANSWERS_C1),   # post-v0.1 sensitivity
    ("B_vs_C1", "B",  ANSWERS_B,  "C1", ANSWERS_C1),   # post-v0.1 sensitivity
]

# --- LOCKED v0.1 PREFERENCE-JUDGE PARAMETERS --------------------------------
JUDGE_MODEL              = "gpt-4.1-2025-04-14"
TEMPERATURE              = 0.0
TOP_P                    = 1.0
SEED                     = 20260531
SHUFFLE_SEED             = 20260531
MAX_COMPLETION_TOKENS    = 1500
MAX_RETRIES              = 6
RETRY_INITIAL_DELAY      = 4.0

AXES = ["caution", "traceability", "sensemaking_usefulness"]
WINNERS = ["X", "Y", "TIE"]

JUDGE_SYSTEM_PROMPT = """You are a preference judge comparing two answers to the same question. The two answers come from different information-retrieval systems. The system identities are HIDDEN — you see only "Answer X" and "Answer Y", in randomized order.

For each of THREE axes, choose which answer is better, or TIE if they are equivalent.

THE THREE AXES:

1. CAUTION
   Which answer better calibrates its confidence to what it can actually support? An answer that hedges, qualifies, or declines when warrant is thin scores higher. An answer that overclaims when warrant is weak scores lower. A clean decline ("the available information does not support a confident answer") is high-caution. A clean assertion with strong specific evidence is also high-caution. Confidently asserting without specific evidence is LOW caution.

2. TRACEABILITY
   Which answer makes its claims more verifiable? An answer that cites specific dated events, named items, or identifiable references scores higher. An answer that makes vague general claims with no anchors scores lower. The question is whether a downstream reader could go check the underlying evidence based on the answer's specifics.

3. SENSEMAKING_USEFULNESS
   Which answer better helps the reader understand the state of the world the question asks about? Useful does not mean longer or more confident — it means more accurate orientation for someone who needs to make a decision. An answer that organizes the relevant signal, distinguishes current from past, and surfaces the load-bearing distinctions scores higher.

For each axis, return: winner ("X" / "Y" / "TIE"), rationale (1-2 sentences), confidence (0.0-1.0).

GUIDANCE:
- Judge each axis independently. Different axes can have different winners.
- Use TIE when the answers are genuinely equivalent on that axis, not as a default for hard calls.
- Do not let answer length influence preference. Longer is not better; shorter is not more cautious.
- Do not infer system identity from style. Different styles do not imply different systems.

Return the JSON object directly. Do not add commentary outside the JSON."""


def _axis_props():
    return {
        "type": "object",
        "properties": {
            "winner":     {"type": "string", "enum": WINNERS},
            "rationale":  {"type": "string"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
        "required": ["winner", "rationale", "confidence"],
        "additionalProperties": False,
    }


PREF_SCHEMA = {
    "name": "preference_judgments",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {a: _axis_props() for a in AXES},
        "required": list(AXES),
        "additionalProperties": False,
    },
}

load_dotenv(STORM_ROOT / ".env")


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def load_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(l) for l in path.open()]


def build_user_prompt(q: dict, answer_x: str, answer_y: str) -> str:
    return (
        f"question_id:    {q['question_id']}\n"
        f"ticker:         {q['ticker']}\n"
        f"category:       {q['category']}\n"
        f"evidence_cutoff: {q['evidence_cutoff']}\n"
        f"\n"
        f"QUESTION:\n{q['question']}\n"
        f"\n"
        f"ANSWER X:\n{answer_x}\n"
        f"\n"
        f"ANSWER Y:\n{answer_y}\n"
    )


def load_existing(path: pathlib.Path) -> dict[tuple, dict]:
    """
    Resume map keyed on (question_id, comparison) so each comparison pair is
    judged at most once per question. Legacy v0.1 records that lack a
    `comparison` field are treated as A_vs_B (the only v0.1 comparison).
    """
    if not path.exists():
        return {}
    out: dict[tuple, dict] = {}
    with path.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            judg = r.get("judgments") or {}
            if all(a in judg and "winner" in judg[a] for a in AXES):
                comparison = r.get("comparison", "A_vs_B")
                out[(r["question_id"], comparison)] = r
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


def unmap_winner(winner: str, x_is_left: bool, left_label: str, right_label: str) -> str:
    """
    Map judge's X/Y/TIE back to the actual system labels based on the recorded
    shuffle. left_label and right_label are the two systems being compared;
    if x_is_left is True, X = left_label, Y = right_label.
    """
    if winner == "TIE":
        return "TIE"
    if winner == "X":
        return left_label if x_is_left else right_label
    if winner == "Y":
        return right_label if x_is_left else left_label
    return "INVALID"


def main() -> None:
    print("Loading inputs...")
    questions = {q["question_id"]: q for q in load_jsonl(QUESTIONS_PATH)}
    # Cache per-system answer maps so they're loaded once
    answer_cache: dict[pathlib.Path, dict] = {}
    def get_answers(path: pathlib.Path) -> dict:
        if path not in answer_cache:
            if not path.exists():
                answer_cache[path] = {}
            else:
                answer_cache[path] = {r["question_id"]: r for r in load_jsonl(path) if r.get("answer_text")}
        return answer_cache[path]

    print(f"  questions: {len(questions)}")

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

    # Lock the per-pair position shuffle: deterministic from SHUFFLE_SEED + qid
    # + comparison so each comparison gets its own balanced randomization.
    def x_is_left_for(qid: str, comparison: str) -> bool:
        seeded = random.Random(f"{SHUFFLE_SEED}:{comparison}:{qid}")
        return seeded.random() < 0.5

    existing = load_existing(OUT_JUDGMENTS)
    print(f"\nResume: {len(existing)} already-judged (qid, comparison) pairs found")

    OUT_JUDGMENTS.parent.mkdir(exist_ok=True)
    fout = OUT_JUDGMENTS.open("a")

    total_completed = 0
    total_skipped = 0
    total_failed = 0

    for comparison, left_label, left_path, right_label, right_path in COMPARISONS:
        left_ans = get_answers(left_path)
        right_ans = get_answers(right_path)
        common = sorted(set(left_ans) & set(right_ans) & set(questions))
        if not common:
            print(f"\n=== {comparison}: no overlapping pairs to judge, skipping ===")
            continue
        print(f"\n=== {comparison}: {len(common)} candidate pairs ===")

        completed = 0
        skipped = 0
        failed = 0
        for i, qid in enumerate(common, 1):
            if (qid, comparison) in existing:
                skipped += 1
                if i % 25 == 0 or i == len(common):
                    print(f"  [{comparison} {i}/{len(common)}] skipped: {skipped}, done: {completed}, failed: {failed}", flush=True)
                continue

            q = questions[qid]
            ans_left = left_ans[qid]["answer_text"]
            ans_right = right_ans[qid]["answer_text"]

            x_is_left = x_is_left_for(qid, comparison)
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
                    "comparison":           comparison,
                    "left_label":           left_label,
                    "right_label":          right_label,
                    "category":             q["category"],
                    "ticker":               q["ticker"],
                    "evidence_cutoff":      q["evidence_cutoff"],
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
                print(f"  [{comparison} {i}/{len(common)}] FAILED {qid}: {type(e).__name__}", flush=True)
                continue

            judgments = res["judgments"]
            if not all(a in judgments for a in AXES):
                failed += 1
                err = {
                    "question_id":          qid,
                    "comparison":           comparison,
                    "left_label":           left_label,
                    "right_label":          right_label,
                    "category":             q["category"],
                    "ticker":               q["ticker"],
                    "evidence_cutoff":      q["evidence_cutoff"],
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
                print(f"  [{comparison} {i}/{len(common)}] FAILED {qid}: incomplete axes", flush=True)
                continue

            # Un-shuffle to actual system labels at write time
            unmapped = {a: dict(judgments[a]) for a in AXES}
            for a in AXES:
                unmapped[a]["winner_unmapped"] = unmap_winner(
                    judgments[a]["winner"], x_is_left, left_label, right_label
                )

            record = {
                "question_id":          qid,
                "comparison":           comparison,
                "left_label":           left_label,
                "right_label":          right_label,
                "category":             q["category"],
                "ticker":               q["ticker"],
                "evidence_cutoff":      q["evidence_cutoff"],
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
            if i % 10 == 0 or i == len(common):
                print(f"  [{comparison} {i}/{len(common)}] done: {completed}, skipped: {skipped}, failed: {failed}", flush=True)

        total_completed += completed
        total_skipped += skipped
        total_failed += failed

    fout.close()
    completed = total_completed
    skipped = total_skipped
    failed = total_failed

    # --- Aggregate ---------------------------------------------------------
    print()
    print("Re-reading judgments for audit aggregation...")
    all_records = load_jsonl(OUT_JUDGMENTS)
    # Now keyed by (qid, comparison). Legacy v0.1 records lacking 'comparison'
    # are treated as A_vs_B.
    by_pair: dict[tuple, dict] = {}
    for r in all_records:
        if all(a in (r.get("judgments") or {}) for a in AXES):
            comparison = r.get("comparison", "A_vs_B")
            by_pair[(r["question_id"], comparison)] = r
    print(f"  complete judgments: {len(by_pair)} (qid, comparison) pairs")

    # Per-axis rates per comparison: count winner_unmapped values
    def axis_rates(records, axis):
        counts = Counter(r["judgments"][axis].get("winner_unmapped") for r in records)
        n = sum(counts.values())
        out = {"n": n}
        for label in counts:
            out[label] = counts[label]
            out[f"{label}_rate"] = counts[label] / n if n else None
        return out

    comparisons_seen = sorted(set(r.get("comparison", "A_vs_B") for r in by_pair.values()))
    per_comparison_per_axis: dict[str, dict[str, dict]] = {}
    for comp in comparisons_seen:
        subset = [r for r in by_pair.values() if r.get("comparison", "A_vs_B") == comp]
        per_comparison_per_axis[comp] = {a: axis_rates(subset, a) for a in AXES}

    per_comparison_per_category_per_axis: dict[str, dict[str, dict[str, dict]]] = {}
    for comp in comparisons_seen:
        per_comparison_per_category_per_axis[comp] = {}
        comp_records = [r for r in by_pair.values() if r.get("comparison", "A_vs_B") == comp]
        for cat in sorted(set(r["category"] for r in comp_records)):
            subset = [r for r in comp_records if r["category"] == cat]
            per_comparison_per_category_per_axis[comp][cat] = {a: axis_rates(subset, a) for a in AXES}

    # Position-bias check per comparison
    position_bias_per_comparison: dict[str, dict] = {}
    for comp in comparisons_seen:
        comp_records = [r for r in by_pair.values() if r.get("comparison", "A_vs_B") == comp]
        pos_counts = Counter()
        for r in comp_records:
            for a in AXES:
                pos_counts[r["judgments"][a].get("winner")] += 1
        total_pos = sum(pos_counts.values())
        position_bias_per_comparison[comp] = {
            "X_wins": pos_counts.get("X", 0),
            "Y_wins": pos_counts.get("Y", 0),
            "TIE":    pos_counts.get("TIE", 0),
            "X_rate": pos_counts.get("X", 0) / total_pos if total_pos else None,
            "Y_rate": pos_counts.get("Y", 0) / total_pos if total_pos else None,
        }

    # Example judgments per (comparison, axis): preserve a few per direction
    examples: dict[str, dict[str, dict]] = {}
    for comp in comparisons_seen:
        examples[comp] = {}
        comp_records = [r for r in by_pair.values() if r.get("comparison", "A_vs_B") == comp]
        for a in AXES:
            buckets: dict[str, list] = defaultdict(list)
            for r in comp_records:
                w = r["judgments"][a].get("winner_unmapped")
                entry = {
                    "question_id":  r["question_id"],
                    "category":     r["category"],
                    "ticker":       r["ticker"],
                    "rationale":    r["judgments"][a]["rationale"][:300],
                    "confidence":   r["judgments"][a]["confidence"],
                }
                if len(buckets[w]) < 4:
                    buckets[w].append(entry)
            examples[comp][a] = dict(buckets)

    audit = {
        "schema_version":           "v0.1+c1",
        "stage":                    "Phase B step 3d (preference) + post-v0.1 C1 preference",
        "judge_model":              JUDGE_MODEL,
        "model_resolved_distinct":  sorted(set(r.get("model_resolved") for r in by_pair.values() if r.get("model_resolved"))),
        "temperature":              TEMPERATURE,
        "top_p":                    TOP_P,
        "seed":                     SEED,
        "shuffle_seed":             SHUFFLE_SEED,
        "judge_prompt_hash":        judge_prompt_hash,
        "judge_prompt":             JUDGE_SYSTEM_PROMPT,
        "axes":                     AXES,
        "blind_to_context":         True,
        "comparisons_configured":   [c[0] for c in COMPARISONS],
        "comparisons_in_audit":     comparisons_seen,
        "input_files": {
            "questions":  str(QUESTIONS_PATH),
            "per_comparison": [
                {"comparison": c[0], "left_label": c[1], "left_path": str(c[2]), "right_label": c[3], "right_path": str(c[4])}
                for c in COMPARISONS
            ],
        },
        "output_file":              str(OUT_JUDGMENTS),
        "pairs_complete":           len(by_pair),
        "pairs_complete_per_comparison": {comp: sum(1 for r in by_pair.values() if r.get("comparison","A_vs_B")==comp) for comp in comparisons_seen},
        "this_run":                 {"completed": completed, "skipped": skipped, "failed": failed},
        "per_comparison_per_axis":  per_comparison_per_axis,
        "per_comparison_per_category_per_axis": per_comparison_per_category_per_axis,
        "position_bias_check_per_comparison": position_bias_per_comparison,
        "examples_per_comparison_per_axis": examples,
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"Wrote {OUT_AUDIT}")

    print()
    print("=" * 72)
    print("PREFERENCE JUDGMENT SUMMARY")
    print("=" * 72)
    for comp in comparisons_seen:
        n = sum(1 for r in by_pair.values() if r.get("comparison","A_vs_B")==comp)
        left, right = comp.split("_vs_")
        print(f"\n  [{comp}] (n={n})")
        print(f"  {'axis':30s}  {left:5s}_wins  {right:5s}_wins  TIE")
        for a in AXES:
            d = per_comparison_per_axis[comp][a]
            l_n = d.get(left, 0); r_n = d.get(right, 0); t_n = d.get("TIE", 0)
            l_r = d.get(f"{left}_rate") or 0
            r_r = d.get(f"{right}_rate") or 0
            t_r = d.get("TIE_rate") or 0
            print(f"  {a:30s}  {l_n:3d}({l_r*100:.0f}%)   {r_n:3d}({r_r*100:.0f}%)   {t_n:3d}({t_r*100:.0f}%)")
        pb = position_bias_per_comparison[comp]
        if pb.get('X_rate') is not None:
            print(f"  position bias: X={pb['X_wins']}({pb['X_rate']*100:.0f}%)  Y={pb['Y_wins']}({pb['Y_rate']*100:.0f}%)  TIE={pb['TIE']}")


if __name__ == "__main__":
    main()
