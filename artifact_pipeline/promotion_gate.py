"""Measure trained pegging policies against the legacy heuristic on shared deals."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import random
from typing import Any

from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    LegacyHeuristicPolicy,
    PeggingPolicy,
    RunningStatistics,
    _stable_seed,
    simulate_pegging,
)

DEFAULT_GATE_DEALS = 200_000
MINIMUM_GATE_DEALS = 1_000
Z_THRESHOLD = 3.0
# Uniformly random four-card hands for each seat, not the discard policy's
# keeps: the approved #187 design measures play strength on every hand rather
# than on the hands one discard policy keeps.
GATE_POPULATION = "uniform-random-four-card-hands-rank-only-v1"
BOTH_SEATS = "both_seats"
GateDeal = tuple[tuple[int, ...], tuple[int, ...], int]


def gate_deals(count: int, seed: int) -> Iterator[GateDeal]:
    """Yield Pone ranks, Dealer ranks and a play seed for each gate deal.

    Both streams carry a "promotion-gate" label, so they cannot coincide with
    the training or measurement streams derived from the same seed.
    """
    deal_rng = random.Random(_stable_seed(seed, "promotion-gate", "deals"))
    for index in range(count):
        cards = deal_rng.sample(range(52), 8)
        yield (
            tuple(card // 4 for card in cards[:4]),
            tuple(card // 4 for card in cards[4:]),
            _stable_seed(seed, "promotion-gate", "play", index),
        )


def evaluate_promotion(
    trained: Mapping[str, PeggingPolicy], deals: int, seed: int
) -> dict[str, Any]:
    """Return each seat's and the both-seat advantage of trained over heuristic.

    Every deal is played three times with one play seed: heuristic against
    heuristic, trained Pone against the heuristic Dealer, and the heuristic
    Pone against the trained Dealer. A seat's advantage is its trained delta
    minus the reference game's delta for the same seat. The both-seat value is
    the two seats' average within each deal, so its standard error keeps the
    covariance that the shared deal induces.
    """
    if deals < MINIMUM_GATE_DEALS:
        raise ValueError(
            f"The promotion gate needs at least {MINIMUM_GATE_DEALS:,} deals"
        )
    heuristic = LegacyHeuristicPolicy()
    games: dict[str, Mapping[str, PeggingPolicy]] = {
        "reference": {PONE: heuristic, DEALER: heuristic},
        PONE: {PONE: trained[PONE], DEALER: heuristic},
        DEALER: {PONE: heuristic, DEALER: trained[DEALER]},
    }
    estimates = {label: RunningStatistics() for label in (PONE, DEALER, BOTH_SEATS)}
    for pone_hand, dealer_hand, play_seed in gate_deals(deals, seed):
        results = {
            game: simulate_pegging(
                pone_hand, dealer_hand, policies, random.Random(play_seed)
            )
            for game, policies in games.items()
        }
        gains = [
            results[seat].delta(seat) - results["reference"].delta(seat)
            for seat in (PONE, DEALER)
        ]
        estimates[PONE].add(gains[0])
        estimates[DEALER].add(gains[1])
        estimates[BOTH_SEATS].add((gains[0] + gains[1]) / 2)
    both = estimates[BOTH_SEATS]
    return {
        "population": GATE_POPULATION,
        "deals": deals,
        "seed": seed,
        "z_threshold": Z_THRESHOLD,
        **{label: value.to_dict() for label, value in estimates.items()},
        "passed": both.mean > 0 and both.mean >= Z_THRESHOLD * both.standard_error,
    }


def describe_promotion(report: Mapping[str, Any]) -> str:
    """Summarize a gate report as one log line."""
    seats = ", ".join(
        f"{label} {report[label]['mu']:+.4f} (se {report[label]['se']:.4f})"
        for label in (PONE, DEALER, BOTH_SEATS)
    )
    return (
        f"[promotion-gate] {report['mode']}: trained minus heuristic points per "
        f"hand over {report['deals']} deals: {seats}; passed: {report['passed']}"
    )
