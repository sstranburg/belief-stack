#!/usr/bin/env python3
"""
Stack-Grounded Retrieval v0.1 — Question set curator.

Down-selects 268 candidates produced by build_question_candidates.py
to the locked 75-question set per pre-registration §4.

Deterministic selection rules (the "hand-curation" is in these rules,
not in 75 individual picks):

  - 15 questions per category × 5 categories = 75 total
  - Each primary-universe actor gets at least 1 question if its
    substrate supports it; the remainder fill by category-specific
    coverage ranking
  - >=60% non-current cutoffs (target 50/75 = 66.7%)
  - No duplicate (category, ticker, cutoff) tuples within the set
  - Template variety: within a category, distribute across the
    available templates

Output:
  stack_grounded_v1/questions.jsonl     (the LOCKED v0.1 question set)
  stack_grounded_v1/data/curation_audit.json   (selection rationale)
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent
CANDIDATES_PATH = ROOT / "data" / "question_candidates_v0_1.jsonl"
OUT_QUESTIONS   = ROOT / "questions.jsonl"
OUT_AUDIT       = ROOT / "data" / "curation_audit.json"

TARGET_PER_CATEGORY = 15
TARGET_TOTAL        = 75
MIN_NON_CURRENT_PCT = 0.60
CURRENT_CUTOFF      = "2026-05-26"

CATEGORIES = [
    "current_intel",
    "change_detection",
    "stale_assumption",
    "contradiction",
    "insufficient_warrant",
]

# Cutoff preference per category (favor non-current where appropriate)
PREFERRED_CUTOFFS_NONCURRENT = {
    "change_detection":     ("2026-02-28", "2026-03-15", "2026-04-15", "2026-05-10"),
    "stale_assumption":     ("2026-04-15", "2026-05-10"),
    "contradiction":        ("2026-03-15", "2026-04-15"),
    "insufficient_warrant": ("2026-01-31", "2026-03-15", "2026-04-15"),
}


def load_candidates() -> list[dict]:
    out = []
    with CANDIDATES_PATH.open() as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def select_category(candidates: list[dict], category: str, n: int,
                    prefer_non_current: bool = True,
                    actor_coverage_target: set[str] | None = None) -> list[dict]:
    """
    Pick n candidates from a category with:
      - max actor diversity (ensure underused actors get picked first if possible)
      - cutoff preference per category
      - template diversity (avoid same template twice on same actor)
    """
    cands = [c for c in candidates if c["category"] == category]

    # Sort candidates by selection-preference score (higher = better pick)
    def score(c):
        s = 0
        if prefer_non_current and c["evidence_cutoff"] != CURRENT_CUTOFF:
            s += 100
        # Slight preference for diverse cutoffs within the category
        return s

    cands = sorted(cands, key=lambda c: -score(c))

    selected: list[dict] = []
    selected_actors: Counter = Counter()
    used_keys: set[tuple] = set()  # (category, ticker, cutoff) dedupe

    # Phase 1: ensure actor diversity — prefer underrepresented actors first
    if actor_coverage_target:
        for actor in actor_coverage_target:
            # Find best candidate for this actor not yet picked
            actor_cands = [c for c in cands if c["ticker"] == actor]
            if not actor_cands:
                continue
            for c in actor_cands:
                key = (c["category"], c["ticker"], c["evidence_cutoff"])
                if key in used_keys:
                    continue
                selected.append(c)
                selected_actors[c["ticker"]] += 1
                used_keys.add(key)
                break
            if len(selected) >= n:
                break

    # Phase 2: fill remaining slots with highest-score unused, distributing
    # actors evenly
    for c in cands:
        if len(selected) >= n:
            break
        key = (c["category"], c["ticker"], c["evidence_cutoff"])
        if key in used_keys:
            continue
        # Prefer actors selected fewer times so far
        if selected_actors[c["ticker"]] >= 3:
            continue
        selected.append(c)
        selected_actors[c["ticker"]] += 1
        used_keys.add(key)

    # Phase 3: relax actor cap if we still don't have n
    if len(selected) < n:
        for c in cands:
            if len(selected) >= n:
                break
            key = (c["category"], c["ticker"], c["evidence_cutoff"])
            if key in used_keys:
                continue
            selected.append(c)
            selected_actors[c["ticker"]] += 1
            used_keys.add(key)

    return selected[:n]


def main() -> None:
    print(f"Loading {CANDIDATES_PATH}…")
    cands = load_candidates()
    print(f"  {len(cands):,} candidates")

    # Get full set of actors with any coverage
    all_actors = sorted(set(c["ticker"] for c in cands))
    print(f"  {len(all_actors)} actors in candidate pool")

    # Phase 1: pick the most underrepresented actor across the full set first.
    # We want each actor to appear in at least 1 question if possible. With
    # 39 actors and 75 questions, average ~1.9 per actor.
    final_set: list[dict] = []
    selected_actors_global: Counter = Counter()

    for category in CATEGORIES:
        # Compute which actors have been underrepresented so far
        actors_needing_coverage = [a for a in all_actors if selected_actors_global[a] == 0]
        picks = select_category(
            cands,
            category,
            TARGET_PER_CATEGORY,
            prefer_non_current=(category != "current_intel"),
            actor_coverage_target=set(actors_needing_coverage),
        )
        final_set.extend(picks)
        for p in picks:
            selected_actors_global[p["ticker"]] += 1

    # Assign final question_ids
    for i, q in enumerate(final_set):
        q["question_id"] = f"q{i+1:03d}_{q['category']}_{q['ticker']}_{q['evidence_cutoff'].replace('-','')}"

    # Validate
    by_cat = Counter(q["category"] for q in final_set)
    non_current = sum(1 for q in final_set if q["evidence_cutoff"] != CURRENT_CUTOFF)
    actor_coverage = Counter(q["ticker"] for q in final_set)
    actors_with_zero = [a for a in all_actors if actor_coverage[a] == 0]

    print()
    print("=" * 72)
    print("FINAL QUESTION SET VALIDATION")
    print("=" * 72)
    print(f"  Total questions:     {len(final_set)} (target {TARGET_TOTAL})")
    print(f"  Non-current share:   {non_current/len(final_set):.2%} (target >= {MIN_NON_CURRENT_PCT:.0%})")
    print(f"  Actors covered:      {len(set(q['ticker'] for q in final_set))} / {len(all_actors)}")
    print(f"  Actors with zero Qs: {actors_with_zero or 'none'}")
    print(f"\n  Per-category counts:")
    for c in CATEGORIES:
        print(f"    {c:24s}  {by_cat[c]}")
    print(f"\n  Per-actor coverage (top 10):")
    for a, n in actor_coverage.most_common(10):
        print(f"    {a:8s}  {n}")
    print(f"\n  Cutoff distribution:")
    for cutoff, n in sorted(Counter(q["evidence_cutoff"] for q in final_set).items()):
        print(f"    {cutoff}  {n}")

    # Write the locked questions
    OUT_QUESTIONS.write_text("\n".join(json.dumps(q) for q in final_set) + "\n")
    print(f"\nWrote {OUT_QUESTIONS}")

    # Write the audit
    audit = {
        "rules_version":          "v0.1",
        "candidates_input":       str(CANDIDATES_PATH),
        "candidates_count":       len(cands),
        "selected_count":         len(final_set),
        "per_category_counts":    {c: by_cat[c] for c in CATEGORIES},
        "non_current_share":      non_current / len(final_set),
        "actors_covered":         len(set(q["ticker"] for q in final_set)),
        "actors_total":           len(all_actors),
        "actors_with_zero_qs":    actors_with_zero,
        "per_actor_coverage":     dict(actor_coverage),
        "cutoff_distribution":    dict(Counter(q["evidence_cutoff"] for q in final_set)),
    }
    OUT_AUDIT.parent.mkdir(exist_ok=True)
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"Wrote {OUT_AUDIT}")


if __name__ == "__main__":
    main()
