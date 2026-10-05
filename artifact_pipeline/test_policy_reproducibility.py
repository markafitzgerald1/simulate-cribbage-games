"""Shared policy graphs preserve seeded seat resolution and digest work."""

import random
import hashlib
import unittest
from unittest.mock import patch

from artifact_pipeline.pegging import (
    PONE,
    DEALER,
    LegacyHeuristicPolicy,
    TabularPeggingPolicy,
    UniformHandPolicy,
    PolicyView,
    simulate_pegging,
    policy_fingerprint,
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

    def test_uniform_fingerprints_hash_each_shared_identity_once(self):
        for updates, expected in (
            (8, "dbb49d7642eeaa62546a391bd44f9367c52798eee6355fbd3264eda0f878cec0"),
            (12, "b0b61e1fd0a721a6a81decd1b8b9e3096a8fc8474307df2b4295ca5ff1f543ab"),
        ):
            policy = UniformHandPolicy((LegacyHeuristicPolicy(),))
            for index in range(updates):
                response = TabularPeggingPolicy({str(index): index % 13}, policy)
                policy = UniformHandPolicy((*policy.policies, response))
            with patch(
                "artifact_pipeline.pegging.hashlib.sha256", wraps=hashlib.sha256
            ) as hashed:
                self.assertEqual(policy_fingerprint(policy), expected)
            # One digest per legacy, response and distinct prior average object.
            self.assertEqual(hashed.call_count, 2 * updates + 2)
            response.actions["changed"] = 1
            self.assertNotEqual(policy_fingerprint(policy), expected)
        distinct = UniformHandPolicy((LegacyHeuristicPolicy(), LegacyHeuristicPolicy()))
        with patch(
            "artifact_pipeline.pegging.hashlib.sha256", wraps=hashlib.sha256
        ) as hashed:
            policy_fingerprint(distinct)
        self.assertEqual(hashed.call_count, 3)


if __name__ == "__main__":
    unittest.main()
