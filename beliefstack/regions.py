"""
L1 - regions.

Clusters of similar inputs in embedding space. Each region has a centroid,
a label (auto-generated or user-supplied), and a list of member event ids.

This module wraps scikit-learn KMeans for the default path. Alternative
clusterers (HDBSCAN, agglomerative, BIC-selected k) are out of scope here -
implement them by replacing `fit_regions` in user code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from sklearn.cluster import KMeans

from .events import Event


@dataclass
class Region:
    """An L1 cluster: centroid + members + a human-readable label."""
    id:               int
    centroid:         np.ndarray
    label:            str
    member_event_ids: list[str] = field(default_factory=list)

    @property
    def n_members(self) -> int:
        return len(self.member_event_ids)


def _default_label(region_id: int, members: list[Event]) -> str:
    """Pick the most common metadata tag or fall back to id."""
    if not members:
        return f"region_{region_id}"
    tags: dict[str, int] = {}
    for e in members:
        for k, v in e.metadata.items():
            if isinstance(v, str) and k in {"tag", "theme", "topic", "category"}:
                tags[v] = tags.get(v, 0) + 1
    if tags:
        return max(tags.items(), key=lambda kv: kv[1])[0]
    return f"region_{region_id}"


def fit_regions(
    embeddings: np.ndarray,
    events:     list[Event],
    k:          int = 8,
    *,
    random_state: int = 0,
    label_fn:     Callable[[int, list[Event]], str] | None = None,
) -> list[Region]:
    """
    Cluster `embeddings` into `k` regions with KMeans, then assemble Region
    objects with member ids and labels. `events` must align with `embeddings`
    row-wise.

    `label_fn(region_id, members) -> str` lets callers plug a custom labeler
    (e.g. an LLM that summarizes the region in a few words). Default uses the
    most frequent `tag`/`theme`/`topic`/`category` metadata field.
    """
    if len(embeddings) != len(events):
        raise ValueError(
            f"embeddings ({len(embeddings)}) and events ({len(events)}) must align"
        )
    if k <= 0:
        raise ValueError("k must be > 0")
    n = len(embeddings)
    if n == 0:
        return []
    eff_k = min(k, n)
    km = KMeans(n_clusters=eff_k, random_state=random_state, n_init="auto")
    labels = km.fit_predict(embeddings)
    labeler = label_fn or _default_label
    regions: list[Region] = []
    for rid in range(eff_k):
        member_indices = [i for i, lab in enumerate(labels) if lab == rid]
        members        = [events[i] for i in member_indices]
        regions.append(Region(
            id               = rid,
            centroid         = km.cluster_centers_[rid].astype(np.float32),
            label            = labeler(rid, members),
            member_event_ids = [m.id for m in members],
        ))
    return regions


def assign_to_regions(
    embeddings: np.ndarray,
    regions:    list[Region],
) -> np.ndarray:
    """
    For each row in `embeddings`, return the id of the nearest region centroid
    (by Euclidean distance). Output shape: (len(embeddings),) of int.
    """
    if not regions:
        raise ValueError("regions must be non-empty")
    centroids = np.stack([r.centroid for r in regions])
    # broadcast: (N,1,D) - (1,K,D) -> (N,K,D) -> norms (N,K)
    diff = embeddings[:, None, :] - centroids[None, :, :]
    dist = np.linalg.norm(diff, axis=2)
    nearest_idx = np.argmin(dist, axis=1)
    region_ids = np.array([regions[i].id for i in nearest_idx], dtype=np.int32)
    return region_ids
