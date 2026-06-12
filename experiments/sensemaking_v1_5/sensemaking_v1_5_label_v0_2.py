#!/usr/bin/env python3
"""
Sensemaking v1.5 v0.2 — Labeler.

Per PHASE2_PRE_REGISTRATION_v0.2.md §3, §6:
  - REPRICING split by actor-level direction field (I-001 noted in pre-reg §3.3)
  - EARLY isolated into standalone Early_followthrough bucket (Constructive
    truth-table labeling, provisional per §3.4)
  - Ambiguous baseline = MACRO, PRICE-LED, UNCLEAR only (REPRICING removed)

Reads sensemaking_v1_5_rows.parquet (v0.1 harness output — unchanged).
Writes sensemaking_v1_5_labeled_v0_2.parquet + primary_summary_v0_2.json.
"""

from __future__ import annotations

import json
import pathlib
from collections import defaultdict

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
IN_PATH      = ROOT / "data" / "sensemaking_v1_5_rows.parquet"
OUT_PARQUET  = ROOT / "data" / "sensemaking_v1_5_labeled_v0_2.parquet"
OUT_SUMMARY  = ROOT / "data" / "sensemaking_v1_5_primary_summary_v0_2.json"

RULES_VERSION = "v0.2"
HORIZONS      = (5, 20)

# §3.2 v0.2 bucket mapping (uses state + direction; REPRICING split by actor direction)
# Note: REPRICING_bullish / REPRICING_bearish are not "states" but bucket-assignments
# derived from state=REPRICING + direction=±1.
BASE_STATE_TO_BUCKET = {
    "CONFIRMED":         "Constructive",
    "DISAGREEMENT":      "Constructive",
    "NEG_CONFIRMATION":  "Cautious",
    "DIVERGENCE":        "Cautious",
    "EARLY":             "Early_followthrough",
    "MACRO":             "Ambiguous",
    "PRICE-LED":         "Ambiguous",
    "UNCLEAR":           "Ambiguous",
    # REPRICING handled below by direction split
}


def bucket_for_row(state: str, direction: int) -> tuple[str, str]:
    """Return (bucket, effective_state). effective_state encodes the REPRICING split."""
    if state == "REPRICING":
        if direction == 1:
            return ("Constructive", "REPRICING_bullish")
        elif direction == -1:
            return ("Cautious", "REPRICING_bearish")
        else:
            return ("Ambiguous", "REPRICING_unclassified")  # safety; should not occur
    return (BASE_STATE_TO_BUCKET.get(state, "Unknown"), state)


def label_row(bucket: str, fwd_rel: float | None) -> str | None:
    """§6 v0.2 truth table. Early_followthrough uses Constructive labeling (§3.4)."""
    if fwd_rel is None or pd.isna(fwd_rel):
        return None
    if bucket in ("Constructive", "Early_followthrough"):
        return "Hit" if fwd_rel > 0 else "FP"
    if bucket == "Cautious":
        return "Hit" if fwd_rel < 0 else "FN"
    return None  # Ambiguous: not labeled


def per_bucket_metrics(df: pd.DataFrame, horizon: int) -> dict[str, dict]:
    fwd_col   = f"fwd_rel_{horizon}d"
    label_col = f"label_{horizon}d"

    # Ambiguous baseline distribution
    ambig = df[(df["bucket"] == "Ambiguous") & df[fwd_col].notna()]
    baseline_avg    = float(ambig[fwd_col].mean())   if len(ambig) else None
    baseline_median = float(ambig[fwd_col].median()) if len(ambig) else None
    baseline_pos    = float((ambig[fwd_col] > 0).mean()) if len(ambig) else None

    out: dict[str, dict] = {}
    for bucket in ("Constructive", "Cautious", "Early_followthrough", "Ambiguous"):
        rows = df[(df["bucket"] == bucket) & df[fwd_col].notna()]
        n = len(rows)

        labeled = rows[rows[label_col].notna()] if n else rows
        hits = int((labeled[label_col] == "Hit").sum()) if len(labeled) else 0
        fps  = int((labeled[label_col] == "FP").sum())  if len(labeled) else 0
        fns  = int((labeled[label_col] == "FN").sum())  if len(labeled) else 0

        if bucket in ("Constructive", "Early_followthrough"):
            denom = hits + fps
        elif bucket == "Cautious":
            denom = hits + fns
        else:
            denom = 0

        hit_rate = (hits / denom) if denom > 0 else None
        avg     = float(rows[fwd_col].mean())   if n else None
        median  = float(rows[fwd_col].median()) if n else None
        pct_pos = float((rows[fwd_col] > 0).mean()) if n else None

        out[bucket] = {
            "n":                    n,
            "hits":                 hits,
            "false_positives":      fps,
            "false_negatives":      fns,
            "hit_rate":             hit_rate,
            "avg_fwd_rel":          avg,
            "median_fwd_rel":       median,
            "pct_positive_fwd_rel": pct_pos,
            "baseline_avg_diff":    (avg - baseline_avg) if (avg is not None and baseline_avg is not None) else None,
            "baseline_median_diff": (median - baseline_median) if (median is not None and baseline_median is not None) else None,
            "baseline_pct_pos_diff":(pct_pos - baseline_pos) if (pct_pos is not None and baseline_pos is not None) else None,
        }
    return out


