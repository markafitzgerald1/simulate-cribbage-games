import argparse
import json
import secrets
import math

from src.artifact_pipeline.adapter import (
    Index,
    Card,
    DECK_SET,
    score_hand_and_starter,
    BEST_STATIC_SELECT_PONE_KEPT_CARDS,
    BEST_STATIC_SELECT_DEALER_KEPT_CARDS
)

# Use cryptographically secure random numbers as per codebase memory
rand = secrets.SystemRandom()


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
    for i in range(num_indices):
        for j in range(i, num_indices):
            rank1 = Index.indices[i]
            rank2 = Index.indices[j]

            # Same rank -> can only be unsuited
            if i == j:
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
    parts = canonical_pair.split('_')
    rank1_idx = Index.indices.find(parts[0])
    rank2_idx = Index.indices.find(parts[1])
    is_suited = parts[2] == "Suited"

    c1 = Card(rank1_idx, 0)
    c2 = Card(rank2_idx, 0 if is_suited else 1)

    return [c1, c2]


def run_monte_carlo(canonical_pair, player, num_samples):
    """
    Run Monte Carlo simulation for a specific canonical pair and player.
    Uses legacy Gen 0 opponent logic for the opponent's discards.
    Returns raw score data.
    """
    discarded_cards = canonical_to_cards(canonical_pair)
    remaining_deck = [card for card in DECK_SET if card not in discarded_cards]

    raw_scores_by_cut = {rank: [] for rank in Index.indices}

    for _ in range(num_samples):
        # Opponent gets 6 cards from the remaining 50
        opponent_dealt = rand.sample(remaining_deck, 6)

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
        cut_card = rand.choice(remaining_after_deal)

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
        return {"mu": 0.0, "se": 0.0}

    mu = sum(raw_scores) / n
    if n == 1:
        return {"mu": mu, "se": 0.0}

    variance = sum((x - mu) ** 2 for x in raw_scores) / (n - 1)
    se = math.sqrt(variance) / math.sqrt(n)

    return {"mu": mu, "se": se}


def main():
    parser = argparse.ArgumentParser(description="Generate crib points expected values table.")
    parser.add_argument("--samples", type=int, required=True, help="Number of Monte Carlo samples per pair.")
    args = parser.parse_args()

    pairs = get_canonical_pairs()

    final_output = {}

    for pair in pairs:
        pair_data = {}
        for player in ["Dealer", "Pone"]:
            raw_scores_by_cut = run_monte_carlo(pair, player, args.samples)

            player_data = {}
            for cut_card in Index.indices:
                raw_scores = raw_scores_by_cut[cut_card]
                player_data[cut_card] = compute_statistics(raw_scores)
            pair_data[player] = player_data
        final_output[pair] = pair_data

    with open("expected_crib_points.json", "w") as f:
        json.dump(final_output, f, indent=2)

    print("Table generated successfully: expected_crib_points.json")


if __name__ == "__main__":  # pragma: no cover
    main()
