"""Whole-hand mixture correlation and uniform response-history regressions."""

import random
import unittest
from unittest.mock import patch

from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    DecisionTrace,
    PeggingResult,
    PeggingState,
    UniformHandPolicy,
    TabularPeggingPolicy,
    LegacyHeuristicPolicy,
    PolicyView,
    policy_fingerprint,
    simulate_pegging,
    simulate_from_state,
    train_iterative_best_response,
    train_rollout_best_response,
)


class EndPolicy:  # pylint: disable=too-few-public-methods
    def __init__(self, last):
        self.last = last
        self.calls = []

    def select_rank(self, view, rng):
        del rng
        rank = view.legal_ranks[-1 if self.last else 0]
        self.calls.append((view.role, rank))
        return rank


class ChoiceRng(random.Random):
    def __init__(self, choices):
        super().__init__(42)
        self.choices = iter(choices)
        self.widths = []

    def choice(self, seq):
        self.widths.append(len(seq))
        return seq[next(self.choices)]


class TestHandPolicyAverage(unittest.TestCase):
    def test_one_component_per_hand_correlates_all_own_decisions(self):
        first, last = EndPolicy(False), EndPolicy(True)
        mixed = UniformHandPolicy((first, last))
        for component in (0, 1):
            rng = ChoiceRng([component, 1 - component])
            first.calls.clear()
            last.calls.clear()
            result = simulate_pegging(
                (0, 1, 2, 3),
                (4, 5, 6, 7),
                {PONE: mixed, DEALER: EndPolicy(False)},
                rng,
                collect_decisions=True,
            )
            self.assertEqual(rng.widths, [2])
            chosen = (first, last)[component]
            other = (first, last)[1 - component]
            self.assertEqual(len(chosen.calls), 4)
            self.assertEqual(other.calls, [])
            self.assertEqual(result.opening[0], 0 if component == 0 else 3)
            self.assertTrue(
                all(trace.policies[PONE] is chosen for trace in result.decisions)
            )

    def test_both_seats_draw_independently_and_fallback_is_frozen(self):
        first, last = EndPolicy(False), EndPolicy(True)
        prior = UniformHandPolicy((first, last))
        response = TabularPeggingPolicy({}, prior)
        rng = ChoiceRng([1, 0, 1])
        simulate_pegging(
            (0, 1, 2, 3),
            (4, 5, 6, 7),
            {PONE: UniformHandPolicy((first, response)), DEALER: prior},
            rng,
        )
        self.assertEqual(rng.widths, [2, 2, 2])
        self.assertEqual([role for role, _rank in first.calls], [PONE] * 4)
        self.assertEqual([role for role, _rank in last.calls], [DEALER] * 4)
        self.assertIs(response.fallback, prior)

    def test_uniform_history_survives_warm_training_calls(self):
        responses = []

        def fit(role, policies, *_args, **_kwargs):
            response = TabularPeggingPolicy({str(len(responses)): 0}, policies[role])
            responses.append(response)
            return response, {}

        with patch(
            "artifact_pipeline.pegging.train_rollout_best_response", side_effect=fit
        ):
            policies, _ = train_iterative_best_response(
                None, 2, 1, 1, 42, averaging="uniform-hand"
            )
            policies, _ = train_iterative_best_response(
                None, 1, 1, 1, 43, initial_policies=policies, averaging="uniform-hand"
            )
        for role, offset in ((PONE, 0), (DEALER, 1)):
            components = policies[role].policies
            self.assertEqual(len(components), 4)
            self.assertIsInstance(components[0], LegacyHeuristicPolicy)
            self.assertEqual(list(components[1:]), responses[offset::2])
            # Enumerate each equally likely component selection, including the prior.
            for index in range(4):
                rng = ChoiceRng([index, 0, 0, 0])
                simulate_from_state(
                    PeggingState({PONE: [0], DEALER: [1]}),
                    {PONE: policies[role], DEALER: EndPolicy(False)},
                    rng,
                )
                self.assertEqual(rng.widths[0], 4)

    def test_rollout_continuations_keep_trace_component_posterior(self):
        state = PeggingState({PONE: [0, 1], DEALER: [2, 3]}, public_history=[4, 5])
        effective = {PONE: EndPolicy(False), DEALER: EndPolicy(True)}
        trace = DecisionTrace(state.view(), state, effective)
        original = {
            role: UniformHandPolicy((EndPolicy(False), EndPolicy(True)))
            for role in (PONE, DEALER)
        }
        result = PeggingResult({PONE: {}, DEALER: {}})
        with patch(
            "artifact_pipeline.pegging.simulate_pegging",
            return_value=PeggingResult({}, [trace]),
        ), patch(
            "artifact_pipeline.pegging.simulate_from_state", return_value=result
        ) as continuation:
            train_rollout_best_response(
                PONE, original, lambda _rng: ([0, 1, 4, 5], [2, 3, 6, 7]), 1, 2, 42
            )
        self.assertEqual(continuation.call_count, 2)
        self.assertTrue(
            all(call.args[1] is effective for call in continuation.call_args_list)
        )

    def test_responder_uses_opponents_current_average(self):
        observed = []

        def fit(role, policies, *args, **kwargs):
            response, values = train_rollout_best_response(
                role, policies, *args, **kwargs
            )
            observed.append((role, dict(policies), response))
            return response, values

        with patch(
            "artifact_pipeline.pegging.train_rollout_best_response", side_effect=fit
        ):
            train_iterative_best_response(
                lambda _rng: ([0, 1, 2, 3], [4, 5, 6, 7]),
                2,
                2,
                1,
                42,
                averaging="uniform-hand",
            )
        self.assertEqual([role for role, _, _ in observed], [PONE, DEALER] * 2)
        for index in range(1, len(observed)):
            role, snapshot, _response = observed[index]
            opponent = DEALER if role == PONE else PONE
            average = snapshot[opponent]
            self.assertIsInstance(average, UniformHandPolicy)
            expected = [
                response
                for prior_role, _, response in observed[:index]
                if prior_role == opponent
            ]
            self.assertIsInstance(average.policies[0], LegacyHeuristicPolicy)
            self.assertEqual(list(average.policies[1:]), expected)
            self.assertIs(average.policies[-1], observed[index - 1][2])

    def test_response_fallback_retains_own_prior_average(self):
        prior = UniformHandPolicy((LegacyHeuristicPolicy(), EndPolicy(True)))
        policies = {PONE: prior, DEALER: LegacyHeuristicPolicy()}
        response, _values = train_rollout_best_response(
            PONE, policies, lambda _rng: ([0, 1, 2, 3], [4, 5, 6, 7]), 2, 1, 42
        )
        self.assertIs(response.fallback, prior)
        self.assertIsNot(response.fallback, prior.policies[-1])

    def test_uniform_training_caps_every_response_at_one_rollout(self):
        for method, expected in (("uniform-hand", 1), ("geometric", 4)):
            with self.subTest(method=method), patch(
                "artifact_pipeline.pegging.train_rollout_best_response",
                wraps=train_rollout_best_response,
            ) as fit:
                train_iterative_best_response(
                    lambda _rng: ([0, 1, 2, 3], [4, 5, 6, 7]),
                    2,
                    2,
                    4,
                    42,
                    averaging=method,
                )
            self.assertEqual(fit.call_count, 4)
            self.assertEqual(
                [call.args[4] for call in fit.call_args_list], [expected] * 4
            )
        with self.assertRaises(ValueError):
            train_iterative_best_response(None, 1, 1, 0, 42, averaging="uniform-hand")

    def test_frozen_rollouts_do_not_duplicate_observation_counts(self):
        policies = {
            role: UniformHandPolicy((LegacyHeuristicPolicy(), EndPolicy(True)))
            for role in (PONE, DEALER)
        }
        results = []
        for rollouts in (1, 4):
            response, values = train_rollout_best_response(
                PONE,
                policies,
                lambda _rng: ([0, 1, 2, 3], [4, 5, 6, 7]),
                3,
                rollouts,
                42,
            )
            results.append((response.actions, values))
            opening = PolicyView(PONE, (0, 1, 2, 3), 0, (), 4, (), ())
            self.assertEqual(set(values[opening.key()]), {0, 1, 2, 3})
            self.assertEqual(
                [value.n for value in values[opening.key()].values()], [3] * 4
            )
        self.assertEqual(results[0], results[1])

    def test_method_and_hand_policy_validation_and_fingerprint(self):
        with self.assertRaises(ValueError):
            UniformHandPolicy(())
        mixed = UniformHandPolicy((EndPolicy(False), EndPolicy(True)))
        view = PolicyView(PONE, (0, 1), 0, (), 2, (), ())
        with self.assertRaises(ValueError):
            mixed.select_rank(view, random.Random(1))
        self.assertNotEqual(
            policy_fingerprint(mixed), policy_fingerprint(EndPolicy(False))
        )
        self.assertNotEqual(
            policy_fingerprint(mixed),
            policy_fingerprint(UniformHandPolicy((EndPolicy(False),))),
        )
        self.assertNotEqual(
            policy_fingerprint(
                UniformHandPolicy((TabularPeggingPolicy({"state": 0}),))
            ),
            policy_fingerprint(
                UniformHandPolicy((TabularPeggingPolicy({"state": 1}),))
            ),
        )
        for method in ("unknown", "geometric"):
            with self.subTest(method=method), self.assertRaises(ValueError):
                train_iterative_best_response(
                    None,
                    1,
                    1,
                    1,
                    42,
                    initial_policies={PONE: mixed, DEALER: mixed},
                    averaging=method,
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
