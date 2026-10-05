"""Shared policy graphs preserve seeded seat resolution and digest work."""

import random
import unittest

from artifact_pipeline.pegging import (
    PONE,
    DEALER,
    LegacyHeuristicPolicy,
    TabularPeggingPolicy,
    UniformHandPolicy,
    PolicyView,
    simulate_pegging,
)


class TestPolicyReproducibility(unittest.TestCase):
    def test_hand_resolution_uses_fixed_seat_order(self):
        view = PolicyView(PONE, (0, 1, 2, 3), 0, (), 4, (), ())
        low = TabularPeggingPolicy({view.key(): 0})
        high = TabularPeggingPolicy({view.key(): 3})
        policies = {
            PONE: UniformHandPolicy((low, high)),
            DEALER: UniformHandPolicy((LegacyHeuristicPolicy(), low)),
        }
        reverse = {role: policies[role] for role in (DEALER, PONE)}
        for seed in range(12):
            with self.subTest(seed=seed):
                left, right = random.Random(seed), random.Random(seed)
                expected = simulate_pegging(
                    (0, 1, 2, 3),
                    (4, 5, 6, 7),
                    policies,
                    left,
                    collect_decisions=True,
                )
                actual = simulate_pegging(
                    (0, 1, 2, 3),
                    (4, 5, 6, 7),
                    reverse,
                    right,
                    collect_decisions=True,
                )
                self.assertEqual(actual.opening, expected.opening)
                self.assertEqual(actual.players, expected.players)
                self.assertEqual(right.getstate(), left.getstate())
                for observed, wanted in zip(actual.decisions, expected.decisions):
                    for role in (PONE, DEALER):
                        self.assertEqual(observed.policies[role], wanted.policies[role])


if __name__ == "__main__":
    unittest.main()
