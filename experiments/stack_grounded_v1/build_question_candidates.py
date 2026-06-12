#!/usr/bin/env python3
"""
Stack-Grounded Retrieval v0.1 — Question candidate generator.

Per pre-registration §4.4 (anti-curation discipline):
  - Reads ONLY raw L0 substrate (data/normalized/tech_ecosystem.jsonl).
  - Does NOT read belief_objects.jsonl (which doesn't exist yet).
  - Does NOT read derived/* artifacts (actors.json, lifecycle parquets,
    narrative_pressure.jsonl) — those are downstream belief-shaped.
  - The 31-ticker primary universe is configuration, not belief.

Outputs:
  stack_grounded_v1/data/question_candidates_v0_1.jsonl
    Stratified candidate pool (more than 75); hand-curation to the
    final question set follows.

Stratification:
  - 5 categories (current_intel, change_detection, stale_assumption,
    contradiction, insufficient_warrant) — §4.2 weights.
  - Per-actor coverage: at least one candidate per primary ticker
    where the substrate supports it.
  - Per-date spread: cutoffs distributed across the 173-day window
    so currency can be measured at multiple points in time.
  - >=60% non-current cutoffs per §4.5.

Templates are intentionally simple; the candidate pool is for
curation, not the locked question set.
"""

from __future__ import annotations

import json
import pathlib
import random
from collections import defaultdict, Counter
from datetime import date, datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parent
STORM_ROOT = ROOT.parent
EVENTS_PATH = STORM_ROOT / "data" / "normalized" / "tech_ecosystem.jsonl"
OUT_PATH    = ROOT / "data" / "question_candidates_v0_1.jsonl"

WINDOW_START = "2025-12-05"
WINDOW_END   = "2026-05-26"
CURRENT_CUTOFF = WINDOW_END
NON_CURRENT_CUTOFFS = ["2026-01-31", "2026-02-28", "2026-03-15", "2026-04-15", "2026-05-10"]

# Primary universe per pre-reg §2.1 — hardcoded configuration, not derived
# from any belief-shaped artifact. Matches sensemaking-v1.5's universe.
PRIMARY_TICKERS = sorted([
    "NVDA", "TSM", "AMD", "INTC", "ARM", "AVGO", "ASML", "MU", "MRVL",
    "SNDK", "WDC", "ALAB", "MSFT", "META", "GOOGL", "PLTR", "AMZN", "ORCL",
    "SMCI", "DELL", "ANET", "NBIS", "VRT", "VST", "COHR", "CLS", "CEG",
    "CRM", "ADBE", "DDOG", "SNOW", "TTD", "MELI", "NFLX", "TSLA", "AAPL",
    "SOFI", "CRWV", "ZETA",
])
# Note: per pre-reg §2.2, USAR/MP/ODC excluded as experimental. The list
# above totals 39 (some overlap with sensemaking-v1.5's 31; the actual
# in-substrate universe will narrow based on what tech_ecosystem.jsonl
# carries during the window).

# Source reliability priors (configuration, not belief)
LOW_WARRANT_SOURCES = {"x", "reddit"}
HIGH_WARRANT_SOURCES = {"sec", "transcript", "newsapi", "finnhub"}

RANDOM_SEED = 20260531
random.seed(RANDOM_SEED)


def in_window(ts: str) -> bool:
    return WINDOW_START <= ts[:10] <= WINDOW_END


def load_events_in_window() -> list[dict]:
    out = []
    with EVENTS_PATH.open() as f:
        for line in f:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = (e.get("timestamp") or "")[:10]
            if not ts or not in_window(ts):
                continue
            actors = set(e.get("actors") or []) & set(PRIMARY_TICKERS)
            if not actors:
                continue
            e["_date"] = ts
            e["_primary_actors"] = sorted(actors)
            out.append(e)
    return out


def events_for(events: list[dict], ticker: str, cutoff: str) -> list[dict]:
    return [e for e in events if ticker in e["_primary_actors"] and e["_date"] <= cutoff]


def events_for_range(events: list[dict], ticker: str, lo: str, hi: str) -> list[dict]:
    return [e for e in events if ticker in e["_primary_actors"] and lo <= e["_date"] <= hi]


