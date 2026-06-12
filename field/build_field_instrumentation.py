#!/usr/bin/env python3
"""
build_field_instrumentation.py

L1 field instrumentation V1.

Treats the embedded event corpus as a time-enabled semantic field and
computes per-(actor, date) field statistics. Runs alongside `narr` for
validation; does NOT replace it.

Reads:
  data/normalized/tech_ecosystem.jsonl     (events with actor links, source, timestamp)
  data/derived/event_embeddings.parquet    (per-event 1536-d embeddings)
  data/derived/backtest_history.parquet    (the trading-day grid)

Writes:
  data/derived/field_instrumentation.parquet
    columns: date, ticker, event_count_7d, event_count_30d,
             semantic_density_7d, semantic_density_30d, density_momentum,
             source_weighted_density, novelty_score, drift, dispersion,
             cluster_id_primary, cluster_label,
             nearest_event_ids, nearest_event_titles, top_neighbor_actors

  topicspace-site/public/field_actor.json
    { as_of, actors: { TICKER: { metric: value, ... } } }
    Today-only snapshot used by the actor-page debug panel.

Usage:
  source venv/bin/activate && python scripts/build_field_instrumentation.py
  python scripts/build_field_instrumentation.py --tickers NVDA,AMD --tail 10
"""

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


ROOT = Path(__file__).parent.parent
# Match build_backtest_history + embed_events: read from filtered + backfill
# so the field corpus matches narr's corpus exactly.
DEFAULT_SOURCES = [
    ROOT / "data" / "normalized" / "tech_ecosystem_filtered.jsonl",
    ROOT / "data" / "normalized" / "tech_ecosystem_backfill.jsonl",
]
LEGACY_SOURCE   = ROOT / "data" / "normalized" / "tech_ecosystem.jsonl"
EMB_PATH    = ROOT / "data" / "derived" / "event_embeddings.parquet"
HIST_PATH   = ROOT / "data" / "derived" / "backtest_history.parquet"
OUT_PARQ    = ROOT / "data" / "derived" / "field_instrumentation.parquet"
OUT_JSON    = ROOT.parent / "topicspace-site" / "public" / "field_actor.json"

DEGENERATE_TEXT_LEN = 30   # combined title+text len below this → event excluded from density

WINDOW_7D  = 7
WINDOW_30D = 30
COSINE_DEADBAND = 0.30  # only count neighbors with cosine sim above this as "density"


# ── Helpers ─────────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]+")
_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "into", "over",
    "amid", "amid", "says", "said", "will", "have", "more", "less",
    "after", "before", "what", "when", "where", "how", "why", "who",
    "company", "stock", "shares", "stocks", "market", "year",
    "report", "reports", "news", "update", "today",
}


def top_tokens(titles: list[str], k: int = 3) -> str:
    """Cheap TF-style cluster labeler: top N non-stopword tokens."""
    c: Counter = Counter()
    for t in titles:
        for tok in _TOKEN_RE.findall((t or "").lower()):
            if len(tok) >= 4 and tok not in _STOPWORDS:
                c[tok] += 1
    if not c:
        return ""
    return " / ".join(w for w, _ in c.most_common(k))


