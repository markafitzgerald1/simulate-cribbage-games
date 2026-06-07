# pylint: disable=duplicate-code
# Argparse CLI options for separate pipeline entry-point scripts share common arguments,
# which are kept inline to maintain standalone script usability without import complexity.
"""First-Principles Combinatorial expected value (EV) Solver.

This script solves for the exact Iterated Best Response (IBR) expected crib values
under the stated suit-free rank model (91 rank pairs). By precomputing exact
combinatorics and kept card probabilities under this model, it deterministically
enumerates Dealer and Pone discard strategies.

Relationship to the Monte Carlo Generator:
- While generate_table.py uses multi-process Monte Carlo simulations to model
  suited flushes and cards, this script evaluates expected values algebraically.
- The output of this script (expected_crib_points.analytical.json) serves as the
  ideal suit-free Generation 0 policy bootstrap for the Monte Carlo table
  generator, eliminating early-sample policy noise inside the stated rank model.
"""

import argparse
from functools import lru_cache
import itertools
import json
import math
import os
import sys
from typing import Iterable, List, Tuple

if __package__ in (None, ""):  # pragma: no cover
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# pylint: disable=wrong-import-position
from artifact_pipeline.adapter import (  # noqa: E402
    Index,
    cached_pairs_runs_and_fifteens_points,
    get_canonical_pairs,
)

DEFAULT_OUTPUT_PATH = "expected_crib_points.analytical.json"
GENERATION_METHOD = "artifact_pipeline.analytical_solver.v1"
DEFAULT_IBR_CONVERGENCE_THRESHOLD = 0.0001
DEFAULT_IBR_MAX_ITERATIONS = 100
# The full-hand policy loop converges very rapidly (typically in 1 or 2 iterations)
# because the pair-conditioned tables provide an extremely close approximation.
# A default cap of 3 ensures we reach stability/convergence while safely bounding
# execution time in case of rare policy oscillations.
DEFAULT_FULL_HAND_POLICY_MAX_ITERATIONS = 3
_POLICY_SCORE_CACHE_KEY = ("__policy_score_cache__",)
_POLICY_TOTAL_WEIGHT_CACHE_KEY = ("__policy_total_weight_cache__",)


def get_analytical_pairs():
    """Generate the 91 unique suit-free rank pairs (indices 0..12)."""
    pairs = []
    for r1 in range(13):
        for r2 in range(r1, 13):
            pairs.append((r1, r2))
    return pairs


def get_card_removal_weight(removed_cards, selected_cards):
    """Count physical selections of selected_cards after removed_cards are unavailable."""
    weight = 1
    for rank in set(selected_cards):
        available = 4 - removed_cards.count(rank)
        selected = selected_cards.count(rank)
        if selected > available:
            return 0
        weight *= math.comb(available, selected)
    return weight


@lru_cache(maxsize=None)
def score_combination_suit_free(kept_indices, starter_index, true_nobs=True):
    """
    Calculate the exact suit-free score of a 5-card rank index combination.
    Includes suit-averaged Nobs EV conditional on the starter rank.

    This is not the Nobs EV of a known physical hand. The outer hand-EV sum
    weights remaining starter ranks after removing all six dealt cards, which
    lowers the pre-starter Jack expectation when appropriate.
    """
    # 1. Base points (pairs, runs, and fifteens)
    all_indices = tuple(sorted(list(kept_indices) + [starter_index]))
    base_points = cached_pairs_runs_and_fifteens_points(all_indices)

    # 2. Suit-free Nobs EV
    nobs_ev = 0.0
    jacks_in_crib = sum(1 for idx in kept_indices if idx == 10)

    if true_nobs and jacks_in_crib > 0 and starter_index != 10:
        # After suits are marginalized out, a remaining non-Jack starter of a
        # known rank matches each Jack's suit with probability one quarter.
        nobs_ev = jacks_in_crib * 0.25

    return base_points + nobs_ev


def get_hand_combinations_with_weights():
    """
    Precompute all 18,564 unique dealt 6-card hand rank combinations
    along with their standard combinations weight.
    """
    hands = []
    # Generate all sorted multisets of size 6 from 13 ranks
    for comb in itertools.combinations_with_replacement(range(13), 6):
        # Count multiplicity of each rank to ensure it is <= 4 in the deck
        counts = [comb.count(r) for r in range(13)]
        if any(c > 4 for c in counts):
            continue

        # Compute standard combinatorial weight
        weight = 1
        for c in counts:
            if c > 0:
                weight *= math.comb(4, c)
        hands.append((comb, weight))
    return hands


