#!/usr/bin/env python3
"""
Stack-Grounded Retrieval v0.1 — Belief substrate builder (System B payload).

Reads TopicSpace pipeline outputs and emits one belief object per
expectation entity, conforming to the locked schema in pre-reg §3.4.

Strict schema discipline (pre-reg §3.5):
  - ONLY structured state fields are emitted.
  - NO answer_guidance, prompt_hint, caution_note, or any instruction-shaped
    field appears in the output.
  - The LLM must derive caution from warrant fields (confidence, support_n,
    coverage_status, lifecycle_state, evidence_refs vs counterevidence_refs)
    on its own.

Inputs:
  data/derived/expectation_entities.parquet
  data/derived/expectation_lifecycle_events.parquet
  data/derived/narrative_pressure.jsonl
  data/normalized/tech_ecosystem.jsonl       (for evidence_refs linkage)

Outputs:
  stack_grounded_v1/data/belief_objects.jsonl
  stack_grounded_v1/data/belief_substrate_audit.json

Cutoff compatibility:
  Each belief carries `first_seen`, `last_updated`, and `evidence_refs`
  (chunk_ids that resolve to timestamps in chunk_substrate.jsonl). The
  context builder (later phase) enforces:
    - belief.last_updated <= T
    - all evidence_refs resolve to chunks with timestamp <= T
  per pre-reg §5.2. This script does NOT pre-filter by cutoff; it emits
  the full snapshot so any cutoff in the question set can be applied at
  query time.

Field derivation (also documented in SUBSTRATE_CONSTRUCTION_NOTES.md §3):
  belief_id            <- expectation_entities.entity_id
  actor                <- expectation_entities.ticker
  theme                <- expectation_entities.stable_cluster_id
  claim                <- expectation_entities.last_headline
  confidence           <- expectation_entities.last_conviction (already in [0,1])
  support_n            <- expectation_entities.n_versions
  lifecycle_state      <- most recent lifecycle_events.event_type for this
                          entity_id (mapped to the 6-value schema enum;
                          'strengthened' -> 'reconfirmed', and entities
                          with status='active' but no terminal event keep
                          their latest non-terminal event as state)
  evidence_refs        <- tech_ecosystem event_ids whose actors intersect
                          {entity.ticker} AND whose timestamp falls in
                          [entity.first_seen - EVIDENCE_LOOKBACK_DAYS,
                           entity.last_seen]. The asymmetric backward
                          lookback (default 7d) reflects the pipeline's
                          'born' events being driven by accumulated pressure
                          from preceding days, not single-day mentions.
                          Strict [first_seen, last_seen] left ~19% of
                          short-lived beliefs (support_n=1, single-day
                          windows) with empty evidence_refs even though
                          the pipeline had warranted them.
  counterevidence_refs <- subset of the actor's events within +/- 3 days
                          of lifecycle events with event_type in
                          {contradicted, weakened}
  source_mix           <- source counts among evidence_refs
  first_seen           <- expectation_entities.first_seen
  last_updated         <- max(lifecycle_events.date) for this entity_id,
                          falling back to entity.last_seen
  coverage_status      <- derived from warrant quality only (decoupled from
                          lifecycle_state, which carries currency separately):
                          IN_DISTRIBUTION    if support_n >= 3 AND
                                                len(evidence_refs) >= 5
                          OUT_OF_DISTRIBUTION if support_n <= 1 AND
                                                len(evidence_refs) <= 2
                          PARTIAL            otherwise (the mid-warrant band)
                          A well-warranted retired belief is still IN_DIST
                          (good historical coverage); the LLM combines this
                          with lifecycle_state to judge whether the claim
                          is current vs. historical. OUT_OF_DISTRIBUTION
                          marks thinly-supported beliefs the LLM should
                          decline on rather than synthesize from.
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import pandas as pd

ROOT       = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent

EE_PATH        = STORM_ROOT / "data" / "derived" / "expectation_entities.parquet"
LE_PATH        = STORM_ROOT / "data" / "derived" / "expectation_lifecycle_events.parquet"
NP_PATH        = STORM_ROOT / "data" / "derived" / "narrative_pressure.jsonl"
EVENTS_PATH    = STORM_ROOT / "data" / "normalized" / "tech_ecosystem.jsonl"

OUT_BELIEFS    = ROOT / "data" / "belief_objects.jsonl"
OUT_AUDIT      = ROOT / "data" / "belief_substrate_audit.json"

WINDOW_START = "2025-12-05"
WINDOW_END   = "2026-05-26"

PRIMARY_TICKERS = sorted([
    "NVDA", "TSM", "AMD", "INTC", "ARM", "AVGO", "ASML", "MU", "MRVL",
    "SNDK", "WDC", "ALAB", "MSFT", "META", "GOOGL", "PLTR", "AMZN", "ORCL",
    "SMCI", "DELL", "ANET", "NBIS", "VRT", "VST", "COHR", "CLS", "CEG",
    "CRM", "ADBE", "DDOG", "SNOW", "TTD", "MELI", "NFLX", "TSLA", "AAPL",
    "SOFI", "CRWV", "ZETA",
])
PRIMARY_SET = set(PRIMARY_TICKERS)

# Locked schema enum for lifecycle_state per pre-reg §3.4
ALLOWED_LIFECYCLE = {"born", "active", "reconfirmed", "weakened", "contradicted", "retired"}

# Mapping for non-schema event_types into the locked enum
LIFECYCLE_REMAP = {
    "strengthened": "reconfirmed",  # positive revision -> closest schema slot
}

EVIDENCE_REF_CAP        = 50   # max evidence_refs per belief
EVIDENCE_LOOKBACK_DAYS  = 7    # backward window before entity.first_seen
COUNTER_WINDOW_DAYS     = 3    # +/- days around contradicted/weakened lifecycle event


def in_window_date(d: str) -> bool:
    return WINDOW_START <= d[:10] <= WINDOW_END


def normalize_lifecycle(event_type: str) -> str:
    if event_type in ALLOWED_LIFECYCLE:
        return event_type
    if event_type in LIFECYCLE_REMAP:
        return LIFECYCLE_REMAP[event_type]
    return "active"  # fallback; should never trigger with current event_types


def build_event_index() -> tuple[dict, dict]:
    """
    Return:
      events_by_actor: ticker -> list of (timestamp, event_id, source)
      events_by_id:    event_id -> source string (for source_mix lookups)
    Filters to events whose timestamp falls in the window AND at least one
    actor is in the primary universe.
    """
    by_actor: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    by_id: dict[str, str] = {}
    read = 0
    kept = 0
    with EVENTS_PATH.open() as f:
        for line in f:
            read += 1
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = e.get("timestamp")
            if not ts or len(ts) < 10:
                continue
            if not in_window_date(ts):
                continue
            actors = e.get("actors") or []
            primary = [a for a in actors if a in PRIMARY_SET]
            if not primary:
                continue
            ev_id = e.get("event_id")
            if not ev_id:
                continue
            src = e.get("source", "")
            by_id[ev_id] = src
            for a in primary:
                by_actor[a].append((ts, ev_id, src))
            kept += 1
    # Sort each actor's events by timestamp ascending
    for a in by_actor:
        by_actor[a].sort()
    print(f"  events: read {read:,}, indexed {kept:,} across {len(by_actor)} actors")
    return by_actor, by_id


def main() -> None:
    print(f"Loading {EE_PATH}...")
    ee = pd.read_parquet(EE_PATH)
    print(f"  {len(ee):,} entities, {ee['ticker'].nunique()} tickers")

    print(f"Loading {LE_PATH}...")
    le = pd.read_parquet(LE_PATH)
    print(f"  {len(le):,} lifecycle events")

    print(f"Indexing {EVENTS_PATH}...")
    events_by_actor, events_by_id = build_event_index()

    # Pre-group lifecycle events by entity_id, sorted by date asc
    le_sorted = le.sort_values(["entity_id", "date"])
    lifecycle_by_entity: dict[str, list[dict]] = defaultdict(list)
    for row in le_sorted.itertuples(index=False):
        lifecycle_by_entity[row.entity_id].append({
            "date":       row.date,
            "event_type": row.event_type,
        })

    print("Building belief objects...")
    beliefs: list[dict] = []
    skipped_not_primary = 0
    skipped_out_of_window_first_seen = 0
    skipped_no_headline = 0
    counter_skipped_no_lifecycle = 0

    for row in ee.itertuples(index=False):
        ticker = row.ticker
        if ticker not in PRIMARY_SET:
            skipped_not_primary += 1
            continue
        first_seen = row.first_seen
        last_seen  = row.last_seen
        if not first_seen or first_seen > WINDOW_END:
            skipped_out_of_window_first_seen += 1
            continue

        claim = (row.last_headline or "").strip()
        if not claim:
            skipped_no_headline += 1
            continue

        # Lifecycle state — most recent lifecycle event, mapped into the enum
        events_for_entity = lifecycle_by_entity.get(row.entity_id, [])
        if events_for_entity:
            latest_lifecycle = events_for_entity[-1]
            lifecycle_state = normalize_lifecycle(latest_lifecycle["event_type"])
            last_updated = max(e["date"] for e in events_for_entity)
        else:
            # No lifecycle events at all — fall back to status-derived state
            status = (row.status or "active").lower()
            lifecycle_state = status if status in ALLOWED_LIFECYCLE else "active"
            last_updated = last_seen

        # Clamp last_updated to window_end (a belief object as-of v0.1)
        if last_updated and last_updated > WINDOW_END:
            last_updated = WINDOW_END

        # Evidence refs — actor events within
        # [first_seen - EVIDENCE_LOOKBACK_DAYS, last_seen]. Asymmetric
        # backward lookback only; never look past last_seen (cutoff
        # discipline). The lookback accounts for the pipeline's 'born'
        # events being driven by accumulated pressure from preceding days.
        try:
            fs_dt = datetime.strptime(first_seen, "%Y-%m-%d")
            lookback_start = (fs_dt - timedelta(days=EVIDENCE_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        except ValueError:
            lookback_start = first_seen
        actor_events = events_by_actor.get(ticker, [])
        evidence: list[tuple[str, str, str]] = []
        for ts, ev_id, src in actor_events:
            if ts[:10] < lookback_start:
                continue
            if ts[:10] > last_seen:
                break
            evidence.append((ts, ev_id, src))
        # Cap to EVIDENCE_REF_CAP, keep most recent (closer to last_updated)
        if len(evidence) > EVIDENCE_REF_CAP:
            evidence = evidence[-EVIDENCE_REF_CAP:]
        evidence_refs = [ev_id for _, ev_id, _ in evidence]
        source_mix    = dict(Counter(src for _, _, src in evidence))

        # Counterevidence refs — events near contradicted/weakened lifecycle events
        counter_dates: list[str] = []
        for le_event in events_for_entity:
            if le_event["event_type"] in {"contradicted", "weakened"}:
                counter_dates.append(le_event["date"])
        if not counter_dates and lifecycle_state in {"contradicted", "weakened"}:
            counter_skipped_no_lifecycle += 1

        counter_refs: list[str] = []
        if counter_dates:
            counter_set: set[str] = set()
            for cd in counter_dates:
                try:
                    cd_dt = datetime.strptime(cd, "%Y-%m-%d")
                except ValueError:
                    continue
                window_lo = (cd_dt - timedelta(days=COUNTER_WINDOW_DAYS)).strftime("%Y-%m-%d")
                window_hi = (cd_dt + timedelta(days=COUNTER_WINDOW_DAYS)).strftime("%Y-%m-%d")
                for ts, ev_id, _ in actor_events:
                    if ts[:10] < window_lo:
                        continue
                    if ts[:10] > window_hi:
                        break
                    counter_set.add(ev_id)
            # Don't double-count: counterevidence is a labeled subset; keep
            # whatever sits in the +/-3d windows even if also in evidence_refs,
            # since the same event can be evidence AND signal a contradiction.
            counter_refs = sorted(counter_set)

        # Confidence — last_conviction (already in [0,1]; entities have
        # values in [0.4, 0.85] in practice). The pre-reg §3.4 note allows
        # construction here; we use the pipeline's own conviction estimate
        # directly so the warrant signal matches the field's existing scale.
        confidence = float(row.last_conviction) if row.last_conviction is not None else None

        # Coverage status — warrant quality only (decoupled from
        # lifecycle_state, which carries the currency signal separately).
        support_n = int(row.n_versions) if row.n_versions is not None else 0
        n_ev = len(evidence_refs)
        if support_n >= 3 and n_ev >= 5:
            coverage_status = "IN_DISTRIBUTION"
        elif support_n <= 1 and n_ev <= 2:
            coverage_status = "OUT_OF_DISTRIBUTION"
        else:
            coverage_status = "PARTIAL"

        belief = {
            "belief_id":            row.entity_id,
            "actor":                ticker,
            "theme":                row.stable_cluster_id or "",
            "claim":                claim,
            "coverage_status":      coverage_status,
            "confidence":           confidence,
            "support_n":            support_n,
            "lifecycle_state":      lifecycle_state,
            "evidence_refs":        evidence_refs,
            "counterevidence_refs": counter_refs,
            "source_mix":           source_mix,
            "last_updated":         last_updated,
            "first_seen":           first_seen,
        }
        beliefs.append(belief)

    # Sort beliefs by (last_updated desc, belief_id) for stable, ergonomic order
    beliefs.sort(key=lambda b: (b["last_updated"] or "", b["belief_id"]))

    # --- Validation ----------------------------------------------------------
    by_actor = Counter(b["actor"] for b in beliefs)
    by_lifecycle = Counter(b["lifecycle_state"] for b in beliefs)
    by_coverage = Counter(b["coverage_status"] for b in beliefs)
    by_month_last_updated = Counter((b["last_updated"] or "")[:7] for b in beliefs)
    actors_with_zero = sorted(a for a in PRIMARY_TICKERS if by_actor[a] == 0)

    conf_vals = [b["confidence"] for b in beliefs if b["confidence"] is not None]
    n_evidence = [len(b["evidence_refs"]) for b in beliefs]
    n_counter  = [len(b["counterevidence_refs"]) for b in beliefs]
    n_zero_evidence = sum(1 for x in n_evidence if x == 0)
    n_with_counter  = sum(1 for x in n_counter if x > 0)

    # Schema-compliance check — no forbidden instruction fields anywhere
    FORBIDDEN = {"answer_guidance", "prompt_hint", "caution_note", "instruction"}
    forbidden_present = [k for b in beliefs[:1] for k in b.keys() if k in FORBIDDEN]

    # Required-field presence check
    REQUIRED = {
        "belief_id", "actor", "theme", "claim", "coverage_status",
        "confidence", "support_n", "lifecycle_state", "evidence_refs",
        "counterevidence_refs", "source_mix", "last_updated", "first_seen",
    }
    missing_fields_count = 0
    for b in beliefs:
        if REQUIRED - set(b.keys()):
            missing_fields_count += 1

    print()
    print("=" * 72)
    print("BELIEF SUBSTRATE VALIDATION")
    print("=" * 72)
    print(f"  Belief objects emitted:    {len(beliefs):,}")
    print(f"  Window:                    {WINDOW_START} .. {WINDOW_END}")
    print(f"  Actors covered:            {len([a for a in PRIMARY_TICKERS if by_actor[a] > 0])} / {len(PRIMARY_TICKERS)}")
    print(f"  Actors with zero beliefs:  {actors_with_zero or 'none'}")
    print(f"  Forbidden fields present:  {forbidden_present or 'none'}")
    print(f"  Records missing required:  {missing_fields_count}")
    print(f"\n  Confidence (last_conviction):")
    if conf_vals:
        print(f"    min/mean/max:            {min(conf_vals):.3f} / {sum(conf_vals)/len(conf_vals):.3f} / {max(conf_vals):.3f}")
    print(f"\n  Evidence refs per belief:")
    if n_evidence:
        print(f"    min/mean/max:            {min(n_evidence)} / {sum(n_evidence)/len(n_evidence):.1f} / {max(n_evidence)}")
        print(f"    beliefs with 0 refs:     {n_zero_evidence}")
    print(f"  Counterevidence refs:")
    if n_counter:
        print(f"    beliefs with > 0:        {n_with_counter}")
    print(f"\n  Coverage status:")
    for cs, n in by_coverage.most_common():
        print(f"    {cs:22s}  {n:5,}")
    print(f"\n  Lifecycle state:")
    for ls, n in by_lifecycle.most_common():
        print(f"    {ls:14s}  {n:5,}")
    print(f"\n  Per-actor coverage (top 10):")
    for a, n in by_actor.most_common(10):
        print(f"    {a:8s}  {n:4,}")
    print(f"\n  Last-updated month spread:")
    for mo, n in sorted(by_month_last_updated.items()):
        print(f"    {mo}      {n:5,}")
    print(f"\n  Exclusions:")
    print(f"    not in primary universe:    {skipped_not_primary}")
    print(f"    first_seen post-window:     {skipped_out_of_window_first_seen}")
    print(f"    empty last_headline:        {skipped_no_headline}")

    # Write outputs
    OUT_BELIEFS.parent.mkdir(exist_ok=True)
    with OUT_BELIEFS.open("w") as f:
        for b in beliefs:
            f.write(json.dumps(b) + "\n")
    print(f"\nWrote {OUT_BELIEFS}")

    audit = {
        "schema_version":           "v0.1",
        "inputs": {
            "expectation_entities":         str(EE_PATH),
            "expectation_lifecycle_events": str(LE_PATH),
            "narrative_pressure":           str(NP_PATH),
            "tech_ecosystem":               str(EVENTS_PATH),
        },
        "window_start":             WINDOW_START,
        "window_end":               WINDOW_END,
        "primary_universe":         PRIMARY_TICKERS,
        "beliefs_emitted":          len(beliefs),
        "actors_total":             len(PRIMARY_TICKERS),
        "actors_covered":           len([a for a in PRIMARY_TICKERS if by_actor[a] > 0]),
        "actors_with_zero":         actors_with_zero,
        "per_actor_counts":         {a: by_actor[a] for a in PRIMARY_TICKERS},
        "coverage_status_breakdown": dict(by_coverage),
        "lifecycle_state_breakdown": dict(by_lifecycle),
        "confidence_stats": {
            "min":  min(conf_vals) if conf_vals else None,
            "mean": (sum(conf_vals)/len(conf_vals)) if conf_vals else None,
            "max":  max(conf_vals) if conf_vals else None,
            "n_non_null": len(conf_vals),
        },
        "evidence_refs_stats": {
            "min":  min(n_evidence) if n_evidence else None,
            "mean": (sum(n_evidence)/len(n_evidence)) if n_evidence else None,
            "max":  max(n_evidence) if n_evidence else None,
            "cap":  EVIDENCE_REF_CAP,
            "lookback_days": EVIDENCE_LOOKBACK_DAYS,
            "beliefs_with_zero_refs": n_zero_evidence,
        },
        "counterevidence_refs_stats": {
            "beliefs_with_counter": n_with_counter,
            "counter_window_days":  COUNTER_WINDOW_DAYS,
            "lifecycle_state_contradicted_weakened_without_dates": counter_skipped_no_lifecycle,
        },
        "month_breakdown_last_updated": dict(sorted(by_month_last_updated.items())),
        "schema_compliance": {
            "forbidden_fields_present":  forbidden_present,
            "records_missing_required":  missing_fields_count,
            "required_fields":           sorted(REQUIRED),
            "forbidden_fields":          sorted(FORBIDDEN),
        },
        "lifecycle_remap":          LIFECYCLE_REMAP,
        "exclusions": {
            "not_in_primary_universe":  skipped_not_primary,
            "first_seen_post_window":   skipped_out_of_window_first_seen,
            "empty_last_headline":      skipped_no_headline,
        },
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"Wrote {OUT_AUDIT}")


if __name__ == "__main__":
    main()
