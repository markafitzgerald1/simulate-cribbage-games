"""Guard the manual CFR bundle workflow without dispatching it."""

from pathlib import Path
import shlex
import subprocess
import unittest

from test_cfr_inputs_workflow import guard_accepts, load, subcommands

ROOT = Path(__file__).parent
WORKFLOW = ROOT / ".github/workflows/bundle-cfr-inputs.yml"
MEASURE = ROOT / ".github/workflows/measure-fixed-play.yml"
# Every step that calls the API or takes the run id, with its exact script
# and environment. Parsed matching missed quoting, repeated options,
# redirects and write flags spelled another way; exact text cannot.
TOKEN = {"GH_TOKEN": "${{ github.token }}"}
RUN_ID = {"SOURCE_RUN_ID": "${{ inputs.source_run_id }}"}
LOOKUP_PRIOR_JOB = (
    'job="$(gh api'
    ' "repos/$GITHUB_REPOSITORY/actions/runs/$SOURCE_RUN_ID/attempts/1/jobs"'
    ' --jq \'[.jobs[] | select(.name == "prior")] | if length == 1'
    ' then .[0].id else error("expected one prior job") end\')"\n'
)
EXACT_STEPS = {
    "Require a numeric source run id": (RUN_ID, '[[ "$SOURCE_RUN_ID" =~ ^[0-9]+$ ]]'),
    "Check the source run": (
        TOKEN | RUN_ID,
        r"""gh api "repos/$GITHUB_REPOSITORY/actions/runs/$SOURCE_RUN_ID" > source-run.json
python -m scripts.check_cfr_bundle_sources source-run \
  --run-json source-run.json --repository "$GITHUB_REPOSITORY" \
  | tee -a "$GITHUB_STEP_SUMMARY"
""",
    ),
    # The lookup must name the source run's one prior job, or fail. The log
    # needs --location: without it curl saves the redirect's empty body.
    "Match the population to the prior job's log": (
        TOKEN | RUN_ID,
        LOOKUP_PRIOR_JOB
        + r"""# curl, not gh: newer gh refuses a log's terminal escape codes.
curl --fail --silent --show-error --location \
  --header "Authorization: Bearer $GH_TOKEN" \
  --output prior-job.log \
  "$GITHUB_API_URL/repos/$GITHUB_REPOSITORY/actions/jobs/$job/logs"
python -m scripts.check_cfr_bundle_sources prior-log \
  --log prior-job.log --prior-dir cfr-prior \
  | tee -a "$GITHUB_STEP_SUMMARY"
""",
    ),
    "Bundle the measurement inputs": (
        RUN_ID,
        r"""python -u -m artifact_pipeline.bundle_fixed_play_inputs \
  --work cfr-work --prior-dir cfr-prior --output fixed-play-policy-inputs \
  | tee bundle.txt
{
  echo "Source run: $SOURCE_RUN_ID"
  echo "Pin input_run_id: $GITHUB_RUN_ID"
  grep '^policy_manifest_sha256=' bundle.txt
} >> "$GITHUB_STEP_SUMMARY"
""",
    ),
}

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
        # Catches something downloaded from an unchecked run.
        check = self.names.index("Check the source run")
        for index, step in enumerate(self.steps):
            if step.get("uses", "").startswith("actions/download-artifact"):
                self.assertLess(check, index, self.names[index])

    def test_the_population_is_matched_to_the_prior_job_log(self) -> None:
        # Catches skipping the log check or running it too late: nothing
        # else ties the population to the source run.
        names = self.names
        check = names.index("Match the population to the prior job's log")
        for name in (
            "Download the prior",
            "Match the downloads to the source run's evidence",
        ):
            self.assertLess(names.index(name), check, name)
        self.assertLess(check, names.index("Bundle the measurement inputs"))

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
        # run, or into the wrong folder for the checks and the bundler, and
        # an input that overrides another, as a name does a pattern.
        source = {
            "github-token": "${{ github.token }}",
            "run-id": "${{ inputs.source_run_id }}",
        }
        expected = {
            "Download the prior": {"name": "cfr-prior", "path": "cfr-prior"},
            "Download the converged outputs": {
                "name": "cfr-inputs",
                "path": "cfr-work",
            },
            "Download the solve evidence": {
                "pattern": "cfr-evidence-*",
                "merge-multiple": "true",
                "path": "cfr-evidence",
            },
        }
        for name, inputs in expected.items():
            with self.subTest(step=name):
                step = self.step(name)
                self.assertEqual(step["uses"], "actions/download-artifact@v8")
                self.assertEqual(step["with"], inputs | source)

    def test_the_upload_is_what_the_release_draft_downloads(self) -> None:
        # Catches a name or folder the inert release draft would not find.
        upload = self.step("Preserve the bundle")
        self.assertEqual(upload["uses"], "actions/upload-artifact@v7")
        self.assertEqual(upload["with"]["name"], "fixed-play-policy-inputs")
        self.assertEqual(upload["with"]["path"], "fixed-play-policy-inputs/")
        self.assertEqual(upload["with"]["if-no-files-found"], "error")
        measure = load(MEASURE)["jobs"]["measure"]["steps"]
        download = next(
            step
            for step in measure
            if step.get("name") == "Download the pinned fixed inputs"
        )
        self.assertEqual(download["with"]["name"], upload["with"]["name"])

    def test_steps_using_the_api_or_the_run_id_run_exactly_this(self) -> None:
        # Catches any change to what the run id and token reach: a run id
        # hard-coded where the numeric check reads it, an input expanded
        # into a script, a lost token, a repeated or differently quoted
        # argument, a check that only echoes, or a read turned into a write.
        # Each name must be unique, or a second step of that name escapes.
        self.assertEqual(len(set(self.names)), len(self.names))
        for name, (environment, command) in EXACT_STEPS.items():
            with self.subTest(step=name):
                self.assertEqual(self.step(name)["env"], environment)
                self.assertEqual(self.step(name)["run"], command)
        for name, step in zip(self.names, self.steps):
            if name not in EXACT_STEPS:
                with self.subTest(step=name):
                    self.assertNotIn("env", step)
                    self.assertNotRegex(
                        step.get("run", ""),
                        r"\b(gh|curl|GH_TOKEN|SOURCE_RUN_ID)\b|\$\{\{",
                    )
        self.assertNotIn("env", self.job)
        self.assertNotIn("env", self.workflow)

    def test_nothing_publishes(self) -> None:
        # Catches a release or a git write slipped into any step. The exact
        # API steps above rule out a call that sends data.
        for step in self.steps:
            self.assertNotRegex(step.get("uses", ""), "release")
            command = step.get("run", "").replace("\\\n", " ")
            self.assertNotIn("release", subcommands(command, "gh"))
            for verb in ("push", "tag", "commit"):
                self.assertNotIn(verb, subcommands(command, "git"))


if __name__ == "__main__":
    unittest.main()