# ─── Per-category candidate generators ──────────────────────────────────────

def gen_current_intel(events: list[dict], by_ticker: dict, candidates: list[dict]) -> None:
    """Category: current intel. Most-recent cutoff. Top-coverage actors first."""
    templates = [
        "What is the current intel on {ticker}?",
        "What is currently being claimed about {ticker}?",
        "What's the latest read on {ticker} as of {cutoff}?",
        "Summarize the current state of {ticker}.",
        "What is the present-day analytical view on {ticker}?",
    ]
    ranked = sorted(by_ticker.items(), key=lambda kv: -len(kv[1]))
    for i, (ticker, evs) in enumerate(ranked):
        if len(evs) < 20:
            continue
        tmpl = templates[i % len(templates)]
        candidates.append({
            "candidate_id":   f"current_{ticker}_{i:02d}",
            "category":       "current_intel",
            "ticker":         ticker,
            "question":       tmpl.format(ticker=ticker, cutoff=CURRENT_CUTOFF),
            "evidence_cutoff": CURRENT_CUTOFF,
            "expected_failure_mode": "stale_or_unsupported",
            "rationale":      f"Top-coverage actor; recent events available through {CURRENT_CUTOFF}.",
        })


def gen_change_detection(events: list[dict], by_ticker: dict, candidates: list[dict]) -> None:
    """Category: change detection. Mid-window cutoff. Actors with notable density shifts."""
    templates = [
        "What changed in {ticker}'s narrative between {early} and {cutoff}?",
        "How has the read on {ticker} shifted between {early} and {cutoff}?",
        "What new evidence about {ticker} arrived between {early} and {cutoff}?",
        "What is different about {ticker}'s coverage as of {cutoff} vs {early}?",
    ]
    for ticker, evs in by_ticker.items():
        if len(evs) < 25:
            continue
        # Find a cutoff where the prior 30 days had distinct event composition
        # (rough heuristic — actual change-detection labeling is post-hoc)
        for cutoff in NON_CURRENT_CUTOFFS[1:]:  # skip earliest cutoff
            early = (datetime.fromisoformat(cutoff) - timedelta(days=30)).date().isoformat()
            recent = events_for_range(evs, ticker, early, cutoff) if False else \
                     [e for e in evs if early <= e["_date"] <= cutoff]
            prior  = [e for e in evs if e["_date"] < early and e["_date"] >= WINDOW_START]
            if len(recent) < 5 or len(prior) < 5:
                continue
            tmpl = random.choice(templates)
            candidates.append({
                "candidate_id":   f"change_{ticker}_{cutoff.replace('-','')}",
                "category":       "change_detection",
                "ticker":         ticker,
                "question":       tmpl.format(ticker=ticker, early=early, cutoff=cutoff),
                "evidence_cutoff": cutoff,
                "expected_failure_mode": "missed_recent_revision",
                "rationale":      f"Both prior ({len(prior)} events ≥{WINDOW_START},<{early}) and recent ({len(recent)} events {early}–{cutoff}) have coverage.",
            })
            break  # one per ticker is enough at candidate stage


def gen_stale_assumption(events: list[dict], by_ticker: dict, candidates: list[dict]) -> None:
    """Category: stale assumption. Late-mid cutoff. Actors with sufficient earlier coverage."""
    templates = [
        "Which prior assumption about {ticker} should no longer be used without qualification as of {cutoff}?",
        "What earlier claim about {ticker} has lost warrant by {cutoff}?",
        "What about {ticker} was once supported but has weakened by {cutoff}?",
        "What prior consensus on {ticker} no longer cleanly holds as of {cutoff}?",
    ]
    for ticker, evs in by_ticker.items():
        if len(evs) < 30:
            continue
        # Need substantial early coverage + at least some later coverage
        for cutoff in ["2026-04-15", "2026-05-10"]:
            early_cutoff = "2026-02-15"
            early = [e for e in evs if WINDOW_START <= e["_date"] <= early_cutoff]
            later = [e for e in evs if early_cutoff < e["_date"] <= cutoff]
            if len(early) < 8 or len(later) < 5:
                continue
            tmpl = random.choice(templates)
            candidates.append({
                "candidate_id":   f"stale_{ticker}_{cutoff.replace('-','')}",
                "category":       "stale_assumption",
                "ticker":         ticker,
                "question":       tmpl.format(ticker=ticker, cutoff=cutoff),
                "evidence_cutoff": cutoff,
                "expected_failure_mode": "uses_stale_prior",
                "rationale":      f"Substantial earlier coverage ({len(early)} events before {early_cutoff}) plus later coverage ({len(later)} events).",
            })
            break


