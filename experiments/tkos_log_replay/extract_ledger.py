#!/usr/bin/env python3
"""
F-023 Phase 1 step 5: extract the reasoning ledger.

Reads classified turns from `sessions_classified.jsonl` and emits a
ledger of (label, warrant) records — one per turn that was classified
to a region (UNCLASSIFIED turns are omitted from the ledger to keep
the substrate ordered, addressable, provenance-bearing, and tractable).

Warrants conform to the v0.1 schema pinned at
https://topicspace.ai/schemas/warrant-v0.1.json. Belief Stack v0.1 spec:
https://topicspace.ai/research/belief-stack.

Warrant policy (PRE-REGISTERED, locked with rules v0.1):

  All turns in this substrate emit invariant warrants. The rationale:
  each turn's claim is structural — the assistant ran a command, the
  command produced a tool_result, the result either succeeded or
  failed. Decay over wall-clock time is not the right model for
  per-turn engineering operations; the warrant either validates
  against the observed tool result, or it does not.

  Decaying warrants apply later (Phase 2/3) to STATE-LEVEL beliefs
  carried across turns — "the pipeline is running," "the user is
  away," "the deploy is pending" — which DO age and require
  reconciliation. Per-turn operations are invariant.

Warrant fields per turn:
  - schema_version:     "warrant-v0.1"
  - warrant_type:       "invariant"
  - birth_timestamp:    turn timestamp
  - support_n:          number of tool_uses + tool_results carrying the claim
  - coverage_status:    IN_DISTRIBUTION if region != UNCLASSIFIED
  - evidence_refs:      [session_id, uuid, tool_use_ids ...]
  - validation_status:  PASS if no tool errors, FAIL if any error, UNKNOWN if no tools

Output:
  data/reasoning_ledger.jsonl       — full per-turn ledger
  data/reasoning_ledger_summary.json — aggregate stats
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter
from typing import Iterable

IN_PATH  = pathlib.Path(__file__).resolve().parent / "data" / "sessions_classified.jsonl"
OUT_PATH = pathlib.Path(__file__).resolve().parent / "data" / "reasoning_ledger.jsonl"
SUM_PATH = pathlib.Path(__file__).resolve().parent / "data" / "reasoning_ledger_summary.json"

SCHEMA_VERSION = "warrant-v0.1"
LEDGER_VERSION = "v0.1"


def make_warrant(turn: dict) -> dict:
    """Build a v0.1 invariant warrant for a turn."""
    tool_uses = turn.get("tool_uses", []) or []
    tool_results = turn.get("tool_results", []) or []
    n_tools = len(tool_uses) + len(tool_results)

    # support_n: at least 1 (the turn itself); n_tools when there are tool
    # interactions backing the claim
    support_n = max(1, n_tools)

    # validation_status from tool_result outcomes
    if not tool_results:
        validation_status = "UNKNOWN"
    elif any(tr.get("is_error") for tr in tool_results):
        validation_status = "FAIL"
    else:
        validation_status = "PASS"

    # evidence_refs: ledger pointers back into the substrate
    evidence_refs = [
        f"session:{turn['session_id']}",
        f"uuid:{turn['uuid']}",
    ]
    for tu in tool_uses:
        if tu.get("tool_use_id"):
            evidence_refs.append(f"tool_use:{tu['tool_use_id']}")

    coverage = "IN_DISTRIBUTION" if turn["l1_region"] != "UNCLASSIFIED" else "UNCLASSIFIED"

    return {
        "schema_version":    SCHEMA_VERSION,
        "warrant_type":      "invariant",
        "birth_timestamp":   turn.get("timestamp", ""),
        "support_n":         support_n,
        "coverage_status":   coverage,
        "evidence_refs":     evidence_refs,
        "validation_status": validation_status,
    }


def make_ledger_entry(turn: dict) -> dict:
    """Build a single (label, warrant) ledger record from a classified turn."""
    return {
        "session_id":     turn["session_id"],
        "turn_idx":       turn["turn_idx"],
        "uuid":           turn["uuid"],
        "timestamp":      turn.get("timestamp", ""),
        "role":           turn["role"],
        "label": {
            "operation_type":   turn["l1_region"],
            "match_reason":     turn.get("l1_reason", ""),
            "rules_version":    turn.get("rules_version", LEDGER_VERSION),
        },
        "warrant":        make_warrant(turn),
        # Substrate metadata for replay / inspection
        "tool_uses_count":    len(turn.get("tool_uses", []) or []),
        "tool_results_count": len(turn.get("tool_results", []) or []),
        "has_error":          any(tr.get("is_error") for tr in (turn.get("tool_results") or [])),
        "is_meta":            turn.get("is_meta", False),
        "cwd":                turn.get("cwd"),
        "git_branch":         turn.get("git_branch"),
    }


def iter_turns(path: pathlib.Path) -> Iterable[dict]:
    with path.open() as f:
        for line in f:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def main() -> None:
    n_total = 0
    n_classified = 0
    n_unclassified = 0
    region_counts: Counter = Counter()
    validation_counts: Counter = Counter()
    coverage_counts: Counter = Counter()

    # Per-session ledger entry counts
    per_session: dict = {}

    with OUT_PATH.open("w") as out_f:
        for turn in iter_turns(IN_PATH):
            n_total += 1
            entry = make_ledger_entry(turn)
            out_f.write(json.dumps(entry) + "\n")

            region = entry["label"]["operation_type"]
            region_counts[region] += 1
            if region == "UNCLASSIFIED":
                n_unclassified += 1
            else:
                n_classified += 1
            validation_counts[entry["warrant"]["validation_status"]] += 1
            coverage_counts[entry["warrant"]["coverage_status"]] += 1

            sid = entry["session_id"]
            per_session.setdefault(sid, {"n_entries": 0, "n_classified": 0, "n_failed": 0})
            per_session[sid]["n_entries"] += 1
            if region != "UNCLASSIFIED":
                per_session[sid]["n_classified"] += 1
            if entry["warrant"]["validation_status"] == "FAIL":
                per_session[sid]["n_failed"] += 1

    summary = {
        "ledger_version":     LEDGER_VERSION,
        "schema_version":     SCHEMA_VERSION,
        "input":              str(IN_PATH),
        "n_total_entries":    n_total,
        "n_classified":       n_classified,
        "n_unclassified":     n_unclassified,
        "classified_pct":     round(n_classified / n_total * 100, 2) if n_total else 0.0,
        "region_counts":      dict(region_counts.most_common()),
        "validation_status":  dict(validation_counts.most_common()),
        "coverage_status":    dict(coverage_counts.most_common()),
        "n_sessions":         len(per_session),
        "per_session":        per_session,
    }
    SUM_PATH.write_text(json.dumps(summary, indent=2))

    print(f"Wrote {OUT_PATH}  ({n_total:,} ledger entries)")
    print(f"Wrote {SUM_PATH}")
    print()
    print("=" * 72)
    print("REASONING LEDGER SUMMARY (v0.1)")
    print("=" * 72)
    print(f"  Total entries:        {n_total:,}")
    print(f"  Classified:           {n_classified:,}  ({n_classified/n_total*100:.1f}%)")
    print(f"  Unclassified:         {n_unclassified:,}  ({n_unclassified/n_total*100:.1f}%)")
    print()
    print("  Validation status breakdown (per-turn warrant):")
    for status in ("PASS", "FAIL", "UNKNOWN"):
        n = validation_counts.get(status, 0)
        print(f"    {status:<10s} {n:>8,}  ({n/n_total*100:.1f}%)")
    print()
    print("  Coverage status breakdown:")
    for status, n in coverage_counts.most_common():
        print(f"    {status:<22s} {n:>8,}  ({n/n_total*100:.1f}%)")

    # Sessions with highest failure surfaces
    print()
    print("  Sessions with most FAIL warrants:")
    sorted_sessions = sorted(per_session.items(), key=lambda kv: -kv[1]["n_failed"])[:10]
    for sid, info in sorted_sessions:
        if info["n_failed"] == 0: continue
        print(f"    {sid[:48]:<48s} entries={info['n_entries']:>5} fails={info['n_failed']:>4}")


if __name__ == "__main__":
    main()
