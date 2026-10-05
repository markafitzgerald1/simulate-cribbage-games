"""Actual enforced policy identity survives checkpoints and read-only exports."""

import json
from pathlib import Path
import tempfile
import unittest

from artifact_pipeline.export_uncertainty import (
    build_sidecar,
    decode_sidecar,
    encode_json,
)
from artifact_pipeline.play_lines import decode_lines, QUALIFICATIONS
from artifact_pipeline.play_quality import measure_quality
from artifact_pipeline.test_enforced_discards import run_fixture


class TestMeasuredProvenance(unittest.TestCase):
    def test_enforced_identity_survives_checkpoint_lines_and_sidecar(self):
        for passed, policy, averaging in (
            (False, "legacy-heuristic", None),
            (True, "trained", "geometric"),
        ):
            with self.subTest(
                passed=passed
            ), tempfile.TemporaryDirectory() as directory:
                events, outputs = run_fixture(Path(directory), "enforce", passed=passed)
            full = json.loads(outputs["full"])
            metadata = full["__metadata__"]
            sidecar = build_sidecar("play", outputs["full"], outputs["client"])
            self.assertEqual(
                decode_sidecar(encode_json(sidecar), outputs["client"]), sidecar
            )
            lines = decode_lines(outputs["lines"], outputs["client"])
            self.assertEqual(lines["qualifications"], QUALIFICATIONS)
            for provenance in (
                metadata,
                events["checkpoints"][0]["__metadata__"],
                sidecar["provenance"],
                lines["provenance"],
            ):
                self.assertTrue("measured_policy" in provenance)
                self.assertTrue("policy_averaging" in provenance)
                self.assertEqual(provenance["measured_policy"], policy)
                self.assertEqual(provenance["policy_averaging"], averaging)
                self.assertEqual(
                    provenance["policy_fingerprint"], metadata["policy_fingerprint"]
                )
            self.assertEqual(
                metadata["promotion_gate"]["training_policy_averaging"], "geometric"
            )
            self.assertNotIn("promotion_gate", sidecar["provenance"])
            if not passed:
                quality = measure_quality(
                    outputs["lines"], outputs["client"], minimum_lead_count=2
                )
                self.assertEqual(quality["keys_total"], 1)
                self.assertEqual(quality["keys_eligible"], 0)
                self.assertEqual(quality["keys_flagged"], 0)
                for name in (
                    "flagged_share",
                    "gain_mean",
                    "gain_population_sd",
                    "gain_max",
                ):
                    self.assertIsNone(quality[name])


if __name__ == "__main__":
    unittest.main()
