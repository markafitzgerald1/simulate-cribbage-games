"""Direct fitted responses freeze mixed-strategy fallbacks for the whole hand."""

import unittest

from artifact_pipeline.pegging import (
    ROLES,
    LegacyHeuristicPolicy,
    TabularPeggingPolicy,
    UniformHandPolicy,
    policy_fingerprint,
    simulate_pegging,
    simulate_from_state,
    train_rollout_best_response,
)
from artifact_pipeline.test_hand_policy_average import ChoiceRng, EndPolicy


class TestTabularHandBoundary(unittest.TestCase):
    def test_fitted_response_and_nested_table_freeze_prior_for_both_seats(self):
        for role in ROLES:
            first, last = EndPolicy(False), EndPolicy(True)
            prior = UniformHandPolicy((first, last))
            policies = {seat: LegacyHeuristicPolicy() for seat in ROLES}
            policies[role] = prior
            response, _ = train_rollout_best_response(
                role, policies, lambda _rng: ((0, 1, 2, 3), (4, 5, 6, 7)), 1, 1, 42
            )
            original = policy_fingerprint(response)
            for nested in (False, True):
                for component in (0, 1):
                    with self.subTest(role=role, nested=nested, component=component):
                        self.assert_hand(response, role, nested, component)
                        self.assertIs(response.fallback, prior)
                        self.assertEqual(policy_fingerprint(response), original)

    def assert_hand(self, response, role, nested, component):
        for policy in response.fallback.policies:
            policy.calls.clear()
        root = TabularPeggingPolicy({}, response) if nested else response
        rng = ChoiceRng([component])
        result = simulate_pegging(
            (8, 9, 10, 11),
            (8, 9, 10, 11),
            {seat: root if seat == role else LegacyHeuristicPolicy() for seat in ROLES},
            rng,
            collect_decisions=True,
        )
        self.assertEqual(rng.widths, [2])
        chosen = response.fallback.policies[component]
        self.assertEqual(len(chosen.calls), 4)
        self.assertEqual(response.fallback.policies[1 - component].calls, [])
        traces = [trace for trace in result.decisions if trace.view.role == role]
        self.assertTrue(traces)
        self.assertTrue(traces[0].view.key() not in response.actions)
        for trace in traces:
            frozen = trace.policies[role]
            if nested:
                frozen = frozen.fallback
            self.assertIs(frozen.actions, response.actions)
            self.assertIs(frozen.fallback, chosen)
        trace = traces[0]
        simulate_from_state(
            trace.state, trace.policies, rng, forced_rank=trace.view.legal_ranks[0]
        )
        self.assertEqual(rng.widths, [2])


if __name__ == "__main__":
    unittest.main()
