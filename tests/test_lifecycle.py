"""Tests for the L3 lifecycle state transitions."""

from datetime import datetime

import pytest

from beliefstack.lifecycle import (
    LifecycleThresholds,
    update_lifecycle,
)


T0 = datetime(2026, 5, 21, 9, 0, 0)


def _base(**overrides):
    """Helper: build a minimal kwargs dict and override specific fields."""
    kwargs = dict(
        region_id=7,
        timestamp=T0,
        prior_state=None,
        prior_top1=None,
        current_top1=0.5,
        current_n=20,
    )
    kwargs.update(overrides)
    return kwargs


def test_born_on_first_observation():
    e = update_lifecycle(**_base())
    assert e.to_state   == "born"
    assert e.from_state is None
    assert "first" in e.reason


def test_retired_when_sample_collapses():
    t = LifecycleThresholds(min_n_active=5)
    e = update_lifecycle(
        **_base(prior_state="strengthened", prior_top1=0.7, current_top1=0.5, current_n=3),
        thresholds=t,
    )
    assert e.to_state == "retired"


def test_reopened_after_retired_when_evidence_returns():
    t = LifecycleThresholds(min_n_active=5, reopen_n=10)
    e = update_lifecycle(
        **_base(prior_state="retired", prior_top1=None, current_top1=0.5, current_n=12),
        thresholds=t,
    )
    assert e.to_state == "reopened"


def test_strengthened_on_material_top1_gain():
    e = update_lifecycle(
        **_base(prior_state="weakened", prior_top1=0.40, current_top1=0.60, current_n=20),
    )
    assert e.to_state == "strengthened"


def test_weakened_on_material_top1_drop():
    e = update_lifecycle(
        **_base(prior_state="strengthened", prior_top1=0.70, current_top1=0.55, current_n=20),
    )
    assert e.to_state == "weakened"


def test_contradicted_when_below_baseline():
    e = update_lifecycle(
        **_base(prior_state="strengthened", prior_top1=0.60, current_top1=0.30, current_n=20,
                baseline_top1=0.50),
    )
    assert e.to_state == "contradicted"


def test_inverted_overrides_other_transitions():
    # Even with a great current top1, a strong negative prior-actual rank
    # correlation forces 'inverted'.
    e = update_lifecycle(
        **_base(prior_state="strengthened", prior_top1=0.6, current_top1=0.8, current_n=30,
                baseline_top1=0.5, prior_actual_corr=-0.6),
    )
    assert e.to_state == "inverted"


def test_no_material_change_holds_prior_state():
    e = update_lifecycle(
        **_base(prior_state="strengthened", prior_top1=0.60, current_top1=0.62, current_n=20),
    )
    assert e.to_state == "strengthened"
    assert "no material change" in e.reason


def test_first_measured_top1_after_born_strengthens():
    e = update_lifecycle(
        **_base(prior_state="born", prior_top1=None, current_top1=0.55, current_n=20),
    )
    assert e.to_state == "strengthened"


def test_threshold_overrides_change_classification():
    # With strict strengthened threshold, a small gain should NOT trigger 'strengthened'.
    t = LifecycleThresholds(strengthened_delta=0.20)
    e = update_lifecycle(
        **_base(prior_state="strengthened", prior_top1=0.50, current_top1=0.60, current_n=20),
        thresholds=t,
    )
    assert e.to_state == "strengthened"   # held - no material change exceeding delta
    assert "no material change" in e.reason


@pytest.mark.parametrize("prior,curr,expected", [
    (0.40, 0.60, "strengthened"),
    (0.70, 0.55, "weakened"),
    (0.50, 0.52, "strengthened"),   # holds prior 'strengthened' since change is small
])
def test_transitions_parametric(prior, curr, expected):
    e = update_lifecycle(
        **_base(prior_state="strengthened", prior_top1=prior, current_top1=curr, current_n=15),
    )
    assert e.to_state == expected
