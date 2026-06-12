"""
beliefstack.warrants — v0.1 spec-aligned warrant primitives.

Implements the warrant types pinned in the Belief Stack v0.1 specification
at https://topicspace.ai/research/belief-stack and the JSON schema at
https://topicspace.ai/schemas/warrant-v0.1.json.

A warrant is the evidence backing a label. Two variants:

- DecayingWarrant: authority decays over time toward a half-life. For
  substrates where context is time-sensitive (markets narratives,
  conversation regimes).
- InvariantWarrant: authority is binary. Either the evidence_refs still
  validate against the L0 substrate or they don't. For substrates with
  hard structural invariants (financial reasoning, arithmetic tie-outs).

A Belief is a (label, warrant) pair. The contract: no label without a
warrant; the warrant is what makes the label inspectable, falsifiable,
and able to participate in downstream coverage checks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional


# ─── Type aliases (mirror the v0.1 JSON schema enums) ──────────────────────
CoverageStatus = Literal["IN_DISTRIBUTION", "OUT_OF_DISTRIBUTION", "UNCLASSIFIED"]
ValidationStatus = Literal["PASS", "FAIL", "UNKNOWN"]
WarrantType = Literal["decaying", "invariant"]

SCHEMA_VERSION = "warrant-v0.1"
LN2 = 0.6931471805599453  # math.log(2) — fixed to avoid recomputation


# ─── Base warrant ──────────────────────────────────────────────────────────
@dataclass
class BaseWarrant:
    """
    Shared fields required of every warrant variant (per the v0.1 schema).

    Subclasses extend with variant-specific fields (half-life for decaying;
    evidence_refs + validation_status for invariant).
    """

    birth_timestamp: datetime
    support_n: int = 0
    coverage_status: CoverageStatus = "UNCLASSIFIED"
    confidence: Optional[float] = None
    distance_to_centroid: Optional[float] = None
    coverage_threshold: Optional[float] = None

    def __post_init__(self) -> None:
        if self.support_n < 0:
            raise ValueError(f"support_n must be >= 0, got {self.support_n}")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")
        if self.coverage_status not in ("IN_DISTRIBUTION", "OUT_OF_DISTRIBUTION", "UNCLASSIFIED"):
            raise ValueError(f"invalid coverage_status: {self.coverage_status}")

    @property
    def warrant_type(self) -> WarrantType:
        raise NotImplementedError("subclasses must define warrant_type")

    def get_weight(self, current_time: datetime) -> float:
        """
        Current authority weight in [0, 1]. Subclasses define the rule.

        Decaying warrants apply exponential decay against half-life.
        Invariant warrants return 1.0 if validation_status is PASS, else 0.0.
        """
        raise NotImplementedError

    def to_dict(self) -> dict:
        """Serialize to a dict matching warrant-v0.1.json schema."""
        d = {
            "schema_version": SCHEMA_VERSION,
            "warrant_type": self.warrant_type,
            "birth_timestamp": self.birth_timestamp.isoformat(),
            "support_n": self.support_n,
            "coverage_status": self.coverage_status,
        }
        if self.confidence is not None:
            d["confidence"] = self.confidence
        if self.distance_to_centroid is not None:
            d["distance_to_centroid"] = self.distance_to_centroid
        if self.coverage_threshold is not None:
            d["coverage_threshold"] = self.coverage_threshold
        return d


# ─── Decaying warrant ──────────────────────────────────────────────────────
@dataclass
class DecayingWarrant(BaseWarrant):
    """
    A warrant whose authority decays exponentially toward zero on a fixed
    half-life. Used for time-sensitive priors.

    At t = birth_timestamp, weight = initial_confidence.
    At t = birth + half_life, weight = initial_confidence / 2.
    At t = birth + N * half_life, weight = initial_confidence / 2^N.
    """

    initial_confidence: float = 1.0
    half_life: timedelta = field(default_factory=lambda: timedelta(hours=6))

    def __post_init__(self) -> None:
        super().__post_init__()
        if not (0.0 <= self.initial_confidence <= 1.0):
            raise ValueError(
                f"initial_confidence must be in [0, 1], got {self.initial_confidence}"
            )
        if self.half_life.total_seconds() <= 0:
            raise ValueError(f"half_life must be positive, got {self.half_life}")

    @property
    def warrant_type(self) -> WarrantType:
        return "decaying"

    def get_weight(self, current_time: datetime) -> float:
        elapsed_seconds = (current_time - self.birth_timestamp).total_seconds()
        if elapsed_seconds <= 0:
            return self.initial_confidence
        half_lives_elapsed = elapsed_seconds / self.half_life.total_seconds()
        return self.initial_confidence * math.exp(-LN2 * half_lives_elapsed)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["relaxation_half_life_seconds"] = int(self.half_life.total_seconds())
        return d


# ─── Invariant warrant ─────────────────────────────────────────────────────
@dataclass
class InvariantWarrant(BaseWarrant):
    """
    A warrant whose authority is binary. Authority is 1.0 while the
    evidence_refs still validate against the L0 substrate, 0.0 otherwise.

    Used for substrates with hard structural invariants — financial
    reasoning steps, arithmetic tie-outs, schema-typed operations.
    """

    evidence_refs: list[str] = field(default_factory=list)
    validation_status: ValidationStatus = "UNKNOWN"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.validation_status not in ("PASS", "FAIL", "UNKNOWN"):
            raise ValueError(f"invalid validation_status: {self.validation_status}")

    @property
    def warrant_type(self) -> WarrantType:
        return "invariant"

    def get_weight(self, current_time: datetime) -> float:
        # current_time is intentionally unused — invariant warrants don't decay.
        # Authority is determined entirely by the validation status.
        return 1.0 if self.validation_status == "PASS" else 0.0

    def to_dict(self) -> dict:
        d = super().to_dict()
        if self.evidence_refs:
            d["evidence_refs"] = list(self.evidence_refs)
        d["validation_status"] = self.validation_status
        return d


# ─── Belief: label + warrant ───────────────────────────────────────────────
@dataclass
class Belief:
    """
    The L1 representation contract in one object: a label paired with the
    warrant that licenses it.

    A Belief without a warrant is broken regardless of how confident the
    label looks. A Belief with a warrant — even a weak one — is
    inspectable, falsifiable, and able to participate in coverage checks.
    """

    label: str
    warrant: BaseWarrant

    def get_authority(self, current_time: datetime) -> float:
        """Convenience: the warrant's current authority weight."""
        return self.warrant.get_weight(current_time)

    def is_active(self, current_time: datetime, threshold: float = 0.1) -> bool:
        """Whether the belief's warrant survives the given threshold check."""
        return self.get_authority(current_time) >= threshold

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "warrant": self.warrant.to_dict(),
        }


