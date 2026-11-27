"""Tests for paired, seat-swapped strength-ladder matches (issue #263)."""

from __future__ import annotations

import math
import random
import statistics
import unittest
from unittest.mock import patch

from artifact_pipeline.ladder_game import (
    GameOutcome,
    LadderPlayer,
    RandomDiscardRule,
    RandomPeggingPolicy,
    play_game,
)
from artifact_pipeline.ladder_match import (
    _FORKED_MATCH,
    _play_forked_chunk,
    _set_forked_match,
    IntegerMoments,
    MatchAccumulator,
    chunk_ranges,
    elo_difference,
    pair_seed,
    play_pairs,
    run_ladder,
    run_match,
)
from artifact_pipeline.pegging import LegacyHeuristicPolicy


class CountingHeuristic(LegacyHeuristicPolicy):
    """The heuristic, counting its calls the way the CFR policy does."""

    def __init__(self) -> None:
        self.calls = 0

    def select_rank(self, view, rng):
        self.calls += 1
        return super().select_rank(view, rng)

    def reset_counts(self) -> None:
        self.calls = 0

    def decision_counts(self) -> dict[str, int]:
        return {"trained": self.calls, "missing_menu_fallback": 0}


RANDOM = LadderPlayer("random", RandomDiscardRule(), RandomPeggingPolicy())
HEURISTIC = LadderPlayer("heuristic", RandomDiscardRule(), LegacyHeuristicPolicy())


def moments_of(values, scale):
    moments = IntegerMoments(scale)
    for value in values:
        moments = moments.add(value)
    return moments


class TestIntegerMoments(unittest.TestCase):
    def test_summary_by_hand(self):
        self.assertEqual(IntegerMoments(2).summary(), {"n": 0, "mu": None, "se": None})
        self.assertEqual(moments_of([1], 2).summary(), {"n": 1, "mu": 0.5, "se": None})
        self.assertEqual(
            moments_of([1, 1], 2).summary(), {"n": 2, "mu": 0.5, "se": 0.0}
        )
        # Values 0, 1, 1: mean 2/3, sample variance 1/3, SE sqrt(1/9).
        for scaled, scale in (([0, 2, 2], 2), ([0, 1, 1], 1)):
            summary = moments_of(scaled, scale).summary()
            self.assertAlmostEqual(summary["mu"], 2 / 3)
            self.assertAlmostEqual(summary["se"], 1 / 3)

    def test_matches_the_standard_library_on_random_samples(self):
        rng = random.Random(4)
        values = [rng.randrange(-30, 31) for _ in range(500)]
        summary = moments_of(values, 2).summary()
        halves = [value / 2 for value in values]
        self.assertAlmostEqual(summary["mu"], statistics.fmean(halves))
        self.assertAlmostEqual(summary["se"], statistics.stdev(halves) / math.sqrt(500))

    def test_merge_and_affine_are_exact(self):
        rng = random.Random(5)
        left = [rng.randrange(3) for _ in range(40)]
        right = [rng.randrange(3) for _ in range(25)]
        self.assertEqual(
            moments_of(left, 2).merge(moments_of(right, 2)), moments_of(left + right, 2)
        )
        with self.assertRaisesRegex(ValueError, "different scales"):
            moments_of(left, 2).merge(moments_of(right, 1))
        for offset, sign in ((2, -1), (1, -1), (0, -1), (3, 1)):
            self.assertEqual(
                moments_of(left, 2).affine(offset, sign),
                moments_of([offset + sign * value for value in left], 2),
            )
        for sign in (0, 2):
            with self.assertRaisesRegex(ValueError, "reflection or a shift"):
                moments_of(left, 2).affine(0, sign)


class TestElo(unittest.TestCase):
    def test_known_values(self):
        elo, elo_se = elo_difference(0.5, 0.01)
        self.assertEqual(elo, 0.0)
        self.assertAlmostEqual(elo_se, 400 / math.log(10) * 0.04)
        elo, elo_se = elo_difference(0.75, 0.01)
        self.assertAlmostEqual(elo, 400 * math.log10(3))
        # d(Elo)/dp = 400 / (ln 10 * p * (1 - p)) = 926.5 at p = 0.75.
        self.assertAlmostEqual(elo_se, 9.2649, places=4)
        for undefined in ((0.0, 0.1), (1.0, 0.1), (None, None)):
            self.assertEqual(elo_difference(*undefined), (None, None))
        # One pair: the estimate exists even though its SE does not.
        self.assertEqual(elo_difference(0.75, None), (400 * math.log10(3), None))


