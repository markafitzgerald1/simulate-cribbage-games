"""Monte Carlo Expected Crib Points Table Generator.

This script executes multi-process Monte Carlo simulations to evaluate expected
crib points for the 169 canonical suited/unsuited discard pairs. It simulates
suit-ful deal distributions, accounting for crib flush rules and card-removal
effects.

Relationship to the Analytical Solver:
- While analytical_solver.py evaluates expected crib values algebraically using a
  suit-free rank model (converging in seconds), this script performs suited Monte
  Carlo simulations (modeling flush math and strategy variance).
- This script can be bootstrapped via the `--bootstrap` option using the
  analytical solver's converged expected_crib_points.analytical.json as the
  Generation 0 policy baseline, allowing dynamic play from the first sample.
"""

import argparse
import itertools
import json
import math
import os
import random
import statistics as stats_lib
import sys

if __package__ in (None, ""):  # pragma: no cover
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The import below follows the script-mode path shim.
# pylint: disable=wrong-import-position
from artifact_pipeline.adapter import (  # noqa: E402
    Index,
    Card,
    DECK_SET,
    score_hand_and_starter,
    score_hand_and_starter_breakdown,
    BEST_STATIC_SELECT_PONE_KEPT_CARDS,
    BEST_STATIC_SELECT_DEALER_KEPT_CARDS,
    get_canonical_pairs,
    score_hand_over_starters,
)

DEFAULT_OUTPUT_PATH = "expected_crib_points.json"
DEFAULT_CHECKPOINT_FREQUENCY = 100
METADATA_KEY = "__metadata__"
GENERATION_METHOD = "artifact_pipeline.generate_table.v2"
POINT_TYPES = ("total", "fifteens", "pairs", "runs", "flushes", "nobs")
MATCHING_DISCARD_SUIT = "matching_discard_suit"
NON_MATCHING_DISCARD_SUIT = "non_matching_discard_suit"
MATCHING_RANK_1_SUIT = "matching_rank_1_suit"
MATCHING_RANK_2_SUIT = "matching_rank_2_suit"
ROOT_ACCUMULATOR_KEYS = (
    "n",
    "sum",
    "sum_squares",
    "sum_weights_squared",
    "mu",
    "se",
    "policy_mu",
    "policy_se",
)


def canonical_to_cards(canonical_pair):
    """
    Given a canonical string like 'A_2_Suited', return two Card objects
    that match this pair. For 'Suited', they will both have suit 0.
    For 'Unsuited', they will have suit 0 and suit 1.
    """
    parts = canonical_pair.split("_")
    if len(parts) != 3:
        raise ValueError(f"Invalid canonical pair format: {canonical_pair}")

    if len(parts[0]) != 1 or len(parts[1]) != 1:
        raise ValueError(f"Invalid rank in canonical pair: {canonical_pair}")

    rank1_idx = Index.indices.find(parts[0])
    rank2_idx = Index.indices.find(parts[1])

    if rank1_idx == -1 or rank2_idx == -1:
        raise ValueError(f"Invalid rank in canonical pair: {canonical_pair}")

    suit_status = parts[2]
    if suit_status not in ("Suited", "Unsuited"):
        raise ValueError(
            f"Invalid suit status: {suit_status}. Must be 'Suited' or 'Unsuited'."
        )

    is_suited = suit_status == "Suited"

    if rank1_idx == rank2_idx and is_suited:
        raise ValueError(
            f"Impossible canonical pair: {canonical_pair}. Same rank pairs cannot be Suited."
        )

    card_1 = Card(rank1_idx, 0)
    card_2 = Card(rank2_idx, 0 if is_suited else 1)

    return [card_1, card_2]


def cards_to_canonical(card_1, card_2):
    if card_1.index <= card_2.index:
        c1, c2 = card_1, card_2
    else:
        c1, c2 = card_2, card_1

    rank1 = Index.indices[c1.index]
    rank2 = Index.indices[c2.index]

    if c1.index == c2.index:
        suit_status = "Unsuited"
    else:
        suit_status = "Suited" if c1.suit == c2.suit else "Unsuited"

    return f"{rank1}_{rank2}_{suit_status}"


