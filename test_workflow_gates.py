"""Unit tests verifying GitHub Actions workflow gating and integrity."""

from pathlib import Path
import shlex
import unittest
import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parent
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/python-install-and-test.yml"
PLAY_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/generate-play-artifact.yml"
PRODUCTION_EVENTS = (
    "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"
)


class TestWorkflowGates(unittest.TestCase):
    """Verify that ci-passed aggregate job gates all jobs in the PR workflow."""

    def setUp(self) -> None:
        with open(WORKFLOW_PATH, encoding="utf-8") as f:
            self.workflow = yaml.safe_load(f)
        self.jobs = self.workflow.get("jobs", {})

    def test_ci_passed_job_exists(self) -> None:
        """Verify ci-passed job exists and runs unconditionally with always()."""
        self.assertTrue("ci-passed" in self.jobs)
        ci_passed = self.jobs["ci-passed"]
        self.assertEqual(ci_passed.get("if"), "always()")
        self.assertFalse(
            "strategy" in ci_passed,
            "ci-passed must not use a matrix strategy so its name is version-free",
        )

    def test_ci_passed_gates_every_other_workflow_job(self) -> None:
        """Verify ci-passed depends on every other job in the workflow."""
        ci_passed = self.jobs["ci-passed"]
        needs = set(ci_passed.get("needs", []))
        all_other_jobs = set(self.jobs.keys()) - {"ci-passed"}

        self.assertEqual(
            needs,
            all_other_jobs,
            f"Jobs missing from ci-passed needs: {all_other_jobs - needs}",
        )


class TestPlayReleaseWorkflow(unittest.TestCase):
    """Production enforces the gate and the release notes state its outcome."""

    def setUp(self) -> None:
        with open(PLAY_WORKFLOW_PATH, encoding="utf-8") as f:
            jobs = yaml.safe_load(f)["jobs"]
        self.generate = {step["name"]: step for step in jobs["generate-table"]["steps"]}
        self.release = {
            step["name"]: step for step in jobs["release-artifact"]["steps"]
        }

    def command(self, name: str) -> list[str]:
        return shlex.split(self.generate[name]["run"].replace("\\\n", ""))

    def test_production_adds_only_the_enforced_gate(self) -> None:
        self.assertEqual(
            self.command("Generate production artifact"),
            [
                "python",
                "-u",
                "artifact_pipeline/generate_play_table.py",
                "--analytical-max-iterations=40",
                "--full-hand-policy-max-iterations=2",
                "--outer-iterations=2",
                "--ibr-iterations=2",
                "--ibr-samples=30000",
                "--rollouts-per-action=2",
                "--policy-table-samples=200",
                "--samples=13000",
                "--promotion-gate=enforce",
                "--no-resume",
                "--seed=42",
            ],
        )
        self.assertEqual(
            self.generate["Generate production artifact"]["if"], PRODUCTION_EVENTS
        )
        self.assertFalse(
            any(
                "promotion-gate" in part
                for part in self.command("Generate bounded PR artifact")
            )
        )

    def test_every_run_summarizes_the_gate_for_the_release_notes(self) -> None:
        summarize = self.generate["Summarize promotion gate"]
        self.assertFalse("if" in summarize)
        self.assertTrue("release_summary" in summarize["run"])
        self.assertEqual(
            self.generate["Upload promotion gate summary"]["with"]["path"],
            "expected_play_points.gate.md",
        )
        self.assertEqual(
            self.release["Download promotion gate summary"]["with"]["name"],
            self.generate["Upload promotion gate summary"]["with"]["name"],
        )
        body = self.release["Publish rolling release"]["with"]["body"]
        self.assertTrue("${{ steps.gate_summary.outputs.text }}" in body)
        self.assertEqual(
            self.release["Capture promotion gate summary"]["id"], "gate_summary"
        )


if __name__ == "__main__":
    unittest.main()