def per_effective_state_metrics(df: pd.DataFrame, horizon: int) -> dict[str, dict]:
    fwd_col = f"fwd_rel_{horizon}d"
    out = {}
    for state, group in df.groupby("effective_state"):
        rows = group[group[fwd_col].notna()]
        n = len(rows)
        if n == 0:
            out[state] = {"bucket": group["bucket"].iloc[0], "n": 0}
            continue
        out[state] = {
            "bucket":               group["bucket"].iloc[0],
            "n":                    n,
            "avg_fwd_rel":          float(rows[fwd_col].mean()),
            "median_fwd_rel":       float(rows[fwd_col].median()),
            "pct_positive_fwd_rel": float((rows[fwd_col] > 0).mean()),
        }
    return out


def main() -> None:
    print("Loading harness rows (v0.1 output reused for v0.2)…")
    df = pd.read_parquet(IN_PATH)
    primary = df[df["in_primary"]].copy()
    print(f"  primary universe rows: {len(primary):,}")

    # Apply v0.2 bucket mapping
    bucket_eff = [bucket_for_row(s, int(d)) for s, d in zip(primary["state"], primary["direction"])]
    primary["bucket"]          = [b for b, _ in bucket_eff]
    primary["effective_state"] = [e for _, e in bucket_eff]

    # Sanity
    unknown = primary[primary["bucket"] == "Unknown"]
    if not unknown.empty:
        print(f"  WARN: {len(unknown)} rows in Unknown bucket; states: {sorted(unknown['state'].unique())}")

    # Label per horizon
    for h in HORIZONS:
        primary[f"label_{h}d"] = [
            label_row(b, v) for b, v in zip(primary["bucket"], primary[f"fwd_rel_{h}d"])
        ]

    OUT_PARQUET.parent.mkdir(exist_ok=True)
    primary.to_parquet(OUT_PARQUET, index=False)

    summary = {
        "rules_version": RULES_VERSION,
        "universe":      {"in_primary_rows": len(primary)},
        "per_horizon":   {},
    }
    for h in HORIZONS:
        summary["per_horizon"][f"{h}d"] = {
            "per_bucket":          per_bucket_metrics(primary, h),
            "per_effective_state": per_effective_state_metrics(primary, h),
        }
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))
    print(f"  wrote {OUT_PARQUET}")
    print(f"  wrote {OUT_SUMMARY}")

    # Console summary
    for h in HORIZONS:
        print()
        print("=" * 72)
        print(f"V0.2 PRIMARY HEAD ({h}D HORIZON)")
        print("=" * 72)
        b = summary["per_horizon"][f"{h}d"]["per_bucket"]
        print(f"  {'bucket':22s}  {'n':>6s}  {'hits':>5s}  {'FP/FN':>5s}  {'hit_rate':>9s}  {'avg':>10s}  {'med':>10s}  {'%pos':>6s}  {'Δbase':>10s}")
        for bucket in ("Constructive", "Cautious", "Early_followthrough", "Ambiguous"):
            r = b[bucket]
            n = r["n"]
            if n == 0:
                print(f"  {bucket:22s}  n=0")
                continue
            fp_fn = r["false_positives"] if bucket in ("Constructive", "Early_followthrough") else r["false_negatives"]
            hr  = f"{r['hit_rate']:.3f}" if r["hit_rate"] is not None else "n/a"
            avg = f"{r['avg_fwd_rel']:+.4f}"
            med = f"{r['median_fwd_rel']:+.4f}"
            pct = f"{r['pct_positive_fwd_rel']:.3f}"
            bd  = f"{r['baseline_avg_diff']:+.4f}" if r['baseline_avg_diff'] is not None else "n/a"
            print(f"  {bucket:22s}  {n:>6,}  {r['hits']:>5,}  {fp_fn:>5,}  {hr:>9s}  {avg:>10s}  {med:>10s}  {pct:>6s}  {bd:>10s}")

        print()
        print(f"  Per-effective-state ({h}D):")
        ps = summary["per_horizon"][f"{h}d"]["per_effective_state"]
        for state in sorted(ps, key=lambda s: (ps[s].get("bucket", ""), -ps[s].get("n", 0))):
            r = ps[state]
            n = r["n"]
            if n == 0:
                print(f"    [{r['bucket']:20s}] {state:24s}  n=0")
                continue
            avg = f"{r['avg_fwd_rel']:+.4f}"
            med = f"{r['median_fwd_rel']:+.4f}"
            pct = f"{r['pct_positive_fwd_rel']:.3f}"
            print(f"    [{r['bucket']:20s}] {state:24s}  n={n:>5,}  avg={avg}  med={med}  %pos={pct}")


if __name__ == "__main__":
    main()
