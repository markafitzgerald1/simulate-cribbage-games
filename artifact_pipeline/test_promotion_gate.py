"""Promotion gate statistics, stream independence and unchanged outputs."""

from contextlib import ExitStack
from datetime import datetime
import hashlib
import io
import json
import math
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from artifact_pipeline import generate_play_table as generator
from artifact_pipeline import pegging, promotion_gate
from artifact_pipeline.pegging import DEALER, PONE, LegacyHeuristicPolicy
from artifact_pipeline.promotion_gate import evaluate_promotion
from artifact_pipeline.test_generate_play_table import all_first_four_policy

CONTEXT = generator.AnalyticalContext(
    [1.0], [1.0], [], {}, [], [], [((0, 0, 0, 0, 1, 1), 0, 0)]
)
DISCARDS = all_first_four_policy()


class FixedClock:  # pylint: disable=too-few-public-methods
    @staticmethod
    def now(zone):
        return datetime(2026, 10, 5, tzinfo=zone)


def run_bounded_generation(directory, gate_arguments, *extra_patches, resume=False):
    """Run main() with real training, sampling and writers on two hands."""
    argv = [
        "generate_play_table.py",
        *([] if resume else ["--no-resume"]),
        "--hand-limit=2",
        "--outer-iterations=1",
        "--ibr-iterations=1",
        "--ibr-samples=4",
        "--rollouts-per-action=1",
        "--policy-table-samples=3",
        "--samples=6",
        "--checkpoint-frequency=1",
        "--seed=42",
        f"--output={directory}/full.json",
        f"--client-output={directory}/client.json",
        f"--lines-output={directory}/lines.json",
        *gate_arguments,
    ]
    stderr = io.StringIO()
    with ExitStack() as stack:
        for context in (
            patch("sys.argv", argv),
            patch("sys.stderr", stderr),
            patch("sys.stdout", io.StringIO()),
            patch.object(generator, "datetime", FixedClock),
            patch.object(
                generator, "solve_initial_discard_policy", return_value=CONTEXT
            ),
            patch.object(
                generator, "selected_discards_to_policy", return_value=DISCARDS
            ),
            patch.object(
                generator, "refine_discard_policy", return_value=(CONTEXT, 0, 0.0)
            ),
            *extra_patches,
        ):
            stack.enter_context(context)
        generator.main()
    outputs = {
        name: Path(directory, f"{name}.json").read_bytes()
        for name in ("full", "client", "lines")
    }
    return outputs, stderr.getvalue()


def digests(outputs):
    return {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()}


class ScriptedResult:  # pylint: disable=too-few-public-methods
    def __init__(self, pone_delta):
        self.pone_delta = pone_delta

    def delta(self, role):
        return self.pone_delta if role == PONE else -self.pone_delta


def game_name(policies, trained):
    """Name a gate game by which seats play the trained policies."""
    trained_seats = tuple(
        seat for seat in (PONE, DEALER) if policies[seat] is trained[seat]
    )
    heuristic_seats = tuple(
        seat
        for seat in (PONE, DEALER)
        if isinstance(policies[seat], LegacyHeuristicPolicy)
    )
    return trained_seats, heuristic_seats


def scripted_gate(trained, pone_deltas_by_deal, deals):
    """Evaluate with Pone deltas scripted per deal as (reference, Pone, Dealer)."""
    calls = []

    def play(pone_hand, dealer_hand, policies, rng):
        calls.append((pone_hand, dealer_hand, policies, rng.getstate()))
        reference, trained_pone, trained_dealer = pone_deltas_by_deal[
            (len(calls) - 1) // 3
        ]
        value = {
            ((), (PONE, DEALER)): reference,
            ((PONE,), (DEALER,)): trained_pone,
            ((DEALER,), (PONE,)): trained_dealer,
        }[game_name(policies, trained)]
        return ScriptedResult(value)

    with patch.object(promotion_gate, "simulate_pegging", side_effect=play):
        report = evaluate_promotion(trained, deals, 42)
    return report, calls


