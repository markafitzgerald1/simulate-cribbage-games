"""Guard the manual CFR bundle workflow without dispatching it."""

from pathlib import Path
import shlex
import subprocess
import unittest

from test_cfr_inputs_workflow import guard_accepts, load, subcommands

ROOT = Path(__file__).parent
WORKFLOW = ROOT / ".github/workflows/bundle-cfr-inputs.yml"
RELEASE_DRAFT = ROOT / "examples/generate-fixed-play-artifact.yml"
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
        # Catches removing the named shell: Actions' bash for an unnamed
        # shell ignores a failure before the last stage of a pipeline.
        self.assertEqual(self.workflow["defaults"], {"run": {"shell": "bash"}})
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
            bundle[bundle.index("--output") + 1], "fixed-play-policy-inputs"
        )

    def test_nothing_publishes(self) -> None:
        # Catches a release, push or write call slipped into any step.
        for step in self.steps:
            self.assertNotRegex(step.get("uses", ""), "release")
            command = step.get("run", "")
            self.assertNotIn("release", subcommands(command, "gh"))
            for verb in ("push", "tag", "commit"):
                self.assertNotIn(verb, subcommands(command, "git"))
            self.assertNotRegex(command, r"gh api .*(-X|--method)")


if __name__ == "__main__":
    unittest.main()
