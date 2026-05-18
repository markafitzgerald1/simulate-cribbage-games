import argparse
import json
import math
import os
import random
import sys

if __package__ in (None, ""):  # pragma: no cover
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from artifact_pipeline.adapter import (  # noqa: E402
    Index,
    Card,
    DECK_SET,
    score_hand_and_starter,
    BEST_STATIC_SELECT_PONE_KEPT_CARDS,
    BEST_STATIC_SELECT_DEALER_KEPT_CARDS,
)


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


def compute_statistics(raw_scores):
    """
    Compute mean (mu) and standard error (se) from a list of raw scores.
    """
    n = len(raw_scores)
    if n == 0:
        return None

    mu = sum(raw_scores) / n
    if n == 1:
        return {"mu": mu, "se": 0.0}

    variance = sum((x - mu) ** 2 for x in raw_scores) / (n - 1)
    se = math.sqrt(variance) / math.sqrt(n)

    return {"mu": mu, "se": se}


def positive_int(value):
    ivalue = int(value)
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"{value} is an invalid positive int value")
    return ivalue


def main():
    parser = argparse.ArgumentParser(
        description="Generate crib points expected values table."
    )
    parser.add_argument(
        "--samples",
        type=positive_int,
        required=True,
        help="Number of Monte Carlo samples per pair (must be > 0).",
    )
    parser.add_argument(
        "--seed", type=int, help="Optional RNG seed for reproducible generation."
    )
    args = parser.parse_args()

    if args.seed is not None:
        rng = random.Random(args.seed)
    else:
        rng = random.Random()

    pairs = get_canonical_pairs()

    final_output = {}

    for pair in pairs:
        pair_data = {}
        for player in ["Dealer", "Pone"]:
            raw_scores_by_cut = run_monte_carlo(pair, player, args.samples, rng)

            player_data = {}
            for cut_card in Index.indices:
                raw_scores = raw_scores_by_cut[cut_card]
                stats = compute_statistics(raw_scores)
                if stats is not None:
                    player_data[cut_card] = stats
            pair_data[player] = player_data
        final_output[pair] = pair_data

    with open("expected_crib_points.json", "w") as f:
        json.dump(final_output, f, indent=2)

    print("Table generated successfully: expected_crib_points.json")


if __name__ == "__main__":  # pragma: no cover
    main()
