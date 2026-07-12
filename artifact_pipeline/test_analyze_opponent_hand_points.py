"""Tests for the issue 75 opponent hand-points analysis."""

import argparse
import json
import math
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artifact_pipeline.analytical_solver import (
    get_card_removal_weight,
    get_hand_combinations_with_weights,
    score_combination_suit_free,
)
from artifact_pipeline.analyze_opponent_hand_points import (
    CONDITIONED_OPPONENT_DEALS,
    DEALER,
    PHYSICAL_SIX_CARD_DEALS,
    PONE,
    PolicySubsetAggregate,
    REPRESENTATIVE_PHYSICAL_DEALS,
    SampleMoments,
    _parse_args,
    _physical_sample_seed,
    _rank_table_sizes,
    _sample_rank_policy_keep,
    _normalized_size_projections,
    analyze,
    build_policy_subset_aggregates,
    canonical_suit_key,
    conditioned_suitless_expected_values,
    exact_suitless_table,
    main,
    nonnegative_int,
    physical_deal_key,
    positive_int,
    rank_hand_key,
    sample_suit_aware_hand_points,
    suit_normalized_six_card_state_count,
)
from artifact_pipeline.generate_play_table import DiscardPolicy


def first_four_policy():
    """Return a deterministic policy for every valid six-rank hand."""
    mapping = {}
    for hand, _weight in get_hand_combinations_with_weights():
        for role in (PONE, DEALER):
            mapping[(role, hand)] = hand[:4]
    return DiscardPolicy(mapping)


