"""Corroborate a generated play table against a vendored Cribbage Pro sample.

Run on every scheduled/dispatch artifact generation (see the play-artifact
workflow), this offline check compares this project's independently simulated
pegging table against a small, attributed sample of Cribbage Pro's published
values -- their empirical human-play averages, a fully independent methodology
and the only comparable public source we have found. It records the
aggregate metrics in the artifact metadata, and with ``--fail-on-regression``
it fails the build when the role-relative deltas diverge grossly from the
reference, so a regressed table is never released. See ``cribbage_pro_reference``
for source attribution and the no-copyright note on the underlying averages.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from statistics import mean
from typing import Any, Mapping, Sequence

if __package__ in (None, ""):  # pragma: no cover
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# pylint: disable=wrong-import-position
from artifact_pipeline.cribbage_pro_reference import (  # noqa: E402
    CRIBBAGE_PRO_PEGGING_SAMPLE,
    RETRIEVED,
)
from artifact_pipeline.pegging import DEALER, PONE  # noqa: E402


def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
    left_mean = mean(left)
    right_mean = mean(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right)
    )
    denominator = math.sqrt(
        sum((value - left_mean) ** 2 for value in left)
        * sum((value - right_mean) ** 2 for value in right)
    )
    return numerator / denominator if denominator else 0.0


def _ranks(values: Sequence[float]) -> list[float]:
    ordered = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[index]]:
            end += 1
        average_rank = (index + end - 1) / 2.0
        for ordered_index in ordered[index:end]:
            ranks[ordered_index] = average_rank
        index = end
    return ranks


def _metrics(actual: Sequence[float], expected: Sequence[float]) -> dict[str, float]:
    differences = [
        actual_value - expected_value
        for actual_value, expected_value in zip(actual, expected)
    ]
    return {
        "bias": mean(differences),
        "mae": mean(abs(value) for value in differences),
        "rmse": math.sqrt(mean(value * value for value in differences)),
        "pearson": _pearson(actual, expected),
        "spearman": _pearson(_ranks(actual), _ranks(expected)),
    }


def compare_tables(
    generated: Mapping[str, Any],
    external: Mapping[str, tuple[float, ...]],
) -> dict[str, object]:
    """Compare four absolute-seat series and two role-relative delta series."""
    shared = sorted((set(generated) - {"__metadata__"}) & set(external))
    if not shared:
        raise ValueError("The tables have no shared hand keys")
    series: dict[str, tuple[list[float], list[float]]] = {
        "pone_player": ([], []),
        "pone_opponent": ([], []),
        "dealer_player": ([], []),
        "dealer_opponent": ([], []),
        "pone_delta": ([], []),
        "dealer_delta": ([], []),
    }
    for hand_key in shared:
        pone_player, pone_opponent, dealer_player, dealer_opponent = external[hand_key]
        generated_pone = generated[hand_key][PONE]
        generated_dealer = generated[hand_key][DEALER]
        values = {
            "pone_player": (
                generated_pone["players"][PONE]["mu"],
                pone_player,
            ),
            "pone_opponent": (
                generated_pone["players"][DEALER]["mu"],
                pone_opponent,
            ),
            "dealer_player": (
                generated_dealer["players"][DEALER]["mu"],
                dealer_player,
            ),
            "dealer_opponent": (
                generated_dealer["players"][PONE]["mu"],
                dealer_opponent,
            ),
            "pone_delta": (
                generated_pone["mu"],
                pone_player - pone_opponent,
            ),
            "dealer_delta": (
                generated_dealer["mu"],
                dealer_player - dealer_opponent,
            ),
        }
        for name, (actual, expected) in values.items():
            series[name][0].append(actual)
            series[name][1].append(expected)
    return {
        "shared_hands": len(shared),
        "metrics": {
            name: _metrics(actual, expected)
            for name, (actual, expected) in series.items()
        },
    }


# Gross-regression thresholds for the role-relative delta series (the values the
# UI shows). A production run sits well inside these (pearson ~0.93, |bias|
# ~0.18); the margin tolerates Cribbage Pro's different (human-play) methodology
# while still catching a sign flip or a scaling/offset bug.
GATED_SERIES = ("pone_delta", "dealer_delta")
MIN_PEARSON = 0.8
MAX_ABS_BIAS = 0.6


def regression_failures(report: Mapping[str, Any]) -> list[str]:
    """Return threshold violations for the gated delta series, empty if none."""
    metrics = report["metrics"]
    failures: list[str] = []
    for name in GATED_SERIES:
        series = metrics[name]
        if series["pearson"] < MIN_PEARSON:
            failures.append(f"{name}: pearson {series['pearson']:.3f} < {MIN_PEARSON}")
        if abs(series["bias"]) > MAX_ABS_BIAS:
            failures.append(
                f"{name}: |bias| {abs(series['bias']):.3f} > {MAX_ABS_BIAS}"
            )
    return failures


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("table")
    parser.add_argument("--write-metadata", action="store_true")
    parser.add_argument("--fail-on-regression", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    with open(args.table, encoding="utf-8") as table_file:
        generated = json.load(table_file)
    report = {
        **compare_tables(generated, CRIBBAGE_PRO_PEGGING_SAMPLE),
        "reference": "Cribbage Pro pegging quiz (vendored sample)",
        "reference_hands": len(CRIBBAGE_PRO_PEGGING_SAMPLE),
        "reference_retrieved": RETRIEVED,
    }
    if args.write_metadata:
        generated["__metadata__"]["external_regression"] = report
        with open(args.table, "w", encoding="utf-8") as table_file:
            json.dump(generated, table_file, indent=2, sort_keys=True)
            table_file.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.fail_on_regression:
        failures = regression_failures(report)
        if failures:
            print(
                "Pegging table diverges from the Cribbage Pro reference:",
                *failures,
                sep="\n  ",
                file=sys.stderr,
            )
            sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
