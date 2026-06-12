#!/usr/bin/env python3
"""
F-023 Phase 2 step 1: stratified random sample.

Per PHASE2_PRE_REGISTRATION_v0.1.md §4:
  - Universe: all 83,271 normalized turns
  - Seed: 20260529
  - Method: stratified by session, uniform without replacement
  - Cap: min(200, n_turns_in_session) per session
  - Expected eval size: ~1,000–2,000 turns

Output:
  data/phase2_sample.json — list of {session_id, turn_idx, uuid, timestamp} records
"""

from __future__ import annotations

import json
import pathlib
import random
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent
IN_PATH = ROOT / "data" / "sessions_classified.jsonl"
OUT_PATH = ROOT / "data" / "phase2_sample.json"

SEED = 20260529
CAP_PER_SESSION = 200
RULES_VERSION = "v0.1"


def main() -> None:
    # Group turn indices by session
    by_session: dict[str, list[dict]] = defaultdict(list)
    with IN_PATH.open() as f:
        for line in f:
            try:
                t = json.loads(line)
            except json.JSONDecodeError:
                continue
            by_session[t["session_id"]].append({
                "session_id":    t["session_id"],
                "turn_idx":      t["turn_idx"],
                "uuid":          t["uuid"],
                "timestamp":     t.get("timestamp", ""),
                "l1_region":     t.get("l1_region", "UNCLASSIFIED"),
                "role":          t.get("role"),
                "has_error":     any(tr.get("is_error") for tr in (t.get("tool_results") or [])),
            })

    rng = random.Random(SEED)
    sample: list[dict] = []
    per_session_counts: dict[str, dict] = {}

    for sid in sorted(by_session.keys()):
        turns = by_session[sid]
        n_session = len(turns)
        cap = min(CAP_PER_SESSION, n_session)
        if cap == n_session:
            chosen = list(turns)
        else:
            chosen = rng.sample(turns, cap)
        # Sort chosen by turn_idx so downstream code can stream in order
        chosen.sort(key=lambda r: r["turn_idx"])
        sample.extend(chosen)
        per_session_counts[sid] = {"n_total": n_session, "n_sampled": cap}

    out = {
        "rules_version":      RULES_VERSION,
        "seed":               SEED,
        "cap_per_session":    CAP_PER_SESSION,
        "n_sessions":         len(by_session),
        "n_sampled":          len(sample),
        "n_universe":         sum(len(v) for v in by_session.values()),
        "per_session_counts": per_session_counts,
        "sample":             sample,
    }
    OUT_PATH.write_text(json.dumps(out, indent=2))

    print(f"Wrote {OUT_PATH}")
    print(f"  universe:         {out['n_universe']:,} turns")
    print(f"  sessions:         {out['n_sessions']}")
    print(f"  sampled:          {out['n_sampled']:,} turns")
    print(f"  cap per session:  {CAP_PER_SESSION}")
    print(f"  seed:             {SEED}")


if __name__ == "__main__":
    main()
