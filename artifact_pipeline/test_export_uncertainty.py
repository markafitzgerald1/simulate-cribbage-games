"""Contract and read-only regression tests for marginal-statistics sidecars."""

import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from artifact_pipeline import export_uncertainty as exporter
from artifact_pipeline.adapter import get_canonical_pairs
from artifact_pipeline.pegging import canonical_hand_key, get_canonical_hands
from scripts.measure_uncertainty import packed_candidate


def crib_bucket(key, rank, measured):
    bucket = copy.deepcopy(measured)
    bucket["points"] = {"fifteens": {"mu": 1.23456, "se": 99}}
    bucket["starter_suit_relation"] = {
        "non_matching_discard_suit": {**measured, "se": 0.05}
    }
    if key == "A_2_Suited" and rank not in ("A", "2"):
        bucket["starter_suit_relation"]["matching_discard_suit"] = measured.copy()
    if key == "A_J_Unsuited":
        if rank != "A":
            bucket["starter_suit_relation"]["matching_rank_1_suit"] = measured.copy()
        if rank != "J":
            bucket["starter_suit_relation"]["matching_rank_2_suit"] = measured.copy()
    return bucket


def fixture(table):
    """Small independent fixtures with all ranks but no generation code."""
    measured = {
        "mu": 7.749001108447055,
        "se": 0.023563883578079117,
        "n": 11461.568181821294,
        "sum_w2": 6360.283574380505,
    }
    if table == "play":
        measured = {
            "mu": -1.23456,
            "n": 13000,
            "se": 0.0252782869455673,
            "players": {
                "Dealer": {"mu": 3.0, "se": 1000},
                "Pone": {"mu": 4.23456, "se": 2000},
            },
        }
        full = {"A_2_3_4": {role: copy.deepcopy(measured) for role in exporter.ROLES}}
    else:
        full = {}
        for key in ("A_A_Unsuited", "A_2_Suited", "A_J_Unsuited", "J_J_Unsuited"):
            full[key] = {}
            for role in exporter.ROLES:
                full[key][role] = {}
                for rank in exporter.RANKS:
                    full[key][role][rank] = crib_bucket(key, rank, measured)

    def client(value):
        return {
            key: round(item, 4) if key == "mu" else client(item)
            for key, item in value.items()
            if key == "mu" or isinstance(item, dict)
        }

    means = client(full)
    if table == "crib":
        for role in exporter.ROLES:
            for bucket in means["A_A_Unsuited"][role].values():
                del bucket["starter_suit_relation"]
    full["__metadata__"] = {
        "seed": 42,
        "generation": 1,
        "use_control_variates": table == "crib",
        "joint_policy_converged": False,
        "policy_fingerprint": "fixed-policy",
        "generation_accumulators": {
            "A_A_Unsuited": {
                "Dealer": {
                    "A": {
                        **measured,
                        "mu": 7.748511329363203,
                        "policy_mu": 7.740845299442242,
                        "se": 999,
                    }
                }
            }
        },
        "training_history": [1, 2, 3],
    }
    return full, means


def encoded(value):
    return json.dumps(value).encode()


def records(sidecar):
    return sidecar["record_groups"]["totals"]["records"]


