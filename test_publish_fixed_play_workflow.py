"""Guard the manual fixed-policy publication workflow without dispatching it."""

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

from artifact_pipeline.promotion_gate import release_summary
from test_cfr_inputs_workflow import guard_accepts, load

ROOT = Path(__file__).parent
WORKFLOW = ROOT / ".github/workflows/publish-fixed-play.yml"
MEASURE = ROOT / ".github/workflows/measure-fixed-play.yml"
PLAY = ROOT / ".github/workflows/generate-play-artifact.yml"
BACKFILL = ROOT / ".github/workflows/export-uncertainty.yml"
DIGESTS = ROOT / "examples/fixed-play-release.sha256"
NOTES = ROOT / "examples/fixed-play-release.md"
ENVIRONMENT = "play-release"
TOKEN = {"GH_TOKEN": "${{ github.token }}"}
ASSETS = [
    "expected_play_points.client.json",
    "expected_play_points.json",
    "expected_play_points.lines.json",
    "expected_play_points.uncertainty.json",
]
APPROVED = {
    "github.event_name": "workflow_dispatch",
    "github.ref": "refs/heads/main",
    "github.run_attempt": "1",
    "inputs.approval": "publish",
}
# Every step of both jobs that runs a script, in order. Exact text, because a
# parsed match misses a dropped flag, a pipe that hides a failure, or a check
# that only echoes.
VERIFY = {
    "Require main exactly": '[[ "$GITHUB_REF" == "refs/heads/main" ]]',
    "Require a protected release environment": (
        'gh api "repos/$GITHUB_REPOSITORY/environments/play-release" |\n'
        "  jq -e '.can_admins_bypass == false\n"
        '    and any(.protection_rules[]; .type == "required_reviewers"'
        " and (.reviewers | length) > 0)'\n"
    ),
    "Check the measurement run": (
        'gh api "repos/$GITHUB_REPOSITORY/actions/runs/$MEASUREMENT_RUN" |\n'
        '  jq -e \'.path == ".github/workflows/measure-fixed-play.yml"'
        ' and .event == "workflow_dispatch"\n'
        '    and .head_branch == "main" and .run_attempt == 1'
        ' and .conclusion == "success"\'\n'
    ),
    "Install pinned dependencies": "python -m pip install -r requirements.txt",
    "Match the download to the committed digests": (
        "sha256sum --check --strict ../examples/fixed-play-release.sha256"
    ),
    "Verify the table and its companions": (
        'pin="$(jq -er .policy_manifest_sha256 examples/fixed-play-inputs.json)"\n'
        "python -m scripts.verify_fixed_play_bundle \\\n"
        '  --policy-manifest-sha256 "$pin" --release-samples 13000 \\\n'
        "  --full candidate/expected_play_points.json \\\n"
        "  --means candidate/expected_play_points.client.json \\\n"
        "  --sidecar candidate/expected_play_points.uncertainty.json \\\n"
        "  --lines candidate/expected_play_points.lines.json\n"
    ),
    "Require the notes to quote the measured gate result": None,
    "Download the release this would replace": (
        'gh release download expected-play-points --repo "$GITHUB_REPOSITORY"'
        " --dir previous\n"
        'gh release view expected-play-points --repo "$GITHUB_REPOSITORY"'
        " --json body --jq .body > previous/release-notes.md\n"
    ),
}
PUBLISH = {
    "Match the download to the committed digests": VERIFY[
        "Match the download to the committed digests"
    ],
    "Verify the attached release assets": (
        'gh api "repos/$GITHUB_REPOSITORY/releases/tags/expected-play-points" |\n'
        "  bash scripts/check_crib_release_assets.sh"
        " examples/fixed-play-release.sha256\n"
    ),
}
WITH_TOKEN = {
    "Require a protected release environment",
    "Check the measurement run",
    "Download the release this would replace",
    "Verify the attached release assets",
}


def name(step: dict) -> str:
    return step.get("name", step.get("uses", "").partition("@")[0])


class PublishFixedPlayWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = load(WORKFLOW)
        self.jobs = self.workflow["jobs"]
        self.verify = {name(step): step for step in self.jobs["verify"]["steps"]}
        self.publish = {name(step): step for step in self.jobs["publish"]["steps"]}
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def run_step(self, step: dict, cwd: Path, **env: str) -> int:
        """Run a step's script as the job would."""
        result = subprocess.run(
            ["bash", "-e", "-c", step["run"]],
            cwd=cwd,
            env={**os.environ, "GITHUB_REPOSITORY": "o/r", **env},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode

    def run_with_api(self, step: dict, response: object) -> int:
        """Run a step against a `gh` that prints one API response."""
        (self.folder / "response.json").write_text(json.dumps(response))
        stub = self.folder / "gh"
        stub.write_text('#!/bin/sh\ncat "$(dirname "$0")/response.json"\n')
        stub.chmod(0o755)
        path = f"{self.folder}{os.pathsep}{os.environ['PATH']}"
        return self.run_step(step, ROOT, PATH=path, MEASUREMENT_RUN="1")

    def test_manual_dispatch_only_and_one_job_can_write(self) -> None:
        # Catches another trigger, an optional confirmation, a write token on
        # the job that runs project code, or publishing without the reviewer.
        self.assertEqual(set(self.workflow["on"]), {"workflow_dispatch"})
        inputs = self.workflow["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(set(inputs), {"approval"})
        self.assertEqual(inputs["approval"]["required"], "true")
        self.assertNotIn("default", inputs["approval"])
        self.assertEqual(
            self.workflow["permissions"], {"contents": "read", "actions": "read"}
        )
        self.assertEqual(list(self.jobs), ["verify", "publish"])
        for key in ("permissions", "environment", "env", "defaults", "outputs"):
            self.assertNotIn(key, self.jobs["verify"])
        self.assertEqual(
            self.jobs["publish"]["permissions"],
            {"actions": "read", "contents": "write"},
        )
        self.assertEqual(self.jobs["publish"]["environment"], ENVIRONMENT)
        self.assertEqual(self.jobs["publish"]["needs"], "verify")
        self.assertEqual(self.workflow["defaults"], {"run": {"shell": "bash"}})

    def test_every_writer_of_the_release_waits_for_the_reviewer(self) -> None:
        # Catches a job that can write the release without the environment.
        for path, job in ((PLAY, "release-artifact"), (BACKFILL, "export")):
            self.assertEqual(load(path)["jobs"][job]["environment"], ENVIRONMENT)

    def test_publication_shares_the_release_writer_lock(self) -> None:
        # Catches a group that no longer excludes generate-play-artifact.yml, and
        # one held by a job, which would leave the wait for approval unlocked.
        self.assertEqual(self.workflow["concurrency"], load(PLAY)["concurrency"])
        self.assertEqual(self.workflow["concurrency"]["cancel-in-progress"], "false")

    def test_both_jobs_require_the_approved_first_attempt_on_main(self) -> None:
        # Catches a guard that drops one condition in either job: a re-run of
        # the publish job alone does not repeat the verify job.
        deviations = {
            "github.event_name": "push",
            "github.ref": "refs/heads/feature",
            "github.run_attempt": "2",
            "inputs.approval": "measure",
        }
        for job in self.jobs.values():
            self.assertTrue(guard_accepts(job["if"], APPROVED))
            for key, value in deviations.items():
                with self.subTest(key=key):
                    self.assertFalse(guard_accepts(job["if"], {**APPROVED, key: value}))

    def test_steps_run_in_order_with_exactly_these_scripts(self) -> None:
        # Catches a check dropped, weakened, reordered after the publication,
        # or allowed to fail, and a script or action added to either job.
        order = {
            "verify": [
                *list(VERIFY)[:3],
                "actions/checkout",
                "actions/setup-python",
                "Install pinned dependencies",
                "Download the measured table",
                *list(VERIFY)[4:],
                "Preserve the release this would replace",
            ],
            "publish": [
                "actions/checkout",
                "Download the measured table",
                "Match the download to the committed digests",
                "Publish the rolling release",
                "Verify the attached release assets",
            ],
        }
        for job, scripts in (("verify", VERIFY), ("publish", PUBLISH)):
            steps = self.jobs[job]["steps"]
            self.assertEqual([name(step) for step in steps], order[job])
            for step in steps:
                for key in ("if", "continue-on-error", "shell"):
                    self.assertNotIn(key, step)
                expected = TOKEN if name(step) in WITH_TOKEN else None
                self.assertEqual(step.get("env"), expected, name(step))
                if "run" in step and scripts[name(step)] is not None:
                    self.assertEqual(step["run"], scripts[name(step)])

    def test_the_bytes_published_are_the_committed_digests(self) -> None:
        # Catches a pin that omits an asset, a download from another run or
        # artifact, a changed or missing file accepted, or other files attached.
        lines = DIGESTS.read_text(encoding="utf-8").splitlines()
        self.assertEqual([line[66:] for line in lines], ASSETS)
        for line in lines:
            self.assertRegex(line, r"\A[0-9a-f]{64}  \S+\Z")
        uploads = [
            step["with"]["name"]
            for step in load(MEASURE)["jobs"]["measure"]["steps"]
            if step.get("uses", "").startswith("actions/upload-artifact")
        ]
        for steps in (self.verify, self.publish):
            download = steps["Download the measured table"]["with"]
            self.assertEqual(
                download,
                {
                    "name": uploads[0],
                    "path": "candidate",
                    "github-token": "${{ github.token }}",
                    "run-id": "${{ env.MEASUREMENT_RUN }}",
                },
            )
            check = steps["Match the download to the committed digests"]
            self.assertEqual(check["working-directory"], "candidate")
        release = self.publish["Publish the rolling release"]
        self.assertRegex(release["uses"], r"\A\w+/action-gh-release@")
        self.assertEqual(
            sorted(release["with"]["files"].split()),
            [f"candidate/{asset}" for asset in ASSETS],
        )
        self.assertEqual(release["with"]["tag_name"], "expected-play-points")
        self.assertEqual(release["with"]["fail_on_unmatched_files"], "true")
        self.assertEqual(release["with"]["make_latest"], "false")
        self.assertEqual(release["with"]["body_path"], "examples/fixed-play-release.md")

    @unittest.skipUnless(shutil.which("sha256sum"), "needs sha256sum")
    def test_the_digest_step_rejects_a_changed_or_missing_file(self) -> None:
        # Catches a check that reads the wrong folder or ignores a mismatch.
        (self.folder / "examples").mkdir()
        candidate = self.folder / "candidate"
        candidate.mkdir()
        rows = []
        for asset in ASSETS:
            (candidate / asset).write_text(asset)
            rows.append(f"{hashlib.sha256(asset.encode()).hexdigest()}  {asset}\n")
        (self.folder / "examples" / DIGESTS.name).write_text("".join(rows))
        step = self.verify["Match the download to the committed digests"]
        self.assertEqual(self.run_step(step, candidate), 0)
        (candidate / ASSETS[0]).write_text("changed")
        self.assertNotEqual(self.run_step(step, candidate), 0)
        (candidate / ASSETS[0]).unlink()
        self.assertNotEqual(self.run_step(step, candidate), 0)

    @unittest.skipUnless(shutil.which("jq"), "needs jq")
    def test_publication_waits_for_an_environment_with_a_reviewer(self) -> None:
        # Catches an environment accepted with no reviewer, or whose reviewer
        # an administrator may bypass: Actions would let the publish job pass
        # through without approval.
        step = self.verify["Require a protected release environment"]
        self.assertTrue(f"environments/{ENVIRONMENT}" in step["run"])
        branch = {"type": "branch_policy"}
        reviewed = {"type": "required_reviewers", "reviewers": [{"type": "User"}]}
        empty = {"type": "required_reviewers", "reviewers": []}
        for bypass, rules, accepted in (
            (False, [branch, reviewed], True),
            (True, [branch, reviewed], False),
            (None, [branch, reviewed], False),
            (False, [], False),
            (False, [branch], False),
            (False, [empty], False),
        ):
            with self.subTest(bypass=bypass, rules=rules):
                response = {"can_admins_bypass": bypass, "protection_rules": rules}
                code = self.run_with_api(step, response)
                self.assertEqual(code == 0, accepted)
        self.assertNotEqual(self.run_with_api(step, {"message": "Not Found"}), 0)

    @unittest.skipUnless(shutil.which("jq"), "needs jq")
    def test_the_source_must_be_a_successful_measurement_on_main(self) -> None:
        # Catches another workflow, a branch, a re-run or a failed run.
        step = self.verify["Check the measurement run"]
        run = {
            "path": ".github/workflows/measure-fixed-play.yml",
            "event": "workflow_dispatch",
            "head_branch": "main",
            "run_attempt": 1,
            "conclusion": "success",
        }
        self.assertEqual(self.run_with_api(step, run), 0)
        deviations = {
            "path": ".github/workflows/generate-play-artifact.yml",
            "event": "push",
            "head_branch": "feature",
            "run_attempt": 2,
            "conclusion": "failure",
        }
        for key, value in deviations.items():
            with self.subTest(key=key):
                self.assertNotEqual(self.run_with_api(step, {**run, key: value}), 0)

    def test_the_notes_name_the_run_and_quote_its_gate(self) -> None:
        # Catches notes left from another run, or a gate result they misstate.
        run = self.workflow["env"]["MEASUREMENT_RUN"]
        self.assertRegex(run, r"\A\d+\Z")
        notes = NOTES.read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"actions/runs/(\d+)", notes), [run])
        seat = {"mu": 0.5, "se": 0.1}
        metadata = {
            "measured_policy": "trained",
            "promotion_gate": {
                "mode": "enforce",
                "passed": True,
                "deals": 1000,
                **{label: seat for label in ("Pone", "Dealer", "both_seats")},
            },
        }
        for folder in ("candidate", "examples", "bin"):
            (self.folder / folder).mkdir()
        (self.folder / "bin/python").symlink_to(sys.executable)
        full = self.folder / "candidate/expected_play_points.json"
        full.write_text(json.dumps({"__metadata__": metadata}))
        env = {
            "PATH": f"{self.folder / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "PYTHONPATH": str(ROOT),
        }
        step = self.verify["Require the notes to quote the measured gate result"]
        copy = self.folder / "examples/fixed-play-release.md"
        copy.write_text(f"Notes.\n\n{release_summary(metadata)}\n")
        self.assertEqual(self.run_step(step, self.folder, **env), 0)
        copy.write_text(copy.read_text().replace("+0.5000", "+0.6000"))
        self.assertNotEqual(self.run_step(step, self.folder, **env), 0)

    def test_the_replaced_assets_are_kept(self) -> None:
        # Catches a publication that leaves nothing to restore from.
        keep = self.verify["Preserve the release this would replace"]
        self.assertEqual(keep["with"]["path"], "previous/")
        self.assertEqual(keep["with"]["if-no-files-found"], "error")
        self.assertEqual(keep["with"]["retention-days"], "90")


if __name__ == "__main__":
    unittest.main()
