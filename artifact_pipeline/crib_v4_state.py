"""Exact joint moments and projections for opt-in crib estimator v4.

The full checkpoint owns these integer moments. Displayed means and standard
errors are derived views and must never be read back as sampling state.
"""

from fractions import Fraction
from math import sqrt

from artifact_pipeline.crib_decomposition import (
    RANK_CATEGORIES,
    ROOT,
    SUIT_CATEGORIES,
    bucket_populations,
)

SCALE = 310464
CENTER_DENOMINATOR = 1176
RELATION_ORDER = (
    "matching_discard_suit",
    "matching_rank_1_suit",
    "matching_rank_2_suit",
    "non_matching_discard_suit",
)
STREAM_ALLOCATION = {
    "distinct_rank": {"base": 1, "residual": 1, "suit": 1},
    "same_rank": {"base": 1, "suit": 1},
}


def active_streams(group):
    """Return the required stream order for a physical rank group."""
    return ("base", "residual", "suit") if group.suited else ("base", "suit")


def coordinate_labels(group, rank_names, stream):
    """Name every legal coordinate in the contract's deterministic order."""
    if stream not in active_streams(group):
        raise ValueError(f"Unavailable stream: {stream}")
    labels = []
    for cut, rank_name in enumerate(rank_names):
        if stream in ("base", "residual"):
            labels.extend(f"{rank_name}/{stream}/{kind}" for kind in RANK_CATEGORIES)
            continue
        variants = ("Unsuited", "Suited") if group.suited else ("Unsuited",)
        for variant in variants:
            populations = bucket_populations(group, variant)
            if (cut, ROOT) not in populations:
                continue
            labels.extend(
                f"{rank_name}/{variant}/{ROOT}/{kind}" for kind in SUIT_CATEGORIES
            )
            for relation_name in RELATION_ORDER:
                if (cut, relation_name) not in populations:
                    continue
                labels.extend(
                    f"{rank_name}/{variant}/{relation_name}/correction_{kind}"
                    for kind in RANK_CATEGORIES
                )
                labels.extend(
                    f"{rank_name}/{variant}/{relation_name}/{kind}"
                    for kind in SUIT_CATEGORIES
                )
    return labels


def observation_coordinates(observation, rank_names, stream):
    """Translate decomposition-core keys into fully qualified labels."""
    translated = {}
    for key, value in observation.items():
        if stream in ("base", "residual"):
            _prefix, cut, kind = key
            label = f"{rank_names[cut]}/{stream}/{kind}"
        elif key[0] == "C":
            _prefix, variant, cut, relation_name, kind = key
            label = f"{rank_names[cut]}/{variant}/{relation_name}/correction_{kind}"
        else:
            kind, variant, cut, relation_name = key
            label = f"{rank_names[cut]}/{variant}/{relation_name}/{kind}"
        translated[label] = value
    return translated


def integer_row(labels, coordinates):
    """Scale an exact complete observation without a floating conversion."""
    if set(coordinates) != set(labels):
        raise ValueError("Observation labels differ from the active stream contract")
    row = []
    for label in labels:
        scaled = SCALE * coordinates[label]
        if not isinstance(scaled, (int, Fraction)) or scaled.denominator != 1:
            raise ValueError(f"V4 observation is not an integer: {label}")
        row.append(int(scaled))
    return row


def empty_moments(labels):
    """Create one complete stream with zero unit-weight rows."""
    return {
        "count": 0,
        "next_index": 0,
        "scale": SCALE,
        "labels": list(labels),
        "sum_x": [0] * len(labels),
        "sum_xx_upper": {},
    }


def add_row(moments, row):
    """Commit one integer row and every within-stream nonzero product."""
    if len(row) != len(moments["labels"]) or not all(
        isinstance(value, int) for value in row
    ):
        raise ValueError("Invalid complete integer row")
    moments["count"] += 1
    moments["next_index"] += 1
    nonzero = [(index, value) for index, value in enumerate(row) if value]
    for index, value in nonzero:
        moments["sum_x"][index] += value
    upper = moments["sum_xx_upper"]
    for position, (left, left_value) in enumerate(nonzero):
        for right, right_value in nonzero[position:]:
            key = (left, right)
            updated = upper.get(key, 0) + left_value * right_value
            if updated:
                upper[key] = updated
            else:
                upper.pop(key, None)


