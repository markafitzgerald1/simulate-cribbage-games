"""Exercise the policy shard release gates without publishing anything."""

# cspell:words esac pipefail shasum
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from zipfile import ZipFile

from scripts.verify_policy_shards_release import verify
from test_cfr_inputs_workflow import guard_accepts, load
from test_export_policy_shards_workflow import APPROVED, ROOT

WORKFLOW = ROOT / ".github/workflows/publish-policy-shards.yml"
FIXED_PLAY = ROOT / ".github/workflows/publish-fixed-play.yml"
PUBLISH_APPROVED = {**APPROVED, "inputs.approval": "publish"}
SHARD = "pone/A_2_3_4.bin.gz"
INDEX_DIGEST = "a" * 64


class PublishPolicyShardsWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = load(WORKFLOW)
        self.jobs = self.workflow["jobs"]

    def test_only_an_approved_first_attempt_can_publish(self) -> None:
        self.assertEqual(set(self.workflow["on"]), {"workflow_dispatch"})
        approval = self.workflow["on"]["workflow_dispatch"]["inputs"]["approval"]
        self.assertEqual(approval["required"], "true")
        self.assertNotIn("default", approval)
        self.assertEqual(self.workflow["defaults"], {"run": {"shell": "bash"}})
        self.assertEqual(self.workflow["concurrency"]["cancel-in-progress"], "false")
        self.assertEqual(
            self.workflow["permissions"], {"contents": "read", "actions": "read"}
        )
        self.assertEqual(set(self.jobs), {"verify", "publish"})
        for job in self.jobs.values():
            self.assertTrue(guard_accepts(job["if"], PUBLISH_APPROVED))
            for key, value in PUBLISH_APPROVED.items():
                deviation = "2" if value == "1" else "other"
                self.assertFalse(
                    guard_accepts(job["if"], {**PUBLISH_APPROVED, key: deviation})
                )
            self.assertNotIn("continue-on-error", job)

        verify_job, publish = self.jobs["verify"], self.jobs["publish"]
        self.assertNotIn("permissions", verify_job)
        self.assertEqual(publish["needs"], "verify")
        self.assertEqual(publish["environment"], "play-release")
        self.assertEqual(publish["permissions"], {"contents": "write"})
        fixed_checks = load(FIXED_PLAY)["jobs"]["verify"]["steps"][:2]
        self.assertEqual(verify_job["steps"][:2], fixed_checks)
        for branch, allowed in (("main", True), ("Main", False)):
            result = subprocess.run(
                ["bash", "-e", "-c", verify_job["steps"][0]["run"]],
                env={"GITHUB_REF": f"refs/heads/{branch}"},
                check=False,
            )
            self.assertEqual(result.returncode == 0, allowed)

    def test_verified_archive_is_the_only_asset_and_is_rechecked(self) -> None:
        verify_steps = self.jobs["verify"]["steps"]
        download = verify_steps[4]["run"]
        self.assertTrue(".digest == $digest" in download)
        self.assertLess(
            download.index("sha256sum"), download.index("verify_policy_shards")
        )

        checkout, fetch, check, release, audit = self.jobs["publish"]["steps"]
        self.assertEqual(checkout["uses"], "actions/checkout@v7")
        self.assertNotIn("ref", checkout["with"])
        self.assertEqual(fetch["with"], {"name": verify_steps[-1]["with"]["name"]})
        self.assertEqual(verify_steps[-1]["with"]["path"], "${{ env.ARCHIVE }}")
        fixed_release = load(FIXED_PLAY)["jobs"]["publish"]["steps"][-2]
        self.assertEqual(release["uses"], fixed_release["uses"])
        self.assertEqual(release["with"]["tag_name"], "pegging-policy-shards")
        self.assertEqual(release["with"]["files"], "${{ env.ARCHIVE }}")
        self.assertEqual(release["with"]["fail_on_unmatched_files"], "true")
        self.assertEqual(release["with"]["make_latest"], "false")
        for step in [
            *verify_steps[:5],
            verify_steps[-1],
            checkout,
            fetch,
            check,
            release,
            audit,
        ]:
            self.assertNotIn("if", step)
            self.assertNotIn("continue-on-error", step)

        pins = json.loads((ROOT / self.workflow["env"]["PINS"]).read_text())
        self.assertRegex(pins["run_id"], r"^[0-9]+$")
        for key in ("artifact_sha256", "index_sha256"):
            self.assertRegex(pins[key], r"^[0-9a-f]{64}$")


