"""Bounded packaging and publication-integrity tests; no generation or sampling."""

import copy
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import prepare_crib_activation as activation

ROOT = Path(__file__).parent


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def packaging_fixture():
    """Synthetic scalar records cover the required identities without moments."""
    sidecar = json.loads(
        (
            ROOT / "artifact_pipeline/fixtures/crib-uncertainty-v2/sidecar.json"
        ).read_bytes()
    )
    sidecar["provenance"].update(
        generation=1,
        precut_resolved_negative=0,
        precut_resolved_positive=155,
        precut_unresolved=1,
    )
    means = {
        "__metadata__": {
            "generation_method": "artifact_pipeline.generate_table.v4",
            "generation": 1,
            "seed": 42,
        }
    }
    records = {}
    keys = []
    for first, second in itertools.combinations_with_replacement("A23456789TJQK", 2):
        for suited in [False] if first == second else [True, False]:
            key = f"{first}_{second}_{'Suited' if suited else 'Unsuited'}"
            keys.append(key)
            means[key] = {}
            for role in ("Dealer", "Pone"):
                means[key][role] = {}
                for rank in "A23456789TJQK":
                    slots = []
                    if suited or first == second == "J":
                        slots = ["non_matching_discard_suit"]
                        if rank not in (first, second):
                            slots.append("matching_discard_suit")
                    elif "J" in (first, second):
                        slots = ["non_matching_discard_suit"]
                        if rank != first:
                            slots.append("matching_rank_1_suit")
                        if rank != second:
                            slots.append("matching_rank_2_suit")
                    means[key][role][rank] = {
                        "mu": 5.0,
                        "starter_suit_relation": {slot: {"mu": 5.0} for slot in slots},
                    }
                    for slot in ["total", *slots]:
                        records[f"{key}/{role}/{rank}/{slot}"] = {
                            "mu": 5.0,
                            "n": 22000,
                            "reported_marginal_se": 0.02,
                        }
    sidecar["keys"] = keys
    sidecar["record_groups"]["totals"] = {
        "record_count": len(records),
        "records": records,
    }
    # Deliberate whitespace makes encoding the JSON again change the input bytes.
    full_bytes = b'{ "measurement": "bounded packaging fixture" }\n'
    means_bytes = (json.dumps(means, separators=(",", ":")) + "\n\n").encode()
    sidecar["source_full_sha256"] = sha256(full_bytes)
    sidecar["means_sha256"] = sha256(means_bytes)
    return full_bytes, means_bytes, sidecar


