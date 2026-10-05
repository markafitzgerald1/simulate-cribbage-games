"""Pin the approved play publication flags without executing generation."""

from pathlib import Path
import shlex
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


if __name__ == "__main__":
    unittest.main()