def precompute_exact_crib_scores(true_nobs=True):
    """
    Precompute ExpectedCrib[d, p, c] for all 91 analytical Dealer pairs d,
    91 analytical Pone pairs p, and 13 cut cards c.
    ExpectedCrib[d, p, c] represents the exact expected crib score of d union p
    with cut card c, taking card-removal into account.
    """
    analytical_pairs = get_analytical_pairs()
    crib_scores = {}

    for d_idx, d in enumerate(analytical_pairs):
        for p_idx, p in enumerate(analytical_pairs):
            # Combine the two pairs to form the 4 crib cards
            crib_combination = tuple(sorted(list(d) + list(p)))

            crib_scores[(d_idx, p_idx)] = {}
            for c in range(13):
                # If all 4 cards of rank c are in the crib, it is impossible to cut a 5th card of rank c
                if crib_combination.count(c) == 4:
                    crib_scores[(d_idx, p_idx)][c] = 0.0
                    continue

                crib_scores[(d_idx, p_idx)][c] = score_combination_suit_free(
                    crib_combination, c, true_nobs=true_nobs
                )

    return crib_scores


def _build_crib_score_matrices(crib_scores, num_pairs):
    """Convert crib-score dictionaries into dense rank-score matrices."""
    score_rows = []
    score_totals = []
    for dealer_idx in range(num_pairs):
        row_values = []
        row_totals = []
        for pone_idx in range(num_pairs):
            scores = tuple(
                crib_scores[(dealer_idx, pone_idx)][rank] for rank in range(13)
            )
            row_values.append(scores)
            row_totals.append(4.0 * sum(scores))
        score_rows.append(row_values)
        score_totals.append(row_totals)
    return score_rows, score_totals


def _hand_conditioned_policy_ev(hand, cut_values):
    """Average policy EV over starter ranks available after the six-card hand."""
    return sum((4 - hand.count(rank)) * cut_values[rank] for rank in range(13)) / 46.0


def _iter_rank_count_subsets(
    rank_counts: Iterable[Tuple[int, int]]
) -> List[Tuple[Tuple[Tuple[int, int], ...], int, int]]:
    """Yield sparse rank-count subsets and their physical subset multiplicity."""
    sorted_rank_counts = sorted(rank_counts)
    # list of (prefix, subset_size, multiplicity)
    subsets: List[Tuple[Tuple[Tuple[int, int], ...], int, int]] = [((), 0, 1)]
    for rank, count in sorted_rank_counts:
        next_subsets = []
        for prefix, subset_size, multiplicity in subsets:
            next_subsets.append((prefix, subset_size, multiplicity))
            for selected_count in range(1, count + 1):
                next_subsets.append(
                    (
                        prefix + ((rank, selected_count),),
                        subset_size + selected_count,
                        multiplicity * math.comb(count, selected_count),
                    )
                )
        subsets = next_subsets
    return subsets


def _iter_containment_subset_weights(
    rank_counts: Iterable[Tuple[int, int]]
) -> List[Tuple[Tuple[Tuple[int, int], ...], int]]:
    """Yield physical-hand containment weights for every subset of a rank hand."""
    sorted_rank_counts = sorted(rank_counts)
    # list of (prefix, weight)
    subsets: List[Tuple[Tuple[Tuple[int, int], ...], int]] = [((), 1)]
    for rank, count in sorted_rank_counts:
        next_subsets = []
        for prefix, weight in subsets:
            for selected_count in range(count + 1):
                key = prefix
                if selected_count:
                    key = prefix + ((rank, selected_count),)
                next_subsets.append(
                    (
                        key,
                        weight * math.comb(4 - selected_count, count - selected_count),
                    )
                )
        subsets = next_subsets
    return subsets


def _add_policy_subset_entry(role_entries, discard_idx, rank_counts, weight):
    """Accumulate one selected-policy hand into a subset aggregate."""
    entry = role_entries.get(discard_idx)
    if entry is None:
        entry = [0.0, [0.0] * 13]
        role_entries[discard_idx] = entry
    entry[0] += weight
    for rank, count in rank_counts:
        entry[1][rank] += weight * count


def _build_policy_subset_aggregates(selected_discards, hand_rank_counts):
    """Build reusable selected-policy aggregates for full-hand conditioning."""
    aggregates = {}
    for (
        (_hand, dealer_discard_idx, pone_discard_idx),
        rank_counts,
    ) in zip(selected_discards, hand_rank_counts):
        for subset_key, weight in _iter_containment_subset_weights(rank_counts):
            dealer_entries, pone_entries = aggregates.setdefault(subset_key, ({}, {}))
            _add_policy_subset_entry(
                dealer_entries, dealer_discard_idx, rank_counts, weight
            )
            _add_policy_subset_entry(
                pone_entries, pone_discard_idx, rank_counts, weight
            )

    frozen_aggregates = {}
    for subset_key, (dealer_entries, pone_entries) in aggregates.items():
        frozen_aggregates[subset_key] = (
            _freeze_policy_subset_entries(dealer_entries),
            _freeze_policy_subset_entries(pone_entries),
        )
    frozen_aggregates[_POLICY_SCORE_CACHE_KEY] = {}
    frozen_aggregates[_POLICY_TOTAL_WEIGHT_CACHE_KEY] = {}
    return frozen_aggregates


def _freeze_policy_subset_entries(role_entries):
    """Freeze mutable aggregate entries into sparse rank-weight tuples."""
    return {
        discard_idx: (
            weight,
            tuple(
                (rank, rank_weight)
                for rank, rank_weight in enumerate(rank_weights)
                if rank_weight
            ),
        )
        for discard_idx, (weight, rank_weights) in role_entries.items()
    }


