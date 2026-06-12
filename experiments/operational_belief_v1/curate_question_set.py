#!/usr/bin/env python3
"""
Operational Belief v0.1 — Question curator (step 5c, part 2).

Reads candidates from build_question_candidates.py, calls the scorer
(score_operational_label.py) for applicability + oracle classification,
and freezes the 75-question set per the locked §4.5 selection rules.

Reading order matters:
  - Candidate question TEXT was generated blind to the belief substrate
    (in build_question_candidates.py).
  - The scorer IS allowed to read operational_beliefs.jsonl (and the
    upstream TKOS artifacts) because it is the ORACLE — its job is to
    produce ground truth.
  - The curator calls the scorer per candidate to filter / balance.
    The curator does NOT read operational_beliefs.jsonl directly.

Locked selection rules (§4.5):
  - 15 questions per category × 5 categories = 75 total
  - Max 3 questions per session
  - Turn-position: ≤25% early, ≥50% middle, 15-35% late
  - Per-category balance: 5 positive / 5 mixed / 5 negative oracle
    (hard floor: ≥3 negatives)
  - Deterministic selection from a seeded shuffle

Outputs:
  operational_belief_v1/questions.jsonl
  operational_belief_v1/data/question_construction_audit.json
"""

from __future__ import annotations

import json
import pathlib
import random
from collections import Counter, defaultdict

from score_operational_label import Scorer

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent

IN_CANDIDATES = ROOT / "data" / "question_candidates_v0_1.jsonl"
OUT_QUESTIONS = ROOT / "questions.jsonl"
OUT_AUDIT     = ROOT / "data" / "question_construction_audit.json"

# Locked targets per §4.5
TARGET_PER_CATEGORY = 15
TARGET_TOTAL        = 75
POSITIVE_TARGET     = 5
NEGATIVE_TARGET     = 5
MIXED_TARGET        = 5
NEGATIVE_FLOOR      = 3
PER_SESSION_CAP     = 3
SEED                = 20260601

# Turn-position bucket targets per category (15 questions per category)
TARGET_EARLY = 4   # ≤25%
TARGET_MID   = 8   # ≥50%
TARGET_LATE  = 3   # 15-35%
# (4 + 8 + 3 = 15)

CATEGORIES = [
    "validation_check",
    "repeated_failure",
    "approval_status",
    "completion_check",
    "readiness_check",
]


def load_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(l) for l in path.open()]