def select_opponent_kept_cards_dynamic(
    player, opponent_dealt, generation_accumulators=None
):
    # pylint: disable=too-many-locals
    if generation_accumulators is None:
        if player == "Dealer":
            return BEST_STATIC_SELECT_PONE_KEPT_CARDS(opponent_dealt)
        return BEST_STATIC_SELECT_DEALER_KEPT_CARDS(opponent_dealt)

    opp_role = "Pone" if player == "Dealer" else "Dealer"
    plus_crib = opp_role == "Dealer"

    max_score = None
    best_kept = None

    deck_set_to_use = DECK_SET
    starters = [card for card in deck_set_to_use if card not in opponent_dealt]

    # Pre-build lookup table for policy EV by rank to avoid repeated dictionary and statistics logic.
    # We only look up the canonical pairs that actually could be formed by discarding from opponent_dealt.
    # Since there are only 15 combinations of 4 cards, there are 15 possible canonical pairs.
    ev_lookups = {}
    for kept_combination in itertools.combinations(opponent_dealt, 4):
        discarded = [c for c in opponent_dealt if c not in kept_combination]
        canonical_pair = cards_to_canonical(discarded[0], discarded[1])

        if canonical_pair not in ev_lookups:
            ev_by_rank = [0.0] * 13
            pair_data = generation_accumulators.get(canonical_pair) or {}
            player_data = pair_data.get(opp_role) or {}
            for r in range(13):
                acc = player_data.get(Index.indices[r])
                if acc:
                    stats = accumulator_to_statistics(acc)
                    ev_by_rank[r] = policy_mean(stats) if stats is not None else 0.0
            ev_lookups[canonical_pair] = ev_by_rank

    for kept_combination in itertools.combinations(opponent_dealt, 4):
        kept_hand = list(kept_combination)

        # 1. Calculate average hand score using our optimized batch scoring helper
        hand_scores = score_hand_over_starters(kept_hand, starters)
        total_hand_score = sum(hand_scores.values())
        average_hand_score = total_hand_score / len(starters)

        # 2. Calculate average crib score using the pre-computed policy EV table
        discarded = [c for c in opponent_dealt if c not in kept_hand]
        canonical_pair = cards_to_canonical(discarded[0], discarded[1])
        ev_by_rank = ev_lookups[canonical_pair]

        total_crib_score = sum(ev_by_rank[starter.index] for starter in starters)
        average_crib_score = total_crib_score / len(starters)

        if plus_crib:
            score = average_hand_score + average_crib_score
        else:
            score = average_hand_score - average_crib_score

        if max_score is None or score > max_score:
            max_score = score
            best_kept = kept_hand

    return best_kept


def run_monte_carlo(canonical_pair, player, num_samples, rng):
    """
    Run Monte Carlo simulation for a specific canonical pair and player.
    Uses legacy Gen 0 opponent logic for the opponent's discards.
    Returns raw score data.
    """
    if player not in ("Dealer", "Pone"):
        raise ValueError(f"Invalid player role: {player}. Must be 'Dealer' or 'Pone'.")

    discarded_cards = canonical_to_cards(canonical_pair)
    remaining_deck = [card for card in DECK_SET if card not in discarded_cards]

    raw_scores_by_cut = {rank: [] for rank in Index.indices}

    for _ in range(num_samples):
        # Opponent gets 6 cards from the remaining 50
        opponent_dealt = rng.sample(remaining_deck, 6)

        # Determine opponent strategy
        if player == "Dealer":
            # If we are Dealer, the crib is ours. Opponent is Pone.
            kept = BEST_STATIC_SELECT_PONE_KEPT_CARDS(opponent_dealt)
        else:
            # If we are Pone, the crib is opponent's (Dealer's).
            kept = BEST_STATIC_SELECT_DEALER_KEPT_CARDS(opponent_dealt)

        opponent_discards = [c for c in opponent_dealt if c not in kept]

        # Cut card is drawn from the 44 remaining cards
        remaining_after_deal = [c for c in remaining_deck if c not in opponent_dealt]
        cut_card = rng.choice(remaining_after_deal)

        # Form the crib hand
        crib_hand = discarded_cards + opponent_discards

        # Calculate score
        score = score_hand_and_starter(crib_hand, cut_card, is_crib=True)

        cut_card_rank_str = Index.indices[cut_card.index]
        raw_scores_by_cut[cut_card_rank_str].append(score)

    return raw_scores_by_cut


def empty_accumulator():
    return {"n": 0, "sum": 0.0, "sum_squares": 0.0, "sum_weights_squared": 0.0}


def update_accumulator(accumulator, value, weight=1.0):
    accumulator["n"] += weight
    accumulator["sum"] += value * weight
    accumulator["sum_squares"] += value * value * weight
    accumulator.setdefault("sum_weights_squared", 0.0)
    accumulator["sum_weights_squared"] += weight * weight


def update_breakdown_accumulator(accumulator, breakdown, weight=1.0):
    update_accumulator(accumulator, breakdown["total"], weight=weight)
    points = accumulator.setdefault("points", {})
    for point_type in POINT_TYPES:
        update_accumulator(
            points.setdefault(point_type, empty_accumulator()),
            breakdown[point_type],
            weight=weight,
        )


def update_relation_accumulator(accumulator, relation, breakdown, weight=1.0):
    relation_accumulators = accumulator.setdefault("starter_suit_relation", {})
    update_breakdown_accumulator(
        relation_accumulators.setdefault(relation, empty_accumulator()),
        breakdown,
        weight=weight,
    )


def root_accumulator_copy(accumulator):
    return {
        key: value for key, value in accumulator.items() if key in ROOT_ACCUMULATOR_KEYS
    }


def _root_accumulator_to_statistics(accumulator):
    n = accumulator["n"]
    if n == 0:
        if "mu" in accumulator:
            statistics = {
                "n": 0,
                "mu": accumulator["mu"],
                "se": accumulator.get("se", 0.0),
            }
            if "policy_mu" in accumulator:
                statistics["policy_mu"] = accumulator["policy_mu"]
                statistics["policy_se"] = accumulator.get("policy_se", 0.0)
            return statistics
        return None

    mu = accumulator["sum"] / n
    if n <= 1:
        statistics = {"n": n, "mu": mu, "se": 0.0}
        if (
            "sum_weights_squared" in accumulator
            and accumulator["sum_weights_squared"] != n
        ):
            statistics["sum_w2"] = accumulator["sum_weights_squared"]
    else:
        sum_w2 = accumulator.get("sum_weights_squared", n)
        denom = n - (sum_w2 / n)
        if denom <= 0:
            variance = 0.0
        else:
            variance = (accumulator["sum_squares"] - n * mu * mu) / denom
        se = math.sqrt(max(variance, 0.0)) / math.sqrt(n)
        statistics = {"n": n, "mu": mu, "se": se}
        if (
            "sum_weights_squared" in accumulator
            and accumulator["sum_weights_squared"] != n
        ):
            statistics["sum_w2"] = accumulator["sum_weights_squared"]

    if "policy_mu" in accumulator:
        statistics["policy_mu"] = accumulator["policy_mu"]
        statistics["policy_se"] = accumulator.get("policy_se", 0.0)
    return statistics