class TestEvaluatePromotion(unittest.TestCase):
    trained = {PONE: object(), DEALER: object()}

    def test_each_trained_seat_faces_the_heuristic_on_one_shared_deal(self):
        _, calls = scripted_gate(self.trained, [(0, 0, 0)] * 1000, 1000)
        self.assertEqual(len(calls), 3000)
        for deal in range(1000):
            group = calls[deal * 3 : deal * 3 + 3]
            self.assertEqual(len({call[:2] for call in group}), 1)
            self.assertEqual(len({repr(call[3]) for call in group}), 1)
            self.assertCountEqual(
                [game_name(call[2], self.trained) for call in group],
                [((), (PONE, DEALER)), ((PONE,), (DEALER,)), ((DEALER,), (PONE,))],
            )
        self.assertEqual(len({repr(call[3]) for call in calls}), 1000)

    def test_seat_signs_and_both_seat_error_from_per_deal_averages(self):
        # Pone gains 1 and 3, Dealer gains 3 and 1: every per-deal average is 2.
        report, _ = scripted_gate(self.trained, [(5, 6, 2), (-4, -1, -5)] * 500, 1000)
        pone_se = math.sqrt(1 / 999)
        self.assertEqual(report[PONE]["n"], 1000)
        self.assertEqual(report[PONE]["mu"], 2.0)
        self.assertAlmostEqual(report[PONE]["se"], pone_se)
        self.assertEqual(report[DEALER]["n"], 1000)
        self.assertEqual(report[DEALER]["mu"], 2.0)
        self.assertAlmostEqual(report[DEALER]["se"], pone_se)
        self.assertEqual(report["both_seats"], {"n": 1000, "mu": 2.0, "se": 0.0})
        self.assertTrue(report["passed"])

    def test_passes_only_on_a_positive_mean_at_three_standard_errors(self):
        for mean, error, passed in (
            (0.0, 0.0, False),
            (-1.0, 0.0, False),
            (-1.0, 1.0, False),
            (2.5, 1.0, False),
            (3.0, 1.0, True),
            (3.5, 1.0, True),
            (1.0, 0.0, True),
        ):
            # Each seat gains mean -/+ error, so the per-deal averages do too.
            delta = error * math.sqrt(999)
            scripted = [(0, gain, -gain) for gain in (mean - delta, mean + delta)] * 500
            with self.subTest(mean=mean, error=error):
                report, _ = scripted_gate(self.trained, scripted, 1000)
                self.assertAlmostEqual(report["both_seats"]["mu"], mean)
                self.assertAlmostEqual(report["both_seats"]["se"], error)
                self.assertIs(report["passed"], passed)

    def test_rejects_fewer_than_one_thousand_deals(self):
        for deals in (1, 2, 999):
            with self.subTest(deals=deals):
                with self.assertRaisesRegex(ValueError, "at least 1,000 deals"):
                    evaluate_promotion(self.trained, deals, 42)

    def test_heuristic_against_itself_has_no_advantage(self):
        heuristic = {role: LegacyHeuristicPolicy() for role in (PONE, DEALER)}
        report = evaluate_promotion(heuristic, 1000, 42)
        for label in (PONE, DEALER, "both_seats"):
            self.assertEqual(report[label], {"n": 1000, "mu": 0.0, "se": 0.0})
        self.assertFalse(report["passed"])


class TestGateArguments(unittest.TestCase):
    def test_enabled_gate_rejects_fewer_than_one_thousand_deals(self):
        for deals in (1, 2, 999):
            with self.subTest(deals=deals):
                argv = ["generate_play_table.py", f"--promotion-gate-deals={deals}"]
                with patch("sys.argv", argv), patch(
                    "sys.stderr", io.StringIO()
                ) as stderr, patch.object(
                    generator, "solve_initial_discard_policy"
                ) as solve, self.assertRaises(
                    SystemExit
                ) as error:
                    generator.main()
                self.assertEqual(error.exception.code, 2)
                solve.assert_not_called()
                self.assertTrue("at least 1,000" in stderr.getvalue())

    def test_defaults_and_off_mode_accept_any_positive_count(self):
        with patch("sys.argv", ["generate_play_table.py"]):
            args = generator._parse_args()  # pylint: disable=protected-access
        self.assertEqual(
            (args.promotion_gate, args.promotion_gate_deals), ("report", 200_000)
        )
        for arguments in (
            ["--promotion-gate=off", "--promotion-gate-deals=1"],
            ["--promotion-gate=off", "--promotion-gate-deals=2"],
            ["--promotion-gate-deals=1000"],
        ):
            with patch("sys.argv", ["generate_play_table.py", *arguments]):
                args = generator._parse_args()  # pylint: disable=protected-access
            self.assertEqual(
                args.promotion_gate_deals, int(arguments[-1].split("=")[1])
            )


