import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import math
import os
import random
import sys

if __package__ in (None, ""):  # pragma: no cover
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Justification: The script path shims must be placed at the very top before any
# workspace modules (such as artifact_pipeline or simulate_cribbage_games) are imported,
# otherwise standalone CLI runs cannot locate these packages.
# pylint: disable=wrong-import-position
import simulate_cribbage_games  # noqa: E402
from artifact_pipeline.adapter import (  # noqa: E402
    Index,
    Card,
    DECK_SET,
    score_hand_and_starter,
    BEST_STATIC_SELECT_PONE_KEPT_CARDS,
    BEST_STATIC_SELECT_DEALER_KEPT_CARDS,
    keep_max_post_cut_hand_plus_crib_points,
    minus_crib_points,
)


DEFAULT_OUTPUT_PATH = "expected_crib_points.json"
DEFAULT_CHECKPOINT_FREQUENCY = 100
METADATA_KEY = "__metadata__"
GENERATION_METHOD = "artifact_pipeline.generate_table.v1"


def get_canonical_pairs():
    """
    Generate the 169 canonical discard pairs.
    Format: [Rank1]_[Rank2]_[SuitStatus]
    Rank1 and Rank2 are from Index.indices (A, 2, ..., K).
    Rank1 is always less than or equal to Rank2 in value.
    SuitStatus is 'Suited' or 'Unsuited'.
    Pairs of the same rank (e.g., A_A) can only be 'Unsuited'.
    """
    pairs = []
    num_indices = len(Index.indices)
    for rank1_index in range(num_indices):
        for rank2_index in range(rank1_index, num_indices):
            rank1 = Index.indices[rank1_index]
            rank2 = Index.indices[rank2_index]

            # Same rank -> can only be unsuited
            if rank1_index == rank2_index:
                pairs.append(f"{rank1}_{rank2}_Unsuited")
            else:
                pairs.append(f"{rank1}_{rank2}_Suited")
                pairs.append(f"{rank1}_{rank2}_Unsuited")

    return pairs


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
    """
    Convert two Card objects to their canonical pair string representation.
    """
    index_1 = card_1.index
    index_2 = card_2.index
    rank_1 = Index.indices[index_1]
    rank_2 = Index.indices[index_2]

    # Sort ranks so rank_1 index is <= rank_2 index
    if index_1 > index_2:
        index_1, index_2 = index_2, index_1
        rank_1, rank_2 = rank_2, rank_1
        card_1, card_2 = card_2, card_1

    is_suited = (card_1.suit == card_2.suit) and (index_1 != index_2)
    suit_str = "Suited" if is_suited else "Unsuited"
    return f"{rank_1}_{rank_2}_{suit_str}"


def get_expected_crib_points_from_accumulators(
    generation_accumulators, pair_str, player_role, discarded_cards
):
    """
    Calculate the expected crib score from generation accumulators for the discard pair,
    weighted by the probability of each cut card.
    """
    discarded_indices = [card_item.index for card_item in discarded_cards]
    total_expected_value = 0.0
    total_weight = 0

    for rank_idx, rank_str in enumerate(Index.indices):
        match_count = discarded_indices.count(rank_idx)
        weight = 4 - match_count

        # Retrieve statistics from prior generation's accumulator
        accum_dict = (
            generation_accumulators.get(pair_str, {}).get(player_role, {}).get(rank_str)
        )
        if accum_dict and accum_dict["n"] > 0:
            mean_score = accum_dict["sum"] / accum_dict["n"]
            total_expected_value += mean_score * weight
            total_weight += weight

    return total_expected_value / total_weight if total_weight > 0 else 0.0


