"""Wire regressions against the retained seed-42 golden document."""

import gzip
import hashlib
import json
import unittest
from pathlib import Path

from artifact_pipeline.export_uncertainty import (
    build_sidecar,
    decode_sidecar,
    encode_json,
)

FIXTURES = Path(__file__).parent / "fixtures" / "crib-uncertainty-v2"


class TestCribUncertaintyV2(unittest.TestCase):
    def setUp(self):
        self.means = (FIXTURES / "means.json").read_bytes()
        self.sidecar = json.loads((FIXTURES / "sidecar.json").read_bytes())
        self.totals = self.sidecar["record_groups"]["totals"]
        self.records = self.totals["records"]

    def decode(self):
        return decode_sidecar(encode_json(self.sidecar), self.means)

    def test_export_projects_all_golden_records_from_saved_moments(self):
        full = gzip.decompress((FIXTURES / "full.json.gz").read_bytes())
        exported = build_sidecar("crib", full, self.means)
        self.assertEqual(exported, self.sidecar)
        self.assertEqual(
            list(exported["record_groups"]["totals"]["records"]), list(self.records)
        )

    def test_export_checks_measured_se_against_projection(self):
        full = json.loads(gzip.decompress((FIXTURES / "full.json.gz").read_bytes()))
        full["3_8_Suited"]["Dealer"]["A"]["se"] += 0.001
        with self.assertRaisesRegex(ValueError, "projection differs.*Dealer/A"):
            build_sidecar("crib", encode_json(full), self.means)

    def test_export_rejects_inconsistent_completed_state(self):
        raw = gzip.decompress((FIXTURES / "full.json.gz").read_bytes())
        for path, replacement, error in (
            (("phase",), "sampling", "completed"),
            (("requested_pairs",), ["3_8_Suited"], "complete twins"),
            (("generation_accumulators",), ..., "policy payload"),
            (("policy_sha256",), "a" * 64, "policy digest"),
            (("run_control", "target_samples"), 1, "measured target"),
            (("run_control", "target_samples"), 5, "did not reach"),
            (("estimator_state", "3_8", "Dealer"), ..., "measured roles"),
            (("estimator_state", "3_8"), 5, "Malformed v2 measured state"),
            (("requested_pairs",), "3_8_Suited", "complete twins"),
            (("requested_pairs",), [5], "complete twins"),
            (
                ("estimator_state", "3_8", "Dealer", "streams", "residual"),
                ...,
                "active streams",
            ),
            (
                ("estimator_state", "3_8", "Dealer", "streams"),
                ["base", "residual", "suit"],
                "active streams",
            ),
            (("precut_twin_report",), {"rows": [{"status": "invalid"}]}, "row status"),
            (("precut_twin_report",), None, "Malformed v2 pre-cut report"),
        ):
            with self.subTest(path=path, replacement=replacement):
                full = json.loads(raw)
                parent = full["__metadata__"]
                for key in path[:-1]:
                    parent = parent[key]
                if replacement is ...:
                    del parent[path[-1]]
                else:
                    parent[path[-1]] = replacement
                with self.assertRaisesRegex(ValueError, error):
                    build_sidecar("crib", encode_json(full), self.means)

    def test_export_includes_pre_cut_counts(self):
        full = json.loads(gzip.decompress((FIXTURES / "full.json.gz").read_bytes()))
        full["__metadata__"]["convergence_shift"] = 0.09525
        full["__metadata__"]["precut_twin_report"] = {
            "rows": [{"status": "resolved-positive"}, {"status": "unresolved"}]
        }
        provenance = build_sidecar("crib", encode_json(full), self.means)["provenance"]
        self.assertEqual(provenance["convergence_shift"], 0.09525)
        self.assertEqual(provenance["precut_resolved_positive"], 1)
        self.assertEqual(provenance["precut_resolved_negative"], 0)
        self.assertEqual(provenance["precut_unresolved"], 1)

    def test_export_ignores_undocumented_source_provenance(self):
        full = json.loads(gzip.decompress((FIXTURES / "full.json.gz").read_bytes()))
        full["__metadata__"].update(
            precut_resolved_positive=156,
            precut_resolved_negative=0,
            precut_unresolved=0,
            undocumented_policy_snapshot=None,
        )
        provenance = build_sidecar("crib", encode_json(full), self.means)["provenance"]
        self.assertEqual(provenance, self.sidecar["provenance"])

    def test_export_requires_all_retained_client_relations(self):
        raw = gzip.decompress((FIXTURES / "full.json.gz").read_bytes())
        client = json.loads(self.means)
        del client["3_8_Suited"]["Dealer"]["A"]["starter_suit_relation"][
            "matching_discard_suit"
        ]
        with self.assertRaisesRegex(ValueError, "Incomplete v2 client relations"):
            build_sidecar("crib", raw, encode_json(client))

    def test_reader_checks_client_metadata_even_if_hash_matches(self):
        for value in (
            None,
            {"generation_method": "artifact_pipeline.generate_table.v3"},
        ):
            with self.subTest(value=value):
                means = json.loads((FIXTURES / "means.json").read_bytes())
                means["__metadata__"] = value
                self.means = encode_json(means)
                self.sidecar["means_sha256"] = hashlib.sha256(self.means).hexdigest()
                with self.assertRaisesRegex(ValueError, "client metadata"):
                    self.decode()

    def test_reader_rejects_invalid_v2_provenance(self):
        for key, value in (
            ("estimator_state", None),
            ("policy_snapshot", {"moments": []}),
            ("policy_sha256", "invalid"),
            ("generation", -1),
            ("seed", True),
            ("convergence_shift", -0.01),
            ("convergence_shift", 10**400),
            ("precut_unresolved", 0),
        ):
            with self.subTest(key=key):
                original = self.sidecar["provenance"].copy()
                self.sidecar["provenance"][key] = value
                with self.assertRaises(ValueError):
                    self.decode()
                self.sidecar["provenance"] = original

    def test_golden_matches_exact_client_bytes(self):
        self.assertEqual(self.decode(), self.sidecar)
        self.means += b"\n"
        with self.assertRaisesRegex(ValueError, "means_sha256"):
            self.decode()

    def test_missing_relation_and_measured_zero_are_distinct(self):
        relation = "3_8_Suited/Dealer/A/matching_discard_suit"
        root = "3_8_Suited/Dealer/A/total"
        del self.records[relation]
        self.totals["record_count"] -= 1
        self.records[root]["reported_marginal_se"] = 0
        records = self.decode()["record_groups"]["totals"]["records"]
        self.assertNotIn(relation, records)
        self.assertEqual(records[root]["reported_marginal_se"], 0)

    def test_v2_rejects_incompatible_headers_and_record_fields(self):
        record = self.records["3_8_Suited/Dealer/A/total"]
        for parent, key, wrong in (
            (self.sidecar, "schema", "expected-points-uncertainty.v1"),
            (self.sidecar, "n_semantics", "sum_weights"),
            (self.sidecar, "cross_bucket_covariance", "comparison_covariance"),
            (record, "n", 4.0),
            (record, "mu", 99),
            (record, "mu", 10**400),
            (record, "reported_marginal_se", -1),
        ):
            with self.subTest(key=key, wrong=wrong):
                original = parent[key]
                parent[key] = wrong
                with self.assertRaises(ValueError):
                    self.decode()
                parent[key] = original
        del self.sidecar["selection_adjustment"]
        with self.assertRaisesRegex(ValueError, "selection_adjustment"):
            self.decode()

    def repin_seed(self, seed):
        means = json.loads((FIXTURES / "means.json").read_bytes())
        means["__metadata__"]["seed"] = seed
        self.means = encode_json(means)
        self.sidecar["means_sha256"] = hashlib.sha256(self.means).hexdigest()
        self.sidecar["provenance"]["seed"] = seed

    def test_reader_accepts_only_javascript_safe_integers(self):
        limit = 2**53 - 1
        for seed in (limit, -limit):
            with self.subTest(seed=seed):
                self.repin_seed(seed)
                self.assertEqual(self.decode()["provenance"]["seed"], seed)
        for seed in (limit + 1, -limit - 1, 9007199254740993):
            with self.subTest(seed=seed):
                self.repin_seed(seed)
                with self.assertRaisesRegex(ValueError, "Invalid v2 seed"):
                    self.decode()

    def test_reader_rejects_unsafe_counts_from_a_valid_baseline(self):
        limit = 2**53 - 1
        record = self.records["3_8_Suited/Dealer/A/total"]
        for parent, key, error in (
            (record, "n", "Invalid v2 measured record"),
            (self.sidecar["provenance"], "generation", "Invalid v2 generation"),
        ):
            with self.subTest(key=key):
                self.assertEqual(self.decode(), self.sidecar)
                original = parent[key]
                parent[key] = limit + 1
                with self.assertRaisesRegex(ValueError, error):
                    self.decode()
                parent[key] = original

    def test_export_refuses_integers_outside_the_safe_range(self):
        raw = json.loads(gzip.decompress((FIXTURES / "full.json.gz").read_bytes()))
        for field, value in (("seed", 2**53), ("generation", 2**53)):
            with self.subTest(field=field):
                full = json.loads(json.dumps(raw))
                full["__metadata__"][field] = value
                means = json.loads(self.means)
                means["__metadata__"][field] = value
                with self.assertRaises(ValueError):
                    build_sidecar("crib", encode_json(full), encode_json(means))