def accumulator_to_statistics(accumulator, include_nested=True):
    statistics = _root_accumulator_to_statistics(accumulator)
    if statistics is None:
        return None
    if not include_nested:
        return statistics

    points = {}
    for point_type, point_accumulator in accumulator.get("points", {}).items():
        point_statistics = accumulator_to_statistics(point_accumulator)
        if point_statistics is not None:
            points[point_type] = point_statistics
    if points:
        statistics["points"] = points

    relation_statistics = {}
    for relation, relation_accumulator in accumulator.get(
        "starter_suit_relation", {}
    ).items():
        stats = accumulator_to_statistics(relation_accumulator)
        if stats is not None:
            relation_statistics[relation] = stats
    if relation_statistics:
        statistics["starter_suit_relation"] = relation_statistics

    return statistics


def policy_mean(statistics):
    """Return the EV used for policy decisions from serialized statistics."""
    return statistics.get("policy_mu", statistics["mu"])


def statistics_to_accumulator(statistics):
    if "n" not in statistics:
        raise ValueError(
            "Existing output lacks n values. Regenerate it or rerun with --no-resume."
        )

    n = float(statistics["n"])
    if n.is_integer():
        n = int(n)
    mu = statistics["mu"]
    se = statistics.get("se", 0.0)
    if n == 0:
        accumulator = {"n": 0, "sum": 0.0, "sum_squares": 0.0, "mu": mu, "se": se}
    elif n <= 1:
        sum_w2 = statistics.get("sum_w2", n)
        accumulator = {
            "n": n,
            "sum": mu * n,
            "sum_squares": mu * mu * n,
            "sum_weights_squared": sum_w2,
        }
    else:
        sum_w2 = statistics.get("sum_w2", n)
        denom = n - (sum_w2 / n)
        variance = se * se * n
        if denom > 0:
            sum_squares = variance * denom + n * mu * mu
        else:
            sum_squares = n * mu * mu
        accumulator = {
            "n": n,
            "sum": mu * n,
            "sum_squares": sum_squares,
            "sum_weights_squared": sum_w2,
        }

    if "policy_mu" in statistics:
        accumulator["policy_mu"] = statistics["policy_mu"]
        accumulator["policy_se"] = statistics.get("policy_se", 0.0)
    if "points" in statistics:
        accumulator["points"] = {
            point_type: statistics_to_accumulator(point_stats)
            for point_type, point_stats in statistics["points"].items()
        }
    if "starter_suit_relation" in statistics:
        accumulator["starter_suit_relation"] = {
            relation: statistics_to_accumulator(relation_stats)
            for relation, relation_stats in statistics["starter_suit_relation"].items()
        }
    return accumulator


def blend_policy_accumulators(prior_accumulator, measured_accumulator, dampening):
    """Blend policy EV while retaining honest pooled measurement statistics."""
    if measured_accumulator is None:
        return (
            root_accumulator_copy(prior_accumulator)
            if prior_accumulator is not None
            else empty_accumulator()
        )
    if prior_accumulator is None:
        return root_accumulator_copy(measured_accumulator)

    prior_stats = accumulator_to_statistics(prior_accumulator)
    measured_stats = accumulator_to_statistics(measured_accumulator)
    if prior_stats is None:
        return root_accumulator_copy(measured_accumulator)
    if measured_stats is None:
        return root_accumulator_copy(prior_accumulator)

    prior_policy_mu = prior_stats.get("policy_mu", prior_stats["mu"])
    prior_policy_se = prior_stats.get("policy_se", prior_stats["se"])
    policy_mu = prior_policy_mu + dampening * (measured_stats["mu"] - prior_policy_mu)
    policy_se = math.sqrt(
        (1.0 - dampening) ** 2 * prior_policy_se**2
        + dampening**2 * measured_stats["se"] ** 2
    )
    sum_w2_prior = prior_accumulator.get("sum_weights_squared", prior_accumulator["n"])
    sum_w2_measured = measured_accumulator.get(
        "sum_weights_squared", measured_accumulator["n"]
    )
    return {
        "n": prior_accumulator["n"] + measured_accumulator["n"],
        "sum": prior_accumulator["sum"] + measured_accumulator["sum"],
        "sum_squares": (
            prior_accumulator["sum_squares"] + measured_accumulator["sum_squares"]
        ),
        "sum_weights_squared": sum_w2_prior + sum_w2_measured,
        "policy_mu": policy_mu,
        "policy_se": policy_se,
    }


def serialize_accumulators(accumulators, include_nested=True):
    if accumulators is None:
        return None
    serialized = {}
    for pair, pair_data in accumulators.items():
        if pair == METADATA_KEY:
            continue
        serialized[pair] = {}
        for player, player_data in pair_data.items():
            serialized[pair][player] = {}
            for cut_card, acc in player_data.items():
                stats = accumulator_to_statistics(acc, include_nested=include_nested)
                if stats is not None:
                    serialized[pair][player][cut_card] = stats
    return serialized


