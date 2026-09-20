"""Read-only marginal-statistics export; no generator or simulator imports."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any

SCHEMA = "expected-points-uncertainty.v1"
RANKS = list("A23456789TJQK")
ROLES = ["Dealer", "Pone"]
CRIB_SLOTS = [
    "total",
    "matching_discard_suit",
    "non_matching_discard_suit",
    "matching_rank_1_suit",
    "matching_rank_2_suit",
]
QUALIFICATIONS = {
    "crib": "Weighted marginal formula is not established as calibrated; "
    "joint and squared-weight residual moments are unavailable. "
    "Root and relation estimates overlap; do not add them.",
    "play": "Delta SE preserves own-minus-opponent pairing. Distinct entries "
    "are independently sampled conditional on frozen policies. "
    "Identical estimate identities cancel before comparisons.",
    "scope": "No policy-learning or model uncertainty; no global or "
    "twin-difference noise floor; missing is unavailable, not zero.",
}


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(data: bytes) -> dict[str, Any]:
    """Reject duplicate names and nonstandard numeric constants, recursively."""
    return _object(
        json.loads(
            data, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
    )


def _invalid_constant(value: str) -> None:
    raise ValueError(f"JSON value is not finite: {value}")


def encode_json(value: dict[str, Any]) -> bytes:
    """Write readable records for git diffs, without rounding numbers."""
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected a finite number")
    if not math.isfinite(value):
        raise ValueError("Expected a finite number")
    return value


def _keys(table: str, means: dict[str, Any]) -> list[str]:
    if table == "crib":
        ordered = [
            f"{first}_{second}_{suit}"
            for first, second in itertools.combinations_with_replacement(RANKS, 2)
            for suit in (["Unsuited"] if first == second else ["Suited", "Unsuited"])
        ]
    elif table == "play":
        ordered = [
            "_".join(hand) for hand in itertools.combinations_with_replacement(RANKS, 4)
        ]
    else:
        raise ValueError("Unknown table")
    # Rank order, not lexicographic: RANKS.index("T") sorts ten between nine
    # and jack, matching the published client table's own key order rather
    # than ASCII order, which would sort digits before "T" and land ten last.
    present = {key for key in means if key != "__metadata__"}
    if not present or not present <= set(ordered):
        raise ValueError("Unexpected artifact keys")
    return [key for key in ordered if key in present]


def _relations(key: str, rank: str) -> set[str]:
    first, second, suit = key.split("_")
    if suit == "Unsuited" and "J" not in (first, second):
        return set()
    if suit == "Suited" or first == second:
        result = set(CRIB_SLOTS[1:3])
        if rank in (first, second):
            result.remove("matching_discard_suit")
        return result
    result = set(CRIB_SLOTS[2:])
    if rank == first:
        result.remove("matching_rank_1_suit")
    if rank == second:
        result.remove("matching_rank_2_suit")
    return result


def mean_buckets(table: str, means: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Enumerate exactly the lookup inputs retained by the matching means."""
    result = {}
    for key in _keys(table, means):
        roles = _object(means[key])
        if set(roles) != set(ROLES):
            raise ValueError("Unexpected roles")
        for role in ROLES:
            entry = _object(roles[role])
            if table == "play":
                result[f"{key}/{role}/delta"] = entry
                continue
            if set(entry) != set(RANKS):
                raise ValueError("Unexpected starter ranks")
            for rank in RANKS:
                bucket = _object(entry[rank])
                result[f"{key}/{role}/{rank}/total"] = bucket
                relations = _object(bucket.get("starter_suit_relation", {}))
                if not set(relations) <= _relations(key, rank):
                    raise ValueError("Unexpected or impossible suit relations")
                for slot in CRIB_SLOTS[1:]:
                    if slot in relations:
                        result[f"{key}/{role}/{rank}/{slot}"] = _object(relations[slot])
    return result


def _matching_means(source: dict[str, Any], means: dict[str, Any]) -> None:
    """Check every displayed mean, including category means, without rebuilding it."""
    for key, value in means.items():
        if key == "__metadata__":
            continue
        if key not in source:
            raise ValueError(f"Missing source mean: {key}")
        if key == "mu":
            if round(_number(source[key]), 4) != _number(value):
                raise ValueError("Source and client means do not match")
        else:
            _matching_means(_object(source[key]), _object(value))


def _statistics(table: str, source: dict[str, Any]) -> dict[str, Any] | None:
    names = ["se", "n"] + (["sum_w2"] if table == "crib" else [])
    values = {name: source[name] for name in names if name in source}
    for value in values.values():
        if _number(value) < 0:
            raise ValueError("Negative statistic")
    if "se" not in values or "n" not in values or values["n"] < 2:
        return None
    if table == "crib":
        values.setdefault("sum_w2", values["n"])
        if values["sum_w2"] <= 0 or values["n"] - values["sum_w2"] / values["n"] <= 0:
            return None
    elif int(values["n"]) != values["n"]:
        raise ValueError("Play simulation count must be integral")
    return {"reported_marginal_se": values.pop("se"), **values}


