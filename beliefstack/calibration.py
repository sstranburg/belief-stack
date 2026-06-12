"""
L4 - calibration.

Walk-forward scoring of L2 hypotheses against held-out outcomes. The split is
chronological by event timestamp; predictions never see the held-out future.

Metrics produced per region:
    top1_accuracy   - fraction of test events whose true outcome equals the
                      hypothesis's top-1 predicted outcome
    top3_accuracy   - fraction whose true outcome is in the top-3
    brier_score     - mean squared error against the predicted probability
                      vector restricted to the *predicted* support
                      (lower is better; 0 is perfect)
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .events     import Event
from .hypotheses import Hypothesis
from .regions    import Region


@dataclass
class CalibrationResult:
    """Per-region calibration over a held-out test slice."""
    region_id:       int
    n_train:         int
    n_test:          int
    top1_accuracy:   float | None
    top3_accuracy:   float | None
    brier_score:     float | None
    prior_dist:      dict[Any, float] = field(default_factory=dict)   # from hypothesis
    actual_dist:     dict[Any, float] = field(default_factory=dict)   # from test


def _brier(prob_by_outcome: dict[Any, float], true_outcome: Any) -> float:
    """Multiclass Brier over the *predicted* support, plus the true outcome."""
    keys = set(prob_by_outcome) | {true_outcome}
    total = 0.0
    for k in keys:
        p = prob_by_outcome.get(k, 0.0)
        y = 1.0 if k == true_outcome else 0.0
        total += (p - y) ** 2
    return total


def walk_forward_calibrate(
    *,
    events:          list[Event],
    region_ids:      list[int],         # one region id per event, same order
    hypotheses:      Iterable[Hypothesis],
    split_at:        datetime,
) -> list[CalibrationResult]:
    """
    Split events at `split_at` (events with timestamp < split_at are train, the
    rest are test) and score each hypothesis against its region's test slice.

    `hypotheses` are assumed to have been generated using only train data
    (caller's responsibility - this function does NOT regenerate them).
    """
    if len(events) != len(region_ids):
        raise ValueError(
            f"events ({len(events)}) and region_ids ({len(region_ids)}) must align"
        )
    train_idx = [i for i, e in enumerate(events) if e.timestamp <  split_at]
    test_idx  = [i for i, e in enumerate(events) if e.timestamp >= split_at]

    # Group test events by their region.
    test_by_region: dict[int, list[Event]] = {}
    for i in test_idx:
        test_by_region.setdefault(region_ids[i], []).append(events[i])

    # Group train events too, just to record n_train per region.
    train_by_region: dict[int, list[Event]] = {}
    for i in train_idx:
        train_by_region.setdefault(region_ids[i], []).append(events[i])

    results: list[CalibrationResult] = []
    for h in hypotheses:
        train_in_region = train_by_region.get(h.region_id, [])
        test_in_region  = test_by_region.get(h.region_id, [])

        labeled_test = [e for e in test_in_region if e.outcome is not None]
        n_test = len(labeled_test)
        prior_dist  = {o: p for o, p in h.top3}
        if n_test == 0:
            results.append(CalibrationResult(
                region_id    = h.region_id,
                n_train      = h.n_train,
                n_test       = 0,
                top1_accuracy= None,
                top3_accuracy= None,
                brier_score  = None,
                prior_dist   = prior_dist,
                actual_dist  = {},
            ))
            continue

        top1_hits = 0
        top3_hits = 0
        brier_sum = 0.0
        actual_counts: dict[Any, int] = {}
        top3_outcomes = {o for o, _ in h.top3}
        for e in labeled_test:
            actual_counts[e.outcome] = actual_counts.get(e.outcome, 0) + 1
            if e.outcome == h.direction:
                top1_hits += 1
            if e.outcome in top3_outcomes:
                top3_hits += 1
            brier_sum += _brier(prior_dist, e.outcome)

        results.append(CalibrationResult(
            region_id    = h.region_id,
            n_train      = h.n_train,
            n_test       = n_test,
            top1_accuracy= top1_hits / n_test,
            top3_accuracy= top3_hits / n_test,
            brier_score  = brier_sum / n_test,
            prior_dist   = prior_dist,
            actual_dist  = {o: c / n_test for o, c in actual_counts.items()},
        ))
    return results
