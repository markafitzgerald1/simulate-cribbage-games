"""Exercise the policy shard release gates without publishing anything."""

import hashlib
import json
from pathlib import Path
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
        # Catches an unverified handoff, skipped checksum, or widened asset glob.
        verify_steps = self.jobs["verify"]["steps"]
        download = verify_steps[4]["run"]
        self.assertTrue(
            "/actions/runs/$run_id/artifacts?name=pegging-policy-shards" in download
        )
        self.assertTrue(".digest == $digest" in download)
        self.assertLess(
            download.index("sha256sum"), download.index("verify_policy_shards")
        )
        self.assertTrue('jq -er .index_sha256 "$PINS"' in download)

        checkout, fetch, check, release, audit = self.jobs["publish"]["steps"]
        self.assertEqual(checkout["uses"], "actions/checkout@v7")
        self.assertNotIn("ref", checkout["with"])
        self.assertEqual(fetch["with"], {"name": verify_steps[-1]["with"]["name"]})
        self.assertEqual(verify_steps[-1]["with"]["path"], "${{ env.ARCHIVE }}")
        self.assertTrue('jq -er .artifact_sha256 "$PINS"' in check["run"])
        self.assertTrue("sha256sum --check --strict release.sha256" in check["run"])
        fixed_release = load(FIXED_PLAY)["jobs"]["publish"]["steps"][-2]
        self.assertEqual(release["uses"], fixed_release["uses"])
        self.assertEqual(release["with"]["tag_name"], "pegging-policy-shards")
        self.assertEqual(release["with"]["files"], "${{ env.ARCHIVE }}")
        self.assertEqual(release["with"]["fail_on_unmatched_files"], "true")
        self.assertEqual(release["with"]["make_latest"], "false")
        self.assertTrue("check_crib_release_assets.sh release.sha256" in audit["run"])
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


class VerifyPolicyShardsReleaseTest(unittest.TestCase):
    def test_rejects_changed_or_unlisted_bytes(self) -> None:
        shard = b"approved shard bytes"
        entry = {"file": SHARD, "sha256": hashlib.sha256(shard).hexdigest()}
        cases = [
            ("valid", [entry], {SHARD: shard}, None),
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
                    index = json.dumps(
                        {"schema": "pegging-policy-shards.v1", "shards": entries}
                    ).encode()
                    with ZipFile(path, "w") as archive:
                        archive.writestr("shards.json", index)
                        for filename, data in members.items():
                            archive.writestr(filename, data)
                    digest = hashlib.sha256(index).hexdigest()
                    if name == "index digest":
                        digest = "0" * 64
                    if error:
                        with self.assertRaisesRegex(ValueError, error):
                            verify(path, digest)
                    else:
                        self.assertEqual(verify(path, digest), 1)