def deserialize_accumulators(serialized):
    if serialized is None:
        return None
    accumulators = {}
    for pair, pair_data in serialized.items():
        accumulators[pair] = {}
        for player, player_data in pair_data.items():
            accumulators[pair][player] = {}
            for cut_card, stats in player_data.items():
                accumulators[pair][player][cut_card] = statistics_to_accumulator(stats)
    return accumulators


def build_metadata(
    seed, generation=0, generation_accumulators=None, use_control_variates=False
):
    return {
        "generation_method": GENERATION_METHOD,
        "seed": seed,
        "seed_was_specified": seed is not None,
        "generation": generation,
        "generation_accumulators": serialize_accumulators(
            generation_accumulators, include_nested=False
        ),
        "use_control_variates": use_control_variates,
    }


def load_output(output_path):
    if not os.path.exists(output_path):
        return {}, None

    with open(output_path, "r", encoding="utf-8") as table_file:
        table_data = json.load(table_file)

    metadata = table_data.get(METADATA_KEY)
    accumulators = {}
    for pair, pair_data in table_data.items():
        if pair == METADATA_KEY:
            continue
        accumulators[pair] = {}
        for player, player_data in pair_data.items():
            accumulators[pair][player] = {}
            for cut_card, stats_data in player_data.items():
                accumulators[pair][player][cut_card] = statistics_to_accumulator(
                    stats_data
                )
    return accumulators, metadata


def has_samples(accumulators):
    return any(
        accumulator["n"] > 0
        for pair_data in accumulators.values()
        for player_data in pair_data.values()
        for accumulator in player_data.values()
    )


def validate_resume_metadata(metadata, seed, output_path, use_control_variates=False):
    if metadata is None:
        raise ValueError(
            f"Existing output {output_path} lacks resume metadata. "
            "Regenerate it or rerun with --no-resume."
        )
    if metadata.get("generation_method") != GENERATION_METHOD:
        raise ValueError(
            f"Existing output {output_path} was generated with method "
            f"{metadata.get('generation_method')}, but this run requested {GENERATION_METHOD}."
        )
    metadata_seed = metadata.get("seed")
    if metadata_seed != seed:
        raise ValueError(
            f"Existing output {output_path} was generated with seed "
            f"{metadata_seed}, but this run requested {seed}. "
            "Use the same seed options as the original run or rerun with --no-resume."
        )
    metadata_cv = metadata.get("use_control_variates", False)
    if metadata_cv != use_control_variates:
        raise ValueError(
            f"Existing output {output_path} was generated with use_control_variates={metadata_cv}, "
            f"but this run requested {use_control_variates}. "
            "Use the same options as the original run or rerun with --no-resume."
        )


# pylint: disable=too-many-arguments,too-many-positional-arguments
def load_or_initialize_accumulators(
    output_path,
    no_resume,
    seed,
    bootstrap_path=None,
    require_bootstrap=False,
    use_control_variates=False,
):
    if no_resume:
        accumulators, metadata = {}, None
    else:
        accumulators, metadata = load_output(output_path)
        if metadata is not None or has_samples(accumulators):
            validate_resume_metadata(metadata, seed, output_path, use_control_variates)
            return accumulators, metadata

    # Fresh run (not resuming) - check if we should bootstrap
    if bootstrap_path and os.path.exists(bootstrap_path):
        bootstrap_accumulators, _ = load_output(bootstrap_path)
        metadata = {
            "generation": 0,
            "generation_accumulators": serialize_accumulators(
                bootstrap_accumulators, include_nested=False
            ),
            "use_control_variates": use_control_variates,
        }
        return {}, metadata
    if bootstrap_path and require_bootstrap:
        raise FileNotFoundError(f"Bootstrap file not found: {bootstrap_path}")

    return accumulators, metadata


def get_cut_accumulator(accumulators, pair, player, cut_card):
    pair_data = accumulators.setdefault(pair, {})
    player_data = pair_data.setdefault(player, {})
    return player_data.setdefault(cut_card, empty_accumulator())


def get_total_sample_count(accumulators, pair, player):
    return sum(
        accumulator["n"]
        for accumulator in accumulators.get(pair, {}).get(player, {}).values()
    )


def sample_rng_for_index(rng, seed, canonical_pair, player, sample_index):
    if seed is None:
        return rng
    return random.Random(f"{seed}:{canonical_pair}:{player}:{sample_index}")


def average_breakdowns(breakdowns):
    return {
        point_type: sum(breakdown[point_type] for breakdown in breakdowns)
        / len(breakdowns)
        for point_type in POINT_TYPES
    }


def starter_suit_relation(canonical_pair, starter):
    parts = canonical_pair.split("_")
    if parts[2] == "Suited":
        return MATCHING_DISCARD_SUIT if starter.suit == 0 else NON_MATCHING_DISCARD_SUIT

    if parts[0] == parts[1]:
        # Pair
        return (
            MATCHING_DISCARD_SUIT
            if starter.suit in (0, 1)
            else NON_MATCHING_DISCARD_SUIT
        )

    if starter.suit == 0:
        return MATCHING_RANK_1_SUIT
    if starter.suit == 1:
        return MATCHING_RANK_2_SUIT
    return NON_MATCHING_DISCARD_SUIT


def average_starter_breakdowns(starter_breakdowns):
    return average_breakdowns([breakdown for _starter, breakdown in starter_breakdowns])