def _get_policy_subset_total_weight(policy_subset_aggregates, subset_key):
    """Return the policy hand weight for one contained-card subset."""
    total_weight_cache = policy_subset_aggregates[_POLICY_TOTAL_WEIGHT_CACHE_KEY]
    if subset_key not in total_weight_cache:
        _dealer_entries, pone_entries = policy_subset_aggregates[subset_key]
        total_weight_cache[subset_key] = sum(
            weight for weight, _rank_weights in pone_entries.values()
        )
    return total_weight_cache[subset_key]


def _score_policy_subset_role(
    entries, candidate_idx, score_rows, score_totals, candidate_is_dealer
):
    """Score one role's subset aggregate for a candidate discard."""
    base_total = 0.0
    removed_rank_totals = [0.0] * 13
    for opponent_idx, (weight, rank_weights) in entries.items():
        if candidate_is_dealer:
            scores = score_rows[candidate_idx][opponent_idx]
            total = score_totals[candidate_idx][opponent_idx]
        else:
            scores = score_rows[opponent_idx][candidate_idx]
            total = score_totals[opponent_idx][candidate_idx]
        base_total += weight * total - sum(
            rank_weight * scores[rank] for rank, rank_weight in rank_weights
        )
        for rank in range(13):
            removed_rank_totals[rank] += weight * scores[rank]
    return base_total, tuple(removed_rank_totals)


def _get_policy_subset_candidate_totals(
    policy_subset_aggregates, subset_key, candidate_idx, crib_score_matrices
):
    """Return cached scoring totals for one subset and candidate discard."""
    score_rows, score_totals = crib_score_matrices
    score_cache = policy_subset_aggregates[_POLICY_SCORE_CACHE_KEY]
    cache_key = (subset_key, candidate_idx)
    if cache_key in score_cache:
        return score_cache[cache_key]

    dealer_entries, pone_entries = policy_subset_aggregates[subset_key]
    dealer_totals = _score_policy_subset_role(
        pone_entries, candidate_idx, score_rows, score_totals, True
    )
    pone_totals = _score_policy_subset_role(
        dealer_entries, candidate_idx, score_rows, score_totals, False
    )

    score_cache[cache_key] = (
        dealer_totals[0],
        dealer_totals[1],
        pone_totals[0],
        pone_totals[1],
    )
    return score_cache[cache_key]


def _candidate_policy_crib_evs(
    removed_cards,
    candidate_indices,
    policy_subset_aggregates,
    analytical_pairs,
    crib_scores,
    crib_score_matrices=None,
):  # pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments
    """Evaluate candidate crib EVs using reusable selected-policy aggregates."""
    if crib_score_matrices is None:
        crib_score_matrices = _build_crib_score_matrices(
            crib_scores, len(analytical_pairs)
        )
    removed_rank_counts = tuple(
        (rank, removed_cards.count(rank)) for rank in sorted(set(removed_cards))
    )
    removed_count_by_rank = [0] * 13
    for rank, count in removed_rank_counts:
        removed_count_by_rank[rank] = count

    subset_terms = _iter_rank_count_subsets(removed_rank_counts)
    total_hand_weight = 0.0
    for subset_key, subset_size, multiplicity in subset_terms:
        if subset_key not in policy_subset_aggregates:
            continue
        coefficient = -multiplicity if subset_size % 2 else multiplicity
        total_hand_weight += coefficient * _get_policy_subset_total_weight(
            policy_subset_aggregates, subset_key
        )

    starter_denominator = 52.0 - len(removed_cards) - 6.0
    denominator = total_hand_weight * starter_denominator
    dealer_evs = {}
    pone_evs = {}
    if not denominator:
        return (
            {candidate_idx: 0.0 for candidate_idx in candidate_indices},
            {candidate_idx: 0.0 for candidate_idx in candidate_indices},
        )

    for candidate_idx in candidate_indices:
        dealer_total = 0.0
        pone_total = 0.0
        for subset_key, subset_size, multiplicity in subset_terms:
            if subset_key not in policy_subset_aggregates:
                continue
            coefficient = -multiplicity if subset_size % 2 else multiplicity
            (
                dealer_base_total,
                dealer_removed_rank_totals,
                pone_base_total,
                pone_removed_rank_totals,
            ) = _get_policy_subset_candidate_totals(
                policy_subset_aggregates,
                subset_key,
                candidate_idx,
                crib_score_matrices,
            )
            dealer_total += coefficient * (
                dealer_base_total
                - sum(
                    removed_count_by_rank[rank] * dealer_removed_rank_totals[rank]
                    for rank, _count in removed_rank_counts
                )
            )
            pone_total += coefficient * (
                pone_base_total
                - sum(
                    removed_count_by_rank[rank] * pone_removed_rank_totals[rank]
                    for rank, _count in removed_rank_counts
                )
            )

        dealer_evs[candidate_idx] = dealer_total / denominator
        pone_evs[candidate_idx] = pone_total / denominator

    return dealer_evs, pone_evs