class TestExportUncertainty(unittest.TestCase):
    def test_measured_precision_provenance_pairing_and_binary_experiment(self):
        for table in ("crib", "play"):
            full, means = fixture(table)
            full_bytes, means_bytes = encoded(full), encoded(means)
            sidecar = exporter.build_sidecar(table, full_bytes, means_bytes)
            roundtrip = exporter.decode_sidecar(
                exporter.encode_json(sidecar), means_bytes
            )
            self.assertEqual(roundtrip, sidecar)
            self.assertEqual(
                sidecar["source_full_sha256"], hashlib.sha256(full_bytes).hexdigest()
            )
            self.assertEqual(
                sidecar["means_sha256"], hashlib.sha256(means_bytes).hexdigest()
            )
            self.assertIs(sidecar["provenance"]["joint_policy_converged"], False)
            self.assertEqual(
                sidecar["provenance"]["policy_fingerprint"], "fixed-policy"
            )
            self.assertNotIn("generation_accumulators", sidecar["provenance"])
            self.assertNotIn("training_history", sidecar["provenance"])
            self.assertIsNone(sidecar["cross_bucket_covariance"])
            self.assertIsNone(sidecar["policy_uncertainty"])
            self.assertIsNone(sidecar["calibrated_comparison_uncertainty"])
            if table == "crib":
                record = records(sidecar)["A_A_Unsuited/Dealer/A/total"]
                self.assertEqual(
                    record,
                    {
                        "reported_marginal_se": 0.023563883578079117,
                        "n": 11461.568181821294,
                        "sum_w2": 6360.283574380505,
                    },
                )
                self.assertFalse(
                    any(
                        "A_A_Unsuited" in key and not key.endswith("/total")
                        for key in records(sidecar)
                    )
                )
            else:
                self.assertEqual(
                    records(sidecar)["A_2_3_4/Dealer/delta"],
                    {"reported_marginal_se": 0.0252782869455673, "n": 13000},
                )
            self.assertFalse(
                any("fifteens" in key or "players" in key for key in records(sidecar))
            )
            binary = packed_candidate(sidecar)
            self.assertEqual(binary[:4], b"EPU1")
            length = struct.unpack("<I", binary[4:8])[0]
            header = json.loads(binary[8 : 8 + length])
            self.assertEqual(header["record_count"], len(records(sidecar)))
            self.assertEqual(
                len(binary),
                8
                + length
                + header["mask_bytes"]
                + len(records(sidecar)) * len(header["columns"]) * 8,
            )

    def test_keys_are_rank_ordered_not_lexicographic(self):
        """`keys` must match the published client table's own order.

        Pin the expected order against the production canonical-order
        helpers (`get_canonical_pairs` for crib, `get_canonical_hands` /
        `canonical_hand_key` for play) rather than a hard-coded key list, so
        a hard-coded expectation could not pass by drifting in lockstep with
        a bug in the exporter's own ordering. Insert the fixture keys in
        neither lexicographic nor rank order, so a regression to
        `sorted()` (or an accidental no-op) is distinguishable from a
        correct rank-order result.
        """
        bucket = {"mu": 1.0, "se": 0.1, "n": 100, "sum_w2": 100}
        crib_present = ["J_J_Unsuited", "A_J_Unsuited", "A_2_Suited", "A_A_Unsuited"]
        full = {
            key: {
                role: {rank: dict(bucket) for rank in exporter.RANKS}
                for role in exporter.ROLES
            }
            for key in crib_present
        }
        means = {
            key: {
                role: {rank: {"mu": bucket["mu"]} for rank in exporter.RANKS}
                for role in exporter.ROLES
            }
            for key in crib_present
        }
        full["__metadata__"] = {"seed": 1}
        expected_crib = [key for key in get_canonical_pairs() if key in crib_present]
        self.assertNotEqual(sorted(crib_present), expected_crib)
        sidecar = exporter.build_sidecar("crib", encoded(full), encoded(means))
        self.assertEqual(sidecar["keys"], expected_crib)

        play_bucket = {"mu": 1.0, "se": 0.1, "n": 100}
        play_present = [
            canonical_hand_key(hand)
            for hand in [(3, 2, 1, 0), (12, 0, 0, 0), (0, 0, 0, 0)]
        ]
        full_play = {
            key: {role: dict(play_bucket) for role in exporter.ROLES}
            for key in play_present
        }
        means_play = {
            key: {role: {"mu": play_bucket["mu"]} for role in exporter.ROLES}
            for key in play_present
        }
        full_play["__metadata__"] = {
            "seed": 1,
            "policy_fingerprint": "fixed",
            "joint_policy_converged": False,
        }
        all_play_keys = [canonical_hand_key(hand) for hand in get_canonical_hands()]
        expected_play = [key for key in all_play_keys if key in play_present]
        self.assertNotEqual(sorted(play_present), expected_play)
        sidecar_play = exporter.build_sidecar(
            "play", encoded(full_play), encoded(means_play)
        )
        self.assertEqual(sidecar_play["keys"], expected_play)

    def test_absence_zero_defaults_and_extension_groups(self):
        full, means = fixture("crib")
        root = full["A_2_Suited"]["Dealer"]
        root["A"]["n"] = 0
        root["2"]["n"] = 1
        del root["3"]["se"]
        del root["4"]["n"]
        root["5"]["se"] = 0
        del root["5"]["sum_w2"]
        root["6"]["sum_w2"] = root["6"]["n"] ** 2
        root["7"]["sum_w2"] = 0
        del root["8"]["starter_suit_relation"]["matching_discard_suit"]["se"]
        sidecar = exporter.build_sidecar("crib", encoded(full), encoded(means))
        for rank in "A23467":
            self.assertNotIn(f"A_2_Suited/Dealer/{rank}/total", records(sidecar))
        zero = records(sidecar)["A_2_Suited/Dealer/5/total"]
        self.assertEqual(zero["reported_marginal_se"], 0)
        self.assertEqual(zero["n"], zero["sum_w2"])
        self.assertNotIn("A_2_Suited/Dealer/8/matching_discard_suit", records(sidecar))
        self.assertIsNotNone(records(sidecar).get("A_2_Suited/Dealer/8/total"))
        original = copy.deepcopy(records(sidecar))
        sidecar["record_groups"]["categories"] = {"future": [1, 2, 3]}
        sidecar["future_header"] = {"version": 2}
        for record in records(sidecar).values():
            record["future_field"] = "ignored"
        loaded = exporter.decode_sidecar(encoded(sidecar), encoded(means))
        self.assertEqual(set(records(loaded)), set(original))
        for key, record in original.items():
            self.assertEqual(
                {field: records(loaded)[key][field] for field in record}, record
            )

    def test_qualifications_wording_may_change_but_keys_may_not(self):
        """Wording is prose, not wire format; only the keys are the contract.

        Regression for a finding against whole-dict equality on
        `qualifications`: clarifying a qualification's text must not reject
        a previously published sidecar, and publishing reworded text must
        not be rejected by an unchanged reader.
        """
        full, means = fixture("play")
        good = exporter.build_sidecar("play", encoded(full), encoded(means))
        reworded = copy.deepcopy(good)
        reworded["qualifications"] = {
            key: f"{value} (reworded for clarity)"
            for key, value in reworded["qualifications"].items()
        }
        self.assertNotEqual(reworded["qualifications"], good["qualifications"])
        decoded = exporter.decode_sidecar(encoded(reworded), encoded(means))
        self.assertEqual(decoded["qualifications"], reworded["qualifications"])

    def test_bad_json_and_numbers(self):
        for value in (
            b"[]",
            b'{"a":1,"a":2}',
            b'{"x":{"a":1,"a":2}}',
            b'{"x":NaN}',
            b"{} trailing",
            b'{"x":Infinity}',
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                exporter.read_json(value)
        for value in (True, "1", float("inf"), -1):
            full, means = fixture("play")
            full["A_2_3_4"]["Dealer"]["se"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                exporter.build_sidecar("play", encoded(full), encoded(means))
        full, means = fixture("play")
        full["A_2_3_4"]["Dealer"]["n"] = 2.5
        with self.assertRaisesRegex(ValueError, "integral"):
            exporter.build_sidecar("play", encoded(full), encoded(means))

    def test_source_and_means_mismatch(self):
        full, means = fixture("play")
        for change in (
            lambda data: data.pop("A_2_3_4"),
            lambda data: data["A_2_3_4"]["Dealer"].update(mu=100),
            lambda data: data["A_2_3_4"]["Dealer"].pop("mu"),
            lambda data: data["A_2_3_4"]["Dealer"]["players"]["Pone"].update(mu=0),
        ):
            source = copy.deepcopy(full)
            change(source)
            with self.assertRaises(ValueError):
                exporter.build_sidecar("play", encoded(source), encoded(means))
        means["__metadata__"] = {"ignored_by_mean_comparison": 1}
        exporter.build_sidecar("play", encoded(full), encoded(means))

    def test_invalid_lookup_structure(self):
        full, means = fixture("crib")
        for change in (
            lambda data: data.update(bad={}),
            lambda data: data["A_A_Unsuited"].pop("Dealer"),
            lambda data: data["A_A_Unsuited"]["Dealer"].pop("A"),
            lambda data: data["A_A_Unsuited"]["Dealer"]["A"].update(
                starter_suit_relation={"matching_discard_suit": {"mu": 1}}
            ),
            lambda data: data["A_2_Suited"]["Dealer"]["A"][
                "starter_suit_relation"
            ].update(matching_discard_suit={"mu": 1}),
        ):
            mutated = copy.deepcopy(means)
            change(mutated)
            with self.assertRaises(ValueError):
                exporter.build_sidecar("crib", encoded(full), encoded(mutated))
        with self.assertRaisesRegex(ValueError, "Unknown table"):
            exporter.build_sidecar("other", encoded(full), encoded(means))

    def test_invalid_sidecar(self):
        full, means = fixture("play")
        good = exporter.build_sidecar("play", encoded(full), encoded(means))
        changes = [
            lambda data: data.update(schema="v2"),
            lambda data: data.update(table="other"),
            lambda data: data.update(means_sha256="0" * 64),
            lambda data: data.pop("policy_uncertainty"),
            lambda data: data.pop("qualifications"),
            lambda data: data.update(qualifications={}),
            lambda data: data["qualifications"].pop("scope"),
            lambda data: data.update(
                qualifications={**good["qualifications"], "extra": "x"}
            ),
            lambda data: data["qualifications"].update(scope=""),
            lambda data: data["qualifications"].update(scope=123),
            lambda data: data.update(qualifications="not a dict"),
            lambda data: data.update(keys=["A_2_3_4", "A_2_3_4"]),
            lambda data: data.update(source_full_sha256=None),
            lambda data: data.update(source_full_sha256="bad"),
            lambda data: data.update(source_full_sha256="z" * 64),
            lambda data: data.update(provenance={"invalid": []}),
            lambda data: data.update(provenance={"invalid": 1e309}),
            lambda data: data["provenance"].pop("policy_fingerprint"),
            lambda data: data["provenance"].update(policy_fingerprint=""),
            lambda data: data["provenance"].pop("joint_policy_converged"),
            lambda data: data["provenance"].update(joint_policy_converged=0),
            lambda data: data["record_groups"]["totals"].update(record_count=0),
            lambda data: data["record_groups"]["totals"].update(record_count=True),
            lambda data: data["record_groups"]["totals"].update(record_count="2"),
            lambda data: records(data).update(
                bad=records(data).pop("A_2_3_4/Dealer/delta")
            ),
            lambda data: records(data)["A_2_3_4/Dealer/delta"].pop("n"),
            lambda data: records(data)["A_2_3_4/Dealer/delta"].update(n=0),
            lambda data: records(data)["A_2_3_4/Dealer/delta"].update(
                reported_marginal_se=-1, se=0.1
            ),
            lambda data: records(data)["A_2_3_4/Dealer/delta"].update(
                reported_marginal_se="invalid", se=0.1
            ),
        ]
        for change in changes:
            mutated = copy.deepcopy(good)
            change(mutated)
            with self.assertRaises(ValueError):
                exporter.decode_sidecar(encoded(mutated), encoded(means))
        for field in ("policy_fingerprint", "joint_policy_converged"):
            incomplete, incomplete_means = fixture("play")
            incomplete["__metadata__"].pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                exporter.build_sidecar(
                    "play", encoded(incomplete), encoded(incomplete_means)
                )
        # Numeric overflow uses standard JSON syntax but must also be rejected.
        with self.assertRaises(ValueError):
            exporter.decode_sidecar(
                encoded(good).replace(b'"seed": 42', b'"seed": 1e999'), encoded(means)
            )

    def test_export_cli_preserves_both_client_files_and_import_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            before = {}
            for table in ("crib", "play"):
                full, means = fixture(table)
                full_path, means_path = (
                    base / f"{table}.full.json",
                    base / f"{table}.client.json",
                )
                full_path.write_bytes(encoded(full))
                # Deliberate unusual whitespace verifies preservation of exact bytes.
                means_path.write_bytes(b" \n" + encoded(means) + b"\n ")
                before[means_path] = means_path.read_bytes()
                output = base / f"{table}.uncertainty.json"
                arguments = [
                    "export_uncertainty",
                    "--table",
                    table,
                    "--full",
                    str(full_path),
                    "--means",
                    str(means_path),
                    "--output",
                    str(output),
                ]
                with patch.object(sys, "argv", arguments), patch.dict(
                    sys.modules,
                    {
                        "artifact_pipeline.export_uncertainty": None,
                        "artifact_pipeline.generate_table": None,
                        "artifact_pipeline.generate_play_table": None,
                        "artifact_pipeline.pegging": None,
                        "simulate_cribbage_games": None,
                    },
                ):
                    runpy.run_path(str(Path(exporter.__file__)), run_name="__main__")
                exporter.decode_sidecar(output.read_bytes(), means_path.read_bytes())
                self.assertEqual(full_path.read_bytes(), encoded(full))
                for input_path in (full_path, means_path):
                    with self.assertRaisesRegex(ValueError, "overwrite"):
                        exporter.export_files(table, full_path, means_path, input_path)
                link = base / f"{table}.link"
                os.link(means_path, link)
                with self.assertRaisesRegex(ValueError, "overwrite"):
                    exporter.export_files(table, full_path, means_path, link)
            for path, original_bytes in before.items():
                self.assertEqual(path.read_bytes(), original_bytes)


if __name__ == "__main__":
    unittest.main()