def relation_breakdowns_for_starters(canonical_pair, starter_breakdowns):
    relation_breakdowns = {}

    parts = canonical_pair.split("_")
    if parts[2] == "Suited" or parts[0] == parts[1]:
        relations = (MATCHING_DISCARD_SUIT, NON_MATCHING_DISCARD_SUIT)
    else:
        relations = (
            MATCHING_RANK_1_SUIT,
            MATCHING_RANK_2_SUIT,
            NON_MATCHING_DISCARD_SUIT,
        )

    for relation in relations:
        breakdowns = [
            breakdown
            for starter, breakdown in starter_breakdowns
            if starter_suit_relation(canonical_pair, starter) == relation
        ]
        if breakdowns:
            relation_breakdowns[relation] = (
                average_breakdowns(breakdowns),
                len(breakdowns),
            )
    return relation_breakdowns


def score_crib_sample_breakdown(
    discarded_cards,
    remaining_deck,
    player,
    sample_rng,
    generation_accumulators=None,
):
    opponent_dealt = sample_rng.sample(remaining_deck, 6)
    kept = select_opponent_kept_cards_dynamic(
        player, opponent_dealt, generation_accumulators
    )
    opponent_discards = [card for card in opponent_dealt if card not in kept]
    remaining_after_deal = [
        card for card in remaining_deck if card not in opponent_dealt
    ]
    cut_card = sample_rng.choice(remaining_after_deal)
    crib_hand = discarded_cards + opponent_discards
    breakdown = score_hand_and_starter_breakdown(crib_hand, cut_card, is_crib=True)
    return cut_card, breakdown


def score_crib_sample(
    discarded_cards,
    remaining_deck,
    player,
    sample_rng,
    generation_accumulators=None,
):
    cut_card, breakdown = score_crib_sample_breakdown(
        discarded_cards,
        remaining_deck,
        player,
        sample_rng,
        generation_accumulators,
    )
    return cut_card, breakdown["total"]


def score_crib_sample_ev_breakdown(
    discarded_cards,
    remaining_deck,
    player,
    sample_rng,
    generation_accumulators=None,
):
    opponent_dealt = sample_rng.sample(remaining_deck, 6)
    kept = select_opponent_kept_cards_dynamic(
        player, opponent_dealt, generation_accumulators
    )
    opponent_discards = [card for card in opponent_dealt if card not in kept]
    remaining_after_deal = [
        card for card in remaining_deck if card not in opponent_dealt
    ]
    crib_hand = discarded_cards + opponent_discards
    canonical_pair = cards_to_canonical(discarded_cards[0], discarded_cards[1])

    results = []
    for c in range(13):
        starters = [card for card in remaining_after_deal if card.index == c]
        if starters:
            starter_breakdowns = [
                (
                    starter,
                    score_hand_and_starter_breakdown(crib_hand, starter, is_crib=True),
                )
                for starter in starters
            ]
            results.append(
                (
                    c,
                    average_starter_breakdowns(starter_breakdowns),
                    len(starters),
                    relation_breakdowns_for_starters(
                        canonical_pair, starter_breakdowns
                    ),
                )
            )
    return results


def score_crib_sample_ev(
    discarded_cards,
    remaining_deck,
    player,
    sample_rng,
    generation_accumulators=None,
):
    results = score_crib_sample_ev_breakdown(
        discarded_cards,
        remaining_deck,
        player,
        sample_rng,
        generation_accumulators,
    )
    return [
        (rank, breakdown["total"], num_starters)
        for rank, breakdown, num_starters, _relations in results
    ]


def update_control_variates_result_accumulators(
    accumulators, canonical_pair, player, result
):
    c, breakdown, num_starters, relation_breakdowns = result
    weight = 13.0 * num_starters / 44.0
    accumulator = get_cut_accumulator(
        accumulators, canonical_pair, player, Index.indices[c]
    )
    update_breakdown_accumulator(accumulator, breakdown, weight=weight)
    for relation, (
        relation_breakdown,
        relation_starters,
    ) in relation_breakdowns.items():
        relation_weight = 13.0 * relation_starters / 44.0
        update_relation_accumulator(
            accumulator,
            relation,
            relation_breakdown,
            weight=relation_weight,
        )


# pylint: disable=too-many-arguments,too-many-positional-arguments
def _run_control_variates_sample(
    accumulators,
    canonical_pair,
    player,
    discarded_cards,
    remaining_deck,
    sample_rng,
    generation_accumulators,
):
    results = score_crib_sample_ev_breakdown(
        discarded_cards,
        remaining_deck,
        player,
        sample_rng,
        generation_accumulators,
    )
    for result in results:
        update_control_variates_result_accumulators(
            accumulators, canonical_pair, player, result
        )


# pylint: disable=too-many-arguments,too-many-positional-arguments
def _run_mc_sample(
    accumulators,
    canonical_pair,
    player,
    discarded_cards,
    remaining_deck,
    sample_rng,
    generation_accumulators,
):
    cut_card, breakdown = score_crib_sample_breakdown(
        discarded_cards,
        remaining_deck,
        player,
        sample_rng,
        generation_accumulators,
    )
    accumulator = get_cut_accumulator(
        accumulators, canonical_pair, player, Index.indices[cut_card.index]
    )
    update_breakdown_accumulator(accumulator, breakdown)
    relation = starter_suit_relation(canonical_pair, cut_card)
    if relation is not None:
        update_relation_accumulator(accumulator, relation, breakdown)


