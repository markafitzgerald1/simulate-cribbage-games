import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from artifact_pipeline.compare_hessel import (
    compare_to_hessel,
    iter_rank_pairs,
    main,
    print_markdown_table,
    roles_from_arg,
    sorted_rows,
    summarize_rows,
    threshold_failed,
)
from artifact_pipeline.hessel import HESSEL_AVERAGES


def write_table(path, role_data):
    with open(path, "w", encoding="utf-8") as output_file:
        json.dump({"A_A_Unsuited": role_data}, output_file)


def run_main_with_single_dealer_table(output_path, *args):
    write_table(
        output_path,
        {"Dealer": {"A": {"n": 1, "mu": 5.26, "se": 0.0}}},
    )
    argv = ["compare_hessel.py", "--role", "Dealer", *args, output_path]
    with patch("sys.argv", argv), patch(
        "sys.stdout", new_callable=io.StringIO
    ) as stdout:
        main()
    return stdout.getvalue()


def comparison_row(pair="AA", abs_delta=0.2, z_score=2.0, delta=0.2):
    return {
        "pair": pair,
        "role": "Dealer",
        "generated": 5.46,
        "hessel": 5.26,
        "delta": delta,
        "abs_delta": abs_delta,
        "se": 0.1,
        "z_score": z_score,
        "n": 4.0,
    }


class TestCompareHessel(unittest.TestCase):
    def test_reference_table_has_all_rank_pairs(self):
        self.assertEqual(len(HESSEL_AVERAGES), 91)
        self.assertEqual(set(HESSEL_AVERAGES), set(iter_rank_pairs()))

    def test_compare_to_hessel(self):
        data = {
            "A_A_Unsuited": {
                "Dealer": {"A": {"n": 4, "mu": 5.46, "se": 0.1}},
                "Pone": {"A": {"n": 4, "mu": 6.17, "se": 0.2}},
            }
        }

        rows = compare_to_hessel(data, ("Dealer", "Pone"), "actual")

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["pair"], "AA")
        self.assertEqual(rows[0]["role"], "Dealer")
        self.assertAlmostEqual(rows[0]["delta"], 0.2)
        self.assertAlmostEqual(rows[0]["z_score"], 2.0)
        self.assertEqual(rows[1]["role"], "Pone")
        self.assertAlmostEqual(rows[1]["delta"], 0.1)

    def test_summarize_rows(self):
        summary = summarize_rows(
            [
                comparison_row(delta=0.2, abs_delta=0.2, z_score=2.0),
                comparison_row(delta=-0.1, abs_delta=0.1, z_score=1.0),
            ]
        )

        self.assertEqual(summary["count"], 2.0)
        self.assertAlmostEqual(summary["mean_delta"], 0.05)
        self.assertAlmostEqual(summary["mean_abs_delta"], 0.15)
        self.assertAlmostEqual(summary["max_abs_delta"], 0.2)

    def test_summarize_rows_empty(self):
        summary = summarize_rows([])

        self.assertEqual(summary["count"], 0)
        self.assertEqual(summary["max_abs_delta"], 0.0)

    def test_sorted_rows(self):
        rows = [
            comparison_row(pair="AA", abs_delta=0.1, z_score=3.0),
            comparison_row(pair="A2", abs_delta=0.3, z_score=1.0),
        ]

        self.assertEqual(
            [row["pair"] for row in sorted_rows(rows, "rank")],
            ["AA", "A2"],
        )
        self.assertEqual(
            [row["pair"] for row in sorted_rows(rows, "abs-delta")],
            ["A2", "AA"],
        )
        self.assertEqual(
            [row["pair"] for row in sorted_rows(rows, "z-score")],
            ["AA", "A2"],
        )

    def test_roles_from_arg(self):
        self.assertEqual(roles_from_arg("Dealer"), ("Dealer",))
        self.assertEqual(roles_from_arg("Pone"), ("Pone",))
        self.assertEqual(roles_from_arg("both"), ("Dealer", "Pone"))

    def test_threshold_failed(self):
        summary = {"max_abs_delta": 0.2, "max_z_score": 3.0}

        self.assertFalse(threshold_failed(summary, 0.2, 3.0))
        self.assertTrue(threshold_failed(summary, 0.1, None))
        self.assertTrue(threshold_failed(summary, None, 2.9))

    def test_print_markdown_table(self):
        rows = [comparison_row(delta=0.1, z_score=2.0)]

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            print_markdown_table(rows, ("Dealer",), "delta", 2)

        output = stdout.getvalue()
        self.assertTrue("Dealer delta" in output)
        self.assertTrue("| A | 0.10 |" in output)
        self.assertTrue("| - | ---- |" in output)

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            print_markdown_table(rows, ("Dealer",), "z-score", 2)
        self.assertTrue("| A | 2.00 |" in stdout.getvalue())

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            print_markdown_table(rows, ("Dealer",), "n", 2)
        self.assertTrue("| A | 4 |" in stdout.getvalue())

        for statistic, expected in (
            ("generated", "| A | 5.46 |"),
            ("hessel", "| A | 5.26 |"),
            ("se", "| A | 0.10 |"),
        ):
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                print_markdown_table(rows, ("Dealer",), statistic, 2)
            self.assertTrue(expected in stdout.getvalue())

    def test_main_markdown_table(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")
            output = run_main_with_single_dealer_table(output_path)

        self.assertTrue("Dealer delta" in output)
        self.assertTrue("Summary:" in output)

    def test_main_markdown_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")
            output = run_main_with_single_dealer_table(output_path, "--view", "rows")

        self.assertTrue("| AA | Dealer | 5.260 | 5.260 | 0.000 |" in output)
        self.assertTrue(output.rstrip().endswith("max_z_score=inf"))

    def test_main_csv_threshold_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")
            write_table(
                output_path,
                {"Dealer": {"A": {"n": 1, "mu": 5.46, "se": 0.1}}},
            )

            with patch(
                "sys.argv",
                [
                    "compare_hessel.py",
                    "--role",
                    "Dealer",
                    "--format",
                    "csv",
                    "--max-abs-delta",
                    "0.1",
                    output_path,
                ],
            ), patch("sys.stdout", new_callable=io.StringIO) as stdout:
                with self.assertRaises(SystemExit) as context:
                    main()

        self.assertEqual(context.exception.code, 1)
        self.assertTrue(stdout.getvalue().startswith("pair,role,generated"))


if __name__ == "__main__":
    unittest.main()
