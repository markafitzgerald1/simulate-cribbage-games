"""Read-only projection of the v4 crib uncertainty sidecar."""

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass

from artifact_pipeline.crib_decomposition import CribGroup, ROOT
from artifact_pipeline.crib_v4_state import (
    active_streams,
    bucket_statistics,
    coordinate_labels,
    decode_moments,
)

SCHEMA = "expected-points-uncertainty.v2"
SAMPLE_UNIT = "independent-vector-rows-per-active-stream"
CONTRACTS = {
    "generation_method": "artifact_pipeline.generate_table.v4",
    "estimator_contract": "shared-rank-relation-v1",
    "relation_centering_contract": "uniform-two-card-rank-completion-v1",
    "selector_contract": "legacy-suit-sensitive-first-max-v1",
    "rng_contract": "python-random-sample-v1",
    "sample_unit": SAMPLE_UNIT,
}
QUALIFICATIONS = {
    "crib": "Marginal sampling SE conditional on the frozen opponent policy. "
    "Root and relation estimates overlap.",
    "scope": "No coverage claim, policy-learning or model uncertainty. "
    "A twin-difference SE is specific to that comparison.",
}
HEADER = {
    "n_semantics": SAMPLE_UNIT,
    "uncertainty_scope": "fixed-policy-sampling",
    "selection_adjustment": None,
}
SOURCE_PROVENANCE = set(CONTRACTS) | {
    "policy_sha256",
    "bootstrap_sha256",
    "generation",
    "seed",
    "deck_order",
    "python_implementation",
    "python_version",
    "scale",
    "seed_was_specified",
    "use_control_variates",
    "phase",
    "convergence_shift",
}
MAX_SAFE_INTEGER = 2**53 - 1
PRODUCER_STATE = {"generation_accumulators", "estimator_state", "randomness_key"}
GUARD_STATUSES = ("resolved-positive", "resolved-negative", "unresolved")


def is_safe_integer(value, minimum=-MAX_SAFE_INTEGER):
    """JSON integers must survive a JavaScript reader unchanged."""
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and minimum <= value <= MAX_SAFE_INTEGER
    )


@dataclass(frozen=True)
class _Card:
    index: int
    suit: int


def validate_provenance(provenance):
    """Validate v4 sampling provenance shared by export and decode."""
    if PRODUCER_STATE & provenance.keys():
        raise ValueError("Unexpected v2 checkpoint state in provenance")
    for name, value in CONTRACTS.items():
        if provenance.get(name) != value:
            raise ValueError(f"Invalid v2 provenance: {name}")
    for name in ("policy_sha256", "bootstrap_sha256"):
        value = provenance.get(name)
        if name == "bootstrap_sha256" and name in provenance and value is None:
            continue
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)
        ):
            raise ValueError(f"Invalid v2 provenance: {name}")
    generation = provenance.get("generation")
    if not is_safe_integer(generation, 0):
        raise ValueError("Invalid v2 generation")
    if "seed" not in provenance or (
        provenance["seed"] is not None and not is_safe_integer(provenance["seed"])
    ):
        raise ValueError("Invalid v2 seed")
    if "convergence_shift" in provenance:
        shift = provenance["convergence_shift"]
        if type(shift) not in (int, float) or not 0 <= shift < math.inf:
            raise ValueError("Invalid v2 convergence shift")
    counts = {f"precut_{status.replace('-', '_')}" for status in GUARD_STATUSES}
    present = counts & provenance.keys()
    if present and (
        present != counts
        or any(not is_safe_integer(provenance[key], 0) for key in counts)
    ):
        raise ValueError("Invalid v2 pre-cut counts")


def build_provenance(metadata):
    """Keep scalar provenance and summarize the measured guard report."""
    provenance = {
        key: value
        for key, value in metadata.items()
        if key in SOURCE_PROVENANCE and not isinstance(value, (dict, list))
    }
    if "precut_twin_report" in metadata:
        report = metadata["precut_twin_report"]
        rows = report.get("rows") if isinstance(report, dict) else None
        if not isinstance(rows, list):
            raise ValueError("Malformed v2 pre-cut report")
        statuses = [
            row.get("status") if isinstance(row, dict) else None for row in rows
        ]
        if any(status not in GUARD_STATUSES for status in statuses):
            raise ValueError("Unknown pre-cut row status")
        counts = Counter(statuses)
        for status in GUARD_STATUSES:
            provenance[f"precut_{status.replace('-', '_')}"] = counts[status]
    validate_provenance(provenance)
    return provenance


