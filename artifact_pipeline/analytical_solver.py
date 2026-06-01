# pylint: disable=duplicate-code
# Argparse CLI options for separate pipeline entry-point scripts share common arguments,
# which are kept inline to maintain standalone script usability without import complexity.
"""First-Principles Combinatorial expected value (EV) Solver.

This script solves for the exact game-theoretic Iterated Best Response (IBR)
expected crib values under a suit-free rank model (91 rank pairs). By precomputing
exact combinatorics and kept card probabilities, it resolves the Nash Equilibrium
for Dealer and Pone discard strategies.

Relationship to the Monte Carlo Generator:
- While generate_table.py uses multi-process Monte Carlo simulations to model
  suited flushes and cards, this script evaluates expected values algebraically,
  converging in less than 8 seconds sequentially.
- The output of this script (expected_crib_points.analytical.json) serves as the
  ideal mathematically rigorous Generation 0 policy bootstrap for the Monte
  Carlo table generator, eliminating early-sample policy noise.
"""

import argparse
from functools import lru_cache
import itertools
import json
import math
import os
import sys

if __package__ in (None, ""):  # pragma: no cover
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# pylint: disable=wrong-import-position
from artifact_pipeline.adapter import (  # noqa: E402
    Index,
    cached_pairs_runs_and_fifteens_points,
    get_canonical_pairs,
)

DEFAULT_OUTPUT_PATH = "expected_crib_points.analytical.json"


def get_analytical_pairs():
    """Generate the 91 unique suit-free rank pairs (indices 0..12)."""
    pairs = []
    for r1 in range(13):
        for r2 in range(r1, 13):
            pairs.append((r1, r2))
    return pairs


def get_card_removal_factor(pair1, pair2):
    """
    Compute the combinatorial card-removal factor for pair2 given pair1 is removed.
    This is proportional to product_{c} comb(4 - pair1.count(c), pair2.count(c)).
    """
    factor = 1.0
    for c in set(pair2):
        c1 = pair1.count(c)
        c2 = pair2.count(c)
        if c1 + c2 > 4:
            return 0.0
        # Re-weight from unconditioned comb(4, c2) to conditional comb(4 - c1, c2)
        factor *= math.comb(4 - c1, c2) / math.comb(4, c2)
    return factor


@lru_cache(maxsize=None)
def score_combination_suit_free(kept_indices, starter_index, true_nobs=True):
    """
    Calculate the exact suit-free score of a 5-card rank index combination.
    Includes either our exact conditional Nobs EV or Hessel's 0.25 flat approximation.
    """
    # 1. Base points (pairs, runs, and fifteens)
    all_indices = tuple(sorted(list(kept_indices) + [starter_index]))
    base_points = cached_pairs_runs_and_fifteens_points(all_indices)

    # 2. Suit-free Nobs EV
    nobs_ev = 0.0
    jacks_in_crib = sum(1 for idx in kept_indices if idx == 10)

    if jacks_in_crib > 0:
        if true_nobs:
            if starter_index != 10:  # Cut card is not a Jack
                # Expected Nobs per Jack: (44 + jacks_in_crib) / 192
                nobs_ev = jacks_in_crib * (44 + jacks_in_crib) / 192.0
        else:
            if starter_index != 10:
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


