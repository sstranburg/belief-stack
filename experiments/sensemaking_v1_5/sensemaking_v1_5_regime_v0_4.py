#!/usr/bin/env python3
"""
Sensemaking v1.5 v0.4 — Regime detector.

Per pre-registration v0.4 §3:
  Detector A: calendar_regime — A_early (T < 2026-03-01) vs B_later (>=)
  Detector B: vol_regime      — 20-day rolling realized vol on QQQ daily
                                returns; threshold = window-median rv;
                                LOW_VOL (< median) vs HIGH_VOL (>= median);
                                UNDEFINED for first 19 trading days

Outputs:
  data/sensemaking_v1_5_regimes_v0_4.parquet
    one row per trading day in the QQQ price series:
      date, daily_return, rolling_vol_20d, vol_regime, calendar_regime
"""

from __future__ import annotations

import json
import pathlib

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent
QQQ_PATH    = STORM_ROOT / "data" / "derived" / "prices" / "QQQ.parquet"
OUT_PARQUET = ROOT / "data" / "sensemaking_v1_5_regimes_v0_4.parquet"
OUT_SUMMARY = ROOT / "data" / "sensemaking_v1_5_regime_meta_v0_4.json"

RULES_VERSION    = "v0.4"
WINDOW_START     = pd.Timestamp("2025-12-05")
WINDOW_END       = pd.Timestamp("2026-05-26")
CALENDAR_CUT     = pd.Timestamp("2026-03-01")
VOL_WINDOW       = 20            # 20-day rolling realized vol
VOL_THRESHOLD_Q  = 0.50          # window median


def main() -> None:
    print("Loading QQQ price series…")
    qqq = pd.read_parquet(QQQ_PATH)
    qqq["timestamp"] = pd.to_datetime(qqq["timestamp"])
    qqq = qqq.sort_values("timestamp").reset_index(drop=True)

    # Restrict to a window large enough to cover the 20-day lookback before WINDOW_START
    lookback_buffer_start = WINDOW_START - pd.Timedelta(days=40)  # generous calendar buffer
    qqq = qqq[(qqq["timestamp"] >= lookback_buffer_start) & (qqq["timestamp"] <= WINDOW_END)].copy()
    qqq = qqq.reset_index(drop=True)

    # Daily returns (close-to-close)
    qqq["daily_return"] = qqq["close"].pct_change()

    # 20-day rolling realized vol (std of daily returns over trailing 20 trading days)
    # Use min_periods = VOL_WINDOW so only fully-formed windows count
    qqq["rolling_vol_20d"] = qqq["daily_return"].rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std()

    # Threshold = median of defined rolling_vol within the locked window
    in_window = qqq[(qqq["timestamp"] >= WINDOW_START) & (qqq["timestamp"] <= WINDOW_END)]
    defined = in_window["rolling_vol_20d"].dropna()
    threshold = float(np.quantile(defined.values, VOL_THRESHOLD_Q))
    print(f"  {len(defined):,} trading days with defined rolling_vol_20d in window")
    print(f"  window-median rolling_vol_20d = {threshold:.6f}")

    # Regime assignment
    def classify_vol(rv):
        if pd.isna(rv):
            return "UNDEFINED"
        return "LOW_VOL" if rv < threshold else "HIGH_VOL"

    qqq["vol_regime"] = qqq["rolling_vol_20d"].apply(classify_vol)
    qqq["calendar_regime"] = qqq["timestamp"].apply(
        lambda d: "A_early" if d < CALENDAR_CUT else "B_later"
    )

    # Restrict output to in-window rows only
    out = qqq[(qqq["timestamp"] >= WINDOW_START) & (qqq["timestamp"] <= WINDOW_END)].copy()
    out = out[["timestamp", "close", "daily_return", "rolling_vol_20d", "vol_regime", "calendar_regime"]].copy()
    out["date"] = out["timestamp"].dt.date.astype(str)

    OUT_PARQUET.parent.mkdir(exist_ok=True)
    out.to_parquet(OUT_PARQUET, index=False)

    # Meta summary
    counts = out["vol_regime"].value_counts().to_dict()
    cal_counts = out["calendar_regime"].value_counts().to_dict()
    # Cross-tab
    crosstab = pd.crosstab(out["calendar_regime"], out["vol_regime"]).to_dict()

    meta = {
        "rules_version":     RULES_VERSION,
        "window_start":      str(WINDOW_START.date()),
        "window_end":        str(WINDOW_END.date()),
        "calendar_cut":      str(CALENDAR_CUT.date()),
        "vol_window_days":   VOL_WINDOW,
        "vol_threshold_q":   VOL_THRESHOLD_Q,
        "vol_threshold_rv":  threshold,
        "n_trading_days_in_window": len(out),
        "vol_regime_counts": counts,
        "calendar_regime_counts": cal_counts,
        "crosstab_calendar_x_vol": crosstab,
    }
    OUT_SUMMARY.write_text(json.dumps(meta, indent=2, default=str))
    print(f"  wrote {OUT_PARQUET}")
    print(f"  wrote {OUT_SUMMARY}")

    print()
    print("=" * 72)
    print("V0.4 REGIME ASSIGNMENT SUMMARY")
    print("=" * 72)
    print(f"  Trading days in window: {len(out):,}")
    print(f"  Vol regime threshold:   rv = {threshold:.6f}  (window-median)")
    print()
    print("  Vol regime counts:")
    for k, v in counts.items():
        print(f"    {k:10s}  {v:>4}")
    print()
    print("  Calendar regime counts:")
    for k, v in cal_counts.items():
        print(f"    {k:10s}  {v:>4}")
    print()
    print("  Cross-tab (calendar × vol):")
    print(pd.crosstab(out["calendar_regime"], out["vol_regime"]))


if __name__ == "__main__":
    main()
