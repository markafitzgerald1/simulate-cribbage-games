"""A component with no probability mass is never selected, at any draw."""

import random
import unittest

from artifact_pipeline.pegging import (
    GeometricHandPolicy,
    PolicyMixture,
    PolicyView,
    _resolve_hand_policy,
    _updated_policy,
)
from artifact_pipeline.test_hand_policy_average import EndPolicy


class FixedRandom(random.Random):
    def __init__(self, value):
        super().__init__(0)
        self.value = value

    def random(self):
        return self.value


def named_components(count):
    return [EndPolicy(bool(index % 2)) for index in range(count)]


class TestZeroWeightComponents(unittest.TestCase):
    cases = (
        ((0.0, 1.0), 0.0, 1),
        ((0.0, 1.0), 0.5, 1),
        ((1.0, 0.0), 0.0, 0),
        ((1.0, 0.0), 1.0, 0),
        ((1.0, 0.0), 2.0, 0),
        ((0.5, 0.0, 0.5), 0.5, 0),
        ((0.5, 0.0, 0.5), 0.75, 2),
        ((0.5, 0.0, 0.5), 0.25, 0),
        ((0.0, 0.0, 1.0), 0.0, 2),
    )

    def test_hand_draw_never_resolves_to_a_zero_weight_component(self):
        for weights, draw, expected in self.cases:
            components = named_components(len(weights))
            policy = GeometricHandPolicy(tuple(components), weights)
            with self.subTest(weights=weights, draw=draw):
                resolved = _resolve_hand_policy(policy, FixedRandom(draw))
                self.assertIs(resolved, components[expected])

    def test_decision_draw_never_selects_a_zero_weight_component(self):
        view = PolicyView("Pone", (0, 1, 2, 3), 0, (), 4, (), ())
        for weights, draw, expected in self.cases:
            components = named_components(len(weights))
            policy = PolicyMixture(tuple(components), weights)
            with self.subTest(weights=weights, draw=draw):
                policy.select_rank(view, FixedRandom(draw))
                self.assertEqual(
                    [bool(component.calls) for component in components],
                    [index == expected for index in range(len(weights))],
                )

    def test_a_full_weight_response_leaves_the_prior_without_mass(self):
        prior, response = named_components(2)
        updated = _updated_policy(prior, response, "geometric-hand", 1.0)
        self.assertEqual(updated.weights, (0.0, 1.0))
        self.assertIs(_resolve_hand_policy(updated, FixedRandom(0.0)), response)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
