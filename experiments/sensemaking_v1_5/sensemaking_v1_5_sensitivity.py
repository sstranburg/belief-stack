#!/usr/bin/env python3
"""
Sensemaking v1.5 — Sensitivity appendix (Phase B, stage 4).

Per pre-registration §12:
  §12.1 REPRICING-as-Constructive sensitivity
  §12.2 Experimental-tickers-included sensitivity
  §12.3 Sensitivity is not the primary claim
  §12.4 What sensitivity is not

Reads:
  sensemaking_v1_5/data/sensemaking_v1_5_rows.parquet
  sensemaking_v1_5/data/sensemaking_v1_5_primary_summary.json
    (used for delta comparisons; primary numbers are the locked headline)

Writes:
  sensemaking_v1_5/data/sensemaking_v1_5_sensitivity_summary.json
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
ROWS_PATH      = ROOT / "data" / "sensemaking_v1_5_rows.parquet"
PRIMARY_SUMMARY = ROOT / "data" / "sensemaking_v1_5_primary_summary.json"
OUT_SUMMARY    = ROOT / "data" / "sensemaking_v1_5_sensitivity_summary.json"

RULES_VERSION = "v0.1"
HORIZONS      = (5, 20)

# §3.2 primary bucket mapping
PRIMARY_BUCKETS = {
    "Constructive": {"CONFIRMED", "EARLY", "DISAGREEMENT"},
    "Cautious":     {"NEG_CONFIRMATION", "DIVERGENCE"},
    "Ambiguous":    {"MACRO", "PRICE-LED", "UNCLEAR", "REPRICING"},
}

# §12.1 — REPRICING-as-Constructive mapping
S121_BUCKETS = {
    "Constructive": {"CONFIRMED", "EARLY", "DISAGREEMENT", "REPRICING"},
    "Cautious":     {"NEG_CONFIRMATION", "DIVERGENCE"},
    "Ambiguous":    {"MACRO", "PRICE-LED", "UNCLEAR"},
}


def per_bucket_metrics(rows: pd.DataFrame, state_to_bucket: dict, horizon: int) -> dict:
    fwd_col = f"fwd_rel_{horizon}d"
    rows = rows.copy()
    rows["bucket"] = rows["state"].map(state_to_bucket)
    rows = rows[rows[fwd_col].notna()]

    # Baseline = Ambiguous rows (under this bucket mapping)
    ambig = rows[rows["bucket"] == "Ambiguous"]
    baseline_avg    = float(ambig[fwd_col].mean())   if len(ambig) else None
    baseline_median = float(ambig[fwd_col].median()) if len(ambig) else None
    baseline_pct    = float((ambig[fwd_col] > 0).mean()) if len(ambig) else None

    out = {}
    for bucket in ("Constructive", "Cautious", "Ambiguous"):
        b_rows = rows[rows["bucket"] == bucket]
        n = len(b_rows)
        if n == 0:
            out[bucket] = {"n": 0}
            continue
        avg     = float(b_rows[fwd_col].mean())
        median  = float(b_rows[fwd_col].median())
        pct_pos = float((b_rows[fwd_col] > 0).mean())
        if bucket == "Constructive":
            hits = int((b_rows[fwd_col] > 0).sum())
            fp_fn = int((b_rows[fwd_col] <= 0).sum())
            denom = hits + fp_fn
            hit_rate = hits / denom if denom else None
        elif bucket == "Cautious":
            hits = int((b_rows[fwd_col] < 0).sum())
            fp_fn = int((b_rows[fwd_col] >= 0).sum())
            denom = hits + fp_fn
            hit_rate = hits / denom if denom else None
        else:
            hits = fp_fn = 0
            hit_rate = None
        out[bucket] = {
            "n":                    n,
            "hits":                 hits,
            "fp_or_fn":             fp_fn,
            "hit_rate":             hit_rate,
            "avg_fwd_rel":          avg,
            "median_fwd_rel":       median,
            "pct_positive_fwd_rel": pct_pos,
            "baseline_avg_diff":    (avg - baseline_avg) if baseline_avg is not None else None,
            "baseline_median_diff": (median - baseline_median) if baseline_median is not None else None,
            "baseline_pct_pos_diff":(pct_pos - baseline_pct) if baseline_pct is not None else None,
        }
    return out


def main() -> None:
    print("Loading harness rows + primary summary…")
    rows_all = pd.read_parquet(ROWS_PATH)
    primary_summary = json.loads(PRIMARY_SUMMARY.read_text())

    primary_rows = rows_all[rows_all["in_primary"]].copy()
    augmented_rows = rows_all.copy()   # primary + experimental

    summary = {"rules_version": RULES_VERSION}

    # ─── §12.1 REPRICING-as-Constructive ──────────────────────────────────────
    print("\n§12.1 — REPRICING-as-Constructive sensitivity (primary universe)")
    s121 = {}
    s121_state_to_bucket = {s: b for b, states in S121_BUCKETS.items() for s in states}
    for h in HORIZONS:
        s121[f"{h}d"] = per_bucket_metrics(primary_rows, s121_state_to_bucket, h)
    summary["s12_1_REPRICING_as_Constructive"] = s121

    # ─── §12.2 Experimental-tickers-included ─────────────────────────────────
    print("\n§12.2 — Experimental-tickers-included sensitivity (primary + experimental cohort)")
    s122 = {}
    primary_state_to_bucket = {s: b for b, states in PRIMARY_BUCKETS.items() for s in states}
    for h in HORIZONS:
        s122[f"{h}d"] = per_bucket_metrics(augmented_rows, primary_state_to_bucket, h)
    summary["s12_2_experimental_included"] = s122

    # ─── Deltas vs locked primary ─────────────────────────────────────────────
    deltas = {"s12_1_vs_primary": {}, "s12_2_vs_primary": {}}
    for h in HORIZONS:
        for src_key, sens in (("s12_1", s121), ("s12_2", s122)):
            d_out = {}
            for bucket in ("Constructive", "Cautious", "Ambiguous"):
                primary_bucket = primary_summary["per_horizon"][f"{h}d"]["per_bucket"][bucket]
                sens_bucket = sens[f"{h}d"][bucket]
                if "avg_fwd_rel" in sens_bucket and primary_bucket["avg_fwd_rel"] is not None:
                    d_out[bucket] = {
                        "primary_avg":  primary_bucket["avg_fwd_rel"],
                        "sens_avg":     sens_bucket["avg_fwd_rel"],
                        "delta_avg":    sens_bucket["avg_fwd_rel"] - primary_bucket["avg_fwd_rel"],
                        "primary_n":    primary_bucket["n"],
                        "sens_n":       sens_bucket["n"],
                        "primary_baseline_diff": primary_bucket["baseline_avg_diff"],
                        "sens_baseline_diff":    sens_bucket["baseline_avg_diff"],
                    }
                else:
                    d_out[bucket] = {"primary_n": primary_bucket["n"], "sens_n": sens_bucket.get("n", 0)}
            deltas[f"{src_key}_vs_primary"][f"{h}d"] = d_out
    summary["deltas_vs_primary"] = deltas

    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nWrote {OUT_SUMMARY}")

    # ─── Console summary ──────────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("§12.1 — REPRICING-as-Constructive vs PRIMARY")
    print("=" * 72)
    for h in HORIZONS:
        print(f"\n  {h}D horizon:")
        for bucket in ("Constructive", "Cautious", "Ambiguous"):
            d = deltas["s12_1_vs_primary"][f"{h}d"][bucket]
            if "delta_avg" not in d:
                print(f"    {bucket:14s}  (no data)")
                continue
            print(
                f"    {bucket:14s}  primary n={d['primary_n']:>5} avg={d['primary_avg']:+.4f}  "
                f"|  sens n={d['sens_n']:>5} avg={d['sens_avg']:+.4f}  |  Δ_avg={d['delta_avg']:+.4f}  "
                f"|  primary_Δbaseline={d['primary_baseline_diff']:+.4f}  sens_Δbaseline={d['sens_baseline_diff']:+.4f}"
            )

    print()
    print("=" * 72)
    print("§12.2 — Experimental-tickers-INCLUDED vs PRIMARY")
    print("=" * 72)
    for h in HORIZONS:
        print(f"\n  {h}D horizon:")
        for bucket in ("Constructive", "Cautious", "Ambiguous"):
            d = deltas["s12_2_vs_primary"][f"{h}d"][bucket]
            if "delta_avg" not in d:
                print(f"    {bucket:14s}  (no data)")
                continue
            print(
                f"    {bucket:14s}  primary n={d['primary_n']:>5} avg={d['primary_avg']:+.4f}  "
                f"|  sens n={d['sens_n']:>5} avg={d['sens_avg']:+.4f}  |  Δ_avg={d['delta_avg']:+.4f}  "
                f"|  primary_Δbaseline={d['primary_baseline_diff']:+.4f}  sens_Δbaseline={d['sens_baseline_diff']:+.4f}"
            )


if __name__ == "__main__":
    main()
