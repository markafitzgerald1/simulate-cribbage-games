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
]
