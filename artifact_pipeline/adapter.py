import os
import sys

# Add the project root to sys.path to import simulate_cribbage_games safely
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, ".."))
if project_root not in sys.path:  # pragma: no cover
    sys.path.insert(0, project_root)

# Import legacy engine functions and data structures safely.
# pylint: disable=wrong-import-position
from simulate_cribbage_games import (  # noqa: E402
    Card,
    Index,
    DECK_SET,
    score_hand_and_starter,
    cached_pairs_runs_and_fifteens_points,
    BEST_STATIC_SELECT_PONE_KEPT_CARDS,
    BEST_STATIC_SELECT_DEALER_KEPT_CARDS,
)

__all__ = [
    "Card",
    "Index",
    "DECK_SET",
    "score_hand_and_starter",
    "cached_pairs_runs_and_fifteens_points",
    "BEST_STATIC_SELECT_PONE_KEPT_CARDS",
    "BEST_STATIC_SELECT_DEALER_KEPT_CARDS",
    "get_canonical_pairs",
]


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
