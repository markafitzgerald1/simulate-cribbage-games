"""Exercise the play lines re-export workflow without GitHub writes."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from artifact_pipeline.export_uncertainty import build_sidecar, encode_json
from artifact_pipeline.play_lines import decode_lines
from test_cfr_inputs_workflow import guard_accepts, load
from test_publish_fixed_play_workflow import PLAY, TOKEN, name

ROOT = Path(__file__).parent
WORKFLOW = ROOT / ".github/workflows/reexport-play-lines.yml"
MANIFEST = Path("examples/fixed-play-release.sha256")
PIN = Path("examples/reexport-play-lines.sha256")
CHECKER = Path("scripts/check_crib_release_assets.sh")
LINES = "expected_play_points.lines.json"
CANDIDATE = Path("candidate") / LINES
APPROVED = {
    "github.event_name": "workflow_dispatch",
    "github.ref": "refs/heads/main",
    "github.run_attempt": "1",
    "inputs.approval": "publish-lines",
}


def digest_line(path: Path) -> str:
    """Format a checksum for the file's basename."""
    return f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"


class ReexportPlayLinesWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.workflow = load(WORKFLOW)
        self.jobs = self.workflow["jobs"]
        self.steps = {
            job: {name(step): step for step in config["steps"]}
            for job, config in self.jobs.items()
        }
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def run_step(self, job, step_name, stub="", **env):
        step = self.steps[job][step_name]
        shell = self.workflow["defaults"]["run"]["shell"]
        return subprocess.run(
            [shell, "-eo", "pipefail", "-c", stub + step["run"]],
            cwd=self.folder / step.get("working-directory", ""),
            env={**os.environ, "GITHUB_REPOSITORY": "o/r", **env},
            capture_output=True,
            text=True,
            check=False,
        )

    def test_dispatch_and_write_permissions(self):
        self.assertEqual(set(self.workflow["on"]), {"workflow_dispatch"})
        approval = self.workflow["on"]["workflow_dispatch"]["inputs"]["approval"]
        self.assertEqual(approval["required"], "true")
        self.assertEqual(approval["type"], "string")
        self.assertNotIn("default", approval)
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertEqual(self.workflow["defaults"], {"run": {"shell": "bash"}})
        self.assertEqual(self.workflow["concurrency"], load(PLAY)["concurrency"])
        self.assertEqual(self.workflow["concurrency"]["cancel-in-progress"], "false")
        self.assertEqual(set(self.jobs), {"export", "publish"})
        self.assertNotIn("permissions", self.jobs["export"])
        self.assertNotIn("outputs", self.jobs["export"])
        self.assertEqual(self.jobs["publish"]["permissions"], {"contents": "write"})
        self.assertEqual(self.jobs["publish"]["needs"], "export")
        self.assertEqual(self.jobs["publish"]["environment"], "play-release")
        self.assertEqual(
            self.steps["publish"]["Verify and replace only the lines asset"]["env"],
            TOKEN,
        )

    def test_main_and_first_attempt_guards_in_both_jobs(self):
        deviations = {
            "github.event_name": "push",
            "github.ref": "refs/tags/main",
            "github.run_attempt": "2",
            "inputs.approval": "publish",
        }
        for job, config in self.jobs.items():
            self.assertTrue(guard_accepts(config["if"], APPROVED))
            for key, invalid in deviations.items():
                with self.subTest(job=job, key=key):
                    self.assertFalse(
                        guard_accepts(config["if"], {**APPROVED, key: invalid})
                    )
            self.assertEqual(next(iter(self.steps[job])), "Require main exactly")
            for ref, allowed in (("refs/heads/main", True), ("refs/heads/Main", False)):
                with self.subTest(job=job, ref=ref):
                    result = self.run_step(job, "Require main exactly", GITHUB_REF=ref)
                    self.assertEqual(result.returncode == 0, allowed, result.stderr)

    @unittest.skipUnless(shutil.which("jq"), "jq is required by the release workflow")
    def test_export_requires_a_protected_release_environment(self):
        check = "Require a protected release environment"
        self.assertEqual(self.steps["export"][check]["env"], TOKEN)
        stub = """
gh() {
    [[ "$*" == 'api repos/o/r/environments/play-release' ]] || return 2
    printf '%s\n' "$RESPONSE"
    return "$API_STATUS"
}
"""
        reviewers = {"type": "required_reviewers", "reviewers": [{}]}
        for bypass, rules, status, allowed in (
            (False, [reviewers], "0", True),
            (True, [reviewers], "0", False),
            (False, [], "0", False),
            (False, [{**reviewers, "reviewers": []}], "0", False),
            (False, [{**reviewers, "type": "wait_timer"}], "0", False),
            (False, [reviewers], "1", False),
        ):
            with self.subTest(bypass=bypass, rules=rules, status=status):
                response = {"can_admins_bypass": bypass, "protection_rules": rules}
                result = self.run_step(
                    "export",
                    check,
                    stub,
                    RESPONSE=json.dumps(response),
                    API_STATUS=status,
                )
                self.assertEqual(result.returncode == 0, allowed, result.stderr)

    def test_steps_keep_the_v1_backup_and_bind_the_v2_download(self):
        self.assertEqual(
            list(self.steps["export"]),
            [
                "Require main exactly",
                "Require a protected release environment",
                "actions/checkout",
                "actions/setup-python",
                "Download the current release",
                "Match the released measurement to the committed digests",
                "Export version 2 without measuring",
                "Preserve the version 1 asset",
                "Upload the replacement asset",
            ],
        )
        self.assertEqual(
            list(self.steps["publish"]),
            [
                "Require main exactly",
                "actions/checkout",
                "actions/download-artifact",
                "Verify and replace only the lines asset",
            ],
        )
        for job in self.steps.values():
            for step in job.values():
                for key in ("if", "continue-on-error", "shell"):
                    self.assertNotIn(key, step)
        export = self.steps["export"]
        self.assertEqual(
            export["actions/setup-python"]["with"],
            {"python-version-file": ".python-version"},
        )
        self.assertEqual(
            export["Preserve the version 1 asset"]["with"],
            {
                "name": "previous-play-lines",
                "path": f"previous/{LINES}",
                "if-no-files-found": "error",
                "retention-days": "90",
            },
        )
        self.assertEqual(
            export["Upload the replacement asset"]["with"],
            {
                "name": "replacement-play-lines",
                "path": f"candidate/{LINES}",
                "if-no-files-found": "error",
            },
        )
        self.assertEqual(
            self.steps["publish"]["actions/download-artifact"]["with"],
            {"name": "replacement-play-lines", "path": "candidate"},
        )
        self.assertRegex(
            (ROOT / PIN).read_text(), rf"\A[0-9a-f]{{64}}  {re.escape(LINES)}\n\Z"
        )

    def test_export_checks_the_v1_inputs_and_reports_the_pinned_v2_without_site(self):
        previous = self.folder / "previous"
        previous.mkdir()
        metadata = {
            "generation_method": "fixture",
            "joint_policy_converged": False,
            "policy_fingerprint": "frozen",
            "seed": 42,
        }
        means = {"A_2_3_4": {role: {"mu": 0.0} for role in ("Pone", "Dealer")}}
        opening = {"0": {"n": 2, "mean": 0.0, "moment_2": 0.0, "responses": {"0": 2}}}
        full = {
            "__metadata__": metadata,
            "A_2_3_4": {
                role: {"mu": 0.0, "se": 0.0, "n": 2, "opening": opening}
                for role in ("Pone", "Dealer")
            },
        }
        files = {
            "expected_play_points.json": encode_json(full),
            "expected_play_points.client.json": encode_json(means),
            "expected_play_points.uncertainty.json": encode_json(
                build_sidecar("play", encode_json(full), encode_json(means))
            ),
            LINES: b"previous",
        }
        for filename, data in files.items():
            (previous / filename).write_bytes(data)
        (self.folder / MANIFEST.parent).mkdir()
        (self.folder / MANIFEST).write_text(
            "".join(digest_line(previous / filename) for filename in files)
        )
        check = "Match the released measurement to the committed digests"
        self.assertEqual(self.run_step("export", check).returncode, 0)
        (previous / LINES).write_bytes(b"wrong v1")
        self.assertNotEqual(self.run_step("export", check).returncode, 0)
        (previous / LINES).write_bytes(files[LINES])

        summary = self.folder / "summary"
        step_name = "Export version 2 without measuring"
        # Run the workflow as written and fail if it tries to enable site-packages.
        shim = 'python() { [[ "$1" == -S ]] || return 2; "$TEST_PYTHON" "$@"; }\n'
        (self.folder / PIN).write_text(f"{'0' * 64}  {LINES}\n")
        env = {
            "TEST_PYTHON": sys.executable,
            "PYTHONPATH": str(ROOT),
            "GITHUB_STEP_SUMMARY": str(summary),
        }
        result = self.run_step("export", step_name, shim, **env)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(summary.exists())
        candidate = self.folder / CANDIDATE
        self.assertTrue(candidate.is_file(), result.stderr)
        document = decode_lines(
            candidate.read_bytes(), files["expected_play_points.client.json"]
        )
        self.assertEqual(
            document["entries"], [[[[0, 2, 0.0, 0.0]], [[0, 2, 0.0, 0.0, [[0, 2]]]]]]
        )
        checksum = digest_line(candidate)
        (self.folder / PIN).write_text(checksum)
        candidate.unlink()
        candidate.parent.rmdir()
        result = self.run_step("export", step_name, shim, **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(digest_line(candidate), checksum)
        for message in (result.stdout, summary.read_text()):
            self.assertEqual(
                message.splitlines()[-1],
                f"Opening lines v2 SHA-256 {checksum.split()[0]}",
            )

    @unittest.skipUnless(shutil.which("jq"), "jq is required by the release workflow")
    def test_publish_verifies_before_and_after_uploading_only_lines(self):
        for path in (MANIFEST, CHECKER):
            (self.folder / path.parent).mkdir(exist_ok=True)
            shutil.copyfile(ROOT / path, self.folder / path)
        assets = []
        for line in (self.folder / MANIFEST).read_text().splitlines():
            digest, filename = line.split("  ")
            assets.append(
                {"digest": f"sha256:{digest}", "name": filename, "state": "uploaded"}
            )
        candidate = self.folder / CANDIDATE
        candidate.parent.mkdir()
        candidate.write_bytes(b"replacement")
        checksum = digest_line(candidate)
        (self.folder / PIN).write_text(checksum)
        updated = [
            (
                {**asset, "digest": f"sha256:{checksum.split()[0]}"}
                if asset["name"] == LINES
                else asset
            )
            for asset in assets
        ]
        fake = """
gh() {
    if [[ "$*" == 'api repos/o/r/releases/tags/expected-play-points' ]]; then
        if [[ -f uploaded ]]; then cat after.json; else cat before.json; fi
        return "$API_STATUS"
    fi
    [[ "$*" == 'release upload expected-play-points candidate/expected_play_points.lines.json --repo o/r --clobber' ]] || return 1
    touch uploaded
}
"""
        stale = [{**assets[0], "digest": "sha256:stale"}, *assets[1:]]
        sibling_changed = [
            (
                {**asset, "digest": "sha256:clobbered"}
                if asset["name"] == "expected_play_points.client.json"
                else asset
            )
            for asset in updated
        ]
        for before, after, content, status, ok, uploaded in (
            (assets, updated, b"replacement", "0", True, True),
            (stale, updated, b"replacement", "0", False, False),
            (assets, updated, b"replacement", "1", False, False),
            (assets, updated, b"tampered", "0", False, False),
            (assets, assets, b"replacement", "0", False, True),
            (assets, sibling_changed, b"replacement", "0", False, True),
        ):
            with self.subTest(
                after=after, status=status, ok=ok, uploaded=uploaded, content=content
            ):
                marker = self.folder / "uploaded"
                marker.unlink(missing_ok=True)
                candidate.write_bytes(content)
                (self.folder / "before.json").write_text(json.dumps({"assets": before}))
                (self.folder / "after.json").write_text(json.dumps({"assets": after}))
                result = self.run_step(
                    "publish",
                    "Verify and replace only the lines asset",
                    fake,
                    API_STATUS=status,
                )
                self.assertEqual(result.returncode == 0, ok, result.stderr)
                self.assertEqual(marker.exists(), uploaded)