class TestGateInGeneration(unittest.TestCase):
    def test_report_adds_only_its_metadata_to_off_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            off, off_log = run_bounded_generation(directory, ["--promotion-gate=off"])
        with tempfile.TemporaryDirectory() as directory:
            report, log = run_bounded_generation(
                directory, ["--promotion-gate-deals=1000"]
            )
        off_full = json.loads(off.pop("full"))
        full = json.loads(report.pop("full"))
        gate = full["__metadata__"].pop("promotion_gate")
        self.assertFalse("promotion_gate" in off_full["__metadata__"])
        self.assertEqual(full, off_full)
        self.assertEqual(report, off)
        self.assertEqual(
            (gate["mode"], gate["deals"], gate["seed"]), ("report", 1000, 42)
        )
        self.assertEqual(gate["both_seats"]["n"], 1000)
        self.assertTrue("[promotion-gate] report:" in log)
        self.assertFalse("promotion-gate" in off_log)

    def test_off_drops_a_gate_report_carried_by_a_resumed_table(self):
        with tempfile.TemporaryDirectory() as directory:
            run_bounded_generation(directory, ["--promotion-gate-deals=1000"])
            outputs, _ = run_bounded_generation(
                directory, ["--promotion-gate=off"], resume=True
            )
        self.assertFalse(
            "promotion_gate" in json.loads(outputs["full"])["__metadata__"]
        )

    def test_gate_measures_final_trained_policies_before_measurement(self):
        events = []
        real_train = generator.train_iterative_best_response
        real_sample = generator.generate_play_table

        def train(*args, **kwargs):
            policies, reports = real_train(*args, **kwargs)
            events.append(("train", policies))
            return policies, reports

        def gate(policies, deals, seed):
            events.append(("gate", policies))
            return {"passed": False, "deals": deals, "seed": seed}

        def sample(discard_policy, policies, **kwargs):
            events.append(("final" if "checkpoint" in kwargs else "table", policies))
            return real_sample(discard_policy, policies, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            run_bounded_generation(
                directory,
                [],
                patch.object(generator, "train_iterative_best_response", train),
                patch.object(generator, "evaluate_promotion", gate),
                patch.object(generator, "describe_promotion", return_value=""),
                patch.object(generator, "generate_play_table", sample),
            )
        self.assertEqual(
            [name for name, _ in events], ["train", "table", "train", "gate", "final"]
        )
        self.assertIs(events[3][1], events[2][1])
        self.assertIs(events[4][1], events[2][1])

    def test_gate_streams_do_not_reuse_training_streams(self):
        training = {"active": False, "states": [], "deals": []}
        gate = {"states": [], "deals": []}
        real_train = generator.train_iterative_best_response
        real_policy_deal = generator.sample_policy_deal
        real_from_state = pegging.simulate_from_state
        real_pegging = pegging.simulate_pegging

        def train(*args, **kwargs):
            training["active"] = True
            try:
                return real_train(*args, **kwargs)
            finally:
                training["active"] = False

        def training_deal(rng, discard_policy):
            replica = random.Random()
            replica.setstate(rng.getstate())
            cards = replica.sample(range(52), 8)
            training["deals"].append(
                (
                    tuple(card // 4 for card in cards[:4]),
                    tuple(card // 4 for card in cards[4:]),
                )
            )
            return real_policy_deal(rng, discard_policy)

        def training_play(state, policies, rng, **kwargs):
            if training["active"]:
                training["states"].append(repr(rng.getstate()))
            return real_from_state(state, policies, rng, **kwargs)

        def gate_play(pone_hand, dealer_hand, policies, rng):
            gate["states"].append(repr(rng.getstate()))
            gate["deals"].append((pone_hand, dealer_hand))
            return real_pegging(pone_hand, dealer_hand, policies, rng)

        with tempfile.TemporaryDirectory() as directory:
            run_bounded_generation(
                directory,
                ["--promotion-gate-deals=1000"],
                patch.object(generator, "train_iterative_best_response", train),
                patch.object(generator, "sample_policy_deal", training_deal),
                patch.object(pegging, "simulate_from_state", training_play),
                patch.object(promotion_gate, "simulate_pegging", gate_play),
            )
        self.assertGreater(len(training["deals"]), 0)
        self.assertGreater(len(training["states"]), 0)
        self.assertEqual(len(set(gate["states"])), 1000)
        self.assertTrue(set(gate["deals"]).isdisjoint(training["deals"]))
        self.assertTrue(set(gate["states"]).isdisjoint(training["states"]))


if __name__ == "__main__":
    unittest.main()
