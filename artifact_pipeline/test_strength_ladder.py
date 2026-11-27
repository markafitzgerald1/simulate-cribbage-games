"""Tests for the strength-ladder command line (issue #263)."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import random
import tempfile
import unittest

from artifact_pipeline.generate_play_table import DiscardPolicy
from artifact_pipeline.pegging import DEALER, PONE
from artifact_pipeline.strength_ladder import (
    SCHEMA,
    RankDiscardRule,
    _plus_minus,
    main,
    parse_args,
)
from artifact_pipeline.test_fixed_policy_fixtures import make_bundle


def run_cli(argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(argv)
    return code, out.getvalue()


class TestRankDiscardRule(unittest.TestCase):
    def test_keeps_the_named_ranks_with_the_lowest_suits(self):
        keeps = {
            (PONE, (0, 0, 5, 7, 9, 12)): (0, 0, 5, 7),
            (DEALER, (0, 1, 2, 3, 3, 4)): (1, 2, 3, 4),
        }
        rule = RankDiscardRule(DiscardPolicy(keeps))
        dealt = [(12, 0), (0, 3), (9, 1), (5, 2), (0, 1), (7, 0)]
        self.assertEqual(
            rule.select_discard(PONE, dealt, random.Random(0)),
            (((0, 1), (0, 3), (5, 2), (7, 0)), ((9, 1), (12, 0))),
        )
        dealt = [(3, 2), (0, 0), (4, 1), (3, 0), (2, 3), (1, 1)]
        self.assertEqual(
            rule.select_discard(DEALER, dealt, random.Random(0)),
            (((1, 1), (2, 3), (3, 0), (4, 1)), ((0, 0), (3, 2))),
        )


class TestArguments(unittest.TestCase):
    def test_rejects_bad_rungs_counts_and_a_missing_manifest(self):
        for argv in (
            ["--discards", "random", "--rungs", "random"],
            ["--discards", "random", "--rungs", "random,random"],
            ["--discards", "random", "--rungs", "random,expert"],
            ["--rungs", "random,heuristic"],
            ["--discards", "random", "--rungs", "random,cfr"],
            ["--discards", "random", "--rungs", "random,heuristic", "--pairs", "0"],
            ["--discards", "random", "--rungs", "random,heuristic", "--workers", "0"],
        ):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parse_args(argv)
        args = parse_args(["--discards", "random", "--rungs", " heuristic , random"])
        self.assertEqual(args.rungs, ["heuristic", "random"])

    def test_plus_minus_shows_what_is_known(self):
        self.assertEqual(_plus_minus(None, None), "n/a")
        self.assertEqual(_plus_minus(0.5, None, 100), "50.00")
        self.assertEqual(_plus_minus(0.5612, 0.0011, 100), "56.12 +/- 0.11")


class TestMain(unittest.TestCase):
    @staticmethod
    def bundle_ladder():
        """Run the CLI twice on a fixture bundle, with and without workers."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = make_bundle(root)
            argv = ["--policy-manifest", str(manifest), "--pairs", "6", "--cross-table"]
            reports = []
            for extra in (["--workers", "2"], []):
                output = root / "ladder.json"
                code, printed = run_cli([*argv, *extra, "--output", str(output)])
                assert code == 0
                reports.append(json.loads(output.read_text(encoding="utf-8")))
            return reports, printed, manifest.read_bytes()

    def test_bundle_ladder_cross_table_report(self):
        (report, again), printed, manifest_bytes = self.bundle_ladder()
        self.assertEqual(again, report)
        population = json.loads(manifest_bytes)["discard_population"]
        self.assertEqual(report["schema"], SCHEMA)
        self.assertEqual(
            report["provenance"]["policy_manifest_sha256"],
            hashlib.sha256(manifest_bytes).hexdigest(),
        )
        self.assertEqual(
            report["provenance"]["discard_population_sha256"], population["sha256"]
        )
        self.assertEqual(
            [r["name"] for r in report["rungs"]], ["random", "heuristic", "cfr"]
        )
        pairs = {(m["player"], m["opponent"]) for m in report["matches"]}
        self.assertEqual(len(pairs), 6)
        for match in report["matches"]:
            self.assertEqual(match["pairs"], 6)
            self.assertEqual(
                bool(match["policy_decisions"]),
                "cfr" in (match["player"], match["opponent"]),
            )
        cfr_match = next(
            m
            for m in report["matches"]
            if (m["player"], m["opponent"]) == ("cfr", "heuristic")
        )
        counts = cfr_match["policy_decisions"]["cfr"]
        decisions = (
            f"{counts['missing_menu_fallback']:,} / {counts['off_support']:,} "
            f"/ {sum(counts.values()):,}"
        )
        lines = printed.splitlines()
        self.assertTrue(
            "6 deal pairs per match, seed 42, bundle discards" in lines[0], lines[0]
        )
        rows = [line for line in lines if line.startswith("| heuristic vs random")]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].endswith("| n/a |"))
        cfr_row = next(line for line in lines if line.startswith("| cfr vs heuristic"))
        self.assertTrue(cfr_row.endswith(f"| {decisions} |"), cfr_row)
        win = cfr_match["win_rate"]
        self.assertTrue(
            f"| {100 * win['mu']:.2f} +/- {100 * win['se']:.2f} |" in cfr_row, cfr_row
        )

    def test_random_discards_need_no_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "ladder.json"
            code, printed = run_cli(
                [
                    "--discards",
                    "random",
                    "--rungs",
                    "random,heuristic",
                    "--pairs",
                    "4",
                    "--output",
                    str(output),
                ]
            )
            report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(report["provenance"], {"discards": "random"})
        argv = ["--discards", "random", "--rungs", "random,heuristic", "--pairs", "4"]
        self.assertEqual(run_cli(argv), (0, printed))
        self.assertEqual(len(report["matches"]), 2)
        self.assertTrue("| heuristic vs random |" in printed, printed)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
