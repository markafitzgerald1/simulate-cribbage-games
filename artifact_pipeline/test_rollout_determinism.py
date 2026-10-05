"""Frozen hand traces count deterministic continuations once in either seat."""

import io
import unittest
from contextlib import redirect_stderr

from artifact_pipeline.pegging import (
    PONE,
    DEALER,
    GeometricHandPolicy,
    UniformHandPolicy,
    LegacyHeuristicPolicy,
    TabularPeggingPolicy,
    PolicyMixture,
    PolicyView,
    train_rollout_best_response,
)
from artifact_pipeline.test_parallel_play import RandomRankPolicy


def hand_policy(kind, component):
    return (
        UniformHandPolicy((component,))
        if kind == "uniform"
        else GeometricHandPolicy((component,), (1.0,))
    )


class TestRolloutDeterminism(unittest.TestCase):
    def fit(self, policies, rollouts, workers=1):
        with redirect_stderr(io.StringIO()):
            response, moments = train_rollout_best_response(
                PONE,
                policies,
                lambda _rng: ((0, 1, 2, 3), (4, 5, 6, 7)),
                3,
                rollouts,
                42,
                workers=workers,
            )
        opening = PolicyView(PONE, (0, 1, 2, 3), 0, (), 4, (), ())
        return response.actions, moments, [v.n for v in moments[opening.key()].values()]

    def test_asymmetric_hand_traces_cap_both_seats_and_frozen_fallbacks(self):
        for kind in ("uniform", "geometric"):
            prior = hand_policy(kind, LegacyHeuristicPolicy())
            frozen = hand_policy(kind, TabularPeggingPolicy({}, prior))
            for seat in (PONE, DEALER):
                policies = {
                    PONE: LegacyHeuristicPolicy(),
                    DEALER: LegacyHeuristicPolicy(),
                }
                policies[seat] = frozen
                expected = self.fit(policies, 1)
                for workers in (1, 2):
                    with self.subTest(kind=kind, seat=seat, workers=workers):
                        actual = self.fit(policies, 4, workers)
                        self.assertEqual(actual[2], [3] * 4)
                        self.assertEqual(actual, expected)

    def test_stochastic_resolved_fallbacks_and_custom_policies_keep_rollouts(self):
        random_policy = RandomRankPolicy()
        mixture = PolicyMixture((LegacyHeuristicPolicy(), random_policy), (0.5, 0.5))
        for component in (
            random_policy,
            mixture,
            TabularPeggingPolicy({}, random_policy),
        ):
            for kind in ("uniform", "geometric"):
                for seat in (PONE, DEALER):
                    with self.subTest(
                        component=type(component).__name__, kind=kind, seat=seat
                    ):
                        policies = {
                            role: hand_policy(kind, LegacyHeuristicPolicy())
                            for role in (PONE, DEALER)
                        }
                        policies[seat] = hand_policy(kind, component)
                        self.assertEqual(self.fit(policies, 4)[2], [12] * 4)

    def test_production_geometric_rollout_behavior_is_retained(self):
        policies = {PONE: LegacyHeuristicPolicy(), DEALER: LegacyHeuristicPolicy()}
        self.assertEqual(self.fit(policies, 4)[2], [12] * 4)