class TestOpponentHandPointAnalysis(unittest.TestCase):
    """Exercise exact, physical, sizing, and command paths."""

    @classmethod
    def setUpClass(cls):
        cls.policy = first_four_policy()
        cls.hands = get_hand_combinations_with_weights()
        cls.aggregates = build_policy_subset_aggregates(cls.policy, cls.hands)

    def test_integer_parsers(self):
        self.assertEqual(positive_int("2"), 2)
        self.assertEqual(nonnegative_int("0"), 0)
        with self.assertRaises(argparse.ArgumentTypeError):
            positive_int("0")
        with self.assertRaises(argparse.ArgumentTypeError):
            nonnegative_int("-1")

    def test_canonical_suit_key_normalizes_global_renaming(self):
        clubs_diamonds = ((0, 0), (1, 0), (2, 0), (3, 0), (4, 1), (5, 1))
        hearts_spades = ((0, 2), (1, 2), (2, 2), (3, 2), (4, 3), (5, 3))
        different_incidence = ((0, 0), (1, 0), (2, 0), (3, 1), (4, 0), (5, 1))
        self.assertEqual(
            canonical_suit_key(clubs_diamonds), canonical_suit_key(hearts_spades)
        )
        self.assertNotEqual(
            canonical_suit_key(clubs_diamonds), canonical_suit_key(different_incidence)
        )
        with self.assertRaises(ValueError):
            canonical_suit_key(((0, 0), (0, 0)))
        with self.assertRaises(ValueError):
            canonical_suit_key(((13, 0),))

    def test_burnside_state_count(self):
        self.assertEqual(PHYSICAL_SIX_CARD_DEALS, 20_358_520)
        self.assertEqual(suit_normalized_six_card_state_count(), 962_988)

    def test_streaming_sample_moments(self):
        empty = SampleMoments()
        self.assertEqual(empty.standard_deviation, 0.0)
        self.assertTrue(math.isinf(empty.standard_error))
        empty.add(2.0)
        self.assertEqual(empty.standard_deviation, 0.0)
        empty.add(4.0)
        self.assertAlmostEqual(empty.mean, 3.0)
        self.assertAlmostEqual(empty.standard_error, 1.0)

    def test_conditioned_exact_value_matches_direct_enumeration(self):
        known = (0, 1, 2, 3, 4, 5)
        actual = conditioned_suitless_expected_values(known, self.aggregates)
        direct_totals = {PONE: 0.0, DEALER: 0.0}
        direct_weight = 0
        for hand, _weight in self.hands:
            weight = get_card_removal_weight(known, hand)
            if not weight:
                continue
            direct_weight += weight
            for role in (PONE, DEALER):
                kept = self.policy.kept_ranks(role, hand)
                direct_totals[role] += weight * sum(
                    (4 - known.count(rank) - hand.count(rank))
                    * score_combination_suit_free(kept, rank)
                    for rank in range(13)
                )
        self.assertEqual(direct_weight, CONDITIONED_OPPONENT_DEALS)
        for role in (PONE, DEALER):
            self.assertAlmostEqual(
                actual[role], direct_totals[role] / (direct_weight * 40)
            )

    def test_conditioned_value_rejects_incomplete_aggregates(self):
        incomplete = dict(self.aggregates)
        incomplete[()] = PolicySubsetAggregate()
        with self.assertRaisesRegex(ValueError, "conditioned opponent deal count"):
            conditioned_suitless_expected_values(
                (0, 1, 2, 3, 4, 5),
                incomplete,
            )

    def test_exact_table_keys_and_limit(self):
        with patch(
            "artifact_pipeline.analyze_opponent_hand_points.build_policy_subset_aggregates",
            return_value=self.aggregates,
        ):
            table = exact_suitless_table(self.policy, hand_limit=2)
        self.assertEqual(len(table), 2)
        self.assertEqual(next(iter(table)), "A_A_A_A_2_2")
        self.assertEqual(rank_hand_key((0, 9, 10, 11, 12)), "A_T_J_Q_K")

    def test_rank_policy_suit_selection_and_physical_sampling(self):
        dealt = ((0, 0), (0, 1), (1, 0), (2, 0), (3, 0), (4, 0))
        keep = _sample_rank_policy_keep(self.policy, PONE, dealt, random.Random(42))
        self.assertEqual(len(keep), 4)
        first_name, known = REPRESENTATIVE_PHYSICAL_DEALS[0]
        seed = _physical_sample_seed(42, first_name, PONE)
        first = sample_suit_aware_hand_points(known, PONE, self.policy, 5, seed)
        second = sample_suit_aware_hand_points(known, PONE, self.policy, 5, seed)
        self.assertEqual(
            (first.n, first.mean, first.moment_2), (5, second.mean, second.moment_2)
        )
        with self.assertRaisesRegex(ValueError, "six unique"):
            sample_suit_aware_hand_points(known[:5], PONE, self.policy, 1, seed)

    def test_keys_and_size_projections(self):
        self.assertEqual(physical_deal_key(((0, 0), (12, 3))), "A0_K3")
        table = {
            "A_2_3_4_5_6": {PONE: 4.0, DEALER: 5.0},
            "8_9_T_J_Q_K": {PONE: 6.0, DEALER: 7.0},
        }
        sizes = _rank_table_sizes(table)
        self.assertGreater(sizes["minified_json_bytes"], 0)
        self.assertGreater(sizes["gzip_bytes"], 0)
        self.assertEqual(sizes["packed_float32_value_bytes"], 16)
        projected = _normalized_size_projections(table, 10)
        self.assertEqual(projected["packed_float32_value_bytes"], 80)
        self.assertEqual(projected["quantized_int16_residual_bytes"], 40)
        self.assertEqual(projected["rank_float32_plus_quantized_residual_bytes"], 56)

    def test_analysis_report_with_and_without_physical_pilot(self):
        table = {
            rank_hand_key(sorted(card[0] for card in known)): {
                PONE: float(index + 4),
                DEALER: float(index + 5),
            }
            for index, (_name, known) in enumerate(REPRESENTATIVE_PHYSICAL_DEALS)
        }
        moments = SampleMoments()
        moments.add(5.0)
        moments.add(7.0)
        with patch(
            "artifact_pipeline.analyze_opponent_hand_points.exact_suitless_table",
            return_value=table,
        ), patch(
            "artifact_pipeline.analyze_opponent_hand_points.sample_suit_aware_hand_points",
            return_value=moments,
        ):
            report = analyze(self.policy, None, 2, 42)
            without_pilot = analyze(self.policy, 1, 0, 42)
        one_entry = {next(iter(table)): next(iter(table.values()))}
        with patch(
            "artifact_pipeline.analyze_opponent_hand_points.exact_suitless_table",
            return_value=one_entry,
        ), patch(
            "artifact_pipeline.analyze_opponent_hand_points.sample_suit_aware_hand_points",
            return_value=moments,
        ):
            partial_pilot = analyze(self.policy, 1, 2, 42)
        self.assertFalse(
            report["discard_invariance"]["opponent_ev_varies_across_user_discards"]
        )
        self.assertEqual(report["suit_aware_pilot"]["deal_count"], 6)
        self.assertEqual(without_pilot["suit_aware_pilot"]["deal_count"], 0)
        self.assertGreater(partial_pilot["suit_aware_pilot"]["deal_count"], 0)
        self.assertLess(partial_pilot["suit_aware_pilot"]["deal_count"], 6)
        self.assertTrue("defer" in report["recommendation"])

    def test_parse_args_and_main_output_paths(self):
        args = _parse_args(
            [
                "--hand-limit=2",
                "--physical-samples=0",
                "--seed=7",
                "--analytical-max-iterations=2",
                "--full-hand-policy-max-iterations=1",
            ]
        )
        self.assertEqual((args.hand_limit, args.physical_samples, args.seed), (2, 0, 7))
        context = type("Context", (), {"selected_discards": []})()
        report = {"recommendation": "defer"}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            with patch(
                "artifact_pipeline.analyze_opponent_hand_points.solve_initial_discard_policy",
                return_value=context,
            ), patch(
                "artifact_pipeline.analyze_opponent_hand_points.selected_discards_to_policy",
                return_value=self.policy,
            ), patch(
                "artifact_pipeline.analyze_opponent_hand_points.analyze",
                return_value=report,
            ):
                self.assertEqual(main(["--output", str(output)]), 0)
                written = json.loads(output.read_text())
                self.assertEqual(written["recommendation"], "defer")
                self.assertGreaterEqual(written["policy_solve_elapsed_seconds"], 0.0)
                self.assertGreaterEqual(written["total_elapsed_seconds"], 0.0)
                self.assertEqual(main([]), 0)


if __name__ == "__main__":
    unittest.main()
