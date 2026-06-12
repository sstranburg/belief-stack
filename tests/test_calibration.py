"""Tests for L4 walk-forward calibration."""

from datetime import datetime, timedelta

import pytest

from beliefstack.calibration import walk_forward_calibrate
from beliefstack.events      import Event
from beliefstack.hypotheses  import Hypothesis


BASE = datetime(2026, 5, 1, 9, 0, 0)


def _ev(eid, day, region_outcome, outcome):
    """Tiny helper. region_outcome is recorded in metadata for traceability."""
    return Event(
        id        = f"e{eid:03d}",
        timestamp = BASE + timedelta(days=day),
        text      = f"event {eid}",
        metadata  = {"theme": region_outcome},
        outcome   = outcome,
    )


def _hyp(region_id, direction, top3, n_train):
    return Hypothesis(
        region_id  = region_id,
        label      = f"r{region_id}",
        direction  = direction,
        conviction = next((p for o, p in top3 if o == direction), 1.0),
        top3       = top3,
        timestamp  = BASE,
        n_train    = n_train,
    )


def test_perfect_top1_when_prediction_matches_all_test():
    events = [
        _ev(1, day=1, region_outcome="A", outcome="high"),
        _ev(2, day=2, region_outcome="A", outcome="high"),
        _ev(3, day=10, region_outcome="A", outcome="high"),
        _ev(4, day=11, region_outcome="A", outcome="high"),
    ]
    region_ids = [0, 0, 0, 0]
    hyp = _hyp(0, "high", [("high", 1.0)], n_train=2)
    split = BASE + timedelta(days=5)
    [cal] = walk_forward_calibrate(
        events=events, region_ids=region_ids, hypotheses=[hyp], split_at=split,
    )
    assert cal.n_train       == 2
    assert cal.n_test        == 2
    assert cal.top1_accuracy == pytest.approx(1.0)
    assert cal.top3_accuracy == pytest.approx(1.0)
    assert cal.brier_score   == pytest.approx(0.0)


def test_zero_top1_when_every_prediction_misses():
    events = [
        _ev(1, day=1,  region_outcome="A", outcome="high"),
        _ev(2, day=10, region_outcome="A", outcome="quiet"),
        _ev(3, day=11, region_outcome="A", outcome="quiet"),
    ]
    region_ids = [0, 0, 0]
    hyp = _hyp(0, "high", [("high", 1.0)], n_train=1)
    split = BASE + timedelta(days=5)
    [cal] = walk_forward_calibrate(
        events=events, region_ids=region_ids, hypotheses=[hyp], split_at=split,
    )
    assert cal.n_test        == 2
    assert cal.top1_accuracy == pytest.approx(0.0)
    # top3 still misses because "quiet" was never in the predicted support.
    assert cal.top3_accuracy == pytest.approx(0.0)
    # Brier per event = (1 - 0)^2 + (0 - 1)^2 = 2.0 (predicted 'high' = 1, true = 'quiet' = 0
    # for 'high'; predicted 0 for 'quiet', true 1). Mean over 2 events = 2.0.
    assert cal.brier_score   == pytest.approx(2.0)


def test_partial_top3_credit():
    events = [
        _ev(1, day=1,  region_outcome="A", outcome="high"),
        _ev(2, day=10, region_outcome="A", outcome="moderate"),
        _ev(3, day=11, region_outcome="A", outcome="quiet"),
        _ev(4, day=12, region_outcome="A", outcome="moderate"),
    ]
    region_ids = [0, 0, 0, 0]
    # Predict 'high' top1; top3 includes 'moderate' and 'quiet' too.
    hyp = _hyp(0, "high", [("high", 0.5), ("moderate", 0.3), ("quiet", 0.2)], n_train=1)
    split = BASE + timedelta(days=5)
    [cal] = walk_forward_calibrate(
        events=events, region_ids=region_ids, hypotheses=[hyp], split_at=split,
    )
    assert cal.n_test        == 3
    assert cal.top1_accuracy == pytest.approx(0.0)   # all test outcomes != 'high'
    assert cal.top3_accuracy == pytest.approx(1.0)   # all test outcomes were in top3


def test_unlabeled_test_events_are_excluded_from_scoring():
    events = [
        _ev(1, day=1,  region_outcome="A", outcome="high"),
        # day 10 event has outcome=None - should be ignored in scoring
        Event(id="e002", timestamp=BASE + timedelta(days=10),
              text="x", metadata={}, outcome=None),
        _ev(3, day=11, region_outcome="A", outcome="high"),
    ]
    region_ids = [0, 0, 0]
    hyp = _hyp(0, "high", [("high", 1.0)], n_train=1)
    split = BASE + timedelta(days=5)
    [cal] = walk_forward_calibrate(
        events=events, region_ids=region_ids, hypotheses=[hyp], split_at=split,
    )
    assert cal.n_test        == 1   # only the labeled test event was scored
    assert cal.top1_accuracy == pytest.approx(1.0)


def test_no_test_events_yields_none_metrics():
    events = [
        _ev(1, day=1, region_outcome="A", outcome="high"),
        _ev(2, day=2, region_outcome="A", outcome="high"),
    ]
    region_ids = [0, 0]
    hyp = _hyp(0, "high", [("high", 1.0)], n_train=2)
    split = BASE + timedelta(days=10)  # all events are train
    [cal] = walk_forward_calibrate(
        events=events, region_ids=region_ids, hypotheses=[hyp], split_at=split,
    )
    assert cal.n_test         == 0
    assert cal.top1_accuracy  is None
    assert cal.top3_accuracy  is None
    assert cal.brier_score    is None


def test_misaligned_inputs_raise():
    with pytest.raises(ValueError, match="must align"):
        walk_forward_calibrate(
            events=[_ev(1, day=1, region_outcome="A", outcome="high")],
            region_ids=[0, 0],   # mismatched length
            hypotheses=[],
            split_at=BASE,
        )


def test_split_is_chronological_and_half_open():
    # Event exactly at split_at should fall into TEST (split is [start, split_at) train,
    # [split_at, end] test).
    events = [
        _ev(1, day=1, region_outcome="A", outcome="high"),  # train
        Event(id="e002", timestamp=BASE + timedelta(days=5),
              text="boundary", metadata={}, outcome="high"),  # test (=split_at)
    ]
    region_ids = [0, 0]
    hyp = _hyp(0, "high", [("high", 1.0)], n_train=1)
    split = BASE + timedelta(days=5)
    [cal] = walk_forward_calibrate(
        events=events, region_ids=region_ids, hypotheses=[hyp], split_at=split,
    )
    assert cal.n_test == 1