def main() -> None:
    print("Loading candidates...")
    candidates = load_jsonl(IN_CANDIDATES)
    print(f"  {len(candidates):,} candidates")

    print("\nLoading scorer (this opens TKOS substrates + operational_beliefs)...")
    scorer = Scorer()

    print("\nApplying scorer to all candidates...")
    # Bucket: category -> oracle_class ("POSITIVE", "NEGATIVE", "NA") -> turn_bucket -> session_id -> [candidate+scorer_result]
    bucketed: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))
    applicable_count = 0
    na_count = 0
    for c in candidates:
        res = scorer.score(c["session_id"], c["turn_idx"], c["category"])
        if res.applicability != "APPLICABLE":
            na_count += 1
            continue
        applicable_count += 1
        oracle_cls = res.oracle_class  # "POSITIVE" | "NEGATIVE"
        bucket = c["turn_position_bucket"]
        bucketed[c["category"]][oracle_cls][bucket][c["session_id"]].append({
            "candidate": c,
            "scorer": res,
        })
    print(f"  applicable: {applicable_count:,}; NA: {na_count:,}")

    # Diagnostic before selection
    print("\nApplicable distribution per category × oracle_class:")
    for cat in CATEGORIES:
        pos = sum(len(s) for b in bucketed[cat]["POSITIVE"].values() for s in [b.values()])
        # Actually count per-session lists flattened
        pos = sum(len(lst) for b in bucketed[cat]["POSITIVE"].values() for lst in b.values())
        neg = sum(len(lst) for b in bucketed[cat]["NEGATIVE"].values() for lst in b.values())
        print(f"  {cat:22s}  positive={pos:5d}  negative={neg:5d}")

    # Deterministic shuffle for selection
    rng = random.Random(SEED)

    # ---- Selection ---------------------------------------------------------
    # For each category, pick TARGET_PER_CATEGORY questions with:
    #   - oracle balance target (POS: 5, NEG: 5, MIXED: 5)
    #   - hard floor: NEG ≥ 3
    #   - turn-position target: 4 early / 8 middle / 3 late
    #   - per-session cap globally
    #
    # If targets cannot be hit under locked rules, surface deviation in audit.

    selected: list[dict] = []
    session_count: Counter = Counter()
    deviations: dict = {}

    def try_pick_one(cat: str, oracle_cls: str, bucket: str, exclude_sessions: set[str]) -> dict | None:
        """Pick one candidate from the (cat, oracle_cls, bucket) bin, respecting per-session cap."""
        for_bin = bucketed[cat][oracle_cls].get(bucket, {})
        # Shuffle session ids deterministically
        sids = sorted(for_bin.keys())
        rng.shuffle(sids)
        for sid in sids:
            if session_count[sid] >= PER_SESSION_CAP:
                continue
            if sid in exclude_sessions:
                continue
            pool = for_bin[sid]
            if not pool:
                continue
            # Deterministic pick within session
            pool_sorted = sorted(pool, key=lambda x: x["candidate"]["turn_idx"])
            rng.shuffle(pool_sorted)
            picked = pool_sorted[0]
            # Remove from pool so we don't double-pick
            for_bin[sid] = [p for p in pool if p["candidate"]["candidate_id"] != picked["candidate"]["candidate_id"]]
            return picked
        return None

    def try_pick_any_bucket(cat: str, oracle_cls: str) -> dict | None:
        """Pick from any bucket if specific bucket targets can't be hit."""
        for bucket in ("middle", "late", "early"):  # preference order
            picked = try_pick_one(cat, oracle_cls, bucket, set())
            if picked:
                return picked
        return None

    for cat in CATEGORIES:
        cat_selected: list[dict] = []
        cat_picked_buckets: Counter = Counter()
        oracle_targets = {"POSITIVE": POSITIVE_TARGET, "NEGATIVE": NEGATIVE_TARGET}
        oracle_picked: Counter = Counter()

        # Pass 1: hit each oracle class up to its target
        for oracle_cls, target in oracle_targets.items():
            for _ in range(target):
                # Try preferred bucket first (round-robin: middle, then any)
                # Pick the bucket that has the most need
                preferred_bucket = None
                if cat_picked_buckets.get("middle", 0) < TARGET_MID:
                    preferred_bucket = "middle"
                elif cat_picked_buckets.get("early", 0) < TARGET_EARLY:
                    preferred_bucket = "early"
                elif cat_picked_buckets.get("late", 0) < TARGET_LATE:
                    preferred_bucket = "late"

                picked = None
                if preferred_bucket:
                    picked = try_pick_one(cat, oracle_cls, preferred_bucket, set())
                if picked is None:
                    picked = try_pick_any_bucket(cat, oracle_cls)
                if picked is None:
                    break
                cat_selected.append(picked)
                cat_picked_buckets[picked["candidate"]["turn_position_bucket"]] += 1
                oracle_picked[oracle_cls] += 1
                session_count[picked["candidate"]["session_id"]] += 1

        # Pass 2: fill the "mixed" slots with whichever class has more remaining
        remaining = TARGET_PER_CATEGORY - len(cat_selected)
        for _ in range(remaining):
            # Pick class with more candidates available
            pos_avail = sum(len(lst) for b in bucketed[cat]["POSITIVE"].values() for lst in b.values())
            neg_avail = sum(len(lst) for b in bucketed[cat]["NEGATIVE"].values() for lst in b.values())
            cls = "POSITIVE" if pos_avail >= neg_avail else "NEGATIVE"
            preferred_bucket = None
            if cat_picked_buckets.get("middle", 0) < TARGET_MID:
                preferred_bucket = "middle"
            elif cat_picked_buckets.get("early", 0) < TARGET_EARLY:
                preferred_bucket = "early"
            elif cat_picked_buckets.get("late", 0) < TARGET_LATE:
                preferred_bucket = "late"
            picked = None
            if preferred_bucket:
                picked = try_pick_one(cat, cls, preferred_bucket, set())
            if picked is None:
                picked = try_pick_any_bucket(cat, cls)
            if picked is None:
                # Try the other class
                alt = "NEGATIVE" if cls == "POSITIVE" else "POSITIVE"
                picked = try_pick_any_bucket(cat, alt)
                if picked is None:
                    break
                cls = alt
            cat_selected.append(picked)
            cat_picked_buckets[picked["candidate"]["turn_position_bucket"]] += 1
            oracle_picked[cls] += 1
            session_count[picked["candidate"]["session_id"]] += 1

        # Record deviations
        if len(cat_selected) < TARGET_PER_CATEGORY:
            deviations.setdefault(cat, {})["short_count"] = TARGET_PER_CATEGORY - len(cat_selected)
        if oracle_picked.get("NEGATIVE", 0) < NEGATIVE_FLOOR:
            deviations.setdefault(cat, {})["below_negative_floor"] = {
                "got":      oracle_picked.get("NEGATIVE", 0),
                "floor":    NEGATIVE_FLOOR,
            }
        for bucket, target in (("early", TARGET_EARLY), ("middle", TARGET_MID), ("late", TARGET_LATE)):
            if cat_picked_buckets.get(bucket, 0) < target:
                deviations.setdefault(cat, {}).setdefault("bucket_shortfall", {})[bucket] = {
                    "got":    cat_picked_buckets.get(bucket, 0),
                    "target": target,
                }

        selected.extend(cat_selected)

    # ---- Assign final question_ids and write ------------------------------
    selected.sort(key=lambda x: (x["candidate"]["category"], x["candidate"]["session_id"], x["candidate"]["turn_idx"]))
    final_questions = []
    for i, item in enumerate(selected, 1):
        c = item["candidate"]
        r = item["scorer"]
        qid = f"q{i:03d}_{c['category']}_{c['session_id'].split('::')[-1][:8]}_T{c['turn_idx']}"
        final_questions.append({
            "question_id":          qid,
            "session_id":           c["session_id"],
            "turn_idx":             c["turn_idx"],
            "category":             c["category"],
            "question":             c["question"],
            "turn_position_bucket": c["turn_position_bucket"],
            "session_total_turns":  c["session_total_turns"],
            "expected_failure_mode": r.metric,
            "oracle_class":         r.oracle_class,
            "oracle_state":         r.oracle_state,
            "ground_truth_resolution": {
                "type":              "programmatic_plus_judge",
                "supporting_turns":  r.supporting_turns,
                "counterevidence_turns": r.counterevidence_turns,
                "rationale":         r.rationale,
            },
        })

    OUT_QUESTIONS.write_text("\n".join(json.dumps(q) for q in final_questions) + "\n")
    print(f"\nWrote {OUT_QUESTIONS}  ({len(final_questions)} questions)")

    # ---- §4.6 Sampling diagnostic ------------------------------------------
    sessions_represented = sorted(set(q["session_id"] for q in final_questions))
    cat_counts = Counter(q["category"] for q in final_questions)
    oracle_counts = defaultdict(Counter)
    bucket_dist = defaultdict(Counter)
    per_session_max = Counter(q["session_id"] for q in final_questions).most_common(1)[0][1] if final_questions else 0
    for q in final_questions:
        oracle_counts[q["category"]][q["oracle_class"]] += 1
        bucket_dist[q["category"]][q["turn_position_bucket"]] += 1

    # Excluded sessions
    phase2_sids = set()
    try:
        ps = json.loads((STORM_ROOT / "tkos_log_replay" / "data" / "phase2_sample.json").read_text())
        phase2_sids = set(ps["per_session_counts"].keys())
    except Exception:
        pass
    eligible_total = len(phase2_sids)
    excluded = []
    for sid in sorted(phase2_sids):
        if sid not in sessions_represented:
            # Determine why
            reason = "no_qualifying_turn"  # default
            cands_for_sid = [c for c in candidates if c["session_id"] == sid]
            if not cands_for_sid:
                reason = "no_candidates_generated"
            else:
                # Did any candidate from this session get to APPLICABLE?
                # We can't know without re-running scorer here; use a heuristic:
                # if there ARE candidates but none made it into final selected,
                # report "cap_filled" or "lost_to_balance"
                reason = "lost_to_selection (candidates existed but per-category quota / balance preempted)"
            excluded.append({"session_id": sid, "exclusion_reason": reason})

    audit = {
        "schema_version":         "v0.1",
        "stage":                  "step 5c: question construction",
        "seed":                   SEED,
        "construction_inputs_opened": [
            "tkos_log_replay/data/sessions_normalized.jsonl",
            "tkos_log_replay/data/reasoning_ledger.jsonl",
            "tkos_log_replay/data/phase2_sample.json",
            "operational_belief_v1/data/question_candidates_v0_1.jsonl",
            # scorer's reads (oracle side; allowed):
            "operational_belief_v1/data/operational_beliefs.jsonl  [via scorer for eligibility/balance only]",
            "tkos_log_replay/data/phase2_belief_timelines.jsonl  [via scorer]",
        ],
        "construction_inputs_FORBIDDEN_during_text_generation": [
            "operational_belief_v1/data/operational_beliefs.jsonl  [used ONLY by scorer for eligibility/balance — NEVER by question-text generator]",
            "tkos_log_replay/data/phase2_belief_timelines.jsonl  [same]",
        ],
        "sessions_eligible":      eligible_total,
        "sessions_represented":   len(sessions_represented),
        "sessions_represented_ids": sessions_represented,
        "excluded_sessions":      excluded,
        "category_counts":        dict(cat_counts),
        "per_session_max":        per_session_max,
        "per_session_cap":        PER_SESSION_CAP,
        "turn_position_distribution": {cat: dict(bucket_dist[cat]) for cat in CATEGORIES},
        "per_category_balance_buckets": {
            cat: {
                "positive": oracle_counts[cat].get("POSITIVE", 0),
                "negative": oracle_counts[cat].get("NEGATIVE", 0),
            }
            for cat in CATEGORIES
        },
        "positive_negative_oracle_balance_per_metric": {
            cat: {
                "positive_count": oracle_counts[cat].get("POSITIVE", 0),
                "negative_count": oracle_counts[cat].get("NEGATIVE", 0),
                "negative_floor": NEGATIVE_FLOOR,
                "meets_negative_floor": oracle_counts[cat].get("NEGATIVE", 0) >= NEGATIVE_FLOOR,
            }
            for cat in CATEGORIES
        },
        "deviations_from_targets": deviations,
        "totals": {
            "questions_emitted":        len(final_questions),
            "questions_target":         TARGET_TOTAL,
            "candidates_total":         len(candidates),
            "candidates_applicable":    applicable_count,
            "candidates_NA":            na_count,
        },
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"Wrote {OUT_AUDIT}")

    # Pretty summary
    print()
    print("=" * 78)
    print("QUESTION SET CONSTRUCTION SUMMARY")
    print("=" * 78)
    print(f"  Questions emitted:       {len(final_questions)} / {TARGET_TOTAL}")
    print(f"  Sessions represented:    {len(sessions_represented)} / {eligible_total}")
    print(f"  Per-session max:         {per_session_max} (cap {PER_SESSION_CAP})")
    print()
    print(f"  {'category':22s}  count  pos  neg  early/mid/late")
    for cat in CATEGORIES:
        n = cat_counts.get(cat, 0)
        p = oracle_counts[cat].get("POSITIVE", 0)
        ng = oracle_counts[cat].get("NEGATIVE", 0)
        e = bucket_dist[cat].get("early", 0)
        m = bucket_dist[cat].get("middle", 0)
        l = bucket_dist[cat].get("late", 0)
        print(f"  {cat:22s}  {n:3d}    {p:2d}   {ng:2d}   {e}/{m}/{l}")
    if deviations:
        print(f"\n  ⚠ Deviations from targets:")
        for cat, dev in deviations.items():
            print(f"    {cat}: {dev}")


if __name__ == "__main__":
    main()
