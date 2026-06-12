"""LLM-based hypothesis generator for the synthetic-themes demo (example-local).

Produces a *stateful expectation* per region rather than a discrete outcome
class with empirical priors. The expectation carries:

    narrative        - 1-2 sentence read on the theme
    state            - categorical: ESCALATING / RESOLVING / STALLING / MIXED
    score            - 0-100 magnitude of the expectation
    direction        - +1 / 0 / -1
    conviction       - 0.0-1.0
    read             - one-line forward interpretation
    predicted_class  - bridge to L4 calibration (one of the substrate's
                       outcome labels: escalated / resolved / stalled)

The expectation lives in `Hypothesis.extras`; `Hypothesis.direction` carries
`predicted_class` so the existing L3 lifecycle and L4 calibration machinery
continue to work unchanged. The point of L2 here is the expectation object;
`predicted_class` is the evaluation bridge, not the belief itself.

EXAMPLE-LOCAL — deliberately not promoted into the core library. The library
stays substrate-agnostic and LLM-free; substrate-specific generators (this
one for Teams chatter, future ones for other domains) live next to their
example. Promotion into core would require at least two substrates exercising
the same abstraction.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any

from beliefstack import Hypothesis
from beliefstack.events  import Event
from beliefstack.regions import Region

from _llm_client import chat_model, get_client


# Substrate-specific outcome label space. Kept here (not in the library) so
# domain conventions stay near the generator that knows about them.
OUTCOME_CLASSES = ("escalated", "resolved", "stalled")
STATE_VALUES    = ("ESCALATING", "RESOLVING", "STALLING", "MIXED")


_SYSTEM_PROMPT = (
    "You are an organizational-sensemaking analyst. You read clusters of "
    "internal chatter from a corporate MS Teams environment and produce "
    "structured forward expectations about how each theme is likely to "
    "evolve. You are concise, grounded in the signals shown, and you do not "
    "hedge with disclaimers."
)


def _build_user_prompt(region_label: str, snippets: list[str]) -> str:
    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(snippets))
    return f"""Theme label: {region_label}

Recent signals from internal MS Teams chatter ({len(snippets)} items, chronological):
{numbered}

Produce a JSON object with EXACTLY these fields and value constraints:

{{
  "narrative":       "1-2 sentence read on what this theme is currently about",
  "state":           one of [ESCALATING, RESOLVING, STALLING, MIXED],
  "score":           integer 0-100 (magnitude of the expectation),
  "direction":       integer in [+1, 0, -1]   (+1 escalating, 0 mixed/neutral, -1 stalling),
  "conviction":      number in [0.0, 1.0] (confidence in the read),
  "read":            "one-line forward interpretation (a single sentence)",
  "predicted_class": one of [escalated, resolved, stalled]   (most likely next observation outcome)
}}

Be specific. Ground your read in the signals above. Do not add fields beyond
the seven listed."""


def _coerce_int(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _coerce_float(v: Any, lo: float, hi: float, default: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, x))


def _normalize_expectation(raw: dict, fallback_top: str) -> dict:
    """Defensive shape-check on the LLM response."""
    state = str(raw.get("state", "MIXED")).upper()
    if state not in STATE_VALUES:
        state = "MIXED"
    predicted = str(raw.get("predicted_class", fallback_top))
    if predicted not in OUTCOME_CLASSES:
        predicted = fallback_top
    return {
        "narrative":       str(raw.get("narrative", "") or "")[:600],
        "state":           state,
        "score":           _coerce_int(raw.get("score"),       0,   100, 50),
        "direction":       _coerce_int(raw.get("direction"),  -1,   1,   0),
        "conviction":      _coerce_float(raw.get("conviction"), 0.0, 1.0, 0.5),
        "read":            str(raw.get("read", "") or "")[:300],
        "predicted_class": predicted,
    }


class LLMTeamsExpectationGenerator:
    """L2 generator that calls an LLM to produce a stateful expectation.

    Satisfies the `HypothesisGenerator` Protocol. One LLM call per region per
    pass. Output populates `Hypothesis.extras` with the expectation fields;
    `Hypothesis.direction` carries `predicted_class` so existing L3/L4
    machinery works unchanged.
    """

    def __init__(self, min_train: int = 2, model: str | None = None):
        self.min_train = min_train
        self.model     = model or chat_model()

    def generate(
        self,
        region:       Region,
        train_events: list[Event],
        timestamp:    datetime,
    ) -> Hypothesis | None:
        member_ids = set(region.member_event_ids)
        in_region  = [e for e in train_events if e.id in member_ids]
        if len(in_region) < self.min_train:
            return None

        snippets = [e.text for e in in_region]

        # Compute an empirical fallback for predicted_class so a bad LLM
        # response can't break the L4 bridge.
        labeled = [e.outcome for e in in_region if e.outcome is not None]
        if labeled:
            top_counts = Counter(labeled).most_common()
            fallback_top = top_counts[0][0]
            empirical_top3 = [
                (o, c / len(labeled)) for o, c in top_counts[:3]
            ]
        else:
            fallback_top = "stalled"
            empirical_top3 = []

        client = get_client()
        resp = client.chat.completions.create(
            model           = self.model,
            response_format = {"type": "json_object"},
            temperature     = 0.4,
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": _build_user_prompt(region.label, snippets)},
            ],
        )
        raw_text = resp.choices[0].message.content or "{}"
        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError:
            raw = {}

        expectation = _normalize_expectation(raw, fallback_top=fallback_top)

        return Hypothesis(
            region_id  = region.id,
            label      = region.label,
            direction  = expectation["predicted_class"],       # bridges to L4
            conviction = expectation["conviction"],             # also used by L3/L4
            top3       = empirical_top3,                        # empirical, for inspection
            timestamp  = timestamp,
            n_train    = len(in_region),
            extras     = expectation,                           # the L2 object itself
        )
