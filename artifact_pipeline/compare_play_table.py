"""Compare a generated play table with Cribbage Pro's published totals."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import re
from statistics import mean
from typing import Any, Mapping, Sequence
from urllib.request import urlopen

from artifact_pipeline.pegging import DEALER, PONE

DEFAULT_SOURCE_URL = "https://www.cribbagepro.net/pegging_quiz/pegging_data.js"
DOWNLOAD_TIMEOUT_SECONDS = 30
ROW_PATTERN = re.compile(r"(\[\s*['\"].*?\])\s*,?", re.DOTALL)


def normalize_external_hand(hand: str) -> str:
    """Convert comma-delimited external ranks to the artifact key format."""
    labels = [label.strip().replace("10", "T") for label in hand.split(",")]
    rank_order = {label: index for index, label in enumerate("A23456789TJQK")}
    return "_".join(sorted(labels, key=rank_order.__getitem__))


def parse_cribbage_pro_data(source: str) -> dict[str, tuple[float, ...]]:
    """Parse the JavaScript array without executing third-party code."""
    rows = {}
    for match in ROW_PATTERN.finditer(source):
        # Best-effort parse: skip rows that are malformed or non-numeric (the
        # third-party format could change) rather than failing the whole run.
        try:
            candidate = ast.literal_eval(match.group(1))
            if len(candidate) == 5:
                rows[normalize_external_hand(candidate[0])] = tuple(
                    float(value) for value in candidate[1:]
                )
        except (ValueError, SyntaxError, KeyError):
            continue
    if not rows:
        raise ValueError("No Cribbage Pro pegging rows were found")
    return rows


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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("table")
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument("--write-metadata", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    with open(args.table, encoding="utf-8") as table_file:
        generated = json.load(table_file)
    with urlopen(  # nosec B310
        args.source_url, timeout=DOWNLOAD_TIMEOUT_SECONDS
    ) as response:
        source = response.read()
    external = parse_cribbage_pro_data(source.decode("utf-8"))
    report = {
        **compare_tables(generated, external),
        "source_url": args.source_url,
        "source_sha256": hashlib.sha256(source).hexdigest(),
    }
    if args.write_metadata:
        generated["__metadata__"]["external_regression"] = report
        with open(args.table, "w", encoding="utf-8") as table_file:
            json.dump(generated, table_file, indent=2, sort_keys=True)
            table_file.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":  # pragma: no cover
    main()
