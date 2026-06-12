"""
L0 - events.

The lowest layer: timestamped evidence with text, optional metadata, and an
optional outcome label used downstream for L4 calibration.

No domain assumptions. An Event is a generic record. Adapters in user code
are expected to map their own data into this shape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


@dataclass
class Event:
    """A single L0 evidence record."""

    id:        str
    timestamp: datetime
    text:      str
    metadata:  dict[str, Any]      = field(default_factory=dict)
    # `outcome` is the observed ground truth used at L4 calibration. It can be
    # a label, a numeric value, a tuple - whatever the domain's outcome labeler
    # produces. Leave None if not yet observed.
    outcome:   Any | None          = None

    def to_dict(self) -> dict:
        return {
            "id":        self.id,
            "timestamp": self.timestamp.isoformat(),
            "text":      self.text,
            "metadata":  self.metadata,
            "outcome":   self.outcome,
        }


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # tolerate "2026-05-21T13:00:00" or "2026-05-21"
        return datetime.fromisoformat(value)
    raise TypeError(f"unsupported timestamp type: {type(value).__name__}")


def load_events_jsonl(path: str | Path) -> list[Event]:
    """Load events from a JSONL file. Each line is one event record."""
    events: list[Event] = []
    with open(path) as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{i} - invalid JSON: {e}") from e
            events.append(Event(
                id        = str(d["id"]),
                timestamp = _parse_ts(d["timestamp"]),
                text      = str(d["text"]),
                metadata  = d.get("metadata", {}),
                outcome   = d.get("outcome"),
            ))
    return events


def filter_by_date_range(
    events: Iterable[Event],
    start:  datetime | None = None,
    end:    datetime | None = None,
) -> list[Event]:
    """Return events whose timestamp falls in [start, end). Either bound may be None."""
    out: list[Event] = []
    for e in events:
        if start is not None and e.timestamp < start:
            continue
        if end is not None and e.timestamp >= end:
            continue
        out.append(e)
    return out
