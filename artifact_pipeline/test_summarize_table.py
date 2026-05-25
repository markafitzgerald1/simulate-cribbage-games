import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from artifact_pipeline.summarize_table import (
    build_table,
    combine_estimates,
    combine_suit_estimates,
    format_value,
    get_pair_estimate,
    get_pair_stat,
    main,
    mean,
    mean_cut_stat,
    parse_args,
    pool_cut_estimate,
    print_csv_table,
    print_markdown_table,
)


class TestSummarizeTable(unittest.TestCase):  # pylint: disable=too-many-public-methods
    def test_mean(self):
        self.assertIsNone(mean([]))
        self.assertEqual(mean([2.0, 4.0]), 3.0)

    def test_mean_cut_stat(self):
        cut_stats = {
            "A": {"mu": 4.0, "se": 1.0},
            "2": {"mu": 6.0},
            "3": {"se": 3.0},
        }
        self.assertEqual(mean_cut_stat(cut_stats, "mu"), 5.0)
        self.assertEqual(mean_cut_stat(cut_stats, "se"), 2.0)

    def test_pool_cut_estimate_with_sample_counts(self):
        cut_stats = {
            "A": {"n": 2, "mu": 3.0, "se": 1.0},
            "2": {"n": 1, "mu": 9.0, "se": 0.0},
        }

        estimate = pool_cut_estimate(cut_stats)

        self.assertEqual(estimate["n"], 3)
        self.assertEqual(estimate["mu"], 5.0)
        self.assertAlmostEqual(estimate["se"], (13 / 3) ** 0.5)

    def test_pool_cut_estimate_empty(self):
        self.assertIsNone(pool_cut_estimate({"A": {"se": 1.0}}))

    def test_pool_cut_estimate_without_sample_counts(self):
        cut_stats = {
            "A": {"mu": 4.0, "se": 1.0},
            "2": {"mu": 6.0, "se": 1.0},
        }

        estimate = pool_cut_estimate(cut_stats)

        self.assertEqual(estimate["n"], 2)
        self.assertEqual(estimate["mu"], 5.0)
        self.assertAlmostEqual(estimate["se"], 0.5**0.5)

    def test_combine_estimates(self):
        combined = combine_estimates(
            (
                (0.25, {"n": 4, "mu": 8.0, "se": 2.0}),
                (0.75, {"n": 4, "mu": 4.0, "se": 2.0}),
            )
        )

        self.assertEqual(combined["mu"], 5.0)
        self.assertAlmostEqual(combined["se"], (0.25**2 * 4 + 0.75**2 * 4) ** 0.5)

    def test_combine_estimates_empty(self):
        self.assertIsNone(combine_estimates(()))

    def test_combine_suit_estimates_with_missing_unsuited_actual_is_incomplete(self):
        estimate = {"n": 1, "mu": 8.0, "se": 0.0}

        self.assertIsNone(combine_suit_estimates(estimate, None, "actual"))

    def test_combine_suit_estimates_with_missing_unsuited_suited_only(self):
        estimate = {"n": 1, "mu": 8.0, "se": 0.0}

        self.assertEqual(
            combine_suit_estimates(estimate, None, "suited-only"), estimate
        )

    def test_get_pair_stat_same_rank(self):
        data = {
            "A_A_Unsuited": {
                "Dealer": {"A": {"n": 1, "mu": 5.0}, "2": {"n": 1, "mu": 7.0}}
            }
        }

        self.assertEqual(get_pair_stat(data, ("A", "A"), "Dealer", "mu", "actual"), 6.0)

    def test_get_pair_stat_same_rank_suited_only_is_impossible(self):
        data = {
            "A_A_Unsuited": {
                "Dealer": {"A": {"n": 1, "mu": 5.0}, "2": {"n": 1, "mu": 7.0}}
            }
        }

        self.assertIsNone(
            get_pair_stat(data, ("A", "A"), "Dealer", "mu", "suited-only")
        )

    def test_get_pair_stat_actual_suit_weighting(self):
        data = {
            "A_2_Suited": {"Dealer": {"A": {"n": 1, "mu": 8.0}}},
            "A_2_Unsuited": {"Dealer": {"A": {"n": 1, "mu": 4.0}}},
        }

        self.assertEqual(get_pair_stat(data, ("A", "2"), "Dealer", "mu", "actual"), 5.0)

    def test_get_pair_stat_other_suit_weighting(self):
        data = {
            "A_2_Suited": {"Dealer": {"A": {"n": 1, "mu": 8.0}}},
            "A_2_Unsuited": {"Dealer": {"A": {"n": 1, "mu": 4.0}}},
        }

        self.assertEqual(
            get_pair_stat(data, ("A", "2"), "Dealer", "mu", "unweighted"), 6.0
        )
        self.assertEqual(
            get_pair_stat(data, ("A", "2"), "Dealer", "mu", "suited-only"), 8.0
        )
        self.assertEqual(
            get_pair_stat(data, ("A", "2"), "Dealer", "mu", "unsuited-only"), 4.0
        )

    def test_get_pair_estimate_includes_pooled_se(self):
        data = {
            "A_2_Suited": {"Dealer": {"A": {"n": 4, "mu": 8.0, "se": 2.0}}},
            "A_2_Unsuited": {"Dealer": {"A": {"n": 4, "mu": 4.0, "se": 2.0}}},
        }

        estimate = get_pair_estimate(data, "A", "2", "Dealer", "actual")

        self.assertEqual(estimate["mu"], 5.0)
        self.assertAlmostEqual(estimate["se"], (0.25**2 * 4 + 0.75**2 * 4) ** 0.5)

    def test_build_table_shows_each_discard_pair_once(self):
        data = {
            "A_A_Unsuited": {"Dealer": {"A": {"n": 1, "mu": 1.0}}},
            "A_2_Suited": {"Dealer": {"A": {"n": 1, "mu": 5.0}}},
            "A_2_Unsuited": {"Dealer": {"A": {"n": 1, "mu": 5.0}}},
            "2_2_Unsuited": {"Dealer": {"A": {"n": 1, "mu": 2.0}}},
        }

        table = build_table(data, "Dealer", "actual")

        self.assertEqual(table[0][0]["mu"], 1.0)
        self.assertIsNone(table[0][1])
        self.assertEqual(table[1][0]["mu"], 5.0)
        self.assertEqual(table[1][1]["mu"], 2.0)

    def test_format_value(self):
        self.assertEqual(format_value(None, "mu", 2, False), "")
        self.assertEqual(format_value({"mu": 1.234}, "mu", 2, False), "1.23")
        self.assertEqual(
            format_value({"mu": 1.234, "se": 0.567}, "mu", 2, True),
            "1.23 +/- 0.57",
        )
        self.assertEqual(format_value({"n": 12.5}, "n", 2, False), "12")
        self.assertEqual(
            format_value({"mu": 1.13}, "mu", 2, False, round_to=0.25), "1.25"
        )
        self.assertEqual(
            format_value({"mu": 1.12}, "mu", 2, False, round_to=0.25), "1.00"
        )

    def test_print_markdown_table(self):
        table = [[{"mu": 1.0, "se": 0.25}]]
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            print_markdown_table(table, "mu", 2, True)

        output = stdout.getvalue()
        self.assertTrue("|     |" in output)
        self.assertTrue("1.00 +/- 0.25" in output)
        self.assertTrue("| --- |" in output)

    def test_print_csv_table(self):
        table = [[{"mu": 1.0, "se": 0.25}]]
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            print_csv_table(table, "mu", 2, False)

        output = stdout.getvalue()
        self.assertTrue(output.startswith(",A,2,3,4,5,6,7,8,9,T,J,Q,K"))
        self.assertTrue("A,1.00" in output)

    @patch("sys.argv", ["summarize_table.py", "--role", "Dealer"])
    def test_parse_args_defaults(self):
        args = parse_args()

        self.assertEqual(args.path, "expected_crib_points.json")
        self.assertEqual(args.role, "Dealer")
        self.assertEqual(args.statistic, "mu")
        self.assertEqual(args.format, "markdown")
        self.assertEqual(args.precision, 2)
        self.assertEqual(args.suit_weighting, "actual")
        self.assertFalse(args.show_se)
        self.assertIsNone(args.round_to)

    def test_main_prints_markdown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")
            with open(output_path, "w", encoding="utf-8") as output_file:
                json.dump(
                    {"A_A_Unsuited": {"Dealer": {"A": {"n": 1, "mu": 5.0}}}},
                    output_file,
                )

            with patch(
                "sys.argv",
                ["summarize_table.py", "--role", "Dealer", output_path],
            ), patch("sys.stdout", new_callable=io.StringIO) as stdout:
                main()

        self.assertTrue("5.00" in stdout.getvalue())

    def test_main_prints_csv(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")
            with open(output_path, "w", encoding="utf-8") as output_file:
                json.dump(
                    {"A_A_Unsuited": {"Dealer": {"A": {"n": 1, "mu": 5.0}}}},
                    output_file,
                )

            with patch(
                "sys.argv",
                [
                    "summarize_table.py",
                    "--role",
                    "Dealer",
                    "--format",
                    "csv",
                    output_path,
                ],
            ), patch("sys.stdout", new_callable=io.StringIO) as stdout:
                main()

        self.assertTrue(stdout.getvalue().startswith(",A,2,3,4,5,6,7,8,9,T,J,Q,K"))


if __name__ == "__main__":
    unittest.main()
