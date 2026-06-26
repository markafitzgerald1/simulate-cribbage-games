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
    fifteens_points,
    pairs_points,
    runs_points,
    flush_points,
    nobs_points,
    cached_pairs_runs_and_fifteens_points,
    BEST_STATIC_SELECT_PONE_KEPT_CARDS,
    BEST_STATIC_SELECT_DEALER_KEPT_CARDS,
    DEFAULT_SELECT_PLAY,
)

__all__ = [
    "Card",
    "Index",
    "DECK_SET",
    "score_hand_and_starter",
    "score_hand_and_starter_breakdown",
    "cached_pairs_runs_and_fifteens_points",
    "BEST_STATIC_SELECT_PONE_KEPT_CARDS",
    "BEST_STATIC_SELECT_DEALER_KEPT_CARDS",
    "legacy_select_play_rank",
    "get_canonical_pairs",
    "score_hand_over_starters",
]


def legacy_select_play_rank(playable_ranks, current_play_count, sequence):
    """Select a rank using the immutable legacy simulator's default policy."""
    playable_cards = [Card(rank, 0) for rank in playable_ranks]
    sequence_cards = [Card(rank, 0) for rank in sequence]
    selected_index = DEFAULT_SELECT_PLAY(
        playable_cards, current_play_count, sequence_cards
    )
    return playable_cards[selected_index].index


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


def score_hand_and_starter_breakdown(kept_hand, starter, is_crib=False):
    """Score a hand and starter with cribbage-rule point categories."""
    hand_plus_starter = [*kept_hand, starter]
    sorted_indices = tuple(sorted(card.index for card in hand_plus_starter))
    fifteens = fifteens_points(hand_plus_starter)
    pairs = pairs_points(sorted_indices)
    runs = runs_points(sorted_indices)
    flushes = flush_points(kept_hand, starter, is_crib=is_crib)
    nobs = nobs_points(kept_hand, starter)
    total = fifteens + pairs + runs + flushes + nobs
    return {
        "total": total,
        "fifteens": fifteens,
        "pairs": pairs,
        "runs": runs,
        "flushes": flushes,
        "nobs": nobs,
    }


JACK_INDEX = 10


def insert_sorted(sorted_4, x):
    """
    Inserts value x into a sorted 4-element tuple to produce a sorted 5-element tuple.
    Avoids overhead of sorting list of 5 elements.
    """
    if x <= sorted_4[0]:
        return (x, sorted_4[0], sorted_4[1], sorted_4[2], sorted_4[3])
    if x <= sorted_4[1]:
        return (sorted_4[0], x, sorted_4[1], sorted_4[2], sorted_4[3])
    if x <= sorted_4[2]:
        return (sorted_4[0], sorted_4[1], x, sorted_4[2], sorted_4[3])
    if x <= sorted_4[3]:
        return (sorted_4[0], sorted_4[1], sorted_4[2], x, sorted_4[3])
    return (sorted_4[0], sorted_4[1], sorted_4[2], sorted_4[3], x)


def score_hand_over_starters(kept_hand, starters):
    """
    Score a kept hand of 4 cards against a list of starter cards.
    Pre-computes hand-invariant properties to optimize performance.
    """
    sorted_kept_indices = sorted([c.index for c in kept_hand])

    kept_hand_suits = [c.suit for c in kept_hand]
    is_flush = (
        kept_hand_suits[0]
        == kept_hand_suits[1]
        == kept_hand_suits[2]
        == kept_hand_suits[3]
    )
    flush_suit = kept_hand_suits[0] if is_flush else -1

    jack_suits = {c.suit for c in kept_hand if c.index == JACK_INDEX}

    scores = {}
    for starter in starters:
        # 1. Pairs, runs, fifteens points (cached)
        hand_combo = insert_sorted(sorted_kept_indices, starter.index)
        pts = cached_pairs_runs_and_fifteens_points(hand_combo)

        # 2. Flush points
        # is_crib=False because we are scoring the opponent's kept hand, not a crib.
        if is_flush:
            pts += 5 if starter.suit == flush_suit else 4

        # 3. Nobs points
        if starter.suit in jack_suits:
            pts += 1

        scores[starter] = pts

    return scores
