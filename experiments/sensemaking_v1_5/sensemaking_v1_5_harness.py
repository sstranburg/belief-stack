#!/usr/bin/env python3
"""
Sensemaking v1.5 — Harness (Phase B, stage 1).

Reads:
  data/derived/backtest_history.parquet  (variant = "baseline" only, per I-001)
  data/derived/prices/<TICKER>.parquet   (per-ticker close prices)
  data/derived/prices/QQQ.parquet        (benchmark)

Writes:
  sensemaking_v1_5/data/sensemaking_v1_5_rows.parquet
    one row per (date, ticker) — the unit of v0.1 evaluation per §2.3.

Applies §7 exclusions explicitly:
  1. State missing or UNCLASSIFIED → row excluded (in_primary = False, reason logged)
  2. Price data missing for T, T+5, or T+20 → that horizon's fwd_rel is null,
     excluded_5d / excluded_20d carries the reason
  3. T+N falls outside the window → that horizon excluded
  4. Ticker in EXPERIMENTAL_TICKERS (USAR, MP, ODC) → row marked
     is_experimental = True; excluded from primary unless §12.2 sensitivity
     re-includes it. The harness emits all 31 primary + 1 experimental
     (MP — the only experimental in backtest_history per I-002).
  + I-002 universe gap: rows where ticker absent from backtest_history cannot
    be emitted; the 8 post-window non-experimental tickers are noted in stdout
    but not in the rows parquet.

No measurement interpretation. Bucketing and Hit/FP/FN labeling are stage 2.
"""

from __future__ import annotations

import json
import pathlib
from datetime import date

import pandas as pd

# ─── Paths ───────────────────────────────────────────────────────────────────

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent
BACKTEST_HISTORY_PATH = STORM_ROOT / "data" / "derived" / "backtest_history.parquet"
PRICES_DIR            = STORM_ROOT / "data" / "derived" / "prices"
ACTORS_JSON_PATH      = STORM_ROOT.parent / "topicspace-site" / "public" / "actors.json"
OUT_PATH              = ROOT / "data" / "sensemaking_v1_5_rows.parquet"

# ─── Locked v0.1 constants ───────────────────────────────────────────────────

RULES_VERSION    = "v0.1"
WINDOW_START     = pd.Timestamp("2025-12-05")
WINDOW_END       = pd.Timestamp("2026-05-26")
BENCHMARK        = "QQQ"
HORIZONS_DAYS    = (5, 20)
VARIANT          = "baseline"                # I-001
EXPERIMENTAL_TICKERS = frozenset({"USAR", "MP", "ODC"})  # §2.2


# ─── Helpers ─────────────────────────────────────────────────────────────────

def load_price_series(ticker: str) -> pd.DataFrame | None:
    p = PRICES_DIR / f"{ticker}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    df = df.drop_duplicates(subset="timestamp", keep="last")
    return df[["timestamp", "close"]]


