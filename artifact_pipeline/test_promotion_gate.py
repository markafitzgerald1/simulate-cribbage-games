"""Duplicate-deal promotion estimates and policy-selection regression tests."""

import math
import json
import io
import tempfile
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from artifact_pipeline import generate_play_table as generator
from artifact_pipeline.generate_play_table import _parse_args
from artifact_pipeline.pegging import (
    PONE,
    DEALER,
    LegacyHeuristicPolicy,
    policy_fingerprint,
)
from artifact_pipeline.promotion_gate import evaluate_promotion, promotion_gate


class DeltaResult:  # pylint: disable=too-few-public-methods
    def __init__(self, delta):
        self.value = delta

    def delta(self, role):
        return self.value if role == PONE else -self.value


class TestPromotionGate(unittest.TestCase):
    def test_duplicates_reference_seat_sign_and_covariance(self):
        policies = {PONE: object(), DEALER: object()}
        calls = []
        # Reference, trained Pone, trained Dealer: negatively correlated gains.
        values = iter([5, 7, 5, -3, -3, -5] * 2)

        def play(pone, dealer, selected, rng):
            calls.append((pone, dealer, selected, rng.getstate()))
            return DeltaResult(next(values))

        with patch(
            "artifact_pipeline.promotion_gate.simulate_pegging", side_effect=play
        ):
            report = evaluate_promotion(policies, 4, 42)
        expected_rng = random.Random(42)
        for index in range(4):
            group = calls[index * 3 : index * 3 + 3]
            cards = expected_rng.sample(range(52), 8)
            expected = (
                tuple(card // 4 for card in cards[:4]),
                tuple(card // 4 for card in cards[4:]),
            )
            self.assertTrue(all(call[:2] == expected for call in group))
            self.assertEqual(group[0][3], group[1][3])
            self.assertEqual(group[0][3], group[2][3])
            self.assertIsInstance(group[0][2][PONE], LegacyHeuristicPolicy)
            self.assertIsInstance(group[0][2][DEALER], LegacyHeuristicPolicy)
            self.assertIs(group[1][2][PONE], policies[PONE])
            self.assertIs(group[2][2][DEALER], policies[DEALER])
            self.assertIs(group[1][2][DEALER], group[0][2][DEALER])
            self.assertIs(group[2][2][PONE], group[0][2][PONE])
        self.assertNotEqual(calls[0][3], calls[3][3])
        for role in (PONE, DEALER):
            self.assertEqual(report[role]["n"], 4)
            self.assertEqual(report[role]["mu"], 1)
            self.assertAlmostEqual(report[role]["se"], math.sqrt(1 / 3))
        self.assertEqual(report["both_seats"], {"n": 4, "mu": 1.0, "se": 0.0})
        self.assertTrue(report["passed"])

    def test_modes_positive_three_se_gate_and_measured_provenance(self):
        policies = {role: LegacyHeuristicPolicy() for role in (PONE, DEALER)}
        for mean, se, passed in (
            (0, 0, False),
            (-1, 1, False),
            (2.9, 1, False),
            (3, 1, True),
            (3.1, 1, True),
            (1, 0, True),
        ):
            values = [
                DeltaResult(value)
                for gain in (mean - se, mean + se)
                for value in (0, gain, -gain)
            ]
            with patch(
                "artifact_pipeline.promotion_gate.simulate_pegging", side_effect=values
            ):
                record = evaluate_promotion(policies, 2, 42)
            self.assertEqual(record["passed"], passed)
            for mode in ("report", "enforce"):
                with patch(
                    "artifact_pipeline.promotion_gate.evaluate_promotion",
                    return_value=record,
                ):
                    measured, metadata = promotion_gate(policies, mode, 2, 42, 1)
                fallback = mode == "enforce" and not passed
                self.assertEqual(
                    metadata["measured_policy"],
                    "legacy-heuristic" if fallback else "trained",
                )
                if fallback:
                    self.assertTrue(
                        all(
                            measured[role] is not policies[role]
                            for role in (PONE, DEALER)
                        )
                    )
                else:
                    self.assertIs(measured, policies)
                self.assertTrue("trained_policy_fingerprint" in metadata)
                self.assertTrue("measured_policy_fingerprint" in metadata)
        with patch("artifact_pipeline.promotion_gate.evaluate_promotion") as evaluate:
            measured, metadata = promotion_gate(policies, "off", 2, 42, 1)
        evaluate.assert_not_called()
        self.assertIs(measured, policies)
        self.assertEqual(metadata["mode"], "off")

    def test_validation_and_serial_parallel_exact_estimates(self):
        policies = {role: LegacyHeuristicPolicy() for role in (PONE, DEALER)}
        for count, workers in ((0, 1), (1, 1), (2, 0)):
            with self.assertRaises(ValueError):
                evaluate_promotion(policies, count, 42, workers)
        with self.assertRaises(ValueError):
            promotion_gate(policies, "unknown", 2, 42, 1)
        expected = evaluate_promotion(policies, 35, 42, 1)
        self.assertEqual(expected, evaluate_promotion(policies, 35, 42, 2))
        self.assertEqual(expected["both_seats"]["mu"], 0)
        self.assertFalse(expected["passed"])


class TestPromotionIntegration(unittest.TestCase):
    def test_gate_after_final_training_before_measured_fingerprint(self):
        context = generator.AnalyticalContext(
            [1.0], [1.0], [], {}, [], [], [((0, 0, 0, 0, 1, 1), 0, 0)]
        )
        trained = {role: object() for role in (PONE, DEALER)}
        events = []
        sampled = []

        def train(*_args, **_kwargs):
            events.append("train")
            return trained, []

        def sample(_discard, policies, **kwargs):
            events.append("sample")
            sampled.append((policies, kwargs))
            return {"__metadata__": {}}

        def evaluate(*_args):
            events.append("gate")
            return {"passed": False, "both_seats": {"n": 2, "mu": 0.0, "se": 0.1}}

        for mode in ("report", "enforce"):
            events.clear()
            sampled.clear()
            with tempfile.TemporaryDirectory() as directory:
                argv = [
                    "generate_play_table.py",
                    "--no-resume",
                    "--hand-limit=1",
                    "--outer-iterations=1",
                    "--promotion-gate-deals=2",
                    "--workers=2",
                    f"--promotion-gate={mode}",
                    f"--output={directory}/full.json",
                    f"--client-output={directory}/client.json",
                    f"--lines-output={directory}/lines.json",
                ]
                with patch("sys.argv", argv), patch.object(
                    generator, "solve_initial_discard_policy", return_value=context
                ), patch.object(
                    generator, "train_iterative_best_response", side_effect=train
                ), patch.object(
                    generator, "generate_play_table", side_effect=sample
                ), patch.object(
                    generator, "refine_discard_policy", return_value=(context, 0, 0)
                ), patch(
                    "artifact_pipeline.promotion_gate.evaluate_promotion",
                    side_effect=evaluate,
                ) as gate, patch.object(
                    generator, "_write_lines"
                ), patch(
                    "builtins.print"
                ):
                    generator.main()
                full = json.loads(Path(directory, "full.json").read_bytes())
            self.assertEqual(
                events,
                ["train", "sample", "train", "gate"]
                + ["sample"] * (2 if mode == "enforce" else 1),
            )
            gate.assert_called_once_with(trained, 2, 42, 2)
            measured, kwargs = sampled[-1]
            self.assertIs(sampled[0][0], trained)
            if mode == "report":
                self.assertIs(measured, trained)
            else:
                self.assertTrue(
                    all(isinstance(p, LegacyHeuristicPolicy) for p in measured.values())
                )
            self.assertEqual(
                kwargs["play_policy_fingerprint"],
                ":".join(policy_fingerprint(measured[r]) for r in (PONE, DEALER)),
            )
            self.assertEqual(
                full["__metadata__"]["promotion_gate"]["measured_policy_fingerprint"],
                kwargs["play_policy_fingerprint"],
            )

    def test_enabled_gate_minimum_is_rejected_before_analytical_training(self):
        for mode in ("report", "enforce"):
            with self.subTest(mode=mode), patch(
                "sys.argv",
                [
                    "generate_play_table.py",
                    "--promotion-gate=" + mode,
                    "--promotion-gate-deals=1",
                ],
            ), patch.object(
                generator,
                "solve_initial_discard_policy",
                side_effect=AssertionError("training started"),
            ) as solve, patch(
                "sys.stderr", io.StringIO()
            ) as stderr:
                with self.assertRaises(SystemExit) as error:
                    generator.main()
                self.assertEqual(error.exception.code, 2)
                solve.assert_not_called()
                self.assertTrue("at least 2" in stderr.getvalue())
        for mode, deals in (("off", 1), ("report", 2), ("enforce", 2)):
            with patch(
                "sys.argv",
                [
                    "generate_play_table.py",
                    "--promotion-gate=" + mode,
                    "--promotion-gate-deals=" + str(deals),
                ],
            ):
                self.assertEqual(_parse_args().promotion_gate_deals, deals)


if __name__ == "__main__":
    unittest.main()