def _integer_string(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Moment is not an integer")
    return str(value)


def _parse_integer_string(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Moment must be a decimal string")
    parsed = int(value)
    if str(parsed) != value:
        raise ValueError("Moment has a decimal encoding that is not canonical")
    return parsed


def encode_moments(moments):
    """Serialize signed big integers without JSON-number precision loss."""
    return {
        "count": moments["count"],
        "next_index": moments["next_index"],
        "scale": moments["scale"],
        "labels": moments["labels"],
        "sum_x": [_integer_string(value) for value in moments["sum_x"]],
        "sum_xx_upper": [
            [left, right, _integer_string(value)]
            for (left, right), value in sorted(moments["sum_xx_upper"].items())
        ],
    }


def _exact_psd(matrix):
    """Check for a nonnegative quadratic form by rational Schur complements."""
    remaining = [list(map(Fraction, row)) for row in matrix]
    while remaining:
        pivot = remaining[0][0]
        if pivot < 0:
            return False
        if pivot == 0:
            if any(remaining[0][index] for index in range(1, len(remaining))):
                return False
            remaining = [row[1:] for row in remaining[1:]]
            continue
        remaining = [
            [
                remaining[left][right]
                - remaining[left][0] * remaining[0][right] / pivot
                for right in range(1, len(remaining))
            ]
            for left in range(1, len(remaining))
        ]
    return True


def validate_moments(moments):
    """Reject impossible counts, exact-zero cases, and negative covariance."""
    count = moments["count"]
    totals = moments["sum_x"]
    upper = moments["sum_xx_upper"]
    if count == 0:
        if any(totals) or upper:
            raise ValueError("Zero-row moments contain observations")
        return
    if count == 1:
        for left, total in enumerate(totals):
            for right in range(left, len(totals)):
                if upper.get((left, right), 0) != total * totals[right]:
                    raise ValueError("One-row joint moments are inconsistent")
        return
    for index, total in enumerate(totals):
        if (upper.get((index, index), 0) - total) % 2:
            raise ValueError("Integer square moment has impossible parity")
    active = [
        index
        for index in range(len(totals))
        if count * upper.get((index, index), 0) != totals[index] ** 2
    ]
    active_set = set(active)
    for left, total in enumerate(totals):
        for right in range(left, len(totals)):
            covariance = count * upper.get((left, right), 0) - total * totals[right]
            if (left not in active_set or right not in active_set) and covariance:
                raise ValueError("Zero-variance coordinate has covariance")
    matrix = [
        [
            count * upper.get((min(left, right), max(left, right)), 0)
            - totals[left] * totals[right]
            for right in active
        ]
        for left in active
    ]
    if not _exact_psd(matrix):
        raise ValueError("Joint covariance has a negative quadratic form")


def decode_moments(payload, labels):
    """Validate a saved stream against its complete expected coordinate order."""
    if set(payload) != {
        "count",
        "next_index",
        "scale",
        "labels",
        "sum_x",
        "sum_xx_upper",
    }:
        raise ValueError("Incomplete stream payload")
    count = payload["count"]
    valid_count = isinstance(count, int) and not isinstance(count, bool) and count >= 0
    valid_contract = (
        isinstance(payload["next_index"], int)
        and not isinstance(payload["next_index"], bool)
        and payload["next_index"] == count
        and isinstance(payload["scale"], int)
        and not isinstance(payload["scale"], bool)
        and payload["scale"] == SCALE
        and payload["labels"] == list(labels)
    )
    if not valid_count or not valid_contract:
        raise ValueError("Stream count, index, scale, or labels are incompatible")
    if not isinstance(payload["sum_x"], list) or len(payload["sum_x"]) != len(labels):
        raise ValueError("Incomplete first moments")
    if not isinstance(payload["sum_xx_upper"], list):
        raise ValueError("Malformed cross moments")
    totals = [_parse_integer_string(value) for value in payload["sum_x"]]
    upper = {}
    last = (-1, -1)
    for entry in payload["sum_xx_upper"]:
        if not isinstance(entry, list) or len(entry) != 3:
            raise ValueError("Malformed upper-triangle entry")
        left, right, value = entry
        valid_types = (
            isinstance(left, int)
            and not isinstance(left, bool)
            and isinstance(right, int)
            and not isinstance(right, bool)
        )
        if (
            not valid_types
            or not 0 <= left <= right < len(labels)
            or (left, right) <= last
        ):
            raise ValueError("Unsorted or invalid upper-triangle index")
        parsed = _parse_integer_string(value)
        if parsed == 0:
            raise ValueError("Sparse upper triangle must omit zeros")
        upper[(left, right)] = parsed
        last = (left, right)
    moments = {
        "count": count,
        "next_index": count,
        "scale": SCALE,
        "labels": list(labels),
        "sum_x": totals,
        "sum_xx_upper": upper,
    }
    validate_moments(moments)
    return moments


def projected_statistics(streams, coefficients):
    """Project exact joint moments through rational coefficients."""
    if not streams:
        raise ValueError("Projection has no streams")
    counts = {moments["count"] for moments in streams.values()}
    if len(counts) != 1:
        raise ValueError("Projection streams have unequal counts")
    count = counts.pop()
    if count == 0:
        return None
    mean = Fraction(0)
    variance = Fraction(0)
    for name, weights in coefficients.items():
        moments = streams[name]
        labels = {label: index for index, label in enumerate(moments["labels"])}
        sparse = [
            (labels[label], Fraction(weight)) for label, weight in weights.items()
        ]
        total = sum(
            (weight * moments["sum_x"][index] for index, weight in sparse), Fraction(0)
        )
        mean += total / (SCALE * count)
        if count >= 2:
            cross = sum(
                (
                    left_weight
                    * right_weight
                    * moments["sum_xx_upper"].get(
                        (min(left, right), max(left, right)), 0
                    )
                    for left, left_weight in sparse
                    for right, right_weight in sparse
                ),
                Fraction(0),
            )
            numerator = count * cross - total * total
            if numerator < 0:
                raise ValueError("Projected covariance is negative")
            variance += numerator / (SCALE * SCALE * count * count * (count - 1))
    return {
        "n": count,
        "mu": float(mean),
        "se": sqrt(float(variance)) if count >= 2 else None,
    }
