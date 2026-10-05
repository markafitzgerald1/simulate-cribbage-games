"""Policy graph shapes drive warm-start safety and frozen rollout counts."""

import random
import unittest
from unittest.mock import patch

from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    ROLES,
    LegacyHeuristicPolicy,
    PolicyMixture,
    PolicyView,
    TabularPeggingPolicy,
    UniformHandPolicy,
    train_iterative_best_response,
    train_rollout_best_response,
    classify_policy_graph,
    _classify_policy_graph,
)


class StochasticPolicy:  # pylint: disable=too-few-public-methods
    def select_rank(self, view, rng):
        return rng.choice(view.legal_ranks)


def graph_shapes():
    legacy = LegacyHeuristicPolicy()
    hand = UniformHandPolicy((legacy,))
    mixture = PolicyMixture((legacy, legacy), (0.5, 0.5))
    custom = StochasticPolicy()
    return (
        ("legacy", legacy, False, True, False),
        ("tabular", TabularPeggingPolicy({}, legacy), False, True, False),
        ("hand", hand, True, True, False),
        ("tabular-hand", TabularPeggingPolicy({}, hand), True, True, False),
        (
            "mixture-hand",
            PolicyMixture((TabularPeggingPolicy({}, hand), legacy), (0.5, 0.5)),
            True,
            False,
            True,
        ),
        ("hand-mixture", UniformHandPolicy((mixture,)), True, False, True),
        ("decision-mixture", mixture, False, False, True),
        ("custom", custom, False, False, False),
        ("tabular-custom", TabularPeggingPolicy({}, custom), False, False, False),
        ("hand-custom", UniformHandPolicy((custom,)), True, False, False),
    )


class TestPolicyGraph(unittest.TestCase):
    def test_graph_shapes_validate_warm_starts_and_resolved_rollouts(self):
        for name, policy, has_hand, deterministic, has_mixture in graph_shapes():
            traits = classify_policy_graph(policy)
            self.assertEqual(
                (
                    traits.has_hand_average,
                    traits.deterministic_after_freezing,
                    traits.has_decision_mixture,
                ),
                (has_hand, deterministic, has_mixture),
            )
            for seat in ROLES:
                policies = {role: LegacyHeuristicPolicy() for role in ROLES}
                policies[seat] = policy
                with self.subTest(shape=name, seat=seat):
                    _, moments = train_rollout_best_response(
                        PONE,
                        policies,
                        lambda _rng: ((0, 1, 2, 3), (4, 5, 6, 7)),
                        3,
                        4,
                        42,
                    )
                    opening = PolicyView(PONE, (0, 1, 2, 3), 0, (), 4, (), ())
                    expected = 3 if has_hand and deterministic else 12
                    self.assertEqual(
                        [v.n for v in moments[opening.key()].values()], [expected] * 4
                    )
                for averaging in ("geometric", "uniform-hand"):
                    self.assert_warm_start(policies, averaging, has_hand, has_mixture)

    def assert_warm_start(self, policies, averaging, has_hand, has_mixture):
        forbidden = has_hand if averaging == "geometric" else has_mixture
        with self.subTest(averaging=averaging), patch(
            "artifact_pipeline.pegging.train_rollout_best_response",
            wraps=train_rollout_best_response,
        ) as fit:
            if forbidden:
                with self.assertRaisesRegex(ValueError, "Cannot resume"):
                    train_iterative_best_response(
                        None,
                        1,
                        3,
                        4,
                        42,
                        initial_policies=policies,
                        averaging=averaging,
                    )
                fit.assert_not_called()
            else:
                train_iterative_best_response(
                    lambda _rng: ((0, 1, 2, 3), (4, 5, 6, 7)),
                    1,
                    3,
                    4,
                    42,
                    initial_policies=policies,
                    averaging=averaging,
                )
                self.assertEqual([call.args[4] for call in fit.call_args_list], [4, 4])

    def test_resolved_component_controls_cap_including_mixed_custom_seats(self):
        legacy = LegacyHeuristicPolicy()
        prior = UniformHandPolicy((StochasticPolicy(), legacy))
        policies = {PONE: TabularPeggingPolicy({}, prior), DEALER: legacy}
        with patch.object(random.Random, "choice", return_value=legacy):
            _, moments = train_rollout_best_response(
                PONE,
                policies,
                lambda _rng: ((0, 1, 2, 3), (4, 5, 6, 7)),
                3,
                4,
                42,
            )
        opening = PolicyView(PONE, (0, 1, 2, 3), 0, (), 4, (), ())
        self.assertEqual([v.n for v in moments[opening.key()].values()], [3] * 4)
        policies[DEALER] = StochasticPolicy()
        _, moments = train_rollout_best_response(
            PONE,
            policies,
            lambda _rng: ((0, 1, 2, 3), (4, 5, 6, 7)),
            3,
            4,
            42,
        )
        self.assertEqual([v.n for v in moments[opening.key()].values()], [12] * 4)

    def test_classifier_memoizes_shared_nodes_and_rejects_cycles(self):
        policy = LegacyHeuristicPolicy()
        for _ in range(12):
            policy = UniformHandPolicy((policy, policy))
        with patch(
            "artifact_pipeline.pegging._classify_policy_graph",
            wraps=_classify_policy_graph,
        ) as inspect:
            traits = classify_policy_graph(policy)
        self.assertEqual(inspect.call_count, 25)
        self.assertTrue(traits.has_hand_average)
        self.assertTrue(traits.deterministic_after_freezing)
        self.assertFalse(traits.has_decision_mixture)
        cyclic = TabularPeggingPolicy({})
        cyclic.fallback = cyclic
        with self.assertRaisesRegex(ValueError, "cycles"):
            classify_policy_graph(cyclic)
        with self.assertRaisesRegex(ValueError, "cycles"):
            train_iterative_best_response(
                None,
                1,
                1,
                4,
                42,
                initial_policies={PONE: cyclic, DEALER: policy},
            )

    def test_stochastic_uniform_warm_starts_retain_actual_observations(self):
        observations = []

        def fit(*args, **kwargs):
            response, moments = train_rollout_best_response(*args, **kwargs)
            observations.append(moments)
            return response, moments

        custom = StochasticPolicy()
        policies = {PONE: custom, DEALER: UniformHandPolicy((custom,))}
        with patch(
            "artifact_pipeline.pegging.train_rollout_best_response", side_effect=fit
        ):
            train_iterative_best_response(
                lambda _rng: ((0, 1, 2, 3), (4, 5, 6, 7)),
                2,
                3,
                4,
                42,
                initial_policies=policies,
                averaging="uniform-hand",
            )
        # Each response sees three trace samples and four replicas per action.
        for moments in observations[::2]:
            opening = PolicyView(PONE, (0, 1, 2, 3), 0, (), 4, (), ())
            self.assertEqual([v.n for v in moments[opening.key()].values()], [12] * 4)
