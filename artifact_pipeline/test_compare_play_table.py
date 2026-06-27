"""Tests for the optional Cribbage Pro regression comparison."""

import io
import json
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
    normalize_external_hand,
    parse_cribbage_pro_data,
)


class Response:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return b"var data = [['A,2,3,4', 2, 3, 4, 1]];"


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

    def test_normalize_and_parse(self):
        self.assertEqual(normalize_external_hand("K,10,A,5"), "A_5_T_K")
        parsed = parse_cribbage_pro_data(
            "const pegging_data = [['bad', 1], ['A,2,3,4', 2, 3, 4, 1],"
            "['2,3,4,5', 'x', 3, 4, 1],"
            "['10,J,Q,K', 1.1, 2.2, 3.3, 4.4]];"
        )
        self.assertEqual(parsed["A_2_3_4"], (2.0, 3.0, 4.0, 1.0))
        self.assertEqual(parsed["T_J_Q_K"], (1.1, 2.2, 3.3, 4.4))
        self.assertTrue("2_3_4_5" not in parsed)
        with self.assertRaises(ValueError):
            parse_cribbage_pro_data("const empty = [];")

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
                {
                    "table": str(table_path),
                    "source_url": "https://example.test",
                    "write_metadata": True,
                },
            )()
            with patch(
                "artifact_pipeline.compare_play_table._parse_args",
                return_value=main_args,
            ), patch(
                "artifact_pipeline.compare_play_table.urlopen",
                return_value=Response(),
            ), patch(
                "sys.stdout", new_callable=io.StringIO
            ) as stdout:
                main()
                main_args.write_metadata = False
                main()
            self.assertTrue('"shared_hands": 1' in stdout.getvalue())
            updated = json.loads(table_path.read_text(encoding="utf-8"))
            regression = updated["__metadata__"]["external_regression"]
            self.assertEqual(regression["source_url"], "https://example.test")
            self.assertEqual(len(regression["source_sha256"]), 64)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
