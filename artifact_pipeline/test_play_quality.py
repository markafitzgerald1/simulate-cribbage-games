"""Hand-calculated policy diagnostics, independent of generation/training."""

import json
import unittest

from artifact_pipeline.play_lines import QUALIFICATIONS, SCHEMA
from artifact_pipeline.play_quality import measure_quality


class TestPlayQuality(unittest.TestCase):
    def measure(self, rows, **kwargs):
        document = {
            "schema": SCHEMA,
            "means_sha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
            "ranks": "A23456789TJQK",
            "roles": ["Pone", "Dealer"],
            "columns": [
                ["lead", "n", "mu", "se"],
                ["lead", "n", "mu", "se", "response", "response_n"],
            ],
            "precision": {"mu_decimals": 3, "se_significant_figures": 2},
            "provenance": {
                "generation_method": "test",
                "seed": 42,
                "policy_fingerprint": "test",
                "joint_policy_converged": False,
            },
            "qualifications": QUALIFICATIONS,
            "keys": ["A_2_3_4", "2_3_4_5", "3_4_5_6"][: len(rows)],
            "entries": [[pone, [[12, 200, 99, 0, 3, 200]]] for pone in rows],
        }
        return measure_quality(json.dumps(document).encode(), b"{}", **kwargs)

    def test_key_statistics_keep_own_eligible_support_and_existing_gauge(self):
        rows = [
            [[0, 300, 0, 0.1], [1, 100, 1, 0.2]],
            [[1, 99, 10, 0], [2, 100, 0, 0.2]],
        ]
        original = self.measure(rows)
        detailed = self.measure(rows, include_key_statistics=True)
        self.assertEqual(
            detailed.pop("key_statistics"), {"A_2_3_4": {"flagged": True, "gain": 0.75}}
        )
        self.assertEqual(detailed, original)

    def test_count_weighted_gain_and_equal_key_population_spread(self):
        # Gains are 1 - (300*0 + 100*1)/400 = .75 and 3 - 2 = 1.
        result = self.measure(
            [[[0, 300, 0, 0.1], [1, 100, 1, 0.2]], [[1, 100, 1, 1], [2, 100, 3, 1]]]
        )
        self.assertEqual(result["keys_total"], 2)
        self.assertEqual(result["keys_eligible"], 2)
        self.assertEqual(result["keys_flagged"], 1)
        self.assertEqual(result["flagged_share"], 0.5)
        self.assertEqual(result["gain_mean"], 0.875)
        self.assertEqual(result["gain_population_sd"], 0.125)
        self.assertEqual(result["gain_max"], 1)
        self.assertEqual(result["eligible_samples"], 600)
        self.assertEqual(result["observed_samples"], 600)
        self.assertEqual(result["minimum_lead_count"], 100)
        self.assertEqual(result["z_threshold"], 3)

    def test_minimum_count_filters_thin_and_rare_leads_without_zero_filling(self):
        result = self.measure(
            [
                [[0, 200, 0, 0], [1, 99, 100, 0], [2, 1, None, None]],
                [[1, 200, 0, 0], [2, 100, 3, 0], [3, 99, 99, 0]],
                [],
            ]
        )
        self.assertEqual(result["keys_total"], 3)
        self.assertEqual(result["keys_eligible"], 1)
        self.assertEqual(result["flagged_share"], 1)
        self.assertEqual(result["gain_mean"], 2)
        self.assertEqual(result["eligible_samples"], 300)
        self.assertEqual(result["observed_samples"], 699)

    def test_mode_is_count_first_with_rank_ties_and_positive_gap(self):
        for rows, expected in (
            ([[0, 100, 1, 0], [1, 200, 0, 0]], 1),
            ([[0, 100, 0, 0], [1, 100, 1, 0]], 1),
            ([[0, 100, 1, 0], [1, 100, 0, 0]], 0),
            ([[0, 100, 1, 0], [1, 100, 1, 0]], 0),
        ):
            with self.subTest(rows=rows):
                result = self.measure([rows])
                self.assertEqual(result["keys_flagged"], expected)
                self.assertEqual(result["gain_population_sd"], 0)

    def test_z_boundary_uses_both_errors_and_checks_every_alternative(self):
        for gap, expected in ((1.499, 0), (1.5, 1), (1.501, 1)):
            # sqrt(.3**2 + .4**2) = .5, so z=3 at gap=1.5.
            with self.subTest(gap=gap):
                result = self.measure([[[0, 200, 0, 0.3], [1, 100, gap, 0.4]]])
                self.assertEqual(result["keys_flagged"], expected)
        # The largest mean is too noisy, but a different alternative clears z=3.
        result = self.measure([[[0, 200, 0, 0.3], [1, 100, 1.5, 0.4], [2, 100, 2, 10]]])
        self.assertEqual(result["keys_flagged"], 1)
        self.assertEqual(result["gain_mean"], 1.125)

    def test_unavailable_is_null_and_single_lead_is_not_comparable(self):
        for rows in ([], [[]], [[[0, 200, 0, 0]]]):
            with self.subTest(rows=rows):
                result = self.measure(rows)
                self.assertEqual(result["keys_eligible"], 0)
                for field in (
                    "flagged_share",
                    "gain_mean",
                    "gain_population_sd",
                    "gain_max",
                ):
                    self.assertIsNone(result[field])
        result = self.measure([[[0, 100, 0, 0], [1, 100, 0, 0]]])
        self.assertEqual(result["gain_mean"], 0)

    def test_thresholds_are_explicit_and_validated(self):
        result = self.measure(
            [[[0, 3, 0, 0.3], [1, 2, 1, 0.4]]],
            minimum_lead_count=2,
            z_threshold=2,
        )
        self.assertEqual(result["keys_flagged"], 1)
        for count in (1, True, 2.5):
            with self.subTest(count=count), self.assertRaises(ValueError):
                self.measure([], minimum_lead_count=count)
        for threshold in (0, -1, True, float("inf"), float("nan")):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                self.measure([], z_threshold=threshold)

    def test_rejects_unpaired_or_malformed_artifact(self):
        with self.assertRaises(ValueError):
            measure_quality(b"{}", b"wrong")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