def _validate_provenance(table: str, provenance: dict[str, Any]) -> None:
    for value in provenance.values():
        if isinstance(value, (dict, list)):
            raise ValueError("Provenance must contain scalar values only")
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            _number(value)
    if table == "play":
        fingerprint = provenance.get("policy_fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError("Invalid play policy fingerprint")
        if not isinstance(provenance.get("joint_policy_converged"), bool):
            raise ValueError("Invalid play convergence status")


def build_sidecar(table: str, full_bytes: bytes, means_bytes: bytes) -> dict[str, Any]:
    """Export measured totals only; snapshot and policy values are never read."""
    full, means = read_json(full_bytes), read_json(means_bytes)
    buckets = mean_buckets(table, means)
    if set(full) - {"__metadata__"} != set(_keys(table, means)):
        raise ValueError("Full and client artifact keys differ")
    _matching_means(full, means)
    metadata = _object(full.get("__metadata__", {}))
    provenance = {
        key: value
        for key, value in metadata.items()
        if not isinstance(value, (dict, list))
    }
    _validate_provenance(table, provenance)
    records = {}
    for identity in buckets:
        path = identity.split("/")
        source = full[path[0]][path[1]]
        if table == "crib":
            source = source[path[2]]
            if path[3] != "total":
                source = source["starter_suit_relation"][path[3]]
        record = _statistics(table, source)
        if record is not None:
            records[identity] = record
    result = {
        "schema": SCHEMA,
        "table": table,
        "source_full_sha256": hashlib.sha256(full_bytes).hexdigest(),
        "means_sha256": hashlib.sha256(means_bytes).hexdigest(),
        "provenance": provenance,
        "statistic": "reported_marginal_se",
        "n_semantics": "sum_weights" if table == "crib" else "simulation_count",
        "cross_bucket_covariance": None,
        "policy_uncertainty": None,
        "calibrated_comparison_uncertainty": None,
        "qualifications": QUALIFICATIONS,
        "keys": _keys(table, means),
        "roles": ROLES,
        "ranks": RANKS if table == "crib" else [],
        "slots": CRIB_SLOTS if table == "crib" else ["delta"],
        "record_groups": {"totals": {"record_count": len(records), "records": records}},
    }
    return decode_sidecar(encode_json(result), means_bytes)


def _validate_qualifications(sidecar: dict[str, Any]) -> None:
    """Require the stable identifiers and non-empty text, not exact wording.

    Qualification wording is prose, not wire format: whole-dict equality
    against QUALIFICATIONS would force every published sidecar and every
    reader into lockstep on a wording-only edit.
    """
    qualifications = sidecar.get("qualifications")
    if not isinstance(qualifications, dict) or set(qualifications) != set(
        QUALIFICATIONS
    ):
        raise ValueError("Invalid sidecar field: qualifications")
    if any(
        not isinstance(value, str) or not value for value in qualifications.values()
    ):
        raise ValueError("Invalid sidecar field: qualifications")


def decode_sidecar(data: bytes, means_bytes: bytes) -> dict[str, Any]:
    """Validate version-1 totals; ignore separate, future record groups/fields."""
    sidecar = read_json(data)
    means = read_json(means_bytes)
    table = sidecar.get("table")
    if sidecar.get("schema") != SCHEMA or table not in ("crib", "play"):
        raise ValueError("Unsupported schema or table")
    expected = {
        "means_sha256": hashlib.sha256(means_bytes).hexdigest(),
        "statistic": "reported_marginal_se",
        "n_semantics": "sum_weights" if table == "crib" else "simulation_count",
        "keys": _keys(table, means),
        "roles": ROLES,
        "ranks": RANKS if table == "crib" else [],
        "slots": CRIB_SLOTS if table == "crib" else ["delta"],
        "cross_bucket_covariance": None,
        "policy_uncertainty": None,
        "calibrated_comparison_uncertainty": None,
    }
    for key, value in expected.items():
        if key not in sidecar or sidecar[key] != value:
            raise ValueError(f"Invalid sidecar field: {key}")
    _validate_qualifications(sidecar)
    digest = sidecar.get("source_full_sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise ValueError("Invalid source digest")
    provenance = _object(sidecar.get("provenance"))
    _validate_provenance(table, provenance)
    totals = _object(_object(sidecar.get("record_groups")).get("totals"))
    records = _object(totals.get("records"))
    if (
        isinstance(totals.get("record_count"), bool)
        or not isinstance(totals.get("record_count"), int)
        or totals["record_count"] != len(records)
    ):
        raise ValueError("Inconsistent record count")
    if not set(records) <= set(mean_buckets(table, means)):
        raise ValueError("Unexpected record identity")
    columns = ["reported_marginal_se", "n"] + (["sum_w2"] if table == "crib" else [])
    for record in records.values():
        record = _object(record)
        if any(column not in record for column in columns):
            raise ValueError("Missing statistic column")
        source = {
            "se": record["reported_marginal_se"],
            "n": record["n"],
            **({"sum_w2": record["sum_w2"]} if table == "crib" else {}),
        }
        if _statistics(table, source) is None:
            raise ValueError("Unsupported measured record")
    return sidecar


def export_files(table: str, full_path: Path, means_path: Path, output: Path) -> None:
    """Never write either input, even through a symlink or hard link."""
    for source in (full_path, means_path):
        if output.resolve() == source.resolve() or (
            output.exists() and output.samefile(source)
        ):
            raise ValueError("Output must not overwrite an input artifact")
    sidecar = build_sidecar(table, full_path.read_bytes(), means_path.read_bytes())
    output.write_bytes(encode_json(sidecar))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", choices=("crib", "play"), required=True)
    parser.add_argument("--full", type=Path, required=True)
    parser.add_argument("--means", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export_files(args.table, args.full, args.means, args.output)


if __name__ == "__main__":
    main()
