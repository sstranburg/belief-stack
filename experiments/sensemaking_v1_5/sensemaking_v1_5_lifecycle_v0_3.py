#!/usr/bin/env python3
"""
Sensemaking v1.5 v0.3 — Lifecycle revision-prediction (PRIMARY).

Per pre-registration v0.3 §3, §6.1:
  - Constructive_revision = {reconfirmed, strengthened} → Hit if fwd_rel > 0
  - Cautious_revision = {contradicted, weakened} → Hit if fwd_rel < 0
  - Baseline = v0.2 Ambiguous (MACRO + PRICE-LED + UNCLEAR) from state-bucket axis
  - Lifecycle event date = T; forward returns from per-ticker prices
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent

ROWS_PATH      = ROOT / "data" / "sensemaking_v1_5_rows.parquet"
LIFECYCLE_PATH = STORM_ROOT / "data" / "derived" / "expectation_lifecycle_events.parquet"
ENTITIES_PATH  = STORM_ROOT / "data" / "derived" / "expectation_entities.parquet"
OUT_PARQUET    = ROOT / "data" / "sensemaking_v1_5_lifecycle_v0_3.parquet"
OUT_SUMMARY    = ROOT / "data" / "sensemaking_v1_5_lifecycle_summary_v0_3.json"

RULES_VERSION = "v0.3"
HORIZONS      = (5, 20)

LIFECYCLE_BUCKETS = {
    "Constructive_revision": {"reconfirmed", "strengthened"},
    "Cautious_revision":     {"contradicted", "weakened"},
}
EVENT_TO_BUCKET = {e: b for b, evs in LIFECYCLE_BUCKETS.items() for e in evs}

AMBIGUOUS_STATES = {"MACRO", "PRICE-LED", "UNCLEAR"}  # v0.2/v0.3 baseline


def label_row(bucket: str, fwd_rel) -> str | None:
    if fwd_rel is None or pd.isna(fwd_rel):
        return None
    if bucket == "Constructive_revision":
        return "Hit" if fwd_rel > 0 else "FP"
    if bucket == "Cautious_revision":
        return "Hit" if fwd_rel < 0 else "FN"
    return None


def metric_block(rows: pd.DataFrame, fwd_col: str, label_col: str | None, direction: str | None) -> dict:
    rows = rows[rows[fwd_col].notna()]
    n = len(rows)
    if n == 0:
        return {"n": 0}
    out = {
        "n":              n,
        "avg_fwd_rel":    float(rows[fwd_col].mean()),
        "median_fwd_rel": float(rows[fwd_col].median()),
        "pct_positive_fwd_rel": float((rows[fwd_col] > 0).mean()),
    }
    if label_col:
        hits = int((rows[label_col] == "Hit").sum())
        if direction == "constructive":
            fp = int((rows[label_col] == "FP").sum())
            out["hits"] = hits
            out["false_positives"] = fp
            denom = hits + fp
            out["hit_rate"] = (hits / denom) if denom > 0 else None
        elif direction == "cautious":
            fn = int((rows[label_col] == "FN").sum())
            out["hits"] = hits
            out["false_negatives"] = fn
            denom = hits + fn
            out["hit_rate"] = (hits / denom) if denom > 0 else None
    return out


def main() -> None:
    print("Loading harness rows + lifecycle + entities…")
    rows = pd.read_parquet(ROWS_PATH)
    lc = pd.read_parquet(LIFECYCLE_PATH)
    entities = pd.read_parquet(ENTITIES_PATH)

    ticker_lookup = dict(zip(entities["entity_id"], entities["ticker"]))
    lc["ticker"] = lc["entity_id"].map(ticker_lookup)
    lc["date"]   = lc["date"].astype(str)

    # Filter to revision-class events
    lc = lc[lc["event_type"].isin(EVENT_TO_BUCKET)].copy()
    lc["lifecycle_bucket"] = lc["event_type"].map(EVENT_TO_BUCKET)
    print(f"  revision-class events: {len(lc):,}")

    # Restrict to primary-universe tickers
    primary_tickers = set(rows[rows["in_primary"]]["ticker"].unique())
    lc = lc[lc["ticker"].isin(primary_tickers)].copy()
    print(f"  events restricted to primary tickers: {len(lc):,}")

    # Join harness rows on (date, ticker) for forward returns
    rows_for_join = rows[["date", "ticker", "fwd_rel_5d", "fwd_rel_20d", "in_primary", "sufficient_data"]].copy()
    rows_for_join["date"]   = rows_for_join["date"].astype(str)
    rows_for_join["ticker"] = rows_for_join["ticker"].astype(str)
    lc_joined = lc.merge(rows_for_join, on=["date", "ticker"], how="left")

    matched = lc_joined["fwd_rel_5d"].notna() | lc_joined["fwd_rel_20d"].notna()
    print(f"  matched to harness row: {matched.sum():,} / {len(lc_joined):,}")
    lc_joined["matched_to_harness"] = matched

    # Restrict to primary-universe matches
    lc_primary = lc_joined[lc_joined["in_primary"] == True].copy()

    # Labels per horizon
    for h in HORIZONS:
        lc_primary[f"label_{h}d"] = [
            label_row(b, v) for b, v in zip(lc_primary["lifecycle_bucket"], lc_primary[f"fwd_rel_{h}d"])
        ]

    OUT_PARQUET.parent.mkdir(exist_ok=True)
    lc_primary.to_parquet(OUT_PARQUET, index=False)

    # Baseline rows from state-bucket axis
    state_primary = rows[rows["in_primary"]].copy()
    baseline_rows = state_primary[state_primary["state"].isin(AMBIGUOUS_STATES)]

    summary: dict = {
        "rules_version":     RULES_VERSION,
        "matched_to_harness": int(matched.sum()),
        "unmatched":          int((~matched).sum()),
        "per_horizon":        {},
    }

    for h in HORIZONS:
        fwd_col = f"fwd_rel_{h}d"
        per_bucket = {}
        for lb in ("Constructive_revision", "Cautious_revision"):
            rows_lb = lc_primary[lc_primary["lifecycle_bucket"] == lb]
            direction = "constructive" if lb == "Constructive_revision" else "cautious"
            per_bucket[lb] = metric_block(rows_lb, fwd_col, f"label_{h}d", direction)

        ambig = baseline_rows[baseline_rows[fwd_col].notna()]
        baseline_avg = float(ambig[fwd_col].mean()) if len(ambig) else None
        per_bucket["Ambiguous_baseline_v0_2"] = {
            "n":           len(ambig),
            "avg_fwd_rel": baseline_avg,
            "median_fwd_rel": float(ambig[fwd_col].median()) if len(ambig) else None,
            "pct_positive_fwd_rel": float((ambig[fwd_col] > 0).mean()) if len(ambig) else None,
        }

        for k in ("Constructive_revision", "Cautious_revision"):
            if per_bucket[k].get("avg_fwd_rel") is not None and baseline_avg is not None:
                per_bucket[k]["baseline_avg_diff"] = per_bucket[k]["avg_fwd_rel"] - baseline_avg
            else:
                per_bucket[k]["baseline_avg_diff"] = None

        # Internal gap (the v0.2 finding to test)
        c_avg = per_bucket["Constructive_revision"].get("avg_fwd_rel")
        k_avg = per_bucket["Cautious_revision"].get("avg_fwd_rel")
        per_bucket["internal_gap_constructive_minus_cautious"] = (
            (c_avg - k_avg) if (c_avg is not None and k_avg is not None) else None
        )
        summary["per_horizon"][f"{h}d"] = per_bucket

    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))
    print(f"  wrote {OUT_PARQUET}")
    print(f"  wrote {OUT_SUMMARY}")

    # Console summary
    for h in HORIZONS:
        print()
        print("=" * 72)
        print(f"V0.3 PRIMARY (LIFECYCLE) — {h}D HORIZON")
        print("=" * 72)
        p = summary["per_horizon"][f"{h}d"]
        for lb in ("Constructive_revision", "Cautious_revision", "Ambiguous_baseline_v0_2"):
            r = p[lb]
            n = r["n"]
            if n == 0:
                print(f"  {lb:30s}  n=0")
                continue
            avg = f"{r.get('avg_fwd_rel'):+.4f}"
            med = f"{r.get('median_fwd_rel'):+.4f}"
            pct = f"{r.get('pct_positive_fwd_rel'):.3f}"
            d   = r.get("baseline_avg_diff")
            dd  = f"{d:+.4f}" if d is not None else "—"
            hr  = r.get("hit_rate")
            hrf = f"{hr:.3f}" if hr is not None else "n/a"
            print(f"  {lb:30s}  n={n:>4}  avg={avg}  med={med}  %pos={pct}  Δbase={dd}  hit_rate={hrf}")
        gap = p["internal_gap_constructive_minus_cautious"]
        if gap is not None:
            print(f"  {'INTERNAL GAP (constructive − cautious)':30s}  {gap:+.4f}")


if __name__ == "__main__":
    main()
