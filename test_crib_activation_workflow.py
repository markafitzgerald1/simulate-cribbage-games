"""Check draft activation and rollback boundaries without dispatching."""

import json
from pathlib import Path
import subprocess
import unittest

import yaml  # type: ignore[import-untyped]

from test_v4_shard_workflow import guard_accepts

ROOT = Path(__file__).parent
WORKFLOWS = ROOT / ".github" / "workflows"


class TestCribActivationWorkflow(unittest.TestCase):
    def require_fragment(self, fragment, text):
        self.assertTrue(fragment in text, f"missing {fragment!r}")

    def test_approved_activation_call_passes_each_reusable_sampling_guard(self):
        caller = yaml.safe_load((WORKFLOWS / "activate-crib-v4.yml").read_text())
        measure = caller["jobs"]["measure"]
        self.assertEqual(measure["uses"], "./.github/workflows/shadow-crib-v4.yml")
        self.assertEqual(
            measure["with"],
            {"prepare_activation": True, "approval": "${{ inputs.approval }}"},
        )
        context = {
            "github.event_name": "workflow_dispatch",
            "github.ref": "refs/heads/main",
            "github.run_attempt": 1,
            "inputs.operation": "prepare",
            "inputs.approval": "prepare",
            "inputs.prepare_activation": measure["with"]["prepare_activation"],
        }
        self.assertTrue(guard_accepts(measure["if"], **context))
        shadow = yaml.safe_load((WORKFLOWS / "shadow-crib-v4.yml").read_text())
        for job in ("initialize", "generation0", "generation1"):
            with self.subTest(job=job):
                self.assertTrue(guard_accepts(shadow["jobs"][job]["if"], **context))

    def test_activation_and_rollback_are_manual_and_serialized(self):
        workflow = (WORKFLOWS / "activate-crib-v4.yml").read_text()
        self.require_fragment("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertEqual(workflow.count("contents: write"), 2)
        self.assertEqual(workflow.count("github.ref == 'refs/heads/main'"), 4)
        self.assertEqual(workflow.count("github.run_attempt == 1"), 4)
        self.require_fragment("group: expected-crib-points-release-", workflow)
        self.require_fragment("needs: prepare-rollback", workflow)
        self.require_fragment(
            "scripts.prepare_crib_activation verify candidate", workflow
        )
        measure = workflow.split("  measure:\n")[1].split("  publish:\n")[0]
        self.require_fragment(
            "github.run_attempt == 1 && inputs.operation == 'prepare' "
            "&& inputs.approval == 'prepare'",
            measure,
        )
        self.require_fragment("prepare_activation: true", workflow)
        self.require_fragment("approval: ${{ inputs.approval }}", measure)
        self.require_fragment("approval == 'restore-v3'", workflow)
        self.require_fragment("approval == 'publish'", workflow)

    def test_every_workflow_runs_the_exporter_as_a_module(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            text = path.read_text()
            self.assertNotIn("artifact_pipeline/export_uncertainty.py ", text, path)

    def test_only_writer_jobs_use_the_protected_environment(self):
        jobs = yaml.safe_load((WORKFLOWS / "activate-crib-v4.yml").read_text())["jobs"]
        self.assertEqual(jobs["publish"].get("environment"), "crib-release")
        self.assertEqual(jobs["restore"].get("environment"), "crib-release")
        self.assertNotIn("environment", jobs["prepare-rollback"])
        self.assertNotIn("environment", jobs["measure"])

    def test_only_writer_jobs_hold_the_release_lock(self):
        workflow = yaml.safe_load((WORKFLOWS / "activate-crib-v4.yml").read_text())
        self.assertNotIn("concurrency", workflow)
        jobs = workflow["jobs"]
        release = {
            "group": "expected-crib-points-release-${{ github.ref_name }}",
            "cancel-in-progress": False,
        }
        self.assertEqual(jobs["publish"].get("concurrency"), release)
        self.assertEqual(jobs["restore"].get("concurrency"), release)
        self.assertNotIn("concurrency", jobs["prepare-rollback"])
        shadow = yaml.safe_load((WORKFLOWS / "shadow-crib-v4.yml").read_text())
        self.assertNotEqual(shadow["concurrency"]["group"], release["group"])
        self.assertFalse(shadow["concurrency"]["cancel-in-progress"])

    def test_diagnostics_survive_packaging_failure_and_candidate_is_success_only(self):
        workflow = yaml.safe_load((WORKFLOWS / "shadow-crib-v4.yml").read_text())
        steps = workflow["jobs"]["finalize"]["steps"]
        diagnostic = next(
            s for s in steps if s.get("with", {}).get("name") == "v4-shadow-result"
        )
        package = next(
            s for s in steps if "scripts.prepare_crib_activation" in s.get("run", "")
        )
        candidate = next(
            s
            for s in steps
            if s.get("with", {}).get("name") == "crib-v4-release-assets"
        )
        self.assertLess(steps.index(diagnostic), steps.index(package))
        self.assertGreater(steps.index(candidate), steps.index(package))
        self.assertEqual(candidate["if"], "inputs.prepare_activation")

    def test_release_bodies_identify_preparation_and_restore_sources(self):
        workflow = yaml.safe_load((WORKFLOWS / "activate-crib-v4.yml").read_text())
        publish = workflow["jobs"]["publish"]["steps"]
        release = next(
            s
            for s in publish
            if s.get("with", {}).get("tag_name") == "expected-crib-points"
        )
        body = release["with"]["body"]
        self.require_fragment("${{ inputs.prepared_run }}", body)
        self.require_fragment("${{ github.sha }}", body)
        self.require_fragment("${{ steps.preparation.outputs.prepared_at }}", body)
        provenance = next(s for s in publish if s.get("id") == "preparation")
        self.require_fragment(".created_at", provenance["run"])
        self.require_fragment("$GITHUB_OUTPUT", provenance["run"])
        restore = workflow["jobs"]["restore"]["steps"]
        release = next(
            s
            for s in restore
            if s.get("with", {}).get("tag_name") == "expected-crib-points"
        )
        self.require_fragment("crib-v4-shadow-41771033920", release["with"]["body"])

    def test_preflight_and_verified_gzip_precede_replacing_client_pair(self):
        workflow = (WORKFLOWS / "activate-crib-v4.yml").read_text()
        publish = workflow.split("  publish:\n")[1].split("  restore:\n")[0]
        checks = (
            "scripts.prepare_crib_activation verify candidate",
            "check_crib_release_assets.sh scripts/crib-v3-release.sha256",
            'gh release upload expected-crib-points "candidate/$asset"',
            "check_crib_release_assets.sh staged.sha256",
            "tag_name: expected-crib-points",
        )
        positions = [publish.index(check) for check in checks]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("--clobber", publish)
        self.assertNotIn("candidate/expected_crib_points.json.gz", publish)

    def test_asset_check_rejects_wrong_digest_state_and_asset_set(self):
        scripts = ROOT / "scripts"
        manifest = scripts / "crib-v3-release.sha256"
        expected = [
            {"digest": f"sha256:{digest}", "name": name, "state": "uploaded"}
            for digest, name in (
                line.split() for line in manifest.read_text().splitlines()
            )
        ]
        cases = (
            (expected[::-1], 0),
            (expected[1:], 1),
            (expected + [expected[0]], 1),
            (expected + [{"name": "unexpected.json"}], 1),
            ([{**expected[0], "state": "starter"}, *expected[1:]], 1),
            ([{**expected[0], "digest": "sha256:" + "0" * 64}, *expected[1:]], 1),
        )
        for assets, status in cases:
            with self.subTest(assets=assets):
                result = subprocess.run(
                    [
                        "bash",
                        str(scripts / "check_crib_release_assets.sh"),
                        str(manifest),
                    ],
                    input=json.dumps({"assets": assets}),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, status, result.stderr)

    def test_legacy_cron_and_crib_backfill_cannot_replace_v4(self):
        v3 = (WORKFLOWS / "generate-crib-artifact.yml").read_text()
        backfill = (WORKFLOWS / "export-uncertainty.yml").read_text()
        self.assertNotIn("schedule:", v3)
        self.require_fragment("workflow_dispatch:", v3)
        self.assertNotIn("contents: write", v3)
        self.assertNotIn("expected-crib-points", backfill)

    def test_readonly_workflow_prepares_assets_only_when_called_for_activation(self):
        shadow = (WORKFLOWS / "shadow-crib-v4.yml").read_text()
        self.require_fragment("default: false", shadow)
        self.assertEqual(shadow.count("if: inputs.prepare_activation"), 3)
        self.assertNotIn("contents: write", shadow)
        workflow = yaml.load(shadow, Loader=yaml.BaseLoader)
        dispatch = workflow["on"]["workflow_dispatch"]["inputs"]["approval"]
        reusable = workflow["on"]["workflow_call"]["inputs"]["approval"]
        self.assertEqual(dispatch["required"], "true")
        self.assertEqual(reusable["required"], "true")
        for job in ("initialize", "generation0", "generation1"):
            guard = workflow["jobs"][job]["if"]
            for fragment in (
                "github.event_name == 'workflow_dispatch'",
                "github.ref == 'refs/heads/main'",
                "github.run_attempt == 1",
                "inputs.approval == 'prepare'",
                "inputs.approval == 'shadow'",
            ):
                self.require_fragment(fragment, guard)
        self.assertLess(
            shadow.index("crib_v4_shards finalize"),
            shadow.index("scripts.prepare_crib_activation"),
        )