def select_opponent_kept_cards_dynamic(
    player_role, opponent_dealt, generation_accumulators=None
):
    """
    Select the opponent's kept cards.
    If generation_accumulators is provided, greedily maximize/minimize
    based on expected crib values from the prior generation.
    """
    if generation_accumulators is None:
        if player_role == "Dealer":
            return BEST_STATIC_SELECT_PONE_KEPT_CARDS(opponent_dealt)
        return BEST_STATIC_SELECT_DEALER_KEPT_CARDS(opponent_dealt)

    opponent_role = "Pone" if player_role == "Dealer" else "Dealer"

    def custom_expected_crib_points(discarded_dealt_cards):
        pair_str = cards_to_canonical(
            discarded_dealt_cards[0], discarded_dealt_cards[1]
        )
        return get_expected_crib_points_from_accumulators(
            generation_accumulators, pair_str, opponent_role, discarded_dealt_cards
        )

    def custom_expected_crib_points_ignoring_suit(discard1_idx, discard2_idx):
        card_1 = Card(discard1_idx, 0)
        card_2 = Card(discard2_idx, 1)
        pair_str = cards_to_canonical(card_1, card_2)
        return get_expected_crib_points_from_accumulators(
            generation_accumulators, pair_str, opponent_role, [card_1, card_2]
        )

    orig_non_suited = (
        simulate_cribbage_games.expected_random_opponent_discard_crib_points
    )
    orig_suited = (
        simulate_cribbage_games.expected_random_opponent_discard_crib_points_ignoring_suit
    )

    try:
        simulate_cribbage_games.expected_random_opponent_discard_crib_points = (
            custom_expected_crib_points
        )
        simulate_cribbage_games.expected_random_opponent_discard_crib_points_ignoring_suit = (
            custom_expected_crib_points_ignoring_suit
        )

        if opponent_role == "Dealer":
            return keep_max_post_cut_hand_plus_crib_points(opponent_dealt)
        return minus_crib_points(opponent_dealt)
    finally:
        simulate_cribbage_games.expected_random_opponent_discard_crib_points = (
            orig_non_suited
        )
        simulate_cribbage_games.expected_random_opponent_discard_crib_points_ignoring_suit = (
            orig_suited
        )


