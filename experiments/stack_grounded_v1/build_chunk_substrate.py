#!/usr/bin/env python3
"""
Stack-Grounded Retrieval v0.1 — Chunk substrate builder (System A payload).

Reads ONLY the raw L0 evidence stream and emits a flat per-event chunk file.
No derived/* belief artifacts are consulted. Each chunk preserves the source
event_id so System B's belief objects can reference the same identifiers
(evidence_refs join back into this file).

Cutoff compatibility:
  Each chunk records its `timestamp`. The context builder (later phase)
  filters to {chunk.timestamp <= evidence_cutoff} at query time per
  pre-reg §5.2. This script does NOT pre-filter by question cutoff.

Inputs:
  data/normalized/tech_ecosystem.jsonl

Outputs:
  stack_grounded_v1/data/chunk_substrate.jsonl
  stack_grounded_v1/data/chunk_substrate_audit.json
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter

ROOT       = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent
EVENTS_PATH    = STORM_ROOT / "data" / "normalized" / "tech_ecosystem.jsonl"
OUT_CHUNKS     = ROOT / "data" / "chunk_substrate.jsonl"
OUT_AUDIT      = ROOT / "data" / "chunk_substrate_audit.json"

WINDOW_START = "2025-12-05"
WINDOW_END   = "2026-05-26"

# Primary universe — identical to build_question_candidates.py per pre-reg §2.1.
# Hardcoded configuration, not derived from any belief artifact.
PRIMARY_TICKERS = sorted([
    "NVDA", "TSM", "AMD", "INTC", "ARM", "AVGO", "ASML", "MU", "MRVL",
    "SNDK", "WDC", "ALAB", "MSFT", "META", "GOOGL", "PLTR", "AMZN", "ORCL",
    "SMCI", "DELL", "ANET", "NBIS", "VRT", "VST", "COHR", "CLS", "CEG",
    "CRM", "ADBE", "DDOG", "SNOW", "TTD", "MELI", "NFLX", "TSLA", "AAPL",
    "SOFI", "CRWV", "ZETA",
])
PRIMARY_SET = set(PRIMARY_TICKERS)


def in_window(ts: str) -> bool:
    return WINDOW_START <= ts[:10] <= WINDOW_END


def main() -> None:
    print(f"Reading {EVENTS_PATH}...")
    total = 0
    out_chunks: list[dict] = []
    seen_ids: set[str] = set()
    skip_no_id = 0
    skip_dup = 0
    skip_window = 0
    skip_no_primary_actor = 0
    skip_bad_json = 0
    skip_bad_ts = 0

    with EVENTS_PATH.open() as f:
        for line in f:
            total += 1
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                skip_bad_json += 1
                continue

            ts = e.get("timestamp")
            if not ts or len(ts) < 10:
                skip_bad_ts += 1
                continue
            if not in_window(ts):
                skip_window += 1
                continue

            actors_all = e.get("actors") or []
            actors_primary = [a for a in actors_all if a in PRIMARY_SET]
            if not actors_primary:
                skip_no_primary_actor += 1
                continue

            ev_id = e.get("event_id")
            if not ev_id:
                skip_no_id += 1
                continue
            if ev_id in seen_ids:
                skip_dup += 1
                continue
            seen_ids.add(ev_id)

            chunk = {
                "chunk_id":    ev_id,
                "timestamp":   ts,
                "source":      e.get("source", ""),
                "title":       (e.get("title") or "").strip(),
                "text":        (e.get("text") or "").strip(),
                "actors":      actors_all,           # full actor list preserved
                "actors_primary": actors_primary,    # intersection with universe
                "tags":        e.get("tags") or [],
                "url":         e.get("url", ""),
                "reliability": e.get("reliability"),
            }
            out_chunks.append(chunk)

    print(f"  read {total:,} events; kept {len(out_chunks):,} chunks")

    # Sort by timestamp for stable diffs and ergonomic inspection
    out_chunks.sort(key=lambda c: (c["timestamp"], c["chunk_id"]))

    # Validation counts
    by_source  = Counter(c["source"] for c in out_chunks)
    by_actor   = Counter()
    by_month   = Counter()
    empty_text = 0
    empty_title = 0
    for c in out_chunks:
        for a in c["actors_primary"]:
            by_actor[a] += 1
        by_month[c["timestamp"][:7]] += 1
        if not c["text"]:
            empty_text += 1
        if not c["title"]:
            empty_title += 1

    actors_with_zero = sorted(a for a in PRIMARY_TICKERS if by_actor[a] == 0)

    print()
    print("=" * 72)
    print("CHUNK SUBSTRATE VALIDATION")
    print("=" * 72)
    print(f"  Chunks emitted:       {len(out_chunks):,}")
    print(f"  Unique chunk_ids:     {len(seen_ids):,}")
    print(f"  Window:               {WINDOW_START} .. {WINDOW_END}")
    print(f"  Actors covered:       {len([a for a in PRIMARY_TICKERS if by_actor[a] > 0])} / {len(PRIMARY_TICKERS)}")
    print(f"  Actors with zero:     {actors_with_zero or 'none'}")
    print(f"  Empty title:          {empty_title}")
    print(f"  Empty text:           {empty_text}")
    print(f"\n  Source breakdown:")
    for src, n in by_source.most_common():
        print(f"    {src:12s}  {n:6,}")
    print(f"\n  Month breakdown:")
    for mo, n in sorted(by_month.items()):
        print(f"    {mo}      {n:6,}")
    print(f"\n  Exclusions:")
    print(f"    bad json:            {skip_bad_json}")
    print(f"    bad timestamp:       {skip_bad_ts}")
    print(f"    out of window:       {skip_window}")
    print(f"    no primary actor:    {skip_no_primary_actor}")
    print(f"    missing event_id:    {skip_no_id}")
    print(f"    duplicate event_id:  {skip_dup}")

    # Write outputs
    OUT_CHUNKS.parent.mkdir(exist_ok=True)
    with OUT_CHUNKS.open("w") as f:
        for c in out_chunks:
            f.write(json.dumps(c) + "\n")
    print(f"\nWrote {OUT_CHUNKS}")

    audit = {
        "schema_version":    "v0.1",
        "input":              str(EVENTS_PATH),
        "window_start":       WINDOW_START,
        "window_end":         WINDOW_END,
        "primary_universe":   PRIMARY_TICKERS,
        "events_total_read":  total,
        "chunks_emitted":     len(out_chunks),
        "unique_chunk_ids":   len(seen_ids),
        "actors_total":       len(PRIMARY_TICKERS),
        "actors_covered":     len([a for a in PRIMARY_TICKERS if by_actor[a] > 0]),
        "actors_with_zero":   actors_with_zero,
        "per_actor_counts":   {a: by_actor[a] for a in PRIMARY_TICKERS},
        "source_breakdown":   dict(by_source),
        "month_breakdown":    dict(sorted(by_month.items())),
        "empty_title":        empty_title,
        "empty_text":         empty_text,
        "exclusions": {
            "bad_json":            skip_bad_json,
            "bad_timestamp":       skip_bad_ts,
            "out_of_window":       skip_window,
            "no_primary_actor":    skip_no_primary_actor,
            "missing_event_id":    skip_no_id,
            "duplicate_event_id":  skip_dup,
        },
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"Wrote {OUT_AUDIT}")


if __name__ == "__main__":
    main()
