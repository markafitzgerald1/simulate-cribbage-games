"""Descriptive Pone lead diagnostics from a validated published lines pair."""

from __future__ import annotations

import math
from statistics import fmean, pstdev
from typing import Any

from artifact_pipeline.play_lines import decode_lines


def _measure_key(
    pone_rows: list[list[Any]], minimum_lead_count: int, z_threshold: float
) -> dict[str, Any] | None:
    rows = [row for row in pone_rows if row[1] >= minimum_lead_count]
    if len(rows) < 2:
        return None
    mode = min(rows, key=lambda row: (-row[1], row[0]))
    count = sum(row[1] for row in rows)
    mixture_mean = sum(row[1] * row[2] for row in rows) / count
    return {
        "flagged": any(
            row[2] > mode[2]
            and row[2] - mode[2] >= z_threshold * math.hypot(row[3], mode[3])
            for row in rows
        ),
        "gain": max(row[2] for row in rows) - mixture_mean,
        "eligible_samples": count,
    }


def measure_quality(
    lines_bytes: bytes,
    means_bytes: bytes,
    minimum_lead_count: int = 100,
    z_threshold: float = 3.0,
    include_key_statistics: bool = False,
) -> dict[str, Any]:
    """Screen observed Pone lines, including their policy-specific continuations."""
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
    key_statistics = {}
    gains = []
    flagged = 0
    eligible_samples = 0
    observed_samples = 0
    for key, (pone_rows, _dealer_rows) in zip(lines["keys"], lines["entries"]):
        observed_samples += sum(row[1] for row in pone_rows)
        cell = _measure_key(pone_rows, minimum_lead_count, z_threshold)
        if cell is None:
            continue
        flagged += cell["flagged"]
        eligible_samples += cell["eligible_samples"]
        gains.append(cell["gain"])
        key_statistics[key] = {"flagged": cell["flagged"], "gain": cell["gain"]}
    return {
        **({"key_statistics": key_statistics} if include_key_statistics else {}),
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
