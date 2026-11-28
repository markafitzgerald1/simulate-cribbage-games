"""Observed first-exchange summaries paired with exact client means bytes."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from artifact_pipeline.export_uncertainty import (
    decode_sidecar,
    read_json,
    validate_measured_policy,
)
from artifact_pipeline.pegging import DEALER, ROLES, RunningStatistics

SCHEMA = "expected-play-lines.v2"
RANKS = "A23456789TJQK"
COLUMNS = [
    ["lead", "n", "mu", "se"],
    ["lead", "n", "mu", "se", "responses"],
]
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
            row: list[Any] = [
                lead,
                stats.n,
                round(stats.mean, 3) + 0.0 if stats.n >= 2 else None,
                float(f"{stats.standard_error:.2g}") if stats.n >= 2 else None,
            ]
            if role == DEALER:
                row.append(
                    [
                        [rank, count]
                        for rank, count in sorted(self.responses[lead].items())
                    ]
                )
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
    for name in ("measured_policy", "discard_policy_fingerprint"):
        if name in metadata:
            provenance[name] = metadata[name]
    return {
        "schema": SCHEMA,
        "means_sha256": hashlib.sha256(means_bytes).hexdigest(),
        "ranks": RANKS,
        "roles": list(ROLES),
        "columns": [columns.copy() for columns in COLUMNS],
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


def _validate_responses(responses: Any, ranks: list[str], count: int) -> None:
    if not isinstance(responses, list):
        raise ValueError("Invalid Dealer responses array")
    previous_rank = -1
    total = 0
    for pair in responses:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("Invalid Dealer response pair")
        rank, observations = pair
        if (
            not _integer(rank, 0, 12)
            or rank <= previous_rank
            or RANKS[rank] not in ranks
            or not _integer(observations, 1, count)
        ):
            raise ValueError("Invalid Dealer response rank or count")
        previous_rank = rank
        total += observations
    if total != count:
        raise ValueError("Dealer response counts must sum to the lead count")


def _validate_rows(rows: list[list[Any]], ranks: list[str], role_index: int) -> None:
    if not isinstance(rows, list):
        raise ValueError("Invalid lines rows array")
    previous_lead = -1
    for row in rows:
        if not isinstance(row, list) or len(row) != len(COLUMNS[role_index]):
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
        else:
            _validate_responses(row[4], ranks, count)


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
        "columns": COLUMNS,
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


def main() -> None:
    """Re-export lines from the exact measured pair named by its play sidecar."""
    parser = argparse.ArgumentParser(description=main.__doc__)
    for name in ("full", "means", "sidecar", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()

    full_bytes = args.full.read_bytes()
    means_bytes = args.means.read_bytes()
    sidecar = decode_sidecar(args.sidecar.read_bytes(), means_bytes)
    if (
        sidecar["table"] != "play"
        or sidecar["source_full_sha256"] != hashlib.sha256(full_bytes).hexdigest()
    ):
        raise ValueError("Play sidecar does not bind the supplied full table")

    lines = build_lines(read_json(full_bytes), means_bytes)
    encoded = (json.dumps(lines, separators=(",", ":"), sort_keys=True) + "\n").encode()
    decode_lines(encoded, means_bytes)
    # Exclusive creation protects all existing files, including input aliases.
    with args.output.open("xb") as output:
        output.write(encoded)
    print(
        f"Play lines: {len(encoded)} minified bytes; "
        f"{len(gzip.compress(encoded, 9, mtime=0))} gzip bytes"
    )


if __name__ == "__main__":  # pragma: no cover
    main()
