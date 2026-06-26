"""Generate rank-only expected pegging points for browser consumption."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from copy import deepcopy
import json
import math
import os
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from typing import Any, Mapping, Sequence

if __package__ in (None, ""):  # pragma: no cover
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# pylint: disable=wrong-import-position
from artifact_pipeline.analytical_solver import (  # noqa: E402
    _expected_crib_cut_tables,
    _expected_crib_tables,
    _select_discard_indices,
    get_analytical_pairs,
    get_card_removal_weight,
    run_analytical_ibr,
)
from artifact_pipeline.pegging import (  # noqa: E402
    DEALER,
    PONE,
    POINT_TYPES,
    ROLES,
    PeggingPolicy,
    RunningStatistics,
    canonical_hand_key,
    get_canonical_hands,
    other_role,
    policy_fingerprint,
    simulate_pegging,
    train_iterative_best_response,
)

DEFAULT_OUTPUT_PATH = "expected_play_points.json"
DEFAULT_CLIENT_OUTPUT_PATH = "expected_play_points.client.json"
GENERATION_METHOD = "artifact_pipeline.generate_play_table.v1"
PHYSICAL_DECK = tuple((rank, suit) for rank in range(13) for suit in range(4))


@dataclass(frozen=True)
class AnalyticalContext:
    """Analytical hand/crib values and their current discard policy."""

    dealer_table: Sequence[float]
    pone_table: Sequence[float]
    hand_kept_evs: Sequence[tuple[tuple[int, ...], int, Mapping[int, float]]]
    crib_scores: Mapping[tuple[int, int], Mapping[int, float]]
    dealer_cut_table: Sequence[Sequence[float]]
    pone_cut_table: Sequence[Sequence[float]]
    selected_discards: Sequence[tuple[tuple[int, ...], int, int]]


@dataclass(frozen=True)
class DiscardPolicy:
    """Rank-only Dealer and Pone keep choices for every six-card multiset."""

    kept_by_role_and_hand: Mapping[tuple[str, tuple[int, ...]], tuple[int, ...]]

    def kept_ranks(self, role: str, dealt_ranks: Sequence[int]) -> tuple[int, ...]:
        """Return the policy's four kept ranks."""
        key = (role, tuple(sorted(dealt_ranks)))
        try:
            return self.kept_by_role_and_hand[key]
        except KeyError as error:
            raise ValueError(f"No discard policy for {key}") from error

    def keep_physical_cards(
        self, role: str, dealt_cards: Sequence[tuple[int, int]]
    ) -> tuple[tuple[int, int], ...]:
        """Choose physical cards matching the rank policy."""
        remaining = list(dealt_cards)
        kept = []
        for rank in self.kept_ranks(role, [card[0] for card in dealt_cards]):
            card = next(card for card in remaining if card[0] == rank)
            remaining.remove(card)
            kept.append(card)
        return tuple(kept)


@dataclass
class PlayerAccumulators:
    """Total and point-type moments for one absolute seat."""

    total: RunningStatistics
    points: dict[str, RunningStatistics]


@dataclass
class EntryAccumulators:
    """Paired delta and absolute-seat moments for one role bucket."""

    delta: RunningStatistics
    players: dict[str, PlayerAccumulators]


def selected_discards_to_policy(
    selected_discards: Sequence[tuple[tuple[int, ...], int, int]],
) -> DiscardPolicy:
    """Convert analytical discard indices to role-specific kept-rank mappings."""
    analytical_pairs = get_analytical_pairs()
    mapping = {}
    for hand, dealer_discard_index, pone_discard_index in selected_discards:
        for role, discard_index in (
            (DEALER, dealer_discard_index),
            (PONE, pone_discard_index),
        ):
            kept = list(hand)
            discard = analytical_pairs[discard_index]
            kept.remove(discard[0])
            kept.remove(discard[1])
            mapping[(role, tuple(hand))] = tuple(kept)
    return DiscardPolicy(mapping)