def lookup_close_at_offset(
    px: pd.DataFrame,
    base_date: pd.Timestamp,
    offset_trading_days: int,
) -> tuple[float | None, pd.Timestamp | None, str | None]:
    """
    Find the close price `offset_trading_days` trading days after base_date.
    Trading days are inferred from the px index (rows present = traded days).
    Returns (close, actual_date, exclusion_reason).
    """
    # Locate base_date in px
    match = px[px["timestamp"] == base_date]
    if match.empty:
        return None, None, "base_date_missing"
    base_idx = match.index[0]
    target_idx = base_idx + offset_trading_days
    if target_idx >= len(px):
        return None, None, "horizon_outside_series"
    target_row = px.iloc[target_idx]
    return float(target_row["close"]), pd.Timestamp(target_row["timestamp"]), None


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Loading backtest_history.parquet…")
    bh = pd.read_parquet(BACKTEST_HISTORY_PATH)
    print(f"  total rows: {len(bh):,}")

    # I-001: restrict to baseline variant
    bh = bh[bh["variant"] == VARIANT].copy()
    print(f"  after variant=baseline filter: {len(bh):,}")

    # Restrict to locked window
    bh["date"] = pd.to_datetime(bh["date"])
    bh = bh[(bh["date"] >= WINDOW_START) & (bh["date"] <= WINDOW_END)].copy()
    print(f"  after window filter: {len(bh):,}")
    print(f"  date range observed: {bh['date'].min().date()} → {bh['date'].max().date()}")
    bh_tickers = sorted(bh["ticker"].unique())
    print(f"  tickers in backtest_history: {len(bh_tickers)}")

    # I-002: actors.json gap surveillance
    actors_json = json.loads(ACTORS_JSON_PATH.read_text())["actors"]
    aj_tickers = sorted([a["t"] for a in actors_json])
    gap = sorted(set(aj_tickers) - set(bh_tickers))
    print(f"  actors.json tickers: {len(aj_tickers)}")
    print(f"  in actors.json but absent from backtest_history (I-002): {gap}")

    # Load benchmark prices
    print(f"\nLoading benchmark prices ({BENCHMARK})…")
    qqq_px = load_price_series(BENCHMARK)
    if qqq_px is None:
        raise SystemExit(f"FATAL: {BENCHMARK} prices not found at {PRICES_DIR / (BENCHMARK + '.parquet')}")
    print(f"  {len(qqq_px)} trading days from {qqq_px['timestamp'].min().date()} to {qqq_px['timestamp'].max().date()}")

    # Per-ticker price cache
    print("\nLoading per-ticker prices…")
    px_cache: dict[str, pd.DataFrame] = {}
    for t in bh_tickers:
        ts = load_price_series(t)
        if ts is None:
            print(f"  WARN: prices missing for {t}; rows will be excluded")
        else:
            px_cache[t] = ts

    # Compute rows
    print(f"\nEmitting rows ({len(bh):,} (date, ticker) pairs × 2 horizons)…")
    out_records: list[dict] = []
    exclusion_counts = {
        "state_missing_or_unclassified": 0,
        "ticker_prices_missing":          0,
        "base_date_missing_in_prices":    0,
        "base_date_missing_in_qqq":       0,
        # Per-horizon exclusions
        "horizon_5d_outside_window":      0,
        "horizon_20d_outside_window":     0,
        "horizon_5d_outside_series":      0,
        "horizon_20d_outside_series":     0,
        "qqq_horizon_5d_outside_series":  0,
        "qqq_horizon_20d_outside_series": 0,
    }

    for row in bh.itertuples(index=False):
        d           = pd.Timestamp(row.date)
        ticker      = row.ticker
        state       = row.state
        narr        = int(row.narr)
        nds         = float(row.nds)
        rel         = float(row.rel)
        direction   = int(row.direction)
        sufficient  = bool(row.sufficient_data)
        is_exp      = ticker in EXPERIMENTAL_TICKERS

        # §7.1 — state missing/UNCLASSIFIED
        if state in (None, "", "UNCLASSIFIED") or pd.isna(state):
            exclusion_counts["state_missing_or_unclassified"] += 1
            continue

        # Per-ticker prices
        px = px_cache.get(ticker)
        if px is None:
            exclusion_counts["ticker_prices_missing"] += 1
            continue

        # Base-date close on both ticker and QQQ
        base_row = px[px["timestamp"] == d]
        if base_row.empty:
            exclusion_counts["base_date_missing_in_prices"] += 1
            continue
        base_close = float(base_row.iloc[0]["close"])

        qqq_base = qqq_px[qqq_px["timestamp"] == d]
        if qqq_base.empty:
            exclusion_counts["base_date_missing_in_qqq"] += 1
            continue
        qqq_base_close = float(qqq_base.iloc[0]["close"])

        per_horizon = {}
        for h in HORIZONS_DAYS:
            fwd_close, fwd_date, fwd_excl = lookup_close_at_offset(px, d, h)
            qqq_fwd_close, qqq_fwd_date, qqq_fwd_excl = lookup_close_at_offset(qqq_px, d, h)

            # §7.3 — T+N falls outside the locked window
            if fwd_date is not None and fwd_date > WINDOW_END:
                fwd_close = None
                fwd_excl = "horizon_outside_window"
                exclusion_counts[f"horizon_{h}d_outside_window"] += 1
            if qqq_fwd_date is not None and qqq_fwd_date > WINDOW_END:
                qqq_fwd_close = None
                qqq_fwd_excl = "horizon_outside_window"

            # §7.2 — price data missing
            if fwd_close is None:
                if fwd_excl == "horizon_outside_series":
                    exclusion_counts[f"horizon_{h}d_outside_series"] += 1
                per_horizon[h] = {"fwd_rel": None, "excluded_reason": fwd_excl}
                continue
            if qqq_fwd_close is None:
                if qqq_fwd_excl == "horizon_outside_series":
                    exclusion_counts[f"qqq_horizon_{h}d_outside_series"] += 1
                per_horizon[h] = {"fwd_rel": None, "excluded_reason": qqq_fwd_excl or "qqq_horizon_missing"}
                continue

            fwd_ret      = (fwd_close - base_close) / base_close
            qqq_fwd_ret  = (qqq_fwd_close - qqq_base_close) / qqq_base_close
            per_horizon[h] = {
                "fwd_rel":          fwd_ret - qqq_fwd_ret,
                "fwd_ret":          fwd_ret,
                "qqq_fwd_ret":      qqq_fwd_ret,
                "fwd_date":         fwd_date.date().isoformat(),
                "excluded_reason":  None,
            }

        out_records.append({
            "date":             d.date().isoformat(),
            "ticker":           ticker,
            "state":            state,
            "narr":             narr,
            "nds":              nds,
            "rel":              rel,
            "direction":        direction,
            "sufficient_data":  sufficient,
            "is_experimental":  is_exp,
            "in_primary":       not is_exp,        # §2.2: experimentals excluded from primary
            "fwd_rel_5d":       per_horizon.get(5, {}).get("fwd_rel"),
            "fwd_rel_20d":      per_horizon.get(20, {}).get("fwd_rel"),
            "fwd_ret_5d":       per_horizon.get(5, {}).get("fwd_ret"),
            "fwd_ret_20d":      per_horizon.get(20, {}).get("fwd_ret"),
            "qqq_fwd_ret_5d":   per_horizon.get(5, {}).get("qqq_fwd_ret"),
            "qqq_fwd_ret_20d":  per_horizon.get(20, {}).get("qqq_fwd_ret"),
            "fwd_date_5d":      per_horizon.get(5, {}).get("fwd_date"),
            "fwd_date_20d":     per_horizon.get(20, {}).get("fwd_date"),
            "excluded_5d":      per_horizon.get(5, {}).get("excluded_reason"),
            "excluded_20d":     per_horizon.get(20, {}).get("excluded_reason"),
        })

    out = pd.DataFrame(out_records)
    OUT_PATH.parent.mkdir(exist_ok=True)
    out.to_parquet(OUT_PATH, index=False)

    print(f"\nWrote {OUT_PATH} ({len(out):,} rows)")
    print()
    print("=" * 72)
    print("HARNESS RUN SUMMARY (rules v0.1)")
    print("=" * 72)
    print(f"  evaluation rows emitted:    {len(out):,}")
    print(f"  primary universe rows:      {len(out[out['in_primary']]):,}")
    print(f"  experimental cohort rows:   {len(out[~out['in_primary']]):,}")
    print()
    print(f"  rows with valid fwd_rel_5d:  {out['fwd_rel_5d'].notna().sum():,}")
    print(f"  rows with valid fwd_rel_20d: {out['fwd_rel_20d'].notna().sum():,}")
    print()
    print("Exclusion counts:")
    for k, v in exclusion_counts.items():
        if v:
            print(f"  {k:40s}  {v:6,}")
    print()
    print("Per-state row counts (primary):")
    primary = out[out["in_primary"]]
    state_counts = primary["state"].value_counts()
    for state, n in state_counts.items():
        valid_5d = primary[(primary["state"] == state) & primary["fwd_rel_5d"].notna()].shape[0]
        valid_20d = primary[(primary["state"] == state) & primary["fwd_rel_20d"].notna()].shape[0]
        print(f"  {state:18s}  total={n:5,}  valid_5d={valid_5d:5,}  valid_20d={valid_20d:5,}")
    print()
    print(f"sufficient_data = True (primary):  {primary['sufficient_data'].sum():,}")
    print(f"sufficient_data = False (primary): {(~primary['sufficient_data']).sum():,}")


if __name__ == "__main__":
    main()