def run_monte_carlo(
    canonical_pair, player, num_samples, rng, generation_accumulators=None
):
    """
    Run Monte Carlo simulation for a specific canonical pair and player.
    Uses dynamic opponent logic based on generation_accumulators.
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
        kept = select_opponent_kept_cards_dynamic(
            player, opponent_dealt, generation_accumulators
        )

        # Cut card is drawn from the 44 remaining cards
        remaining_after_deal = [c for c in remaining_deck if c not in opponent_dealt]
        cut_card = rng.choice(remaining_after_deal)

        # Form the crib hand and calculate score
        score = score_hand_and_starter(
            discarded_cards + [c for c in opponent_dealt if c not in kept],
            cut_card,
            is_crib=True,
        )

        raw_scores_by_cut[Index.indices[cut_card.index]].append(score)

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


def build_metadata(seed, generation=0, generation_accumulators=None):
    return {
        "generation_method": GENERATION_METHOD,
        "seed": seed,
        "seed_was_specified": seed is not None,
        "generation": generation,
        "generation_accumulators": generation_accumulators,
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
    for key in ["generation_method", "seed", "seed_was_specified"]:
        if metadata.get(key) != build_metadata(seed).get(key):
            expected_metadata = build_metadata(seed)
            raise ValueError(
                f"Existing output {output_path} was generated with metadata "
                f"{metadata}, but this run requested {expected_metadata}. "
                "Use the same seed options as the original run or rerun with --no-resume."
            )


def load_or_initialize_accumulators(output_path, no_resume, seed):
    if no_resume:
        return {}, 0, None
    accumulators, metadata = load_output(output_path)
    if has_samples(accumulators) or metadata is not None:
        validate_resume_metadata(metadata, seed, output_path)
    generation = 0
    generation_accumulators = None
    if metadata is not None:
        generation = metadata.get("generation", 0)
        generation_accumulators = metadata.get("generation_accumulators")
    return accumulators, generation, generation_accumulators


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


def run_monte_carlo_into_accumulators(
    accumulators, canonical_pair, player, num_samples, sampling
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
            sampling.get("generation_accumulators"),
        )
        cut_card_rank_str = Index.indices[cut_card.index]
        update_accumulator(
            get_cut_accumulator(
                accumulators, canonical_pair, player, cut_card_rank_str
            ),
            score,
        )


# pylint: disable=too-few-public-methods
# Justification: WorkerState acts solely as a namespace for caching prior generation table
# estimates to avoid pickle overhead per worker process, hence requiring no public methods.
class WorkerState:
    """
    Module-level class to cache prior generation table once per subprocess
    worker during parallel Monte Carlo simulation runs.
    """

    generation_accumulators = None


def init_worker(generation_accumulators):
    """
    Initialize a worker process with the generation accumulators to avoid pickling overhead.
    """
    WorkerState.generation_accumulators = generation_accumulators


# Justification: Six parameters are required to serialize all components of the Monte
# Carlo state chunk (including RNG seeds, the active pair, player role, and generation state)
# to the subprocess worker cleanly.
# pylint: disable=too-many-arguments,too-many-positional-arguments
def run_monte_carlo_single_task(
    pair,
    player,
    num_samples,
    first_sample_index,
    seed,
    generation_accumulators=None,
):
    """
    Worker task to run a chunk of Monte Carlo samples for one pair and player.
    Returns the accumulated results for this chunk.
    """
    local_accumulators = {}
    gen_acc = (
        generation_accumulators
        if generation_accumulators is not None
        else WorkerState.generation_accumulators
    )
    sampling = {
        "rng": random.Random() if seed is None else None,
        "first_sample_index": first_sample_index,
        "seed": seed,
        "generation_accumulators": gen_acc,
    }
    run_monte_carlo_into_accumulators(
        local_accumulators, pair, player, num_samples, sampling
    )
    return pair, player, local_accumulators.get(pair, {}).get(player, {})


def merge_accumulators(accumulators, pair, player, local_player_acc):
    pair_data = accumulators.setdefault(pair, {})
    player_data = pair_data.setdefault(player, {})
    for cut_card, local_acc in local_player_acc.items():
        main_acc = player_data.setdefault(cut_card, empty_accumulator())
        main_acc["n"] += local_acc["n"]
        main_acc["sum"] += local_acc["sum"]
        main_acc["sum_squares"] += local_acc["sum_squares"]


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


# Justification: Seven parameters are required to serialize all components of the Monte
# Carlo state (including RNG seeds, list of active pairs, the current policy generation,
# and prior IBR policy states) to the output file wrapper safely.
# pylint: disable=too-many-arguments,too-many-positional-arguments
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


# Justification: Six arguments are necessary to coordinate the execution parameters, RNG,
# target pairs, active accumulator mappings, checkpoints, and prior generations in
# a single cohesive runner interface. Additionally, it handles parallel executor loops,
# KeyboardInterrupt worker termination, and complex state merging.
# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals,too-many-branches
def run_generation(
    args, rng, pairs, accumulators, checkpoint=None, generation_accumulators=None
):
    processes = getattr(args, "processes", 1)
    made_progress = False

    tasks = []
    for pair in pairs:
        for player in ["Dealer", "Pone"]:
            current_samples = get_total_sample_count(accumulators, pair, player)
            if args.infinite:
                samples_to_run = args.checkpoint_frequency
            else:
                samples_to_run = min(
                    args.checkpoint_frequency,
                    max(args.samples - current_samples, 0),
                )
            if samples_to_run > 0:
                tasks.append((pair, player, samples_to_run, current_samples))

    if tasks:
        if processes > 1:
            with ProcessPoolExecutor(
                max_workers=processes,
                initializer=init_worker,
                initargs=(generation_accumulators,),
            ) as executor:
                try:
                    futures = [
                        executor.submit(
                            run_monte_carlo_single_task,
                            pair,
                            player,
                            samples_to_run,
                            first_sample_index,
                            args.seed,
                            None,
                        )
                        for pair, player, samples_to_run, first_sample_index in tasks
                    ]
                    for future in as_completed(futures):
                        pair, player, local_player_acc = future.result()
                        merge_accumulators(accumulators, pair, player, local_player_acc)
                except KeyboardInterrupt:
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise
            made_progress = True
        else:
            for pair, player, samples_to_run, current_samples in tasks:
                run_monte_carlo_into_accumulators(
                    accumulators,
                    pair,
                    player,
                    samples_to_run,
                    {
                        "rng": rng,
                        "first_sample_index": current_samples,
                        "seed": args.seed,
                        "generation_accumulators": generation_accumulators,
                    },
                )
                made_progress = True

    if made_progress and checkpoint:
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


def _ev_shift(prev_data, curr_data, cut_card):
    prev_stats = accumulator_to_statistics(prev_data.get(cut_card, empty_accumulator()))
    curr_stats = accumulator_to_statistics(curr_data.get(cut_card, empty_accumulator()))
    if not prev_stats and not curr_stats:
        return 0.0
    prev_mu = prev_stats["mu"] if prev_stats else 0.0
    curr_mu = curr_stats["mu"] if curr_stats else 0.0
    return abs(curr_mu - prev_mu)


def calculate_max_ev_shift(prev_accumulators, current_accumulators, pairs):
    max_shift = 0.0
    for pair in pairs:
        for player in ["Dealer", "Pone"]:
            prev_data = prev_accumulators.get(pair, {}).get(player, {})
            curr_data = current_accumulators.get(pair, {}).get(player, {})
            for cut_card in Index.indices:
                max_shift = max(max_shift, _ev_shift(prev_data, curr_data, cut_card))
    return max_shift


def processes_type(value):
    if value.lower() == "auto":
        return max(1, (os.cpu_count() or 1) - 1)
    try:
        ivalue = int(value)
        if ivalue <= 0:
            raise argparse.ArgumentTypeError(
                f"{value} is an invalid positive int value"
            )
        return ivalue
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{value} must be a positive integer or 'auto'"
        ) from exc


def positive_int(value):
    ivalue = int(value)
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"{value} is an invalid positive int value")
    return ivalue


# Justification: The main entry point manages CLI argument parsing, interactive execution
# loops, files loading/saving, Ctrl-C signal management, and complex nested conditional
# flow for multi-generation best-response convergence checking.
# pylint: disable=too-many-statements,too-many-branches,too-many-nested-blocks
def main(override_pairs=None):
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
        "--processes",
        type=processes_type,
        default=1,
        help="Number of parallel worker processes to use or 'auto' (default: 1).",
    )
    args = parser.parse_args()

    if args.processes > 1:
        print(
            f"Running Monte Carlo simulations in parallel using {args.processes} worker processes..."
        )
    else:
        print("Running Monte Carlo simulations sequentially (1 worker process)...")

    if not args.infinite and args.samples is None:
        parser.error("--samples is required unless --infinite is set")

    if args.seed is not None:
        rng = random.Random(args.seed)
    else:
        rng = random.Random()

    pairs = override_pairs if override_pairs is not None else get_canonical_pairs()
    accumulators, generation, generation_accumulators = load_or_initialize_accumulators(
        args.output, args.no_resume, args.seed
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

    try:
        while True:
            if args.max_generations is not None and generation >= args.max_generations:
                print(f"Warning: Hardcap reached at generation {generation}.")
                checkpoint()
                break

            # Inner checkpoint loop: sample in chunks up to checkpoint_frequency
            # until reached_target_sample_count confirms the entire matrix is met
            # for the active generation.
            while True:
                if not args.infinite and reached_target_sample_count(
                    accumulators, pairs, args.samples
                ):
                    break

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
                        accumulators, pairs
                    )
                    print(
                        f"Generation {generation} Checkpoint written: {args.output} "
                        f"(n >= {completed_samples} samples per pair/player)"
                    )

                if not args.infinite:
                    if not made_progress:
                        break
                    if reached_target_sample_count(accumulators, pairs, args.samples):
                        break
                else:
                    made_progress = False
                    break

            if not args.infinite:
                # Check convergence threshold if set and generation > 0
                if args.convergence_threshold is not None and generation > 0:
                    if generation_accumulators is not None:
                        max_shift = calculate_max_ev_shift(
                            generation_accumulators, accumulators, pairs
                        )
                        if max_shift <= args.convergence_threshold:
                            print(
                                f"Converged at generation {generation} with max EV shift {max_shift} <= {args.convergence_threshold}"
                            )
                            checkpoint()
                            break

                # Advance policy generation only when entire sample target is fully met
                if reached_target_sample_count(accumulators, pairs, args.samples):
                    if (
                        args.max_generations is None
                        and args.convergence_threshold is None
                    ):
                        break

                    if (
                        args.max_generations is not None
                        and (generation + 1) >= args.max_generations
                    ):
                        print(
                            f"Warning: Hardcap reached at generation {generation + 1}."
                        )
                        checkpoint()
                        break

                    generation_accumulators = {
                        pair: {
                            player: {
                                cut: dict(accumulators[pair][player][cut])
                                for cut in Index.indices
                                if cut in accumulators[pair][player]
                            }
                            for player in ["Dealer", "Pone"]
                            if player in accumulators[pair]
                        }
                        for pair in get_canonical_pairs()
                        if pair in accumulators
                    }
                    accumulators = {}
                    generation += 1
                    checkpoint()
                else:
                    checkpoint()
                    break
            else:
                # Infinite loop checkpoints but does not advance generation
                made_progress = False
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
