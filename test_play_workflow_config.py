"""Pin the approved play publication flags without executing generation."""

from pathlib import Path
import shlex
import json
import os
import subprocess
import tempfile
import unittest

import yaml  # type: ignore[import-untyped]

WORKFLOW = Path(__file__).parent / ".github/workflows/generate-play-artifact.yml"


class TestPlayWorkflowConfig(unittest.TestCase):
    def setUp(self):
        self.job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"][
            "generate-table"
        ]
        self.steps = {step["name"]: step for step in self.job["steps"]}

    def command(self, name):
        return shlex.split(self.steps[name]["run"].replace("\\\n", ""))

    def test_production_enforces_promotion_with_four_workers_only(self):
        command = self.command("Generate production artifact")
        self.assertEqual(
            command[:3], ["python", "-u", "artifact_pipeline/generate_play_table.py"]
        )
        self.assertCountEqual(
            command[3:],
            [
                "--analytical-max-iterations=40",
                "--full-hand-policy-max-iterations=2",
                "--outer-iterations=2",
                "--ibr-iterations=2",
                "--ibr-samples=30000",
                "--rollouts-per-action=2",
                "--policy-table-samples=200",
                "--samples=13000",
                "--promotion-gate=enforce",
                "--workers=4",
                "--no-resume",
                "--seed=42",
            ],
        )
        self.assertEqual(
            self.steps["Generate production artifact"]["if"],
            "github.event_name == 'schedule' || "
            "github.event_name == 'workflow_dispatch'",
        )
        self.assertEqual(self.job["timeout-minutes"], 330)

    def test_bounded_pr_generation_settings_are_unchanged(self):
        self.assertEqual(
            self.command("Generate bounded PR artifact"),
            [
                "python",
                "-u",
                "artifact_pipeline/generate_play_table.py",
                "--analytical-max-iterations=2",
                "--full-hand-policy-max-iterations=1",
                "--outer-iterations=1",
                "--ibr-iterations=1",
                "--ibr-samples=25",
                "--rollouts-per-action=1",
                "--policy-table-samples=10",
                "--samples=25",
                "--hand-limit=4",
                "--no-resume",
                "--seed=42",
            ],
        )
        self.assertEqual(
            self.steps["Generate bounded PR artifact"]["if"],
            "github.event_name == 'pull_request'",
        )

    def test_release_names_gate_outcome_and_actual_measured_policy(self):
        release = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"][
            "release-artifact"
        ]
        steps = {step["name"]: step for step in release["steps"]}
        self.assertTrue("Capture promotion gate outcome" in steps)
        capture = steps["Capture promotion gate outcome"]
        self.assertEqual(capture["id"], "play_promotion")
        body = steps["Publish rolling release"]["with"]["body"]
        for name in (
            "outcome",
            "measured_policy",
            "policy_averaging",
            "both_seat_advantage",
        ):
            self.assertTrue("${{ steps.play_promotion.outputs." + name + " }}" in body)
        for passed, policy, averaging in (
            (False, "legacy-heuristic", None),
            (True, "trained", "geometric"),
        ):
            with self.subTest(
                passed=passed
            ), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                stats = {"n": 200000, "mu": -0.15 if not passed else 0.15, "se": 0.003}
                (root / "expected_play_points.json").write_text(
                    json.dumps(
                        {
                            "__metadata__": {
                                "measured_policy": policy,
                                "policy_averaging": averaging,
                                "promotion_gate": {
                                    "passed": passed,
                                    "both_seats": stats,
                                },
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                output = root / "step-output"
                result = subprocess.run(
                    ["bash", "-eu", "-c", capture["run"]],
                    cwd=root,
                    env={**os.environ, "GITHUB_OUTPUT": str(output)},
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                values = dict(
                    line.split("=", 1)
                    for line in output.read_text(encoding="utf-8").splitlines()
                )
            self.assertEqual(values["outcome"], "passed" if passed else "failed")
            self.assertEqual(values["measured_policy"], policy)
            self.assertEqual(values["policy_averaging"], averaging or "none")
            self.assertEqual(json.loads(values["both_seat_advantage"]), stats)


if __name__ == "__main__":
    unittest.main()
