"""
Tests for the v0.1 spec-aligned warrant primitives.

Covers:
- DecayingWarrant exponential-decay math at characteristic points
- InvariantWarrant binary authority
- Belief authority + is_active threshold check
- Round-trip serialization through warrant-v0.1 schema
- Validation errors on malformed inputs
"""

from datetime import datetime, timedelta

import pytest

from beliefstack.warrants import (
    BaseWarrant,
    DecayingWarrant,
    InvariantWarrant,
    Belief,
    warrant_from_dict,
    SCHEMA_VERSION,
)


T0 = datetime(2026, 5, 28, 23, 59, 0)
SIX_HOURS = timedelta(hours=6)


# ─── DecayingWarrant: the math ─────────────────────────────────────────────
def test_decaying_warrant_at_birth_returns_initial_confidence():
    w = DecayingWarrant(birth_timestamp=T0, initial_confidence=1.0, half_life=SIX_HOURS)
    assert w.get_weight(T0) == pytest.approx(1.0)


def test_decaying_warrant_at_one_half_life_is_half_of_initial():
    w = DecayingWarrant(birth_timestamp=T0, initial_confidence=1.0, half_life=SIX_HOURS)
    weight = w.get_weight(T0 + SIX_HOURS)
    assert weight == pytest.approx(0.5, abs=1e-6)


def test_decaying_warrant_at_two_half_lives_is_quarter_of_initial():
    w = DecayingWarrant(birth_timestamp=T0, initial_confidence=1.0, half_life=SIX_HOURS)
    weight = w.get_weight(T0 + 2 * SIX_HOURS)
    assert weight == pytest.approx(0.25, abs=1e-6)


def test_decaying_warrant_before_birth_clamps_to_initial():
    """If queried before the warrant was born, return initial confidence (no negative decay)."""
    w = DecayingWarrant(birth_timestamp=T0, initial_confidence=0.8, half_life=SIX_HOURS)
    assert w.get_weight(T0 - timedelta(hours=1)) == pytest.approx(0.8)


def test_decaying_warrant_initial_confidence_scales_decay():
    w = DecayingWarrant(birth_timestamp=T0, initial_confidence=0.6, half_life=SIX_HOURS)
    weight = w.get_weight(T0 + SIX_HOURS)
    assert weight == pytest.approx(0.3, abs=1e-6)


def test_decaying_warrant_after_many_half_lives_approaches_zero():
    w = DecayingWarrant(birth_timestamp=T0, initial_confidence=1.0, half_life=SIX_HOURS)
    weight = w.get_weight(T0 + timedelta(hours=72))
    assert weight < 0.001


def test_decaying_warrant_rejects_invalid_initial_confidence():
    with pytest.raises(ValueError):
        DecayingWarrant(birth_timestamp=T0, initial_confidence=1.5, half_life=SIX_HOURS)
    with pytest.raises(ValueError):
        DecayingWarrant(birth_timestamp=T0, initial_confidence=-0.1, half_life=SIX_HOURS)


def test_decaying_warrant_rejects_nonpositive_half_life():
    with pytest.raises(ValueError):
        DecayingWarrant(birth_timestamp=T0, initial_confidence=1.0, half_life=timedelta(0))


# ─── InvariantWarrant: binary authority ────────────────────────────────────
def test_invariant_warrant_pass_returns_full_authority():
    w = InvariantWarrant(
        birth_timestamp=T0,
        evidence_refs=["json.company.ebitda"],
        validation_status="PASS",
    )
    assert w.get_weight(T0) == 1.0
    # And does not decay over time.
    assert w.get_weight(T0 + timedelta(days=30)) == 1.0


def test_invariant_warrant_fail_returns_zero_authority():
    w = InvariantWarrant(
        birth_timestamp=T0,
        evidence_refs=["json.company.ebitda"],
        validation_status="FAIL",
    )
    assert w.get_weight(T0) == 0.0


def test_invariant_warrant_unknown_returns_zero_authority():
    w = InvariantWarrant(birth_timestamp=T0, validation_status="UNKNOWN")
    assert w.get_weight(T0) == 0.0


def test_invariant_warrant_rejects_invalid_validation_status():
    with pytest.raises(ValueError):
        InvariantWarrant(birth_timestamp=T0, validation_status="MAYBE")


# ─── Belief: label + warrant ───────────────────────────────────────────────
def test_belief_authority_matches_warrant_weight():
    w = DecayingWarrant(birth_timestamp=T0, initial_confidence=1.0, half_life=SIX_HOURS)
    b = Belief(label="USER_SLEEPING", warrant=w)
    assert b.get_authority(T0) == pytest.approx(1.0)
    assert b.get_authority(T0 + SIX_HOURS) == pytest.approx(0.5, abs=1e-6)


def test_belief_is_active_with_default_threshold():
    w = DecayingWarrant(birth_timestamp=T0, initial_confidence=1.0, half_life=SIX_HOURS)
    b = Belief(label="USER_SLEEPING", warrant=w)
    assert b.is_active(T0)
    # After ~3 half-lives, authority is ~0.125 > 0.1, still active.
    assert b.is_active(T0 + 3 * SIX_HOURS)
    # After ~4 half-lives, authority is ~0.0625 < 0.1, no longer active.
    assert not b.is_active(T0 + 4 * SIX_HOURS)


