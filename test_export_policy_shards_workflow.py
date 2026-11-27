"""Guard the manual policy shard export workflow without dispatching it."""

from pathlib import Path
import subprocess
import unittest

from test_cfr_inputs_workflow import guard_accepts, load, subcommands

ROOT = Path(__file__).parent
WORKFLOW = ROOT / ".github/workflows/export-policy-shards.yml"
MEASURE = ROOT / ".github/workflows/measure-fixed-play.yml"
APPROVED = {
    "github.event_name": "workflow_dispatch",
    "github.ref": "refs/heads/main",
    "github.run_attempt": "1",
    "inputs.approval": "shards",
}
EXPORT = r"""python -m artifact_pipeline.export_policy_shards \
  --policy-manifest inputs/policy.json \
  --policy-manifest-sha256 "$MANIFEST_SHA256" \
  --output shards | tee -a "$GITHUB_STEP_SUMMARY"
"""


class ExportPolicyShardsWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = load(WORKFLOW)
        self.job = self.workflow["jobs"]["export"]
        self.steps = self.job["steps"]
        self.names = [step.get("name", step.get("uses")) for step in self.steps]

    def step(self, name: str) -> dict:
        return self.steps[self.names.index(name)]

    def test_manual_dispatch_only_and_nothing_can_publish(self) -> None:
        # Catches another trigger, an optional confirmation, a write
        # permission, a release or environment, or a second job.
        self.assertEqual(set(self.workflow["on"]), {"workflow_dispatch"})
        inputs = self.workflow["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(set(inputs), {"approval"})
        self.assertEqual(inputs["approval"]["required"], "true")
        self.assertNotIn("default", inputs["approval"])
        self.assertEqual(
            self.workflow["permissions"], {"contents": "read", "actions": "read"}
        )
        self.assertEqual(set(self.workflow["jobs"]), {"export"})
        for key in ("permissions", "environment"):
            self.assertNotIn(key, self.job)
        for step in self.steps:
            self.assertNotRegex(step.get("uses", ""), "release")
            self.assertEqual(subcommands(step.get("run", ""), "gh"), [])
        self.assertEqual(self.workflow["concurrency"]["cancel-in-progress"], "false")

    def test_every_step_runs_in_order_and_none_can_be_skipped(self) -> None:
        # Catches a skipped or tolerated step, another checkout ref, or a
        # shell that would not fail a piped export.
        self.assertEqual(
            self.names,
            [
                "Require main exactly",
                "actions/checkout@v7",
                "actions/setup-python@v7",
                "Install pinned dependencies",
                "Bootstrap the tally shelf",
                "Read the pinned inputs",
                "Download the pinned fixed inputs",
                "Export the shards",
                "Preserve the shards and their index",
            ],
        )
        for step in self.steps:
            with self.subTest(step=step.get("name", step.get("uses"))):
                self.assertNotIn("if", step)
                self.assertNotIn("continue-on-error", step)
                self.assertNotIn("shell", step)
        self.assertNotIn("with", self.step("actions/checkout@v7"))
        self.assertNotIn("continue-on-error", self.job)
        self.assertEqual(self.workflow["defaults"], {"run": {"shell": "bash"}})

    def test_the_job_requires_the_approved_first_attempt_on_main(self) -> None:
        # Catches a guard that drops one condition, or the exact main check.
        self.assertTrue(guard_accepts(self.job["if"], APPROVED))
        deviations = {
            "github.event_name": "push",
            "github.ref": "refs/heads/feature",
            "github.run_attempt": "2",
            "inputs.approval": "measure",
        }
        for key, value in deviations.items():
            with self.subTest(key=key):
                self.assertFalse(
                    guard_accepts(self.job["if"], {**APPROVED, key: value})
                )
        self.assertEqual(self.names[0], "Require main exactly")
        for ref, accepted in (("refs/heads/main", True), ("refs/heads/Main", False)):
            result = subprocess.run(
                ["bash", "-e", "-c", self.steps[0]["run"]],
                env={"GITHUB_REF": ref},
                check=False,
            )
            self.assertEqual(result.returncode == 0, accepted, ref)

    def test_inputs_are_the_measured_tables_pins(self) -> None:
        # Catches a bundle read from anything but the committed pins, or a
        # pin step that drifts from the one the measured table was made with.
        measure = {
            step.get("name"): step for step in load(MEASURE)["jobs"]["measure"]["steps"]
        }
        self.assertEqual(
            self.step("Download the pinned fixed inputs"),
            measure["Download the pinned fixed inputs"],
        )
        pins = self.step("Read the pinned inputs")
        self.assertEqual(pins["id"], "pins")
        # The measurement's step also fixes a timestamp; the rest must match.
        measured = measure["Read the pinned inputs and fix the timestamp"]["run"]
        self.assertTrue(measured.endswith(pins["run"]))

    def test_the_export_command_is_the_approved_one(self) -> None:
        # Catches an unpinned digest or a summary the job log would not show.
        export = self.step("Export the shards")
        self.assertEqual(export["run"], EXPORT)
        self.assertEqual(
            export["env"],
            {"MANIFEST_SHA256": "${{ steps.pins.outputs.manifest_sha256 }}"},
        )
        self.assertEqual(self.names[-1], "Preserve the shards and their index")
        self.assertEqual(
            self.steps[-1]["with"],
            {
                "name": "pegging-policy-shards",
                "if-no-files-found": "error",
                "retention-days": "90",
                "path": "shards/",
            },
        )


if __name__ == "__main__":
    unittest.main()
