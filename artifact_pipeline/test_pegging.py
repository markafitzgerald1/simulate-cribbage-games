"""Tests for the standalone rank-only pegging engine."""

import random
import unittest

from artifact_pipeline.pegging import (
    DEALER,
    GO_ACTION,
    PONE,
    LegacyHeuristicPolicy,
    PeggingState,
    PolicyMixture,
    PolicyView,
    RunningStatistics,
    TabularPeggingPolicy,
    _empty_points,
    _play_rank,
    _say_go,
    canonical_hand_key,
    get_canonical_hands,
    other_role,
    policy_fingerprint,
    rank_count,
    score_play,
    simulate_from_state,
    simulate_pegging,
    train_iterative_best_response,
    train_rollout_best_response,
)


class FixedPolicy:  # pylint: disable=too-few-public-methods
    """Choose the first or last legal rank for deterministic tests."""

    def __init__(self, choose_last=False):
        self.choose_last = choose_last

    def select_rank(self, view, rng):
        del rng
        return view.legal_ranks[-1 if self.choose_last else 0]


class TestPegging(unittest.TestCase):
    def test_roles_ranks_and_hand_keys(self):
        self.assertEqual(other_role(PONE), DEALER)
        self.assertEqual(other_role(DEALER), PONE)
        with self.assertRaises(ValueError):
            other_role("Spectator")
        self.assertEqual(rank_count(0), 1)
        self.assertEqual(rank_count(12), 10)
        with self.assertRaises(ValueError):
            rank_count(-1)
        with self.assertRaises(ValueError):
            rank_count(13)
        self.assertEqual(canonical_hand_key((12, 0, 9, 4)), "A_5_T_K")
        with self.assertRaises(ValueError):
            canonical_hand_key((0, 1, 2))
        with self.assertRaises(ValueError):
            canonical_hand_key((0, 1, 2, 13))
        self.assertEqual(len(get_canonical_hands()), 1820)

    def test_running_statistics(self):
        statistics = RunningStatistics()
        self.assertEqual(statistics.standard_error, 0.0)
        statistics.add(2.0)
        self.assertEqual(statistics.to_dict(), {"n": 1, "mu": 2.0, "se": 0.0})
        statistics.add(4.0)
        self.assertAlmostEqual(statistics.mean, 3.0)
        self.assertAlmostEqual(statistics.standard_error, 1.0)
        restored = RunningStatistics.from_dict(statistics.to_dict())
        self.assertEqual(restored.n, statistics.n)
        self.assertAlmostEqual(restored.mean, statistics.mean)
        self.assertAlmostEqual(restored.moment_2, statistics.moment_2)

    def test_policy_view_and_tabular_fallback(self):
        view = PolicyView(
            role=PONE,
            own_remaining=(0, 4, 9),
            count=27,
            sequence=(9, 2),
            opponent_remaining_count=2,
            passed_roles=(),
            public_history=(9, 2),
        )
        self.assertEqual(view.legal_ranks, (0,))
        self.assertTrue("Pone" in view.key())
        policy = TabularPeggingPolicy({view.key(): 0}, FixedPolicy(True))
        self.assertEqual(policy.select_rank(view, random.Random(1)), 0)
        self.assertEqual(len(policy_fingerprint(policy)), 64)
        missing = PolicyView(
            role=PONE,
            own_remaining=(0, 1),
            count=0,
            sequence=(),
            opponent_remaining_count=4,
            passed_roles=(),
            public_history=(),
        )
        self.assertEqual(policy.select_rank(missing, random.Random(1)), 1)
        no_play = PolicyView(
            role=PONE,
            own_remaining=(9,),
            count=25,
            sequence=(9, 9),
            opponent_remaining_count=1,
            passed_roles=(),
            public_history=(9, 9),
        )
        self.assertEqual(policy.select_rank(no_play, random.Random(1)), GO_ACTION)

    def test_policy_mixture_validation_and_selection(self):
        with self.assertRaises(ValueError):
            PolicyMixture((), ())
        with self.assertRaises(ValueError):
            PolicyMixture((FixedPolicy(),), (-1.0,))
        view = PolicyView(PONE, (0, 1), 0, (), 2, (), ())
        mixture = PolicyMixture(
            (FixedPolicy(), FixedPolicy(True)),
            (0.25, 0.75),
        )
        self.assertEqual(mixture.select_rank(view, random.Random(1)), 0)
        self.assertEqual(mixture.select_rank(view, random.Random(2)), 1)
        tail = PolicyMixture((FixedPolicy(True),), (1.0,))
        self.assertEqual(tail.select_rank(view, random.Random(3)), 1)
        self.assertEqual(policy_fingerprint(mixture), policy_fingerprint(mixture))
        self.assertNotEqual(
            policy_fingerprint(mixture),
            policy_fingerprint(LegacyHeuristicPolicy()),
        )
        self.assertEqual(len(policy_fingerprint(FixedPolicy())), 64)

    def test_legacy_policy_uses_public_state(self):
        policy = LegacyHeuristicPolicy()
        lead = PolicyView(PONE, (0, 3, 9), 0, (), 3, (), ())
        self.assertEqual(policy.select_rank(lead, random.Random(1)), 3)
        no_play = PolicyView(PONE, (9,), 25, (9,), 1, (), (9,))
        self.assertEqual(policy.select_rank(no_play, random.Random(1)), GO_ACTION)

    def test_state_copy_and_view_hide_opponent_cards(self):
        state = PeggingState(
            hands={PONE: [0, 1], DEALER: [12]},
            passed_roles={DEALER},
        )
        copied = state.copy()
        copied.hands[PONE].remove(0)
        self.assertEqual(state.hands[PONE], [0, 1])
        view = state.view()
        self.assertEqual(view.own_remaining, (0, 1))
        self.assertEqual(view.opponent_remaining_count, 1)
        self.assertNotIn(12, view.own_remaining)

    def test_score_play_categories(self):
        self.assertEqual(score_play((4,), 5), _empty_points())
        self.assertEqual(score_play((4, 4), 10)["pair"], 2.0)
        self.assertEqual(score_play((4, 4, 4), 15)["pair"], 6.0)
        self.assertEqual(score_play((4, 4, 4, 4), 20)["pair"], 12.0)
        self.assertEqual(score_play((0, 2, 1), 6)["run"], 3.0)
        self.assertEqual(score_play((0, 2, 1, 3), 10)["run"], 4.0)
        self.assertEqual(score_play((0, 1, 1, 2), 7)["run"], 0.0)
        self.assertEqual(score_play((4, 9), 15)["fifteen"], 2.0)
        self.assertEqual(score_play((9, 9, 9, 0), 31)["thirty_one"], 2.0)
        with self.assertRaises(ValueError):
            score_play((), 0)

    def test_complete_simulation_totals_and_last_card(self):
        policies = {PONE: FixedPolicy(), DEALER: FixedPolicy()}
        result = simulate_pegging(
            (0, 1, 2, 3),
            (4, 5, 6, 7),
            policies,
            random.Random(1),
            collect_decisions=True,
        )
        for role in (PONE, DEALER):
            self.assertAlmostEqual(
                result.total(role), sum(result.players[role].values())
            )
        self.assertEqual(
            result.players[PONE]["last_card"] + result.players[DEALER]["last_card"],
            1.0,
        )
        self.assertGreater(len(result.decisions), 0)
        self.assertEqual(result.delta(PONE), -result.delta(DEALER))
        with self.assertRaises(ValueError):
            simulate_pegging((0,), (1, 2, 3, 4), policies, random.Random(1))
        empty = simulate_from_state(
            PeggingState(hands={PONE: [], DEALER: []}),
            policies,
            random.Random(1),
        )
        self.assertEqual(empty.total(PONE), 0.0)

    def test_thirty_one_is_exclusive_from_last_card(self):
        policies = {PONE: FixedPolicy(), DEALER: FixedPolicy()}
        state = PeggingState(
            hands={PONE: [0], DEALER: []},
            next_role=PONE,
            count=30,
            sequence=[9, 9, 9],
            last_player=DEALER,
        )
        result = simulate_from_state(state, policies, random.Random(1))
        self.assertEqual(result.players[PONE]["thirty_one"], 2.0)
        self.assertEqual(result.players[PONE]["last_card"], 0.0)

    def test_go_scores_last_player_and_resets_leader(self):
        scores = {PONE: _empty_points(), DEALER: _empty_points()}
        state = PeggingState(
            hands={PONE: [9], DEALER: [9]},
            next_role=PONE,
            count=25,
            sequence=[9, 4, 9],
            passed_roles={DEALER},
            last_player=DEALER,
        )
        _say_go(state, scores)
        self.assertEqual(scores[DEALER]["go"], 1.0)
        self.assertEqual(state.count, 0)
        self.assertEqual(state.next_role, PONE)
        invalid = PeggingState(
            hands={PONE: [9], DEALER: [9]},
            next_role=PONE,
            count=25,
            passed_roles={DEALER},
        )
        with self.assertRaises(ValueError):
            _say_go(invalid, scores)

    def test_illegal_forced_rank_is_rejected(self):
        state = PeggingState(hands={PONE: [0], DEALER: [1]})
        policies = {PONE: FixedPolicy(), DEALER: FixedPolicy()}
        with self.assertRaises(ValueError):
            simulate_from_state(state, policies, random.Random(1), forced_rank=12)

    def test_play_rank_resets_after_thirty_one(self):
        scores = {PONE: _empty_points(), DEALER: _empty_points()}
        state = PeggingState(
            hands={PONE: [0, 1], DEALER: [2]},
            next_role=PONE,
            count=30,
            sequence=[9, 9, 9],
        )
        self.assertFalse(_play_rank(state, 0, scores))
        self.assertEqual(state.count, 0)
        self.assertEqual(state.next_role, DEALER)

    def test_rollout_best_response_and_ibr(self):
        policies = {PONE: FixedPolicy(), DEALER: FixedPolicy(True)}

        def deal_sampler(rng):
            del rng
            return (0, 1, 2, 3), (4, 5, 6, 7)

        response, values = train_rollout_best_response(
            PONE, policies, deal_sampler, 2, 1, 42
        )
        self.assertGreater(len(values), 0)
        view_key = next(iter(values))
        self.assertTrue(response.actions[view_key] in values[view_key])
        with self.assertRaises(ValueError):
            train_rollout_best_response("Invalid", policies, deal_sampler, 1, 1, 1)
        with self.assertRaises(ValueError):
            train_rollout_best_response(PONE, policies, deal_sampler, 0, 1, 1)
        trained, reports = train_iterative_best_response(deal_sampler, 1, 1, 1, 42)
        self.assertEqual(set(trained), {PONE, DEALER})
        self.assertEqual(len(reports), 2)
        with self.assertRaises(ValueError):
            train_iterative_best_response(deal_sampler, 0, 1, 1, 42)
        with self.assertRaises(ValueError):
            train_iterative_best_response(deal_sampler, 1, 1, 1, 42, mixture_weight=0.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
