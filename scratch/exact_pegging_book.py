"""Exact rank-only opening books against frozen deterministic continuations.

This research module has no production reader and changes no release artifacts.
The physical opponent population removes the acting player's four known cards.
"""

from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
import importlib
from itertools import combinations_with_replacement
import json
import math
import multiprocessing
from pathlib import Path
import random
import sys
import time
from typing import Any

from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    LegacyHeuristicPolicy,
    PeggingState,
    TabularPeggingPolicy,
    canonical_hand_key,
    get_canonical_hands,
    policy_fingerprint,
    simulate_from_state,
)
from artifact_pipeline.promotion_gate import DEFAULT_GATE_DEALS, evaluate_promotion

book = importlib.import_module("scratch.pegging_opening_book")
checks = importlib.import_module("scratch.pegging_book_checks")
HANDS = get_canonical_hands()
EPSILON = Fraction(1, 1_000_000)
OPPONENT_WEIGHT = math.comb(48, 4)
OWN_WEIGHT = math.comb(52, 4)
POPULATION_WEIGHT = OWN_WEIGHT * OPPONENT_WEIGHT


def physical_weight(hand, capacities=None) -> int:
    """Count unordered physical draws represented by a rank multiset."""
    counts = Counter(hand)
    available = capacities if capacities is not None else (4,) * 13
    return math.prod(
        math.comb(available[rank], count) for rank, count in counts.items()
    )


def opponent_hands(own, ranks: int = 13):
    """Enumerate every feasible opponent multiset and its physical multiplicity."""
    capacities = tuple(4 - own.count(rank) for rank in range(ranks))
    hands = HANDS if ranks == 13 else combinations_with_replacement(range(ranks), 4)
    for opponent in hands:
        weight = physical_weight(opponent, capacities)
        if weight:
            yield opponent, weight


def choose_override(candidates, baseline: int, weight: int, epsilon=EPSILON):
    """Compare integer gain sums, preferring the lower rank only on exact ties."""
    if not weight:
        return None
    best = max(candidates, key=lambda value: (value["gain_sum"], -value["rank"]))
    if (
        best["rank"] != baseline
        and best["gain_sum"] * epsilon.denominator > weight * epsilon.numerator
    ):
        return best["rank"]
    return None


def integer_delta(result, role: str) -> int:
    """Refuse non-integer scoring rather than silently truncating exact sums."""
    delta = result.delta(role)
    value = int(delta)
    if value != delta:
        raise ValueError("Exact pegging requires integer point differences")
    return value


def candidates_from_totals(totals, baseline: int):
    """Retain integer absolute sums and paired differences from the baseline."""
    return [
        {"rank": rank, "delta_sum": value, "gain_sum": value - totals[baseline]}
        for rank, value in sorted(totals.items())
    ]


def exact_pone_hand(job) -> dict[str, Any]:
    """Enumerate every opponent and force every distinct opening lead."""
    own, ranks = job
    heuristic = LegacyHeuristicPolicy()
    baseline = heuristic.select_rank(book.opening_view(own), random.Random(0))
    policies = {PONE: heuristic, DEALER: heuristic}
    totals = {rank: 0 for rank in sorted(set(own))}
    rng = random.Random(0)
    weight_sum = multiset_count = 0
    for opponent, weight in opponent_hands(own, ranks):
        state = PeggingState({PONE: list(own), DEALER: list(opponent)})
        weight_sum += weight
        multiset_count += 1
        for rank in totals:
            totals[rank] += weight * integer_delta(
                simulate_from_state(state, policies, rng, forced_rank=rank), PONE
            )
    if weight_sum != math.comb(4 * ranks - 4, 4):
        raise ValueError("Opponent population weight does not match the physical deck")
    if rng.getstate() != random.Random(0).getstate():
        raise ValueError("Exact enumeration requires deterministic continuations")
    candidates = candidates_from_totals(totals, baseline)
    return {
        "hand": list(own),
        "key": canonical_hand_key(own),
        "weight": weight_sum,
        "own_weight": physical_weight(own),
        "opponent_multisets": multiset_count,
        "simulations": multiset_count * len(totals),
        "heuristic_lead": baseline,
        "override": choose_override(candidates, baseline, weight_sum),
        "override_epsilon_zero": choose_override(
            candidates, baseline, weight_sum, Fraction(0)
        ),
        "candidates": candidates,
    }


