"""
beliefstack - a minimal L0 -> L4 belief-revision library.

Layers:
    L0  events       - timestamped evidence
    L1  regions      - learned clusters of similar inputs
    L2  hypotheses   - per-region forward predictions
    L3  lifecycle    - born / strengthened / weakened / contradicted / retired / reopened / inverted
    L4  calibration  - walk-forward measurement of L2 against held-out outcomes

The decisions and reports modules sit on top: they consume L3 + L4 outputs and
emit human-readable artifacts.

The warrants module implements the v0.1 spec-aligned primitives — Belief,
DecayingWarrant, InvariantWarrant — matching the schema at
https://topicspace.ai/schemas/warrant-v0.1.json.
"""

from .events       import Event, load_events_jsonl, filter_by_date_range
from .embeddings   import EmbeddingAdapter, MockEmbedder, get_default_embedder
from .regions      import Region, fit_regions, assign_to_regions
from .hypotheses   import Hypothesis, EmpiricalHypothesisGenerator
from .lifecycle    import LifecycleEvent, LifecycleState, update_lifecycle
from .calibration  import CalibrationResult, walk_forward_calibrate
from .decisions    import Decision, DecisionClass, classify_region, DecisionConfig
from .reports      import render_region_cards_html
from .warrants     import (
    BaseWarrant, DecayingWarrant, InvariantWarrant, Belief,
    CoverageStatus, ValidationStatus, WarrantType,
    SCHEMA_VERSION, warrant_from_dict,
)

__version__ = "0.1.0"

__all__ = [
    "Event", "load_events_jsonl", "filter_by_date_range",
    "EmbeddingAdapter", "MockEmbedder", "get_default_embedder",
    "Region", "fit_regions", "assign_to_regions",
    "Hypothesis", "EmpiricalHypothesisGenerator",
    "LifecycleEvent", "LifecycleState", "update_lifecycle",
    "CalibrationResult", "walk_forward_calibrate",
    "Decision", "DecisionClass", "classify_region", "DecisionConfig",
    "render_region_cards_html",
    # v0.1 spec primitives
    "BaseWarrant", "DecayingWarrant", "InvariantWarrant", "Belief",
    "CoverageStatus", "ValidationStatus", "WarrantType",
    "SCHEMA_VERSION", "warrant_from_dict",
]
