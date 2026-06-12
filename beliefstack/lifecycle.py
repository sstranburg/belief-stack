"""
L3 - lifecycle.

Tracks how the *belief* about each region evolves across runs. Given a region's
prior calibration and its current calibration, emit a lifecycle event.

States:
    born          - first time the region is observed
    strengthened  - hypothesis improving (e.g. top1 accuracy is up materially)
    weakened      - hypothesis degrading but still positive lift
    contradicted  - hypothesis now performing worse than baseline
    retired       - sample collapsed below the floor; not actionable
    reopened      - retired region that has accumulated enough new evidence
    inverted      - sign flip: prior pointed one way, reality points the other

These are *belief* states, not data states. They are the unit on which L4-driven
operational decisions are made (see `decisions.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


LifecycleState = Literal[
    "born",
    "strengthened",
    "weakened",
    "contradicted",
    "retired",
    "reopened",
    "inverted",
]


@dataclass
class LifecycleEvent:
    """One step in a region's belief lifecycle."""
    region_id:  int
    timestamp:  datetime
    from_state: LifecycleState | None    # None on first observation
    to_state:   LifecycleState
    reason:     str
    metrics:    dict[str, float] = field(default_factory=dict)


@dataclass
class LifecycleThresholds:
    """Tunable thresholds. Defaults are tuned for production-scale event volumes."""
    min_n_active:          int   = 5      # below this -> retired
    reopen_n:              int   = 10     # retired -> reopened requires at least this many obs
    strengthened_delta:    float = 0.05   # top1 must improve by this much
    weakened_delta:        float = 0.05   # top1 must drop by this much
    contradicted_vs_base:  float = 0.00   # top1 below baseline by any amount triggers contradicted
    inverted_corr:         float = -0.30  # prior-vs-actual rank correlation below this -> inverted


def update_lifecycle(
    *,
    region_id:        int,
    timestamp:        datetime,
    prior_state:      LifecycleState | None,
    prior_top1:       float | None,
    current_top1:     float | None,
    current_n:        int,
    baseline_top1:    float | None = None,
    prior_actual_corr: float | None = None,
    thresholds:       LifecycleThresholds | None = None,
) -> LifecycleEvent:
    """
    Pure function. Given a region's prior lifecycle state and its current
    calibration metrics, emit the next lifecycle event.

    Order of precedence (first match wins):
        1. first observation                            -> born
        2. inverted (prior_actual_corr < threshold)     -> inverted
        3. current_n < min_n_active                     -> retired
        4. prior_state == 'retired' AND current_n >=    -> reopened
           reopen_n AND there is current_top1
        5. baseline supplied AND current_top1 below it  -> contradicted
           by more than contradicted_vs_base
        6. material improvement over prior_top1         -> strengthened
        7. material drop from prior_top1                -> weakened
        8. otherwise                                    -> keep prior state
                                                           (or 'strengthened'
                                                           if no prior_top1)
    """
    t = thresholds or LifecycleThresholds()
    metrics: dict[str, float] = {
        "current_top1": float(current_top1) if current_top1 is not None else float("nan"),
        "current_n":    float(current_n),
    }
    if prior_top1     is not None: metrics["prior_top1"]        = float(prior_top1)
    if baseline_top1  is not None: metrics["baseline_top1"]     = float(baseline_top1)
    if prior_actual_corr is not None: metrics["prior_actual_corr"] = float(prior_actual_corr)

    # 1. born
    if prior_state is None:
        return LifecycleEvent(
            region_id=region_id, timestamp=timestamp,
            from_state=None, to_state="born",
            reason="first observation", metrics=metrics,
        )

    # 2. inverted - sign flip overrides everything else
    if prior_actual_corr is not None and prior_actual_corr < t.inverted_corr:
        return LifecycleEvent(
            region_id=region_id, timestamp=timestamp,
            from_state=prior_state, to_state="inverted",
            reason=f"prior-actual rank correlation {prior_actual_corr:.2f} "
                   f"below threshold {t.inverted_corr:.2f}",
            metrics=metrics,
        )

    # 3. retired - sample collapsed
    if current_n < t.min_n_active:
        return LifecycleEvent(
            region_id=region_id, timestamp=timestamp,
            from_state=prior_state, to_state="retired",
            reason=f"n={current_n} below min_n_active={t.min_n_active}",
            metrics=metrics,
        )

    # 4. reopened
    if prior_state == "retired" and current_n >= t.reopen_n and current_top1 is not None:
        return LifecycleEvent(
            region_id=region_id, timestamp=timestamp,
            from_state=prior_state, to_state="reopened",
            reason=f"retired region accumulated n={current_n} (>= {t.reopen_n})",
            metrics=metrics,
        )

    # 5. contradicted vs baseline
    if (baseline_top1 is not None and current_top1 is not None
            and current_top1 < baseline_top1 - t.contradicted_vs_base):
        return LifecycleEvent(
            region_id=region_id, timestamp=timestamp,
            from_state=prior_state, to_state="contradicted",
            reason=f"top1 {current_top1:.2f} below baseline {baseline_top1:.2f}",
            metrics=metrics,
        )

    # 6/7. delta-driven transitions
    if prior_top1 is not None and current_top1 is not None:
        delta = current_top1 - prior_top1
        if delta >= t.strengthened_delta:
            return LifecycleEvent(
                region_id=region_id, timestamp=timestamp,
                from_state=prior_state, to_state="strengthened",
                reason=f"top1 improved by {delta:+.2f}",
                metrics=metrics,
            )
        if delta <= -t.weakened_delta:
            return LifecycleEvent(
                region_id=region_id, timestamp=timestamp,
                from_state=prior_state, to_state="weakened",
                reason=f"top1 dropped by {delta:+.2f}",
                metrics=metrics,
            )

    # 8. otherwise hold; if there's no prior_top1 we default to 'strengthened'
    if prior_top1 is None and current_top1 is not None:
        return LifecycleEvent(
            region_id=region_id, timestamp=timestamp,
            from_state=prior_state, to_state="strengthened",
            reason="first measured top1 after born",
            metrics=metrics,
        )
    return LifecycleEvent(
        region_id=region_id, timestamp=timestamp,
        from_state=prior_state, to_state=prior_state,
        reason="no material change",
        metrics=metrics,
    )
