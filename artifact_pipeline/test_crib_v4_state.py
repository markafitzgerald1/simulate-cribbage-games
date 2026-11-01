"""Exact integer-moment and covariance tests for the opt-in crib estimator."""

import copy
import unittest
from fractions import Fraction

from artifact_pipeline.crib_v4_state import (
    SCALE,
    active_streams,
    add_row,
    coordinate_labels,
    decode_moments,
    empty_moments,
    encode_moments,
    integer_row,
    observation_coordinates,
    projected_statistics,
    _exact_psd,
)
from artifact_pipeline.test_crib_decomposition import same_rank_group, twin_group


class TestV4State(unittest.TestCase):
    """Treat serialized joint vectors as the only measurement authority."""

    def test_coordinate_order_and_exact_scaling(self):
        group = twin_group()
        names = ("A", "2", "3", "4", "J")
        self.assertEqual(active_streams(group), ("base", "residual", "suit"))
        self.assertEqual(active_streams(same_rank_group()), ("base", "suit"))
        self.assertEqual(
            coordinate_labels(group, names, "base")[:3],
            ["A/base/fifteens", "A/base/pairs", "A/base/runs"],
        )
        self.assertEqual(
            coordinate_labels(group, names, "residual")[:3],
            ["A/residual/fifteens", "A/residual/pairs", "A/residual/runs"],
        )
        suit_labels = coordinate_labels(group, names, "suit")
        self.assertEqual(
            suit_labels[:2], ["2/Unsuited/root/flushes", "2/Unsuited/root/nobs"]
        )
        self.assertNotIn("A/Suited/matching_discard_suit/flushes", suit_labels)
        self.assertTrue("3/Suited/root/flushes" in suit_labels)
        self.assertEqual(len(suit_labels), len(set(suit_labels)))
        with self.assertRaises(ValueError):
            coordinate_labels(same_rank_group(), names, "residual")
        cases = (
            ("base", {("B", 0, "fifteens"): Fraction(2, 3)}, "A/base/fifteens"),
            ("residual", {("D", 0, "pairs"): Fraction(-1, 3)}, "A/residual/pairs"),
            (
                "suit",
                {
                    ("C", "Suited", 2, "non_matching_discard_suit", "runs"): Fraction(
                        1, 3
                    )
                },
                "3/Suited/non_matching_discard_suit/correction_runs",
            ),
            (
                "suit",
                {("nobs", "Unsuited", 4, "root"): Fraction(1, 3)},
                "J/Unsuited/root/nobs",
            ),
        )
        for stream, observation, label in cases:
            self.assertEqual(
                observation_coordinates(observation, names, stream),
                {label: next(iter(observation.values()))},
            )
        self.assertEqual(integer_row(["x"], {"x": Fraction(1, SCALE)}), [1])
        for coordinates in ({"y": 1}, {"x": Fraction(1, 5)}):
            with self.assertRaises(ValueError):
                integer_row(["x"], coordinates)

    def test_joint_covariance_retains_negative_cross_terms(self):
        base = empty_moments(["B_A", "B_2"])
        suit = empty_moments(["C", "F", "J"])
        for baseline, components in (
            ([2 * SCALE, 0], [SCALE, 2 * SCALE, 0]),
            ([0, 2 * SCALE], [-SCALE, 0, 2 * SCALE]),
        ):
            add_row(base, baseline)
            add_row(suit, components)
        self.assertLess(suit["sum_xx_upper"][(0, 2)], 0)
        self.assertEqual(
            projected_statistics({"base": base}, {"base": {"B_A": 1, "B_2": -1}}),
            {"n": 2, "mu": 0.0, "se": 2.0},
        )
        twin = projected_statistics(
            {"base": base, "suit": suit},
            {"base": {}, "suit": {"C": 1, "F": 1, "J": 1}},
        )
        self.assertEqual(twin, {"n": 2, "mu": 2.0, "se": 1.0})
        independent_error = sum(
            projected_statistics({"suit": suit}, {"suit": {name: 1}})["se"] ** 2
            for name in ("C", "F", "J")
        )
        self.assertNotEqual(twin["se"] ** 2, independent_error)
        different = projected_statistics(
            {"base": base, "suit": suit},
            {"base": {"B_A": 1, "B_2": -1}, "suit": {"C": 1}},
        )
        self.assertEqual(different["mu"], 0.0)
        self.assertAlmostEqual(different["se"] ** 2, 5.0)

    def test_zero_one_and_measured_zero(self):
        moments = empty_moments(["x"])
        self.assertIsNone(projected_statistics({"one": moments}, {"one": {"x": 1}}))
        add_row(moments, [2 * SCALE])
        self.assertEqual(
            projected_statistics({"one": moments}, {"one": {"x": 1}}),
            {"n": 1, "mu": 2.0, "se": None},
        )
        add_row(moments, [2 * SCALE])
        self.assertEqual(
            projected_statistics({"one": moments}, {"one": {"x": 1}}),
            {"n": 2, "mu": 2.0, "se": 0.0},
        )
        with self.assertRaises(ValueError):
            projected_statistics({}, {})
        with self.assertRaises(ValueError):
            projected_statistics(
                {"a": moments, "b": empty_moments(["x"])}, {"a": {"x": 1}}
            )
        for invalid in ([], [1.0]):
            with self.assertRaises(ValueError):
                add_row(moments, invalid)

    def test_sparse_integer_round_trip(self):
        moments = empty_moments(["x", "y"])
        add_row(moments, [2, 1])
        add_row(moments, [0, -1])
        payload = encode_moments(moments)
        self.assertEqual(payload["sum_x"], ["2", "0"])
        self.assertEqual(
            payload["sum_xx_upper"], [[0, 0, "4"], [0, 1, "2"], [1, 1, "2"]]
        )
        self.assertEqual(decode_moments(payload, ["x", "y"]), moments)
        zeros = empty_moments(["x", "y"])
        add_row(zeros, [1, 0])
        add_row(zeros, [0, 1])
        self.assertEqual(
            decode_moments(encode_moments(zeros), ["x", "y"])["sum_xx_upper"].get(
                (0, 1), 0
            ),
            0,
        )

    def test_checkpoint_rejects_malformed_moments(self):
        source = empty_moments(["x", "y"])
        add_row(source, [1, 2])
        add_row(source, [3, 0])
        valid = encode_moments(source)
        changes = (
            lambda item: item.pop("labels"),
            lambda item: item.update(count=-1),
            lambda item: item.update(next_index=9),
            lambda item: item.update(scale=1),
            lambda item: item.update(labels=["y", "x"]),
            lambda item: item.update(sum_x=["1"]),
            lambda item: item.update(sum_x=["01", "2"]),
            lambda item: item.update(sum_x=[1, "2"]),
            lambda item: item.update(sum_xx_upper="wrong"),
            lambda item: item.update(sum_xx_upper=[[0, 0, "0"]]),
            lambda item: item.update(sum_xx_upper=[[1, 0, "1"]]),
            lambda item: item.update(sum_xx_upper=[[0, 2, "1"]]),
            lambda item: item.update(sum_xx_upper=[[0, 0, "1"], [0, 0, "2"]]),
            lambda item: item.update(sum_xx_upper=[[0, 0, "1", "extra"]]),
            lambda item: item.update(sum_xx_upper=[["0", 0, "1"]]),
        )
        for mutate in changes:
            payload = copy.deepcopy(valid)
            mutate(payload)
            with self.subTest(payload=payload):
                with self.assertRaises((ValueError, TypeError)):
                    decode_moments(payload, ["x", "y"])
        for count, totals, upper in (
            (0, ["1", "0"], []),
            (1, ["1", "0"], []),
            (2, ["1", "0"], [[0, 0, "2"]]),
            (2, ["2", "0"], [[0, 0, "1"], [0, 1, "1"]]),
            (2, ["0", "0"], [[0, 0, "2"], [0, 1, "3"], [1, 1, "2"]]),
        ):
            payload = copy.deepcopy(valid)
            payload.update(
                count=count, next_index=count, sum_x=totals, sum_xx_upper=upper
            )
            with self.subTest(count=count, totals=totals, upper=upper):
                with self.assertRaises(ValueError):
                    decode_moments(payload, ["x", "y"])

    def test_invalid_in_memory_projection_and_integer_encoding(self):
        moments = empty_moments(["x"])
        moments["sum_x"][0] = 1.0
        with self.assertRaises(ValueError):
            encode_moments(moments)
        self.assertFalse(_exact_psd([[0, 1], [1, 0]]))
        centered = empty_moments(["x", "y"])
        centered.update(
            count=2,
            next_index=2,
            sum_x=[2, 0],
            sum_xx_upper={(0, 0): 2, (0, 1): 1, (1, 1): 2},
        )
        with self.assertRaises(ValueError):
            decode_moments(encode_moments(centered), ["x", "y"])
        broken = empty_moments(["x"])
        broken.update(count=2, next_index=2, sum_x=[0], sum_xx_upper={(0, 0): -1})
        with self.assertRaises(ValueError):
            projected_statistics({"one": broken}, {"one": {"x": 1}})


if __name__ == "__main__":
    unittest.main()
