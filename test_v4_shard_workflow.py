"""Guard the approved manual shadow budget without dispatching a workflow."""

import json
from pathlib import Path
import re
import unittest

WORKFLOW = Path(__file__).parent / ".github/workflows/shadow-crib-v4.yml"


class TestV4ShadowWorkflow(unittest.TestCase):
    def _require_fragment(self, fragment, workflow):
        self.assertTrue(fragment in workflow, fragment)

    def test_manual_readonly_two_wave_budget_and_publication_boundary(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self._require_fragment("  workflow_dispatch:\n", workflow)
        self._require_fragment("  contents: read\n", workflow)
        for forbidden in (
            "schedule:",
            "pull_request:",
            "contents: write",
            "action-gh-release",
            "gh release create",
            "continue-on-error:",
        ):
            self.assertNotIn(forbidden, workflow)
        matrices = re.findall(r"shard: (\[[^\n]+\])", workflow)
        self.assertEqual(
            [json.loads(value) for value in matrices], [list(range(8))] * 2
        )
        self.assertEqual(workflow.count("max-parallel: 8"), 2)
        self.assertEqual(workflow.count("fail-fast: false"), 2)
        self.assertEqual(workflow.count("timeout-minutes: 180"), 2)
        self.assertEqual(workflow.count("timeout-minutes: 120"), 3)
        self.assertEqual(workflow.count("+ 9000"), 2)
        self._require_fragment("shell: bash", workflow)
        self.assertEqual(workflow.count("--shard '${{ matrix.shard }}'"), 2)
        self.assertEqual(workflow.count("--output work | tee measurement.jsonl"), 2)
        for previous in (
            "initialize",
            "generation0",
            "assemble0",
            "generation1",
            "assemble1",
        ):
            self._require_fragment(f"needs: {previous}\n", workflow)

    def test_reference_is_pinned_before_bootstrap_and_each_phase_keeps_its_plan(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self._require_fragment("releases/assets/$asset_id", workflow)
        self.assertNotIn("gh release download", workflow)
        self.assertLess(
            workflow.index("require_complete=True"),
            workflow.index("--convergence-threshold=0.001"),
        )
        for command in (
            "measure --plan plan0/plan.json",
            "measure --plan assembled0/next-plan.json",
            "assemble --plan plan0/plan.json",
            "assemble --plan assembled0/next-plan.json",
            "--plan assembled0/next-plan.json --assembled assembled1",
        ):
            self._require_fragment(command, workflow)
        for wave in (0, 1):
            self._require_fragment(f"--shards wave{wave}/v4-shadow-g{wave}-*", workflow)
            self._require_fragment(
                f"name: v4-shadow-g{wave}-${{{{ matrix.shard }}}}", workflow
            )
            self._require_fragment(
                f"name: v4-shadow-timing-g{wave}-${{{{ matrix.shard }}}}", workflow
            )
        self.assertEqual(workflow.count("python-version-file: .python-version"), 6)


if __name__ == "__main__":
    unittest.main()
