#!/usr/bin/env python3
"""
Operational Belief v0.1 — Preference judging.

For each of the 73 paired questions (where both A and B have answers),
presents the two answers in randomized order to a locked preference
judge. Judge returns a winner (X / Y / TIE) plus rationale + confidence
for each of 2 pre-registered axes:
  1. traceability
  2. appropriate_caution

The script un-shuffles X/Y back to A/B for aggregation.

LOCKED v0.1 preference-judge parameters:
  - Model:                gpt-4.1-2025-04-14
  - Family separation:    generator=gpt-4o, det judge=gpt-5-mini, pref judge=gpt-4.1
  - Temperature:          0.0
  - top_p:                1.0
  - Seed:                 20260601
  - Shuffle seed:         20260601 (per-pair position randomization)
  - max_completion_tokens: 1500
  - Response format:      json_schema (strict)
  - Blind to context:     YES — judge sees only (question, ticker, cutoff,
                          category, Answer X, Answer Y)
  - System identity hidden: judge sees "Answer X" / "Answer Y"; X→A/B
                          mapping recorded out-of-band per pair

Excluded from judging: q047 and q061 (System B has no answer due to
TPM cap; see ANSWER_GENERATION_NOTES.md §5). These are generation/
feasibility failures, not preference losses — reported separately.

Outputs:
  operational_belief_v1/data/preference_judgments.jsonl
  operational_belief_v1/data/preference_audit.json
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

QUESTIONS_PATH = ROOT / "questions.jsonl"
ANSWERS_A      = ROOT / "data" / "answers_a.jsonl"
ANSWERS_B      = ROOT / "data" / "answers_b.jsonl"
OUT_JUDGMENTS  = ROOT / "data" / "preference_judgments.jsonl"
OUT_AUDIT      = ROOT / "data" / "preference_audit.json"

# --- LOCKED v0.1 PREFERENCE-JUDGE PARAMETERS --------------------------------
JUDGE_MODEL              = "gpt-4.1-2025-04-14"
TEMPERATURE              = 0.0
TOP_P                    = 1.0
SEED                     = 20260601
SHUFFLE_SEED             = 20260601
MAX_COMPLETION_TOKENS    = 1500
MAX_RETRIES              = 6
RETRY_INITIAL_DELAY      = 4.0

AXES = ["traceability", "appropriate_caution"]
WINNERS = ["X", "Y", "TIE"]

JUDGE_SYSTEM_PROMPT = """You are a preference judge comparing two answers to the same question. The two answers come from different information-retrieval systems. The system identities are HIDDEN — you see only "Answer X" and "Answer Y", in randomized order.

The question is about operational state in a long-running LLM-assistant workflow (validation, repeated failure, action authorization, completion, or readiness). The answers describe what the assistant believes about the workflow state at a specific point in time.

For each of TWO axes, choose which answer is better, or TIE if they are equivalent.

THE TWO AXES:

1. TRACEABILITY
   Which answer makes its claims more verifiable? An answer that cites specific turn numbers, belief identifiers, tool output references, or named operational state scores higher. An answer that makes vague general claims with no anchors scores lower. The question is whether a downstream reader could go check the underlying evidence based on the answer's specifics.

2. APPROPRIATE_CAUTION
   Which answer pauses, declines, or qualifies when the operational state is unresolved? An answer that correctly recognizes a pending state and recommends waiting, asking for clarification, or holding off scores higher. An answer that proceeds confidently under ambiguous state scores lower. A CLEAN DECLINE ("the context does not support this answer") is high-caution. CONFIDENT OVERCLAIM under thin state is low-caution.

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
    "name": "operational_preference_judgments",
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


