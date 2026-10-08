"""Independent confirmation, paired comparison and initial-lead rule contracts."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import importlib
import io
import json
import math
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    LegacyHeuristicPolicy,
    PolicyView,
    _stable_seed,
    policy_fingerprint,
)

checks = importlib.import_module("scratch.pegging_book_checks")
book = importlib.import_module("scratch.pegging_opening_book")

ACCEPTED = {
    "hand": [0, 0, 1, 8],
    "key": "A_A_2_9",
    "heuristic_lead": 1,
    "override": 0,
    "candidates": [
        {"lead": 0, "n": 2500, "mu": 1.5, "se": 0.06, "z": 25},
        {"lead": 1, "n": 2500, "mu": 0, "se": 0, "z": None},
        {"lead": 8, "n": 2500, "mu": 1.1, "se": 0.07, "z": 15.7},
    ],
}
REJECTED = {
    "hand": [2, 3, 4, 7],
    "key": "3_4_5_8",
    "heuristic_lead": 3,
    "override": None,
    "candidates": [
        {"lead": 2, "n": 2500, "mu": -0.1, "se": 0.03, "z": -3.33},
        {"lead": 3, "n": 2500, "mu": 0, "se": 0, "z": None},
        {"lead": 4, "n": 2500, "mu": -1, "se": 0.05, "z": -20},
        {"lead": 7, "n": 2500, "mu": -0.12, "se": 0.07, "z": -1.71},
    ],
}
QUAD = {
    "hand": [0, 0, 0, 0],
    "key": "A_A_A_A",
    "heuristic_lead": 0,
    "override": None,
    "candidates": [{"lead": 0, "n": 2500, "mu": 0, "se": 0, "z": None}],
}


def source_report():
    rows = deepcopy([ACCEPTED, REJECTED, QUAD])
    return {
        "hands": rows,
        "evidence_sha256": book.evidence_digest(rows),
        "policy_fingerprint": policy_fingerprint(book.build_policy(rows)),
    }


class Result:  # pylint: disable=too-few-public-methods
    def __init__(self, value):
        self.value = value

    def delta(self, role):
        if role != PONE:
            raise AssertionError("Comparison must use Pone's delta")
        return self.value


class TestBookChecks(unittest.TestCase):
    def test_confirmation_pairs_frozen_choices_and_independent_streams(self):
        calls = []
        totals = (100, -200, 300, -400)
        gains = (1, 3, 1, 3)

        def rollout(hand, opponent, ranks, seed):
            index = len(calls)
            calls.append((hand, opponent, ranks, seed))
            return {1: totals[index], 0: totals[index] + gains[index]}

        original = deepcopy(ACCEPTED)
        with patch.object(book, "rollout_leads", side_effect=rollout):
            row = checks.confirm_lead((ACCEPTED, 0, 4, 42, "accepted"))
        self.assertEqual(ACCEPTED, original)
        self.assertEqual(row["tested_lead"], 0)
        self.assertEqual(row["fresh"]["n"], 4)
        self.assertEqual(row["fresh"]["mu"], 2)
        self.assertAlmostEqual(row["fresh"]["se"], math.sqrt(1 / 3))
        self.assertEqual(row["fresh_minus_original"], 0.5)
        self.assertEqual(len({call[3] for call in calls}), 4)
        self.assertTrue(all(call[2] == (1, 0) for call in calls))
        self.assertNotEqual(checks.FRESH_LABEL, book.TRAINING_LABEL)
        old_rng = random.Random(
            _stable_seed(42, book.TRAINING_LABEL, "deals", tuple(ACCEPTED["hand"]))
        )
        pool = book.remaining_deck(tuple(ACCEPTED["hand"]))
        old_opponents = [
            tuple(card // 4 for card in old_rng.sample(pool, 4)) for _ in calls
        ]
        self.assertNotEqual([call[1] for call in calls], old_opponents)
        for index, call in enumerate(calls):
            self.assertNotEqual(
                call[3],
                _stable_seed(
                    42, book.TRAINING_LABEL, "play", tuple(ACCEPTED["hand"]), index
                ),
            )

    def test_fresh_two_se_screen_inclusive_positive_and_without_training_borrowing(
        self,
    ):
        for differences, expected in (
            ((1, 3), True),
            ((0.99, 2.99), False),
            ((0, 0), False),
            ((-1, -1), False),
            ((1, 1), True),
        ):
            observations = iter(differences)
            with self.subTest(differences=differences), patch.object(
                book,
                "rollout_leads",
                side_effect=lambda *_, observations=observations: {
                    1: 0,
                    0: next(observations),
                },
            ):
                row = checks.confirm_lead((ACCEPTED, 0, 2, 42, "accepted"))
                self.assertEqual(row["passes_validation"], expected)
                self.assertEqual(row["fresh"]["n"], 2)
                self.assertEqual(row["original"]["n"], 2500)
        for selected, samples in ((1, 2), (0, 1)):
            with self.assertRaises(ValueError):
                checks.confirm_lead((ACCEPTED, selected, samples, 42, "accepted"))

    def test_rejected_controls_freeze_best_original_alternative_and_never_install(self):
        rows = [ACCEPTED, REJECTED, QUAD]
        jobs = checks.confirmation_jobs(rows, 1, 2, 42)
        self.assertEqual(
            [(job[0]["key"], job[1], job[4]) for job in jobs],
            [("A_A_2_9", 0, "accepted"), ("3_4_5_8", 2, "rejected-control")],
        )
        confirmation = [
            {"key": "A_A_2_9", "group": "accepted", "passes_validation": False},
            {
                "key": "3_4_5_8",
                "group": "rejected-control",
                "passes_validation": True,
                "tested_lead": 2,
            },
        ]
        self.assertEqual(checks.restricted_policy(rows, confirmation).actions, {})
        confirmation[0]["passes_validation"] = True
        self.assertEqual(
            checks.restricted_policy(rows, confirmation).actions,
            {book.opening_view((0, 0, 1, 8)).key(): 0},
        )
        for controls, samples in ((2, 2), (-1, 2), (0, 1)):
            with self.assertRaises(ValueError):
                checks.confirmation_jobs(rows, controls, samples, 42)
        tied = deepcopy(REJECTED)
        tied["candidates"][-1]["mu"] = -0.1
        self.assertEqual(checks.confirmation_jobs([tied], 1, 2, 42)[0][1], 2)

    def test_confirmation_seed_and_pool_schedule_reproducibility(self):
        jobs = checks.confirmation_jobs([ACCEPTED, REJECTED], 1, 20, 42)
        serial = checks.confirm_jobs(jobs, 1)
        self.assertEqual(serial, checks.confirm_jobs(jobs, 2))
        self.assertNotEqual(
            serial[0], checks.confirm_lead((ACCEPTED, 0, 20, 43, "accepted"))
        )
        self.assertEqual(checks.confirm_jobs([], 1), [])
        with self.assertRaises(ValueError):
            checks.confirm_jobs(jobs, 0)

    def test_shrinkage_summary_has_correct_sign_counts_and_quantiles(self):
        rows = [
            {"original": {"mu": old}, "fresh": {"mu": new}, "passes_validation": passed}
            for old, new, passed in ((3, 1, True), (2, 0, False), (1, -1, False))
        ]
        summary = checks.confirmation_summary(rows)
        self.assertEqual(
            (
                summary["fresh_positive"],
                summary["fresh_zero"],
                summary["fresh_negative"],
            ),
            (1, 1, 1),
        )
        self.assertEqual(summary["fresh_minus_original_mean"], -2)
        self.assertEqual(summary["original_mean"], 2)
        self.assertEqual(summary["fresh_mean"], 0)
        self.assertEqual(summary["passes_validation"], 1)
        self.assertEqual(
            checks.quantiles([10, 0]),
            {
                "0.0": 0,
                "0.05": 0.5,
                "0.25": 2.5,
                "0.5": 5,
                "0.75": 7.5,
                "0.95": 9.5,
                "1.0": 10,
            },
        )
        self.assertEqual(checks.confirmation_summary([]), {"keys": 0})

    def test_book_comparison_keeps_shared_cards_seeds_sign_and_paired_error(self):
        candidate, reference = object(), object()
        calls = []

        def play(pone, dealer, policies, rng):
            index = len(calls)
            calls.append((pone, dealer, policies, rng.getstate()))
            return Result((10, 11, -10, -7)[index % 4])

        with patch.object(checks, "simulate_pegging", side_effect=play):
            report = checks.compare_pone(candidate, reference, 1000, 43)
        self.assertEqual(report[PONE]["mu"], 2)
        self.assertAlmostEqual(report[PONE]["se"], math.sqrt(1 / 999))
        self.assertEqual(report["both_seats"]["mu"], 1)
        self.assertAlmostEqual(report["both_seats"]["se"], 0.5 * math.sqrt(1 / 999))
        self.assertEqual(report[DEALER], {"n": 1000, "mu": 0, "se": 0})
        self.assertTrue(report["passed"])
        for index in range(0, len(calls), 2):
            left, right = calls[index : index + 2]
            self.assertEqual(left[:2], right[:2])
            self.assertEqual(left[3], right[3])
            self.assertIs(left[2][PONE], reference)
            self.assertIs(right[2][PONE], candidate)
            self.assertIsInstance(right[2][DEALER], LegacyHeuristicPolicy)
        with self.assertRaises(ValueError):
            checks.compare_pone(candidate, reference, 999, 43)
        heuristic = LegacyHeuristicPolicy()
        self.assertFalse(checks.compare_pone(heuristic, heuristic, 1000, 43)["passed"])

    def test_pair_rule_is_one_initial_pone_rule_with_fixed_multiple_pair_tie(self):
        policy = checks.PairLeadPolicy()
        rng = random.Random(42)
        for hand, expected in (
            ((0, 0, 1, 8), 0),
            ((3, 4, 5, 5), 5),
            ((0, 0, 5, 5), 0),
            ((0, 7, 7, 7), 7),
            ((12, 12, 12, 12), 12),
            ((2, 3, 4, 7), 3),
        ):
            self.assertEqual(policy.select_rank(book.opening_view(hand), rng), expected)
        self.assertEqual(rng.getstate(), random.Random(42).getstate())
        for view in (
            PolicyView(DEALER, (0, 0, 1, 8), 0, (), 4, (), ()),
            PolicyView(PONE, (0, 0, 1, 8), 0, (), 3, (), ()),
            PolicyView(PONE, (0, 0, 1, 8), 0, (), 4, (), (-2,)),
            PolicyView(PONE, (0, 0, 8), 4, (3,), 3, (), (3,)),
            PolicyView(PONE, (9,), 25, (9,), 1, (), (9,)),
        ):
            self.assertEqual(
                policy.select_rank(view, rng),
                LegacyHeuristicPolicy().select_rank(view, rng),
            )

    def test_feature_counts_overlap_and_face_cards_never_count_above_ten(self):
        features = checks.lead_features([3, 4, 5, 5], 5)
        for name in (
            "lead_from_repeated_rank",
            "lead_from_exact_pair",
            "lead_is_highest",
            "hand_has_repeated_rank",
            "hand_has_run_of_three",
        ):
            self.assertTrue(features[name], name)
        self.assertFalse(features["lead_is_lowest"])
        self.assertTrue(checks.lead_features([0, 1, 2, 3], 1)["hand_has_run_of_four"])
        self.assertFalse(checks.lead_features([0, 1, 3, 4], 1)["hand_has_run_of_three"])
        self.assertTrue(checks.lead_features([0, 0, 3, 3], 0)["hand_has_two_pairs"])
        self.assertTrue(checks.lead_features([0, 0, 0, 3], 0)["hand_has_triple"])
        for lead in (9, 10, 11, 12):
            row = checks.lead_features([0, 1, 2, lead], lead)
            self.assertFalse(row["lead_count_above_ten"])
            self.assertTrue(row["lead_has_ten_value"])
            self.assertEqual(row["lead_is_face_rank"], lead >= 10)
        output = checks.pattern_summary(
            [ACCEPTED], [{"key": "A_A_2_9", "group": "accepted", "fresh": {"mu": 1.4}}]
        )
        self.assertEqual(
            output["lead_from_repeated_rank"],
            {"keys": 1, "original_mean": 1.5, "fresh_mean": 1.4},
        )
        self.assertEqual(
            output["lead_count_above_ten"],
            {"keys": 0, "original_mean": None, "fresh_mean": None},
        )

    def test_cli_orders_stages_checks_digests_and_counts_all_alternatives(self):
        with tempfile.TemporaryDirectory() as directory:
            source, selection, patterns = [
                Path(directory, name + ".json")
                for name in ("source", "selection", "patterns")
            ]
            source.write_text(json.dumps(source_report()), encoding="utf-8")
            base = [
                "checks",
                "--book=" + str(source),
                "--gate-deals=1000",
                "--workers=1",
                "--controls=1",
                "--samples=2",
            ]
            with patch(
                "sys.argv", [*base, "selection", "--output=" + str(selection)]
            ), redirect_stdout(io.StringIO()):
                checks.main()
            a = json.loads(selection.read_bytes())
            self.assertEqual(a["null_benchmark"]["alternative_tests"], 5)
            self.assertAlmostEqual(
                a["null_benchmark"]["expected_if_all_null"], 0.006749490158150472
            )
            self.assertEqual(a["original_gate"]["seed"], 43)
            self.assertEqual(a["restricted_gate"]["seed"], 43)
            self.assertEqual(
                a["evidence_sha256"], book.evidence_digest(a["confirmations"])
            )
            b_argv = [
                *base,
                "patterns",
                "--output=" + str(patterns),
                "--confirmation=" + str(selection),
            ]
            with patch("sys.argv", b_argv), redirect_stdout(io.StringIO()):
                checks.main()
            b = json.loads(patterns.read_bytes())
            self.assertEqual(b["rule_vs_heuristic"]["seed"], 44)
            self.assertEqual(b["rule_vs_original_book"]["seed"], 44)
            for arguments in (
                [*base, "patterns", "--output=" + str(patterns)],
                [*base, "selection", "--output=" + str(selection), "--samples=1"],
            ):
                with patch("sys.argv", arguments), redirect_stderr(
                    io.StringIO()
                ), self.assertRaises(SystemExit):
                    checks.main()
            for field in ("evidence_sha256", "original_policy_fingerprint"):
                damaged = {**a, field: "bad"}
                selection.write_text(json.dumps(damaged), encoding="utf-8")
                with patch("sys.argv", b_argv), self.assertRaises(ValueError):
                    checks.main()
            for field in ("evidence_sha256", "policy_fingerprint"):
                damaged = {**source_report(), field: "bad"}
                source.write_text(json.dumps(damaged), encoding="utf-8")
                with self.assertRaises(ValueError):
                    checks.read_book(source)


if __name__ == "__main__":
    unittest.main()
