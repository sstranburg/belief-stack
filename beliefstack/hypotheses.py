"""
L2 - hypotheses.

Per-region forward predictions. Each hypothesis says: given the events that fall
in this region, what outcome do we expect next, with what conviction?

The default generator is `EmpiricalHypothesisGenerator` - it takes the per-region
empirical distribution of outcomes from a training window as the prior.

Alternative generators (sequence-conditional, time-decayed, hierarchical,
calibrated probability outputs, multilabel) are documented in the essay
"A pattern for evolving beliefs"
(https://topicspace.ai/writing/a-pattern-for-evolving-beliefs) and are
deliberately out of scope here. Implement them by satisfying the same protocol
shape.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from .events  import Event
from .regions import Region


@dataclass
class Hypothesis:
    """An L2 forward prediction for one region at a point in time.

    The core fields (direction / conviction / top3) are sufficient for the
    library's L3 lifecycle and L4 calibration machinery. Richer L2 forms
    (e.g. an LLM-generated multi-dimensional expectation with narrative,
    state, conviction, and read) can travel in `extras` as a plain dict
    and be rendered by consumers (reports, inspection surfaces). The
    library itself does not interpret `extras` — it's a forward-compatible
    payload channel for domain-specific hypothesis content.
    """
    region_id:  int
    label:      str                       # human-readable, usually = region.label
    direction:  Any                       # the top-1 predicted outcome
    conviction: float                     # in [0, 1]; = mode_share within the training window
    top3:       list[tuple[Any, float]]   # [(outcome, prob), ...] top-3 outcomes
    timestamp:  datetime                  # when the hypothesis was generated
    n_train:    int                       # training-set size that produced it
    extras:     dict | None = None        # optional richer payload (e.g. {narrative, state, score, read})


@runtime_checkable
class HypothesisGenerator(Protocol):
    def generate(
        self,
        region:       Region,
        train_events: list[Event],
        timestamp:    datetime,
    ) -> Hypothesis | None:
        ...


def _outcome_of(e: Event) -> Any:
    """Default outcome-extractor: read e.outcome. Returns None if absent."""
    return e.outcome


class EmpiricalHypothesisGenerator:
    """
    Per-region empirical distribution of outcomes.

    Skips training events with outcome = None. Returns None for regions with
    no labeled training observations.
    """

    def __init__(self, min_train: int = 1):
        self.min_train = min_train

    def generate(
        self,
        region:       Region,
        train_events: list[Event],
        timestamp:    datetime,
    ) -> Hypothesis | None:
        member_ids = set(region.member_event_ids)
        in_region  = [e for e in train_events if e.id in member_ids]
        labeled    = [(e, _outcome_of(e)) for e in in_region if _outcome_of(e) is not None]
        if len(labeled) < self.min_train:
            return None
        counts = Counter(o for _, o in labeled)
        total  = sum(counts.values())
        ranked = counts.most_common()
        top_outcome, top_count = ranked[0]
        top3 = [(o, c / total) for o, c in ranked[:3]]
        return Hypothesis(
            region_id  = region.id,
            label      = region.label,
            direction  = top_outcome,
            conviction = top_count / total,
            top3       = top3,
            timestamp  = timestamp,
            n_train    = total,
        )


def generate_all(
    regions:      Iterable[Region],
    train_events: list[Event],
    timestamp:    datetime,
    generator:    HypothesisGenerator | None = None,
) -> list[Hypothesis]:
    """Convenience: run the generator over a collection of regions."""
    gen = generator or EmpiricalHypothesisGenerator()
    out: list[Hypothesis] = []
    for r in regions:
        h = gen.generate(r, train_events, timestamp)
        if h is not None:
            out.append(h)
    return out
