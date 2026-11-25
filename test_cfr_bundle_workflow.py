"""Guard the manual CFR bundle workflow without dispatching it."""

from pathlib import Path
import shlex
import subprocess
import unittest

from test_cfr_inputs_workflow import guard_accepts, load, subcommands

ROOT = Path(__file__).parent
WORKFLOW = ROOT / ".github/workflows/bundle-cfr-inputs.yml"
RELEASE_DRAFT = ROOT / "examples/generate-fixed-play-artifact.yml"
# The lookup must name the source run's one prior job, or fail.
LOOKUP_PRIOR_JOB = (
    'job="$(gh api'
    ' "repos/$GITHUB_REPOSITORY/actions/runs/$SOURCE_RUN_ID/attempts/1/jobs"'
    ' --jq \'[.jobs[] | select(.name == "prior")] | if length == 1'
    ' then .[0].id else error("expected one prior job") end\')"'
)

APPROVED = {
    "github.event_name": "workflow_dispatch",
    "github.ref": "refs/heads/main",
    "github.run_attempt": "1",
    "inputs.approval": "bundle",
}


class CfrBundleWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = load(WORKFLOW)
        self.job = self.workflow["jobs"]["bundle"]
        self.steps = self.job["steps"]
        self.names = [step.get("name", step.get("uses")) for step in self.steps]

    def step(self, name: str) -> dict:
        return self.steps[self.names.index(name)]

    def test_manual_dispatch_only_with_read_permissions(self) -> None:
        # Catches a trigger other than dispatch, a write permission, or the
        # typed confirmation or source run made optional or defaulted.
        self.assertEqual(set(self.workflow["on"]), {"workflow_dispatch"})
        inputs = self.workflow["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(set(inputs), {"approval", "source_run_id"})
        for value in inputs.values():
            self.assertEqual(value["required"], "true")
            self.assertEqual(value["type"], "string")
            self.assertNotIn("default", value)
        self.assertEqual(
            self.workflow["permissions"], {"contents": "read", "actions": "read"}
        )
        self.assertNotIn("permissions", self.job)
        self.assertEqual(self.workflow["concurrency"]["cancel-in-progress"], "false")

    def test_the_job_requires_the_approved_first_attempt_on_main(self) -> None:
        # Catches a guard that drops one condition: each deviation alone must
        # stop the job, so a re-run or a branch dispatch does nothing.
        self.assertTrue(guard_accepts(self.job["if"], APPROVED))
        deviations = {
            "github.event_name": "push",
            "github.ref": "refs/heads/feature",
            "github.run_attempt": "2",
            "inputs.approval": "generate",
        }
        for key, value in deviations.items():
            with self.subTest(key=key):
                self.assertFalse(
                    guard_accepts(self.job["if"], {**APPROVED, key: value})
                )

    def test_exact_checks_come_first(self) -> None:
        # Catches dropping the exact main check that the case-insensitive
        # guard needs, or the numeric check on the run id that every later
        # step passes to the API and to the downloads.
        self.assertEqual(
            self.names[:2], ["Require main exactly", "Require a numeric source run id"]
        )
        cases = (
            (0, {"GITHUB_REF": "refs/heads/main"}, True),
            (0, {"GITHUB_REF": "refs/heads/Main"}, False),
            (1, {"SOURCE_RUN_ID": "45322543914"}, True),
            (1, {"SOURCE_RUN_ID": "4532 --paginate"}, False),
            (1, {"SOURCE_RUN_ID": "../runs"}, False),
            (1, {"SOURCE_RUN_ID": ""}, False),
        )
        for index, environment, accepted in cases:
            with self.subTest(environment=environment):
                result = subprocess.run(
                    ["bash", "-e", "-c", self.steps[index]["run"]],
                    env=environment,
                    check=False,
                )
                self.assertEqual(result.returncode == 0, accepted)

    def test_a_failed_check_piped_into_tee_fails_its_step(self) -> None:
        # Catches removing the named shell, or overriding it for the job:
        # Actions' bash for an unnamed shell, and sh, ignore a failure
        # before the last stage of a pipeline.
        self.assertEqual(self.workflow["defaults"], {"run": {"shell": "bash"}})
        self.assertNotIn("defaults", self.job)
        for step in self.steps:
            self.assertNotIn("shell", step)

    def test_everything_is_checked_before_the_bundle(self) -> None:
        # Catches bundling before any check, or checking only some sources.
        bundle = self.names.index("Bundle the measurement inputs")
        for name in (
            "Check the source run",
            "Rebuild the menus and offsets against their pins",
            "Match the downloads to the source run's evidence",
        ):
            self.assertLess(self.names.index(name), bundle, name)
        self.assertLess(
            self.names.index("Rebuild the menus and offsets against their pins"),
            self.names.index("Match the downloads to the source run's evidence"),
        )
        for step in self.steps:
            self.assertNotIn("if", step)
            self.assertNotIn("continue-on-error", step)
        self.assertNotIn("continue-on-error", self.job)

    def test_the_source_run_is_checked_before_any_download(self) -> None:
        # Catches a source check that only echoes its command, or that runs
        # after something has been downloaded from an unchecked run.
        check = self.names.index("Check the source run")
        for index, step in enumerate(self.steps):
            if step.get("uses", "").startswith("actions/download-artifact"):
                self.assertLess(check, index, self.names[index])
        lines = (
            self.step("Check the source run")["run"].replace("\\\n", " ").splitlines()
        )
        self.assertEqual(
            [shlex.split(line)[:4] for line in lines],
            [
                [
                    "gh",
                    "api",
                    "repos/$GITHUB_REPOSITORY/actions/runs/$SOURCE_RUN_ID",
                    ">",
                ],
                ["python", "-m", "scripts.check_cfr_bundle_sources", "source-run"],
            ],
        )
        command = shlex.split(lines[1])
        self.assertEqual(command[command.index("--run-json") + 1], "source-run.json")
        self.assertEqual(
            command[command.index("--repository") + 1], "$GITHUB_REPOSITORY"
        )

    def test_the_population_is_matched_to_the_prior_job_log(self) -> None:
        # Catches skipping the log check, echoing it, or checking another
        # job's log: nothing else ties the population to the source run.
        names = self.names
        check = names.index("Match the population to the prior job's log")
        for name in (
            "Download the prior",
            "Match the downloads to the source run's evidence",
        ):
            self.assertLess(names.index(name), check, name)
        self.assertLess(check, names.index("Bundle the measurement inputs"))
        lines = self.steps[check]["run"].replace("\\\n", " ").splitlines()
        self.assertEqual(lines[0].strip(), LOOKUP_PRIOR_JOB)
        fetch, verify = (shlex.split(line) for line in lines[2:])
        self.assertEqual(fetch[:2], ["curl", "--fail"])
        # Without --location curl saves the redirect's empty body, and
        # without the token the API refuses the log.
        self.assertTrue("--location" in fetch, fetch)
        self.assertEqual(
            fetch[fetch.index("--header") + 1], "Authorization: Bearer $GH_TOKEN"
        )
        # Single quotes would send the literal text $GH_TOKEN.
        header = '--header "Authorization: Bearer $GH_TOKEN"'
        self.assertTrue(header in lines[2], lines[2])
        self.assertEqual(fetch[fetch.index("--output") + 1], "prior-job.log")
        self.assertEqual(
            fetch[-1], "$GITHUB_API_URL/repos/$GITHUB_REPOSITORY/actions/jobs/$job/logs"
        )
        self.assertEqual(
            verify[:4],
            ["python", "-m", "scripts.check_cfr_bundle_sources", "prior-log"],
        )
        self.assertEqual(verify[verify.index("--log") + 1], "prior-job.log")
        self.assertEqual(verify[verify.index("--prior-dir") + 1], "cfr-prior")

    def test_the_prior_is_rebuilt_from_the_population(self) -> None:
        # Catches skipping the rebuild or the comparison: the population is
        # not in the solve's evidence, and only this ties it to the prior.
        names = self.names
        rebuild = names.index("Rebuild the prior from the population")
        self.assertLess(
            names.index("Match the downloads to the source run's evidence"), rebuild
        )
        self.assertLess(rebuild, names.index("Bundle the measurement inputs"))
        lines = self.steps[rebuild]["run"].replace("\\\n", " ").splitlines()
        build, compare = (shlex.split(line) for line in lines)
        self.assertEqual(
            build[:4], ["python", "-u", "artifact_pipeline/cfr_prior.py", "prior"]
        )
        self.assertEqual(
            build[build.index("--population") + 1], "cfr-prior/population.json"
        )
        self.assertEqual(build[build.index("--output") + 1], "rebuilt-prior.bin")
        self.assertEqual(compare, ["cmp", "rebuilt-prior.bin", "cfr-prior/prior.bin"])

    def test_the_checks_run_the_real_commands(self) -> None:
        # Catches a check that only echoes its command, or checks the wrong
        # folder, so nothing would stop a mismatched bundle.
        source = shlex.split(
            self.step("Check the source run")["run"].replace("\\\n", " ")
        )
        self.assertEqual(
            source[source.index("scripts.check_cfr_bundle_sources") + 1], "source-run"
        )
        self.assertEqual(source[:2], ["gh", "api"])
        rebuild = shlex.split(
            self.step("Rebuild the menus and offsets against their pins")[
                "run"
            ].replace("\\\n", " ")
        )
        self.assertEqual(
            rebuild[:6],
            [
                "python",
                "-u",
                "-m",
                "scripts.run_cfr_inputs",
                "build-inputs",
                "--binary",
            ],
        )
        self.assertEqual(rebuild[rebuild.index("--output") + 1], "cfr-work")
        match = shlex.split(
            self.step("Match the downloads to the source run's evidence")[
                "run"
            ].replace("\\\n", " ")
        )
        self.assertEqual(
            match[:4], ["python", "-m", "scripts.check_cfr_bundle_sources", "sources"]
        )
        for option, folder in (
            ("--work", "cfr-work"),
            ("--prior-dir", "cfr-prior"),
            ("--evidence", "cfr-evidence"),
        ):
            self.assertEqual(match[match.index(option) + 1], folder)

    def test_downloads_come_from_the_named_source_run(self) -> None:
        # Catches a download from this run (no run id), from a hard-coded
        # run, or into the wrong folder for the checks and the bundler.
        expected = {
            "Download the prior": ("name", "cfr-prior", "cfr-prior"),
            "Download the converged outputs": ("name", "cfr-inputs", "cfr-work"),
            "Download the solve evidence": (
                "pattern",
                "cfr-evidence-*",
                "cfr-evidence",
            ),
        }
        for name, (key, artifact, path) in expected.items():
            with self.subTest(step=name):
                step = self.step(name)
                self.assertEqual(step["uses"], "actions/download-artifact@v8")
                self.assertEqual(step["with"][key], artifact)
                self.assertEqual(step["with"]["path"], path)
                self.assertEqual(step["with"]["run-id"], "${{ inputs.source_run_id }}")
                self.assertEqual(step["with"]["github-token"], "${{ github.token }}")
        self.assertEqual(
            self.step("Download the solve evidence")["with"]["merge-multiple"], "true"
        )

    def test_the_upload_is_what_the_release_draft_downloads(self) -> None:
        # Catches a name or folder the inert release draft would not find.
        upload = self.step("Preserve the bundle")
        self.assertEqual(upload["uses"], "actions/upload-artifact@v7")
        self.assertEqual(upload["with"]["name"], "fixed-play-policy-inputs")
        self.assertEqual(upload["with"]["path"], "fixed-play-policy-inputs/")
        self.assertEqual(upload["with"]["if-no-files-found"], "error")
        draft = load(RELEASE_DRAFT)["jobs"]["generate-table"]["steps"]
        download = next(
            step
            for step in draft
            if step.get("name") == "Download the pinned fixed inputs"
        )
        self.assertEqual(download["with"]["name"], upload["with"]["name"])
        bundle = shlex.split(
            self.step("Bundle the measurement inputs")["run"].replace("\\\n", " ")
        )
        self.assertEqual(
            bundle[:4],
            ["python", "-u", "-m", "artifact_pipeline.bundle_fixed_play_inputs"],
        )
        for option, folder in (
            ("--work", "cfr-work"),
            ("--prior-dir", "cfr-prior"),
            ("--output", "fixed-play-policy-inputs"),
        ):
            self.assertEqual(bundle[bundle.index(option) + 1], folder)

    def test_inputs_reach_commands_only_through_the_step_environment(self) -> None:
        # Catches a run id hard-coded where the numeric check reads it, an
        # input expanded straight into a script, or an API call that lost
        # its token: each step that names a value must bind it here.
        bindings = {
            "$SOURCE_RUN_ID": ("SOURCE_RUN_ID", "${{ inputs.source_run_id }}"),
            "$GH_TOKEN": ("GH_TOKEN", "${{ github.token }}"),
        }
        for name, step in zip(self.names, self.steps):
            command = step.get("run", "")
            with self.subTest(step=name):
                self.assertNotIn("${{", command)
                uses_api = bool(subcommands(command, "gh")) or "curl" in command
                for variable, (key, value) in bindings.items():
                    if variable in command or (key == "GH_TOKEN" and uses_api):
                        self.assertEqual(step["env"][key], value)

    def test_nothing_publishes(self) -> None:
        # Catches a release, push or write call slipped into any step: a
        # git write, a release, or an API call that sends data.
        for step in self.steps:
            self.assertNotRegex(step.get("uses", ""), "release")
            command = step.get("run", "").replace("\\\n", " ")
            self.assertNotIn("release", subcommands(command, "gh"))
            for verb in ("push", "tag", "commit"):
                self.assertNotIn(verb, subcommands(command, "git"))
            self.assertNotRegex(
                command,
                r"gh api.*\s(-X|--method|-[fF]|--field|--raw-field|--input)",
            )
            self.assertNotRegex(
                command,
                r"curl.*\s(-X|--request|-d|--data|--json|-F|--form|-T|--upload)",
            )


if __name__ == "__main__":
    unittest.main()
