"""Guard the approved manual shadow budget without dispatching a workflow."""

import hashlib
import json
from pathlib import Path
import re
import unittest

import yaml  # type: ignore[import-untyped]

WORKFLOW = Path(__file__).parent / ".github/workflows/shadow-crib-v4.yml"


def guard_accepts(expression, **context):
    """Evaluate the workflow's Boolean guard with explicit Actions context values."""
    expression = re.sub(
        r"(?:github|inputs)\.[a-z_]+",
        lambda match: repr(context.get(match[0], False)),
        expression,
    )
    expression = expression.replace("&&", " and ").replace("||", " or ")
    expression = expression.replace("!", " not ")
    return bool(eval(expression.strip(), {"__builtins__": {}}, {}))


class TestV4ShadowWorkflow(unittest.TestCase):
    def _require_fragment(self, fragment, workflow):
        self.assertTrue(fragment in workflow, fragment)

    def test_activation_runtime_pins_match_the_repository_runtime(self):
        # A Python or requirements bump must re-pin here, in review, rather
        # than surface as a failed activation dispatch.
        workflow = yaml.safe_load(WORKFLOW.read_text())
        steps = workflow["jobs"]["initialize"]["steps"]
        step = next(
            s
            for s in steps
            if s.get("name") == "Verify approved activation runtime pins"
        )
        pins = re.findall(r"^([0-9a-f]{64})  (\S+)$", step["run"], re.MULTILINE)
        self.assertEqual(
            sorted(name for _, name in pins), [".python-version", "requirements.txt"]
        )
        for digest, name in pins:
            data = (WORKFLOW.parents[2] / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest, name)

    def test_every_sampling_entry_requires_explicit_manual_authorization(self):
        workflow = yaml.safe_load(WORKFLOW.read_text())
        approved = {
            "github.event_name": "workflow_dispatch",
            "github.ref": "refs/heads/main",
            "github.run_attempt": 1,
            "inputs.prepare_activation": True,
            "inputs.approval": "prepare",
        }
        shadow = {
            **approved,
            "inputs.prepare_activation": False,
            "inputs.approval": "shadow",
        }
        standalone = {
            key: value
            for key, value in shadow.items()
            if key != "inputs.prepare_activation"
        }
        for job in ("initialize", "generation0", "generation1"):
            guard = workflow["jobs"][job]["if"]
            # Standalone dispatch has no prepare_activation input.
            self.assertTrue(guard_accepts(guard, **standalone))
            for context in (approved, shadow):
                with self.subTest(job=job, context=context):
                    self.assertTrue(guard_accepts(guard, **context))
                rejected = [
                    {**context, "github.event_name": event}
                    for event in ("pull_request", "schedule", "push")
                ] + [
                    {**context, "github.ref": "refs/heads/feature"},
                    {**context, "github.ref": "refs/tags/main"},
                    {**context, "github.run_attempt": 2},
                    {**context, "inputs.approval": ""},
                    {**context, "inputs.approval": "publish"},
                    {
                        **context,
                        "inputs.prepare_activation": not context[
                            "inputs.prepare_activation"
                        ],
                    },
                    {
                        key: value
                        for key, value in context.items()
                        if not key.startswith("inputs.")
                    },
                    {
                        key: value
                        for key, value in context.items()
                        if key != "inputs.approval"
                    },
                ]
                for invalid in rejected:
                    with self.subTest(job=job, rejected=invalid):
                        self.assertFalse(guard_accepts(guard, **invalid))

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
        self._require_fragment("bash scripts/download_crib_v3_reference.sh", workflow)
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