def gen_contradiction(events: list[dict], by_ticker: dict, candidates: list[dict]) -> None:
    """Category: contradiction. Any cutoff. Actors with mixed-source / mixed-direction signals."""
    templates = [
        "Where does the evidence about {ticker} conflict as of {cutoff}?",
        "Are there contradicting signals on {ticker} as of {cutoff}?",
        "What tension exists between recent sources on {ticker} as of {cutoff}?",
        "Which claims about {ticker} are in disagreement as of {cutoff}?",
    ]
    for ticker, evs in by_ticker.items():
        if len(evs) < 20:
            continue
        # Use a non-current cutoff for most contradictions; current for a few
        for cutoff in ["2026-03-15", "2026-04-15", CURRENT_CUTOFF]:
            window_evs = [e for e in evs if WINDOW_START <= e["_date"] <= cutoff]
            srcs = Counter(e.get("source") for e in window_evs)
            # Need multi-source coverage to even discuss contradiction
            if len(srcs) < 3 or sum(srcs.values()) < 10:
                continue
            tmpl = random.choice(templates)
            candidates.append({
                "candidate_id":   f"contradiction_{ticker}_{cutoff.replace('-','')}",
                "category":       "contradiction",
                "ticker":         ticker,
                "question":       tmpl.format(ticker=ticker, cutoff=cutoff),
                "evidence_cutoff": cutoff,
                "expected_failure_mode": "omits_contradicting_evidence",
                "rationale":      f"{len(window_evs)} events ≤{cutoff} across {len(srcs)} sources: {dict(srcs)}.",
            })
            break


