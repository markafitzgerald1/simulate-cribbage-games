"""Tests for the optional vendored-sample Cribbage Pro comparison."""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artifact_pipeline.compare_play_table import (
    DEALER,
    PONE,
    _metrics,
    _parse_args,
    compare_tables,
    main,
)
from artifact_pipeline.cribbage_pro_reference import CRIBBAGE_PRO_PEGGING_SAMPLE


class TestComparePlayTable(unittest.TestCase):
    def setUp(self):
        self.generated = {
            "__metadata__": {},
            "A_2_3_4": {
                PONE: {
                    "mu": -1.0,
                    "players": {PONE: {"mu": 2.0}, DEALER: {"mu": 3.0}},
                },
                DEALER: {
                    "mu": 3.0,
                    "players": {PONE: {"mu": 1.0}, DEALER: {"mu": 4.0}},
                },
            },
        }

    def test_vendored_sample_shape(self):
        labels = "A23456789TJQK"
        self.assertGreaterEqual(len(CRIBBAGE_PRO_PEGGING_SAMPLE), 30)
        for key, values in CRIBBAGE_PRO_PEGGING_SAMPLE.items():
            ranks = key.split("_")
            self.assertEqual(len(ranks), 4)
            self.assertTrue(all(rank in labels for rank in ranks))
            order = [labels.index(rank) for rank in ranks]
            self.assertEqual(order, sorted(order))
            self.assertEqual(len(values), 4)
            self.assertTrue(all(0.0 <= value <= 8.0 for value in values))

    def test_compare_tables(self):
        report = compare_tables(self.generated, {"A_2_3_4": (2.0, 3.0, 4.0, 1.0)})
        self.assertEqual(report["shared_hands"], 1)
        for metrics in report["metrics"].values():
            self.assertEqual(metrics["bias"], 0.0)
            self.assertEqual(metrics["mae"], 0.0)
        with self.assertRaises(ValueError):
            compare_tables(self.generated, {"A_A_A_A": (1, 1, 1, 1)})

    def test_metrics_include_correlations(self):
        metrics = _metrics([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
        self.assertEqual(metrics["pearson"], 1.0)
        self.assertEqual(metrics["spearman"], 1.0)
        constant = _metrics([1.0, 1.0], [2.0, 2.0])
        self.assertEqual(constant["pearson"], 0.0)

    def test_parse_args_and_main(self):
        with patch("sys.argv", ["compare_play_table.py", "table.json"]):
            args = _parse_args()
        self.assertEqual(args.table, "table.json")
        self.assertFalse(args.write_metadata)
        with tempfile.TemporaryDirectory() as directory:
            table_path = Path(directory) / "table.json"
            table_path.write_text(json.dumps(self.generated), encoding="utf-8")
            main_args = type(
                "Args",
                (),
                {"table": str(table_path), "write_metadata": True},
            )()
            with patch(
                "artifact_pipeline.compare_play_table._parse_args",
                return_value=main_args,
            ), patch("sys.stdout", new_callable=io.StringIO) as stdout:
                main()
                main_args.write_metadata = False
                main()
            # Only A_2_3_4 overlaps the vendored sample.
            self.assertTrue('"shared_hands": 1' in stdout.getvalue())
            updated = json.loads(table_path.read_text(encoding="utf-8"))
            regression = updated["__metadata__"]["external_regression"]
            self.assertEqual(
                regression["reference_hands"], len(CRIBBAGE_PRO_PEGGING_SAMPLE)
            )
            self.assertTrue(regression["reference_retrieved"])

    def test_documented_script_invocation_loads_package_imports(self):
        repo_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "artifact_pipeline/compare_play_table.py", "--help"],
            cwd=repo_root,
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue("usage:" in result.stdout)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