def outcome(pone_score, dealer_score, pone_peg=0, dealer_peg=0, hands=9):
    return GameOutcome(pone_score, dealer_score, pone_peg, dealer_peg, hands)


class TestMatchAccumulator(unittest.TestCase):
    def test_add_pair_counts_from_a_side(self):
        match = MatchAccumulator()
        # A wins as first Pone by 21, and wins as first Dealer by 11.
        match.add_pair(outcome(121, 100, 30, 20, 9), outcome(110, 121, 15, 25, 8))
        # A loses as first Pone by 1 and as first Dealer by 3.
        match.add_pair(outcome(120, 121, 10, 12, 10), outcome(121, 118, 9, 7, 10))
        # A wins as first Pone only.
        match.add_pair(outcome(121, 90), outcome(121, 95))
        summary = match.summary()
        self.assertEqual(
            summary["pair_outcomes"], {"both_won": 1, "split": 1, "both_lost": 1}
        )
        self.assertEqual(summary["pairs"], 3)
        self.assertEqual(summary["games"], 6)
        self.assertAlmostEqual(summary["win_rate"]["mu"], 0.5)
        self.assertAlmostEqual(summary["won_as_first_pone"]["mu"], 2 / 3)
        self.assertAlmostEqual(summary["won_as_first_dealer"]["mu"], 1 / 3)
        # Pair means of (A's margin as Pone + A's margin as Dealer) / 2.
        self.assertAlmostEqual(
            summary["point_margin"]["mu"], ((21 + 11) + (-1 - 3) + (31 - 26)) / 6
        )
        self.assertAlmostEqual(
            summary["pegging_margin"]["mu"], ((10 + 10) + (-2 - 2) + 0) / 6
        )
        self.assertAlmostEqual(summary["hands_per_game"]["mu"], (17 + 20 + 18) / 6)
        self.assertAlmostEqual(summary["win_rate_se_as_iid_games"], math.sqrt(0.25 / 6))

    def test_empty_match_summary(self):
        summary = MatchAccumulator().summary()
        self.assertEqual(summary["pairs"], 0)
        self.assertIsNone(summary["win_rate"]["mu"])
        self.assertEqual((summary["elo"], summary["elo_se"]), (None, None))
        self.assertIsNone(summary["win_rate_se_as_iid_games"])