def _select_discard_indices(
    hand_kept_evs,
    dl_tbl,
    pn_tbl,
    dealer_cut_table=None,
    pone_cut_table=None,
    opponent_policy_aggregates=None,
    analytical_pairs=None,
    crib_scores=None,
    crib_score_matrices=None,
):  # pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments
    """Select Dealer and Pone discards for each possible six-card rank hand."""
    selected = []
    for hand, _weight, discards_ev in hand_kept_evs:
        best_dl_idx = None
        best_dl_score = -math.inf
        best_pn_idx = None
        best_pn_score = -math.inf
        if opponent_policy_aggregates is not None:
            dl_candidate_evs, pn_candidate_evs = _candidate_policy_crib_evs(
                hand,
                discards_ev.keys(),
                opponent_policy_aggregates,
                analytical_pairs,
                crib_scores,
                crib_score_matrices,
            )
        else:
            dl_candidate_evs = None
            pn_candidate_evs = None
        for idx, hand_ev in discards_ev.items():
            if dl_candidate_evs is not None:
                dl_policy_ev = dl_candidate_evs[idx]
                pn_policy_ev = pn_candidate_evs[idx]
            else:
                dl_policy_ev = (
                    _hand_conditioned_policy_ev(hand, dealer_cut_table[idx])
                    if dealer_cut_table is not None
                    else dl_tbl[idx]
                )
                pn_policy_ev = (
                    _hand_conditioned_policy_ev(hand, pone_cut_table[idx])
                    if pone_cut_table is not None
                    else pn_tbl[idx]
                )
            dl_score = hand_ev + dl_policy_ev
            pn_score = hand_ev - pn_policy_ev
            if dl_score > best_dl_score:
                best_dl_idx = idx
                best_dl_score = dl_score
            if pn_score > best_pn_score:
                best_pn_idx = idx
                best_pn_score = pn_score
        selected.append((hand, best_dl_idx, best_pn_idx))
    return selected


def _expected_crib_cut_tables(
    selected_discards,
    analytical_pairs,
    crib_scores,
    conditioned_hand_weights,
    hand_rank_counts,
):
    """Evaluate cut-rank crib policy EVs against the selected discard policy."""
    conditioned_cut_values = [
        _evaluate_conditioned_crib_expected_cuts(
            fixed_idx,
            selected_discards,
            analytical_pairs,
            crib_scores,
            conditioned_hand_weights,
            hand_rank_counts,
        )
        for fixed_idx in range(len(analytical_pairs))
    ]
    return (
        [cut_values["Dealer"] for cut_values in conditioned_cut_values],
        [cut_values["Pone"] for cut_values in conditioned_cut_values],
    )


def _expected_crib_tables(  # pylint: disable=too-many-locals
    selected_discards,
    analytical_pairs,
    crib_scores,
    conditioned_hand_weights,
    hand_rank_counts,
):
    """Evaluate crib EVs against policies dealt from the remaining physical cards."""
    num_pairs = len(analytical_pairs)
    dl_next = [0.0] * num_pairs
    pn_next = [0.0] * num_pairs

    for fixed_idx, fixed_pair in enumerate(analytical_pairs):
        pone_discard_weights = [0.0] * num_pairs
        dealer_discard_weights = [0.0] * num_pairs
        pone_dealt_rank_weights = [[0.0] * 13 for _ in range(num_pairs)]
        dealer_dealt_rank_weights = [[0.0] * 13 for _ in range(num_pairs)]
        total_hand_weight = 0
        for (
            (_hand, dealer_discard_idx, pone_discard_idx),
            rank_counts,
            hand_weight,
        ) in zip(
            selected_discards, hand_rank_counts, conditioned_hand_weights[fixed_idx]
        ):
            if not hand_weight:
                continue
            total_hand_weight += hand_weight
            pone_discard_weights[pone_discard_idx] += hand_weight
            dealer_discard_weights[dealer_discard_idx] += hand_weight
            for rank, count in rank_counts:
                pone_dealt_rank_weights[pone_discard_idx][rank] += hand_weight * count
                dealer_dealt_rank_weights[dealer_discard_idx][rank] += (
                    hand_weight * count
                )

        dl_total = 0.0
        pn_total = 0.0
        for discard_idx in range(num_pairs):
            pone_weight = pone_discard_weights[discard_idx]
            if pone_weight:
                scores = crib_scores[(fixed_idx, discard_idx)]
                available_score = 4.0 * sum(scores.values()) - sum(
                    scores[rank] for rank in fixed_pair
                )
                dl_total += pone_weight * available_score - sum(
                    rank_weight * scores[rank]
                    for rank, rank_weight in enumerate(
                        pone_dealt_rank_weights[discard_idx]
                    )
                )
            dealer_weight = dealer_discard_weights[discard_idx]
            if dealer_weight:
                scores = crib_scores[(discard_idx, fixed_idx)]
                available_score = 4.0 * sum(scores.values()) - sum(
                    scores[rank] for rank in fixed_pair
                )
                pn_total += dealer_weight * available_score - sum(
                    rank_weight * scores[rank]
                    for rank, rank_weight in enumerate(
                        dealer_dealt_rank_weights[discard_idx]
                    )
                )
        denominator = total_hand_weight * 44.0
        if denominator:
            dl_next[fixed_idx] = dl_total / denominator
            pn_next[fixed_idx] = pn_total / denominator

    return dl_next, pn_next