# pylint: disable=too-many-arguments,too-many-positional-arguments
def run_monte_carlo_into_accumulators(
    accumulators,
    canonical_pair,
    player,
    num_samples,
    sampling,
    generation_accumulators=None,
):
    """
    Run Monte Carlo samples and add raw score totals to cumulative accumulators.
    """
    if player not in ("Dealer", "Pone"):
        raise ValueError(f"Invalid player role: {player}. Must be 'Dealer' or 'Pone'.")

    discarded_cards = canonical_to_cards(canonical_pair)
    remaining_deck = [card for card in DECK_SET if card not in discarded_cards]

    use_cv = sampling.get("use_control_variates", False)
    for sample_offset in range(num_samples):
        sample_rng = sample_rng_for_index(
            sampling["rng"],
            sampling["seed"],
            canonical_pair,
            player,
            sampling["first_sample_index"] + sample_offset,
        )
        if use_cv:
            _run_control_variates_sample(
                accumulators,
                canonical_pair,
                player,
                discarded_cards,
                remaining_deck,
                sample_rng,
                generation_accumulators,
            )
        else:
            _run_mc_sample(
                accumulators,
                canonical_pair,
                player,
                discarded_cards,
                remaining_deck,
                sample_rng,
                generation_accumulators,
            )


def compute_statistics(raw_scores):
    """
    Compute mean (mu) and standard error (se) from a list of raw scores.
    """
    n = len(raw_scores)
    if n == 0:
        return None

    mu = sum(raw_scores) / n
    if n == 1:
        return {"n": n, "mu": mu, "se": 0.0}

    variance = sum((x - mu) ** 2 for x in raw_scores) / (n - 1)
    se = math.sqrt(variance) / math.sqrt(n)

    return {"n": n, "mu": mu, "se": se}


def accumulators_to_output(
    accumulators,
    seed=None,
    pairs=None,
    generation=0,
    generation_accumulators=None,
    use_control_variates=False,
):
    output = {
        METADATA_KEY: build_metadata(
            seed, generation, generation_accumulators, use_control_variates
        )
    }
    pairs_to_use = pairs if pairs is not None else get_canonical_pairs()
    for pair in pairs_to_use:
        pair_data = {}
        for player in ["Dealer", "Pone"]:
            player_data = {}
            for cut_card in Index.indices:
                accumulator = accumulators.get(pair, {}).get(player, {}).get(cut_card)
                if accumulator:
                    statistics = accumulator_to_statistics(accumulator)
                    if statistics is not None:
                        player_data[cut_card] = statistics
            pair_data[player] = player_data
        output[pair] = pair_data
    return output


def write_output(
    accumulators,
    output_path,
    seed=None,
    pairs=None,
    generation=0,
    generation_accumulators=None,
    use_control_variates=False,
):
    temporary_output_path = f"{output_path}.tmp"
    with open(temporary_output_path, "w", encoding="utf-8") as output_file:
        json.dump(
            accumulators_to_output(
                accumulators,
                seed,
                pairs,
                generation,
                generation_accumulators,
                use_control_variates,
            ),
            output_file,
            indent=2,
        )
        output_file.write("\n")
    os.replace(temporary_output_path, output_path)


def get_deal_count(accumulators, pair, player, use_cv=False):
    total = get_total_sample_count(accumulators, pair, player)
    if use_cv:
        return total / 13.0
    return total


def run_generation(
    args, rng, pairs, accumulators, checkpoint=None, generation_accumulators=None
):
    use_cv = getattr(args, "use_control_variates", False)
    made_progress = False
    for pair in pairs:
        for player in ["Dealer", "Pone"]:
            current_deals = get_deal_count(accumulators, pair, player, use_cv)
            if args.infinite and getattr(args, "samples", None) is None:
                deals_to_run = args.checkpoint_frequency
            else:
                deals_to_run = min(
                    args.checkpoint_frequency,
                    max(getattr(args, "samples", 0) - current_deals, 0),
                )

            if deals_to_run > 0:
                deals_to_run_int = int(round(deals_to_run))
                if deals_to_run_int > 0:
                    run_monte_carlo_into_accumulators(
                        accumulators,
                        pair,
                        player,
                        deals_to_run_int,
                        {
                            "rng": rng,
                            "first_sample_index": int(round(current_deals)),
                            "seed": args.seed,
                            "use_control_variates": use_cv,
                        },
                        generation_accumulators=generation_accumulators,
                    )
                    made_progress = True
    if made_progress and checkpoint:
        checkpoint()
    return made_progress


def minimum_completed_sample_count(accumulators, pairs, use_cv=False):
    return min(
        get_deal_count(accumulators, pair, player, use_cv)
        for pair in pairs
        for player in ["Dealer", "Pone"]
    )


def format_samples(n):
    return f"{int(round(n))}" if abs(n - round(n)) < 1e-9 else f"{n:.2f}"


def get_se_summary(accumulators, pairs):
    se_values = []
    for pair in pairs:
        pair_data = accumulators.get(pair)
        if not pair_data:
            continue
        for player in ["Dealer", "Pone"]:
            player_data = pair_data.get(player)
            if not player_data:
                continue
            for cut_card in Index.indices:
                acc = player_data.get(cut_card)
                if not acc:
                    continue
                stats = accumulator_to_statistics(acc)
                if stats is None or "se" not in stats:
                    continue
                n = stats.get("n", 0)
                sum_w2 = stats.get("sum_w2", n)
                denom = n - (sum_w2 / n) if n > 0 else 0.0
                if denom > 1e-9:
                    se_values.append(stats["se"])
    if not se_values:
        return None, None
    return stats_lib.median(se_values), max(se_values)