@unittest.skipUnless(
    shutil.which("jq") and shutil.which("shasum"), "needs jq and shasum"
)
class PolicyShardsReleaseStepsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = load(WORKFLOW)
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)
        self.env = {**self.workflow["env"], "GITHUB_REPOSITORY": "test/repo"}
        self.archive = self.folder / self.env["ARCHIVE"]
        self.pins = {
            "run_id": "12345",
            "artifact_sha256": hashlib.sha256(b"ZIP").hexdigest(),
            "index_sha256": INDEX_DIGEST,
        }
        (self.folder / self.env["PINS"]).parent.mkdir()
        (self.folder / "scripts").symlink_to(ROOT / "scripts", target_is_directory=True)

    def fixture(self, filename: str, data: object) -> None:
        (self.folder / filename).write_text(json.dumps(data))

    def run_step(self, step: dict, expected: bool, **pins: str) -> None:
        self.fixture(self.env["PINS"], {**self.pins, **pins})
        stubs = """
        gh() {
          [[ "$1" == api && "$#" == 2 ]] || return 2
          case "$2" in
            repos/test/repo/actions/runs/12345) cat run.json ;;
            "repos/test/repo/actions/runs/12345/artifacts?name=pegging-policy-shards") cat artifacts.json ;;
            repos/test/repo/actions/artifacts/678/zip) cat export.zip ;;
            repos/test/repo/releases/tags/pegging-policy-shards) cat release.json ;;
            *) return 2 ;;
          esac
        }
        sha256sum() { shasum -a 256 "$@"; }
        python() { [[ "$*" == "-m scripts.verify_policy_shards_release $ARCHIVE $INDEX_DIGEST" ]]; }
        """
        command = ["bash", "-eo", "pipefail", "-c", stubs + step["run"]]
        result = subprocess.run(
            command,
            cwd=self.folder,
            env={**self.env, "PATH": os.environ["PATH"], "INDEX_DIGEST": INDEX_DIGEST},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode == 0, expected, result.stderr)

    def test_download_rejects_invalid_source_and_digests(self) -> None:
        step = self.workflow["jobs"]["verify"]["steps"][4]
        run = {
            "path": ".github/workflows/export-policy-shards.yml",
            "event": "workflow_dispatch",
            "head_branch": "main",
            "run_attempt": 1,
            "conclusion": "success",
        }
        name, digest = "pegging-policy-shards", self.pins["artifact_sha256"]
        artifact = {
            "name": name,
            "digest": f"sha256:{digest}",
            "expired": False,
            "id": 678,
        }
        self.fixture("artifacts.json", {"total_count": 1, "artifacts": [artifact]})
        (self.folder / "export.zip").write_bytes(b"ZIP")
        self.fixture("run.json", run)
        self.run_step(step, True)
        for field in run:
            with self.subTest(field=field):
                self.fixture("run.json", {**run, field: "unexpected"})
                self.run_step(step, False)
        self.fixture("run.json", run)
        duplicates = [artifact, {**artifact, "id": 679}]
        self.fixture("artifacts.json", {"total_count": 2, "artifacts": duplicates})
        self.run_step(step, False)
        self.fixture("artifacts.json", {"total_count": 1, "artifacts": [artifact]})
        self.run_step(step, False, index_sha256="0" * 64)
        (self.folder / "export.zip").write_bytes(b"changed")
        self.run_step(step, False)

    def test_publish_rechecks_zip_and_uses_pinned_notes(self) -> None:
        check, release, audit = self.workflow["jobs"]["publish"]["steps"][2:]
        self.archive.write_bytes(b"ZIP")
        self.run_step(check, True)
        self.archive.write_bytes(b"changed")
        self.run_step(check, False)
        digest = self.pins["artifact_sha256"]
        asset = {"name": self.archive.name, "state": "uploaded"}
        for reported in (digest, "0" * 64):
            assets = [{**asset, "digest": f"sha256:{reported}"}]
            self.fixture("release.json", {"assets": assets})
            self.run_step(audit, reported == digest)
        self.assertTrue("body_path" in release["with"])
        self.assertNotIn("body", release["with"])
        notes = (self.folder / release["with"]["body_path"]).read_text()
        for pin in self.pins.values():
            self.assertTrue(pin in notes)


class VerifyPolicyShardsReleaseTest(unittest.TestCase):
    def test_rejects_changed_or_unlisted_bytes(self) -> None:
        shard = b"approved shard bytes"
        entry = {"file": SHARD, "sha256": hashlib.sha256(shard).hexdigest()}
        cases = [
            ("valid", [entry], {SHARD: shard}, None),
            ("wrong schema", [entry], {SHARD: shard}, "nonempty"),
            ("index digest", [entry], {SHARD: shard}, "shards.json SHA-256"),
            ("shard digest", [entry], {SHARD: b"changed"}, "Shard SHA-256"),
            ("missing", [entry], {}, "ZIP members"),
            ("extra", [entry], {SHARD: shard, "extra": b""}, "ZIP members"),
            ("unsafe name", [{**entry, "file": "../escape"}], {}, "Invalid shard path"),
            ("duplicate", [entry, entry], {SHARD: shard}, "Duplicate index entry"),
            ("empty index", [], {}, "nonempty"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.zip"
            for name, entries, members, error in cases:
                with self.subTest(case=name):
                    schema = (
                        f"pegging-policy-shards.v{2 if name == 'wrong schema' else 1}"
                    )
                    index = json.dumps({"schema": schema, "shards": entries}).encode()
                    with ZipFile(path, "w") as archive:
                        archive.writestr("shards.json", index)
                        for member in members.items():
                            archive.writestr(*member)
                    digest = hashlib.sha256(index).hexdigest()
                    if name == "index digest":
                        digest = "0" * 64
                    if error:
                        with self.assertRaisesRegex(ValueError, error):
                            verify(path, digest)
                    else:
                        self.assertEqual(verify(path, digest), 1)
