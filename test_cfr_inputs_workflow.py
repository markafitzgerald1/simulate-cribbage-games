"""Guard the manual CFR input workflow without dispatching it."""

from pathlib import Path
import re
import subprocess
import unittest

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).parent
WORKFLOW = ROOT / ".github/workflows/generate-cfr-inputs.yml"
ACTION = ROOT / ".github/actions/cfr-solve-job/action.yml"
APPROVED = {
    "github.event_name": "workflow_dispatch",
    "github.ref": "refs/heads/main",
    "github.run_attempt": "1",
    "inputs.approval": "generate",
    "needs.solve-first.outputs.status": "paused",
}


def load(path: Path) -> dict:
    # BaseLoader keeps `on` a string key rather than the Boolean True.
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def equals(left, right) -> bool:
    """Compare as Actions expressions do: numbers by value, strings by case."""
    if isinstance(left, str) and isinstance(right, str):
        return left.casefold() == right.casefold()
    return float(left) == float(right)


def guard_accepts(expression: str, context: dict) -> bool:
    """Evaluate a job's `if` with explicit Actions context values."""
    expression = re.sub(
        r"(?:github|inputs|needs)\.[a-z_.-]+",
        lambda match: repr(context[match[0]]),
        expression,
    )
    expression = re.sub(r"(\S+) == (\S+)", r"equals(\1, \2)", expression)
    expression = expression.replace("&&", " and ").replace("||", " or ")
    namespace = {"__builtins__": {}, "equals": equals}
    return bool(eval(expression, namespace, {}))  # pylint: disable=eval-used


class CfrInputsWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = load(WORKFLOW)
        self.jobs = self.workflow["jobs"]
        self.action = load(ACTION)

    def test_manual_dispatch_only_with_read_permission(self) -> None:
        self.assertEqual(set(self.workflow["on"]), {"workflow_dispatch"})
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertEqual(self.workflow["concurrency"]["cancel-in-progress"], "false")

    def test_every_job_requires_the_approved_first_attempt_on_main(self) -> None:
        # Catches a job whose guard drops one condition: each deviation alone
        # must stop every job, so a re-run or a branch dispatch does nothing.
        deviations = {
            "github.event_name": "push",
            "github.ref": "refs/heads/feature",
            "github.run_attempt": "2",
            "inputs.approval": "yes",
        }
        for name, job in self.jobs.items():
            with self.subTest(job=name):
                self.assertTrue(guard_accepts(job["if"], APPROVED))
                for key, value in deviations.items():
                    context = {**APPROVED, key: value}
                    self.assertFalse(guard_accepts(job["if"], context), key)

    def test_guards_ignore_case_so_each_job_checks_main_exactly(self) -> None:
        # The job guards accept a branch named Main, as Actions compares
        # strings without case. Catches dropping the exact check from the
        # prior job or the solve action, or loosening its comparison.
        self.assertTrue(
            guard_accepts(
                self.jobs["prior"]["if"], {**APPROVED, "github.ref": "refs/heads/Main"}
            )
        )
        checks = [
            step
            for step in self.jobs["prior"]["steps"] + self.action["runs"]["steps"]
            if step.get("name") == "Require main exactly"
        ]
        self.assertEqual(len(checks), 2)
        self.assertEqual(
            self.action["runs"]["steps"][0]["name"], "Require main exactly"
        )
        self.assertEqual(self.jobs["prior"]["steps"][0]["name"], "Require main exactly")
        for check in checks:
            for ref, accepted in (
                ("refs/heads/main", True),
                ("refs/heads/Main", False),
                ("refs/heads/main2", False),
            ):
                result = subprocess.run(
                    ["bash", "-e", "-c", check["run"]],
                    env={"GITHUB_REF": ref},
                    check=False,
                )
                self.assertEqual(result.returncode == 0, accepted, ref)

    def test_the_resume_job_runs_only_after_a_pause(self) -> None:
        guard = self.jobs["solve-continue"]["if"]
        for status in ("converged", "failed", ""):
            context = {**APPROVED, "needs.solve-first.outputs.status": status}
            self.assertFalse(guard_accepts(guard, context), status)

    def test_the_resume_job_restores_what_the_first_job_saved(self) -> None:
        steps = self.jobs["solve-continue"]["steps"]
        restore = next(
            s for s in steps if s.get("name") == "Restore the paused solve state"
        )
        uploads = {
            step["name"]: step["with"]
            for step in self.action["runs"]["steps"]
            if "upload-artifact@" in step.get("uses", "")
        }
        saved = uploads["Preserve the paused solve state"]
        self.assertEqual(
            saved["name"].replace("${{ inputs.job }}", "first"), restore["with"]["name"]
        )
        self.assertEqual(restore["with"]["path"], "cfr-work")
        self.assertTrue("cfr-work/" in saved["path"].split())
        excluded = {line for line in saved["path"].split() if line.startswith("!")}
        self.assertEqual(
            excluded,
            {"!cfr-work/menus/**", "!cfr-work/trees/**", "!cfr-work/offsets.bin"},
        )

    def test_a_second_pause_fails_the_run(self) -> None:
        final = self.jobs["solve-continue"]["steps"][-1]
        self.assertEqual(final["if"], "steps.solve-job.outputs.status != 'converged'")
        self.assertTrue(final["run"].rstrip().endswith("exit 1"))

    def test_solves_pause_well_before_their_time_limit(self) -> None:
        for name in ("solve-first", "solve-continue"):
            with self.subTest(job=name):
                job = self.jobs[name]
                call = next(s for s in job["steps"] if s.get("id") == "solve-job")
                margin = int(job["timeout-minutes"]) - int(call["with"]["stop-minutes"])
                self.assertGreaterEqual(margin, 45)
                self.assertLessEqual(int(job["timeout-minutes"]), 360)

    def test_nothing_publishes(self) -> None:
        # Catches a release, push or write token added to any step: outputs
        # leave the run only as 30-day Actions artifacts.
        steps = self.action["runs"]["steps"] + [
            step for job in self.jobs.values() for step in job["steps"]
        ]
        for step in steps:
            uses, command = step.get("uses", ""), step.get("run", "")
            self.assertNotIn("release", uses)
            for forbidden in ("gh release", "git push", "gh api"):
                self.assertNotIn(forbidden, command)
        self.assertNotIn("write", str(self.workflow["permissions"]))
        for job in self.jobs.values():
            self.assertNotIn("permissions", job)
        uploads = [step for step in steps if "upload-artifact@" in step.get("uses", "")]
        self.assertEqual(len(uploads), 4)
        for upload in uploads:
            self.assertEqual(upload["with"]["retention-days"], "30")


if __name__ == "__main__":
    unittest.main()