def load_existing(path: pathlib.Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with path.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            judg = r.get("judgments") or {}
            if all(a in judg and "winner" in judg[a] for a in AXES):
                out[r["question_id"]] = r
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


def unmap_winner(winner: str, x_is_a: bool) -> str:
    if winner == "TIE":
        return "TIE"
    if winner == "X":
        return "A" if x_is_a else "B"
    if winner == "Y":
        return "B" if x_is_a else "A"
    return "INVALID"


def main() -> None:
    print("Loading inputs...")
    questions = {q["question_id"]: q for q in load_jsonl(QUESTIONS_PATH)}
    answers_a = {r["question_id"]: r for r in load_jsonl(ANSWERS_A) if r.get("answer_text")}
    answers_b = {r["question_id"]: r for r in load_jsonl(ANSWERS_B) if r.get("answer_text")}
    # Paired set: only questions where BOTH systems have answers
    common = sorted(set(answers_a) & set(answers_b) & set(questions))
    missing_b = sorted(set(answers_a) - set(answers_b))
    print(f"  paired set (both A and B have answers): {len(common)}")
    print(f"  excluded from preference judging (B missing): {missing_b}")

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

    # Deterministic per-pair shuffle from SHUFFLE_SEED + qid
    def x_is_a_for(qid: str) -> bool:
        seeded = random.Random(f"{SHUFFLE_SEED}:{qid}")
        return seeded.random() < 0.5

    existing = load_existing(OUT_JUDGMENTS)
    print(f"\nResume: {len(existing)} already-judged pairs found")

    OUT_JUDGMENTS.parent.mkdir(exist_ok=True)
    fout = OUT_JUDGMENTS.open("a")

    total = len(common)
    completed = 0
    skipped = 0
    failed = 0

    for i, qid in enumerate(common, 1):
        if qid in existing:
            skipped += 1
            if i % 20 == 0 or i == total:
                print(f"  [{i}/{total}] skipped: {skipped}, done: {completed}, failed: {failed}", flush=True)
            continue

        q = questions[qid]
        ans_a = answers_a[qid]["answer_text"]
        ans_b = answers_b[qid]["answer_text"]

        x_is_a = x_is_a_for(qid)
        answer_x = ans_a if x_is_a else ans_b
        answer_y = ans_b if x_is_a else ans_a

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
                "category":             q["category"],
                "session_id":           q["session_id"],
                "turn_idx":             q["turn_idx"],
                "judge_model":          JUDGE_MODEL,
                "shuffle_seed":         SHUFFLE_SEED,
                "x_is_a":               x_is_a,
                "judge_prompt_hash":    judge_prompt_hash,
                "prompt_hash":          prompt_hash,
                "answer_x_hash":        x_hash,
                "answer_y_hash":        y_hash,
                "judgments":            {},
                "error":                f"{type(e).__name__}: {str(e)[:300]}",
                "judged_at":            datetime.datetime.utcnow().isoformat() + "Z",
            }
            fout.write(json.dumps(err) + "\n"); fout.flush()
            print(f"  [{i}/{total}] FAILED {qid}: {type(e).__name__}", flush=True)
            continue

        judgments = res["judgments"]
        if not all(a in judgments for a in AXES):
            failed += 1
            err = {
                "question_id":          qid,
                "category":             q["category"],
                "session_id":           q["session_id"],
                "turn_idx":             q["turn_idx"],
                "judge_model":          JUDGE_MODEL,
                "shuffle_seed":         SHUFFLE_SEED,
                "x_is_a":               x_is_a,
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
            print(f"  [{i}/{total}] FAILED {qid}: incomplete axes", flush=True)
            continue

        # Un-shuffle to A/B at write time
        unmapped = {a: dict(judgments[a]) for a in AXES}
        for a in AXES:
            unmapped[a]["winner_unmapped"] = unmap_winner(judgments[a]["winner"], x_is_a)

        record = {
            "question_id":          qid,
            "category":             q["category"],
            "session_id":           q["session_id"],
            "turn_idx":             q["turn_idx"],
            "judge_model":          JUDGE_MODEL,
            "model_resolved":       res["model_resolved"],
            "system_fingerprint":   res["system_fingerprint"],
            "seed":                 SEED,
            "shuffle_seed":         SHUFFLE_SEED,
            "x_is_a":               x_is_a,
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
        if i % 10 == 0 or i == total:
            print(f"  [{i}/{total}] done: {completed}, skipped: {skipped}, failed: {failed}", flush=True)

    fout.close()

    # --- Aggregate ---------------------------------------------------------
    print()
    print("Re-reading judgments for audit aggregation...")
    all_records = load_jsonl(OUT_JUDGMENTS)
    by_qid: dict[str, dict] = {}
    for r in all_records:
        if all(a in (r.get("judgments") or {}) for a in AXES):
            by_qid[r["question_id"]] = r
    print(f"  complete judgments: {len(by_qid)} pairs")

    def axis_rates(records, axis):
        counts = Counter(r["judgments"][axis].get("winner_unmapped") for r in records)
        n = sum(counts.values())
        return {
            "n":     n,
            "A":     counts.get("A", 0),
            "B":     counts.get("B", 0),
            "TIE":   counts.get("TIE", 0),
            "A_rate":   counts.get("A", 0) / n if n else None,
            "B_rate":   counts.get("B", 0) / n if n else None,
            "TIE_rate": counts.get("TIE", 0) / n if n else None,
        }

    per_axis = {a: axis_rates(list(by_qid.values()), a) for a in AXES}

    per_category: dict[str, dict[str, dict]] = defaultdict(dict)
    for cat in sorted(set(r["category"] for r in by_qid.values())):
        subset = [r for r in by_qid.values() if r["category"] == cat]
        for a in AXES:
            per_category[cat][a] = axis_rates(subset, a)

    # Position-bias check
    pos_counts = Counter()
    for r in by_qid.values():
        for a in AXES:
            w = r["judgments"][a].get("winner")
            pos_counts[w] += 1
    total_pos = sum(pos_counts.values())
    pos_bias = {
        "X_wins":   pos_counts.get("X", 0),
        "Y_wins":   pos_counts.get("Y", 0),
        "TIE":      pos_counts.get("TIE", 0),
        "X_rate":   pos_counts.get("X", 0) / total_pos if total_pos else None,
        "Y_rate":   pos_counts.get("Y", 0) / total_pos if total_pos else None,
    }

    # Example judgments per axis (A wins / B wins / TIE)
    examples_by_axis: dict[str, dict] = {}
    for a in AXES:
        ex = {"A_wins": [], "B_wins": [], "TIE": []}
        for r in by_qid.values():
            unmapped_winner = r["judgments"][a].get("winner_unmapped")
            entry = {
                "question_id":  r["question_id"],
                "category":     r["category"],
                "rationale":    r["judgments"][a]["rationale"][:300],
                "confidence":   r["judgments"][a]["confidence"],
            }
            key = "A_wins" if unmapped_winner == "A" else "B_wins" if unmapped_winner == "B" else "TIE"
            if len(ex[key]) < 4:
                ex[key].append(entry)
        examples_by_axis[a] = ex

    audit = {
        "schema_version":           "v0.1",
        "stage":                    "operational v0.1 preference judging",
        "judge_model":              JUDGE_MODEL,
        "model_resolved_distinct":  sorted(set(r.get("model_resolved") for r in by_qid.values() if r.get("model_resolved"))),
        "temperature":              TEMPERATURE,
        "top_p":                    TOP_P,
        "seed":                     SEED,
        "shuffle_seed":             SHUFFLE_SEED,
        "judge_prompt_hash":        judge_prompt_hash,
        "judge_prompt":             JUDGE_SYSTEM_PROMPT,
        "axes":                     AXES,
        "blind_to_context":         True,
        "blind_to_system_identity": True,
        "input_files": {
            "questions":  str(QUESTIONS_PATH),
            "answers_a":  str(ANSWERS_A),
            "answers_b":  str(ANSWERS_B),
        },
        "output_file":              str(OUT_JUDGMENTS),
        "pairs_total":              total,
        "pairs_complete":           len(by_qid),
        "excluded_from_preference_due_to_b_missing": missing_b,
        "this_run":                 {"completed": completed, "skipped": skipped, "failed": failed},
        "per_axis":                 per_axis,
        "per_category_per_axis":    {cat: dict(am) for cat, am in per_category.items()},
        "position_bias_check":      pos_bias,
        "examples_by_axis":         examples_by_axis,
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"Wrote {OUT_AUDIT}")

    # Pretty summary
    print()
    print("=" * 72)
    print("PREFERENCE JUDGMENT SUMMARY (paired n=73; q047 & q061 excluded)")
    print("=" * 72)
    print(f"  {'axis':30s}  A_wins   B_wins   TIE")
    for a in AXES:
        d = per_axis[a]
        ar = (d['A_rate'] or 0) * 100
        br = (d['B_rate'] or 0) * 100
        tr = (d['TIE_rate'] or 0) * 100
        print(f"  {a:30s}  {d['A']:3d}({ar:.0f}%)  {d['B']:3d}({br:.0f}%)  {d['TIE']:3d}({tr:.0f}%)")
    print()
    print(f"Position-bias check (raw X vs Y wins across all axes):")
    print(f"  X (first slot):  {pos_bias['X_wins']:3d} ({(pos_bias['X_rate'] or 0)*100:.0f}%)")
    print(f"  Y (second slot): {pos_bias['Y_wins']:3d} ({(pos_bias['Y_rate'] or 0)*100:.0f}%)")
    print(f"  TIE:             {pos_bias['TIE']:3d}")


if __name__ == "__main__":
    main()