class TestRunMatch(unittest.TestCase):
    def test_standard_error_is_the_spread_of_pair_results(self):
        pairs = 60
        per_pair = []
        for index in range(pairs):
            seed = pair_seed(13, index)
            first = play_game(HEURISTIC, RANDOM, seed)
            second = play_game(RANDOM, HEURISTIC, seed)
            per_pair.append(
                (int(first.first_pone_won) + int(not second.first_pone_won)) / 2
            )
        summary = run_match(HEURISTIC, RANDOM, pairs, 13).summary()
        self.assertAlmostEqual(summary["win_rate"]["mu"], statistics.fmean(per_pair))
        self.assertAlmostEqual(
            summary["win_rate"]["se"], statistics.stdev(per_pair) / math.sqrt(pairs)
        )

    def test_reversed_match_is_the_exact_inverse(self):
        forward = run_match(HEURISTIC, RANDOM, 40, 21)
        self.assertEqual(forward.inverted(), run_match(RANDOM, HEURISTIC, 40, 21))
        self.assertEqual(forward.inverted().inverted(), forward)

    def test_self_play_splits_every_pair(self):
        twin = LadderPlayer("twin", RandomDiscardRule(), RandomPeggingPolicy())
        summary = run_match(RANDOM, twin, 30, 8).summary()
        self.assertEqual(
            summary["pair_outcomes"], {"both_won": 0, "split": 30, "both_lost": 0}
        )
        self.assertEqual(summary["win_rate"], {"n": 30, "mu": 0.5, "se": 0.0})
        self.assertEqual(summary["point_margin"], {"n": 30, "mu": 0.0, "se": 0.0})
        self.assertEqual(summary["elo"], 0.0)

    def test_workers_do_not_change_the_result(self):
        serial = run_match(HEURISTIC, RANDOM, 37, 3)
        self.assertEqual(run_match(HEURISTIC, RANDOM, 37, 3, workers=3), serial)
        self.assertNotEqual(run_match(HEURISTIC, RANDOM, 37, 4), serial)

    def test_a_forked_chunk_plays_its_own_pairs(self):
        # Coverage does not follow forked workers, so run the worker body here.
        _set_forked_match(
            {"player_a": HEURISTIC, "player_b": RANDOM, "seed": 3, "target_score": 121}
        )
        try:
            chunk = _play_forked_chunk(range(2, 5))
        finally:
            _FORKED_MATCH.clear()
        self.assertEqual(chunk, play_pairs(HEURISTIC, RANDOM, range(2, 5), 3))
        self.assertEqual(chunk.summary()["pairs"], 3)

    def test_a_parallel_match_leaves_no_shared_state(self):
        run_match(HEURISTIC, RANDOM, 4, 3, workers=2)
        self.assertEqual(_FORKED_MATCH, {})

    def test_each_pair_plays_both_seatings_on_its_own_seed(self):
        with patch("artifact_pipeline.ladder_match.play_game", wraps=play_game) as spy:
            play_pairs(HEURISTIC, RANDOM, range(3), 9, 61)
        calls = [call.args for call in spy.call_args_list]
        seeds = [pair_seed(9, index) for index in range(3)]
        self.assertEqual(len(set(seeds)), 3)
        self.assertEqual(
            calls,
            [
                args
                for seed in seeds
                for args in (
                    (HEURISTIC, RANDOM, seed, 61),
                    (RANDOM, HEURISTIC, seed, 61),
                )
            ],
        )

    def test_workers_play_to_the_given_target(self):
        short = run_match(HEURISTIC, RANDOM, 8, 3, target_score=31)
        self.assertEqual(
            run_match(HEURISTIC, RANDOM, 8, 3, workers=2, target_score=31), short
        )
        self.assertLess(
            short.summary()["hands_per_game"]["mu"],
            run_match(HEURISTIC, RANDOM, 8, 3).summary()["hands_per_game"]["mu"],
        )

    def test_rejects_two_counting_policies_with_one_name(self):
        same_a = LadderPlayer("same", RandomDiscardRule(), CountingHeuristic())
        same_b = LadderPlayer("same", RandomDiscardRule(), CountingHeuristic())
        with self.assertRaisesRegex(ValueError, "share the player name same"):
            run_match(same_a, same_b, 1, 1)

    def test_policy_decisions_are_collected_from_every_worker(self):
        policy = CountingHeuristic()
        counted = LadderPlayer("counted", RandomDiscardRule(), policy)
        policy.calls = 999  # stale calls from before the match are dropped
        serial = run_match(counted, RANDOM, 9, 2)
        calls = policy.calls
        self.assertGreater(calls, 9 * 2 * 8)
        decisions = {"counted": {"missing_menu_fallback": 0, "trained": calls}}
        self.assertEqual(serial.summary()["policy_decisions"], decisions)
        self.assertEqual(serial.inverted().summary()["policy_decisions"], decisions)
        self.assertEqual(run_match(counted, RANDOM, 9, 2, workers=3), serial)
        # One policy object shared by two players is counted once, under both.
        twin = LadderPlayer("twin", RandomDiscardRule(), policy)
        shared = run_match(counted, twin, 4, 2).summary()["policy_decisions"]
        self.assertEqual(list(shared), ["counted+twin"])
        self.assertEqual(shared["counted+twin"]["trained"], policy.calls)

    def test_heuristic_pegging_beats_random_pegging(self):
        summary = run_match(HEURISTIC, RANDOM, 300, 1).summary()
        win = summary["win_rate"]
        self.assertGreater(win["mu"] - 3 * win["se"], 0.5)
        self.assertLess(win["se"], summary["win_rate_se_as_iid_games"])

    def test_rejects_an_empty_match(self):
        for pairs, workers in ((0, 1), (1, 0)):
            with self.assertRaisesRegex(ValueError, "at least one"):
                run_match(HEURISTIC, RANDOM, pairs, 1, workers=workers)

    def test_summary_elo_follows_the_paired_win_rate(self):
        match = MatchAccumulator()
        # Two pairs won both, one split, one lost both: win rate 5/8.
        won_both = (outcome(121, 90), outcome(90, 121))
        match.add_pair(*won_both)
        match.add_pair(*won_both)
        match.add_pair(outcome(121, 90), outcome(121, 95))
        match.add_pair(outcome(90, 121), outcome(121, 90))
        summary = match.summary()
        win = summary["win_rate"]
        self.assertAlmostEqual(win["mu"], 5 / 8)
        self.assertEqual(
            (summary["elo"], summary["elo_se"]), elo_difference(win["mu"], win["se"])
        )
        self.assertGreater(summary["elo"], 0)
        self.assertAlmostEqual(
            summary["win_rate_se_as_iid_games"], math.sqrt(5 / 8 * 3 / 8 / 8)
        )
        inverse = match.inverted().summary()
        self.assertAlmostEqual(inverse["elo"], -summary["elo"])
        self.assertAlmostEqual(inverse["elo_se"], summary["elo_se"])

    def test_chunk_ranges_cover_every_pair_once(self):
        for pairs, chunks in ((10, 4), (3, 8), (16, 4), (1, 1)):
            ranges = chunk_ranges(pairs, chunks)
            self.assertEqual([i for r in ranges for i in r], list(range(pairs)))
            self.assertEqual(len(ranges), min(pairs, chunks))
            self.assertLessEqual(max(map(len, ranges)) - min(map(len, ranges)), 1)
        for pairs, chunks in ((0, 4), (4, 0)):
            with self.assertRaisesRegex(ValueError, "at least one pair"):
                chunk_ranges(pairs, chunks)


