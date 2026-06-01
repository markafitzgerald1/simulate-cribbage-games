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
    BEST_STATIC_SELECT_PONE_KEPT_CARDS,
    BEST_STATIC_SELECT_DEALER_KEPT_CARDS,
    get_canonical_pairs,
)


DEFAULT_OUTPUT_PATH = "expected_crib_points.json"
DEFAULT_CHECKPOINT_FREQUENCY = 100
METADATA_KEY = "__metadata__"
GENERATION_METHOD = "artifact_pipeline.generate_table.v1"


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

    for kept_combination in itertools.combinations(opponent_dealt, 4):
        kept_hand = list(kept_combination)
        # Calculate average hand score
        total_hand_score = 0
        for starter in starters:
            total_hand_score += score_hand_and_starter(kept_hand, starter)
        average_hand_score = total_hand_score / len(starters)

        # Calculate average crib score using generation_accumulators
        discarded = [c for c in opponent_dealt if c not in kept_hand]
        canonical_pair = cards_to_canonical(discarded[0], discarded[1])

        total_crib_score = 0.0
        for starter in starters:
            starter_rank = Index.indices[starter.index]
            acc = (
                generation_accumulators.get(canonical_pair, {})
                .get(opp_role, {})
                .get(starter_rank)
            )
            if acc:
                stats = accumulator_to_statistics(acc)
                mu = stats["mu"] if stats is not None else 0.0
            else:
                mu = 0.0
            total_crib_score += mu
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
    return {"n": 0, "sum": 0.0, "sum_squares": 0.0}


def update_accumulator(accumulator, value):
    accumulator["n"] += 1
    accumulator["sum"] += value
    accumulator["sum_squares"] += value * value


def accumulator_to_statistics(accumulator):
    n = accumulator["n"]
    if n == 0:
        return None

    mu = accumulator["sum"] / n
    if n == 1:
        return {"n": n, "mu": mu, "se": 0.0}

    variance = (accumulator["sum_squares"] - n * mu * mu) / (n - 1)
    se = math.sqrt(max(variance, 0.0)) / math.sqrt(n)
    return {"n": n, "mu": mu, "se": se}


def statistics_to_accumulator(statistics):
    if "n" not in statistics:
        raise ValueError(
            "Existing output lacks n values. Regenerate it or rerun with --no-resume."
        )

    n = int(statistics["n"])
    mu = statistics["mu"]
    se = statistics.get("se", 0.0)
    if n <= 1:
        return {"n": n, "sum": mu * n, "sum_squares": mu * mu * n}

    variance = se * se * n
    return {
        "n": n,
        "sum": mu * n,
        "sum_squares": (n - 1) * variance + n * mu * mu,
    }


def serialize_accumulators(accumulators):
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
                stats = accumulator_to_statistics(acc)
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


