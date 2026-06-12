#!/usr/bin/env python3
"""
Sensemaking v1.5 v0.4 — Lifecycle revision × regime (SECONDARY).

Per pre-registration v0.4 §12.1. Lifecycle buckets unchanged from
v0.3 §3; stratified by both regime detectors.
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent

LIFECYCLE_PATH_V03 = ROOT / "data" / "sensemaking_v1_5_lifecycle_v0_3.parquet"
REGIMES_PATH       = ROOT / "data" / "sensemaking_v1_5_regimes_v0_4.parquet"
OUT_PARQUET        = ROOT / "data" / "sensemaking_v1_5_lifecycle_v0_4.parquet"
OUT_SUMMARY        = ROOT / "data" / "sensemaking_v1_5_lifecycle_summary_v0_4.json"

RULES_VERSION = "v0.4"
HORIZONS      = (5, 20)


def metric_block(rows: pd.DataFrame, fwd_col: str) -> dict:
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
    print("Loading v0.3 lifecycle parquet + regimes…")
    lc = pd.read_parquet(LIFECYCLE_PATH_V03)
    regimes = pd.read_parquet(REGIMES_PATH)

    # Join regimes on event date
    regimes_join = regimes[["date", "vol_regime", "calendar_regime"]].copy()
    regimes_join["date"]   = regimes_join["date"].astype(str)
    lc["date"]             = lc["date"].astype(str)
    lc = lc.merge(regimes_join, on="date", how="left")

    OUT_PARQUET.parent.mkdir(exist_ok=True)
    lc.to_parquet(OUT_PARQUET, index=False)

    summary = {
        "rules_version": RULES_VERSION,
        "n_events":      len(lc),
        "per_horizon":   {},
    }

    for h in HORIZONS:
        fwd_col = f"fwd_rel_{h}d"
        per_horizon = {}

        for detector_key, regime_labels in (
            ("calendar_regime", ("A_early", "B_later")),
            ("vol_regime",      ("LOW_VOL", "HIGH_VOL")),
        ):
            per_regime = {}
            for r in regime_labels:
                sub = lc[lc[detector_key] == r]
                per_bucket = {}
                for lb in ("Constructive_revision", "Cautious_revision"):
                    rows_lb = sub[sub["lifecycle_bucket"] == lb]
                    per_bucket[lb] = metric_block(rows_lb, fwd_col)
                c = per_bucket["Constructive_revision"].get("avg_fwd_rel")
                k = per_bucket["Cautious_revision"].get("avg_fwd_rel")
                per_bucket["internal_gap"] = (c - k) if (c is not None and k is not None) else None
                per_regime[r] = per_bucket
            per_horizon[detector_key] = per_regime

        # Aggregate (matches v0.3 lifecycle primary)
        agg_per_bucket = {}
        for lb in ("Constructive_revision", "Cautious_revision"):
            rows_lb = lc[lc["lifecycle_bucket"] == lb]
            agg_per_bucket[lb] = metric_block(rows_lb, fwd_col)
        c = agg_per_bucket["Constructive_revision"].get("avg_fwd_rel")
        k = agg_per_bucket["Cautious_revision"].get("avg_fwd_rel")
        agg_per_bucket["internal_gap"] = (c - k) if (c is not None and k is not None) else None
        per_horizon["aggregate"] = agg_per_bucket

        summary["per_horizon"][f"{h}d"] = per_horizon

    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))
    print(f"  wrote {OUT_PARQUET}")
    print(f"  wrote {OUT_SUMMARY}")

    # Console
    for h in HORIZONS:
        for detector_label, detector_key, regime_labels in (
            ("CALENDAR REGIME", "calendar_regime", ("A_early", "B_later")),
            ("VOL REGIME",      "vol_regime",      ("LOW_VOL", "HIGH_VOL")),
        ):
            print()
            print("=" * 72)
            print(f"V0.4 LIFECYCLE — {detector_label} — {h}D")
            print("=" * 72)
            for r in regime_labels:
                pr = summary["per_horizon"][f"{h}d"][detector_key][r]
                print(f"\n  {r}:")
                for lb in ("Constructive_revision", "Cautious_revision"):
                    row = pr[lb]
                    n = row["n"]
                    if n == 0:
                        print(f"    {lb:24s}  n=0")
                        continue
                    print(f"    {lb:24s}  n={n:>4}  avg={row['avg_fwd_rel']:+.4f}  %pos={row['pct_positive_fwd_rel']:.3f}")
                gap = pr["internal_gap"]
                if gap is not None:
                    print(f"    INTERNAL GAP: {gap:+.4f}")


if __name__ == "__main__":
    main()
