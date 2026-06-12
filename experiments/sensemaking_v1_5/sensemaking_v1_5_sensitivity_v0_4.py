#!/usr/bin/env python3
"""
Sensemaking v1.5 v0.4 — Sensitivity appendix.

Per pre-registration v0.4 §13:
  §13.1 Calendar vs volatility regime cross-tab agreement
  §13.2 Volatility threshold sensitivity (33rd / 50th / 67th percentile)
  §13.3 Event-type granularity (preserved from v0.3 §12.1, stratified by regime)
"""

from __future__ import annotations

import json
import pathlib

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent
STATE_PATH     = ROOT / "data" / "sensemaking_v1_5_state_v0_4.parquet"
LIFECYCLE_PATH = ROOT / "data" / "sensemaking_v1_5_lifecycle_v0_4.parquet"
REGIMES_PATH   = ROOT / "data" / "sensemaking_v1_5_regimes_v0_4.parquet"
QQQ_PATH       = STORM_ROOT / "data" / "derived" / "prices" / "QQQ.parquet"
OUT_SUMMARY    = ROOT / "data" / "sensemaking_v1_5_sensitivity_summary_v0_4.json"

RULES_VERSION    = "v0.4"
HORIZONS         = (5, 20)
VOL_WINDOW       = 20
WINDOW_START     = pd.Timestamp("2025-12-05")
WINDOW_END       = pd.Timestamp("2026-05-26")


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