def _max_policy_table_shift(current_tables, next_tables):
    """Return the largest absolute table movement between two policies."""
    dealer_table, pone_table, dealer_cut_table, pone_cut_table = current_tables
    dealer_next, pone_next, dealer_cut_next, pone_cut_next = next_tables
    max_shift = 0.0
    for pair_idx, (dealer_value, pone_value) in enumerate(zip(dealer_next, pone_next)):
        max_shift = max(
            max_shift,
            abs(dealer_value - dealer_table[pair_idx]),
            abs(pone_value - pone_table[pair_idx]),
        )
        for starter in range(13):
            max_shift = max(
                max_shift,
                abs(
                    dealer_cut_next[pair_idx][starter]
                    - dealer_cut_table[pair_idx][starter]
                ),
                abs(
                    pone_cut_next[pair_idx][starter] - pone_cut_table[pair_idx][starter]
                ),
            )
    return max_shift


def _run_analytical_ibr(
    true_nobs=True,
    max_iterations=DEFAULT_IBR_MAX_ITERATIONS,
    convergence_threshold=DEFAULT_IBR_CONVERGENCE_THRESHOLD,
    condition_policy_on_full_hand=True,
    full_hand_policy_max_iterations=DEFAULT_FULL_HAND_POLICY_MAX_ITERATIONS,
):
    """
    Execute the Iterated Best Response loop sequentially to solve
    for Dealer and Pone expected crib tables.
    condition_policy_on_full_hand=False is retained only for bounded historical
    comparison tests of the older pair-conditioned approximation. The command
    line and public solver API always use full-hand-conditioned policy
    selection. full_hand_policy_max_iterations bounds the expensive full-hand
    stability loop separately from the pair-conditioned table iteration cap.
    Returns:
      DlTbl: Expected crib value Dealer gets when Dealer discards d
      PnTbl: Expected crib value Dealer gets when Pone discards p
    """
    # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-many-nested-blocks
    # Dense mathematical IBR dynamic transition matrix computations are kept
    # unified in a single optimized block to prevent dictionary lookup overhead
    # and retain mathematical readability of the game-theoretic solver.
    analytical_pairs = get_analytical_pairs()
    num_pairs = len(analytical_pairs)
    print(f"Precomputing hand combinations and crib scores ({num_pairs} pairs)...")

    # 1. Precompute static combinations and crib scores
    hands = get_hand_combinations_with_weights()
    crib_scores = precompute_exact_crib_scores(true_nobs=true_nobs)
    crib_score_matrices = _build_crib_score_matrices(crib_scores, num_pairs)

    # 2. Precompute kept hand expected values for each of the 18,564 hands
    # Precomputing all unique 4-card kept rank combinations allows us to evaluate
    # kept EV algebraically without inner loop iterations.
    unique_kept = []
    for comb in itertools.combinations_with_replacement(range(13), 4):
        unique_kept.append(comb)

    kept_totals = {}
    kept_card_scores = {}
    for kept in unique_kept:
        card_scores = [
            score_combination_suit_free(kept, r, true_nobs=true_nobs) for r in range(13)
        ]
        kept_totals[kept] = sum(card_scores)
        kept_card_scores[kept] = card_scores

    hand_kept_evs = []
    for hand, weight in hands:
        discards_ev = {}
        # Find all unique 2-card discards from the 6 dealt cards
        unique_discards = sorted(list(set(itertools.combinations(hand, 2))))
        for d in unique_discards:
            # Ranks remaining in hand are kept
            kept = list(hand)
            kept.remove(d[0])
            kept.remove(d[1])
            kept_tup = tuple(kept)

            # Sum_{r} (4 - count_hand[r]) * score(kept, r) = 4 * TotalScore(kept) - Sum_{c in hand} score(kept, c)
            total_score = 4.0 * kept_totals[kept_tup] - sum(
                kept_card_scores[kept_tup][card] for card in hand
            )
            p_idx = analytical_pairs.index(d)
            discards_ev[p_idx] = total_score / 46.0
        hand_kept_evs.append((hand, weight, discards_ev))
    conditioned_hand_weights = [
        [get_card_removal_weight(pair, hand) for hand, _weight, _evs in hand_kept_evs]
        for pair in analytical_pairs
    ]
    hand_rank_counts = [
        tuple((rank, hand.count(rank)) for rank in sorted(set(hand)))
        for hand, _weight, _evs in hand_kept_evs
    ]

    # 3. IBR Convergence Loop
    dl_tbl = [0.0] * num_pairs
    pn_tbl = [0.0] * num_pairs
    dealer_cut_table = [[0.0] * 13 for _ in range(num_pairs)]
    pone_cut_table = [[0.0] * 13 for _ in range(num_pairs)]
    dampening = 0.50
    iteration = 0
    print(f"Starting pair-conditioned IBR loop (max {max_iterations} iterations)...")
    while iteration < max_iterations:
        selected_discards = _select_discard_indices(
            hand_kept_evs,
            dl_tbl,
            pn_tbl,
            dealer_cut_table,
            pone_cut_table,
        )
        dl_next, pn_next = _expected_crib_tables(
            selected_discards,
            analytical_pairs,
            crib_scores,
            conditioned_hand_weights,
            hand_rank_counts,
        )
        dealer_cut_next, pone_cut_next = _expected_crib_cut_tables(
            selected_discards,
            analytical_pairs,
            crib_scores,
            conditioned_hand_weights,
            hand_rank_counts,
        )

        # Apply dampening
        max_shift = 0.0
        for i in range(num_pairs):
            dl_shift = dampening * (dl_next[i] - dl_tbl[i])
            pn_shift = dampening * (pn_next[i] - pn_tbl[i])
            max_shift = max(max_shift, abs(dl_shift), abs(pn_shift))

            dl_tbl[i] += dl_shift
            pn_tbl[i] += pn_shift
            for starter in range(13):
                dealer_cut_shift = dampening * (
                    dealer_cut_next[i][starter] - dealer_cut_table[i][starter]
                )
                pone_cut_shift = dampening * (
                    pone_cut_next[i][starter] - pone_cut_table[i][starter]
                )
                max_shift = max(max_shift, abs(dealer_cut_shift), abs(pone_cut_shift))
                dealer_cut_table[i][starter] += dealer_cut_shift
                pone_cut_table[i][starter] += pone_cut_shift

        print(
            f"  Pair IBR iteration {iteration + 1}/{max_iterations}: "
            f"max shift = {max_shift:.6f}"
        )
        if max_shift < convergence_threshold:  # pragma: no cover
            print(f"IBR converged successfully in {iteration + 1} iterations.")
            break

        iteration += 1

    if condition_policy_on_full_hand:
        selected_discards = _select_discard_indices(
            hand_kept_evs, dl_tbl, pn_tbl, dealer_cut_table, pone_cut_table
        )
        full_hand_iterations = max(
            1, min(max_iterations, full_hand_policy_max_iterations)
        )
        print(
            f"Starting full-hand policy refinement "
            f"(max {full_hand_iterations} iterations)..."
        )
        for full_hand_iteration in range(full_hand_iterations):
            policy_subset_aggregates = _build_policy_subset_aggregates(
                selected_discards, hand_rank_counts
            )
            next_selected_discards = _select_discard_indices(
                hand_kept_evs,
                dl_tbl,
                pn_tbl,
                opponent_policy_aggregates=policy_subset_aggregates,
                analytical_pairs=analytical_pairs,
                crib_scores=crib_scores,
                crib_score_matrices=crib_score_matrices,
            )
            dealer_next, pone_next = _expected_crib_tables(
                next_selected_discards,
                analytical_pairs,
                crib_scores,
                conditioned_hand_weights,
                hand_rank_counts,
            )
            dealer_cut_next, pone_cut_next = _expected_crib_cut_tables(
                next_selected_discards,
                analytical_pairs,
                crib_scores,
                conditioned_hand_weights,
                hand_rank_counts,
            )
            max_shift = _max_policy_table_shift(
                (dl_tbl, pn_tbl, dealer_cut_table, pone_cut_table),
                (dealer_next, pone_next, dealer_cut_next, pone_cut_next),
            )
            changed_discards = sum(
                (old_dealer_idx != new_dealer_idx or old_pone_idx != new_pone_idx)
                for (
                    (_old_hand, old_dealer_idx, old_pone_idx),
                    (_new_hand, new_dealer_idx, new_pone_idx),
                ) in zip(selected_discards, next_selected_discards)
            )
            selected_discards = next_selected_discards
            dl_tbl = dealer_next
            pn_tbl = pone_next
            dealer_cut_table = dealer_cut_next
            pone_cut_table = pone_cut_next
            print(
                f"  Full-hand iteration {full_hand_iteration + 1}/"
                f"{full_hand_iterations}: "
                f"changed discards = {changed_discards}, "
                f"max shift = {max_shift:.6f}"
            )
            if not changed_discards or max_shift < convergence_threshold:
                print(
                    "Full-hand policy converged successfully in "
                    f"{full_hand_iteration + 1} iterations."
                )
                break
        else:
            print(
                "Warning: Full-hand policy did not converge within "
                f"{full_hand_iterations} iterations. "
                f"Remaining changed discards: {changed_discards}, "
                f"max shift: {max_shift:.6f}",
                file=sys.stderr,
            )

    return dl_tbl, pn_tbl, hand_kept_evs, crib_scores, dealer_cut_table, pone_cut_table


