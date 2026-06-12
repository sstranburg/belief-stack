"""
Decision classes.

Consumes L3 lifecycle + L4 calibration; emits an operational decision per
region. This is what an approver / operator acts on - not a per-event call.

Classes:
    PROMOTE     - calibrated, large enough sample, treat as trusted
    MONITOR     - workable but watch
    INTERVENE   - missing baseline; needs human attention
    RECLUSTER   - region is incoherent; cluster boundaries are wrong
    INVERT      - prior is sign-flipped vs reality; flipping it recovers signal
    RETIRE      - sample collapsed; stop scoring
    ESCALATE    - high-severity surface; raise to next level of review
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .calibration import CalibrationResult
from .lifecycle   import LifecycleEvent


DecisionClass = Literal[
    "PROMOTE", "MONITOR", "INTERVENE", "RECLUSTER", "INVERT", "RETIRE", "ESCALATE",
]


@dataclass
class DecisionConfig:
    """Tunable knobs for `classify_region`."""
    promote_top1:        float = 0.75
    monitor_top1:        float = 0.50
    recluster_top1:      float = 0.20
    promote_min_n_test:  int   = 10
    escalate_severity:   set[str] = field(default_factory=set)
    # If a region's label intersects `escalate_severity` (e.g. {"financial_advice",
    # "medical"}), force ESCALATE regardless of calibration. Empty by default.


@dataclass
class Decision:
    """Final classification for one region."""
    region_id:          int
    decision_class:     DecisionClass
    reasons:            list[str]
    recommended_action: str


def classify_region(
    *,
    region_label:    str,
    calibration:     CalibrationResult,
    lifecycle:       LifecycleEvent | None = None,
    config:          DecisionConfig | None = None,
) -> Decision:
    """
    Decide what to do about a region given its calibration and current lifecycle.

    Order of precedence:
        1. lifecycle == 'retired'                        -> RETIRE
        2. lifecycle == 'inverted'                       -> INVERT
        3. region_label hits config.escalate_severity    -> ESCALATE
        4. no labeled test data                          -> INTERVENE
        5. top1 below `recluster_top1`                   -> RECLUSTER
        6. top1 between recluster and monitor            -> MONITOR
        7. top1 >= promote_top1 AND n_test sufficient    -> PROMOTE
        8. otherwise                                     -> MONITOR
    """
    cfg = config or DecisionConfig()
    reasons: list[str] = []
    if lifecycle is not None:
        reasons.append(f"lifecycle: {lifecycle.to_state} ({lifecycle.reason})")

    # 1
    if lifecycle is not None and lifecycle.to_state == "retired":
        return Decision(
            region_id          = calibration.region_id,
            decision_class     = "RETIRE",
            reasons            = reasons + [f"n_test={calibration.n_test}"],
            recommended_action = "stop scoring this region; reassess if evidence returns",
        )

    # 2
    if lifecycle is not None and lifecycle.to_state == "inverted":
        return Decision(
            region_id          = calibration.region_id,
            decision_class     = "INVERT",
            reasons            = reasons,
            recommended_action = "flip the prior; reality is the inverse of what we thought",
        )

    # 3
    if cfg.escalate_severity and region_label in cfg.escalate_severity:
        return Decision(
            region_id          = calibration.region_id,
            decision_class     = "ESCALATE",
            reasons            = reasons + [f"label '{region_label}' is high-severity"],
            recommended_action = "raise to senior approver; human review required",
        )

    # 4
    if calibration.top1_accuracy is None or calibration.n_test == 0:
        return Decision(
            region_id          = calibration.region_id,
            decision_class     = "INTERVENE",
            reasons            = reasons + ["no labeled test data available"],
            recommended_action = "collect more outcomes before any automated action",
        )

    top1 = calibration.top1_accuracy
    reasons.append(f"top1={top1:.2f}, n_test={calibration.n_test}")

    # 5
    if top1 < cfg.recluster_top1:
        return Decision(
            region_id          = calibration.region_id,
            decision_class     = "RECLUSTER",
            reasons            = reasons + [
                f"top1 {top1:.2f} below recluster floor {cfg.recluster_top1:.2f}"
            ],
            recommended_action = "region is incoherent; refit clusters or increase k",
        )

    # 6
    if top1 < cfg.monitor_top1:
        return Decision(
            region_id          = calibration.region_id,
            decision_class     = "MONITOR",
            reasons            = reasons,
            recommended_action = "watch; do not promote until calibration improves",
        )

    # 7
    if top1 >= cfg.promote_top1 and calibration.n_test >= cfg.promote_min_n_test:
        return Decision(
            region_id          = calibration.region_id,
            decision_class     = "PROMOTE",
            reasons            = reasons + ["meets promote thresholds"],
            recommended_action = "treat as trusted region; route automatic decisions through it",
        )

    # 8
    return Decision(
        region_id          = calibration.region_id,
        decision_class     = "MONITOR",
        reasons            = reasons + ["does not yet clear promote thresholds"],
        recommended_action = "watch; revisit after more test observations accumulate",
    )