def recompute_regimes_at_threshold(qqq: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Re-classify regimes given an alternate threshold; returns date+vol_regime."""
    out = qqq[["timestamp", "rolling_vol_20d"]].copy()
    out["date"] = out["timestamp"].dt.date.astype(str)
    def cls(rv):
        if pd.isna(rv):
            return "UNDEFINED"
        return "LOW_VOL" if rv < threshold else "HIGH_VOL"
    out["vol_regime"] = out["rolling_vol_20d"].apply(cls)
    return out[["date", "vol_regime"]]


def main() -> None:
    print("Loading inputs…")
    state = pd.read_parquet(STATE_PATH)
    lc    = pd.read_parquet(LIFECYCLE_PATH)
    regimes = pd.read_parquet(REGIMES_PATH)

    summary = {"rules_version": RULES_VERSION}

    # ─── §13.1 Cross-detector agreement ──────────────────────────────────────
    print("§13.1 cross-detector agreement…")
    # Use regime per-trading-day (one row per date), not per (T, ticker)
    crosstab_days = (
        pd.crosstab(regimes["calendar_regime"], regimes["vol_regime"])
        .to_dict()
    )
    # Also at the (T, ticker) level since this is what evaluation rows see
    crosstab_rows = (
        pd.crosstab(state["calendar_regime"], state["vol_regime"])
        .to_dict()
    )
    summary["s13_1_crosstab_trading_days"] = crosstab_days
    summary["s13_1_crosstab_evaluation_rows"] = crosstab_rows

    # ─── §13.2 Volatility threshold sensitivity ──────────────────────────────
    print("§13.2 volatility threshold sensitivity…")
    qqq = pd.read_parquet(QQQ_PATH)
    qqq["timestamp"] = pd.to_datetime(qqq["timestamp"])
    qqq = qqq.sort_values("timestamp").reset_index(drop=True)
    lookback_buffer_start = WINDOW_START - pd.Timedelta(days=40)
    qqq = qqq[(qqq["timestamp"] >= lookback_buffer_start) & (qqq["timestamp"] <= WINDOW_END)].copy().reset_index(drop=True)
    qqq["daily_return"] = qqq["close"].pct_change()
    qqq["rolling_vol_20d"] = qqq["daily_return"].rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std()
    in_window = qqq[(qqq["timestamp"] >= WINDOW_START) & (qqq["timestamp"] <= WINDOW_END)]
    defined = in_window["rolling_vol_20d"].dropna().values

    threshold_results = {}
    for q_label, q in (("p33", 0.33), ("p50", 0.50), ("p67", 0.67)):
        thr = float(np.quantile(defined, q))
        new_regimes = recompute_regimes_at_threshold(qqq, thr)
        new_regimes["date"] = new_regimes["date"].astype(str)
        # Join onto state rows (left, replacing vol_regime)
        state_alt = state.drop(columns=["vol_regime"]).merge(
            new_regimes.rename(columns={"vol_regime": "vol_regime_alt"}),
            on="date", how="left",
        )
        per_horizon = {}
        for h in HORIZONS:
            fwd_col = f"fwd_rel_{h}d"
            per_regime = {}
            for r in ("LOW_VOL", "HIGH_VOL"):
                sub = state_alt[state_alt["vol_regime_alt"] == r]
                per_bucket = {}
                for bucket in ("Constructive", "Cautious", "REPRICING_primary", "Early_followthrough", "Ambiguous"):
                    b_rows = sub[sub["bucket"] == bucket]
                    per_bucket[bucket] = metric_block(b_rows, fwd_col)
                # baseline diff vs ambiguous in this regime+threshold
                base_avg = per_bucket["Ambiguous"].get("avg_fwd_rel")
                for bucket in ("Constructive", "Cautious", "REPRICING_primary", "Early_followthrough"):
                    if per_bucket[bucket].get("avg_fwd_rel") is not None and base_avg is not None:
                        per_bucket[bucket]["baseline_avg_diff"] = per_bucket[bucket]["avg_fwd_rel"] - base_avg
                    else:
                        per_bucket[bucket]["baseline_avg_diff"] = None
                per_regime[r] = per_bucket
            per_horizon[f"{h}d"] = per_regime
        threshold_results[q_label] = {
            "quantile":  q,
            "threshold_rv": thr,
            "per_horizon": per_horizon,
        }
    summary["s13_2_threshold_sensitivity"] = threshold_results

    # ─── §13.3 Event-type granularity × regime ──────────────────────────────
    print("§13.3 event-type granularity × regime…")
    granular = {}
    for h in HORIZONS:
        fwd_col = f"fwd_rel_{h}d"
        per_event = {}
        for ev in ("reconfirmed", "strengthened", "contradicted", "weakened"):
            ev_rows = lc[lc["event_type"] == ev]
            row_block = {
                "aggregate": metric_block(ev_rows, fwd_col),
            }
            for detector_key, regime_labels in (
                ("calendar_regime", ("A_early", "B_later")),
                ("vol_regime",      ("LOW_VOL", "HIGH_VOL")),
            ):
                per_regime = {}
                for r in regime_labels:
                    sub = ev_rows[ev_rows[detector_key] == r]
                    per_regime[r] = metric_block(sub, fwd_col)
                row_block[detector_key] = per_regime
            per_event[ev] = row_block
        granular[f"{h}d"] = per_event
    summary["s13_3_event_type_granularity"] = granular

    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))
    print(f"  wrote {OUT_SUMMARY}")

    # Console
    print()
    print("=" * 72)
    print("§13.1 CROSS-DETECTOR AGREEMENT — (calendar × vol) at evaluation-row level")
    print("=" * 72)
    print(pd.crosstab(state["calendar_regime"], state["vol_regime"]))

    print()
    print("=" * 72)
    print("§13.2 THRESHOLD SENSITIVITY — Constructive at 20D vs window-baseline")
    print("=" * 72)
    for q_label in ("p33", "p50", "p67"):
        r = threshold_results[q_label]
        h = r["per_horizon"]["20d"]
        low_constr = h["LOW_VOL"]["Constructive"]
        high_constr = h["HIGH_VOL"]["Constructive"]
        print(f"\n  {q_label}  (threshold rv = {r['threshold_rv']:.6f}):")
        print(f"    LOW_VOL Constructive   n={low_constr.get('n',0):>4}  avg={low_constr.get('avg_fwd_rel', 0):+.4f}  Δbase={low_constr.get('baseline_avg_diff', 0):+.4f}")
        print(f"    HIGH_VOL Constructive  n={high_constr.get('n',0):>4}  avg={high_constr.get('avg_fwd_rel', 0):+.4f}  Δbase={high_constr.get('baseline_avg_diff', 0):+.4f}")


if __name__ == "__main__":
    main()
