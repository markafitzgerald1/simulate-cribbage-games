"""Enforced fallback cannot erase training or opponent-discard resume identity."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from artifact_pipeline import generate_play_table as generator
from artifact_pipeline.pegging import ROLES, LegacyHeuristicPolicy, TabularPeggingPolicy
from artifact_pipeline.promotion_gate import validate_promotion_resume


class TestPromotionResume(unittest.TestCase):
    def _run(self, directory, policies, discard_index=0, mode="enforce"):
        context = generator.AnalyticalContext(
            [1.0],
            [1.0],
            [],
            {},
            [],
            [],
            [((0, 0, 0, 0, 1, 1), discard_index, discard_index)],
        )
        argv = [
            "generate_play_table.py",
            "--hand-limit=1",
            "--outer-iterations=1",
            "--ibr-iterations=1",
            "--workers=1",
            "--promotion-gate-deals=2",
            f"--promotion-gate={mode}",
            f"--output={directory}/full.json",
            f"--client-output={directory}/client.json",
            f"--lines-output={directory}/lines.json",
        ]

        def sample(_discard, _policies, **kwargs):
            if kwargs.get("existing_table") is not None:
                generator.validate_resume_table(
                    kwargs["existing_table"],
                    kwargs["seed"],
                    kwargs["play_policy_fingerprint"],
                )
            return {
                "__metadata__": {
                    "generation_method": generator.GENERATION_METHOD,
                    "seed": kwargs["seed"],
                    "policy_fingerprint": kwargs.get("play_policy_fingerprint"),
                }
            }

        with patch("sys.argv", argv), patch.object(
            generator, "solve_initial_discard_policy", return_value=context
        ), patch.object(
            generator, "train_iterative_best_response", return_value=(policies, [])
        ), patch.object(
            generator, "generate_play_table", side_effect=sample
        ), patch.object(
            generator, "refine_discard_policy", return_value=(context, 0, 0)
        ), patch.object(
            generator, "_write_lines"
        ), patch(
            "builtins.print"
        ):
            generator.main()
        return json.loads(Path(directory, "full.json").read_bytes())

    def test_changed_training_or_discard_context_rejects_same_legacy_fingerprint(self):
        legacy = {role: LegacyHeuristicPolicy() for role in ROLES}
        different_training = {role: TabularPeggingPolicy({}) for role in ROLES}
        for policies, discard_index in ((different_training, 0), (legacy, 1)):
            with self.subTest(
                discard_index=discard_index
            ), tempfile.TemporaryDirectory() as directory:
                first = self._run(directory, legacy)
                self.assertEqual(
                    first["__metadata__"]["promotion_gate"]["measured_policy"],
                    "legacy-heuristic",
                )
                with self.assertRaisesRegex(ValueError, "promotion.*context"):
                    self._run(directory, policies, discard_index)

    def test_guard_defers_trained_selection_and_rejects_missing_current_context(self):
        validate_promotion_resume({}, {"mode": "enforce", "measured_policy": "trained"})
        with self.assertRaisesRegex(ValueError, "promotion.*context"):
            validate_promotion_resume(
                {"__metadata__": {"promotion_gate": {}}},
                {"mode": "enforce", "measured_policy": "legacy-heuristic"},
            )

    def test_same_enforced_context_resumes_and_other_modes_keep_existing_checks(self):
        legacy = {role: LegacyHeuristicPolicy() for role in ROLES}
        for mode in ("enforce", "report", "off"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                first = self._run(directory, legacy, mode=mode)
                second = self._run(directory, legacy, mode=mode)
                self.assertEqual(first, second)
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, legacy)
            path = Path(directory, "full.json")
            document = json.loads(path.read_bytes())
            document["__metadata__"].pop("promotion_gate")
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "promotion.*context"):
                self._run(directory, legacy)