def l2_normalize(arr: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalize."""
    n = np.linalg.norm(arr, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return arr / n


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", help="comma-separated subset (default: all in backtest history)")
    ap.add_argument("--tail", type=int, default=None,
                    help="only compute for the last N trading days (testing)")
    args = ap.parse_args()

    sources = [p for p in DEFAULT_SOURCES if p.exists()]
    if not sources and LEGACY_SOURCE.exists():
        sources = [LEGACY_SOURCE]
    if not sources:
        sys.exit(f"No source files found in {DEFAULT_SOURCES[0].parent}")
    if not EMB_PATH.exists():
        sys.exit(f"Missing {EMB_PATH} — run embed_events.py first")
    if not HIST_PATH.exists():
        sys.exit(f"Missing {HIST_PATH}")

    # ── Load events (minimum needed fields) ─────────────────────────────────
    print(f"  loading events from: {', '.join(p.name for p in sources)}")
    rows = []
    seen_eids: set[str] = set()
    for src_path in sources:
        with src_path.open() as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                eid = r.get("event_id")
                if not eid or not r.get("timestamp") or eid in seen_eids:
                    continue
                seen_eids.add(eid)
                ts = r["timestamp"][:10]
                title = (r.get("title") or "")[:200]
                text  = (r.get("text") or "")
                combined_len = len(title) + len(text)
                rows.append({
                    "event_id":     eid,
                    "date":         ts,
                    "title":        title,
                    "actors":       r.get("actors") or [],
                    "reliability":  float(r.get("reliability", 0.5) or 0.5),
                    "source":       r.get("source", ""),
                    "combined_len": combined_len,
                    "degenerate":   combined_len < DEGENERATE_TEXT_LEN,
                })
    events_df = pd.DataFrame(rows)
    events_df["date"] = pd.to_datetime(events_df["date"])
    n_degen = events_df["degenerate"].sum()
    print(f"    {len(events_df):,} events loaded ({n_degen:,} degenerate, <{DEGENERATE_TEXT_LEN} chars)")

    # ── Load embeddings, align to events_df ─────────────────────────────────
    print("  loading embeddings…")
    emb_df = pd.read_parquet(EMB_PATH)
    print(f"    {len(emb_df):,} cached embeddings")
    eid_to_idx = {eid: i for i, eid in enumerate(emb_df["event_id"].tolist())}
    emb_mat = np.stack(emb_df["embedding"].apply(lambda x: np.asarray(x, dtype=np.float32)).tolist())
    emb_mat = l2_normalize(emb_mat)
    print(f"    embedding matrix shape: {emb_mat.shape}")

    # Filter events_df to those with embeddings only
    events_df = events_df[events_df["event_id"].isin(eid_to_idx)].copy()
    events_df["emb_idx"] = events_df["event_id"].map(eid_to_idx)
    print(f"    events with embeddings: {len(events_df):,}")

    # Pre-index events by date for fast window queries
    events_df = events_df.sort_values("date").reset_index(drop=True)
    # Build an actor → list of event row indices map
    actor_to_idx: dict[str, list[int]] = defaultdict(list)
    for i, actors in enumerate(events_df["actors"].tolist()):
        for a in actors:
            actor_to_idx[a].append(i)

    # Boolean array of degenerate events (excluded from density / centroid)
    degenerate_arr = events_df["degenerate"].values

    # ── Trading-day grid from backtest_history ──────────────────────────────
    hist = pd.read_parquet(HIST_PATH).copy()
    hist["date"] = pd.to_datetime(hist["date"])
    if "variant" in hist.columns:
        hist = hist[hist["variant"] == hist["variant"].mode().iloc[0]].copy()
    trading_dates = sorted(hist["date"].unique())
    if args.tail:
        trading_dates = trading_dates[-args.tail:]

    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",")]
    else:
        tickers = sorted(hist["ticker"].unique())
    print(f"  computing for {len(tickers)} tickers × {len(trading_dates)} trading dates")

    # ── Main compute ────────────────────────────────────────────────────────
    out_rows = []
    dates_arr = events_df["date"].values  # numpy datetime64
    rels_arr  = events_df["reliability"].values
    actors_list = events_df["actors"].tolist()
    eids = events_df["event_id"].tolist()
    titles = events_df["title"].tolist()

    for d_idx, d in enumerate(trading_dates):
        d_np = np.datetime64(d)
        lo_7d  = d_np - np.timedelta64(WINDOW_7D, "D")
        lo_30d = d_np - np.timedelta64(WINDOW_30D, "D")
        # Indices of events in each window (any actor)
        mask_7d  = (dates_arr >= lo_7d)  & (dates_arr <= d_np)
        mask_30d = (dates_arr >= lo_30d) & (dates_arr <= d_np)
        idx_7d  = np.where(mask_7d)[0]
        idx_30d = np.where(mask_30d)[0]

        # Sub-matrices once per day
        win_idx_7d  = events_df.iloc[idx_7d]["emb_idx"].values  if len(idx_7d)  else np.array([], dtype=int)
        win_idx_30d = events_df.iloc[idx_30d]["emb_idx"].values if len(idx_30d) else np.array([], dtype=int)
        emb_7d  = emb_mat[win_idx_7d]  if len(win_idx_7d)  else np.zeros((0, emb_mat.shape[1]))
        emb_30d = emb_mat[win_idx_30d] if len(win_idx_30d) else np.zeros((0, emb_mat.shape[1]))
        rel_7d  = rels_arr[idx_7d]  if len(idx_7d)  else np.array([], dtype=np.float32)

        # Pre-compute actor centroids per ticker for the 7-day window — used for neighbor actors
        ticker_centroids_7d: dict[str, np.ndarray] = {}
        for t in tickers:
            act_idx = actor_to_idx.get(t, [])
            if not act_idx:
                continue
            in_win = [i for i in act_idx if i in set(idx_7d.tolist())]
            if not in_win:
                continue
            te = emb_mat[events_df.iloc[in_win]["emb_idx"].values]
            ticker_centroids_7d[t] = l2_normalize(te.mean(axis=0, keepdims=True))[0]

        # Also need centroids one week earlier for drift
        d_np_prev = d_np - np.timedelta64(WINDOW_7D, "D")
        lo_prev7  = d_np_prev - np.timedelta64(WINDOW_7D, "D")
        mask_prev7 = (dates_arr >= lo_prev7) & (dates_arr <= d_np_prev)
        idx_prev7 = np.where(mask_prev7)[0]
        prev7_set = set(idx_prev7.tolist())

        for ticker in tickers:
            act_idx = actor_to_idx.get(ticker, [])

            # Indices in each window (raw, before degenerate filter)
            in_7d_raw  = [i for i in act_idx if mask_7d[i]]
            in_30d_raw = [i for i in act_idx if mask_30d[i]]
            event_count_7d  = len(in_7d_raw)
            event_count_30d = len(in_30d_raw)

            # Filter degenerate (low-text) events from centroid/density math
            in_7d  = [i for i in in_7d_raw  if not degenerate_arr[i]]
            in_30d = [i for i in in_30d_raw if not degenerate_arr[i]]
            degenerate_event_share = (
                (event_count_7d - len(in_7d)) / event_count_7d
                if event_count_7d > 0 else 0.0
            )

            # Defaults
            density_7d = 0.0
            density_30d = 0.0
            density_momentum = 0.0
            source_weighted_density = 0.0
            novelty = 0.0
            drift = 0.0
            dispersion = 0.0
            cluster_id_primary = -1
            cluster_label = ""
            nearest_event_ids: list[str] = []
            nearest_event_titles: list[str] = []
            top_neighbors: list[str] = []

            if event_count_7d > 0:
                # Centroid of actor's 7-day events
                actor_idx_emb_7d = events_df.iloc[in_7d]["emb_idx"].values
                actor_emb_7d = emb_mat[actor_idx_emb_7d]
                centroid_7d = l2_normalize(actor_emb_7d.mean(axis=0, keepdims=True))[0]

                # Semantic density (7d): mean cosine sim of actor's events to the broader 7-day field,
                # excluding the actor's own events. Only count above deadband.
                if emb_7d.shape[0] > event_count_7d:
                    sims = actor_emb_7d @ emb_7d.T  # (k, N)
                    # Exclude self-matches by masking the actor's own indices within idx_7d
                    self_local_idx = [
                        np.where(idx_7d == i)[0][0] for i in in_7d if i in idx_7d
                    ]
                    if self_local_idx:
                        sims[:, self_local_idx] = np.nan
                    above = np.nan_to_num(np.where(sims > COSINE_DEADBAND, sims, 0.0))
                    # Density = mean nonzero similarity over actor's events
                    n_nonzero_per_event = (above > 0).sum(axis=1)
                    sums = above.sum(axis=1)
                    per_event_density = np.where(
                        n_nonzero_per_event > 0,
                        sums / np.maximum(1, n_nonzero_per_event),
                        0.0,
                    ) * (n_nonzero_per_event / max(1, sims.shape[1]))  # scale by share of field
                    density_7d = float(per_event_density.mean())

                    # Source-weighted density: weight neighbor similarity by source reliability
                    if rel_7d.size > 0:
                        weights = np.where(rel_7d > 0, rel_7d, 0.0)
                        if self_local_idx:
                            wmask = np.ones(sims.shape[1])
                            wmask[self_local_idx] = 0
                            weighted = above * weights[None, :] * wmask[None, :]
                        else:
                            weighted = above * weights[None, :]
                        wnonzero = (weighted > 0).sum(axis=1)
                        wsums = weighted.sum(axis=1)
                        per_event_w = np.where(
                            wnonzero > 0,
                            wsums / np.maximum(1, wnonzero),
                            0.0,
                        ) * (wnonzero / max(1, sims.shape[1]))
                        source_weighted_density = float(per_event_w.mean())

                # Dispersion: mean pairwise distance among actor's 7-day events
                if event_count_7d >= 2:
                    pair_sims = actor_emb_7d @ actor_emb_7d.T
                    np.fill_diagonal(pair_sims, np.nan)
                    pair_dists = 1.0 - pair_sims
                    dispersion = float(np.nanmean(pair_dists))

                # Drift: cosine distance between centroid_7d and centroid 7 days earlier
                in_prev7 = [i for i in act_idx if i in prev7_set]
                if in_prev7:
                    prev_actor_emb = emb_mat[events_df.iloc[in_prev7]["emb_idx"].values]
                    prev_centroid = l2_normalize(prev_actor_emb.mean(axis=0, keepdims=True))[0]
                    drift = float(1.0 - centroid_7d @ prev_centroid)

                # Novelty: distance from today's events to centroid of the actor's 30-day prior window
                d_only_today = d_np
                lo_today = d_np
                today_mask = (dates_arr >= lo_today) & (dates_arr <= d_np)
                in_today = [i for i in act_idx if today_mask[i]]
                in_prior_30 = [i for i in in_30d if dates_arr[i] < lo_today]
                if in_today and in_prior_30:
                    today_emb = emb_mat[events_df.iloc[in_today]["emb_idx"].values]
                    prior_emb = emb_mat[events_df.iloc[in_prior_30]["emb_idx"].values]
                    prior_centroid = l2_normalize(prior_emb.mean(axis=0, keepdims=True))[0]
                    sims = today_emb @ prior_centroid
                    novelty = float(1.0 - sims.mean())

                # Nearest events in the 7-day field to actor's centroid (top 3, excluding own)
                if emb_7d.shape[0] > event_count_7d:
                    overall_sims = emb_7d @ centroid_7d  # (N,)
                    # exclude self
                    self_local_idx = [np.where(idx_7d == i)[0][0] for i in in_7d if i in idx_7d]
                    overall_sims_for_rank = overall_sims.copy()
                    if self_local_idx:
                        overall_sims_for_rank[self_local_idx] = -np.inf
                    top_k = np.argsort(-overall_sims_for_rank)[:3]
                    for tk in top_k:
                        if overall_sims_for_rank[tk] == -np.inf:
                            continue
                        ev_global = idx_7d[tk]
                        nearest_event_ids.append(eids[ev_global])
                        nearest_event_titles.append(titles[ev_global][:100])

                # Top neighbor actors: closest 3 ticker centroids (excluding self)
                if ticker in ticker_centroids_7d:
                    sims = []
                    for other_t, other_c in ticker_centroids_7d.items():
                        if other_t == ticker:
                            continue
                        sims.append((other_t, float(centroid_7d @ other_c)))
                    sims.sort(key=lambda x: -x[1])
                    top_neighbors = [t for t, _ in sims[:3]]

                # Cluster: simple per-window kmeans on 30-day field, pick actor's mode
                if emb_30d.shape[0] >= 20:
                    try:
                        from sklearn.cluster import MiniBatchKMeans
                        k = min(20, emb_30d.shape[0] // 5)
                        km = MiniBatchKMeans(n_clusters=k, n_init=3, random_state=42, batch_size=256)
                        labels = km.fit_predict(emb_30d)
                        # actor's events' labels
                        local_actor_idx = [np.where(idx_30d == i)[0][0] for i in in_30d if i in idx_30d]
                        if local_actor_idx:
                            actor_labels = labels[local_actor_idx]
                            primary, _ = Counter(actor_labels.tolist()).most_common(1)[0]
                            cluster_id_primary = int(primary)
                            cluster_title_indices = np.where(labels == primary)[0]
                            cluster_titles = [titles[idx_30d[i]] for i in cluster_title_indices[:30]]
                            cluster_label = top_tokens(cluster_titles, k=3)
                    except ImportError:
                        pass  # sklearn not available — skip clustering

            # 30d density (cheaper proxy: same as 7d but with longer window, simpler average)
            if event_count_30d > 0 and emb_30d.shape[0] > event_count_30d:
                actor_idx_emb_30d = events_df.iloc[in_30d]["emb_idx"].values
                actor_emb_30d = emb_mat[actor_idx_emb_30d]
                sims = actor_emb_30d @ emb_30d.T
                self_local_idx = [np.where(idx_30d == i)[0][0] for i in in_30d if i in idx_30d]
                if self_local_idx:
                    sims[:, self_local_idx] = np.nan
                above = np.nan_to_num(np.where(sims > COSINE_DEADBAND, sims, 0.0))
                n_nonzero = (above > 0).sum(axis=1)
                sums = above.sum(axis=1)
                per_event_d = np.where(
                    n_nonzero > 0,
                    sums / np.maximum(1, n_nonzero),
                    0.0,
                ) * (n_nonzero / max(1, sims.shape[1]))
                density_30d = float(per_event_d.mean())

            # Density momentum: density_7d_today - density_7d_(today-7d)
            # We compute it post-hoc by storing density_7d series and diffing later, but
            # for the in-loop version we compute it inline by re-running 7d for the prior week.
            # Cheaper alternative for V1: leave as 0.0 here, compute as a column-wise diff
            # over the full output below.

            out_rows.append({
                "date":                  pd.Timestamp(d).date().isoformat(),
                "ticker":                ticker,
                "event_count_7d":        event_count_7d,
                "event_count_30d":       event_count_30d,
                "degenerate_event_share": round(degenerate_event_share, 3),
                "semantic_density_7d":   round(density_7d, 4),
                "semantic_density_30d":  round(density_30d, 4),
                "density_momentum":      0.0,    # filled below
                "source_weighted_density": round(source_weighted_density, 4),
                "novelty_score":         round(novelty, 4),
                "drift":                 round(drift, 4),
                "dispersion":            round(dispersion, 4),
                "cluster_id_primary":    cluster_id_primary,
                "cluster_label":         cluster_label,
                "nearest_event_ids":     nearest_event_ids,
                "nearest_event_titles":  nearest_event_titles,
                "top_neighbor_actors":   top_neighbors,
            })

        if (d_idx + 1) % 20 == 0 or d_idx == len(trading_dates) - 1:
            print(f"  {d_idx+1}/{len(trading_dates)} dates processed")

    df = pd.DataFrame(out_rows)

    # Fill density_momentum as 7-day diff per ticker (today vs 7 trading days back)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    for t in df["ticker"].unique():
        mask = df["ticker"] == t
        s = df.loc[mask, "semantic_density_7d"].values
        mom = np.zeros_like(s)
        for i in range(len(s)):
            if i >= 7:
                mom[i] = round(s[i] - s[i - 7], 4)
        df.loc[mask, "density_momentum"] = mom

    OUT_PARQ.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQ, index=False)
    print(f"\n  wrote {OUT_PARQ}  ({len(df):,} rows)")

    # ── Site-facing JSON: today-only snapshot per actor ─────────────────────
    latest = df["date"].max()
    today_df = df[df["date"] == latest]
    today_payload = {
        "as_of":  latest,
        "actors": {},
    }
    for _, r in today_df.iterrows():
        t = r["ticker"]
        today_payload["actors"][t] = {
            "event_count_7d":         int(r["event_count_7d"]),
            "event_count_30d":        int(r["event_count_30d"]),
            "degenerate_event_share": float(r["degenerate_event_share"]),
            "semantic_density_7d":    float(r["semantic_density_7d"]),
            "semantic_density_30d":   float(r["semantic_density_30d"]),
            "density_momentum":       float(r["density_momentum"]),
            "source_weighted_density": float(r["source_weighted_density"]),
            "novelty_score":          float(r["novelty_score"]),
            "drift":                  float(r["drift"]),
            "dispersion":             float(r["dispersion"]),
            "cluster_id_primary":     int(r["cluster_id_primary"]),
            "cluster_label":          r["cluster_label"],
            "nearest_event_titles":   list(r["nearest_event_titles"]),
            "top_neighbor_actors":    list(r["top_neighbor_actors"]),
        }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(today_payload, indent=2))
    print(f"  wrote {OUT_JSON}  ({len(today_df)} actors @ {latest})")


if __name__ == "__main__":
    main()