def reached_target_sample_count(accumulators, pairs, target_samples, use_cv=False):
    return all(
        get_deal_count(accumulators, pair, player, use_cv) >= target_samples - 1e-9
        for pair in pairs
        for player in ["Dealer", "Pone"]
    )


def build_generation_accumulators(
    prev_accumulators, measured_accumulators, pairs, dampening
):
    """Build the next policy table from prior policy and measured samples."""
    generation_accumulators = {}
    for pair in pairs:
        if pair == METADATA_KEY:  # pragma: no cover
            continue
        generation_accumulators[pair] = {}
        for player in ["Dealer", "Pone"]:
            generation_accumulators[pair][player] = {}
            prior_player_data = (
                prev_accumulators.get(pair, {}).get(player, {})
                if prev_accumulators
                else {}
            )
            measured_player_data = measured_accumulators.get(pair, {}).get(player, {})
            for cut in Index.indices:
                prior_acc = prior_player_data.get(cut)
                measured_acc = measured_player_data.get(cut)
                generation_accumulators[pair][player][cut] = blend_policy_accumulators(
                    prior_acc, measured_acc, dampening
                )
    return generation_accumulators


def calculate_max_ev_shift(
    prev_accumulators, current_accumulators, pairs, measured_accumulators=None
):  # pylint: disable=too-many-locals
    max_shift = 0.0
    for pair in pairs:
        for player in ["Dealer", "Pone"]:
            prev_data = prev_accumulators.get(pair, {}).get(player, {})
            curr_data = current_accumulators.get(pair, {}).get(player, {})
            measured_data = (
                measured_accumulators.get(pair, {}).get(player, {})
                if measured_accumulators is not None
                else curr_data
            )
            for cut_card in Index.indices:
                prev_acc = prev_data.get(cut_card, empty_accumulator())
                curr_acc = curr_data.get(cut_card, empty_accumulator())
                measured_acc = measured_data.get(cut_card, empty_accumulator())
                prev_stats = accumulator_to_statistics(prev_acc)
                curr_stats = accumulator_to_statistics(curr_acc)
                measured_stats = accumulator_to_statistics(measured_acc)
                if measured_stats is None or curr_stats is None:
                    return math.inf
                prev_mu = policy_mean(prev_stats) if prev_stats is not None else 0.0
                shift = abs(policy_mean(curr_stats) - prev_mu)
                max_shift = max(max_shift, shift)
    return max_shift


def positive_int(value):
    parsed_value = int(value)
    if parsed_value <= 0:
        raise argparse.ArgumentTypeError(f"{value} is an invalid positive int value")
    return parsed_value