def enumerate_jobs(jobs, stage: str, workers: int, worker=exact_pone_hand):
    """Retain canonical result order independent of spawned worker scheduling."""
    if workers < 1:
        raise ValueError("Need positive workers and a supported enumeration stage")
    if workers == 1:
        return list(map(worker, jobs))
    rows = []
    started = time.monotonic()
    with multiprocessing.get_context("spawn").Pool(workers) as pool:
        for row in pool.imap(worker, jobs):
            rows.append(row)
            if len(rows) % 100 == 0:
                print(
                    f"[exact-{stage}] {len(rows)}/{len(jobs)} keys, "
                    f"{time.monotonic() - started:.1f}s",
                    file=sys.stderr,
                    flush=True,
                )
    return rows


def build_pone(rows) -> TabularPeggingPolicy:
    """Use the existing table/fallback boundary for exact opening decisions."""
    return book.build_policy(rows)


def gain_sum(row, rank: int) -> int:
    """Read a rank's exact conditional paired gain numerator."""
    return next(
        value["gain_sum"] for value in row["candidates"] if value["rank"] == rank
    )


def fraction_record(value: Fraction) -> dict[str, int | float]:
    """Publish exact rational authority with a convenience decimal for reports."""
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "mu": float(value),
    }


def population_gain(rows, choices) -> dict[str, int | float]:
    """Average over uniform physical own hands and conditional opponent draws."""
    numerator = sum(
        row["own_weight"] * gain_sum(row, choices[row["key"]]) for row in rows
    )
    return fraction_record(Fraction(numerator, POPULATION_WEIGHT))


def summarize_pone(rows, sampled):
    """Compare complete exact decisions and the exact quality of sampled choices."""
    old = {row["key"]: row for row in sampled["hands"]}
    old_choices = {
        key: row["override"] if row["override"] is not None else row["heuristic_lead"]
        for key, row in old.items()
    }
    new_choices = {
        row["key"]: (
            row["override"] if row["override"] is not None else row["heuristic_lead"]
        )
        for row in rows
    }
    selected = [row for row in rows if old[row["key"]]["override"] is not None]
    differences = []
    for row in selected:
        choice = old_choices[row["key"]]
        training = next(
            v["mu"] for v in old[row["key"]]["candidates"] if v["lead"] == choice
        )
        exact_gain = gain_sum(row, choice) / row["weight"]
        differences.append(
            {
                "key": row["key"],
                "sampled_lead": choice,
                "sampled_gain": training,
                "exact_gain": exact_gain,
                "exact_minus_sampled": exact_gain - training,
            }
        )
    discrepancies = []
    for row in rows:
        for candidate in row["candidates"]:
            training = next(
                v["mu"]
                for v in old[row["key"]]["candidates"]
                if v["lead"] == candidate["rank"]
            )
            exact_gain = candidate["gain_sum"] / row["weight"]
            discrepancies.append(
                {
                    "key": row["key"],
                    "lead": candidate["rank"],
                    "sampled_gain": training,
                    "exact_gain": exact_gain,
                    "exact_minus_sampled": exact_gain - training,
                }
            )
    regret = sorted(
        [
            {
                "key": row["key"],
                "sampled_lead": old_choices[row["key"]],
                "exact_lead": new_choices[row["key"]],
                "regret": (
                    gain_sum(row, new_choices[row["key"]])
                    - gain_sum(row, old_choices[row["key"]])
                )
                / row["weight"],
            }
            for row in rows
        ],
        key=lambda v: (-v["regret"], v["key"]),
    )
    return {
        "keys": len(rows),
        "overrides": sum(row["override"] is not None for row in rows),
        "epsilon_zero_overrides": sum(
            row["override_epsilon_zero"] is not None for row in rows
        ),
        "epsilon_zero_different_keys": sum(
            row["override"] != row["override_epsilon_zero"] for row in rows
        ),
        "changed_decisions": sum(
            new_choices[key] != choice for key, choice in old_choices.items()
        ),
        "new_overrides": sum(
            old[row["key"]]["override"] is None and row["override"] is not None
            for row in rows
        ),
        "removed_overrides": sum(
            old[row["key"]]["override"] is not None and row["override"] is None
            for row in rows
        ),
        "changed_override_leads": sum(
            old[row["key"]]["override"] is not None
            and row["override"] is not None
            and old[row["key"]]["override"] != row["override"]
            for row in rows
        ),
        "sampled_overrides_exact_positive": sum(
            gain_sum(row, old_choices[row["key"]]) > 0 for row in selected
        ),
        "sampled_override_exact_mean": sum(value["exact_gain"] for value in differences)
        / len(differences),
        "sampled_override_shrinkage_mean": sum(
            value["exact_minus_sampled"] for value in differences
        )
        / len(differences),
        "sampled_override_shrinkage_quantiles": checks.quantiles(
            [v["exact_minus_sampled"] for v in differences]
        ),
        "sampled_population_gain": population_gain(rows, old_choices),
        "exact_population_gain": population_gain(rows, new_choices),
        "largest_decision_regrets": regret[:10],
        "largest_sample_errors": sorted(
            discrepancies, key=lambda v: -abs(v["exact_minus_sampled"])
        )[:10],
    }


