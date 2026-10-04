"""Paired rank-only calibration against the legacy heuristic before measurement."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
import random
from typing import Any

from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    ROLES,
    LegacyHeuristicPolicy,
    PeggingPolicy,
    RunningStatistics,
    _stable_seed,
    policy_fingerprint,
    simulate_pegging,
)
from artifact_pipeline.process_pool import ordered_process_map

DEFAULT_GATE_DEALS = 200_000
GATE_BATCH_SIZE = 256
GateDeal = tuple[tuple[int, ...], tuple[int, ...], int]


def _gate_batches(count: int, seed: int) -> Iterator[list[GateDeal]]:
    rng = random.Random(seed)
    for start in range(0, count, GATE_BATCH_SIZE):
        batch = []
        for index in range(start, min(start + GATE_BATCH_SIZE, count)):
            cards = rng.sample(range(52), 8)
            batch.append(
                (
                    tuple(card // 4 for card in cards[:4]),
                    tuple(card // 4 for card in cards[4:]),
                    _stable_seed(seed, "promotion-gate", index),
                )
            )
        yield batch


def _gate_batch(
    policies: Mapping[str, PeggingPolicy], deals: Sequence[GateDeal]
) -> list[tuple[float, float]]:
    legacy = {role: LegacyHeuristicPolicy() for role in ROLES}
    observations = []
    for pone, dealer, seed in deals:
        reference = simulate_pegging(pone, dealer, legacy, random.Random(seed)).delta(
            PONE
        )
        pone_delta = simulate_pegging(
            pone,
            dealer,
            {PONE: policies[PONE], DEALER: legacy[DEALER]},
            random.Random(seed),
        ).delta(PONE)
        dealer_delta = simulate_pegging(
            pone,
            dealer,
            {PONE: legacy[PONE], DEALER: policies[DEALER]},
            random.Random(seed),
        ).delta(DEALER)
        observations.append((pone_delta - reference, dealer_delta + reference))
    return observations


def evaluate_promotion(
    policies: Mapping[str, PeggingPolicy], deals: int, seed: int, workers: int = 1
) -> dict[str, Any]:
    """Replay ordered paired observations; average seats before estimating SE."""
    if deals < 2 or workers < 1:
        raise ValueError("Promotion requires at least two deals and positive workers")
    batches = _gate_batches(deals, seed)
    results = (
        (_gate_batch(policies, batch) for batch in batches)
        if workers == 1
        else ordered_process_map(_gate_batch, policies, batches, workers)
    )
    estimates = {label: RunningStatistics() for label in (*ROLES, "both_seats")}
    for observations in results:
        for pone_gain, dealer_gain in observations:
            estimates[PONE].add(pone_gain)
            estimates[DEALER].add(dealer_gain)
            estimates["both_seats"].add((pone_gain + dealer_gain) / 2)
    average = estimates["both_seats"]
    return {
        "seed": seed,
        "population": "uniform-physical-eight-card-keeps-rank-only-v1",
        "z_threshold": 3.0,
        **{label: value.to_dict() for label, value in estimates.items()},
        "passed": average.mean > 0 and average.mean >= 3 * average.standard_error,
    }


def promotion_gate(
    policies: Mapping[str, PeggingPolicy],
    mode: str,
    deals: int,
    seed: int,
    workers: int,
) -> tuple[Mapping[str, PeggingPolicy], dict[str, Any]]:
    """Report by default; enforce selects the reference for both measured seats."""
    if mode not in ("off", "report", "enforce"):
        raise ValueError("Unknown promotion gate mode")
    report = {} if mode == "off" else evaluate_promotion(policies, deals, seed, workers)
    fallback = mode == "enforce" and not report["passed"]
    measured = (
        {role: LegacyHeuristicPolicy() for role in ROLES} if fallback else policies
    )
    return measured, {
        "mode": mode,
        **report,
        "measured_policy": "legacy-heuristic" if fallback else "trained",
        "trained_policy_fingerprint": ":".join(
            policy_fingerprint(policies[r]) for r in ROLES
        ),
        "measured_policy_fingerprint": ":".join(
            policy_fingerprint(measured[r]) for r in ROLES
        ),
    }
