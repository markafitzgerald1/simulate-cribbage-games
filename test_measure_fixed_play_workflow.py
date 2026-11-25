"""Guard the manual fixed-policy measurement workflow without dispatching it."""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from test_cfr_inputs_workflow import guard_accepts, load, subcommands

ROOT = Path(__file__).parent
WORKFLOW = ROOT / ".github/workflows/measure-fixed-play.yml"
BUNDLE = ROOT / ".github/workflows/bundle-cfr-inputs.yml"
PINS = ROOT / "examples/fixed-play-inputs.json"
APPROVED = {
    "github.event_name": "workflow_dispatch",
    "github.ref": "refs/heads/main",
    "github.run_attempt": "1",
    "inputs.approval": "measure",
}
MEASURE = r"""exec python -u -m artifact_pipeline.measure_fixed_play_table \
  --policy-manifest inputs/policy.json \
  --policy-manifest-sha256 "$MANIFEST_SHA256" \
  --generated-at "$GENERATED_AT" --checkpoint-dir cells \
  --workers 4 --samples 13000 --seed 42 --promotion-gate enforce
"""


class MeasureFixedPlayWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = load(WORKFLOW)
        self.job = self.workflow["jobs"]["measure"]
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
        self.assertEqual(set(self.workflow["jobs"]), {"measure"})
        for key in ("permissions", "environment", "env", "defaults"):
            self.assertNotIn(key, self.job)
        for step in self.steps:
            self.assertNotRegex(step.get("uses", ""), "release")
            self.assertEqual(subcommands(step.get("run", ""), "gh"), [])
        self.assertEqual(self.workflow["concurrency"]["cancel-in-progress"], "false")
        self.assertEqual(self.workflow["defaults"], {"run": {"shell": "bash"}})

    def test_the_job_requires_the_approved_first_attempt_on_main(self) -> None:
        # Catches a guard that drops one condition, or the exact main check.
        self.assertTrue(guard_accepts(self.job["if"], APPROVED))
        deviations = {
            "github.event_name": "push",
            "github.ref": "refs/heads/feature",
            "github.run_attempt": "2",
            "inputs.approval": "bundle",
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

    def read_pins(self, pins: dict) -> tuple[int, dict[str, str]]:
        """Run the pin step against a pins file, as the job would."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "examples").mkdir()
            (root / "examples/fixed-play-inputs.json").write_text(json.dumps(pins))
            output = root / "output"
            output.touch()
            result = subprocess.run(
                ["bash", "-e", "-c", self.step(self.names[4])["run"]],
                cwd=root,
                env={**os.environ, "GITHUB_OUTPUT": str(output)},
                stderr=subprocess.DEVNULL,
                check=False,
            )
            lines = output.read_text().splitlines()
        return result.returncode, dict(line.split("=", 1) for line in lines)

    def test_the_measurement_uses_the_committed_pins(self) -> None:
        # Catches unpinned inputs accepted, a pin read wrong, an input
        # downloaded from another run, or a digest that is not the pin.
        pins = json.loads(PINS.read_text(encoding="utf-8"))
        self.assertRegex(str(pins["input_run_id"]), r"\A\d+\Z")
        self.assertRegex(pins["policy_manifest_sha256"], r"\A[0-9a-f]{64}\Z")
        code, outputs = self.read_pins(pins)
        self.assertEqual(code, 0)
        self.assertEqual(outputs["run_id"], str(pins["input_run_id"]))
        self.assertEqual(outputs["manifest_sha256"], pins["policy_manifest_sha256"])
        self.assertRegex(
            outputs["generated_at"], r"\A\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\Z"
        )
        for key in ("input_run_id", "policy_manifest_sha256"):
            with self.subTest(unpinned=key):
                self.assertNotEqual(self.read_pins({**pins, key: None})[0], 0)
        self.assertEqual(self.steps[4]["id"], "pins")
        download = self.step("Download the pinned fixed inputs")
        self.assertEqual(
            download["with"],
            {
                "name": "fixed-play-policy-inputs",
                "path": "inputs",
                "github-token": "${{ github.token }}",
                "run-id": "${{ steps.pins.outputs.run_id }}",
            },
        )
        uploads = [
            step["with"]["name"]
            for step in load(BUNDLE)["jobs"]["bundle"]["steps"]
            if step.get("uses", "").startswith("actions/upload-artifact")
        ]
        self.assertEqual(uploads, [download["with"]["name"]])

    def test_the_measurement_command_is_the_approved_one(self) -> None:
        # Catches a changed sample count, seed or gate mode, or a lost pin.
        measure = self.step("Measure the fixed policy in four workers")
        self.assertEqual(measure["run"], MEASURE)
        self.assertEqual(
            measure["env"],
            {
                "MANIFEST_SHA256": "${{ steps.pins.outputs.manifest_sha256 }}",
                "GENERATED_AT": "${{ steps.pins.outputs.generated_at }}",
            },
        )

    def test_the_table_is_verified_before_it_is_kept(self) -> None:
        # Catches a check dropped, weakened, or moved after the upload.
        order = [
            "Measure the fixed policy in four workers",
            "Check the offline reference and record regression",
            "Export and verify companions",
            "Preserve the measured table and companions",
            "Preserve an unfinished run",
        ]
        self.assertEqual(self.names[-5:], order)
        for flag in ("--fail-on-regression", "--write-metadata"):
            self.assertTrue(flag in self.step(order[1])["run"].split(), flag)
        verify = self.step(order[2])
        self.assertEqual(
            verify["env"],
            {"MANIFEST_SHA256": "${{ steps.pins.outputs.manifest_sha256 }}"},
        )
        upload = self.step(order[3])["with"]
        self.assertEqual(upload["name"], "expected-play-points-fixed")
        self.assertEqual(
            upload["path"].split(),
            [
                f"expected_play_points{kind}"
                for kind in (
                    ".json",
                    ".client.json",
                    ".uncertainty.json",
                    ".lines.json",
                    ".gate.md",
                )
            ],
        )
        self.assertRegex(
            verify["run"],
            r'verify_fixed_play_bundle \\\n  --policy-manifest-sha256 "\$MANIFEST_SHA256" --release-samples 13000\n',
        )
        self.assertRegex(verify["run"], r'(?m)^test "\$before" = "\$after"$')
        for step in self.steps[:-1]:
            for key in ("if", "continue-on-error"):
                self.assertNotIn(key, step)

    def test_a_run_out_of_time_still_keeps_its_cells(self) -> None:
        # Catches a step limit that leaves no room before the job's, a job
        # limit past the hosted ceiling, or unfinished work not uploaded.
        limit = int(self.job["timeout-minutes"])
        measure = self.step("Measure the fixed policy in four workers")
        self.assertLessEqual(limit, 360)
        self.assertLessEqual(int(measure["timeout-minutes"]), limit - 25)
        unfinished = self.steps[-1]
        self.assertEqual(unfinished["if"], "failure() || cancelled()")
        # Not cells/ itself: a worker's temporary file can vanish mid-upload.
        self.assertTrue("cells/*.json" in unfinished["with"]["path"].split())
        match = re.search(r"--checkpoint-dir (\S+)", MEASURE)
        self.assertEqual(match and match[1], "cells")


if __name__ == "__main__":
    unittest.main()
