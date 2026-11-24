"""Guard the manual CFR input workflow without dispatching it."""

from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

import yaml  # type: ignore[import-untyped]

from scripts.run_cfr_inputs import CONVERGED_OUTPUTS

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


def subcommands(command: str, program: str) -> list[str]:
    """Each subcommand `program` runs in a shell script, skipping its global
    options (and the value of those that take one, like `git -C DIR`)."""
    takes_value = {"-C", "-c", "--git-dir", "--work-tree", "-R", "--repo"}
    found = []
    for line in command.replace("\\\n", " ").splitlines():
        # Split shell operators (`;`, `&&`, `|`) off as their own words, so
        # `git push;` names the subcommand `push`.
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        words = list(lexer)
        for index, word in enumerate(words):
            if Path(word).name != program:
                continue
            rest = iter(words[index + 1 :])
            for option in rest:
                if option in takes_value:
                    next(rest, None)
                elif not option.startswith("-"):
                    found.append(option)
                    break
    return found


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
        # Catches the typed confirmation made optional or given a default.
        approval = self.workflow["on"]["workflow_dispatch"]["inputs"]["approval"]
        self.assertEqual(approval["required"], "true")
        self.assertEqual(approval["type"], "string")
        self.assertNotIn("default", approval)
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
        # Catches a restore that comes after the solve, names another job's
        # state, or may come back empty: each would start the solve again
        # from iteration zero instead of resuming it.
        steps = self.jobs["solve-continue"]["steps"]
        names = [step.get("name", step.get("id")) for step in steps]
        restore = next(
            s for s in steps if s.get("name") == "Restore the paused solve state"
        )
        check = names.index("Require the restored checkpoint")
        self.assertLess(names.index("Restore the paused solve state"), check)
        self.assertLess(check, names.index("solve-job"))
        self.assertEqual(steps[check]["run"], "test -s cfr-work/checkpoint.json")
        self.assertNotIn("if", steps[check])
        first = next(
            s for s in self.jobs["solve-first"]["steps"] if s.get("id") == "solve-job"
        )
        self.assertEqual(first["with"]["job"], "first")
        uploads = {
            step["name"]: step["with"]
            for step in self.action["runs"]["steps"]
            if "upload-artifact@" in step.get("uses", "")
        }
        saved = uploads["Preserve the paused solve state"]
        paused_upload = next(
            step
            for step in self.action["runs"]["steps"]
            if step.get("name") == "Preserve the paused solve state"
        )
        self.assertEqual(paused_upload["if"], "steps.solve.outputs.status == 'paused'")
        self.assertEqual(
            saved["name"].replace("${{ inputs.job }}", "first"), restore["with"]["name"]
        )
        self.assertEqual(restore["with"]["path"], "cfr-work")
        self.assertTrue("cfr-work/" in saved["path"].split())
        excluded = {line for line in saved["path"].split() if line.startswith("!")}
        self.assertEqual(
            excluded,
            {
                "!cfr-work/menus/**",
                "!cfr-work/trees/**",
                "!cfr-work/offsets.bin",
                "!cfr-work/policy-*.bin",
            },
        )

    def test_a_second_pause_fails_the_run(self) -> None:
        # Catches the final gate made non-fatal, or any step allowed to fail
        # without failing its job.
        final = self.jobs["solve-continue"]["steps"][-1]
        self.assertEqual(final["if"], "steps.solve-job.outputs.status != 'converged'")
        self.assertTrue(final["run"].rstrip().endswith("exit 1"))
        steps = self.action["runs"]["steps"] + [
            step for job in self.jobs.values() for step in job["steps"]
        ]
        for step in steps:
            self.assertNotIn("continue-on-error", step)
        for job in self.jobs.values():
            self.assertNotIn("continue-on-error", job)

    def test_the_jobs_hand_their_status_and_outputs_on(self) -> None:
        # Catches broken wiring between the jobs and the action: a dropped
        # dependency, a status that never reaches the resume job, the action
        # not called, or the solve writing somewhere the uploads do not read.
        self.assertEqual(self.jobs["solve-first"]["needs"], "prior")
        self.assertEqual(self.jobs["solve-continue"]["needs"], "solve-first")
        self.assertEqual(
            self.jobs["solve-first"]["outputs"]["status"],
            "${{ steps.solve-job.outputs.status }}",
        )
        self.assertEqual(
            self.action["outputs"]["status"]["value"],
            "${{ steps.solve.outputs.status }}",
        )
        for name, job in (("solve-first", "first"), ("solve-continue", "continue")):
            call = next(
                s for s in self.jobs[name]["steps"] if s.get("id") == "solve-job"
            )
            self.assertEqual(call["uses"], "./.github/actions/cfr-solve-job")
            # Distinct names keep the two jobs' artifacts apart.
            self.assertEqual(call["with"]["job"], job)
        steps = {step.get("name"): step for step in self.action["runs"]["steps"]}
        solve = steps["Build the inputs and run the solve"]
        self.assertEqual(solve["id"], "solve")
        words = shlex.split(solve["run"].replace("\\\n", " "))
        # The wrapper itself runs, not a command that merely mentions it.
        self.assertEqual(
            words[:5], ["python", "-u", "-m", "scripts.run_cfr_inputs", "solve-job"]
        )
        self.assertEqual(words[words.index("--output") + 1], "cfr-work")
        self.assertEqual(words[words.index("--status-file") + 1], "$GITHUB_OUTPUT")

    def test_the_converged_upload_keeps_every_output(self) -> None:
        # Catches a converged output (the policy, support, solve record or
        # curve, or the certificates) left out of the uploaded artifact.
        upload = next(
            step
            for step in self.action["runs"]["steps"]
            if step.get("name") == "Preserve the converged outputs"
        )
        self.assertEqual(upload["if"], "steps.solve.outputs.status == 'converged'")
        self.assertEqual(upload["with"]["if-no-files-found"], "error")
        # Exactly these paths, so an exclusion (a `!` line) cannot drop one.
        paths = set(upload["with"]["path"].split())
        expected = {f"cfr-work/{name}" for name in CONVERGED_OUTPUTS}
        self.assertEqual(paths, expected | {"cfr-work/certificate-*.json"})

    def test_the_deadline_counts_from_the_job_start(self) -> None:
        # Catches a deadline not taken from the job's recorded start, or not
        # passed to the solve: the budget would then outrun the job's limit.
        for name in ("solve-first", "solve-continue"):
            first = self.jobs[name]["steps"][0]
            self.assertEqual(first["name"], "Record the job start")
            with tempfile.NamedTemporaryFile("r", suffix=".env") as environment:
                subprocess.run(
                    ["bash", "-e", "-c", first["run"]],
                    env={"GITHUB_ENV": environment.name, "PATH": "/usr/bin:/bin"},
                    check=True,
                )
                self.assertRegex(environment.read().strip(), r"^JOB_STARTED_AT=\d+$")
        steps = {step.get("name"): step for step in self.action["runs"]["steps"]}
        record = steps["Record the solve deadline"]
        with tempfile.NamedTemporaryFile("r", suffix=".env") as environment:
            subprocess.run(
                ["bash", "-e", "-c", record["run"]],
                env={
                    "JOB_STARTED_AT": "1000",
                    "STOP_MINUTES": "285",
                    "GITHUB_ENV": environment.name,
                },
                check=True,
            )
            self.assertEqual(
                environment.read().strip(), f"CFR_STOP_AT={1000 + 285 * 60}"
            )
        self.assertEqual(record["env"]["STOP_MINUTES"], "${{ inputs.stop-minutes }}")
        command = steps["Build the inputs and run the solve"]["run"]
        words = shlex.split(command.replace("\\\n", " "))
        self.assertEqual(words[words.index("--stop-at") + 1], "$CFR_STOP_AT")

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
            # Parsed, so a global option before the subcommand (as in
            # `git -C . SUBCOMMAND`) cannot hide it.
            self.assertNotIn("push", subcommands(command, "git"))
            self.assertFalse({"release", "api"} & set(subcommands(command, "gh")))
        self.assertNotIn("write", str(self.workflow["permissions"]))
        for job in self.jobs.values():
            self.assertNotIn("permissions", job)
        uploads = [step for step in steps if "upload-artifact@" in step.get("uses", "")]
        self.assertEqual(len(uploads), 4)
        for upload in uploads:
            self.assertEqual(upload["with"]["retention-days"], "30")


if __name__ == "__main__":
    unittest.main()