# ─── Schema-aligned dict round-tripping ────────────────────────────────────
def warrant_from_dict(d: dict) -> BaseWarrant:
    """
    Reconstruct a warrant from a dict matching warrant-v0.1.json.

    Dispatches on warrant_type. Raises ValueError if schema_version or
    warrant_type is missing/unknown.
    """
    if d.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema_version: {d.get('schema_version')!r} "
            f"(expected {SCHEMA_VERSION!r})"
        )
    wtype = d.get("warrant_type")
    if wtype not in ("decaying", "invariant"):
        raise ValueError(f"invalid warrant_type: {wtype!r}")

    birth_ts = datetime.fromisoformat(d["birth_timestamp"])

    common = {
        "birth_timestamp": birth_ts,
        "support_n": d.get("support_n", 0),
        "coverage_status": d.get("coverage_status", "UNCLASSIFIED"),
        "confidence": d.get("confidence"),
        "distance_to_centroid": d.get("distance_to_centroid"),
        "coverage_threshold": d.get("coverage_threshold"),
    }

    if wtype == "decaying":
        half_life_s = d.get("relaxation_half_life_seconds")
        if half_life_s is None:
            raise ValueError("decaying warrant requires relaxation_half_life_seconds")
        return DecayingWarrant(
            **common,
            initial_confidence=d.get("confidence") or 1.0,
            half_life=timedelta(seconds=int(half_life_s)),
        )
    return InvariantWarrant(
        **common,
        evidence_refs=list(d.get("evidence_refs", [])),
        validation_status=d.get("validation_status", "UNKNOWN"),
    )
