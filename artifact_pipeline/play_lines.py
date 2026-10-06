"""Observed first-exchange summaries paired with exact client means bytes."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Any, Mapping

from artifact_pipeline.export_uncertainty import validate_measured_policy
from artifact_pipeline.pegging import DEALER, ROLES, RunningStatistics

SCHEMA = "expected-play-lines.v1"
RANKS = "A23456789TJQK"
QUALIFICATIONS = {
    "policy": "Observed frozen policy behavior, not optimal play; see joint_policy_converged.",
    "statistics": "Whole-hand delta conditional on opening lead, not alternative-action values; SE excludes policy-learning uncertainty.",
    "missing": "Absent means unavailable, never zero; n < 2 has null mean and SE.",
}


@dataclass
class OpeningLines:
    """Unrounded per-lead delta moments and observed response counts."""

    deltas: dict[int, RunningStatistics] = field(default_factory=dict)
    responses: dict[int, dict[int, int]] = field(default_factory=dict)

    def add(self, opening: list[int], delta: float) -> None:
        """Attribute the same simulation's complete-hand delta to its lead."""
        lead, response = opening
        self.deltas.setdefault(lead, RunningStatistics()).add(delta)
        counts = self.responses.setdefault(lead, {})
        counts[response] = counts.get(response, 0) + 1

    def checkpoint(self) -> dict[str, Any]:
        """Save exact online moments, without rounding or SE reconstruction."""
        return {
            str(lead): {
                "n": stats.n,
                "mean": stats.mean,
                "moment_2": stats.moment_2,
                "responses": self.responses[lead],
            }
            for lead, stats in self.deltas.items()
        }

    @classmethod
    def restore(cls, saved: Mapping[str, Any], total: int) -> OpeningLines:
        """Reject incomplete attribution instead of inventing prior samples."""
        result = cls()
        for lead, cell in saved.items():
            rank = int(lead)
            result.deltas[rank] = RunningStatistics(
                cell["n"], cell["mean"], cell["moment_2"]
            )
            result.responses[rank] = {
                int(response): count for response, count in cell["responses"].items()
            }
            if sum(result.responses[rank].values()) != cell["n"]:
                raise ValueError("Incomplete opening response counts")
        if sum(stats.n for stats in result.deltas.values()) != total:
            raise ValueError("Incomplete opening lead counts")
        return result

    def rows(self, role: str) -> list[list[Any]]:
        """Publish every observed lead, including thin cells, at fixed precision."""
        rows = []
        for lead, stats in sorted(self.deltas.items()):
            row = [
                lead,
                stats.n,
                round(stats.mean, 3) + 0.0 if stats.n >= 2 else None,
                float(f"{stats.standard_error:.2g}") if stats.n >= 2 else None,
            ]
            if role == DEALER:
                counts = self.responses[lead]
                response = min((-count, rank) for rank, count in counts.items())[1]
                row.extend([response, counts[response]])
            rows.append(row)
        return rows


def build_lines(full: Mapping[str, Any], means_bytes: bytes) -> dict[str, Any]:
    """Build the compact companion from the final measured full-table cells."""
    keys = sorted(
        (key for key in full if key != "__metadata__"),
        key=lambda key: tuple(RANKS.index(rank) for rank in key.split("_")),
    )
    metadata = full["__metadata__"]
    provenance = {
        name: metadata[name]
        for name in (
            "generation_method",
            "seed",
            "policy_fingerprint",
            "joint_policy_converged",
        )
    }
    # Enforced runs only; older and report-mode documents carry no such field.
    if "measured_policy" in metadata:
        provenance["measured_policy"] = metadata["measured_policy"]
    return {
        "schema": SCHEMA,
        "means_sha256": hashlib.sha256(means_bytes).hexdigest(),
        "ranks": RANKS,
        "roles": list(ROLES),
        "columns": [
            ["lead", "n", "mu", "se"],
            ["lead", "n", "mu", "se", "response", "response_n"],
        ],
        "precision": {"mu_decimals": 3, "se_significant_figures": 2},
        "provenance": provenance,
        "qualifications": QUALIFICATIONS,
        "keys": keys,
        "entries": [
            [
                OpeningLines.restore(
                    full[key][role]["opening"], full[key][role]["n"]
                ).rows(role)
                for role in ROLES
            ]
            for key in keys
        ],
    }