def test_belief_is_active_respects_custom_threshold():
    w = DecayingWarrant(birth_timestamp=T0, initial_confidence=1.0, half_life=SIX_HOURS)
    b = Belief(label="USER_SLEEPING", warrant=w)
    assert b.is_active(T0 + SIX_HOURS, threshold=0.4)
    assert not b.is_active(T0 + SIX_HOURS, threshold=0.6)


# ─── Schema round-tripping ─────────────────────────────────────────────────
def test_decaying_warrant_serializes_to_v01_schema():
    w = DecayingWarrant(
        birth_timestamp=T0,
        initial_confidence=0.72,
        half_life=SIX_HOURS,
        support_n=337,
        coverage_status="IN_DISTRIBUTION",
        confidence=0.72,
        distance_to_centroid=0.81,
        coverage_threshold=0.93,
    )
    d = w.to_dict()
    assert d["schema_version"] == SCHEMA_VERSION
    assert d["warrant_type"] == "decaying"
    assert d["birth_timestamp"] == T0.isoformat()
    assert d["support_n"] == 337
    assert d["coverage_status"] == "IN_DISTRIBUTION"
    assert d["confidence"] == 0.72
    assert d["distance_to_centroid"] == 0.81
    assert d["coverage_threshold"] == 0.93
    assert d["relaxation_half_life_seconds"] == 6 * 3600


def test_invariant_warrant_serializes_to_v01_schema():
    w = InvariantWarrant(
        birth_timestamp=T0,
        support_n=1,
        coverage_status="IN_DISTRIBUTION",
        evidence_refs=["json.company.ebitda", "json.company.revenue"],
        validation_status="PASS",
    )
    d = w.to_dict()
    assert d["schema_version"] == SCHEMA_VERSION
    assert d["warrant_type"] == "invariant"
    assert d["evidence_refs"] == ["json.company.ebitda", "json.company.revenue"]
    assert d["validation_status"] == "PASS"
    assert "relaxation_half_life_seconds" not in d


def test_warrant_from_dict_round_trips_decaying():
    w = DecayingWarrant(
        birth_timestamp=T0,
        initial_confidence=0.72,
        half_life=SIX_HOURS,
        support_n=337,
        coverage_status="IN_DISTRIBUTION",
        confidence=0.72,
    )
    restored = warrant_from_dict(w.to_dict())
    assert isinstance(restored, DecayingWarrant)
    assert restored.birth_timestamp == w.birth_timestamp
    assert restored.support_n == w.support_n
    assert restored.coverage_status == w.coverage_status
    assert restored.half_life == w.half_life
    # Authority weights should match at multiple time points.
    for offset in (timedelta(0), SIX_HOURS, 2 * SIX_HOURS):
        assert restored.get_weight(T0 + offset) == pytest.approx(
            w.get_weight(T0 + offset), abs=1e-9
        )


def test_warrant_from_dict_round_trips_invariant():
    w = InvariantWarrant(
        birth_timestamp=T0,
        support_n=1,
        coverage_status="IN_DISTRIBUTION",
        evidence_refs=["json.company.ebitda"],
        validation_status="PASS",
    )
    restored = warrant_from_dict(w.to_dict())
    assert isinstance(restored, InvariantWarrant)
    assert restored.evidence_refs == w.evidence_refs
    assert restored.validation_status == "PASS"
    assert restored.get_weight(T0) == 1.0


def test_warrant_from_dict_rejects_unknown_schema_version():
    with pytest.raises(ValueError, match="schema_version"):
        warrant_from_dict({
            "schema_version": "warrant-v9.9",
            "warrant_type": "decaying",
            "birth_timestamp": T0.isoformat(),
            "support_n": 1,
            "coverage_status": "IN_DISTRIBUTION",
            "relaxation_half_life_seconds": 3600,
        })


def test_warrant_from_dict_rejects_invalid_warrant_type():
    with pytest.raises(ValueError, match="warrant_type"):
        warrant_from_dict({
            "schema_version": SCHEMA_VERSION,
            "warrant_type": "perpetual",
            "birth_timestamp": T0.isoformat(),
            "support_n": 1,
            "coverage_status": "IN_DISTRIBUTION",
        })


def test_decaying_warrant_from_dict_requires_half_life():
    with pytest.raises(ValueError, match="relaxation_half_life_seconds"):
        warrant_from_dict({
            "schema_version": SCHEMA_VERSION,
            "warrant_type": "decaying",
            "birth_timestamp": T0.isoformat(),
            "support_n": 1,
            "coverage_status": "IN_DISTRIBUTION",
        })


# ─── Base validation ───────────────────────────────────────────────────────
def test_base_warrant_rejects_invalid_coverage_status():
    with pytest.raises(ValueError):
        DecayingWarrant(
            birth_timestamp=T0,
            initial_confidence=1.0,
            half_life=SIX_HOURS,
            coverage_status="MAYBE_IN",  # type: ignore[arg-type]
        )


def test_base_warrant_rejects_negative_support_n():
    with pytest.raises(ValueError):
        DecayingWarrant(
            birth_timestamp=T0,
            initial_confidence=1.0,
            half_life=SIX_HOURS,
            support_n=-1,
        )


def test_base_warrant_rejects_confidence_out_of_range():
    with pytest.raises(ValueError):
        DecayingWarrant(
            birth_timestamp=T0,
            initial_confidence=1.0,
            half_life=SIX_HOURS,
            confidence=1.5,
        )
