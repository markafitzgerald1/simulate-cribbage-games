"""Descriptive Pone lead diagnostics from a validated published lines pair."""

from __future__ import annotations

import math
from statistics import fmean, pstdev
from typing import Any

from artifact_pipeline.play_lines import decode_lines


def measure_quality(
    lines_bytes: bytes,
    means_bytes: bytes,
    minimum_lead_count: int = 100,
    z_threshold: float = 3.0,
) -> dict[str, Any]:
    """Compare sampled Pone leads; retain denominators and unavailable values."""
    if (
        not isinstance(minimum_lead_count, int)
        or isinstance(minimum_lead_count, bool)
        or minimum_lead_count < 2
    ):
        raise ValueError("Require integer lead count >= 2")
    if (
        isinstance(z_threshold, bool)
        or not math.isfinite(z_threshold)
        or z_threshold <= 0
    ):
        raise ValueError("Require finite positive z")
    lines = decode_lines(lines_bytes, means_bytes)
    gains = []
    flagged = 0
    eligible_samples = 0
    observed_samples = 0
    for pone_rows, _dealer_rows in lines["entries"]:
        observed_samples += sum(row[1] for row in pone_rows)
        rows = [row for row in pone_rows if row[1] >= minimum_lead_count]
        if len(rows) < 2:
            continue
        mode = min(rows, key=lambda row: (-row[1], row[0]))
        # Disjoint randomized lead groups: use both conditional sample SEs.
        flagged += any(
            row[2] > mode[2]
            and row[2] - mode[2] >= z_threshold * math.hypot(row[3], mode[3])
            for row in rows
        )
        count = sum(row[1] for row in rows)
        eligible_samples += count
        mixture_mean = sum(row[1] * row[2] for row in rows) / count
        gains.append(max(row[2] for row in rows) - mixture_mean)
    return {
        "minimum_lead_count": minimum_lead_count,
        "z_threshold": z_threshold,
        "keys_total": len(lines["keys"]),
        "keys_eligible": len(gains),
        "keys_flagged": flagged,
        "flagged_share": flagged / len(gains) if gains else None,
        "gain_mean": fmean(gains) if gains else None,
        "gain_population_sd": pstdev(gains) if gains else None,
        "gain_max": max(gains) if gains else None,
        "eligible_samples": eligible_samples,
        "observed_samples": observed_samples,
    }
