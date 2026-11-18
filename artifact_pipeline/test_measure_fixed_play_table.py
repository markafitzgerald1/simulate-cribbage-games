"""Real v3 measurements, exact tiny models, CLI exports and provenance guards."""

import hashlib
import json
import os
from pathlib import Path
import random
import unittest
from unittest.mock import Mock, patch

from artifact_pipeline.export_uncertainty import (
    build_sidecar,
    decode_sidecar,
    encode_json,
)
from artifact_pipeline.generate_play_table import (
    GENERATION_METHOD,
    sample_opponent_keep,
    build_client_table,
    validate_resume_table,
)
from artifact_pipeline.measure_fixed_play_table import (
    GateSettings,
    load_fixed_discards,
    main,
    measure_fixed_table,
)
from artifact_pipeline.test_fixed_policy_fixtures import bind, make_bundle
from artifact_pipeline.pegging import DEALER, PONE, PeggingState
from artifact_pipeline.test_six_layer_policy import temporary_directory


class TestFixedMeasurement(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(temporary_directory()))
        self.path = make_bundle(self.root)

    def update_discards(self, document):
        destination = self.root / "discards.json"
        destination.write_text(json.dumps(document))
        manifest = json.loads(self.path.read_text())
        manifest["discard_population"].update(bind(self.root, "discards.json"))
        self.path.write_text(json.dumps(manifest))
        return manifest["discard_population"]

    def test_exact_both_seat_measurement_and_pairing(self):
        # Four fives are disjoint from A-A-2-9. Enumerating all1000 root CDF
        # draws gives Pone3 minus Dealer1, or Dealer1 minus Pone1 respectively.
        random_type = random.Random
        values = iter(range(1000))

        def fake_rng(_seed):
            rng = Mock(spec=random_type)
            rng.randrange.side_effect = lambda _stop: next(values)
            return rng

        with patch(
            "artifact_pipeline.generate_play_table.sample_opponent_keep",
            return_value=(4, 4, 4, 4),
        ), patch(
            "artifact_pipeline.generate_play_table.random.Random", side_effect=fake_rng
        ):
            # Reset the common quantile enumerator when entering the second role.
            values = iter(list(range(1000)) * 2)
            table = measure_fixed_table(
                self.path, 1000, 42, [(0, 0, 1, 8)], GateSettings("off")
            )
        entry = table["A_A_2_9"]
        self.assertEqual(entry["Pone"]["mu"], 2)
        self.assertEqual(entry["Dealer"]["mu"], 0)
        self.assertEqual(entry["Pone"]["se"], 0)
        self.assertEqual(entry["Dealer"]["se"], 0)
        self.assertEqual(
            {lead: cell["n"] for lead, cell in entry["Pone"]["opening"].items()},
            {"0": 500, "8": 500},
        )
        metadata = table["__metadata__"]
        self.assertEqual(metadata["generation_method"], GENERATION_METHOD)
        self.assertEqual(metadata["measured_policy"], "trained")
        self.assertIs(metadata["joint_policy_converged"], False)
        self.assertIs(metadata["discard_refinement_converged"], False)
        self.assertEqual(metadata["decision_count_total"], 16000)
        self.assertEqual(metadata["decision_count_trained"], 2000)
        full, means = encode_json(table), encode_json(build_client_table(table))
        sidecar = encode_json(build_sidecar("play", full, means))
        decoded = decode_sidecar(sidecar, means)
        self.assertEqual(decoded["means_sha256"], hashlib.sha256(means).hexdigest())
        self.assertEqual(decoded["provenance"]["measured_policy"], "trained")
        with self.assertRaises(ValueError):
            decode_sidecar(sidecar, means + b" ")
        with self.assertRaisesRegex(ValueError, "different play policy"):
            validate_resume_table(
                table,
                42,
                "a" * 64 + ":" + "b" * 64,
                metadata["discard_policy_fingerprint"],
            )

    def test_real_physical_sampler_and_no_training(self):
        with patch(
            "artifact_pipeline.generate_play_table.refine_discards",
            side_effect=AssertionError("Training/refinement is forbidden"),
        ), patch(
            "artifact_pipeline.generate_play_table.train_iterative_best_response",
            side_effect=AssertionError("Training is forbidden"),
        ), patch(
            "artifact_pipeline.generate_play_table.sample_opponent_keep",
            wraps=sample_opponent_keep,
        ) as sampler:
            table = measure_fixed_table(
                self.path, 20, 43, [(0, 0, 1, 8)], GateSettings("off")
            )
        self.assertEqual(table["A_A_2_9"]["Pone"]["n"], 20)
        self.assertEqual(table["A_A_2_9"]["Dealer"]["n"], 20)
        self.assertEqual(table["__metadata__"]["decision_count_total"], 320)
        self.assertEqual(sampler.call_count, 40)

    def test_physical_population_removes_all_known_aces(self):
        spec = json.loads(self.path.read_text())["discard_population"]
        discards = load_fixed_discards(self.root, spec)
        rng = random.Random(42)
        sampled = [
            sample_opponent_keep((0, 0, 0, 0), "Dealer", discards, rng)
            for _ in range(120)
        ]
        self.assertTrue(all(0 not in hand for hand in sampled))
        self.assertGreater(len(set(sampled)), 10)

    def test_gate_validation_failure_and_gate_counters_excluded(self):
        for gate in [GateSettings("invalid"), GateSettings("report", 1)]:
            with self.assertRaises(ValueError):
                measure_fixed_table(self.path, 2, 42, [], gate)
        report = {"promotion_gate": {"passed": False}}
        with patch(
            "artifact_pipeline.measure_fixed_play_table.promotion_gate_metadata",
            return_value=report,
        ):
            with self.assertRaisesRegex(ValueError, "failed the safety gate"):
                measure_fixed_table(self.path, 2, 42, [], GateSettings("enforce"))

        def evaluate(policies, _args):
            policies[PONE].select_rank(
                PeggingState({PONE: [0, 0, 1, 8], DEALER: [4] * 4}).view(),
                random.Random(1),
            )
            return {"promotion_gate": {"passed": True}}

        with patch(
            "artifact_pipeline.measure_fixed_play_table.promotion_gate_metadata",
            side_effect=evaluate,
        ):
            table = measure_fixed_table(self.path, 2, 42, [], GateSettings("enforce"))
        self.assertEqual(table["__metadata__"]["decision_count_total"], 0)
        self.assertEqual(table["__metadata__"]["decision_share_forced"], 0)

    def test_discard_population_rejections(self):
        original = json.loads((self.root / "discards.json").read_text())
        for malformed in [
            [],
            {},
            {"keeps": "bad"},
            {"keeps": [["Pone"]]},
            {"keeps": [["other", [0] * 6, [0] * 4]]},
            {"keeps": [["Pone", [0, 1, 2, 3, 4, True], [0, 1, 2, 3]]]},
            {"keeps": [["Pone", [0] * 6, [0] * 4]]},
            {"keeps": [["Pone", [0, 1, 2, 3, 4, 5], [0, 1, 2, 12]]]},
            {"keeps": original["keeps"][:1]},
            {"keeps": original["keeps"][:1] * 2},
        ]:
            spec = self.update_discards(malformed)
            with self.assertRaises(ValueError):
                load_fixed_discards(self.root, spec)
        spec = self.update_discards(
            {"keeps": [["Pone", [0, 1, 2, 3, 4, 5], [0, 1, 2, 13]]]}
        )
        with self.assertRaises(ValueError):
            load_fixed_discards(self.root, spec)
        spec = self.update_discards(original)
        for changed in [
            {"keep_fingerprint": "f" * 64},
            {"converged": True},
            {"description": ""},
        ]:
            with self.assertRaises(ValueError):
                load_fixed_discards(self.root, {**spec, **changed})

    def test_duplicate_discard_json_names_are_rejected(self):
        destination = self.root / "discards.json"
        destination.write_text('{"keeps":[],"keeps":[]}')
        spec = json.loads(self.path.read_text())["discard_population"]
        spec.update(bind(self.root, "discards.json"))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            load_fixed_discards(self.root, spec)

    def test_empty_discard_payload_fails(self):
        destination = self.root / "discards.json"
        destination.write_bytes(b"")
        spec = json.loads(self.path.read_text())["discard_population"]
        spec.update(bind(self.root, "discards.json"))
        with self.assertRaises(ValueError):
            load_fixed_discards(self.root, spec)

    def test_fractional_exact_expectation_with_varying_outcomes(self):
        random_type = random.Random
        quantiles = iter(range(1000))

        def fake_rng(_seed):
            rng = Mock(spec=random_type)
            rng.randrange.side_effect = lambda _stop: next(quantiles)
            return rng

        with patch(
            "artifact_pipeline.generate_play_table.sample_opponent_keep",
            return_value=(0, 4, 6, 9),
        ), patch(
            "artifact_pipeline.generate_play_table.random.Random", side_effect=fake_rng
        ):
            table = measure_fixed_table(
                self.path, 1000, 42, [(0, 0, 1, 8)], GateSettings("off")
            )
        pone = table["A_A_2_9"]["Pone"]
        self.assertAlmostEqual(pone["mu"], 5.5)
        self.assertAlmostEqual(pone["players"][PONE]["mu"], 8.5)
        self.assertAlmostEqual(pone["players"][DEALER]["mu"], 3)
        self.assertAlmostEqual(pone["se"], (0.25 / 999) ** 0.5)
        self.assertEqual(table["A_A_2_9"]["Dealer"]["mu"], 3)

    def test_cli_exports_real_pair_and_refuses_aliases(self):
        paths = [
            self.root / name
            for name in ("full.json", "means.json", "lines.json", "sidecar.json")
        ]
        args = [
            "measure",
            "--policy-manifest",
            str(self.path),
            "--samples",
            "2",
            "--hand-limit",
            "1",
            "--promotion-gate",
            "off",
        ]
        for flag, path in zip(
            ["--output", "--client-output", "--lines-output", "--uncertainty-output"],
            paths,
        ):
            args += [flag, str(path)]
        with patch("sys.argv", args):
            main()
        self.assertEqual(
            len(decode_sidecar(paths[3].read_bytes(), paths[1].read_bytes())["keys"]), 1
        )
        with patch(
            "sys.argv", args + ["--client-output", str(paths[0])]
        ), self.assertRaises(SystemExit):
            main()
        with patch("sys.argv", args + ["--output", str(self.path)]), self.assertRaises(
            SystemExit
        ):
            main()
        # A pinned input at the writer's staging path would be truncated.
        document = json.loads(self.path.read_text())
        staged = f"{paths[0].name}.tmp-{os.getpid()}"
        original = document["probabilities"]["file"]
        (self.root / original).rename(self.root / staged)
        document["probabilities"]["file"] = staged
        self.path.write_text(json.dumps(document))
        with patch("sys.argv", args), self.assertRaises(SystemExit):
            main()
        self.assertTrue((self.root / staged).exists())
        # A symlinked output still stages beside the link, not its target.
        target = self.root / "real"
        target.mkdir()
        link = self.root / "linked.json"
        link.symlink_to(target / "full.json")
        linked_stage = f"{link.name}.tmp-{os.getpid()}"
        (self.root / staged).rename(self.root / linked_stage)
        document["probabilities"]["file"] = linked_stage
        self.path.write_text(json.dumps(document))
        with patch("sys.argv", args + ["--output", str(link)]), self.assertRaises(
            SystemExit
        ):
            main()
        self.assertTrue((self.root / linked_stage).exists())
        staged = linked_stage
        (self.root / staged).rename(self.root / original)
        document["probabilities"]["file"] = original
        self.path.write_text(json.dumps(document))
        args_no_limit = [
            "measure",
            "--policy-manifest",
            str(self.path),
            "--promotion-gate",
            "off",
        ]
        with patch("sys.argv", args_no_limit), patch(
            "artifact_pipeline.measure_fixed_play_table.measure_fixed_table",
            return_value={},
        ):
            with patch("artifact_pipeline.measure_fixed_play_table._write_json"), patch(
                "artifact_pipeline.measure_fixed_play_table._write_lines"
            ), patch(
                "artifact_pipeline.measure_fixed_play_table.build_sidecar",
                return_value={},
            ):
                # Use existing tiny outputs for the final export read boundary.
                for flag, path in zip(
                    [
                        "--output",
                        "--client-output",
                        "--lines-output",
                        "--uncertainty-output",
                    ],
                    paths,
                ):
                    args_no_limit += [flag, str(path)]
                main()


if __name__ == "__main__":
    unittest.main()
