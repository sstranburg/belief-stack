"""
Build the expectation field — daily structural snapshots derived from the
expectation replay layer.

Reads:
  data/derived/expectation_replay_history_{Q-001,Q-002}_{20251119,20260210}.jsonl

Writes (combined, then per-family for interpretability):
  data/derived/expectation_field_history.jsonl
  data/derived/expectation_field_events.jsonl
  data/derived/expectation_field_history_E-001.jsonl
  data/derived/expectation_field_events_E-001.jsonl
  data/derived/expectation_field_history_E-002.jsonl
  data/derived/expectation_field_events_E-002.jsonl

Deterministic. No API calls. No price data. The field is constructed
entirely from the expectation layer.
"""

from __future__ import annotations
import json
import pathlib
import collections
import datetime as dt
from typing import Optional

# ── Paths ────────────────────────────────────────────────────────────────────

DERIVED = pathlib.Path(__file__).resolve().parents[1] / "data" / "derived"

# Auto-discover all expectation replay history files.
def _discover_replay_files() -> list[pathlib.Path]:
    return sorted(DERIVED.glob("expectation_replay_history_Q-*_*.jsonl"))

REPLAY_FILES = _discover_replay_files()

# topicspace renamed Q- handles to E- for the writing; keep that mapping.
HANDLE_RENAME = {
    "Q-001": "E-001", "Q-002": "E-002",
    "Q-006": "E-006", "Q-007": "E-007",
    "Q-008": "E-008", "Q-009": "E-009",
}

# ── Snapshot construction ───────────────────────────────────────────────────

ACTIVE_STATUSES = {"active", "weakening"}

AGE_BUCKETS = [
    ("0_7d",   0,   7),
    ("8_30d",  8,  30),
    ("31_plus", 31, 10_000),
]


def _age_bucket(days_alive: int) -> str:
    for name, lo, hi in AGE_BUCKETS:
        if lo <= days_alive <= hi:
            return name
    return "31_plus"


def load_rows(files: list[pathlib.Path]) -> list[dict]:
    rows: list[dict] = []
    for f in files:
        if not f.exists():
            print(f"[warn] missing replay file: {f.name}")
            continue
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            r["family"] = HANDLE_RENAME.get(r.get("question_handle", ""), r.get("question_handle", ""))
            rows.append(r)
    return rows


def snapshot_for_day(day_rows: list[dict]) -> dict:
    """Build a single-day field snapshot from the active rows on that day."""
    n_active = len(day_rows)
    if n_active == 0:
        return {
            "n_active": 0,
            "n_parents_active": 0,
            "n_children_active": 0,
            "by_kind": {},
            "by_family": {},
            "by_status": {},
            "by_age": {},
            "supporting_share": {"mean": None, "min": None, "max": None},
            "events_today": {"born": 0, "split": 0, "weakened": 0, "retired": 0, "strengthened": 0, "stable": 0},
            "cohort_coverage": {"tickers_covered": 0, "tickers_in_multiple": 0},
            "lineage": {"max_depth": 0, "child_fraction": 0.0},
        }

    by_kind   = collections.Counter()
    by_family = collections.Counter()
    by_status = collections.Counter()
    by_age    = collections.Counter()
    events    = collections.Counter()
    shares: list[float] = []
    ticker_counts: collections.Counter = collections.Counter()

    n_parents = 0
    n_children = 0
    for r in day_rows:
        by_kind[r.get("implied_kind", "unknown")] += 1
        by_family[r.get("family", "?")] += 1
        by_status[r.get("status", "unknown")] += 1
        by_age[_age_bucket(r.get("days_alive", 0))] += 1

        # First-day rows count as "born". The replay layer doesn't emit an
        # explicit born event, so we synthesize one from days_alive == 0.
        ev = r.get("event", "")
        if ev:
            events[ev] += 1
        if r.get("days_alive", -1) == 0:
            events["born"] += 1

        shares.append(float(r.get("supporting_share", 0.0)))

        if r.get("parent_expectation_id"):
            n_children += 1
        else:
            n_parents += 1

        for tkr in r.get("supporting_actors", []) or []:
            ticker_counts[tkr] += 1

    # "retired" — we map the replay layer's "died" event to "retired" for
    # consistency with the writing's softened lifecycle vocabulary.
    if events.get("died"):
        events["retired"] = events.pop("died")

    tickers_in_multiple = sum(1 for v in ticker_counts.values() if v >= 2)

    return {
        "n_active": n_active,
        "n_parents_active": n_parents,
        "n_children_active": n_children,
        "by_kind":   dict(by_kind),
        "by_family": dict(by_family),
        "by_status": dict(by_status),
        "by_age":    dict(by_age),
        "supporting_share": {
            "mean": round(sum(shares) / len(shares), 4),
            "min":  round(min(shares), 4),
            "max":  round(max(shares), 4),
        },
        "events_today": {
            "born":         events.get("born", 0),
            "split":        events.get("split", 0),
            "weakened":     events.get("weakened", 0),
            "retired":      events.get("retired", 0),
            "strengthened": events.get("strengthened", 0),
            "stable":       events.get("stable", 0),
        },
        "cohort_coverage": {
            "tickers_covered": len(ticker_counts),
            "tickers_in_multiple": tickers_in_multiple,
        },
        "lineage": {
            "max_depth": 1 if n_children > 0 else 0,  # current replay only has depth 1
            "child_fraction": round(n_children / n_active, 4) if n_active else 0.0,
        },
    }


