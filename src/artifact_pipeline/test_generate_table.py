import unittest
import math
import os
import json
from unittest.mock import patch

from src.artifact_pipeline.generate_table import (
    get_canonical_pairs,
    canonical_to_cards,
    run_monte_carlo,
    compute_statistics,
    main,
)


class TestGenerateTable(unittest.TestCase):
    def test_get_canonical_pairs(self):
        """Test that exactly 169 pairs are generated and formatted correctly."""
        pairs = get_canonical_pairs()
        NUM_CANONICAL_PAIRS = 169
        NUM_SAME_RANK = 13
        NUM_DIFF_RANK = 156
        self.assertEqual(len(pairs), NUM_CANONICAL_PAIRS)

        same_rank = [p for p in pairs if p.split('_')[0] == p.split('_')[1]]
        diff_rank = [p for p in pairs if p.split('_')[0] != p.split('_')[1]]

        self.assertEqual(len(same_rank), NUM_SAME_RANK)
        self.assertEqual(len(diff_rank), NUM_DIFF_RANK)

        for p in same_rank:
            self.assertTrue(p.endswith("_Unsuited"))

    def test_canonical_to_cards(self):
        """Test string to Card mapping."""
        # Suited
        c1, c2 = canonical_to_cards("A_2_Suited")
        self.assertEqual(c1.index, 0)
        self.assertEqual(c2.index, 1)
        self.assertEqual(c1.suit, 0)
        self.assertEqual(c2.suit, 0)

        # Unsuited
        c1, c2 = canonical_to_cards("5_T_Unsuited")
        self.assertEqual(c1.index, 4)
        self.assertEqual(c2.index, 9)
        self.assertEqual(c1.suit, 0)
        self.assertEqual(c2.suit, 1)

    def test_run_monte_carlo(self):
        """Test Monte Carlo simulation returns correct structure and types."""
        NUM_CUT_CARDS = 13
        TEST_SAMPLES = 1

        raw_scores = run_monte_carlo("A_A_Unsuited", "Dealer", TEST_SAMPLES)
        self.assertEqual(len(raw_scores), NUM_CUT_CARDS)

        total_scores = sum(len(scores) for scores in raw_scores.values())
        self.assertEqual(total_scores, TEST_SAMPLES)

    def test_compute_statistics(self):
        """Test variance tracking calculations."""
        # Empty
        res = compute_statistics([])
        self.assertEqual(res["mu"], 0.0)
        self.assertEqual(res["se"], 0.0)

        # Single element
        res = compute_statistics([5])
        self.assertEqual(res["mu"], 5.0)
        self.assertEqual(res["se"], 0.0)

        # Multiple elements
        res = compute_statistics([2, 4, 4, 4, 5, 5, 7, 9])
        self.assertEqual(res["mu"], 5.0)
        # sample var = sum((x-5)^2) / 7 = (9 + 1 + 1 + 1 + 0 + 0 + 4 + 16) / 7 = 32 / 7 = 4.5714...
        # std dev = sqrt(32/7) = 2.138
        # std err = std dev / sqrt(8) = 2.138 / 2.828 = 0.7559
        expected_se = math.sqrt((32 / 7)) / math.sqrt(8)
        self.assertAlmostEqual(res["se"], expected_se)

    @patch('sys.argv', ['generate_table.py', '--samples', '1'])
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
        self.assertIn("A_A_Unsuited", data)
        self.assertIn("Dealer", data["A_A_Unsuited"])
        self.assertIn("Pone", data["A_A_Unsuited"])
        self.assertIn("A", data["A_A_Unsuited"]["Dealer"])

        os.remove("expected_crib_points.json")


if __name__ == '__main__':
    unittest.main()
