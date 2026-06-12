#!/usr/bin/env python3
"""
Sensemaking v1.5 v0.4 — Warrant coverage × regime (TERTIARY).
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
STATE_PATH     = ROOT / "data" / "sensemaking_v1_5_state_v0_4.parquet"
LIFECYCLE_PATH = ROOT / "data" / "sensemaking_v1_5_lifecycle_v0_4.parquet"
OUT_SUMMARY    = ROOT / "data" / "sensemaking_v1_5_coverage_summary_v0_4.json"

RULES_VERSION = "v0.4"
HORIZONS      = (5, 20)


def metric_block(rows, fwd_col):
    rows = rows[rows[fwd_col].notna()]
    n = len(rows)
    if n == 0:
        return {"n": 0}
    return {
        "n":             n,
        "avg_fwd_rel":   float(rows[fwd_col].mean()),
        "pct_positive_fwd_rel": float((rows[fwd_col] > 0).mean()),
    }


def main() -> None:
    print("Loading v0.4 state + lifecycle parquets…")
    state = pd.read_parquet(STATE_PATH)
    lc    = pd.read_parquet(LIFECYCLE_PATH)

    summary = {
        "rules_version": RULES_VERSION,
        "state":         {},
        "lifecycle":     {},
    }

    # State coverage × regime
    for h in HORIZONS:
        per_detector = {}
        for detector_key, regime_labels in (
            ("calendar_regime", ("A_early", "B_later")),
            ("vol_regime",      ("LOW_VOL", "HIGH_VOL")),
        ):
            per_regime = {}
            for r in regime_labels:
                regime_rows = state[state[detector_key] == r]
                per_partition = {}
                for sd in (True, False):
                    p_rows = regime_rows[regime_rows["sufficient_data"] == sd]
                    per_bucket = {}
                    for bucket in ("Constructive", "Cautious", "REPRICING_primary", "Early_followthrough", "Ambiguous"):
                        b_rows = p_rows[p_rows["bucket"] == bucket]
                        per_bucket[bucket] = metric_block(b_rows, f"fwd_rel_{h}d")
                    per_partition[f"sufficient_data_{sd}"] = per_bucket
                per_regime[r] = per_partition
            per_detector[detector_key] = per_regime
        summary["state"][f"{h}d"] = per_detector

    # Lifecycle coverage × regime
    for h in HORIZONS:
        per_detector = {}
        for detector_key, regime_labels in (
            ("calendar_regime", ("A_early", "B_later")),
            ("vol_regime",      ("LOW_VOL", "HIGH_VOL")),
        ):
            per_regime = {}
            for r in regime_labels:
                regime_rows = lc[lc[detector_key] == r]
                per_partition = {}
                for sd in (True, False):
                    p_rows = regime_rows[regime_rows["sufficient_data"] == sd]
                    per_bucket = {}
                    for lb in ("Constructive_revision", "Cautious_revision"):
                        b_rows = p_rows[p_rows["lifecycle_bucket"] == lb]
                        per_bucket[lb] = metric_block(b_rows, f"fwd_rel_{h}d")
                    c = per_bucket["Constructive_revision"].get("avg_fwd_rel")
                    k = per_bucket["Cautious_revision"].get("avg_fwd_rel")
                    per_bucket["internal_gap"] = (c - k) if (c is not None and k is not None) else None
                    per_partition[f"sufficient_data_{sd}"] = per_bucket
                per_regime[r] = per_partition
            per_detector[detector_key] = per_regime
        summary["lifecycle"][f"{h}d"] = per_detector

    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))
    print(f"  wrote {OUT_SUMMARY}")
    print()
    print("Coverage outputs written. Detail in JSON; not printing per-cell to avoid noise.")


if __name__ == "__main__":
    main()
