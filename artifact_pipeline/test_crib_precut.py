"""Hand-derived pre-cut contrasts and simultaneous sign decisions."""

import copy
import math
import unittest

from artifact_pipeline import crib_precut
from artifact_pipeline.crib_v4_state import SCALE, add_row, empty_moments


def fixture_state():
    """Two rows: residual 3/50, 4/50; suit 3/50, 8/50.

    The suit coordinates have negative covariance: [1, 0], [0, 2]. The combined
    gap is 9/50 with SE sqrt(26)/100; independent cuts give sqrt(90)/100.
    """
    streams = {
        "base": empty_moments(["3/base/fifteens"]),
        "residual": empty_moments(["3/residual/fifteens", "A/residual/pairs"]),
        "suit": empty_moments(
            [
                "3/Suited/root/flushes",
                "A/Suited/root/nobs",
                "A/Unsuited/root/nobs",
            ]
        ),
    }
    for name, rows in {
        "base": [[999], [1000]],
        "residual": [[1, 0], [0, 1]],
        "suit": [[1, 0, 0], [0, 2, 0]],
    }.items():
        for row in rows:
            add_row(streams[name], [value * SCALE for value in row])
    return {
        "estimator_state": {
            "3_8": {
                role: {"streams": copy.deepcopy(streams)} for role in ("Dealer", "Pone")
            }
        }
    }


class TestPrecutReport(unittest.TestCase):
    def test_hand_derived_covariance_and_components(self):
        row = crib_precut.precut_twin_report(fixture_state())["rows"][0]
        self.assertEqual(row["rank_group"], "3_8")
        self.assertFalse(row["has_jack"])
        self.assertEqual(row["gap"]["n"], 2)
        self.assertAlmostEqual(row["gap"]["mu"], 9 / 50)
        self.assertAlmostEqual(row["gap"]["se"], math.sqrt(26) / 100)
        self.assertAlmostEqual(row["residual"]["mu"], 7 / 100)
        self.assertAlmostEqual(row["flush"]["mu"], 3 / 100)
        self.assertAlmostEqual(row["nobs"]["mu"], 8 / 100)
        self.assertAlmostEqual(
            row["pointwise"]["lower"], 0.18 - 1.959963984540054 * math.sqrt(26) / 100
        )
        self.assertAlmostEqual(
            row["simultaneous"]["lower"], 0.18 - 3.598 * math.sqrt(26) / 100, places=4
        )
        self.assertEqual(row["status"], "unresolved")

    def test_residual_only_and_displayed_means_ignored(self):
        state = fixture_state()
        for entry in state["estimator_state"]["3_8"].values():
            for key in ("sum_x", "sum_xx_upper"):
                entry["streams"]["suit"][key] = [0, 0, 0] if key == "sum_x" else {}
        for variant, value in (("Suited", -999), ("Unsuited", 999)):
            state[f"3_8_{variant}"] = {
                role: {rank: {"mu": value} for rank in crib_precut.RANKS}
                for role in ("Dealer", "Pone")
            }
        row = crib_precut.precut_twin_report(state)["rows"][0]
        self.assertAlmostEqual(row["gap"]["mu"], 0.07)
        self.assertAlmostEqual(row["gap"]["se"], 0.01)
        self.assertEqual(row["status"], "resolved-positive")

    def test_one_observation_has_no_bounds(self):
        state = fixture_state()
        for entry in state["estimator_state"]["3_8"].values():
            for name, stream in list(entry["streams"].items()):
                one = empty_moments(stream["labels"])
                add_row(one, [0] * len(one["labels"]))
                entry["streams"][name] = one
        row = crib_precut.precut_twin_report(state)["rows"][0]
        self.assertEqual(row["gap"], {"n": 1, "mu": 0.0, "se": None})
        self.assertIsNone(row["pointwise"])
        self.assertIsNone(row["simultaneous"])

    def test_negative_unresolved_missing_and_jack(self):
        state = fixture_state()
        for roles in state["estimator_state"].values():
            for entry in roles.values():
                for stream in entry["streams"].values():
                    stream["sum_x"] = [-value for value in stream["sum_x"]]
        report = crib_precut.precut_twin_report(state)
        crib_precut.enforce_precut_report(report)  # unresolved is not failure
        for roles in state["estimator_state"].values():
            for entry in roles.values():
                for stream in entry["streams"].values():
                    stream["sum_xx_upper"] = {
                        (i, j): left * right // 2
                        for i, left in enumerate(stream["sum_x"])
                        for j, right in enumerate(stream["sum_x"])
                        if i <= j and left * right
                    }
        with self.assertRaisesRegex(ValueError, "3_8.*Dealer"):
            crib_precut.enforce_precut_report(crib_precut.precut_twin_report(state))
        state = fixture_state()
        state["estimator_state"]["3_J"] = state["estimator_state"].pop("3_8")
        state["estimator_state"]["A_A"] = {}
        self.assertTrue(crib_precut.precut_twin_report(state)["rows"][0]["has_jack"])
        for entry in state["estimator_state"]["3_J"].values():
            for stream in entry["streams"].values():
                stream["count"] = 0
        row = crib_precut.precut_twin_report(state)["rows"][0]
        self.assertIsNone(row["gap"])
        self.assertEqual(row["status"], "unresolved")
        self.assertIsNone(row["simultaneous"])
