"""Counter instrumentation must preserve outputs and RNG state in both modes."""

from contextlib import redirect_stdout, redirect_stderr
import io
import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from artifact_pipeline import generate_play_table as generator
from artifact_pipeline.pegging import (
    PONE,
    DEALER,
    LegacyHeuristicPolicy,
    TabularPeggingPolicy,
    PolicyMixture,
    UniformHandPolicy,
    PolicyView,
    simulate_pegging,
)
from scripts.run_pegging_experiment import count_policy_usage, run_experiment


class TestPeggingExperiment(unittest.TestCase):
    def policies(self, hand_average):
        view = PolicyView(PONE, (0, 1, 2, 3), 0, (), 4, (), ())
        pone = TabularPeggingPolicy({view.key(): 0})
        dealer = TabularPeggingPolicy({})
        if hand_average:
            return {
                PONE: UniformHandPolicy((LegacyHeuristicPolicy(), pone)),
                DEALER: UniformHandPolicy((LegacyHeuristicPolicy(), dealer)),
            }, pone
        return {
            PONE: PolicyMixture((LegacyHeuristicPolicy(), pone), (0.5, 0.5)),
            DEALER: PolicyMixture((LegacyHeuristicPolicy(), dealer), (0.5, 0.5)),
        }, pone

    def test_counts_preserve_outputs_randomness_zero_actions_and_restore(self):
        for hand_average in (False, True):
            policies, pone = self.policies(hand_average)
            original = pone.actions
            expected = []
            for seed in range(20):
                rng = random.Random(seed)
                result = simulate_pegging((0, 1, 2, 3), (4, 5, 6, 7), policies, rng)
                expected.append((result.players, result.opening, rng.getstate()))
            with count_policy_usage(policies) as usage:
                for seed, wanted in enumerate(expected):
                    rng = random.Random(seed)
                    result = simulate_pegging((0, 1, 2, 3), (4, 5, 6, 7), policies, rng)
                    self.assertEqual(
                        (result.players, result.opening, rng.getstate()), wanted
                    )
            self.assertIs(pone.actions, original)
            self.assertGreater(usage[PONE]["hits"], 0)
            self.assertEqual(usage[PONE]["distinct_stored_states"], 1)
            self.assertEqual(usage[DEALER]["distinct_stored_states"], 0)
            for role in (PONE, DEALER):
                self.assertEqual(usage[role]["hits"] + usage[role]["legacy"], 80)
                self.assertGreaterEqual(usage[role]["lookups"], usage[role]["hits"])
            with self.assertRaisesRegex(RuntimeError, "abort"):
                with count_policy_usage(policies):
                    raise RuntimeError("abort")
            self.assertIs(pone.actions, original)

    def test_runner_rejects_parallel_process_local_counters(self):
        with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            run_experiment(["--workers=2"])

    def test_runner_measures_real_sampling_and_validates_generated_pair(self):
        policies, _ = self.policies(True)

        def bounded_main():
            table = generator.generate_play_table(
                None,
                policies,
                3,
                42,
                hands=[(0, 1, 2, 3)],
                checkpoint=lambda _table: None,
                play_policy_fingerprint="test",
            )
            table["__metadata__"]["joint_policy_converged"] = False
            generator._write_json("expected_play_points.json", table)
            generator._write_json(
                "expected_play_points.client.json",
                generator.build_client_table(table),
                compact=True,
            )
            generator._write_lines(
                "expected_play_points.lines.json",
                "expected_play_points.client.json",
                table,
            )

        original_directory = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                with patch.object(generator, "main", bounded_main), patch.object(
                    generator, "sample_opponent_keep", return_value=(4, 5, 6, 7)
                ), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    report = run_experiment(["--seed=42"])
                self.assertEqual(report["gauge"]["keys_total"], 1)
                self.assertEqual(report["stages"][0]["stage"], "final_sampling")
                self.assertGreaterEqual(
                    report["elapsed_seconds"], report["stages"][0]["seconds"]
                )
                self.assertTrue(Path("experiment.json").is_file())
                self.assertEqual(len(report["sha256"]), 3)
                self.assertEqual(
                    report["policy_usage"][PONE]["hits"]
                    + report["policy_usage"][PONE]["legacy"],
                    24,
                )
            finally:
                os.chdir(original_directory)


if __name__ == "__main__":
    unittest.main()
