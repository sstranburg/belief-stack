#!/usr/bin/env python3
"""
Sensemaking v1.5 v0.4 — State buckets × regime (PRIMARY).

Per pre-registration v0.4 §4 + §6 + §9.
Buckets unchanged from v0.3 §11.1; regimes per v0.4 §3.
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
ROWS_PATH    = ROOT / "data" / "sensemaking_v1_5_rows.parquet"
REGIMES_PATH = ROOT / "data" / "sensemaking_v1_5_regimes_v0_4.parquet"
OUT_PARQUET  = ROOT / "data" / "sensemaking_v1_5_state_v0_4.parquet"
OUT_SUMMARY  = ROOT / "data" / "sensemaking_v1_5_state_summary_v0_4.json"

RULES_VERSION = "v0.4"
HORIZONS      = (5, 20)

STATE_TO_BUCKET = {
    "CONFIRMED":        "Constructive",
    "DISAGREEMENT":     "Constructive",
    "NEG_CONFIRMATION": "Cautious",
    "DIVERGENCE":       "Cautious",
    "REPRICING":        "REPRICING_primary",
    "EARLY":            "Early_followthrough",
    "MACRO":            "Ambiguous",
    "PRICE-LED":        "Ambiguous",
    "UNCLEAR":          "Ambiguous",
}
LABELED_BUCKETS = {"Constructive", "Cautious", "Early_followthrough"}


def label_row(bucket, fwd_rel) -> str | None:
    if fwd_rel is None or pd.isna(fwd_rel) or bucket not in LABELED_BUCKETS:
        return None
    if bucket in ("Constructive", "Early_followthrough"):
        return "Hit" if fwd_rel > 0 else "FP"
    return "Hit" if fwd_rel < 0 else "FN"


def per_bucket_metrics(df: pd.DataFrame, horizon: int) -> dict:
    fwd_col = f"fwd_rel_{horizon}d"
    label_col = f"label_{horizon}d"
    ambig = df[(df["bucket"] == "Ambiguous") & df[fwd_col].notna()]
    base_avg = float(ambig[fwd_col].mean()) if len(ambig) else None

    out = {}
    for bucket in ("Constructive", "Cautious", "REPRICING_primary", "Early_followthrough", "Ambiguous"):
        rows = df[(df["bucket"] == bucket) & df[fwd_col].notna()]
        n = len(rows)
        if n == 0:
            out[bucket] = {"n": 0}
            continue
        avg = float(rows[fwd_col].mean())
        block = {
            "n":                    n,
            "avg_fwd_rel":          avg,
            "median_fwd_rel":       float(rows[fwd_col].median()),
            "pct_positive_fwd_rel": float((rows[fwd_col] > 0).mean()),
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
            else:
                fn = int((labeled[label_col] == "FN").sum())
                block["hits"] = hits
                block["false_negatives"] = fn
                block["hit_rate"] = hits / (hits + fn) if (hits + fn) else None
        else:
            block["labeled"] = False
        out[bucket] = block
    return out


def main() -> None:
    print("Loading rows + regimes…")
    rows = pd.read_parquet(ROWS_PATH)
    regimes = pd.read_parquet(REGIMES_PATH)
    primary = rows[rows["in_primary"]].copy()

    # Apply v0.3 bucket mapping
    primary["bucket"] = primary["state"].map(STATE_TO_BUCKET)

    # Join regimes on date
    regimes_join = regimes[["date", "vol_regime", "calendar_regime"]].copy()
    regimes_join["date"] = regimes_join["date"].astype(str)
    primary["date"] = primary["date"].astype(str)
    primary = primary.merge(regimes_join, on="date", how="left")

    # Sanity: every primary row should have a calendar_regime; vol_regime can be UNDEFINED
    n_no_cal = primary["calendar_regime"].isna().sum()
    n_undef_vol = (primary["vol_regime"] == "UNDEFINED").sum()
    n_missing_vol = primary["vol_regime"].isna().sum()
    print(f"  primary rows: {len(primary):,}")
    print(f"  no calendar_regime: {n_no_cal:,}")
    print(f"  vol_regime = UNDEFINED: {n_undef_vol:,}")
    print(f"  vol_regime missing (no QQQ row for that date): {n_missing_vol:,}")

    # Label per horizon
    for h in HORIZONS:
        primary[f"label_{h}d"] = [
            label_row(b, v) for b, v in zip(primary["bucket"], primary[f"fwd_rel_{h}d"])
        ]

    OUT_PARQUET.parent.mkdir(exist_ok=True)
    primary.to_parquet(OUT_PARQUET, index=False)

    # Compute per-regime metrics for both detectors at both horizons
    summary = {
        "rules_version": RULES_VERSION,
        "n_primary_rows": len(primary),
        "n_undefined_vol_rows": int(n_undef_vol),
        "per_horizon": {},
    }

    for h in HORIZONS:
        # Calendar detector — A_early vs B_later
        cal_per_regime = {}
        for r in ("A_early", "B_later"):
            sub = primary[primary["calendar_regime"] == r]
            cal_per_regime[r] = per_bucket_metrics(sub, h)
        # Vol detector — LOW_VOL vs HIGH_VOL (exclude UNDEFINED from regime-conditioned primary per §8)
        vol_per_regime = {}
        for r in ("LOW_VOL", "HIGH_VOL"):
            sub = primary[primary["vol_regime"] == r]
            vol_per_regime[r] = per_bucket_metrics(sub, h)
        # Cross-regime aggregate (matches v0.3 secondary state-bucket numbers)
        aggregate = per_bucket_metrics(primary, h)
        summary["per_horizon"][f"{h}d"] = {
            "calendar_regime": cal_per_regime,
            "vol_regime":      vol_per_regime,
            "aggregate":       aggregate,
        }

    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))
    print(f"  wrote {OUT_PARQUET}")
    print(f"  wrote {OUT_SUMMARY}")

    # Console summary
    for h in HORIZONS:
        for detector_label, detector_key, regime_labels in (
            ("CALENDAR REGIME", "calendar_regime", ("A_early", "B_later")),
            ("VOL REGIME",      "vol_regime",      ("LOW_VOL", "HIGH_VOL")),
        ):
            print()
            print("=" * 76)
            print(f"V0.4 PRIMARY — {detector_label} × STATE BUCKET — {h}D")
            print("=" * 76)
            for r in regime_labels:
                print(f"\n  {r}:")
                b = summary["per_horizon"][f"{h}d"][detector_key][r]
                for bucket in ("Constructive", "Cautious", "REPRICING_primary", "Early_followthrough", "Ambiguous"):
                    row = b[bucket]
                    n = row["n"]
                    if n == 0:
                        print(f"    {bucket:22s}  n=0")
                        continue
                    avg = f"{row['avg_fwd_rel']:+.4f}"
                    pct = f"{row['pct_positive_fwd_rel']:.3f}"
                    d = row.get("baseline_avg_diff")
                    dd = f"{d:+.4f}" if d is not None else "—"
                    hr = row.get("hit_rate")
                    hr_str = f"{hr:.3f}" if hr is not None else "(unlabeled)"
                    print(f"    {bucket:22s}  n={n:>5,}  avg={avg}  %pos={pct}  Δbase={dd}  hit={hr_str}")


if __name__ == "__main__":
    main()
