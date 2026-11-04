"""Fixed-policy pre-cut twin diagnostics over validated v4 joint moments.

These normal bounds diagnose a fixed comparison, not policy-learning error or
calibrated finite-sample coverage. The 156-row family stays fixed for subsets.
"""

from fractions import Fraction
from statistics import NormalDist

from artifact_pipeline.crib_v4_state import projected_statistics

RANKS = tuple("A23456789TJQK")
FAMILY_SIZE = 156
POINTWISE_Z = NormalDist().inv_cdf(0.975)
SIMULTANEOUS_Z = NormalDist().inv_cdf(1 - 0.05 / (2 * FAMILY_SIZE))


def _coefficients(streams, rank_key):
    own = rank_key.split("_")
    residual = {
        label: Fraction(4 - own.count(label.split("/")[0]), 50)
        for label in streams["residual"]["labels"]
    }
    suit = {}
    for label in streams["suit"]["labels"]:
        rank, variant, relation, _kind = label.split("/")
        if relation == "root":
            suit[label] = (1 if variant == "Suited" else -1) * Fraction(
                4 - own.count(rank), 50
            )
    return residual, suit


def _bounds(gap, multiplier):
    if gap is None or gap["se"] is None:
        return None
    return {
        "lower": gap["mu"] - multiplier * gap["se"],
        "upper": gap["mu"] + multiplier * gap["se"],
    }


def precut_twin_report(state):
    """Read decoded, validated estimator_state, never displayed means.

    Base cancels algebraically between twins. Independent residual and suit
    streams add variances; every within-stream cross-cut product is retained.
    Same-rank groups have no suited twin and are omitted.
    """
    rows = []
    groups = state["estimator_state"]
    for rank_key in sorted(
        groups, key=lambda key: tuple(RANKS.index(r) for r in key.split("_"))
    ):
        first, second = rank_key.split("_")
        if first == second:
            continue
        for role in ("Dealer", "Pone"):
            streams = groups[rank_key][role]["streams"]
            residual, suit = _coefficients(streams, rank_key)
            components = {
                name: projected_statistics(streams, terms)
                for name, terms in (
                    ("gap", {"residual": residual, "suit": suit}),
                    ("residual", {"residual": residual}),
                    (
                        "flush",
                        {
                            "suit": {
                                k: v for k, v in suit.items() if k.endswith("/flushes")
                            }
                        },
                    ),
                    (
                        "nobs",
                        {
                            "suit": {
                                k: v for k, v in suit.items() if k.endswith("/nobs")
                            }
                        },
                    ),
                )
            }
            simultaneous = _bounds(components["gap"], SIMULTANEOUS_Z)
            status = "unresolved"
            if simultaneous is not None:
                if simultaneous["upper"] < 0:
                    status = "resolved-negative"
                elif simultaneous["lower"] > 0:
                    status = "resolved-positive"
            rows.append(
                {
                    "rank_group": rank_key,
                    "role": role,
                    "has_jack": "J" in (first, second),
                    **components,
                    "pointwise": _bounds(components["gap"], POINTWISE_Z),
                    "simultaneous": simultaneous,
                    "status": status,
                }
            )
    return {
        "contract": "precut-twin-normal-diagnostic-v1",
        "family_size": FAMILY_SIZE,
        "confidence": 0.95,
        "pointwise_z": POINTWISE_Z,
        "simultaneous_z": SIMULTANEOUS_Z,
        "rows": rows,
    }


def enforce_precut_report(report):
    """Reject only resolved-negative rows, without tolerance or resampling."""
    failures = [
        f"{row['rank_group']}/{row['role']}"
        for row in report["rows"]
        if row["status"] == "resolved-negative"
    ]
    if failures:
        raise ValueError("Resolved-negative pre-cut twins: " + ", ".join(failures))