class TestRunLadder(unittest.TestCase):
    def test_adjacent_rungs_and_cross_table_on_common_deals(self):
        middle = LadderPlayer("middle", RandomDiscardRule(), LegacyHeuristicPolicy())
        players = [RANDOM, middle, HEURISTIC]
        adjacent = run_ladder(players, 12, 6)
        self.assertEqual(
            set(adjacent),
            {
                ("middle", "random"),
                ("random", "middle"),
                ("heuristic", "middle"),
                ("middle", "heuristic"),
            },
        )
        cross = run_ladder(players, 12, 6, cross_table=True, workers=2)
        self.assertEqual(len(cross), 6)
        for key, match in adjacent.items():
            self.assertEqual(cross[key], match)
        # Every match is played on the same pair seeds.
        self.assertEqual(
            cross[("heuristic", "random")], run_match(HEURISTIC, RANDOM, 12, 6)
        )
        self.assertEqual(
            cross[("heuristic", "middle")], run_match(HEURISTIC, middle, 12, 6)
        )
        self.assertEqual(
            cross[("random", "heuristic")], run_match(RANDOM, HEURISTIC, 12, 6)
        )

    def test_ladder_counts_each_match_separately(self):
        policy = CountingHeuristic()
        counted = LadderPlayer("counted", RandomDiscardRule(), policy)
        middle = LadderPlayer("middle", RandomDiscardRule(), LegacyHeuristicPolicy())
        results = run_ladder([RANDOM, middle, counted], 5, 2, cross_table=True)
        for opponent in (RANDOM, middle):
            alone = run_match(counted, opponent, 5, 2)
            self.assertEqual(
                results[("counted", opponent.name)].policy_decisions,
                alone.policy_decisions,
            )
        self.assertEqual(results[("middle", "random")].policy_decisions, {})

    def test_rejects_a_ladder_without_two_named_rungs(self):
        for players in ([RANDOM], [RANDOM, RANDOM]):
            with self.assertRaisesRegex(ValueError, "two players"):
                run_ladder(players, 5, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