@lru_cache(maxsize=8)
def _cached_analytical_ibr(
    true_nobs,
    max_iterations,
    convergence_threshold,
    full_hand_policy_max_iterations,
):
    return _run_analytical_ibr(
        true_nobs=true_nobs,
        max_iterations=max_iterations,
        convergence_threshold=convergence_threshold,
        full_hand_policy_max_iterations=full_hand_policy_max_iterations,
    )


def _copy_analytical_ibr_result(result):
    dl_tbl, pn_tbl, hand_kept_evs, crib_scores, dealer_cut_table, pone_cut_table = (
        result
    )
    return (
        list(dl_tbl),
        list(pn_tbl),
        [
            (hand, weight, dict(discards_ev))
            for hand, weight, discards_ev in hand_kept_evs
        ],
        {key: dict(scores) for key, scores in crib_scores.items()},
        [list(row) for row in dealer_cut_table],
        [list(row) for row in pone_cut_table],
    )


def run_analytical_ibr(
    true_nobs=True,
    max_iterations=DEFAULT_IBR_MAX_ITERATIONS,
    convergence_threshold=DEFAULT_IBR_CONVERGENCE_THRESHOLD,
    full_hand_policy_max_iterations=DEFAULT_FULL_HAND_POLICY_MAX_ITERATIONS,
):
    """Return the rank-conditional analytical table for the requested Nobs mode."""
    return _copy_analytical_ibr_result(
        _cached_analytical_ibr(
            true_nobs,
            max_iterations,
            convergence_threshold,
            full_hand_policy_max_iterations,
        )
    )


