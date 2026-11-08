"""Focused contracts and negative tests for the Stage 1 research harness."""

from contextlib import redirect_stdout, redirect_stderr
import io
import importlib
import json
import math
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from artifact_pipeline.adapter import legacy_select_play_rank
from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    LegacyHeuristicPolicy,
    PolicyView,
    RunningStatistics,
    get_canonical_hands,
    simulate_pegging,
)

# Keep the research directory outside the installed Python packages.
book = importlib.import_module("scratch.pegging_opening_book")


class Result:  # pylint: disable=too-few-public-methods
    def __init__(self, delta):
        self.value = delta

    def delta(self, role):
        if role != PONE:
            raise AssertionError("Training must maximize Pone delta")
        return self.value


class TestOpeningBook(unittest.TestCase):
    def test_sampler_removes_known_cards_and_draws_again_each_time(self):
        opponents = []

        def rollout(_own, opponent, _ranks, _seed):
            opponents.append(opponent)
            return {0: 0}

        with patch.object(book, "rollout_leads", side_effect=rollout):
            book.train_hand(((0, 0, 0, 0), 20, 42))
        self.assertEqual(len(opponents), 20)
        self.assertTrue(all(0 not in opponent for opponent in opponents))
        self.assertGreater(len(set(opponents)), 1)

    def test_real_sample_integer_tie_prefers_lower_rank(self):
        left = [4, 3, 5, 5, 4, 3, 5, 3, 5, 3, 4, 5, 5, 4, 4, 3, 4, 3, 5, 3]
        right = [3, 3, 4, 4, 5, 4, 5, 5, 3, 5, 5, 5, 3, 3, 3, 5, 4, 4, 4, 3]
        self.assertEqual(sum(left), sum(right))
        index = iter(range(20))

        def rollout(*_args):
            sample = next(index)
            return {0: left[sample], 1: right[sample], 2: 0, 8: -10}

        with patch.object(book, "rollout_leads", side_effect=rollout):
            row = book.train_hand(((0, 1, 2, 8), 20, 42))
        self.assertEqual(row["override"], 0)
        self.assertEqual(row["candidates"][0]["gain_sum"], 80)
        self.assertEqual(row["candidates"][1]["gain_sum"], 80)

    def test_digest_preserves_unrounded_evidence(self):
        rows = [
            {
                "key": "A_A_2_9",
                "candidates": [
                    {"lead": 0, "n": 2, "mu": 0.12500000000001, "se": 0.000000001}
                ],
            }
        ]
        expected = "ab3541b5fa7bd03ea642e858c275634e278f7490456c086e56df9d4092c6d4bb"
        self.assertEqual(book.evidence_digest(rows), expected)
        rows[0]["candidates"][0]["mu"] += 1e-12
        self.assertNotEqual(book.evidence_digest(rows), expected)

    def test_paired_differences_shared_cards_seeds_and_frozen_continuations(self):
        calls = []
        baselines = (10, -20, 30, -40)
        gains = (1, 3, 1, 3)

        def rollout(state, policies, rng, *, forced_rank):
            calls.append((state.copy(), policies, rng.getstate(), forced_rank))
            index = (len(calls) - 1) // 2
            return Result(baselines[index] + (gains[index] if forced_rank == 0 else 0))

        with patch.object(book, "simulate_from_state", side_effect=rollout):
            row = book.train_hand(((0, 0, 0, 1), 4, 42))
        self.assertEqual(row["heuristic_lead"], 1)
        self.assertEqual(len(calls), 8)
        for index in range(4):
            left, right = calls[index * 2 : index * 2 + 2]
            self.assertEqual(left[0], right[0])
            self.assertEqual(left[2], right[2])
            self.assertEqual((left[3], right[3]), (0, 1))
            for policy in left[1].values():
                self.assertIsInstance(policy, LegacyHeuristicPolicy)
        self.assertEqual(len({repr(call[2]) for call in calls}), 4)
        candidate = row["candidates"][0]
        self.assertEqual(candidate["n"], 4)
        self.assertEqual(candidate["mu"], 2.0)
        self.assertAlmostEqual(candidate["se"], math.sqrt(1 / 3))
        self.assertAlmostEqual(candidate["z"], math.sqrt(12))
        self.assertEqual(row["override"], 0)
        self.assertEqual(row["candidates"][1]["mu"], 0)

    def test_threshold_is_positive_inclusive_paired_and_requires_samples(self):
        for mean, error, count, expected in (
            (0, 0, 2, None),
            (-1, 0, 2, None),
            (2.999, 1, 2, None),
            (3, 1, 2, 0),
            (3.001, 1, 2, 0),
            (1, 0, 2, 0),
            (100, 0, 1, None),
        ):
            values = {
                0: RunningStatistics(count, mean, error**2 * count * max(0, count - 1))
            }
            with self.subTest(mean=mean, error=error, count=count):
                self.assertEqual(book.select_override(values, 1), expected)
        self.assertIsNone(book.select_override({0: RunningStatistics(2, 10, 0)}, 0))
        values = {
            0: RunningStatistics(2, 4, 2),
            1: RunningStatistics(2, 3, 0),
            2: RunningStatistics(2, 4, 2),
        }
        self.assertEqual(book.select_override(values, 3), 0)

    def test_physical_removal_including_four_of_a_rank(self):
        for hand in get_canonical_hands():
            pool = book.remaining_deck(hand)
            self.assertEqual(len(pool), 48)
            self.assertEqual(len(set(pool)), 48)
            for rank in set(hand):
                self.assertEqual(
                    sum(card // 4 == rank for card in pool), 4 - hand.count(rank)
                )
        self.assertTrue(
            all(card // 4 != 0 for card in book.remaining_deck((0, 0, 0, 0)))
        )

    def test_book_only_changes_the_exact_opening_information_state(self):
        row = {"hand": [0, 0, 1, 8], "override": 0}
        policy = book.build_policy([row, {"hand": [3, 4, 5, 5], "override": None}])
        self.assertEqual(len(policy.actions), 1)
        opening = book.opening_view((0, 0, 1, 8))
        self.assertEqual(opening, PolicyView(PONE, (0, 0, 1, 8), 0, (), 4, (), ()))
        rng = random.Random(42)
        state_before = rng.getstate()
        self.assertEqual(policy.select_rank(opening, rng), 0)
        self.assertEqual(rng.getstate(), state_before)
        fallback_views = (
            book.opening_view((3, 4, 5, 5)),
            PolicyView(DEALER, opening.own_remaining, 0, (), 4, (), ()),
            PolicyView(PONE, opening.own_remaining, 0, (), 3, (), ()),
            PolicyView(PONE, opening.own_remaining, 0, (), 4, (), (-2,)),
            PolicyView(PONE, (0, 1, 8), 3, (0, 1), 3, (), (0, 1)),
            PolicyView(PONE, (9,), 25, (9,), 1, (), (9,)),
        )
        for view in fallback_views:
            self.assertEqual(
                policy.select_rank(view, rng),
                LegacyHeuristicPolicy().select_rank(view, rng),
            )

    def test_seed_and_pool_schedule_reproducibility(self):
        hands = [(0, 0, 1, 8), (3, 4, 5, 5), (2, 3, 4, 7)]
        with patch.object(book, "get_canonical_hands", return_value=hands):
            serial = book.train_book(20, 42, 1)
            parallel = book.train_book(20, 42, 2)
        self.assertEqual(serial, parallel)
        self.assertEqual(book.evidence_digest(serial), book.evidence_digest(parallel))
        self.assertNotEqual(serial[0], book.train_hand((hands[0], 20, 43)))
        self.assertIsNone(book.train_hand(((0, 0, 0, 0), 2, 42))["override"])
        with self.assertRaises(ValueError):
            book.train_hand((hands[0], 1, 42))
        with self.assertRaises(ValueError):
            book.train_book(2, 42, 0)

    def test_frozen_heuristic_unit_choices_and_complete_simulation(self):
        # Expected ranks cover the reused immutable heuristic's priority paths.
        for legal, count, sequence, expected in (
            ((0, 3, 9), 0, (), 3),
            ((7, 9), 0, (), 9),
            ((0, 2), 9, (2, 2, 2), 2),
            ((0, 1, 2), 4, (0, 2), 1),
            ((0, 3), 11, (4, 5), 3),
            ((0, 3), 4, (3,), 3),
            ((0, 3), 18, (8, 8), 0),
            ((0, 3), 27, (9, 9, 6), 3),
            ((4, 8), 21, (9, 9, 0), 8),
        ):
            with self.subTest(legal=legal, count=count, sequence=sequence):
                self.assertEqual(
                    legacy_select_play_rank(legal, count, sequence), expected
                )
        heuristic = LegacyHeuristicPolicy()
        policy = book.build_policy([])
        for pone, dealer in (
            ((0, 0, 1, 8), (3, 4, 5, 5)),
            ((9, 9, 9, 9), (8, 8, 8, 8)),
        ):
            reference = simulate_pegging(
                pone, dealer, {PONE: heuristic, DEALER: heuristic}, random.Random(42)
            )
            candidate = simulate_pegging(
                pone, dealer, {PONE: policy, DEALER: heuristic}, random.Random(42)
            )
            self.assertEqual(candidate, reference)

    def test_cli_writes_reproducible_evidence_and_evaluates_merged_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory, "book.json")
            argv = [
                "book",
                "--samples=2",
                "--workers=1",
                "--gate-deals=1000",
                f"--output={output}",
            ]
            with patch("sys.argv", argv), patch.object(
                book, "get_canonical_hands", return_value=[(0, 0, 0, 0)]
            ), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                book.main()
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["overrides"], 0)
            self.assertEqual(
                report["promotion_gate"][PONE], {"n": 1000, "mu": 0, "se": 0}
            )
            self.assertFalse(report["promotion_gate"]["passed"])
            self.assertEqual(
                report["evidence_sha256"], book.evidence_digest(report["hands"])
            )
            with patch("sys.argv", [*argv, "--samples=1"]), redirect_stderr(
                io.StringIO()
            ), self.assertRaises(SystemExit):
                book.main()


if __name__ == "__main__":
    unittest.main()
