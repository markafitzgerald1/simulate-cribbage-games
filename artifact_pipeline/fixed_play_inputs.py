"""Complete digest-bound frozen discard populations for fixed measurement."""

from collections import Counter
import json
from pathlib import Path
from typing import Any, Mapping

from artifact_pipeline.generate_play_table import (
    DiscardPolicy,
    discard_keeps_fingerprint,
)
from artifact_pipeline.pegging import ROLES
from artifact_pipeline.six_layer_policy import (
    verified_component,
    close_component,
    _unique_object,
)


def load_fixed_discards(root: Path, spec: Mapping[str, Any]) -> DiscardPolicy:
    """Validate a complete frozen rank keep map; never refine or invent keeps."""
    data = verified_component(root, spec)
    try:
        document = json.loads(data[:], object_pairs_hook=_unique_object)
    finally:
        close_component(data)
    if not isinstance(document, dict) or not isinstance(document.get("keeps"), list):
        raise ValueError("Frozen discard document needs keep rows")
    keeps = {}
    for row in document["keeps"]:
        if (
            not isinstance(row, list)
            or len(row) != 3
            or not isinstance(row[1], list)
            or not isinstance(row[2], list)
        ):
            raise ValueError("Malformed discard row")
        role, dealt, kept = row
        if (
            role not in ROLES
            or len(dealt) != 6
            or len(kept) != 4
            or dealt != sorted(dealt)
            or kept != sorted(kept)
        ):
            raise ValueError("Invalid canonical discard row")
        if any(
            not isinstance(rank, int) or isinstance(rank, bool) or not 0 <= rank < 13
            for rank in (*dealt, *kept)
        ):
            raise ValueError("Invalid discard rank")
        available: Counter[int] = Counter(dealt)
        chosen: Counter[int] = Counter(kept)
        if max(available.values()) > 4 or chosen - available:
            raise ValueError("Impossible discard row")
        key = (role, tuple(dealt))
        if key in keeps:
            raise ValueError("Duplicate discard row")
        keeps[key] = tuple(kept)
    if len(keeps) != 2 * 18395:
        raise ValueError(
            "Frozen discards must cover every canonical six-card hand/role"
        )
    policy = DiscardPolicy(keeps)
    if discard_keeps_fingerprint(policy) != spec.get("keep_fingerprint"):
        raise ValueError("Discard population fingerprint mismatch")
    if (
        spec.get("converged") is not False
        or not isinstance(spec.get("description"), str)
        or not spec["description"].strip()
    ):
        raise ValueError(
            "Frozen discard population needs honest lack of convergence/limits"
        )
    return policy
