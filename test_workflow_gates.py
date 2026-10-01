"""Unit tests verifying GitHub Actions workflow gating and integrity."""

from pathlib import Path
import unittest
import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parent
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/python-install-and-test.yml"


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

    def test_eval_needs_results_success_and_failure(self) -> None:
        """Test verification of needs results for success and failure modes."""
        all_success = {
            "legacy-tests": {"result": "success"},
            "artifact-coverage": {"result": "success"},
        }
        non_success = [
            f"{k}: {v['result']}"
            for k, v in all_success.items()
            if v.get("result") != "success"
        ]
        self.assertEqual(non_success, [])

        with_failure = {
            "legacy-tests": {"result": "success"},
            "artifact-coverage": {"result": "failure"},
            "lint-and-typecheck": {"result": "cancelled"},
            "frontend-tests-and-build": {"result": "skipped"},
        }
        failed = [
            f"{k}: {v['result']}"
            for k, v in with_failure.items()
            if v.get("result") != "success"
        ]
        self.assertEqual(len(failed), 3)
        self.assertTrue("artifact-coverage: failure" in failed)
        self.assertTrue("lint-and-typecheck: cancelled" in failed)
        self.assertTrue("frontend-tests-and-build: skipped" in failed)


if __name__ == "__main__":
    unittest.main()