# pylint: disable=too-many-arguments,too-many-positional-arguments
def _evaluate_conditioned_crib_expected_cuts(  # pylint: disable=too-many-locals
    fixed_idx,
    selected_discards,
    analytical_pairs,
    crib_scores,
    conditioned_hand_weights,
    hand_rank_counts,
):
    """Evaluate both roles after conditioning on the fixed pair and starter rank."""
    fixed_pair = analytical_pairs[fixed_idx]
    num_pairs = len(analytical_pairs)
    pone_discard_weights = [0.0] * num_pairs
    dealer_discard_weights = [0.0] * num_pairs
    pone_dealt_rank_weights = [[0.0] * 13 for _ in range(num_pairs)]
    dealer_dealt_rank_weights = [[0.0] * 13 for _ in range(num_pairs)]
    total_hand_weight = 0.0
    total_dealt_rank_weights = [0.0] * 13
    for (
        (_hand, dealer_discard_idx, pone_discard_idx),
        rank_counts,
        hand_weight,
    ) in zip(selected_discards, hand_rank_counts, conditioned_hand_weights[fixed_idx]):
        if not hand_weight:
            continue
        total_hand_weight += hand_weight
        pone_discard_weights[pone_discard_idx] += hand_weight
        dealer_discard_weights[dealer_discard_idx] += hand_weight
        for rank, count in rank_counts:
            rank_weight = hand_weight * count
            total_dealt_rank_weights[rank] += rank_weight
            pone_dealt_rank_weights[pone_discard_idx][rank] += rank_weight
            dealer_dealt_rank_weights[dealer_discard_idx][rank] += rank_weight

    role_values = {"Dealer": [], "Pone": []}
    for starter in range(13):
        starter_cards_available = 4 - fixed_pair.count(starter)
        dealer_total = 0.0
        pone_total = 0.0
        conditioned_total_weight = (
            total_hand_weight
            - total_dealt_rank_weights[starter] / starter_cards_available
        )
        if not conditioned_total_weight:
            role_values["Dealer"].append(0.0)
            role_values["Pone"].append(0.0)
            continue
        for discard_idx in range(num_pairs):
            pone_weight = (
                pone_discard_weights[discard_idx]
                - pone_dealt_rank_weights[discard_idx][starter]
                / starter_cards_available
            )
            dealer_weight = (
                dealer_discard_weights[discard_idx]
                - dealer_dealt_rank_weights[discard_idx][starter]
                / starter_cards_available
            )
            if not pone_weight and not dealer_weight:
                continue
            dealer_total += pone_weight * crib_scores[(fixed_idx, discard_idx)][starter]
            pone_total += dealer_weight * crib_scores[(discard_idx, fixed_idx)][starter]
        role_values["Dealer"].append(dealer_total / conditioned_total_weight)
        role_values["Pone"].append(pone_total / conditioned_total_weight)
    return role_values