def gen_insufficient_warrant(events: list[dict], by_ticker: dict, candidates: list[dict]) -> None:
    """Category: insufficient warrant.
    Three sub-types in this substrate (X/Reddit are not dominant; the real
    thin-warrant signals are):
      (a) thinly-covered actors overall
      (b) early cutoffs where any actor had thin accumulation
      (c) narrow-topic queries where the actor+tag intersection is thin
    """
    actor_templates = [
        "What is our current read on {ticker}?",
        "Can we confidently say anything about {ticker} as of {cutoff}?",
        "What can be said about {ticker}'s narrative given the evidence we have as of {cutoff}?",
        "What is the current risk read on {ticker}?",
    ]
    topic_templates = [
        "What is the current read on {ticker}'s {topic} positioning as of {cutoff}?",
        "What does the evidence say about {ticker}'s {topic} as of {cutoff}?",
        "Where does {ticker} stand on {topic} as of {cutoff}?",
    ]
    TOPIC_TAGS = {
        "advanced_packaging": "advanced packaging",
        "custom_silicon":     "custom silicon",
        "inference_efficiency": "inference efficiency",
        "supply_chain":       "supply chain",
        "power_constraints":  "power constraints",
    }

    # Sub-type (a): thin-coverage actors at any cutoff
    for ticker, evs in by_ticker.items():
        for cutoff in [CURRENT_CUTOFF, "2026-04-15", "2026-03-15"]:
            window_evs = [e for e in evs if WINDOW_START <= e["_date"] <= cutoff]
            if not window_evs:
                continue
            total = len(window_evs)
            if total < 150:
                srcs = Counter(e.get("source") for e in window_evs)
                tmpl = random.choice(actor_templates)
                candidates.append({
                    "candidate_id":   f"insufficient_actor_{ticker}_{cutoff.replace('-','')}",
                    "category":       "insufficient_warrant",
                    "ticker":         ticker,
                    "question":       tmpl.format(ticker=ticker, cutoff=cutoff),
                    "evidence_cutoff": cutoff,
                    "expected_failure_mode": "overclaim_on_thin_evidence",
                    "rationale":      f"Sub-type A (thin actor coverage): {total} events ≤{cutoff}; sources {dict(srcs)}.",
                })
                break  # one per ticker

    # Sub-type (b): early-cutoff thinness — even mid-tier actors had less accumulation
    EARLY_CUTOFF = "2026-01-31"
    for ticker, evs in by_ticker.items():
        early_evs = [e for e in evs if WINDOW_START <= e["_date"] <= EARLY_CUTOFF]
        if 5 <= len(early_evs) < 30:  # in-window but thin at early cutoff
            srcs = Counter(e.get("source") for e in early_evs)
            tmpl = random.choice(actor_templates)
            candidates.append({
                "candidate_id":   f"insufficient_early_{ticker}",
                "category":       "insufficient_warrant",
                "ticker":         ticker,
                "question":       tmpl.format(ticker=ticker, cutoff=EARLY_CUTOFF),
                "evidence_cutoff": EARLY_CUTOFF,
                "expected_failure_mode": "overclaim_on_early_thin_evidence",
                "rationale":      f"Sub-type B (early-cutoff thin): {len(early_evs)} events ≤{EARLY_CUTOFF}; sources {dict(srcs)}.",
            })

    # Sub-type (c): narrow-topic queries — actor with events but few tag-matching ones
    for ticker, evs in by_ticker.items():
        for tag, topic_text in TOPIC_TAGS.items():
            for cutoff in [CURRENT_CUTOFF, "2026-04-15"]:
                tagged = [e for e in evs if WINDOW_START <= e["_date"] <= cutoff and tag in (e.get("tags") or [])]
                if 0 <= len(tagged) <= 3:  # thin topic coverage for this actor
                    tmpl = random.choice(topic_templates)
                    candidates.append({
                        "candidate_id":   f"insufficient_topic_{ticker}_{tag}_{cutoff.replace('-','')}",
                        "category":       "insufficient_warrant",
                        "ticker":         ticker,
                        "topic_tag":      tag,
                        "question":       tmpl.format(ticker=ticker, topic=topic_text, cutoff=cutoff),
                        "evidence_cutoff": cutoff,
                        "expected_failure_mode": "overclaim_on_thin_topic_evidence",
                        "rationale":      f"Sub-type C (thin topic): {len(tagged)} events tagged '{tag}' for {ticker} ≤{cutoff}.",
                    })
                    break  # one cutoff per (ticker, tag)


# ─── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Loading raw L0 events from {EVENTS_PATH}…")
    events = load_events_in_window()
    print(f"  {len(events):,} events in window {WINDOW_START}..{WINDOW_END} with primary-universe actors")

    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        for t in e["_primary_actors"]:
            by_ticker[t].append(e)
    print(f"  {len(by_ticker)} actors with coverage in window")

    candidates: list[dict] = []
    gen_current_intel(events, by_ticker, candidates)
    gen_change_detection(events, by_ticker, candidates)
    gen_stale_assumption(events, by_ticker, candidates)
    gen_contradiction(events, by_ticker, candidates)
    gen_insufficient_warrant(events, by_ticker, candidates)

    OUT_PATH.parent.mkdir(exist_ok=True)
    with OUT_PATH.open("w") as f:
        for c in candidates:
            f.write(json.dumps(c) + "\n")

    print(f"\nWrote {len(candidates):,} candidate questions to {OUT_PATH}")
    by_cat = Counter(c["category"] for c in candidates)
    print(f"\nCandidate distribution by category:")
    for cat in ("current_intel", "change_detection", "stale_assumption", "contradiction", "insufficient_warrant"):
        print(f"  {cat:22s}  {by_cat[cat]:>3}")
    cur = sum(1 for c in candidates if c["evidence_cutoff"] == CURRENT_CUTOFF)
    print(f"\nNon-current cutoff share: {(len(candidates) - cur) / len(candidates):.2%}")
    print(f"Actor coverage: {len(set(c['ticker'] for c in candidates))} actors represented")


if __name__ == "__main__":
    main()
