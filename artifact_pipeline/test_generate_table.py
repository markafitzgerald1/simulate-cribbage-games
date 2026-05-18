import unittest
import math
import os
import json
import random
import tempfile
from unittest.mock import patch

import argparse
from artifact_pipeline.generate_table import (
    accumulator_to_statistics,
    get_canonical_pairs,
    canonical_to_cards,
    run_monte_carlo,
    compute_statistics,
    statistics_to_accumulator,
    main,
    positive_int,
)


class TestGenerateTable(unittest.TestCase):
    def test_get_canonical_pairs(self):
        """Test that exactly 169 pairs are generated and formatted correctly."""
        pairs = get_canonical_pairs()
        num_canonical_pairs = 169
        num_same_rank = 13
        num_diff_rank = 156
        self.assertEqual(len(pairs), num_canonical_pairs)

        same_rank = [pair for pair in pairs if pair.split("_")[0] == pair.split("_")[1]]
        diff_rank = [pair for pair in pairs if pair.split("_")[0] != pair.split("_")[1]]

        self.assertEqual(len(same_rank), num_same_rank)
        self.assertEqual(len(diff_rank), num_diff_rank)

        for pair in same_rank:
            self.assertTrue(pair.endswith("_Unsuited"))

    def test_canonical_to_cards(self):
        """Test string to Card mapping."""
        ace_index = 0
        two_index = 1
        five_index = 4
        ten_index = 9
        suit_clubs = 0
        suit_diamonds = 1

        # Suited
        card_1, card_2 = canonical_to_cards("A_2_Suited")
        self.assertEqual(card_1.index, ace_index)
        self.assertEqual(card_2.index, two_index)
        self.assertEqual(card_1.suit, suit_clubs)
        self.assertEqual(card_2.suit, suit_clubs)

        # Unsuited
        card_1, card_2 = canonical_to_cards("5_T_Unsuited")
        self.assertEqual(card_1.index, five_index)
        self.assertEqual(card_2.index, ten_index)
        self.assertEqual(card_1.suit, suit_clubs)
        self.assertEqual(card_2.suit, suit_diamonds)

    def test_run_monte_carlo(self):
        """Test Monte Carlo simulation returns correct structure and types."""
        num_cut_cards = 13
        test_samples = 1

        rng = random.Random(42)

        raw_scores = run_monte_carlo("A_A_Unsuited", "Dealer", test_samples, rng)
        self.assertEqual(len(raw_scores), num_cut_cards)

        total_scores = sum(len(scores) for scores in raw_scores.values())
        self.assertEqual(total_scores, test_samples)

    def test_compute_statistics(self):
        """Test variance tracking calculations."""
        expected_mu_single = 5.0
        expected_se_zero = 0.0
        expected_mu_multi = 5.0
        variance_numerator = 32
        degrees_of_freedom = 7
        sample_size = 8

        # Empty
        res = compute_statistics([])
        self.assertIsNone(res)

        # Single element
        res = compute_statistics([5])
        self.assertEqual(res["n"], 1)
        self.assertEqual(res["mu"], expected_mu_single)
        self.assertEqual(res["se"], expected_se_zero)

        # Multiple elements
        res = compute_statistics([2, 4, 4, 4, 5, 5, 7, 9])
        self.assertEqual(res["n"], sample_size)
        self.assertEqual(res["mu"], expected_mu_multi)
        expected_se = math.sqrt((variance_numerator / degrees_of_freedom)) / math.sqrt(
            sample_size
        )
        self.assertAlmostEqual(res["se"], expected_se)

    def test_statistics_accumulator_round_trip(self):
        statistics = compute_statistics([2, 4, 6])

        accumulator = statistics_to_accumulator(statistics)
        round_tripped = accumulator_to_statistics(accumulator)

        self.assertEqual(round_tripped["n"], statistics["n"])
        self.assertAlmostEqual(round_tripped["mu"], statistics["mu"])
        self.assertAlmostEqual(round_tripped["se"], statistics["se"])

    def test_canonical_to_cards_errors(self):
        """Test error conditions in canonical_to_cards."""
        with self.assertRaises(ValueError):
            canonical_to_cards("A_2")
        with self.assertRaises(ValueError):
            canonical_to_cards("X_2_Suited")
        with self.assertRaises(ValueError):
            canonical_to_cards("A_X_Suited")
        with self.assertRaises(ValueError):
            canonical_to_cards("A_2_Invalid")
        with self.assertRaises(ValueError):
            canonical_to_cards("A_A_Suited")

    def test_run_monte_carlo_errors(self):
        """Test error conditions in run_monte_carlo."""
        rng = random.Random(42)
        with self.assertRaises(ValueError):
            run_monte_carlo("A_A_Unsuited", "InvalidPlayer", 1, rng)

    def test_positive_int(self):
        """Test positive_int logic."""
        self.assertEqual(positive_int("5"), 5)
        with self.assertRaises(argparse.ArgumentTypeError):
            positive_int("0")
        with self.assertRaises(argparse.ArgumentTypeError):
            positive_int("-1")

    @patch("sys.argv", ["generate_table.py", "--samples", "1", "--seed", "42"])
    def test_main(self):
        """Test main integration generates file successfully."""
        if os.path.exists("expected_crib_points.json"):
            os.remove("expected_crib_points.json")

        main()

        self.assertTrue(os.path.exists("expected_crib_points.json"))

        with open("expected_crib_points.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        num_canonical_pairs = 169
        self.assertEqual(len(data), num_canonical_pairs)
        self.assertTrue("A_A_Unsuited" in data)
        self.assertTrue("Dealer" in data["A_A_Unsuited"])
        self.assertTrue("Pone" in data["A_A_Unsuited"])

        # Because we're only doing 1 sample, only 1 cut card will be present.
        # Find which cut card was selected and assert it's valid.
        cut_cards_present = list(data["A_A_Unsuited"]["Dealer"].keys())
        self.assertEqual(len(cut_cards_present), 1)
        self.assertTrue(cut_cards_present[0] in "A23456789TJQK")
        self.assertEqual(data["A_A_Unsuited"]["Dealer"][cut_cards_present[0]]["n"], 1)

        os.remove("expected_crib_points.json")

    @patch("sys.argv", ["generate_table.py", "--samples", "1"])
    def test_main_no_seed(self):
        """Test main integration generates file successfully without seed."""
        if os.path.exists("expected_crib_points.json"):
            os.remove("expected_crib_points.json")

        main()

        self.assertTrue(os.path.exists("expected_crib_points.json"))
        os.remove("expected_crib_points.json")

    def test_main_resumes_existing_output(self):
        """Test main resumes from a prior checkpoint."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "1",
                    "--seed",
                    "42",
                    "--output",
                    output_path,
                    "--no-resume",
                ],
            ):
                main()

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "2",
                    "--seed",
                    "43",
                    "--output",
                    output_path,
                ],
            ):
                main()

            with open(output_path, "r", encoding="utf-8") as output_file:
                data = json.load(output_file)

            total_samples = sum(
                stats["n"] for stats in data["A_A_Unsuited"]["Dealer"].values()
            )
            self.assertEqual(total_samples, 2)

    def test_main_reaches_target_across_multiple_checkpoints(self):
        """Test finite runs continue until the cumulative sample target."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "2",
                    "--checkpoint-frequency",
                    "1",
                    "--seed",
                    "42",
                    "--output",
                    output_path,
                    "--no-resume",
                ],
            ):
                main()

            with open(output_path, "r", encoding="utf-8") as output_file:
                data = json.load(output_file)

            total_samples = sum(
                stats["n"] for stats in data["A_A_Unsuited"]["Dealer"].values()
            )
            self.assertEqual(total_samples, 2)

    def test_seeded_resume_matches_fresh_seeded_run(self):
        """Test seeded resume continues the deterministic sample sequence."""
        with tempfile.TemporaryDirectory() as temp_dir:
            resumed_output_path = os.path.join(temp_dir, "resumed.json")
            fresh_output_path = os.path.join(temp_dir, "fresh.json")

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "1",
                    "--seed",
                    "42",
                    "--output",
                    resumed_output_path,
                    "--no-resume",
                ],
            ):
                main()

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "2",
                    "--seed",
                    "42",
                    "--output",
                    resumed_output_path,
                ],
            ):
                main()

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "2",
                    "--seed",
                    "42",
                    "--output",
                    fresh_output_path,
                    "--no-resume",
                ],
            ):
                main()

            with open(resumed_output_path, "r", encoding="utf-8") as resumed_file:
                resumed_data = json.load(resumed_file)
            with open(fresh_output_path, "r", encoding="utf-8") as fresh_file:
                fresh_data = json.load(fresh_file)

            self.assertEqual(resumed_data, fresh_data)


if __name__ == "__main__":
    unittest.main()