# ── Field-level metrics ─────────────────────────────────────────────────────

def family_hhi(by_family: dict[str, int]) -> float:
    total = sum(by_family.values())
    if total == 0:
        return 0.0
    return round(sum((v / total) ** 2 for v in by_family.values()), 4)


def jaccard_distance(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return round(1 - len(a & b) / len(a | b), 4) if (a | b) else 0.0


def compute_metrics(
    snap: dict,
    active_ids_today: set,
    active_ids_yesterday: set,
    retired_trailing_7d: int,
) -> dict:
    n = snap["n_active"]
    return {
        "breadth":              n,
        "family_concentration": family_hhi(snap["by_family"]),
        "alignment":            snap["supporting_share"]["mean"] or 0.0,
        "refinement_pressure":  snap["lineage"]["child_fraction"],
        "stress":               round(snap["by_status"].get("weakening", 0) / n, 4) if n else 0.0,
        "mortality_7d":         retired_trailing_7d,
        "drift":                jaccard_distance(active_ids_today, active_ids_yesterday),
    }


# ── Event detection (field-level transitions) ───────────────────────────────

def detect_field_events(history: list[dict]) -> list[dict]:
    """Sparse field-level transitions, threshold-based and inspectable."""
    events: list[dict] = []
    by_date = {h["as_of"]: h for h in history}
    dates = [h["as_of"] for h in history]

    for i, d in enumerate(dates):
        m = by_date[d]["metrics"]
        # use 5-trading-day lookback (positional, not calendar)
        prior = by_date[dates[i - 5]]["metrics"] if i >= 5 else None

        if prior:
            if m["breadth"] - prior["breadth"] <= -2:
                events.append({"as_of": d, "kind": "narrowing",
                               "detail": f"breadth {prior['breadth']} → {m['breadth']} over 5d"})
            dc = m["family_concentration"] - prior["family_concentration"]
            if dc <= -0.15:
                events.append({"as_of": d, "kind": "fragmenting",
                               "detail": f"family_concentration {prior['family_concentration']:.2f} → {m['family_concentration']:.2f}"})
            elif dc >= 0.15:
                events.append({"as_of": d, "kind": "consolidating",
                               "detail": f"family_concentration {prior['family_concentration']:.2f} → {m['family_concentration']:.2f}"})

        if m["stress"] >= 0.5 and m["breadth"] >= 2:
            events.append({"as_of": d, "kind": "stressing",
                           "detail": f"stress={m['stress']:.2f} on breadth={m['breadth']}"})
        if m["mortality_7d"] >= 3:
            events.append({"as_of": d, "kind": "churning",
                           "detail": f"mortality_7d={m['mortality_7d']}"})
        if m["drift"] >= 0.5 and m["breadth"] >= 2:
            events.append({"as_of": d, "kind": "drifting",
                           "detail": f"drift={m['drift']:.2f} on breadth={m['breadth']}"})
    return events


# ── Per-scope build ─────────────────────────────────────────────────────────

def build_scope(rows: list[dict], scope_label: str) -> tuple[list[dict], list[dict]]:
    """Build daily snapshots + field events for a given set of rows (a 'scope')."""
    # Index active rows by date
    by_day_active: dict[str, list[dict]] = collections.defaultdict(list)
    retire_dates: list[str] = []  # for trailing-7d mortality
    for r in rows:
        if r.get("status") in ACTIVE_STATUSES:
            by_day_active[r["as_of"]].append(r)
        if r.get("event") == "died":
            retire_dates.append(r["as_of"])

    # Build per-day in date order
    all_dates = sorted(by_day_active.keys())
    history: list[dict] = []
    prior_active_ids: set = set()

    for d in all_dates:
        day_rows = by_day_active[d]
        snap = snapshot_for_day(day_rows)
        active_ids = {r["expectation_id"] for r in day_rows}

        # trailing 7 calendar days of retirements (inclusive of d)
        d_dt = dt.date.fromisoformat(d)
        cutoff = d_dt - dt.timedelta(days=7)
        mortality_7d = sum(1 for rd in retire_dates if cutoff <= dt.date.fromisoformat(rd) <= d_dt)

        metrics = compute_metrics(snap, active_ids, prior_active_ids, mortality_7d)
        history.append({"as_of": d, "scope": scope_label, **snap, "metrics": metrics})
        prior_active_ids = active_ids

    events = detect_field_events(history)
    for e in events:
        e["scope"] = scope_label
    return history, events


# ── Write ───────────────────────────────────────────────────────────────────

def write_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")
    print(f"[wrote] {path.relative_to(DERIVED.parent.parent)}  ({len(rows)} rows)")


def main() -> None:
    all_rows = load_rows(REPLAY_FILES)
    print(f"loaded {len(all_rows)} replay rows from {len(REPLAY_FILES)} files")

    # combined
    combined_hist, combined_events = build_scope(all_rows, "combined")
    write_jsonl(DERIVED / "expectation_field_history.jsonl", combined_hist)
    write_jsonl(DERIVED / "expectation_field_events.jsonl",  combined_events)

    # per family (auto-discover from the data)
    families = sorted({r["family"] for r in all_rows if r["family"]})
    for fam in families:
        fam_rows = [r for r in all_rows if r["family"] == fam]
        hist, events = build_scope(fam_rows, fam)
        write_jsonl(DERIVED / f"expectation_field_history_{fam}.jsonl", hist)
        write_jsonl(DERIVED / f"expectation_field_events_{fam}.jsonl",  events)


if __name__ == "__main__":
    main()
