"""Unit tests verifying GitHub Actions workflow gating and integrity."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
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


class TestDiagnosticWorkflow(unittest.TestCase):
    """Guard manual execution and evidence preservation without dispatching."""

    def test_manual_read_only_serial_job_keeps_upload_on_failure(self):
        path = Path(__file__).parent / ".github/workflows/diagnose-crib-v4.yml"
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow["on"]), {"workflow_dispatch"})
        self.assertEqual(
            workflow["permissions"], {"contents": "read", "actions": "read"}
        )
        self.assertEqual(len(workflow["jobs"]), 1)
        job = workflow["jobs"]["first-shard"]
        self.assertEqual(job["timeout-minutes"], "240")
        # The frozen 3.14.4 runtime has no Ubuntu 26.04 build.
        self.assertEqual(job["runs-on"], "ubuntu-24.04")
        runtime = next(s for s in job["steps"] if "setup-python@" in s.get("uses", ""))
        self.assertEqual(runtime["with"]["python-version"], "3.14.4")
        self.assertNotIn("strategy", job)
        upload = job["steps"][-1]
        self.assertEqual(upload["if"], "always()")
        self.assertTrue(upload["uses"].startswith("actions/upload-artifact@"))
        self.assertNotIn(
            "release", " ".join(step.get("uses", "") for step in job["steps"])
        )

    def test_input_retrieval_falls_back_after_asset_replacement(self):
        workflow = yaml.load(
            (
                Path(__file__).parent / ".github/workflows/diagnose-crib-v4.yml"
            ).read_text(),
            Loader=yaml.BaseLoader,
        )
        steps = workflow["jobs"]["first-shard"]["steps"]
        retrieve = next(
            step for step in steps if step.get("name", "").startswith("Retrieve")
        )
        self.assertTrue("verified_inputs" in retrieve["run"])
        download = retrieve["run"].split("# Every route")[0]
        fake = r"""import os, sys
from pathlib import Path
client = any('697897857' in value or 'client.json' in value for value in sys.argv)
content = 'client' if client else 'full'
if sys.argv[1] == 'api':
    if os.environ['IDS_AVAILABLE'] != 'yes':
        sys.exit(1)
    print(content, end='')
else:
    Path(sys.argv[sys.argv.index('--output') + 1]).write_text(content)
    with Path('fallbacks').open('a') as log:
        log.write(content + '\n')
"""
        for available in ("yes", "no"):
            with self.subTest(
                available=available
            ), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                gh = root / "gh"
                gh.write_text(f"#!{sys.executable}\n" + fake)
                gh.chmod(0o700)
                result = subprocess.run(
                    ["bash", "-e", "-c", download],
                    cwd=root,
                    env={
                        **os.environ,
                        "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                        "IDS_AVAILABLE": available,
                    },
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((root / "inputs/full.json").read_text(), "full")
                self.assertEqual((root / "inputs/client.json").read_text(), "client")
                self.assertEqual((root / "fallbacks").exists(), available == "no")

    def test_resume_validation_precedes_restore_and_uses_environment_input(self):
        workflow = yaml.load(
            (
                Path(__file__).parent / ".github/workflows/diagnose-crib-v4.yml"
            ).read_text(),
            Loader=yaml.BaseLoader,
        )
        steps = workflow["jobs"]["first-shard"]["steps"]
        names = [step.get("name") for step in steps]
        validate = names.index("Verify resume run provenance")
        restore = names.index("Restore compatible per-group checkpoints")
        measure = names.index("Measure the declared first shard")
        self.assertLess(validate, restore)
        self.assertLess(restore, measure)
        self.assertTrue(
            'validate_resume_run(json.load(sys.stdin), os.environ["GITHUB_REPOSITORY"])'
            in steps[validate]["run"]
        )
        self.assertTrue('[[ "$RESUME_RUN_ID" =~ ^[0-9]+$ ]]' in steps[validate]["run"])
        self.assertEqual(
            steps[validate]["env"]["RESUME_RUN_ID"], "${{ inputs.resume_run_id }}"
        )
        self.assertFalse(
            any("${{ inputs.resume_run_id }}" in step.get("run", "") for step in steps)
        )


class TestSurveyWorkflow(unittest.TestCase):
    """Check budget and isolation in the actual committed workflow."""

    def test_budget_parallelism_resume_and_always_upload(self):
        path = Path(__file__).parent / ".github/workflows/survey-crib-v4.yml"
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow["on"]), {"workflow_dispatch"})
        self.assertEqual(
            workflow["permissions"], {"contents": "read", "actions": "read"}
        )
        self.assertNotIn("concurrency", workflow)
        self.assertEqual(len(workflow["jobs"]), 1)
        job = workflow["jobs"]["survey-shard"]
        self.assertEqual(job["strategy"]["matrix"]["shard"], ["1", "2", "3", "4"])
        self.assertEqual(job["strategy"]["max-parallel"], "4")
        self.assertEqual(job["strategy"]["fail-fast"], "false")
        self.assertEqual(job["timeout-minutes"], "330")
        self.assertEqual(job["runs-on"], "ubuntu-24.04")
        self.assertTrue("${{ matrix.shard }}" in job["concurrency"]["group"])
        self.assertEqual(job["concurrency"]["cancel-in-progress"], "false")
        steps = job["steps"]
        self.assertTrue("300 * 60" in steps[0]["run"])
        runtime = next(s for s in steps if "setup-python@" in s.get("uses", ""))
        self.assertEqual(runtime["with"]["python-version"], "3.14.4")
        names = [s.get("name") for s in steps]
        validate = names.index("Verify resume run provenance")
        restore = names.index("Restore compatible per-group checkpoints")
        measure = names.index("Measure the declared survey shard")
        self.assertLess(validate, restore)
        self.assertLess(restore, measure)
        self.assertTrue(
            "scripts.run_crib_v4_survey import validate_resume_run"
            in steps[validate]["run"]
        )
        self.assertTrue('[[ "$RESUME_RUN_ID" =~ ^[0-9]+$ ]]' in steps[validate]["run"])
        self.assertTrue('--shard "${{ matrix.shard }}"' in steps[measure]["run"])
        self.assertTrue(
            "exec python -u -m scripts.run_crib_v4_survey" in steps[measure]["run"]
        )
        upload = steps[-1]
        self.assertEqual(upload["if"], "always()")
        self.assertEqual(upload["with"]["retention-days"], "30")
        self.assertEqual(
            upload["with"]["name"], "crib-v4-survey-shard-${{ matrix.shard }}"
        )
        self.assertEqual(steps[restore]["with"]["name"], upload["with"]["name"])
        self.assertTrue(upload["uses"].startswith("actions/upload-artifact@"))
        self.assertFalse(any("release" in s.get("uses", "") for s in steps))
        self.assertFalse(
            any("${{ inputs.resume_run_id }}" in s.get("run", "") for s in steps)
        )


if __name__ == "__main__":
    unittest.main()
