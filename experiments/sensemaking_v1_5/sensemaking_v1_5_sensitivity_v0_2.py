#!/usr/bin/env python3
"""
Sensemaking v1.5 v0.2 — Sensitivity appendix.

Per pre-registration §12 (v0.2 restructure):
  §12.1 Direction-naive REPRICING reverse: collapse REPRICING back to single
        Ambiguous-bucket entry (the v0.1 mapping). Cleanest test of whether
        the direction-aware split is doing real work.
  §12.2 EARLY-as-Constructive reverse: fold EARLY back into Constructive
        (the v0.1 mapping). Tests whether EARLY isolation matters.
  §12.3 Experimental-tickers-included: preserved from v0.1 §12.2.

Reads:
  sensemaking_v1_5/data/sensemaking_v1_5_rows.parquet
  sensemaking_v1_5/data/sensemaking_v1_5_primary_summary_v0_2.json
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
ROWS_PATH        = ROOT / "data" / "sensemaking_v1_5_rows.parquet"
PRIMARY_V02_PATH = ROOT / "data" / "sensemaking_v1_5_primary_summary_v0_2.json"
OUT_SUMMARY      = ROOT / "data" / "sensemaking_v1_5_sensitivity_summary_v0_2.json"

RULES_VERSION = "v0.2"
HORIZONS      = (5, 20)

# v0.2 primary mapping (for reference)
V02_STATE_TO_BUCKET = {
    "CONFIRMED":         "Constructive",
    "DISAGREEMENT":      "Constructive",
    "NEG_CONFIRMATION":  "Cautious",
    "DIVERGENCE":        "Cautious",
    "EARLY":             "Early_followthrough",
    "MACRO":             "Ambiguous",
    "PRICE-LED":         "Ambiguous",
    "UNCLEAR":           "Ambiguous",
}

# §12.1 — direction-naive REPRICING: REPRICING → Ambiguous (regardless of direction)
# §12.2 — EARLY back to Constructive


def bucket_for_row(state: str, direction: int, mode: str) -> str:
    """
    mode ∈ {"v0_2_primary", "s12_1_naive_repricing", "s12_2_early_constructive", "v0_2_with_experimental"}.
    """
    if state == "REPRICING":
        if mode == "s12_1_naive_repricing":
            return "Ambiguous"
        # All other modes use v0.2 direction split
        if direction == 1:
            return "Constructive"
        if direction == -1:
            return "Cautious"
        return "Ambiguous"
    if state == "EARLY":
        if mode == "s12_2_early_constructive":
            return "Constructive"
        return "Early_followthrough"
    return V02_STATE_TO_BUCKET.get(state, "Unknown")


def metrics_block(df: pd.DataFrame, mode: str, horizon: int) -> dict:
    fwd_col = f"fwd_rel_{horizon}d"
    df = df.copy()
    df["bucket"] = [bucket_for_row(s, int(d), mode) for s, d in zip(df["state"], df["direction"])]
    df = df[df[fwd_col].notna()]

    ambig = df[df["bucket"] == "Ambiguous"]
    baseline_avg = float(ambig[fwd_col].mean()) if len(ambig) else None

    out = {}
    for bucket in ("Constructive", "Cautious", "Early_followthrough", "Ambiguous"):
        rows = df[df["bucket"] == bucket]
        n = len(rows)
        if n == 0:
            out[bucket] = {"n": 0}
            continue
        avg = float(rows[fwd_col].mean())
        pct = float((rows[fwd_col] > 0).mean())
        out[bucket] = {
            "n":                    n,
            "avg_fwd_rel":          avg,
            "median_fwd_rel":       float(rows[fwd_col].median()),
            "pct_positive_fwd_rel": pct,
            "baseline_avg_diff":    (avg - baseline_avg) if baseline_avg is not None else None,
        }
    return out


def main() -> None:
    print("Loading harness rows + v0.2 primary summary…")
    rows_all = pd.read_parquet(ROWS_PATH)
    primary_v02 = json.loads(PRIMARY_V02_PATH.read_text())
    primary_rows = rows_all[rows_all["in_primary"]].copy()
    augmented_rows = rows_all.copy()

    summary = {"rules_version": RULES_VERSION}

    # §12.1 direction-naive REPRICING reverse
    print("§12.1 direction-naive REPRICING reverse…")
    s121 = {f"{h}d": metrics_block(primary_rows, "s12_1_naive_repricing", h) for h in HORIZONS}
    summary["s12_1_naive_repricing"] = s121

    # §12.2 EARLY-as-Constructive reverse
    print("§12.2 EARLY-as-Constructive reverse…")
    s122 = {f"{h}d": metrics_block(primary_rows, "s12_2_early_constructive", h) for h in HORIZONS}
    summary["s12_2_early_constructive"] = s122

    # §12.3 Experimental included (uses v0.2 primary mapping with augmented universe)
    print("§12.3 experimental-tickers-included…")
    s123 = {f"{h}d": metrics_block(augmented_rows, "v0_2_with_experimental", h) for h in HORIZONS}
    summary["s12_3_experimental_included"] = s123

    # Deltas vs v0.2 primary
    deltas = {}
    for src_key, sens in (("s12_1_vs_primary", s121),
                          ("s12_2_vs_primary", s122),
                          ("s12_3_vs_primary", s123)):
        d_out = {}
        for h in HORIZONS:
            per_b = {}
            for bucket in ("Constructive", "Cautious", "Early_followthrough", "Ambiguous"):
                primary_b = primary_v02["per_horizon"][f"{h}d"]["per_bucket"][bucket]
                sens_b = sens[f"{h}d"][bucket]
                if "avg_fwd_rel" in sens_b and primary_b.get("avg_fwd_rel") is not None:
                    per_b[bucket] = {
                        "primary_n":   primary_b["n"],
                        "primary_avg": primary_b["avg_fwd_rel"],
                        "sens_n":      sens_b["n"],
                        "sens_avg":    sens_b["avg_fwd_rel"],
                        "delta_avg":   sens_b["avg_fwd_rel"] - primary_b["avg_fwd_rel"],
                        "primary_baseline_diff": primary_b.get("baseline_avg_diff"),
                        "sens_baseline_diff":    sens_b.get("baseline_avg_diff"),
                    }
                else:
                    per_b[bucket] = {"primary_n": primary_b.get("n", 0), "sens_n": sens_b.get("n", 0)}
            d_out[f"{h}d"] = per_b
        deltas[src_key] = d_out
    summary["deltas_vs_primary"] = deltas

    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nWrote {OUT_SUMMARY}")

    # Console
    for label, key in (
        ("§12.1 direction-naive REPRICING vs V0.2 PRIMARY", "s12_1_vs_primary"),
        ("§12.2 EARLY-as-Constructive vs V0.2 PRIMARY",     "s12_2_vs_primary"),
        ("§12.3 Experimental-included vs V0.2 PRIMARY",     "s12_3_vs_primary"),
    ):
        print()
        print("=" * 72)
        print(label)
        print("=" * 72)
        for h in HORIZONS:
            print(f"\n  {h}D horizon:")
            for bucket in ("Constructive", "Cautious", "Early_followthrough", "Ambiguous"):
                d = deltas[key][f"{h}d"][bucket]
                if "delta_avg" not in d:
                    print(f"    {bucket:22s}  (no data)")
                    continue
                print(
                    f"    {bucket:22s}  primary n={d['primary_n']:>5} avg={d['primary_avg']:+.4f}  "
                    f"|  sens n={d['sens_n']:>5} avg={d['sens_avg']:+.4f}  |  Δ_avg={d['delta_avg']:+.4f}  "
                    f"|  primary_Δbase={d['primary_baseline_diff']:+.4f}  sens_Δbase={d['sens_baseline_diff']:+.4f}"
                )


if __name__ == "__main__":
    main()