def write_report(path: Path, report, rows=None):
    """Keep full integer evidence compact without changing any published format."""
    content = dict(report)
    if rows is not None:
        content["hands"] = rows
    path.write_text(
        json.dumps(content, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def run_pone(args):
    """Enumerate stage 1 first, then compare both frozen books on the default gate."""
    sampled = checks.read_book(args.sampled)
    started = time.monotonic()
    rows = enumerate_jobs([(hand, 13) for hand in HANDS], "pone", args.workers)
    training_seconds = time.monotonic() - started
    policy = build_pone(rows)
    report = {
        "experiment": "issue-187-exact-pone-v1",
        "epsilon": fraction_record(EPSILON),
        "continuations": "legacy-heuristic-both-seats",
        "workers": args.workers,
        "physical_opponent_weight_per_key": OPPONENT_WEIGHT,
        "physical_own_population_weight": OWN_WEIGHT,
        "population_weight": POPULATION_WEIGHT,
        "weight_min": min(row["weight"] for row in rows),
        "weight_max": max(row["weight"] for row in rows),
        "simulations": sum(row["simulations"] for row in rows),
        "summary": summarize_pone(rows, sampled),
        "training_seconds": training_seconds,
        "evidence_sha256": book.evidence_digest(rows),
        "policy_fingerprint": policy_fingerprint(policy),
        "sampled_policy_fingerprint": sampled["policy_fingerprint"],
    }
    write_report(args.output, report, rows)
    for label, candidate in [
        ("exact_gate", policy),
        ("sampled_gate", book.build_policy(sampled["hands"])),
    ]:
        print(f"[exact-pone] starting {label}", file=sys.stderr, flush=True)
        report[label] = evaluate_promotion(
            {PONE: candidate, DEALER: LegacyHeuristicPolicy()},
            args.gate_deals,
            args.seed,
        )
    report["elapsed_seconds"] = time.monotonic() - started
    write_report(args.output, report, rows)
    print(json.dumps(report, indent=2))


def main():
    """Run reproducible exact research, outside generation and publication."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("pone",))
    parser.add_argument(
        "--sampled",
        type=Path,
        default=Path(__file__).with_name("issue187_pone_opening_book.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--gate-deals", type=int, default=DEFAULT_GATE_DEALS)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.workers < 1 or args.gate_deals < 1000:
        parser.error("Need positive workers and at least 1000 gate deals")
    run_pone(args)


if __name__ == "__main__":
    main()
