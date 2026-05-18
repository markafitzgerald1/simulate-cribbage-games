import unittest
import math
import os
import json
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
        NUM_CANONICAL_PAIRS = 169
        NUM_SAME_RANK = 13
        NUM_DIFF_RANK = 156
        self.assertEqual(len(pairs), NUM_CANONICAL_PAIRS)

        same_rank = [pair for pair in pairs if pair.split("_")[0] == pair.split("_")[1]]
        diff_rank = [pair for pair in pairs if pair.split("_")[0] != pair.split("_")[1]]

        self.assertEqual(len(same_rank), NUM_SAME_RANK)
        self.assertEqual(len(diff_rank), NUM_DIFF_RANK)

        for pair in same_rank:
            self.assertTrue(pair.endswith("_Unsuited"))

    def test_canonical_to_cards(self):
        """Test string to Card mapping."""
        ACE_INDEX = 0
        TWO_INDEX = 1
        FIVE_INDEX = 4
        TEN_INDEX = 9
        SUIT_CLUBS = 0
        SUIT_DIAMONDS = 1

        # Suited
        card_1, card_2 = canonical_to_cards("A_2_Suited")
        self.assertEqual(card_1.index, ACE_INDEX)
        self.assertEqual(card_2.index, TWO_INDEX)
        self.assertEqual(card_1.suit, SUIT_CLUBS)
        self.assertEqual(card_2.suit, SUIT_CLUBS)

        # Unsuited
        card_1, card_2 = canonical_to_cards("5_T_Unsuited")
        self.assertEqual(card_1.index, FIVE_INDEX)
        self.assertEqual(card_2.index, TEN_INDEX)
        self.assertEqual(card_1.suit, SUIT_CLUBS)
        self.assertEqual(card_2.suit, SUIT_DIAMONDS)

    def test_run_monte_carlo(self):
        """Test Monte Carlo simulation returns correct structure and types."""
        NUM_CUT_CARDS = 13
        TEST_SAMPLES = 1
        import random

        rng = random.Random(42)

        raw_scores = run_monte_carlo("A_A_Unsuited", "Dealer", TEST_SAMPLES, rng)
        self.assertEqual(len(raw_scores), NUM_CUT_CARDS)

        total_scores = sum(len(scores) for scores in raw_scores.values())
        self.assertEqual(total_scores, TEST_SAMPLES)

    def test_compute_statistics(self):
        """Test variance tracking calculations."""
        EXPECTED_MU_SINGLE = 5.0
        EXPECTED_SE_ZERO = 0.0
        EXPECTED_MU_MULTI = 5.0
        VARIANCE_NUMERATOR = 32
        DEGREES_OF_FREEDOM = 7
        SAMPLE_SIZE = 8

        # Empty
        res = compute_statistics([])
        self.assertIsNone(res)

        # Single element
        res = compute_statistics([5])
        self.assertEqual(res["n"], 1)
        self.assertEqual(res["mu"], EXPECTED_MU_SINGLE)
        self.assertEqual(res["se"], EXPECTED_SE_ZERO)

        # Multiple elements
        res = compute_statistics([2, 4, 4, 4, 5, 5, 7, 9])
        self.assertEqual(res["n"], SAMPLE_SIZE)
        self.assertEqual(res["mu"], EXPECTED_MU_MULTI)
        expected_se = math.sqrt((VARIANCE_NUMERATOR / DEGREES_OF_FREEDOM)) / math.sqrt(
            SAMPLE_SIZE
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
        import random

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

        with open("expected_crib_points.json", "r") as f:
            data = json.load(f)

        NUM_CANONICAL_PAIRS = 169
        self.assertEqual(len(data), NUM_CANONICAL_PAIRS)
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

            with open(output_path, "r") as output_file:
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

            with open(output_path, "r") as output_file:
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

            with open(resumed_output_path, "r") as resumed_file:
                resumed_data = json.load(resumed_file)
            with open(fresh_output_path, "r") as fresh_file:
                fresh_data = json.load(fresh_file)

            self.assertEqual(resumed_data, fresh_data)


if __name__ == "__main__":
    unittest.main()
