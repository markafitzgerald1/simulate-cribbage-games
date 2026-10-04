"""Golden geometric behavior from gauge PR #188, including warm training."""

import hashlib
import json
from pathlib import Path
import random
import unittest

from artifact_pipeline.pegging import (
    policy_fingerprint,
    simulate_pegging,
    train_iterative_best_response,
)


def sample_physical_ranks(rng):
    """Draw disjoint four-card keeps uniformly from the physical rank population."""
    cards = rng.sample(range(52), 8)
    return [card // 4 for card in cards[:4]], [card // 4 for card in cards[4:]]


class TestGeometricCompatibility(unittest.TestCase):
    def test_geometric_matches_gauge_pr_source_oracle(self):
        # This fixture was generated with the exact pegging.py from this commit,
        # not with the implementation under test. CI needs no historical checkout.
        fixture = json.loads(
            Path(__file__)
            .with_name("fixtures")
            .joinpath("geometric_188.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(
            fixture["source_commit"], "83d3e4d8e3df8205ecfcb2d014f8985dd2229413"
        )
        policies = None
        for training in fixture["training"]:
            policies, reports = train_iterative_best_response(
                sample_physical_ranks,
                training["iterations"],
                fixture["samples_per_role"],
                fixture["rollouts_per_action"],
                training["seed"],
                initial_policies=policies,
            )
            self.assertEqual(reports, training["reports"])
            self.assertEqual(
                {role: policy_fingerprint(policy) for role, policy in policies.items()},
                training["fingerprints"],
            )
        self.assertEqual(len(fixture["cases"]), 20)
        for case in fixture["cases"]:
            with self.subTest(seed=case["seed"]):
                rng = random.Random(case["seed"])
                result = simulate_pegging(
                    case["pone"], case["dealer"], policies, rng, collect_decisions=True
                )
                self.assertEqual(result.players, case["players"])
                self.assertEqual(result.opening, case["opening"])
                self.assertEqual(
                    hashlib.sha256(repr(rng.getstate()).encode()).hexdigest(),
                    case["rng_state_sha256"],
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