class TestPrepareCribActivation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.full_bytes, cls.means_bytes, cls.sidecar_fixture = packaging_fixture()
        assert cls.sidecar_fixture["record_groups"]["totals"]["record_count"] == 9076

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.final = self.root / "final"
        self.assembled = self.root / "assembled"
        self.output = self.root / "candidate"
        self.final.mkdir()
        self.assembled.mkdir()
        (self.final / activation.FULL).write_bytes(self.full_bytes)
        (self.final / activation.MEANS).write_bytes(self.means_bytes)
        self.result = self.bundle("shadow")
        self.assembly = self.bundle("generation")
        self.set_shift(0.10)
        self.save_bundles()
        self.sidecar = copy.deepcopy(self.sidecar_fixture)
        pin = patch.object(activation, "MEANS_SHA256", sha256(self.means_bytes))
        pin.start()
        self.addCleanup(pin.stop)
        exporter = patch.object(activation, "build_sidecar", return_value=self.sidecar)
        self.exporter = exporter.start()
        self.addCleanup(exporter.stop)

    def bundle(self, kind):
        return {
            "contract": "crib-v4-assembled-bundle-v1",
            "kind": kind,
            "success": True,
            "terminal": True,
            "generation": 1,
            "plan_sha256": "a" * 64,
            "files": {
                activation.FULL: sha256(self.full_bytes),
                activation.MEANS: sha256(self.means_bytes),
            },
        }

    def save_bundles(self):
        write_json(self.final / "bundle.json", self.result)
        write_json(self.assembled / "bundle.json", self.assembly)

    def set_shift(self, shift):
        diagnostics = self.assembled / "diagnostics.json"
        write_json(diagnostics, {"convergence_shift": shift})
        self.assembly["files"]["diagnostics.json"] = sha256(diagnostics.read_bytes())

    def prepare(self):
        activation.prepare(self.final, self.assembled, self.output)

    def reject_prepare(self, message):
        with self.assertRaisesRegex(ValueError, message):
            self.prepare()
        self.exporter.assert_not_called()
        self.assertFalse(self.output.exists())

    def save_sidecar(self):
        write_json(self.output / activation.SIDECAR, self.sidecar)

    def test_packaging_preserves_exact_inputs_and_hashes_uncompressed_bytes(self):
        self.prepare()
        self.exporter.assert_called_once_with("crib", self.full_bytes, self.means_bytes)
        self.assertEqual(
            (self.output / activation.MEANS).read_bytes(), self.means_bytes
        )
        self.assertEqual((self.final / activation.FULL).read_bytes(), self.full_bytes)
        self.assertEqual((self.final / activation.MEANS).read_bytes(), self.means_bytes)
        compressed = (self.output / (activation.FULL + ".gz")).read_bytes()
        self.assertEqual(gzip.decompress(compressed), self.full_bytes)
        self.assertEqual(compressed[4:8], b"\0\0\0\0")
        self.assertNotEqual(sha256(compressed), self.sidecar["source_full_sha256"])
        self.assertEqual(self.sidecar["provenance"]["convergence_shift"], 0.10)
        self.assertIsNone(activation.verify_candidate(self.output))

    def test_prepare_rejects_incomplete_or_failed_bundles(self):
        for bundle in (self.result, self.assembly):
            for field, invalid in (
                ("contract", "unknown"),
                ("kind", "plan"),
                ("success", False),
                ("terminal", False),
                ("generation", 0),
            ):
                with self.subTest(kind=bundle["kind"], field=field):
                    original = bundle[field]
                    bundle[field] = invalid
                    self.save_bundles()
                    self.reject_prepare("successful terminal generation")
                    bundle[field] = original

    def test_prepare_rejects_plan_mismatch(self):
        self.result["plan_sha256"] = "b" * 64
        self.save_bundles()
        self.reject_prepare("plans differ")

    def test_prepare_rejects_bundle_digest_mismatches(self):
        for bundle in (self.result, self.assembly):
            for name, message in (
                (activation.FULL, "full digest"),
                (activation.MEANS, "client digest"),
            ):
                with self.subTest(kind=bundle["kind"], name=name):
                    original = bundle["files"][name]
                    bundle["files"][name] = "0" * 64
                    self.save_bundles()
                    self.reject_prepare(message)
                    bundle["files"][name] = original

    def test_prepare_rejects_changed_means_bytes(self):
        with (self.final / activation.MEANS).open("ab") as handle:
            handle.write(b" ")
        self.reject_prepare("client digest")

    def test_prepare_rejects_changed_diagnostics(self):
        write_json(self.assembled / "diagnostics.json", {"convergence_shift": 0})
        self.reject_prepare("diagnostics digest")

    def test_prepare_enforces_gate_including_invalid_numbers(self):
        for shift in (
            -0.001,
            0.1000000001,
            float("inf"),
            float("nan"),
            True,
            "0.1",
            None,
        ):
            with self.subTest(shift=shift):
                self.set_shift(shift)
                self.save_bundles()
                self.reject_prepare("0.10 gate")

    def test_prepare_accepts_zero_shift(self):
        self.set_shift(0)
        self.save_bundles()
        self.prepare()
        self.assertIsNone(activation.verify_candidate(self.output))

    def test_prepare_rejects_wrong_export_or_negative_guard(self):
        for path, invalid in (
            (("schema",), "expected-points-uncertainty.v1"),
            (("source_full_sha256",), "0" * 64),
            (("record_groups", "totals", "record_count"), 9075),
            (("provenance", "precut_resolved_negative"), 1),
            (("provenance", "precut_resolved_negative"), None),
        ):
            with self.subTest(path=path, invalid=invalid):
                self.sidecar = copy.deepcopy(self.sidecar_fixture)
                parent = self.sidecar
                for key in path[:-1]:
                    parent = parent[key]
                parent[path[-1]] = invalid
                self.exporter.return_value = self.sidecar
                with self.assertRaisesRegex(ValueError, "sidecar differs"):
                    self.prepare()
                self.assertFalse(self.output.exists())

    def test_verify_rejects_valid_gzip_with_wrong_uncompressed_source(self):
        self.prepare()
        (self.output / (activation.FULL + ".gz")).write_bytes(
            gzip.compress(b"wrong table", mtime=0)
        )
        with self.assertRaisesRegex(ValueError, "uncompressed source digest"):
            activation.verify_candidate(self.output)

    def test_verify_rejects_gzip_transport_hash_as_source_digest(self):
        self.prepare()
        self.sidecar["source_full_sha256"] = sha256(
            (self.output / (activation.FULL + ".gz")).read_bytes()
        )
        self.save_sidecar()
        with self.assertRaisesRegex(ValueError, "uncompressed source digest"):
            activation.verify_candidate(self.output)

    def test_verify_rejects_corrupt_or_truncated_gzip(self):
        self.prepare()
        path = self.output / (activation.FULL + ".gz")
        compressed = path.read_bytes()
        corrupt = bytearray(compressed)
        corrupt[-8] ^= 1  # Corrupt the CRC while keeping the gzip header valid.
        for data in (b"not gzip", bytes(corrupt), compressed[:-4]):
            with self.subTest(data=data):
                path.write_bytes(data)
                with self.assertRaises((gzip.BadGzipFile, EOFError)):
                    activation.verify_candidate(self.output)

    def test_verify_rejects_changed_means(self):
        self.prepare()
        (self.output / activation.MEANS).write_bytes(self.means_bytes + b" ")
        with self.assertRaisesRegex(ValueError, "means_sha256"):
            activation.verify_candidate(self.output)

    def test_verify_requires_approved_pin_gate_and_guard(self):
        self.prepare()
        with patch.object(activation, "MEANS_SHA256", "0" * 64):
            with self.assertRaisesRegex(ValueError, "Invalid v4 release candidate"):
                activation.verify_candidate(self.output)
        for shift in (-0.001, 0.1000000001):
            self.sidecar["provenance"]["convergence_shift"] = shift
            self.save_sidecar()
            with self.assertRaises(ValueError):
                activation.verify_candidate(self.output)
        self.sidecar["provenance"].update(
            convergence_shift=0.10, precut_resolved_negative=1
        )
        self.save_sidecar()
        with self.assertRaisesRegex(ValueError, "Invalid v4 release candidate"):
            activation.verify_candidate(self.output)

    def test_cli_routes_verify_and_prepare_failures(self):
        self.prepare()
        # The CLI's real approved pin must reject our synthetic means.
        for arguments in (
            ["verify", str(self.output)],
            [str(self.final), str(self.assembled), str(self.root / "cli-output")],
        ):
            with self.subTest(arguments=arguments), patch.object(
                sys, "argv", ["prepare_crib_activation", *arguments]
            ):
                with self.assertRaises(ValueError):
                    runpy.run_path(activation.__file__, run_name="__main__")


if __name__ == "__main__":
    unittest.main()