# pylint: disable=too-many-locals
def format_table_as_generation_zero(
    dl_tbl,
    pn_tbl,
    hands,
    crib_scores,
    true_nobs,
    dealer_cut_table=None,
    pone_cut_table=None,
):
    """
    Format the 91-pair analytical tables into the exact 169 canonical
    suited/unsuited Generation 0 metadata structure expected by the generator.
    """
    # Mapping the 91-pair analytical matrices onto 169 canonical suited/unsuited
    # pairs requires nested rollups over absolute conditional opponent probabilities
    # to output the correct bootstrap formats cleanly and efficiently.
    analytical_pairs = get_analytical_pairs()
    canonical_pairs = get_canonical_pairs()

    if dealer_cut_table is not None and pone_cut_table is not None:
        conditioned_cut_values = [
            {"Dealer": list(dealer_values), "Pone": list(pone_values)}
            for dealer_values, pone_values in zip(dealer_cut_table, pone_cut_table)
        ]
    else:
        selected_discards = _select_discard_indices(hands, dl_tbl, pn_tbl)
        conditioned_hand_weights = [
            [get_card_removal_weight(pair, hand) for hand, _weight, _evs in hands]
            for pair in analytical_pairs
        ]
        hand_rank_counts = [
            tuple((rank, hand.count(rank)) for rank in sorted(set(hand)))
            for hand, _weight, _evs in hands
        ]
        conditioned_cut_values = [
            _evaluate_conditioned_crib_expected_cuts(
                fixed_idx,
                selected_discards,
                analytical_pairs,
                crib_scores,
                conditioned_hand_weights,
                hand_rank_counts,
            )
            for fixed_idx in range(len(analytical_pairs))
        ]

    # 2. Build canonical table matching the exact generator JSON format
    output = {
        "__metadata__": {
            "generation_method": GENERATION_METHOD,
            "seed": None,
            "seed_was_specified": False,
            "generation": 0,
            "generation_accumulators": None,
            "true_nobs_applied": true_nobs,
        }
    }

    ranks_mapping = {
        "A": 0,
        "2": 1,
        "3": 2,
        "4": 3,
        "5": 4,
        "6": 5,
        "7": 6,
        "8": 7,
        "9": 8,
        "T": 9,
        "J": 10,
        "Q": 11,
        "K": 12,
    }

    for canonical in canonical_pairs:
        # Convert canonical (e.g. 7_8_Suited) to ranks (e.g. 7, 8)
        parts = canonical.split("_")
        r1_name, r2_name = parts[0], parts[1]
        r1, r2 = ranks_mapping[r1_name], ranks_mapping[r2_name]
        d_idx = analytical_pairs.index((r1, r2))

        pair_data = {}
        for player in ["Dealer", "Pone"]:
            player_data = {}
            for cut_rank_str in Index.indices:
                c = ranks_mapping[cut_rank_str]

                # Evaluate exact EV of the crib conditional on this cut card.
                expected_crib_cut = conditioned_cut_values[d_idx][player][c]

                player_data[cut_rank_str] = {
                    "n": 0,
                    "mu": expected_crib_cut,
                    "se": 0.0,
                    "weight": 4 - analytical_pairs[d_idx].count(c),
                }
            pair_data[player] = player_data
        output[canonical] = pair_data

    return output


def main():
    parser = argparse.ArgumentParser(
        description="Generic First-Principles Suit-Free Analytical Solver."
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_PATH,
        help=f"Output JSON path (default: {DEFAULT_OUTPUT_PATH}).",
    )
    parser.add_argument(
        "--true-nobs",
        action="store_true",
        default=True,
        help="Record true Nobs metadata (default: True).",
    )
    parser.add_argument(
        "--no-true-nobs",
        action="store_false",
        dest="true_nobs",
        help="Record historical compatibility metadata for Hessel comparisons.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=DEFAULT_IBR_MAX_ITERATIONS,
        help=f"Max IBR iterations (default: {DEFAULT_IBR_MAX_ITERATIONS}).",
    )
    parser.add_argument(
        "--convergence-threshold",
        type=float,
        default=DEFAULT_IBR_CONVERGENCE_THRESHOLD,
        help=f"Convergence threshold (default: {DEFAULT_IBR_CONVERGENCE_THRESHOLD}).",
    )
    parser.add_argument(
        "--full-hand-policy-max-iterations",
        type=int,
        default=DEFAULT_FULL_HAND_POLICY_MAX_ITERATIONS,
        help=(
            "Max iterations for full-hand policy loop "
            f"(default: {DEFAULT_FULL_HAND_POLICY_MAX_ITERATIONS})."
        ),
    )
    args = parser.parse_args()

    print(
        f"Starting generic suit-free analytical solver "
        f"(true-nobs={args.true_nobs}, "
        f"max-iterations={args.max_iterations}, "
        f"convergence-threshold={args.convergence_threshold}, "
        f"full-hand-policy-max-iterations={args.full_hand_policy_max_iterations})..."
    )
    dl_tbl, pn_tbl, hands, crib_scores, dealer_cut_table, pone_cut_table = (
        run_analytical_ibr(
            true_nobs=args.true_nobs,
            max_iterations=args.max_iterations,
            convergence_threshold=args.convergence_threshold,
            full_hand_policy_max_iterations=args.full_hand_policy_max_iterations,
        )
    )

    output_data = format_table_as_generation_zero(
        dl_tbl,
        pn_tbl,
        hands,
        crib_scores,
        args.true_nobs,
        dealer_cut_table,
        pone_cut_table,
    )

    with open(args.output, "w", encoding="utf-8") as output_file:
        json.dump(output_data, output_file, indent=2)
        output_file.write("\n")

    print(
        f"Analytical table generated successfully: {args.output} "
        f"(91 rank pairs converted to 169 canonical suited/unsuited pairs)"
    )


if __name__ == "__main__":  # pragma: no cover
    main()
