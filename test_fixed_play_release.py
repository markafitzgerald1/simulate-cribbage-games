"""Bounded CLI/export acceptance and fail-closed release bundle validation."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from artifact_pipeline.export_uncertainty import build_sidecar
from artifact_pipeline.generate_play_table import (
    _write_json,
    _write_lines,
    build_client_table,
)
from artifact_pipeline.measure_fixed_play_table import (
    GateSettings,
    measure_fixed_table,
    main as measure_main,
)
from artifact_pipeline.pegging import canonical_hand_key, get_canonical_hands
from artifact_pipeline.test_fixed_policy_fixtures import make_bundle
from artifact_pipeline.test_six_layer_policy import temporary_directory
from scripts.run_fixed_play_smoke import main as smoke_main, run_smoke
from scripts.verify_fixed_play_bundle import main as verify_main, verify_bundle


class TestFixedPlayRelease(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(temporary_directory()))
        self.manifest = make_bundle(self.root)
        self.pin = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        self.paths = {
            name: self.root / f"{name}.json"
            for name in ("full", "means", "sidecar", "lines")
        }
        self.table = measure_fixed_table(
            self.manifest, 2, 42, [(0, 0, 1, 8)], GateSettings("off")
        )
        self.write_bundle(self.table)

    def write_bundle(self, table):
        _write_json(str(self.paths["full"]), table)
        _write_json(str(self.paths["means"]), build_client_table(table), compact=True)
        _write_lines(str(self.paths["lines"]), str(self.paths["means"]), table)
        _write_json(
            str(self.paths["sidecar"]),
            build_sidecar(
                "play",
                self.paths["full"].read_bytes(),
                self.paths["means"].read_bytes(),
            ),
            compact=True,
        )

    def test_pairing_pin_and_stale_companions(self):
        self.assertEqual(
            verify_bundle(self.paths, self.pin), self.table["__metadata__"]
        )
        with self.assertRaisesRegex(ValueError, "approved pin"):
            verify_bundle(self.paths, "f" * 64)
        sidecar = json.loads(self.paths["sidecar"].read_bytes())
        sidecar["source_full_sha256"] = "f" * 64
        self.paths["sidecar"].write_text(json.dumps(sidecar))
        with self.assertRaisesRegex(ValueError, "Sidecar differs"):
            verify_bundle(self.paths, self.pin)
        self.write_bundle(self.table)
        lines = json.loads(self.paths["lines"].read_bytes())
        lines["provenance"]["joint_policy_converged"] = True
        self.paths["lines"].write_text(json.dumps(lines))
        with self.assertRaisesRegex(ValueError, "Opening lines differ"):
            verify_bundle(self.paths, self.pin)

    def test_release_completeness_counts_gate_and_provenance(self):
        with self.assertRaisesRegex(ValueError, "every canonical"):
            verify_bundle(self.paths, self.pin, 2)
        # Synthetic complete documents exercise release guards, not inference.
        complete = {}
        for hand in get_canonical_hands():
            entry = deepcopy(self.table["A_A_2_9"])
            for role in ("Pone", "Dealer"):
                entry[role]["opening"] = {
                    str(hand[0]): {
                        "n": 2,
                        "mean": 0.0,
                        "moment_2": 0.0,
                        "responses": {str(hand[0]): 2},
                    }
                }
            complete[canonical_hand_key(hand)] = entry
        complete["__metadata__"] = deepcopy(self.table["__metadata__"])
        self.write_bundle(complete)
        with self.assertRaisesRegex(ValueError, "approved samples"):
            verify_bundle(self.paths, self.pin, 3)
        with self.assertRaisesRegex(ValueError, "passed enforced"):
            verify_bundle(self.paths, self.pin, 2)
        complete["__metadata__"]["promotion_gate"] = {"mode": "report", "passed": True}
        self.write_bundle(complete)
        with self.assertRaisesRegex(ValueError, "passed enforced"):
            verify_bundle(self.paths, self.pin, 2)
        complete["__metadata__"]["promotion_gate"] = {
            "mode": "enforce",
            "passed": False,
        }
        self.write_bundle(complete)
        with self.assertRaisesRegex(ValueError, "passed enforced"):
            verify_bundle(self.paths, self.pin, 2)
        complete["__metadata__"]["promotion_gate"]["passed"] = True
        for field, wrong in [
            ("measurement_backend", "native"),
            ("joint_policy_converged", True),
            ("discard_refinement_converged", True),
        ]:
            bad = deepcopy(complete)
            bad["__metadata__"][field] = wrong
            self.write_bundle(bad)
            with self.assertRaisesRegex(ValueError, "truthful"):
                verify_bundle(self.paths, self.pin, 2)
        # The sparse fixture falls back to the heuristic; a release may not.
        self.assertGreater(
            complete["__metadata__"]["decision_count_missing_menu_fallback"], 0
        )
        complete["__metadata__"]["decision_count_missing_menu_fallback"] = 0
        complete["__metadata__"]["decision_count_off_support"] = 0
        for category, wrong in [
            ("missing_menu_fallback", 1),
            ("off_support", 1),
            ("off_support", None),
        ]:
            bad = deepcopy(complete)
            bad["__metadata__"][f"decision_count_{category}"] = wrong
            self.write_bundle(bad)
            with self.assertRaisesRegex(ValueError, f"zero {category}"):
                verify_bundle(self.paths, self.pin, 2)
        self.write_bundle(complete)
        self.assertEqual(
            verify_bundle(self.paths, self.pin, 2), complete["__metadata__"]
        )

    def test_bounded_offline_cli_and_export(self):
        destination = self.root / "smoke"
        with patch("sys.argv", ["smoke", "--output-dir", str(destination)]):
            smoke_main()
        args = ["verify", "--policy-manifest-sha256", self.pin]
        for name, path in self.paths.items():
            args.extend([f"--{name}", str(path)])
        with patch("sys.argv", args):
            verify_main()

    def test_bounded_fixture_rejects_missing_records_and_no_activation(self):
        original = self.root / "smoke"
        # Only the failure contract is mocked; the previous test runs the CLI.
        with patch("scripts.run_fixed_play_smoke.subprocess.run"), patch(
            "pathlib.Path.read_bytes", return_value=b"{}"
        ), patch(
            "scripts.run_fixed_play_smoke.make_bundle", return_value=self.manifest
        ):
            with patch(
                "scripts.run_fixed_play_smoke.decode_sidecar",
                return_value={"record_groups": {"totals": {"record_count": 0}}},
            ), patch(
                "scripts.run_fixed_play_smoke.decode_lines",
                return_value={"entries": []},
            ):
                with self.assertRaisesRegex(ValueError, "lost measured"):
                    run_smoke(original)
            sidecar = {
                "record_groups": {"totals": {"record_count": 42}},
                "provenance": {"decision_count_trained": 0},
            }
            with patch(
                "scripts.run_fixed_play_smoke.decode_sidecar", return_value=sidecar
            ), patch(
                "scripts.run_fixed_play_smoke.decode_lines",
                return_value={"entries": [None] * 21},
            ):
                with self.assertRaisesRegex(ValueError, "never exercised"):
                    run_smoke(original)

    def test_checkpoint_cli_alias_and_timestamp_guards(self):
        base = [
            "measure",
            "--policy-manifest",
            str(self.manifest),
            "--policy-manifest-sha256",
            self.pin,
            "--checkpoint-dir",
            str(self.root),
        ]
        with patch("sys.argv", base), self.assertRaises(SystemExit):
            measure_main()
        with patch(
            "sys.argv", base + ["--generated-at", "2026-10-12T16:00:00Z"]
        ), self.assertRaises(SystemExit):
            measure_main()
        safe = base[:-1] + [
            str(self.root / "cli-cells"),
            "--generated-at",
            "2026-10-12T16:00:00Z",
            "--samples",
            "2",
            "--hand-limit",
            "1",
            "--promotion-gate",
            "off",
        ]
        for flag, path in zip(
            ("output", "client-output", "uncertainty-output", "lines-output"),
            self.paths.values(),
        ):
            safe.extend([f"--{flag}", str(path)])
        with patch("sys.argv", safe):
            measure_main()
        self.assertTrue((self.root / "cli-cells" / "A_A_A_A.Pone.json").exists())


if __name__ == "__main__":
    unittest.main()
