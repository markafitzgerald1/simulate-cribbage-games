"""Exercise the release replacement command with a local GitHub fixture."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_cfr_inputs_workflow import load

ROOT = Path(__file__).parent
WORKFLOW = ROOT / ".github/workflows/reexport-play-lines.yml"
MANIFEST = Path("examples/fixed-play-release.sha256")
CHECKER = Path("scripts/check_crib_release_assets.sh")
LINES = "expected_play_points.lines.json"


@unittest.skipUnless(shutil.which("jq"), "jq is required by the release workflow")
class ReexportPlayLinesWorkflowTest(unittest.TestCase):
    def test_publish_verifies_before_and_after_uploading_only_lines(self):
        steps = load(WORKFLOW)["jobs"]["publish"]["steps"]
        command = next(
            step["run"]
            for step in steps
            if step.get("name") == "Verify and replace only the lines asset"
        )
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for path in (MANIFEST, CHECKER):
            (folder / path.parent).mkdir(exist_ok=True)
            shutil.copyfile(ROOT / path, folder / path)
        assets = []
        for line in (folder / MANIFEST).read_text().splitlines():
            digest, name = line.split("  ")
            assets.append(
                {"digest": f"sha256:{digest}", "name": name, "state": "uploaded"}
            )
        lines_digest = hashlib.sha256(b"replacement").hexdigest()
        updated = [
            (
                {**asset, "digest": f"sha256:{lines_digest}"}
                if asset["name"] == LINES
                else asset
            )
            for asset in assets
        ]
        fake = """
gh() {
    if [[ "$*" == 'api repos/o/r/releases/tags/expected-play-points' ]]; then
        if [[ -f uploaded ]]; then cat after.json; else cat before.json; fi
    else
        [[ "$*" == 'release upload expected-play-points expected_play_points.lines.json --repo o/r --clobber' ]] || return 1
        touch uploaded
    fi
}
"""
        stale = [{**assets[0], "digest": "sha256:stale"}, *assets[1:]]
        for before, after, content, ok, uploaded in (
            (assets, updated, b"replacement", True, True),
            (stale, updated, b"replacement", False, False),
            (assets, updated, b"tampered", False, False),
            (assets, assets, b"replacement", False, True),
        ):
            with self.subTest(ok=ok, uploaded=uploaded, content=content):
                marker = folder / "uploaded"
                marker.unlink(missing_ok=True)
                (folder / LINES).write_bytes(content)
                (folder / "before.json").write_text(json.dumps({"assets": before}))
                (folder / "after.json").write_text(json.dumps({"assets": after}))
                result = subprocess.run(
                    [
                        "bash",
                        "-eo",
                        "pipefail",
                        "-c",
                        "GITHUB_REPOSITORY=o/r\n"
                        f"LINES_SHA256={lines_digest}\n" + fake + command,
                    ],
                    cwd=folder,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode == 0, ok, result.stderr)
                self.assertEqual(marker.exists(), uploaded)
