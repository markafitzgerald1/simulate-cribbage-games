"""Analyze conditional opponent hand points for issue 75."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import gzip
import hashlib
import itertools
import json
import math
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

if __package__ in (None, ""):  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# pylint: disable=wrong-import-position
from artifact_pipeline.adapter import Card, Index, score_hand_and_starter_breakdown
from artifact_pipeline.analytical_solver import (
    DEFAULT_FULL_HAND_POLICY_MAX_ITERATIONS,
    DEFAULT_IBR_MAX_ITERATIONS,
    _iter_containment_subset_weights,
    _iter_rank_count_subsets,
    get_hand_combinations_with_weights,
    score_combination_suit_free,
)
from artifact_pipeline.generate_play_table import (
    DEALER,
    PONE,
    ROLES,
    DiscardPolicy,
    selected_discards_to_policy,
    solve_initial_discard_policy,
)

PHYSICAL_DECK = tuple((rank, suit) for rank in range(13) for suit in range(4))
DEFAULT_SEED = 42
DEFAULT_PHYSICAL_SAMPLES = 10_000
PHYSICAL_SIX_CARD_DEALS = math.comb(52, 6)
CONDITIONED_OPPONENT_DEALS = math.comb(46, 6)
STARTERS_PER_DEAL = 40
FLOAT32_BYTES = 4
INT16_BYTES = 2


@dataclass
class PolicySubsetAggregate:
    """Policy scoring totals for opponent deals containing a fixed subset."""

    weight: int = 0
    role_base_totals: dict[str, float] = field(
        default_factory=lambda: {PONE: 0.0, DEALER: 0.0}
    )
    role_starter_scores: dict[str, list[float]] = field(
        default_factory=lambda: {PONE: [0.0] * 13, DEALER: [0.0] * 13}
    )


@dataclass
class SampleMoments:
    """Streaming physical-card sample moments."""

    n: int = 0
    mean: float = 0.0
    moment_2: float = 0.0

    def add(self, value: float) -> None:
        """Add one sampled score."""
        self.n += 1
        delta = value - self.mean
        self.mean += delta / self.n
        self.moment_2 += delta * (value - self.mean)

    @property
    def standard_deviation(self) -> float:
        """Return the sample standard deviation."""
        if self.n < 2:
            return 0.0
        return math.sqrt(self.moment_2 / (self.n - 1))

    @property
    def standard_error(self) -> float:
        """Return the standard error of the sampled mean."""
        if not self.n:
            return math.inf
        return self.standard_deviation / math.sqrt(self.n)


REPRESENTATIVE_PHYSICAL_DEALS: tuple[tuple[str, tuple[tuple[int, int], ...]], ...] = (
    ("six_one_suit", tuple((rank, 0) for rank in range(6))),
    (
        "four_two_suits",
        ((0, 0), (1, 0), (2, 0), (3, 0), (4, 1), (5, 1)),
    ),
    (
        "three_three_suits",
        ((3, 0), (4, 0), (5, 0), (6, 1), (7, 1), (8, 1)),
    ),
    (
        "two_two_two_suits",
        ((7, 0), (8, 0), (9, 1), (10, 1), (11, 2), (12, 2)),
    ),
    (
        "paired_ranks_mixed_suits",
        ((0, 0), (0, 1), (4, 0), (4, 2), (10, 3), (12, 1)),
    ),
    (
        "triple_rank_mixed_suits",
        ((5, 0), (5, 1), (5, 2), (8, 0), (10, 1), (12, 3)),
    ),
)


def positive_int(value: str) -> int:
    """Parse a strictly positive integer."""
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def nonnegative_int(value: str) -> int:
    """Parse a nonnegative integer."""
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def canonical_suit_key(cards: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    """Return the lexicographically smallest global-suit permutation."""
    sorted_cards = tuple(sorted(cards))
    if len(set(sorted_cards)) != len(sorted_cards):
        raise ValueError("physical cards must be unique")
    if any(
        rank not in range(13) or suit not in range(4) for rank, suit in sorted_cards
    ):
        raise ValueError("physical cards must use ranks 0..12 and suits 0..3")
    return min(
        tuple(sorted((rank, permutation[suit]) for rank, suit in sorted_cards))
        for permutation in itertools.permutations(range(4))
    )


def suit_normalized_six_card_state_count() -> int:
    """Count physical six-card deals modulo global suit renaming."""
    identity_fixed = math.comb(52, 6)
    transposition_fixed = sum(
        math.comb(13, paired) * math.comb(26, 6 - 2 * paired) for paired in range(4)
    )
    double_transposition_fixed = math.comb(26, 3)
    three_cycle_fixed = sum(
        math.comb(13, triples) * math.comb(13, 6 - 3 * triples) for triples in range(3)
    )
    four_cycle_fixed = 0
    fixed_sum = (
        identity_fixed
        + 6 * transposition_fixed
        + 3 * double_transposition_fixed
        + 8 * three_cycle_fixed
        + 6 * four_cycle_fixed
    )
    return fixed_sum // math.factorial(4)


def _rank_counts(hand: Sequence[int]) -> tuple[tuple[int, int], ...]:
    return tuple((rank, hand.count(rank)) for rank in sorted(set(hand)))


def _kept_scores(
    policy: DiscardPolicy, role: str, hand: Sequence[int]
) -> tuple[float, ...]:
    kept = policy.kept_ranks(role, hand)
    return tuple(score_combination_suit_free(kept, rank) for rank in range(13))


def build_policy_subset_aggregates(
    policy: DiscardPolicy,
    hands: Sequence[tuple[tuple[int, ...], int]],
) -> dict[tuple[tuple[int, int], ...], PolicySubsetAggregate]:
    """Aggregate exact rank-policy scores for fast six-card conditioning."""
    aggregates: dict[tuple[tuple[int, int], ...], PolicySubsetAggregate] = {}
    for hand, _physical_weight in hands:
        rank_counts = _rank_counts(hand)
        role_scores = {role: _kept_scores(policy, role, hand) for role in ROLES}
        role_base_totals = {
            role: 4.0 * sum(scores) - sum(scores[rank] for rank in hand)
            for role, scores in role_scores.items()
        }
        for subset_key, completion_weight in _iter_containment_subset_weights(
            rank_counts
        ):
            aggregate = aggregates.setdefault(subset_key, PolicySubsetAggregate())
            aggregate.weight += completion_weight
            for role in ROLES:
                aggregate.role_base_totals[role] += (
                    completion_weight * role_base_totals[role]
                )
                for rank, score in enumerate(role_scores[role]):
                    aggregate.role_starter_scores[role][rank] += (
                        completion_weight * score
                    )
    return aggregates


def conditioned_suitless_expected_values(
    known_hand: Sequence[int],
    aggregates: Mapping[tuple[tuple[int, int], ...], PolicySubsetAggregate],
) -> dict[str, float]:
    """Return exact suitless opponent hand EVs after removing a known six."""
    known_counts = _rank_counts(known_hand)
    conditioned_weight = 0
    role_totals = {PONE: 0.0, DEALER: 0.0}
    for subset_key, subset_size, multiplicity in _iter_rank_count_subsets(known_counts):
        aggregate = aggregates[subset_key]
        coefficient = -multiplicity if subset_size % 2 else multiplicity
        conditioned_weight += coefficient * aggregate.weight
        for role in ROLES:
            removed_starter_total = sum(
                count * aggregate.role_starter_scores[role][rank]
                for rank, count in known_counts
            )
            role_totals[role] += coefficient * (
                aggregate.role_base_totals[role] - removed_starter_total
            )
    if conditioned_weight != CONDITIONED_OPPONENT_DEALS:
        raise ValueError(
            "conditioned opponent deal count was "
            f"{conditioned_weight}, expected {CONDITIONED_OPPONENT_DEALS}"
        )
    denominator = conditioned_weight * STARTERS_PER_DEAL
    return {role: role_totals[role] / denominator for role in ROLES}


def exact_suitless_table(
    policy: DiscardPolicy, hand_limit: int | None = None
) -> dict[str, dict[str, float]]:
    """Generate exact rank-only values for every requested known six-card hand."""
    hands = get_hand_combinations_with_weights()
    aggregates = build_policy_subset_aggregates(policy, hands)
    selected_hands = hands[:hand_limit] if hand_limit is not None else hands
    return {
        rank_hand_key(hand): conditioned_suitless_expected_values(hand, aggregates)
        for hand, _weight in selected_hands
    }


def rank_hand_key(hand: Sequence[int]) -> str:
    """Format a sorted rank hand as a stable artifact-sizing key."""
    return "_".join(Index.indices[rank] for rank in hand)


def _physical_sample_seed(seed: int, deal_name: str, role: str) -> int:
    payload = f"{seed}|{deal_name}|{role}".encode("ascii")
    return int.from_bytes(hashlib.sha256(payload).digest()[:16], "big")


def _sample_rank_policy_keep(
    policy: DiscardPolicy,
    role: str,
    dealt_cards: Sequence[tuple[int, int]],
    rng: random.Random,
) -> tuple[tuple[int, int], ...]:
    """Apply a rank policy with unbiased suit selection for rank-equivalent cards."""
    kept_ranks = policy.kept_ranks(role, sorted(card[0] for card in dealt_cards))
    needed = {rank: kept_ranks.count(rank) for rank in set(kept_ranks)}
    kept = []
    for rank, count in needed.items():
        candidates = [card for card in dealt_cards if card[0] == rank]
        kept.extend(rng.sample(candidates, count))
    return tuple(sorted(kept))


def sample_suit_aware_hand_points(
    known_deal: Sequence[tuple[int, int]],
    opponent_role: str,
    policy: DiscardPolicy,
    samples: int,
    seed: int,
) -> SampleMoments:
    """Sample physical opponent hand points under the rank-driven policy."""
    known = set(known_deal)
    if len(known) != 6:
        raise ValueError("known deal must contain six unique physical cards")
    remaining = [card for card in PHYSICAL_DECK if card not in known]
    rng = random.Random(seed)
    moments = SampleMoments()
    for _sample_index in range(samples):
        opponent_dealt = rng.sample(remaining, 6)
        kept = _sample_rank_policy_keep(policy, opponent_role, opponent_dealt, rng)
        starter_pool = [card for card in remaining if card not in opponent_dealt]
        starter = rng.choice(starter_pool)
        score = score_hand_and_starter_breakdown(
            [Card(rank, suit) for rank, suit in kept],
            Card(*starter),
        )["total"]
        moments.add(float(score))
    return moments


def _role_summary(
    table: Mapping[str, Mapping[str, float]], role: str
) -> dict[str, float]:
    values = [entry[role] for entry in table.values()]
    return {
        "minimum": min(values),
        "maximum": max(values),
        "mean": statistics.fmean(values),
        "population_standard_deviation": statistics.pstdev(values),
    }


def _rank_table_sizes(table: Mapping[str, Mapping[str, float]]) -> dict[str, int]:
    minified = json.dumps(table, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return {
        "minified_json_bytes": len(minified),
        "gzip_bytes": len(gzip.compress(minified, 9)),
        "packed_float32_value_bytes": len(table) * len(ROLES) * FLOAT32_BYTES,
    }


def _normalized_size_projections(
    rank_table: Mapping[str, Mapping[str, float]],
    normalized_count: int,
    physical_pilot: Sequence[Mapping[str, Any]] = (),
) -> dict[str, int | str]:
    rank_sizes = _rank_table_sizes(rank_table)
    rank_count = len(rank_table)
    if physical_pilot:
        physical_entries = {
            entry["canonical_key"]: {
                role: role_entry["mu"] for role, role_entry in entry["roles"].items()
            }
            for entry in physical_pilot
        }
        physical_json = json.dumps(
            physical_entries, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        average_json_entry = len(physical_json) / len(physical_entries)
        projection_basis = "representative physical pilot keys and values"
    else:
        average_json_entry = rank_sizes["minified_json_bytes"] / rank_count
        projection_basis = "rank-table fallback because no physical pilot was run"
    compression_ratio = rank_sizes["gzip_bytes"] / rank_sizes["minified_json_bytes"]
    projected_json_bytes = round(average_json_entry * normalized_count)
    return {
        "json_projection_basis": projection_basis,
        "projected_minified_json_bytes": projected_json_bytes,
        "projected_gzip_bytes": round(projected_json_bytes * compression_ratio),
        "packed_float32_value_bytes": normalized_count * len(ROLES) * FLOAT32_BYTES,
        "quantized_int16_residual_bytes": normalized_count * len(ROLES) * INT16_BYTES,
        "rank_float32_plus_quantized_residual_bytes": (
            rank_count * len(ROLES) * FLOAT32_BYTES
            + normalized_count * len(ROLES) * INT16_BYTES
        ),
    }


def _runtime_projections(
    pilot: Sequence[Mapping[str, Any]], elapsed_seconds: float
) -> dict[str, Any]:
    """Project normalized-table sampling runtime from the physical pilot."""
    role_entries = [
        role_entry
        for deal_entry in pilot
        for role_entry in deal_entry["roles"].values()
    ]
    if not role_entries or elapsed_seconds <= 0.0:
        return {"observed_samples_per_second": None, "precision_targets": {}}
    observed_samples = sum(entry["n"] for entry in role_entries)
    samples_per_second = observed_samples / elapsed_seconds
    maximum_standard_deviation = max(
        entry["standard_deviation"] for entry in role_entries
    )
    normalized_count = suit_normalized_six_card_state_count()
    targets = {}
    for target_standard_error in (0.04, 0.02, 0.01):
        samples_per_entry = math.ceil(
            (maximum_standard_deviation / target_standard_error) ** 2
        )
        total_samples = samples_per_entry * normalized_count * len(ROLES)
        targets[f"{target_standard_error:.2f}"] = {
            "samples_per_entry": samples_per_entry,
            "total_samples": total_samples,
            "single_process_seconds": total_samples / samples_per_second,
        }
    return {
        "observed_samples_per_second": samples_per_second,
        "maximum_observed_standard_deviation": maximum_standard_deviation,
        "precision_targets": targets,
    }


def analyze(  # pylint: disable=too-many-locals
    policy: DiscardPolicy,
    hand_limit: int | None,
    physical_samples: int,
    seed: int,
) -> dict[str, Any]:
    """Run the exact rank analysis and the suit-aware sampling pilot."""
    started = time.monotonic()
    suitless_started = time.monotonic()
    suitless_table = exact_suitless_table(policy, hand_limit=hand_limit)
    suitless_seconds = time.monotonic() - suitless_started
    normalized_count = suit_normalized_six_card_state_count()
    pilot = []
    pilot_started = time.monotonic()
    if physical_samples:
        for deal_name, known_deal in REPRESENTATIVE_PHYSICAL_DEALS:
            rank_key = rank_hand_key(sorted(card[0] for card in known_deal))
            if rank_key not in suitless_table:
                continue
            role_results = {}
            for role in ROLES:
                moments = sample_suit_aware_hand_points(
                    known_deal,
                    role,
                    policy,
                    physical_samples,
                    _physical_sample_seed(seed, deal_name, role),
                )
                baseline = suitless_table[rank_key][role]
                role_results[role] = {
                    "n": moments.n,
                    "mu": moments.mean,
                    "standard_deviation": moments.standard_deviation,
                    "standard_error": moments.standard_error,
                    "suitless_mu": baseline,
                    "suit_effect": moments.mean - baseline,
                }
            pilot.append(
                {
                    "name": deal_name,
                    "canonical_key": physical_deal_key(canonical_suit_key(known_deal)),
                    "rank_key": rank_key,
                    "roles": role_results,
                }
            )
    pilot_seconds = time.monotonic() - pilot_started
    full_rank_state_count = len(get_hand_combinations_with_weights())
    report = {
        "model": {
            "known_cards": 6,
            "opponent_deal_population": 46,
            "opponent_dealt_cards": 6,
            "starter_population_after_both_deals": 40,
            "opponent_policy": "role-specific analytical E(h +/- c) rank policy",
            "suit_aware_policy_limit": (
                "physical scoring with unbiased suits among rank-equivalent keeps; "
                "discarded ranks remain policy-driven but suit-blind"
            ),
        },
        "discard_invariance": {
            "opponent_ev_varies_across_user_discards": False,
            "discard_choices": math.comb(6, 2),
            "reason": (
                "the same six user cards are removed for every discard choice, and "
                "the opponent cannot condition on the hidden selected discard"
            ),
        },
        "state_counts": {
            "physical_six_card_deals": PHYSICAL_SIX_CARD_DEALS,
            "suit_normalized_six_card_states": normalized_count,
            "suitless_rank_states": full_rank_state_count,
            "analyzed_suitless_rank_states": len(suitless_table),
            "exact_physical_outcomes_per_known_deal": (
                CONDITIONED_OPPONENT_DEALS * STARTERS_PER_DEAL
            ),
        },
        "suitless_exact": {
            "sampling_variance": 0.0,
            "roles": {role: _role_summary(suitless_table, role) for role in ROLES},
            "artifact_sizes": _rank_table_sizes(suitless_table),
            "elapsed_seconds": suitless_seconds,
        },
        "suit_aware_pilot": {
            "samples_per_deal_and_role": physical_samples,
            "deal_count": len(pilot),
            "entries": pilot,
            "elapsed_seconds": pilot_seconds,
            "runtime_projections": _runtime_projections(pilot, pilot_seconds),
            "normalized_artifact_size_projections": _normalized_size_projections(
                suitless_table, normalized_count, pilot
            ),
        },
        "recommendation": (
            "defer publishing until a position-aware experiment determines whether "
            "opponent mean, distribution, tail probabilities, or joint outcomes are "
            "needed; use the compact exact rank model as the first positional input"
        ),
        "elapsed_seconds": time.monotonic() - started,
    }
    return report


def physical_deal_key(cards: Sequence[tuple[int, int]]) -> str:
    """Format physical cards as a stable compact key."""
    return "_".join(f"{Index.indices[rank]}{suit}" for rank, suit in cards)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--hand-limit", type=positive_int)
    parser.add_argument(
        "--physical-samples", type=nonnegative_int, default=DEFAULT_PHYSICAL_SAMPLES
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--analytical-max-iterations",
        type=positive_int,
        default=DEFAULT_IBR_MAX_ITERATIONS,
    )
    parser.add_argument(
        "--full-hand-policy-max-iterations",
        type=positive_int,
        default=DEFAULT_FULL_HAND_POLICY_MAX_ITERATIONS,
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the issue 75 analysis command."""
    started = time.monotonic()
    args = _parse_args(argv)
    policy_started = time.monotonic()
    context = solve_initial_discard_policy(
        args.analytical_max_iterations,
        args.full_hand_policy_max_iterations,
    )
    policy_seconds = time.monotonic() - policy_started
    policy = selected_discards_to_policy(context.selected_discards)
    report = analyze(policy, args.hand_limit, args.physical_samples, args.seed)
    report["policy_solve_elapsed_seconds"] = policy_seconds
    report["total_elapsed_seconds"] = time.monotonic() - started
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        sys.stdout.write(serialized)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