def run_analytical_ibr(true_nobs=True):
    """
    Execute the Iterated Best Response loop sequentially to solve
    for Dealer and Pone expected crib tables.
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

    # 1. Precompute static combinations and crib scores
    hands = get_hand_combinations_with_weights()
    crib_scores = precompute_exact_crib_scores(true_nobs=true_nobs)

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

    # 3. IBR Convergence Loop
    dl_tbl = [0.0] * num_pairs
    pn_tbl = [0.0] * num_pairs

    dampening = 0.50
    iteration = 0
    max_iterations = 100
    convergence_threshold = 0.0001

    while iteration < max_iterations:
        # Accumulate Dealer/Pone optimal choice weights
        dl_new_numerators = [0.0] * num_pairs
        dl_new_denominators = [0.0] * num_pairs
        pn_new_numerators = [0.0] * num_pairs
        pn_new_denominators = [0.0] * num_pairs

        for hand, weight, discards_ev in hand_kept_evs:
            best_dl_val = -float("inf")
            best_dl_idx = None
            best_pn_val = -float("inf")
            best_pn_idx = None

            for p_idx, hand_ev in discards_ev.items():
                # Dealer: Hand EV + Crib EV
                dl_val = hand_ev + dl_tbl[p_idx]
                if dl_val > best_dl_val:
                    best_dl_val = dl_val
                    best_dl_idx = p_idx

                # Pone: Hand EV - Crib EV
                pn_val = hand_ev - pn_tbl[p_idx]
                if pn_val > best_pn_val:
                    best_pn_val = pn_val
                    best_pn_idx = p_idx

            # Accumulate optimal choice weights
            dl_new_numerators[best_dl_idx] += weight
            dl_new_denominators[best_dl_idx] += weight

            pn_new_numerators[best_pn_idx] += weight
            pn_new_denominators[best_pn_idx] += weight

        # Compute next step tables
        dl_next = [0.0] * num_pairs
        pn_next = [0.0] * num_pairs

        # Dealer discard policy expected crib
        # DlTbl[d] = sum_{p} Pone_discard_prob[p | d] * ExpectedCrib[d, p]
        for d_idx in range(num_pairs):
            d_pair = analytical_pairs[d_idx]

            # Compute conditional Pone discard probabilities
            cond_probs = []
            for p_idx in range(num_pairs):
                pone_weight = pn_new_numerators[p_idx]
                if pone_weight > 0:
                    factor = get_card_removal_factor(d_pair, analytical_pairs[p_idx])
                    cond_probs.append((p_idx, pone_weight * factor))
                else:
                    cond_probs.append((p_idx, 0.0))

            total_cond_weight = sum(w for _, w in cond_probs)

            expected_score = 0.0
            for p_idx, cond_w in cond_probs:
                if cond_w > 0 and total_cond_weight > 0:
                    pone_prob = cond_w / total_cond_weight

                    if (d_idx, p_idx) in crib_scores:
                        for c in range(13):
                            # P(starter card c | d, p)
                            starter_prob = (
                                4 - d_pair.count(c) - analytical_pairs[p_idx].count(c)
                            ) / 48.0
                            expected_score += (
                                pone_prob
                                * starter_prob
                                * crib_scores[(d_idx, p_idx)][c]
                            )
            dl_next[d_idx] = expected_score

        # Pone discard policy expected crib
        # PnTbl[p] = sum_{d} Dealer_discard_prob[d | p] * ExpectedCrib[d, p]
        for p_idx in range(num_pairs):
            p_pair = analytical_pairs[p_idx]

            # Compute conditional Dealer discard probabilities
            cond_probs = []
            for d_idx in range(num_pairs):
                dealer_weight = dl_new_numerators[d_idx]
                if dealer_weight > 0:
                    factor = get_card_removal_factor(p_pair, analytical_pairs[d_idx])
                    cond_probs.append((d_idx, dealer_weight * factor))
                else:
                    cond_probs.append((d_idx, 0.0))

            total_cond_weight = sum(w for _, w in cond_probs)

            expected_score = 0.0
            for d_idx, cond_w in cond_probs:
                if cond_w > 0 and total_cond_weight > 0:
                    dealer_prob = cond_w / total_cond_weight

                    if (d_idx, p_idx) in crib_scores:
                        for c in range(13):
                            # P(starter card c | d, p)
                            starter_prob = (
                                4 - analytical_pairs[d_idx].count(c) - p_pair.count(c)
                            ) / 48.0
                            expected_score += (
                                dealer_prob
                                * starter_prob
                                * crib_scores[(d_idx, p_idx)][c]
                            )
            pn_next[p_idx] = expected_score

        # Apply dampening
        max_shift = 0.0
        for i in range(num_pairs):
            dl_shift = dampening * (dl_next[i] - dl_tbl[i])
            pn_shift = dampening * (pn_next[i] - pn_tbl[i])
            max_shift = max(max_shift, abs(dl_shift), abs(pn_shift))

            dl_tbl[i] += dl_shift
            pn_tbl[i] += pn_shift

        if max_shift < convergence_threshold:  # pragma: no cover
            print(f"IBR converged successfully in {iteration + 1} iterations.")
            break

        iteration += 1

    return dl_tbl, pn_tbl, hand_kept_evs, crib_scores


# pylint: disable=too-many-arguments,too-many-positional-arguments
def _evaluate_crib_expected_cut(player, d_idx, c, crib_scores, dl_probs, pn_probs):
    """Evaluate exact EV of the crib conditional on this cut card index c."""
    expected_crib_cut = 0.0
    if player == "Dealer":
        # Dealer gets expected value over Pone discards
        for p_idx, p_prob in enumerate(pn_probs):
            score_dict = crib_scores.get((d_idx, p_idx))
            if score_dict is not None:  # pragma: no cover
                expected_crib_cut += p_prob * score_dict[c]
    else:
        # Pone gets expected value over Dealer discards
        for d_index, d_prob in enumerate(dl_probs):
            score_dict = crib_scores.get((d_index, d_idx))
            if score_dict is not None:  # pragma: no cover
                expected_crib_cut += d_prob * score_dict[c]
    return expected_crib_cut


# pylint: disable=too-many-locals
def format_table_as_generation_zero(dl_tbl, pn_tbl, hands, crib_scores, true_nobs):
    """
    Format the 91-pair analytical tables into the exact 169 canonical
    suited/unsuited Generation 0 metadata structure expected by the generator.
    """
    # Mapping the 91-pair analytical matrices onto 169 canonical suited/unsuited
    # pairs requires nested rollups over absolute conditional opponent probabilities
    # to output the correct bootstrap formats cleanly and efficiently.
    analytical_pairs = get_analytical_pairs()
    canonical_pairs = get_canonical_pairs()

    # Pre-calculate Dealer/Pone absolute discard probability distributions
    # to evaluate exactly the expected crib value for a specific cut card.
    dl_probabilities = [0.0] * len(analytical_pairs)
    pn_probabilities = [0.0] * len(analytical_pairs)

    # 1. Evaluate optimum choices under converged tables
    for _, weight, discards_ev in hands:
        best_dl_idx = None
        best_dl_val = -float("inf")
        best_pn_idx = None
        best_pn_val = -float("inf")

        for p_idx, hand_ev in discards_ev.items():
            dl_val = hand_ev + dl_tbl[p_idx]
            if dl_val > best_dl_val:
                best_dl_val = dl_val
                best_dl_idx = p_idx

            pn_val = hand_ev - pn_tbl[p_idx]
            if pn_val > best_pn_val:
                best_pn_val = pn_val
                best_pn_idx = p_idx

        dl_probabilities[best_dl_idx] += weight
        pn_probabilities[best_pn_idx] += weight

    dl_total = sum(dl_probabilities)
    pn_total = sum(pn_probabilities)

    dl_probs = [w / dl_total for w in dl_probabilities]
    pn_probs = [w / pn_total for w in pn_probabilities]

    # 2. Build canonical table matching the exact generator JSON format
    output = {
        "__metadata__": {
            "generation_method": "artifact_pipeline.generate_table.v1",
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
                expected_crib_cut = _evaluate_crib_expected_cut(
                    player, d_idx, c, crib_scores, dl_probs, pn_probs
                )

                player_data[cut_rank_str] = {
                    "n": 0,
                    "mu": expected_crib_cut,
                    "se": 0.0,
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
        help="Use mathematically exact true Nobs EV (default: True).",
    )
    parser.add_argument(
        "--no-true-nobs",
        action="store_false",
        dest="true_nobs",
        help="Use Craig Hessel's flat 0.25 points Jack approximation.",
    )
    args = parser.parse_args()

    print(
        f"Starting generic suit-free analytical solver "
        f"(true-nobs={args.true_nobs})..."
    )
    dl_tbl, pn_tbl, hands, crib_scores = run_analytical_ibr(true_nobs=args.true_nobs)

    output_data = format_table_as_generation_zero(
        dl_tbl, pn_tbl, hands, crib_scores, args.true_nobs
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