def _integer(value: Any, lower: int, upper: int) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and lower <= value <= upper
    )


def _validate_rows(rows: list[list[Any]], ranks: list[str], role_index: int) -> None:
    if not isinstance(rows, list):
        raise ValueError("Invalid lines rows array")
    previous_lead = -1
    for row in rows:
        if not isinstance(row, list) or len(row) != (4 if role_index == 0 else 6):
            raise ValueError("Invalid lines row width")
        lead, count, mean, error = row[:4]
        if (
            not _integer(lead, 0, 12)
            or lead <= previous_lead
            or not _integer(count, 1, 2**53 - 1)
        ):
            raise ValueError("Invalid lead or count")
        previous_lead = lead
        if count < 2:
            if mean is not None or error is not None:
                raise ValueError("Thin cell statistics must be null")
        elif (
            any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in (mean, error)
            )
            or error < 0
        ):
            raise ValueError("Invalid conditional moments")
        if role_index == 0:
            if RANKS[lead] not in ranks:
                raise ValueError("Lead absent from keyed Pone hand")
        elif (
            not _integer(row[4], 0, 12)
            or RANKS[row[4]] not in ranks
            or not _integer(row[5], 1, count)
        ):
            raise ValueError("Invalid modal response")


def decode_lines(lines_bytes: bytes, means_bytes: bytes) -> dict[str, Any]:
    """Validate pairing and positional cells; rejection means unavailable."""
    try:
        data = json.loads(lines_bytes)
        if not isinstance(data, dict):
            raise ValueError("Lines document must be an object")
        return _decode_document(data, means_bytes)
    except (AttributeError, KeyError, TypeError, IndexError, OverflowError) as error:
        raise ValueError("Malformed lines document") from error


def _decode_document(data: dict[str, Any], means_bytes: bytes) -> dict[str, Any]:
    header = {
        "schema": SCHEMA,
        "means_sha256": hashlib.sha256(means_bytes).hexdigest(),
        "ranks": RANKS,
        "roles": list(ROLES),
        "precision": {"mu_decimals": 3, "se_significant_figures": 2},
        "columns": [
            ["lead", "n", "mu", "se"],
            ["lead", "n", "mu", "se", "response", "response_n"],
        ],
    }
    if any(data.get(name) != value for name, value in header.items()):
        raise ValueError("Invalid lines contract or mismatched means digest")
    if any(
        not isinstance(data.get("qualifications", {}).get(name), str)
        or not data["qualifications"][name].strip()
        for name in QUALIFICATIONS
    ):
        raise ValueError("Missing lines qualifications")
    provenance = data["provenance"]
    if (
        not isinstance(provenance["seed"], int)
        or isinstance(provenance["seed"], bool)
        or not isinstance(provenance["joint_policy_converged"], bool)
        or any(
            not isinstance(provenance[name], str) or not provenance[name]
            for name in ("policy_fingerprint", "generation_method")
        )
    ):
        raise ValueError("Invalid frozen-policy provenance")
    validate_measured_policy(provenance)
    keys, entries = data["keys"], data["entries"]
    if (
        not isinstance(keys, list)
        or not isinstance(entries, list)
        or any(not isinstance(key, str) for key in keys)
    ):
        raise ValueError("Invalid lines key/entry arrays")
    if len(keys) != len(entries) or len(set(keys)) != len(keys):
        raise ValueError("Invalid lines key identities")
    for key, roles in zip(keys, entries):
        ranks = key.split("_")
        if (
            len(ranks) != 4
            or any(rank not in RANKS or len(rank) != 1 for rank in ranks)
            or not isinstance(roles, list)
            or len(roles) != 2
        ):
            raise ValueError("Invalid kept hand or roles")
        if ranks != sorted(ranks, key=RANKS.index):
            raise ValueError("Non-canonical kept hand")
        for role_index, rows in enumerate(roles):
            _validate_rows(rows, ranks, role_index)
    if keys != sorted(
        keys, key=lambda key: tuple(RANKS.index(rank) for rank in key.split("_"))
    ):
        raise ValueError("Lines keys must follow canonical rank order")
    return data
