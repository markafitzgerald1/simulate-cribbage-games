"""Counter instrumentation must preserve outputs and RNG state in both modes."""

from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import random
import subprocess
import sys
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
from scripts.run_pegging_experiment import REPO_ROOT, count_policy_usage, run_experiment


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

    def test_forwarded_output_paths_drive_report_and_hashes(self):
        def fake_main():
            args = generator._parse_args()
            full = {
                "__metadata__": {
                    "seed": 42,
                    "joint_policy_converged": False,
                    "generation_method": "test",
                    "policy_fingerprint": "test",
                }
            }
            generator._write_json(args.output, full)
            generator._write_json(args.client_output, {"fixture": 1}, compact=True)
            generator._write_lines(args.lines_output, args.client_output, full)

        original_directory = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                names = ("custom.full.json", "custom.client.json", "custom.lines.json")
                flags = [
                    "--output",
                    names[0],
                    "--client-output=" + names[1],
                    "--lines-output",
                    names[2],
                ]
                with patch.object(generator, "main", fake_main):
                    report = run_experiment(flags)
                self.assertEqual(set(report["sha256"]), set(names))
                self.assertEqual(report["metadata"]["seed"], 42)
                self.assertEqual(report["gauge"]["keys_total"], 0)
                self.assertFalse(Path("expected_play_points.json").exists())
            finally:
                os.chdir(original_directory)

    def test_import_waits_for_experiment_directory_before_opening_cache(self):
        # A fresh interpreter is essential: other tests already imported legacy.
        probe = """
import json
import os
from pathlib import Path
import sys
import diskcache
original_cache = diskcache.Cache
opened = []
def record_cache(*args, **kwargs):
    opened.append(str(Path.cwd()))
    return original_cache(sys.argv[2])
diskcache.Cache = record_cache
from scripts import run_pegging_experiment as runner
before = list(opened)
os.chdir(sys.argv[1])
try:
    runner.run_experiment(["--invalid-generator-option"])
except SystemExit as error:
    assert error.code == 2
else:
    raise AssertionError("Invalid generator option was accepted")
print(json.dumps({"before": before, "opened": opened}))
"""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "experiment"
            target.mkdir()
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    probe,
                    str(target),
                    str(Path(directory) / "cache"),
                ],
                cwd=directory,
                env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
                capture_output=True,
                text=True,
                check=True,
            )
            observed = json.loads(completed.stdout)
            self.assertEqual(observed["before"], [])
            self.assertEqual(observed["opened"], [str(target.resolve())])

    def test_report_path_collisions_fail_before_sampling_or_writes(self):
        original_directory = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                Path("experiment.json").write_text("sentinel", encoding="utf-8")
                for flag in ("--output", "--client-output", "--lines-output"):
                    for path in (
                        "experiment.json",
                        "./experiment.json",
                        str(Path(directory) / "experiment.json"),
                    ):
                        with self.subTest(flag=flag, path=path), patch.object(
                            generator,
                            "main",
                            side_effect=AssertionError(
                                "generator ran with a colliding report path"
                            ),
                        ) as sample:
                            with self.assertRaisesRegex(ValueError, "report path"):
                                run_experiment([flag, path])
                            sample.assert_not_called()
                            self.assertEqual(
                                Path("experiment.json").read_text(encoding="utf-8"),
                                "sentinel",
                            )
                Path("alias.json").symlink_to("experiment.json")
                with patch.object(
                    generator,
                    "main",
                    side_effect=AssertionError(
                        "generator ran with a colliding report path"
                    ),
                ) as sample, self.assertRaisesRegex(ValueError, "report path"):
                    run_experiment(["--output=alias.json"])
                sample.assert_not_called()
            finally:
                os.chdir(original_directory)


if __name__ == "__main__":
    unittest.main()
