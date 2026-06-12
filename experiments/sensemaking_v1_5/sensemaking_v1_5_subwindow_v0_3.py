#!/usr/bin/env python3
"""
Sensemaking v1.5 v0.3 — Per-sub-window stratification (§11.2).

Sub-window cut: 2026-03-01 (calendar midpoint of 2025-12-05 → 2026-05-26).
  Sub-window A (early):  2025-12-05 → 2026-02-28
  Sub-window B (later):  2026-03-01 → 2026-05-26

All 5 state buckets × 2 horizons × 2 sub-windows. Cautious focal interest
(rising-tide hypothesis), but all buckets stratified for full visibility.
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
STATE_PATH  = ROOT / "data" / "sensemaking_v1_5_state_v0_3.parquet"
OUT_SUMMARY = ROOT / "data" / "sensemaking_v1_5_subwindow_summary_v0_3.json"

RULES_VERSION = "v0.3"
HORIZONS      = (5, 20)
CUT_DATE      = "2026-03-01"


def metric_block(rows: pd.DataFrame, horizon: int) -> dict:
    fwd_col = f"fwd_rel_{horizon}d"
    rows = rows[rows[fwd_col].notna()]
    n = len(rows)
    if n == 0:
        return {"n": 0}
    return {
        "n":                    n,
        "avg_fwd_rel":          float(rows[fwd_col].mean()),
        "median_fwd_rel":       float(rows[fwd_col].median()),
        "pct_positive_fwd_rel": float((rows[fwd_col] > 0).mean()),
    }


def main() -> None:
    print("Loading v0.3 state-bucket parquet…")
    df = pd.read_parquet(STATE_PATH)
    df["date"] = pd.to_datetime(df["date"])
    cut = pd.Timestamp(CUT_DATE)
    df["sub_window"] = df["date"].apply(lambda d: "A_early" if d < cut else "B_later")
    print(f"  A_early rows: {(df['sub_window']=='A_early').sum():,}")
    print(f"  B_later rows: {(df['sub_window']=='B_later').sum():,}")

    summary = {
        "rules_version": RULES_VERSION,
        "cut_date":      CUT_DATE,
        "sub_window_A":  "2025-12-05 → 2026-02-28",
        "sub_window_B":  "2026-03-01 → 2026-05-26",
        "per_horizon":   {},
    }

    for h in HORIZONS:
        per_window = {}
        for window_key in ("A_early", "B_later"):
            window_rows = df[df["sub_window"] == window_key]
            per_bucket = {}
            for bucket in ("Constructive", "Cautious", "REPRICING_primary", "Early_followthrough", "Ambiguous"):
                b_rows = window_rows[window_rows["bucket"] == bucket]
                per_bucket[bucket] = metric_block(b_rows, h)
            # Baseline within window = Ambiguous within window
            base_avg = per_bucket["Ambiguous"].get("avg_fwd_rel")
            for bucket in ("Constructive", "Cautious", "REPRICING_primary", "Early_followthrough"):
                if per_bucket[bucket].get("avg_fwd_rel") is not None and base_avg is not None:
                    per_bucket[bucket]["window_baseline_avg_diff"] = per_bucket[bucket]["avg_fwd_rel"] - base_avg
                else:
                    per_bucket[bucket]["window_baseline_avg_diff"] = None
            per_window[window_key] = per_bucket
        summary["per_horizon"][f"{h}d"] = per_window

    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))
    print(f"  wrote {OUT_SUMMARY}")

    for h in HORIZONS:
        print()
        print("=" * 72)
        print(f"V0.3 PER-SUB-WINDOW — {h}D")
        print("=" * 72)
        for window_key in ("A_early", "B_later"):
            print(f"\n  {window_key}:")
            pw = summary["per_horizon"][f"{h}d"][window_key]
            for bucket in ("Constructive", "Cautious", "REPRICING_primary", "Early_followthrough", "Ambiguous"):
                r = pw[bucket]
                n = r["n"]
                if n == 0:
                    print(f"    {bucket:22s}  n=0")
                    continue
                avg = f"{r['avg_fwd_rel']:+.4f}"
                pct = f"{r['pct_positive_fwd_rel']:.3f}"
                d = r.get("window_baseline_avg_diff")
                dd = f"{d:+.4f}" if d is not None else "—"
                print(f"    {bucket:22s}  n={n:>5,}  avg={avg}  %pos={pct}  Δwin_base={dd}")


if __name__ == "__main__":
    main()
