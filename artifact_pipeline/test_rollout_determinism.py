"""Uniform hand traces cap repeats only for known deterministic continuations."""

import unittest

from artifact_pipeline.pegging import (
    PONE,
    DEALER,
    UniformHandPolicy,
    LegacyHeuristicPolicy,
    TabularPeggingPolicy,
    PolicyMixture,
    PolicyView,
    train_rollout_best_response,
)
from artifact_pipeline.test_hand_policy_average import EndPolicy


class TestRolloutDeterminism(unittest.TestCase):
    def fit(self, policies, rollouts):
        response, moments = train_rollout_best_response(
            PONE,
            policies,
            lambda _rng: ((0, 1, 2, 3), (4, 5, 6, 7)),
            3,
            rollouts,
            42,
        )
        opening = PolicyView(PONE, (0, 1, 2, 3), 0, (), 4, (), ())
        return response.actions, moments, [v.n for v in moments[opening.key()].values()]

    def test_asymmetric_hand_traces_cap_both_seats_and_frozen_fallbacks(self):
        prior = UniformHandPolicy((LegacyHeuristicPolicy(),))
        frozen = UniformHandPolicy((TabularPeggingPolicy({}, prior),))
        for seat in (PONE, DEALER):
            with self.subTest(seat=seat):
                policies = {
                    PONE: LegacyHeuristicPolicy(),
                    DEALER: LegacyHeuristicPolicy(),
                }
                policies[seat] = frozen
                expected = self.fit(policies, 1)
                actual = self.fit(policies, 4)
                self.assertEqual(actual[2], [3] * 4)
                self.assertEqual(actual, expected)

    def test_stochastic_resolved_fallbacks_and_custom_policies_keep_rollouts(self):
        custom = EndPolicy(True)
        mixture = PolicyMixture((LegacyHeuristicPolicy(), custom), (0.5, 0.5))
        for component in (custom, mixture, TabularPeggingPolicy({}, custom)):
            for seat in (PONE, DEALER):
                with self.subTest(component=type(component).__name__, seat=seat):
                    policies = {
                        role: UniformHandPolicy((LegacyHeuristicPolicy(),))
                        for role in (PONE, DEALER)
                    }
                    policies[seat] = UniformHandPolicy((component,))
                    self.assertEqual(self.fit(policies, 4)[2], [12] * 4)

    def test_production_geometric_rollout_behavior_is_retained(self):
        policies = {PONE: LegacyHeuristicPolicy(), DEALER: LegacyHeuristicPolicy()}
        self.assertEqual(self.fit(policies, 4)[2], [12] * 4)


if __name__ == "__main__":
    unittest.main()