def _group(rank_key, ranks):
    first, second = (ranks.index(rank) for rank in rank_key.split("_"))
    deck = tuple(_Card(rank, suit) for rank in range(len(ranks)) for suit in range(4))
    unsuited = (_Card(first, 0), _Card(second, 1))
    suited = (_Card(first, 0), _Card(second, 0)) if first != second else None
    return CribGroup(deck, unsuited, suited, 6)


def _require_complete_twins(metadata, keys):
    state = metadata.get("estimator_state")
    requested = metadata.get("requested_pairs")
    groups = {key.rsplit("_", 1)[0] for key in keys}
    expected = {
        f"{group}_{variant}"
        for group in groups
        for variant in ("Unsuited", "Suited")
        if variant == "Unsuited" or group.split("_")[0] != group.split("_")[1]
    }
    message = "v2 export requires matching measured state and complete twins"
    if (
        not isinstance(state, dict)
        or not isinstance(requested, list)
        or any(not isinstance(key, str) for key in requested)
    ):
        raise ValueError(message)
    if (
        set(state) != groups
        or len(requested) != len(keys)
        or set(requested) != expected
        or set(keys) != expected
    ):
        raise ValueError(message)


def validate_source(metadata, means, keys):
    """Bind the completed measurement to its coverage and frozen policy."""
    if metadata.get("phase") != "complete":
        raise ValueError("v2 export requires completed measured state")
    _require_complete_twins(metadata, keys)
    if "generation_accumulators" not in metadata:
        raise ValueError("Missing v2 frozen policy payload")
    policy = metadata["generation_accumulators"]
    policy_bytes = json.dumps(
        "legacy-static-policy-v1" if policy is None else policy,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    if hashlib.sha256(policy_bytes).hexdigest() != metadata["policy_sha256"]:
        raise ValueError("v2 frozen policy digest mismatch")
    validate_client_metadata(means, metadata)


def validate_client_metadata(means, provenance):
    """The client and v2 document must describe the same v4 generation."""
    client = means.get("__metadata__")
    if not isinstance(client, dict):
        raise ValueError("Missing v2 client metadata")
    for field in ("generation_method", "seed", "generation"):
        if (
            field not in client
            or type(client[field]) is not type(provenance[field])
            or client[field] != provenance[field]
        ):
            raise ValueError(f"v2 client metadata differs: {field}")


def _decode_role(state, rank_key, role, target, ranks):
    group = _group(rank_key, ranks)
    if set(state[rank_key]) != {"Dealer", "Pone"}:
        raise ValueError("v2 measured roles differ")
    payload = state[rank_key][role]["streams"]
    if not isinstance(payload, dict) or set(payload) != set(active_streams(group)):
        raise ValueError("v2 export requires the exact active streams")
    if any(stream["count"] != target for stream in payload.values()):
        raise ValueError("v2 measured stream did not reach its target")
    return {
        name: decode_moments(payload[name], coordinate_labels(group, ranks, name))
        for name in active_streams(group)
    }


def _measured_target(full):
    control = full["__metadata__"].get("run_control")
    target = control.get("target_samples") if isinstance(control, dict) else None
    if not is_safe_integer(target, 2):
        raise ValueError("Invalid v2 measured target")
    return target


def project_records(full, buckets, ranks):
    """Project and check every retained total from validated measured moments."""
    state = full["__metadata__"]["estimator_state"]
    target = _measured_target(full)
    streams = {}
    records = {}
    current_group = None
    for identity in buckets:
        rank_key = identity.split("/")[0].rsplit("_", 1)[0]
        role = identity.split("/")[1]
        if rank_key != current_group:
            streams.clear()
            current_group = rank_key
        if role not in streams:
            streams[role] = _decode_role(state, rank_key, role, target, ranks)
        records[identity] = _project_identity(full, streams[role], identity)
    return records


def _project_identity(full, role_streams, identity):
    key, role, rank, slot = identity.split("/")
    relation = ROOT if slot == "total" else slot
    stats = bucket_statistics(role_streams, rank, key.rsplit("_", 1)[1], relation)
    _require_measured_match(full[key][role][rank], relation, stats, identity)
    return {"mu": stats["mu"], "reported_marginal_se": stats["se"], "n": stats["n"]}


def _require_measured_match(measured, relation, stats, identity):
    if relation != ROOT:
        measured = measured["starter_suit_relation"][relation]
    if any(
        type(measured[column]) not in (int, float) or measured[column] != stats[column]
        for column in ("n", "mu", "se")
    ) or not is_safe_integer(measured["n"], 2):
        raise ValueError(f"v2 projection differs from measured source: {identity}")
