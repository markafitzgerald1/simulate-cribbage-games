"""Known seed vectors pin trace/sample/decision/repeat boundaries and action pairing."""

import random
import unittest
from unittest.mock import patch

from artifact_pipeline import pegging
from artifact_pipeline.pegging import _rollout_observations


class TestRolloutSeeds(unittest.TestCase):
    def test_rollout_rng_states_pin_sample_decision_repeat_and_common_actions(self):
        policies = {role: pegging.LegacyHeuristicPolicy() for role in pegging.ROLES}
        states = [
            pegging.PeggingState(
                {pegging.PONE: [0, 1], pegging.DEALER: [2, 3]},
                next_role=role,
                public_history=[index],
            )
            for index, role in enumerate((pegging.DEALER, pegging.PONE, pegging.PONE))
        ]
        traces = [
            pegging.DecisionTrace(state.view(), state, policies) for state in states
        ]
        calls, trace_rng = [], []

        def trace(_pone, _dealer, _policies, rng, **kwargs):
            self.assertTrue(kwargs["collect_decisions"])
            trace_rng.append(rng.getstate())
            return pegging.PeggingResult({}, traces)

        def continue_play(state, selected, rng, forced_rank):
            self.assertIs(selected, policies)
            calls.append((state, forced_rank, rng.getstate()))
            return pegging.PeggingResult({role: {} for role in pegging.ROLES})

        with patch.object(pegging, "simulate_pegging", side_effect=trace), patch.object(
            pegging, "simulate_from_state", side_effect=continue_play
        ):
            for sample in (5, 6):
                observations = list(
                    _rollout_observations(
                        pegging.RolloutContext(pegging.PONE, policies, 2, 19),
                        (sample, (0, 1, 2, 3), (4, 5, 6, 7)),
                    )
                )
                self.assertEqual(len(observations), 8)
        # Independently recorded SHA-256 vectors for the explicit input tuples.
        self.assertEqual(
            trace_rng,
            [
                random.Random(seed).getstate()
                for seed in (4009166070499454366, 15263456353617938442)
            ],
        )
        seeds = (
            18163056595095334705,
            5568718940852653214,
            18163056595095334705,
            5568718940852653214,
            9201670193804636882,
            15987666794362655801,
            9201670193804636882,
            15987666794362655801,
            18279181207109092101,
            4035392403692097558,
            18279181207109092101,
            4035392403692097558,
            6121869813235425348,
            4273059508980333971,
            6121869813235425348,
            4273059508980333971,
        )
        self.assertEqual(
            [call[2] for call in calls],
            [random.Random(seed).getstate() for seed in seeds],
        )
        self.assertEqual([call[1] for call in calls], [0, 0, 1, 1] * 4)
        self.assertEqual(
            [call[0] for call in calls], ([states[1]] * 4 + [states[2]] * 4) * 2
        )


if __name__ == "__main__":
    unittest.main()
