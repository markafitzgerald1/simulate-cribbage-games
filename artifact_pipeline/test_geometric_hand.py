"""Geometric weights with persistent per-seat components and frozen fallbacks."""

import random
import unittest
from unittest.mock import patch

from artifact_pipeline.pegging import (
    PONE,
    DEALER,
    GeometricHandPolicy,
    LegacyHeuristicPolicy,
    TabularPeggingPolicy,
    PolicyView,
    PolicyMixture,
    UniformHandPolicy,
    policy_fingerprint,
    simulate_pegging,
    simulate_from_state,
    train_iterative_best_response,
    train_rollout_best_response,
)
from artifact_pipeline.test_hand_policy_average import EndPolicy


class DrawRng(random.Random):
    def __init__(self, draws):
        super().__init__(42)
        self.draws = iter(draws)
        self.count = 0

    def random(self):
        self.count += 1
        return next(self.draws)


class TestGeometricHand(unittest.TestCase):
    def test_weights_history_prior_fallback_and_fingerprints(self):
        observed = []

        def fit(role, policies, *_args, **_kwargs):
            response = TabularPeggingPolicy({str(len(observed)): 0}, policies[role])
            observed.append((role, dict(policies), response))
            return response, {}

        with patch(
            "artifact_pipeline.pegging.train_rollout_best_response", side_effect=fit
        ) as fitting:
            policies, _ = train_iterative_best_response(
                None, 2, 1, 4, 42, averaging="geometric-hand"
            )
            policies, _ = train_iterative_best_response(
                None, 1, 1, 4, 43, averaging="geometric-hand", initial_policies=policies
            )
        self.assertEqual([c.args[4] for c in fitting.call_args_list], [1] * 6)
        for role in (PONE, DEALER):
            history = policies[role]
            self.assertEqual(history.weights, (1 / 8, 1 / 8, 1 / 4, 1 / 2))
            self.assertIsInstance(history.policies[0], LegacyHeuristicPolicy)
            expected = [response for seat, _, response in observed if seat == role]
            self.assertEqual(list(history.policies[1:]), expected)
        for role, snapshot, response in observed:
            self.assertIs(response.fallback, snapshot[role])
        for index, (role, snapshot, _) in enumerate(observed[1:], 1):
            opponent = DEALER if role == PONE else PONE
            expected = [r for seat, _, r in observed[:index] if seat == opponent]
            self.assertEqual(list(snapshot[opponent].policies[1:]), expected)
        self.assertEqual(len(observed[3][1][PONE].policies), 3)

    def test_validation_and_weight_sensitive_fingerprints(self):
        first, last = EndPolicy(False), EndPolicy(True)
        self.assertNotEqual(
            policy_fingerprint(GeometricHandPolicy((first, last), (0.25, 0.75))),
            policy_fingerprint(GeometricHandPolicy((first, last), (0.5, 0.5))),
        )
        for components, weights in (
            ((), ()),
            ((first,), ()),
            ((first,), (-1,)),
            ((first,), (0,)),
        ):
            with self.assertRaises(ValueError):
                GeometricHandPolicy(components, weights)
        mixed = GeometricHandPolicy((first, last), (0.25, 0.75))
        with self.assertRaises(ValueError):
            mixed.select_rank(
                PolicyView(PONE, (0, 1), 0, (), 2, (), ()), random.Random(1)
            )
        with self.assertRaises(ValueError):
            train_iterative_best_response(
                None, 1, 1, 1, 42, initial_policies={PONE: mixed, DEALER: mixed}
            )

    def test_draw_boundaries_follow_weights_instead_of_uniform_components(self):
        for draw, expected in (
            (0, 0),
            (0.249, 0),
            (0.25, 0),
            (0.251, 1),
            (0.49, 1),
            (0.75, 1),
            (0.999, 1),
        ):
            with self.subTest(draw=draw):
                first, last = EndPolicy(False), EndPolicy(True)
                mixed = GeometricHandPolicy((first, last), (0.25, 0.75))
                rng = DrawRng([draw])
                result = simulate_pegging(
                    (0, 1, 2, 3),
                    (4, 5, 6, 7),
                    {PONE: mixed, DEALER: EndPolicy(False)},
                    rng,
                    collect_decisions=True,
                )
                self.assertEqual(rng.count, 1)
                self.assertEqual(result.opening[0], 0 if expected == 0 else 3)
                self.assertEqual(len((first, last)[expected].calls), 4)
                self.assertEqual((first, last)[1 - expected].calls, [])
                self.assertTrue(
                    all(
                        trace.policies[PONE] is (first, last)[expected]
                        for trace in result.decisions
                    )
                )

    def test_components_independent_seats_fallbacks_frozen_and_trace_posterior(self):
        first, last = EndPolicy(False), EndPolicy(True)
        prior = GeometricHandPolicy((first, last), (0.25, 0.75))
        response = TabularPeggingPolicy({}, prior)
        rng = DrawRng([0.9, 0.1, 0.9])
        result = simulate_pegging(
            (0, 1, 2, 3),
            (4, 5, 6, 7),
            {PONE: GeometricHandPolicy((first, response), (0.25, 0.75)), DEALER: prior},
            rng,
            collect_decisions=True,
        )
        self.assertEqual(rng.count, 3)
        self.assertEqual([seat for seat, _ in first.calls], [PONE] * 4)
        self.assertEqual([seat for seat, _ in last.calls], [DEALER] * 4)
        trace = result.decisions[1]
        before = rng.count
        simulate_from_state(
            trace.state, trace.policies, rng, forced_rank=trace.view.legal_ranks[0]
        )
        self.assertEqual(rng.count, before)
        self.assertIs(response.fallback, prior)
        self.assertEqual(result.opening, [0, 7])

    def test_direct_training_one_rollout_no_count_inflation(self):
        policies = {
            seat: GeometricHandPolicy(
                (LegacyHeuristicPolicy(), TabularPeggingPolicy({})), (0.25, 0.75)
            )
            for seat in (PONE, DEALER)
        }
        values = []
        for rollouts in (1, 4):
            response, moments = train_rollout_best_response(
                PONE,
                policies,
                lambda _rng: ((0, 1, 2, 3), (4, 5, 6, 7)),
                3,
                rollouts,
                42,
            )
            values.append((response.actions, moments))
            opening = PolicyView(PONE, (0, 1, 2, 3), 0, (), 4, (), ())
            self.assertEqual([v.n for v in moments[opening.key()].values()], [3] * 4)
        self.assertEqual(values[0], values[1])


class TestHandWarmStarts(unittest.TestCase):
    def test_both_hand_modes_reject_per_decision_geometric_fallbacks(self):
        mixture = PolicyMixture((LegacyHeuristicPolicy(), EndPolicy(True)), (0.5, 0.5))
        warm = GeometricHandPolicy((TabularPeggingPolicy({}, mixture),), (1.0,))
        for mode in ("uniform-hand", "geometric-hand"):
            for policy in (mixture, warm, UniformHandPolicy((warm,))):
                with self.subTest(mode=mode, policy=type(policy).__name__), patch(
                    "artifact_pipeline.pegging.train_rollout_best_response"
                ) as fit:
                    with self.assertRaisesRegex(ValueError, "per-decision"):
                        train_iterative_best_response(
                            None,
                            1,
                            1,
                            1,
                            42,
                            averaging=mode,
                            initial_policies={
                                PONE: policy,
                                DEALER: LegacyHeuristicPolicy(),
                            },
                        )
                    fit.assert_not_called()