def build_metadata(seed, generation=0, generation_accumulators=None):
    return {
        "generation_method": GENERATION_METHOD,
        "seed": seed,
        "seed_was_specified": seed is not None,
        "generation": generation,
        "generation_accumulators": serialize_accumulators(generation_accumulators),
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
            for cut_card, statistics in player_data.items():
                accumulators[pair][player][cut_card] = statistics_to_accumulator(
                    statistics
                )
    return accumulators, metadata


def has_samples(accumulators):
    return any(
        accumulator["n"] > 0
        for pair_data in accumulators.values()
        for player_data in pair_data.values()
        for accumulator in player_data.values()
    )


def validate_resume_metadata(metadata, seed, output_path):
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


def load_or_initialize_accumulators(output_path, no_resume, seed, bootstrap_path=None):
    if no_resume:
        accumulators, metadata = {}, None
    else:
        accumulators, metadata = load_output(output_path)
        if metadata is not None or has_samples(accumulators):
            validate_resume_metadata(metadata, seed, output_path)
            return accumulators, metadata

    # Fresh run (not resuming) - check if we should bootstrap
    if bootstrap_path and os.path.exists(bootstrap_path):
        bootstrap_accumulators, _ = load_output(bootstrap_path)
        metadata = {
            "generation": 0,
            "generation_accumulators": serialize_accumulators(bootstrap_accumulators),
        }
        return {}, metadata

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


def score_crib_sample(
    discarded_cards, remaining_deck, player, sample_rng, generation_accumulators=None
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
    score = score_hand_and_starter(crib_hand, cut_card, is_crib=True)
    return cut_card, score


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

    for sample_offset in range(num_samples):
        sample_index = sampling["first_sample_index"] + sample_offset
        sample_rng = sample_rng_for_index(
            sampling["rng"], sampling["seed"], canonical_pair, player, sample_index
        )
        cut_card, score = score_crib_sample(
            discarded_cards,
            remaining_deck,
            player,
            sample_rng,
            generation_accumulators,
        )
        cut_card_rank_str = Index.indices[cut_card.index]
        update_accumulator(
            get_cut_accumulator(
                accumulators, canonical_pair, player, cut_card_rank_str
            ),
            score,
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
    accumulators, seed=None, pairs=None, generation=0, generation_accumulators=None
):
    output = {METADATA_KEY: build_metadata(seed, generation, generation_accumulators)}
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
):
    temporary_output_path = f"{output_path}.tmp"
    with open(temporary_output_path, "w", encoding="utf-8") as output_file:
        json.dump(
            accumulators_to_output(
                accumulators, seed, pairs, generation, generation_accumulators
            ),
            output_file,
            indent=2,
        )
        output_file.write("\n")
    os.replace(temporary_output_path, output_path)


def run_generation(
    args, rng, pairs, accumulators, checkpoint=None, generation_accumulators=None
):
    made_progress = False
    for pair in pairs:
        for player in ["Dealer", "Pone"]:
            current_samples = get_total_sample_count(accumulators, pair, player)
            if args.infinite and getattr(args, "samples", None) is None:
                samples_to_run = args.checkpoint_frequency
            else:
                samples_to_run = min(
                    args.checkpoint_frequency,
                    max(getattr(args, "samples", 0) - current_samples, 0),
                )

            if samples_to_run > 0:
                run_monte_carlo_into_accumulators(
                    accumulators,
                    pair,
                    player,
                    samples_to_run,
                    {
                        "rng": rng,
                        "first_sample_index": current_samples,
                        "seed": args.seed,
                    },
                    generation_accumulators=generation_accumulators,
                )
                made_progress = True
                if checkpoint:
                    checkpoint()
    return made_progress


def minimum_completed_sample_count(accumulators, pairs):
    return min(
        get_total_sample_count(accumulators, pair, player)
        for pair in pairs
        for player in ["Dealer", "Pone"]
    )


def reached_target_sample_count(accumulators, pairs, target_samples):
    return all(
        get_total_sample_count(accumulators, pair, player) >= target_samples
        for pair in pairs
        for player in ["Dealer", "Pone"]
    )


def calculate_max_ev_shift(prev_accumulators, current_accumulators, pairs):
    max_shift = 0.0
    for pair in pairs:
        for player in ["Dealer", "Pone"]:
            prev_data = prev_accumulators.get(pair, {}).get(player, {})
            curr_data = current_accumulators.get(pair, {}).get(player, {})
            for cut_card in Index.indices:
                prev_acc = prev_data.get(cut_card, empty_accumulator())
                curr_acc = curr_data.get(cut_card, empty_accumulator())
                prev_stats = accumulator_to_statistics(prev_acc)
                curr_stats = accumulator_to_statistics(curr_acc)
                if curr_stats is not None:
                    prev_mu = prev_stats["mu"] if prev_stats is not None else 0.0
                    shift = abs(curr_stats["mu"] - prev_mu)
                    max_shift = max(max_shift, shift)
    return max_shift


def positive_int(value):
    ivalue = int(value)
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"{value} is an invalid positive int value")
    return ivalue


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
        default="expected_crib_points.analytical.json",
        help="Optional JSON path to bootstrap baseline Generation 0 policy.",
    )
    parser.add_argument(
        "--dampening",
        type=float,
        default=0.50,
        help="Policy update dampening factor (default: 0.50).",
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

    if args.dampening <= 0.0 or args.dampening > 1.0:
        parser.error("--dampening must be in range (0.0, 1.0]")

    if args.seed is not None:
        rng = random.Random(args.seed)
    else:
        rng = random.Random()

    pairs = override_pairs if override_pairs is not None else get_canonical_pairs()
    accumulators, metadata = load_or_initialize_accumulators(
        args.output, args.no_resume, args.seed, args.bootstrap
    )

    generation = 0
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
        )

    # pylint: disable=too-many-nested-blocks
    try:
        while True:
            if args.max_generations is not None and generation >= args.max_generations:
                print(f"Warning: Hardcap reached at generation {generation}.")
                checkpoint()
                break

            # If we've reached the target sample count for this generation,
            # we check if we should continue to the next generation.
            if args.samples is not None and reached_target_sample_count(
                accumulators, pairs, args.samples
            ):
                # 1. Perform convergence check if convergence threshold is specified and generation > 0
                if args.convergence_threshold is not None and generation > 0:
                    max_shift = calculate_max_ev_shift(
                        generation_accumulators, accumulators, pairs
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
                        print(
                            f"Warning: Hardcap reached at generation {next_generation}."
                        )
                    checkpoint()
                    break

                # 3. Transition to the next generation
                print(
                    f"Generation {generation} complete. Transitioning to Generation {next_generation}..."
                )
                prev_gen_accumulators = generation_accumulators
                dampening = args.dampening
                generation_accumulators = {}
                # pylint: disable=too-many-nested-blocks
                for pair in pairs:
                    if pair == METADATA_KEY:  # pragma: no cover
                        continue
                    generation_accumulators[pair] = {}
                    for player in ["Dealer", "Pone"]:
                        generation_accumulators[pair][player] = {}
                        prior_player_data = (
                            prev_gen_accumulators.get(pair, {}).get(player, {})
                            if prev_gen_accumulators
                            else {}
                        )
                        measured_player_data = accumulators.get(pair, {}).get(
                            player, {}
                        )
                        for cut in Index.indices:
                            # Prior stats
                            prior_acc = prior_player_data.get(cut)
                            if prior_acc:
                                stats_prior = accumulator_to_statistics(prior_acc)
                                val_prior = (
                                    stats_prior["mu"]
                                    if stats_prior is not None
                                    else 0.0
                                )
                            else:
                                stats_prior = None
                                val_prior = 0.0

                            # Measured stats
                            measured_acc = measured_player_data.get(cut)
                            if measured_acc:
                                stats_measured = accumulator_to_statistics(measured_acc)
                                val_measured = (
                                    stats_measured["mu"]
                                    if stats_measured is not None
                                    else 0.0
                                )
                                n_measured = (
                                    stats_measured["n"] if stats_measured else 0
                                )
                                se_measured = (
                                    stats_measured["se"] if stats_measured else 0.0
                                )
                            else:
                                stats_measured = None
                                val_measured = 0.0
                                n_measured = 0
                                se_measured = 0.0

                            # Apply low-pass dampened update and compile new statistics
                            if stats_measured is None:
                                if stats_prior is not None:
                                    val_new = val_prior
                                    n_new = stats_prior["n"]
                                    se_new = stats_prior["se"]
                                else:
                                    val_new = 0.0
                                    n_new = 0
                                    se_new = 0.0
                            else:
                                if stats_prior is not None:
                                    val_new = val_prior + dampening * (
                                        val_measured - val_prior
                                    )
                                    n_new = stats_prior["n"] + n_measured
                                    se_new = (
                                        (
                                            stats_prior["se"] * stats_prior["n"]
                                            + se_measured * n_measured
                                        )
                                        / n_new
                                        if n_new > 0
                                        else 0.0
                                    )
                                else:
                                    val_new = val_measured
                                    n_new = n_measured
                                    se_new = se_measured

                            stats_new = {
                                "n": n_new,
                                "mu": val_new,
                                "se": se_new,
                            }
                            generation_accumulators[pair][player][cut] = (
                                statistics_to_accumulator(stats_new)
                            )
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
                completed_samples = minimum_completed_sample_count(accumulators, pairs)
                print(
                    f"Generation {generation} Checkpoint written: {args.output} "
                    f"(n >= {completed_samples} samples per pair/player)"
                )

            if not args.infinite:
                if not made_progress:
                    checkpoint()
                    break
    except KeyboardInterrupt as exc:
        checkpoint()
        completed_samples = minimum_completed_sample_count(accumulators, pairs)
        print(
            f"\nInterrupted. Checkpoint written: {args.output} "
            f"(n >= {completed_samples} samples per pair/player)"
        )
        raise SystemExit(130) from exc

    print(f"Table generated successfully: {args.output}")


if __name__ == "__main__":  # pragma: no cover
    main()
