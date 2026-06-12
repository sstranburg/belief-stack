#!/usr/bin/env python3
"""
Sensemaking v1.5 v0.3 — State buckets (SECONDARY).

Per pre-registration v0.3 §11.1:
  Constructive = {CONFIRMED, DISAGREEMENT}     (Hit if fwd_rel > 0)
  Cautious = {NEG_CONFIRMATION, DIVERGENCE}    (Hit if fwd_rel < 0)
  REPRICING_primary = {REPRICING}              (UNLABELED — descriptive only, per locked §11.1)
  Early_followthrough = {EARLY}                (Constructive labeling, provisional)
  Ambiguous = {MACRO, PRICE-LED, UNCLEAR}      (baseline; unlabeled)
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
ROWS_PATH    = ROOT / "data" / "sensemaking_v1_5_rows.parquet"
OUT_PARQUET  = ROOT / "data" / "sensemaking_v1_5_state_v0_3.parquet"
OUT_SUMMARY  = ROOT / "data" / "sensemaking_v1_5_state_summary_v0_3.json"

RULES_VERSION = "v0.3"
HORIZONS      = (5, 20)

# v0.3 state-bucket mapping (REPRICING standalone, no direction split)
STATE_TO_BUCKET = {
    "CONFIRMED":         "Constructive",
    "DISAGREEMENT":      "Constructive",
    "NEG_CONFIRMATION":  "Cautious",
    "DIVERGENCE":        "Cautious",
    "REPRICING":         "REPRICING_primary",
    "EARLY":             "Early_followthrough",
    "MACRO":             "Ambiguous",
    "PRICE-LED":         "Ambiguous",
    "UNCLEAR":           "Ambiguous",
}

# Buckets that get directional labels
LABELED_BUCKETS = {"Constructive", "Cautious", "Early_followthrough"}


def label_row(bucket: str, fwd_rel) -> str | None:
    if fwd_rel is None or pd.isna(fwd_rel) or bucket not in LABELED_BUCKETS:
        return None
    if bucket in ("Constructive", "Early_followthrough"):
        return "Hit" if fwd_rel > 0 else "FP"
    if bucket == "Cautious":
        return "Hit" if fwd_rel < 0 else "FN"
    return None


def per_bucket_metrics(df: pd.DataFrame, horizon: int) -> dict:
    fwd_col = f"fwd_rel_{horizon}d"
    label_col = f"label_{horizon}d"
    ambig = df[(df["bucket"] == "Ambiguous") & df[fwd_col].notna()]
    base_avg = float(ambig[fwd_col].mean()) if len(ambig) else None
    base_pct = float((ambig[fwd_col] > 0).mean()) if len(ambig) else None

    out = {}
    for bucket in ("Constructive", "Cautious", "REPRICING_primary", "Early_followthrough", "Ambiguous"):
        rows = df[(df["bucket"] == bucket) & df[fwd_col].notna()]
        n = len(rows)
        if n == 0:
            out[bucket] = {"n": 0}
            continue
        avg = float(rows[fwd_col].mean())
        pct = float((rows[fwd_col] > 0).mean())
        block = {
            "n":                    n,
            "avg_fwd_rel":          avg,
            "median_fwd_rel":       float(rows[fwd_col].median()),
            "pct_positive_fwd_rel": pct,
            "baseline_avg_diff":    (avg - base_avg) if base_avg is not None else None,
        }
        if bucket in LABELED_BUCKETS:
            labeled = rows[rows[label_col].notna()]
            hits = int((labeled[label_col] == "Hit").sum())
            if bucket in ("Constructive", "Early_followthrough"):
                fp = int((labeled[label_col] == "FP").sum())
                block["hits"] = hits
                block["false_positives"] = fp
                block["hit_rate"] = hits / (hits + fp) if (hits + fp) else None
            elif bucket == "Cautious":
                fn = int((labeled[label_col] == "FN").sum())
                block["hits"] = hits
                block["false_negatives"] = fn
                block["hit_rate"] = hits / (hits + fn) if (hits + fn) else None
        else:
            block["labeled"] = False
        out[bucket] = block
    return out


def main() -> None:
    print("Loading harness rows…")
    rows_all = pd.read_parquet(ROWS_PATH)
    primary = rows_all[rows_all["in_primary"]].copy()
    primary["bucket"] = primary["state"].map(STATE_TO_BUCKET)

    for h in HORIZONS:
        primary[f"label_{h}d"] = [
            label_row(b, v) for b, v in zip(primary["bucket"], primary[f"fwd_rel_{h}d"])
        ]

    OUT_PARQUET.parent.mkdir(exist_ok=True)
    primary.to_parquet(OUT_PARQUET, index=False)

    summary = {
        "rules_version": RULES_VERSION,
        "universe":      {"in_primary_rows": len(primary)},
        "per_horizon":   {f"{h}d": per_bucket_metrics(primary, h) for h in HORIZONS},
    }
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))
    print(f"  wrote {OUT_PARQUET}")
    print(f"  wrote {OUT_SUMMARY}")

    for h in HORIZONS:
        print()
        print("=" * 72)
        print(f"V0.3 STATE BUCKETS (SECONDARY) — {h}D")
        print("=" * 72)
        b = summary["per_horizon"][f"{h}d"]
        print(f"  {'bucket':22s}  {'n':>6s}  {'avg':>10s}  {'med':>10s}  {'%pos':>6s}  {'Δbase':>10s}  {'hit_rate':>9s}")
        for bucket in ("Constructive", "Cautious", "REPRICING_primary", "Early_followthrough", "Ambiguous"):
            r = b[bucket]
            n = r["n"]
            if n == 0:
                print(f"  {bucket:22s}  n=0")
                continue
            avg = f"{r['avg_fwd_rel']:+.4f}"
            med = f"{r['median_fwd_rel']:+.4f}"
            pct = f"{r['pct_positive_fwd_rel']:.3f}"
            d   = r.get("baseline_avg_diff")
            dd  = f"{d:+.4f}" if d is not None else "—"
            hr  = r.get("hit_rate")
            hrf = f"{hr:.3f}" if hr is not None else ("n/a" if "labeled" in r else "n/a")
            label_marker = "" if r.get("labeled") is False else ""
            print(f"  {bucket:22s}  {n:>6,}  {avg:>10s}  {med:>10s}  {pct:>6s}  {dd:>10s}  {hrf:>9s}{label_marker}")


if __name__ == "__main__":
    main()