def solve_initial_discard_policy(
    analytical_max_iterations: int,
    full_hand_policy_max_iterations: int,
) -> AnalyticalContext:
    """Solve analytical E(h +/- c) and expose its selected discard policy."""
    (
        dealer_table,
        pone_table,
        hand_kept_evs,
        crib_scores,
        dealer_cut_table,
        pone_cut_table,
    ) = run_analytical_ibr(
        max_iterations=analytical_max_iterations,
        full_hand_policy_max_iterations=full_hand_policy_max_iterations,
    )
    selected = _select_discard_indices(
        hand_kept_evs,
        dealer_table,
        pone_table,
        dealer_cut_table,
        pone_cut_table,
    )
    return AnalyticalContext(
        dealer_table=dealer_table,
        pone_table=pone_table,
        hand_kept_evs=hand_kept_evs,
        crib_scores=crib_scores,
        dealer_cut_table=dealer_cut_table,
        pone_cut_table=pone_cut_table,
        selected_discards=selected,
    )


def sample_policy_deal(
    rng: random.Random, discard_policy: DiscardPolicy
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Deal two six-card hands and apply the current discard policy."""
    dealt = rng.sample(PHYSICAL_DECK, 12)
    pone_dealt = dealt[:6]
    dealer_dealt = dealt[6:]
    pone_kept = discard_policy.keep_physical_cards(PONE, pone_dealt)
    dealer_kept = discard_policy.keep_physical_cards(DEALER, dealer_dealt)
    return (
        tuple(sorted(card[0] for card in pone_kept)),
        tuple(sorted(card[0] for card in dealer_kept)),
    )


def _representative_physical_hand(ranks: Sequence[int]) -> tuple[tuple[int, int], ...]:
    used_suits = {rank: 0 for rank in set(ranks)}
    cards = []
    for rank in sorted(ranks):
        suit = used_suits[rank]
        cards.append((rank, suit))
        used_suits[rank] += 1
    return tuple(cards)


def sample_opponent_keep(
    target_hand: Sequence[int],
    opponent_role: str,
    discard_policy: DiscardPolicy,
    rng: random.Random,
) -> tuple[int, ...]:
    """Sample an opponent six-card deal after removing the target kept hand."""
    removed = set(_representative_physical_hand(target_hand))
    remaining_deck = [card for card in PHYSICAL_DECK if card not in removed]
    opponent_dealt = rng.sample(remaining_deck, 6)
    opponent_kept = discard_policy.keep_physical_cards(opponent_role, opponent_dealt)
    return tuple(sorted(card[0] for card in opponent_kept))


def _empty_entry_accumulators() -> EntryAccumulators:
    return EntryAccumulators(
        delta=RunningStatistics(),
        players={
            role: PlayerAccumulators(
                total=RunningStatistics(),
                points={point_type: RunningStatistics() for point_type in POINT_TYPES},
            )
            for role in ROLES
        },
    )


def _entry_from_output(entry: Mapping[str, Any]) -> EntryAccumulators:
    return EntryAccumulators(
        delta=RunningStatistics.from_dict(entry),
        players={
            role: PlayerAccumulators(
                total=RunningStatistics.from_dict(entry["players"][role]),
                points={
                    point_type: RunningStatistics.from_dict(
                        entry["players"][role]["points"][point_type]
                    )
                    for point_type in POINT_TYPES
                },
            )
            for role in ROLES
        },
    )


def _record_result(accumulators: EntryAccumulators, target_role, result) -> None:
    accumulators.delta.add(result.delta(target_role))
    for role in ROLES:
        player_accumulators = accumulators.players[role]
        player_accumulators.total.add(result.total(role))
        for point_type in POINT_TYPES:
            player_accumulators.points[point_type].add(result.players[role][point_type])


def _entry_to_output(accumulators: EntryAccumulators) -> dict[str, Any]:
    output: dict[str, Any] = accumulators.delta.to_dict()
    output["players"] = {}
    for role in ROLES:
        player_accumulators = accumulators.players[role]
        output["players"][role] = {
            **player_accumulators.total.to_dict(),
            "points": {
                point_type: player_accumulators.points[point_type].to_dict()
                for point_type in POINT_TYPES
            },
        }
    return output


def _entry_seed(seed: int, hand_index: int, role_index: int) -> int:
    return seed + hand_index * len(ROLES) + role_index


def _sample_seed(entry_seed: int, sample_index: int) -> int:
    return entry_seed + sample_index * 3_640_003


def validate_resume_table(
    existing_table: Mapping[str, Any],
    seed: int,
    expected_policy_fingerprint: str | None = None,
) -> None:
    """Reject checkpoints produced by an incompatible method or seed."""
    metadata = existing_table.get("__metadata__", {})
    if metadata.get("generation_method") != GENERATION_METHOD:
        raise ValueError("Existing play table uses an incompatible generation method")
    if metadata.get("seed") != seed:
        raise ValueError("Existing play table uses a different seed")
    if (
        expected_policy_fingerprint is not None
        and metadata.get("policy_fingerprint") != expected_policy_fingerprint
    ):
        raise ValueError("Existing play table uses a different play policy")


def generate_play_table(
    discard_policy: DiscardPolicy,
    policies: Mapping[str, PeggingPolicy],
    samples: int,
    seed: int,
    hands: Sequence[tuple[int, ...]] | None = None,
    target_standard_error: float | None = None,
    max_samples: int | None = None,
    existing_table: Mapping[str, Any] | None = None,
    checkpoint: Callable[[Mapping[str, Any]], None] | None = None,
    play_policy_fingerprint: str | None = None,
    checkpoint_frequency: int = 100,
) -> dict[str, Any]:
    """Generate paired seat and point-type estimates for every requested hand."""
    # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    if samples <= 0:
        raise ValueError("Samples must be positive")
    if target_standard_error is not None and target_standard_error <= 0.0:
        raise ValueError("Target standard error must be positive")
    if max_samples is not None and max_samples < samples:
        raise ValueError("Maximum samples cannot be below minimum samples")
    if checkpoint_frequency <= 0:
        raise ValueError("Checkpoint frequency must be positive")
    requested_hands = list(hands if hands is not None else get_canonical_hands())
    if existing_table is not None:
        validate_resume_table(existing_table, seed, play_policy_fingerprint)
    output: dict[str, Any] = deepcopy(dict(existing_table)) if existing_table else {}
    output["__metadata__"] = {
        **output.get("__metadata__", {}),
        **{
            "generation_method": GENERATION_METHOD,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "seed": seed,
            "minimum_samples": samples,
            "target_standard_error": target_standard_error,
            "max_samples": max_samples or samples,
            "hand_count": len(requested_hands),
            "policy_fingerprint": play_policy_fingerprint,
        },
    }
    for hand_index, hand in enumerate(requested_hands):
        hand_key = canonical_hand_key(hand)
        role_entries = output.setdefault(hand_key, {})
        for role_index, target_role in enumerate(ROLES):
            existing_entry = role_entries.get(target_role)
            accumulators = (
                _entry_from_output(existing_entry)
                if existing_entry is not None
                else _empty_entry_accumulators()
            )
            sample_limit = max_samples or samples
            while accumulators.delta.n < sample_limit:
                rng = random.Random(
                    _sample_seed(
                        _entry_seed(seed, hand_index, role_index),
                        accumulators.delta.n,
                    )
                )
                opponent_role = other_role(target_role)
                opponent_keep = sample_opponent_keep(
                    hand, opponent_role, discard_policy, rng
                )
                pone_hand = hand if target_role == PONE else opponent_keep
                dealer_hand = hand if target_role == DEALER else opponent_keep
                result = simulate_pegging(pone_hand, dealer_hand, policies, rng)
                _record_result(accumulators, target_role, result)
                if (
                    accumulators.delta.n >= samples
                    and target_standard_error is not None
                    and accumulators.delta.standard_error <= target_standard_error
                ):
                    break
                if accumulators.delta.n >= samples and target_standard_error is None:
                    break
            role_entries[target_role] = _entry_to_output(accumulators)
        if checkpoint is not None and (
            (hand_index + 1) % checkpoint_frequency == 0
            or hand_index + 1 == len(requested_hands)
        ):
            checkpoint(output)
    return output


def build_client_table(full_table: Mapping[str, Any]) -> dict[str, Any]:
    """Strip sample uncertainty while preserving every browser-visible mean."""
    client: dict[str, Any] = {}
    for hand_key, hand_entry in full_table.items():
        if hand_key == "__metadata__":
            continue
        client[hand_key] = {}
        for role in ROLES:
            role_entry = hand_entry[role]
            client_role = {"mu": round(role_entry["mu"], 4), "players": {}}
            for player in ROLES:
                player_entry = role_entry["players"][player]
                client_role["players"][player] = {
                    "mu": round(player_entry["mu"], 4),
                    "points": {
                        point_type: {
                            "mu": round(player_entry["points"][point_type]["mu"], 4)
                        }
                        for point_type in POINT_TYPES
                    },
                }
            client[hand_key][role] = client_role
    return client


def play_values_from_table(
    table: Mapping[str, Any],
) -> tuple[dict[tuple[int, ...], float], dict[tuple[int, ...], float]]:
    """Extract role-relative kept-hand values for discard policy refinement."""
    labels = {label: index for index, label in enumerate("A23456789TJQK")}
    by_role: dict[str, dict[tuple[int, ...], float]] = {
        DEALER: {},
        PONE: {},
    }
    for hand_key, hand_entry in table.items():
        if hand_key == "__metadata__":
            continue
        ranks = tuple(labels[label] for label in hand_key.split("_"))
        for role in ROLES:
            by_role[role][ranks] = hand_entry[role]["mu"]
    return by_role[DEALER], by_role[PONE]


def refine_discard_policy(
    context: AnalyticalContext,
    play_table: Mapping[str, Any],
) -> tuple[AnalyticalContext, int, float]:
    """Take one joint E(h +/- c +/- deltaP) discard-policy iteration."""
    dealer_play_values, pone_play_values = play_values_from_table(play_table)
    selected = _select_discard_indices(
        context.hand_kept_evs,
        context.dealer_table,
        context.pone_table,
        context.dealer_cut_table,
        context.pone_cut_table,
        dealer_play_values=dealer_play_values,
        pone_play_values=pone_play_values,
    )
    analytical_pairs = get_analytical_pairs()
    conditioned_hand_weights = [
        [
            get_card_removal_weight(pair, hand)
            for hand, _weight, _values in context.hand_kept_evs
        ]
        for pair in analytical_pairs
    ]
    hand_rank_counts = [
        tuple((rank, hand.count(rank)) for rank in sorted(set(hand)))
        for hand, _weight, _values in context.hand_kept_evs
    ]
    dealer_next, pone_next = _expected_crib_tables(
        selected,
        analytical_pairs,
        context.crib_scores,
        conditioned_hand_weights,
        hand_rank_counts,
    )
    dealer_cut_next, pone_cut_next = _expected_crib_cut_tables(
        selected,
        analytical_pairs,
        context.crib_scores,
        conditioned_hand_weights,
        hand_rank_counts,
    )
    changed = sum(
        old_dealer != new_dealer or old_pone != new_pone
        for (_hand, old_dealer, old_pone), (
            _next_hand,
            new_dealer,
            new_pone,
        ) in zip(context.selected_discards, selected)
    )
    max_shift = max(
        max(abs(new - old) for new, old in zip(dealer_next, context.dealer_table)),
        max(abs(new - old) for new, old in zip(pone_next, context.pone_table)),
    )
    return (
        AnalyticalContext(
            dealer_table=dealer_next,
            pone_table=pone_next,
            hand_kept_evs=context.hand_kept_evs,
            crib_scores=context.crib_scores,
            dealer_cut_table=dealer_cut_next,
            pone_cut_table=pone_cut_next,
            selected_discards=selected,
        ),
        changed,
        max_shift,
    )


def _write_json(path: str, data: Mapping[str, object], compact: bool = False) -> None:
    temporary_path = f"{path}.tmp-{os.getpid()}"
    with open(temporary_path, "w", encoding="utf-8") as output_file:
        json.dump(
            data,
            output_file,
            indent=None if compact else 2,
            separators=(",", ":") if compact else None,
            sort_keys=True,
        )
        output_file.write("\n")
    os.replace(temporary_path, path)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Value must be positive")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0.0 or not math.isfinite(parsed):
        raise argparse.ArgumentTypeError("Value must be finite and positive")
    return parsed


def maximum_play_shift(
    previous: Mapping[str, Any] | None, current: Mapping[str, Any]
) -> float:
    """Return the largest root-mean movement across shared role entries."""
    if previous is None:
        return math.inf
    maximum = 0.0
    for hand_key, hand_entry in current.items():
        if hand_key == "__metadata__" or hand_key not in previous:
            continue
        for role in ROLES:
            maximum = max(
                maximum,
                abs(hand_entry[role]["mu"] - previous[hand_key][role]["mu"]),
            )
    return maximum


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--client-output", default=DEFAULT_CLIENT_OUTPUT_PATH)
    parser.add_argument("--samples", type=positive_int, default=1000)
    parser.add_argument("--max-samples", type=positive_int)
    parser.add_argument("--target-standard-error", type=positive_float)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--ibr-iterations", type=positive_int, default=2)
    parser.add_argument("--ibr-samples", type=positive_int, default=5000)
    parser.add_argument("--rollouts-per-action", type=positive_int, default=2)
    parser.add_argument("--outer-iterations", type=positive_int, default=3)
    parser.add_argument("--policy-table-samples", type=positive_int, default=200)
    parser.add_argument("--checkpoint-frequency", type=positive_int, default=100)
    parser.add_argument("--analytical-max-iterations", type=positive_int, default=100)
    parser.add_argument(
        "--full-hand-policy-max-iterations", type=positive_int, default=3
    )
    parser.add_argument("--hand-limit", type=positive_int)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--fail-on-non-convergence", action="store_true")
    return parser.parse_args()


def main() -> None:
    """Train policies, refine discards, and write full and lean artifacts."""
    # pylint: disable=too-many-locals
    args = _parse_args()
    context = solve_initial_discard_policy(
        args.analytical_max_iterations,
        args.full_hand_policy_max_iterations,
    )
    requested_hands = get_canonical_hands()
    if args.hand_limit is not None:
        requested_hands = requested_hands[: args.hand_limit]
    reports = []
    converged = False
    stable_iterations = 0
    policies = None
    previous_policy_table = None
    for outer_iteration in range(args.outer_iterations):
        discard_policy = selected_discards_to_policy(context.selected_discards)
        policies, ibr_reports = train_iterative_best_response(
            partial(sample_policy_deal, discard_policy=discard_policy),
            iterations=args.ibr_iterations,
            samples_per_role=args.ibr_samples,
            rollouts_per_action=args.rollouts_per_action,
            seed=args.seed,
            initial_policies=policies,
        )
        policy_table = generate_play_table(
            discard_policy,
            policies,
            samples=args.policy_table_samples,
            seed=args.seed + outer_iteration,
            hands=requested_hands,
        )
        next_context, changed, max_shift = refine_discard_policy(context, policy_table)
        play_shift = maximum_play_shift(previous_policy_table, policy_table)
        changed_fraction = changed / len(context.selected_discards)
        reports.append(
            {
                "outer_iteration": outer_iteration + 1,
                "changed_discards": changed,
                "changed_discard_fraction": changed_fraction,
                "max_crib_shift": max_shift,
                "max_play_shift": play_shift,
                "play_ibr": ibr_reports,
            }
        )
        context = next_context
        previous_policy_table = policy_table
        if changed_fraction <= 0.001 and play_shift <= 0.01:
            stable_iterations += 1
        else:
            stable_iterations = 0
        if stable_iterations >= 2:
            converged = True
            break
    if args.fail_on_non_convergence and not converged:
        raise RuntimeError("Joint discard/play policy did not converge")
    if policies is None:  # pragma: no cover
        raise AssertionError("At least one outer iteration is required")
    discard_policy = selected_discards_to_policy(context.selected_discards)
    policies, final_ibr_reports = train_iterative_best_response(
        partial(sample_policy_deal, discard_policy=discard_policy),
        iterations=args.ibr_iterations,
        samples_per_role=args.ibr_samples,
        rollouts_per_action=args.rollouts_per_action,
        seed=args.seed + args.outer_iterations,
        initial_policies=policies,
    )
    reports.append({"final_play_ibr": final_ibr_reports})
    final_policy_fingerprint = ":".join(
        policy_fingerprint(policies[role]) for role in ROLES
    )
    existing_table = None
    if not args.no_resume and os.path.exists(args.output):
        with open(args.output, encoding="utf-8") as checkpoint_file:
            existing_table = json.load(checkpoint_file)

    def checkpoint(table: Mapping[str, Any]) -> None:
        _write_json(args.output, table)
        _write_json(args.client_output, build_client_table(table), compact=True)

    full_table = generate_play_table(
        discard_policy,
        policies,
        samples=args.samples,
        seed=args.seed,
        hands=requested_hands,
        target_standard_error=args.target_standard_error,
        max_samples=args.max_samples,
        existing_table=existing_table,
        checkpoint=checkpoint,
        play_policy_fingerprint=final_policy_fingerprint,
        checkpoint_frequency=args.checkpoint_frequency,
    )
    full_table["__metadata__"].update(
        {
            "joint_policy_converged": converged,
            "outer_iterations": reports,
        }
    )
    _write_json(args.output, full_table)
    _write_json(args.client_output, build_client_table(full_table), compact=True)
    print(
        f"Generated {len(requested_hands) * len(ROLES)} role entries in "
        f"{args.output} and {args.client_output}"
    )


if __name__ == "__main__":  # pragma: no cover
    main()