def main(override_pairs=None):
    # pylint: disable=too-many-statements,too-many-branches,too-many-locals
    parser = argparse.ArgumentParser(
        description="Generate crib points expected values table."
    )
    parser.add_argument(
        "--samples",
        type=positive_int,
        help="Target cumulative Monte Carlo samples per pair (must be > 0).",
    )
    parser.add_argument(
        "--infinite",
        action="store_true",
        help="Keep adding samples until interrupted.",
    )
    parser.add_argument(
        "--checkpoint-frequency",
        type=positive_int,
        default=DEFAULT_CHECKPOINT_FREQUENCY,
        help=(
            "Samples per pair/player to add before each checkpoint "
            f"(default: {DEFAULT_CHECKPOINT_FREQUENCY})."
        ),
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_PATH,
        help=f"Output JSON path (default: {DEFAULT_OUTPUT_PATH}).",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore any existing output file and start a fresh run.",
    )
    parser.add_argument(
        "--max-generations",
        type=positive_int,
        help="Hard cap on convergence loop generations.",
    )
    parser.add_argument(
        "--convergence-threshold",
        type=float,
        help="Halt when maximum EV shift is below this threshold.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Optional RNG seed for reproducible generation.",
    )
    parser.add_argument(
        "--bootstrap",
        default=None,
        help="Optional JSON path to bootstrap baseline Generation 0 policy.",
    )
    parser.add_argument(
        "--dampening",
        type=float,
        default=0.50,
        help="Policy update dampening factor (default: 0.50).",
    )
    parser.add_argument(
        "--use-control-variates",
        action="store_true",
        help="Enable control variates expected value scoring (variance reduction).",
    )
    parser.add_argument(
        "--fail-on-non-convergence",
        action="store_true",
        help="Exit with a non-zero status code if the hardcap is reached without satisfying convergence.",
    )
    args = parser.parse_args()

    if not args.infinite and args.samples is None:
        parser.error("--samples is required unless --infinite is set")

    if (
        args.infinite
        and args.samples is None
        and (args.convergence_threshold is not None or args.max_generations is not None)
    ):
        parser.error(
            "--samples is required when using generation stop flags in --infinite mode"
        )

    if args.convergence_threshold is not None and args.convergence_threshold < 0:
        parser.error("--convergence-threshold must be non-negative")

    if args.fail_on_non_convergence and args.convergence_threshold is None:
        parser.error(
            "--fail-on-non-convergence requires --convergence-threshold to be set"
        )

    if args.dampening <= 0.0 or args.dampening > 1.0:
        parser.error("--dampening must be in range (0.0, 1.0]")

    if args.seed is not None:
        rng = random.Random(args.seed)
    else:
        rng = random.Random()

    pairs = override_pairs if override_pairs is not None else get_canonical_pairs()
    accumulators, metadata = load_or_initialize_accumulators(
        args.output,
        args.no_resume,
        args.seed,
        args.bootstrap,
        require_bootstrap=args.bootstrap is not None,
        use_control_variates=getattr(args, "use_control_variates", False),
    )

    generation = 0
    use_cv = getattr(args, "use_control_variates", False)
    generation_accumulators = None
    if metadata is not None:
        generation = metadata.get("generation", 0)
        generation_accumulators = deserialize_accumulators(
            metadata.get("generation_accumulators")
        )

    def checkpoint():
        write_output(
            accumulators,
            args.output,
            args.seed,
            pairs,
            generation,
            generation_accumulators,
            use_control_variates=getattr(args, "use_control_variates", False),
        )

    # pylint: disable=too-many-nested-blocks
    try:
        while True:
            if args.max_generations is not None and generation >= args.max_generations:
                if (
                    args.convergence_threshold is not None
                    and args.fail_on_non_convergence
                ):
                    print(
                        f"Error: Hardcap reached at generation {generation} "
                        f"before satisfying convergence threshold {args.convergence_threshold}.",
                        file=sys.stderr,
                    )
                    checkpoint()
                    sys.exit(1)
                else:
                    print(f"Warning: Hardcap reached at generation {generation}.")
                checkpoint()
                break

            # If we've reached the target sample count for this generation,
            # we check if we should continue to the next generation.
            if args.samples is not None and reached_target_sample_count(
                accumulators, pairs, args.samples, use_cv=use_cv
            ):
                next_generation_accumulators = build_generation_accumulators(
                    generation_accumulators, accumulators, pairs, args.dampening
                )
                # 1. Perform convergence check if convergence threshold is specified and generation > 0
                if args.convergence_threshold is not None and generation > 0:
                    max_shift = calculate_max_ev_shift(
                        generation_accumulators,
                        next_generation_accumulators,
                        pairs,
                        measured_accumulators=accumulators,
                    )
                    print(
                        f"Generation {generation} convergence check: "
                        f"max EV shift = {max_shift:.6f} (threshold = {args.convergence_threshold})"
                    )
                    if max_shift <= args.convergence_threshold:
                        print(
                            f"Converged at generation {generation} with max EV shift {max_shift} <= {args.convergence_threshold}"
                        )
                        checkpoint()
                        break

                # 2. Check if we have reached the max generations limit
                next_generation = generation + 1
                max_generations_limit = args.max_generations
                if max_generations_limit is None and args.convergence_threshold is None:
                    if not args.infinite:
                        max_generations_limit = 1

                if (
                    max_generations_limit is not None
                    and next_generation >= max_generations_limit
                ):
                    if max_generations_limit > 1 or args.max_generations is not None:
                        if (
                            args.convergence_threshold is not None
                            and args.fail_on_non_convergence
                        ):
                            print(
                                f"Error: Hardcap reached at generation {next_generation} "
                                f"before satisfying convergence threshold {args.convergence_threshold}.",
                                file=sys.stderr,
                            )
                            checkpoint()
                            sys.exit(1)
                        else:
                            print(
                                f"Warning: Hardcap reached at generation {next_generation}."
                            )
                    else:
                        print(
                            f"Generation {generation} complete; no convergence "
                            "threshold requested."
                        )
                    checkpoint()
                    break

                # 3. Transition to the next generation
                print(
                    f"Generation {generation} complete. Transitioning to Generation {next_generation}..."
                )
                generation_accumulators = next_generation_accumulators
                accumulators = {}
                generation = next_generation
                checkpoint()
                continue

            made_progress = run_generation(
                args,
                rng,
                pairs,
                accumulators,
                checkpoint=checkpoint,
                generation_accumulators=generation_accumulators,
            )

            if made_progress:
                completed_samples = minimum_completed_sample_count(
                    accumulators, pairs, use_cv=use_cv
                )
                typical_se, max_se = get_se_summary(accumulators, pairs)
                typical_se_str = (
                    f"{typical_se:.3f}" if typical_se is not None else "N/A"
                )
                max_se_str = f"{max_se:.3f}" if max_se is not None else "N/A"
                print(
                    f"Generation {generation} Checkpoint written: {args.output} "
                    f"(n >= {format_samples(completed_samples)} samples per pair/player, "
                    f"typical SE: {typical_se_str}, max SE: {max_se_str})"
                )

            if not args.infinite:
                if not made_progress:
                    checkpoint()
                    break
    except KeyboardInterrupt as exc:
        checkpoint()
        completed_samples = minimum_completed_sample_count(
            accumulators, pairs, use_cv=use_cv
        )
        typical_se, max_se = get_se_summary(accumulators, pairs)
        typical_se_str = f"{typical_se:.3f}" if typical_se is not None else "N/A"
        max_se_str = f"{max_se:.3f}" if max_se is not None else "N/A"
        print(
            f"\nInterrupted. Checkpoint written: {args.output} "
            f"(n >= {format_samples(completed_samples)} samples per pair/player, "
            f"typical SE: {typical_se_str}, max SE: {max_se_str})"
        )
        raise SystemExit(130) from exc

    print(f"Table generated successfully: {args.output}")


if __name__ == "__main__":  # pragma: no cover
    main()
