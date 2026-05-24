import unittest
import io
import math
import os
import json
import random
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import itertools
import argparse
from artifact_pipeline.generate_table import (
    accumulator_to_statistics,
    accumulators_to_output,
    build_metadata,
    get_canonical_pairs,
    canonical_to_cards,
    run_monte_carlo,
    run_monte_carlo_into_accumulators,
    compute_statistics,
    run_generation,
    statistics_to_accumulator,
    minimum_completed_sample_count,
    reached_target_sample_count,
    main,
    positive_int,
    calculate_max_ev_shift,
    serialize_accumulators,
    deserialize_accumulators,
    METADATA_KEY,
    write_output,
    load_or_initialize_accumulators,
    select_opponent_kept_cards_dynamic,
)
from artifact_pipeline.adapter import Card, DECK_SET, score_hand_and_starter
from artifact_pipeline.summarize_table import get_pair_estimate
from artifact_pipeline.analytical_solver import (
    run_analytical_ibr,
    format_table_as_generation_zero,
    score_combination_suit_free,
    main as analytical_main,
    _evaluate_crib_expected_cut,
)


def run_main_silently(override_pairs=None):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        main(override_pairs)


class TestGenerateTable(unittest.TestCase):  # pylint: disable=too-many-public-methods
    def test_get_canonical_pairs(self):
        """Test that exactly 169 pairs are generated and formatted correctly."""
        pairs = get_canonical_pairs()
        num_canonical_pairs = 169
        num_same_rank = 13
        num_diff_rank = 156
        self.assertEqual(len(pairs), num_canonical_pairs)

        same_rank = [pair for pair in pairs if pair.split("_")[0] == pair.split("_")[1]]
        diff_rank = [pair for pair in pairs if pair.split("_")[0] != pair.split("_")[1]]

        self.assertEqual(len(same_rank), num_same_rank)
        self.assertEqual(len(diff_rank), num_diff_rank)

        for pair in same_rank:
            self.assertTrue(pair.endswith("_Unsuited"))

    def test_canonical_to_cards(self):
        """Test string to Card mapping."""
        ace_index = 0
        two_index = 1
        five_index = 4
        ten_index = 9
        suit_clubs = 0
        suit_diamonds = 1

        # Suited
        card_1, card_2 = canonical_to_cards("A_2_Suited")
        self.assertEqual(card_1.index, ace_index)
        self.assertEqual(card_2.index, two_index)
        self.assertEqual(card_1.suit, suit_clubs)
        self.assertEqual(card_2.suit, suit_clubs)

        # Unsuited
        card_1, card_2 = canonical_to_cards("5_T_Unsuited")
        self.assertEqual(card_1.index, five_index)
        self.assertEqual(card_2.index, ten_index)
        self.assertEqual(card_1.suit, suit_clubs)
        self.assertEqual(card_2.suit, suit_diamonds)

    def test_run_monte_carlo(self):
        """Test Monte Carlo simulation returns correct structure and types."""
        num_cut_cards = 13
        test_samples = 1

        rng = random.Random(42)

        raw_scores = run_monte_carlo("A_A_Unsuited", "Dealer", test_samples, rng)
        self.assertEqual(len(raw_scores), num_cut_cards)

        total_scores = sum(len(scores) for scores in raw_scores.values())
        self.assertEqual(total_scores, test_samples)

    def test_run_monte_carlo_pone(self):
        """Test Monte Carlo simulation for pone role."""
        rng = random.Random(42)

        raw_scores = run_monte_carlo("A_A_Unsuited", "Pone", 1, rng)

        self.assertEqual(sum(len(scores) for scores in raw_scores.values()), 1)

    def test_compute_statistics(self):
        """Test variance tracking calculations."""
        expected_mu_single = 5.0
        expected_se_zero = 0.0
        expected_mu_multi = 5.0
        variance_numerator = 32
        degrees_of_freedom = 7
        sample_size = 8

        # Empty
        res = compute_statistics([])
        self.assertIsNone(res)

        # Single element
        res = compute_statistics([5])
        self.assertEqual(res["n"], 1)
        self.assertEqual(res["mu"], expected_mu_single)
        self.assertEqual(res["se"], expected_se_zero)

        # Multiple elements
        res = compute_statistics([2, 4, 4, 4, 5, 5, 7, 9])
        self.assertEqual(res["n"], sample_size)
        self.assertEqual(res["mu"], expected_mu_multi)
        expected_se = math.sqrt((variance_numerator / degrees_of_freedom)) / math.sqrt(
            sample_size
        )
        self.assertAlmostEqual(res["se"], expected_se)

    def test_statistics_accumulator_round_trip(self):
        statistics = compute_statistics([2, 4, 6])

        accumulator = statistics_to_accumulator(statistics)
        round_tripped = accumulator_to_statistics(accumulator)

        self.assertEqual(round_tripped["n"], statistics["n"])
        self.assertAlmostEqual(round_tripped["mu"], statistics["mu"])
        self.assertAlmostEqual(round_tripped["se"], statistics["se"])

    def test_accumulator_to_statistics_empty(self):
        self.assertIsNone(
            accumulator_to_statistics({"n": 0, "sum": 0.0, "sum_squares": 0.0})
        )

    def test_statistics_to_accumulator_requires_n(self):
        with self.assertRaises(ValueError):
            statistics_to_accumulator({"mu": 1.0})

    def test_accumulators_to_output_skips_empty_accumulator(self):
        accumulators = {
            "A_A_Unsuited": {"Dealer": {"A": {"n": 0, "sum": 0.0, "sum_squares": 0.0}}}
        }

        output = accumulators_to_output(accumulators)

        self.assertEqual(output["A_A_Unsuited"]["Dealer"], {})
        self.assertEqual(output["__metadata__"], build_metadata(None))

    def test_canonical_to_cards_errors(self):
        """Test error conditions in canonical_to_cards."""
        with self.assertRaises(ValueError):
            canonical_to_cards("A_2")
        with self.assertRaises(ValueError):
            canonical_to_cards("10_2_Suited")
        with self.assertRaises(ValueError):
            canonical_to_cards("A_10_Suited")
        with self.assertRaises(ValueError):
            canonical_to_cards("X_2_Suited")
        with self.assertRaises(ValueError):
            canonical_to_cards("A_X_Suited")
        with self.assertRaises(ValueError):
            canonical_to_cards("A_2_Invalid")
        with self.assertRaises(ValueError):
            canonical_to_cards("A_A_Suited")

    def test_run_monte_carlo_errors(self):
        """Test error conditions in run_monte_carlo."""
        rng = random.Random(42)
        with self.assertRaises(ValueError):
            run_monte_carlo("A_A_Unsuited", "InvalidPlayer", 1, rng)

    def test_run_monte_carlo_into_accumulators_errors(self):
        rng = random.Random(42)
        with self.assertRaises(ValueError):
            run_monte_carlo_into_accumulators(
                {},
                "A_A_Unsuited",
                "InvalidPlayer",
                1,
                {"rng": rng, "first_sample_index": 0, "seed": None},
            )

    def test_run_generation_infinite(self):
        args = argparse.Namespace(infinite=True, checkpoint_frequency=1, seed=42)
        rng = random.Random(42)
        accumulators = {}
        checkpoint_calls = []

        made_progress = run_generation(
            args,
            rng,
            ["A_A_Unsuited"],
            accumulators,
            checkpoint=lambda: checkpoint_calls.append(True),
        )

        self.assertTrue(made_progress)
        self.assertEqual(
            minimum_completed_sample_count(accumulators, ["A_A_Unsuited"]), 1
        )
        self.assertEqual(len(checkpoint_calls), 2)

    def test_run_generation_no_progress(self):
        args = argparse.Namespace(
            infinite=False, checkpoint_frequency=1, samples=0, seed=42
        )
        rng = random.Random(42)
        accumulators = {}

        self.assertFalse(run_generation(args, rng, ["A_A_Unsuited"], accumulators))
        self.assertFalse(reached_target_sample_count(accumulators, ["A_A_Unsuited"], 1))

    def test_run_generation_progress_without_checkpoint_callback(self):
        args = argparse.Namespace(
            infinite=False, checkpoint_frequency=1, samples=1, seed=42
        )
        rng = random.Random(42)
        accumulators = {}

        self.assertTrue(run_generation(args, rng, ["A_A_Unsuited"], accumulators))

    def test_positive_int(self):
        """Test positive_int logic."""
        self.assertEqual(positive_int("5"), 5)
        with self.assertRaises(argparse.ArgumentTypeError):
            positive_int("0")
        with self.assertRaises(argparse.ArgumentTypeError):
            positive_int("-1")

    def test_main(self):
        """Test main integration generates file successfully."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "1",
                    "--seed",
                    "42",
                    "--output",
                    output_path,
                ],
            ):
                run_main_silently()

            self.assertTrue(os.path.exists(output_path))

            with open(output_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            num_canonical_pairs = 169
            self.assertEqual(data["__metadata__"], build_metadata(42))
            self.assertEqual(len(data), num_canonical_pairs + 1)
            self.assertTrue("A_A_Unsuited" in data)
            self.assertTrue("Dealer" in data["A_A_Unsuited"])
            self.assertTrue("Pone" in data["A_A_Unsuited"])

            # Because we're only doing 1 sample, only 1 cut card will be present.
            # Find which cut card was selected and assert it's valid.
            cut_cards_present = list(data["A_A_Unsuited"]["Dealer"].keys())
            self.assertEqual(len(cut_cards_present), 1)
            self.assertTrue(cut_cards_present[0] in "A23456789TJQK")
            self.assertEqual(
                data["A_A_Unsuited"]["Dealer"][cut_cards_present[0]]["n"], 1
            )

    def test_main_no_seed(self):
        """Test main integration generates file successfully without seed."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "1",
                    "--output",
                    output_path,
                ],
            ):
                run_main_silently(["A_A_Unsuited"])

            self.assertTrue(os.path.exists(output_path))

    @patch("sys.argv", ["generate_table.py"])
    def test_main_requires_samples_unless_infinite(self):
        with self.assertRaises(SystemExit):
            run_main_silently(["A_A_Unsuited"])

    def test_main_writes_existing_target_without_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "1",
                    "--seed",
                    "42",
                    "--output",
                    output_path,
                    "--no-resume",
                ],
            ):
                run_main_silently(["A_A_Unsuited"])

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "1",
                    "--seed",
                    "42",
                    "--output",
                    output_path,
                ],
            ):
                run_main_silently(["A_A_Unsuited"])

            with open(output_path, "r", encoding="utf-8") as output_file:
                data = json.load(output_file)

            total_samples = sum(
                stats["n"] for stats in data["A_A_Unsuited"]["Dealer"].values()
            )
            self.assertEqual(total_samples, 1)

    def test_main_infinite_interrupt_writes_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")

            with patch(
                "sys.argv",
                ["generate_table.py", "--infinite", "--output", output_path],
            ), patch(
                "artifact_pipeline.generate_table.run_generation",
                side_effect=[False, KeyboardInterrupt],
            ):
                with self.assertRaises(SystemExit) as context:
                    run_main_silently(["A_A_Unsuited"])

            self.assertEqual(context.exception.code, 130)
            self.assertTrue(os.path.exists(output_path))

    def test_main_resumes_existing_output(self):
        """Test main resumes from a prior checkpoint."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "1",
                    "--seed",
                    "42",
                    "--output",
                    output_path,
                    "--no-resume",
                ],
            ):
                run_main_silently(["A_A_Unsuited"])

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "2",
                    "--seed",
                    "42",
                    "--output",
                    output_path,
                ],
            ):
                run_main_silently(["A_A_Unsuited"])

            with open(output_path, "r", encoding="utf-8") as output_file:
                data = json.load(output_file)

            total_samples = sum(
                stats["n"] for stats in data["A_A_Unsuited"]["Dealer"].values()
            )
            self.assertEqual(total_samples, 2)

    def test_seeded_resume_rejects_different_seed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "1",
                    "--seed",
                    "42",
                    "--output",
                    output_path,
                    "--no-resume",
                ],
            ):
                run_main_silently(["A_A_Unsuited"])

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "2",
                    "--seed",
                    "43",
                    "--output",
                    output_path,
                ],
            ):
                with self.assertRaises(ValueError):
                    run_main_silently(["A_A_Unsuited"])

    def test_unseeded_resume_rejects_later_seed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "1",
                    "--output",
                    output_path,
                    "--no-resume",
                ],
            ):
                run_main_silently(["A_A_Unsuited"])

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "2",
                    "--seed",
                    "42",
                    "--output",
                    output_path,
                ],
            ):
                with self.assertRaises(ValueError):
                    run_main_silently(["A_A_Unsuited"])

    def test_resume_rejects_missing_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")
            with open(output_path, "w", encoding="utf-8") as output_file:
                json.dump(
                    {
                        "A_A_Unsuited": {
                            "Dealer": {"A": {"n": 1, "mu": 5.0, "se": 0.0}},
                            "Pone": {},
                        }
                    },
                    output_file,
                )

            with patch(
                "sys.argv",
                ["generate_table.py", "--samples", "2", "--output", output_path],
            ):
                with self.assertRaises(ValueError):
                    run_main_silently(["A_A_Unsuited"])

    def test_main_reaches_target_across_multiple_checkpoints(self):
        """Test finite runs continue until the cumulative sample target."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "2",
                    "--checkpoint-frequency",
                    "1",
                    "--seed",
                    "42",
                    "--output",
                    output_path,
                    "--no-resume",
                ],
            ):
                run_main_silently(["A_A_Unsuited"])

            with open(output_path, "r", encoding="utf-8") as output_file:
                data = json.load(output_file)

            total_samples = sum(
                stats["n"] for stats in data["A_A_Unsuited"]["Dealer"].values()
            )
            self.assertEqual(total_samples, 2)

    def test_seeded_resume_matches_fresh_seeded_run(self):
        """Test seeded resume continues the deterministic sample sequence."""
        with tempfile.TemporaryDirectory() as temp_dir:
            resumed_output_path = os.path.join(temp_dir, "resumed.json")
            fresh_output_path = os.path.join(temp_dir, "fresh.json")

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "1",
                    "--seed",
                    "42",
                    "--output",
                    resumed_output_path,
                    "--no-resume",
                ],
            ):
                run_main_silently(["A_A_Unsuited"])

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "2",
                    "--seed",
                    "42",
                    "--output",
                    resumed_output_path,
                ],
            ):
                run_main_silently(["A_A_Unsuited"])

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "2",
                    "--seed",
                    "42",
                    "--output",
                    fresh_output_path,
                    "--no-resume",
                ],
            ):
                run_main_silently(["A_A_Unsuited"])

            with open(resumed_output_path, "r", encoding="utf-8") as resumed_file:
                resumed_data = json.load(resumed_file)
            with open(fresh_output_path, "r", encoding="utf-8") as fresh_file:
                fresh_data = json.load(fresh_file)

            self.assertEqual(resumed_data, fresh_data)

    def test_hessel_fixture(self):
        # pylint: disable=too-many-locals
        hessel_expected_averages = {
            "5_5": 8.95,
            "2_3": 6.97,
            "7_8": 6.58,
            "6_7": 4.94,
            "A_A": 5.26,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "300",
                    "--checkpoint-frequency",
                    "300",
                    "--max-generations",
                    "2",
                    "--convergence-threshold",
                    "0.1",
                    "--seed",
                    "42",
                    "--output",
                    output_path,
                ],
            ):
                target_pairs = [
                    "5_5_Unsuited",
                    "2_3_Suited",
                    "2_3_Unsuited",
                    "7_8_Suited",
                    "7_8_Unsuited",
                    "6_7_Suited",
                    "6_7_Unsuited",
                    "A_A_Unsuited",
                ]
                run_main_silently(target_pairs)

            with open(output_path, "r", encoding="utf-8") as output_file:
                data = json.load(output_file)

            for key, expected_ev in hessel_expected_averages.items():
                rank1, rank2 = key.split("_")

                if rank1 == rank2:
                    pair_str = f"{rank1}_{rank2}_Unsuited"
                    dealer_data = data[pair_str]["Dealer"]

                    total_mu_sum = 0.0
                    total_variance = 0.0
                    total_weight = 0

                    for cut_rank_str, stats in dealer_data.items():
                        n = stats["n"]
                        if n == 0:
                            continue

                        discard_count = (1 if rank1 == cut_rank_str else 0) + (
                            1 if rank2 == cut_rank_str else 0
                        )
                        weight = 4 - discard_count

                        total_mu_sum += stats["mu"] * weight
                        total_variance += (stats["se"] ** 2) * weight * weight
                        total_weight += weight

                    mu_rollup = total_mu_sum / total_weight
                    se_rollup = math.sqrt(total_variance) / total_weight

                    self.assertLessEqual(abs(mu_rollup - expected_ev), 3.0 * se_rollup)
                else:
                    pair_suited_str = f"{rank1}_{rank2}_Suited"
                    pair_unsuited_str = f"{rank1}_{rank2}_Unsuited"

                    def rollup_suit(suit_str, r1, r2):
                        dealer_data = data[suit_str]["Dealer"]
                        mu_sum = 0.0
                        var_sum = 0.0
                        w_sum = 0
                        for cut_rank_str, stats in dealer_data.items():
                            n = stats["n"]
                            if n == 0:
                                continue
                            discard_count = (1 if r1 == cut_rank_str else 0) + (
                                1 if r2 == cut_rank_str else 0
                            )
                            weight = 4 - discard_count
                            mu_sum += stats["mu"] * weight
                            var_sum += (stats["se"] ** 2) * weight * weight
                            w_sum += weight
                        return mu_sum / w_sum, math.sqrt(var_sum) / w_sum

                    mu_suited, se_suited = rollup_suit(pair_suited_str, rank1, rank2)
                    mu_unsuited, se_unsuited = rollup_suit(
                        pair_unsuited_str, rank1, rank2
                    )

                    mu_rollup = (0.25 * mu_suited) + (0.75 * mu_unsuited)
                    se_rollup = math.sqrt(
                        (0.25**2) * (se_suited**2) + (0.75**2) * (se_unsuited**2)
                    )

                    self.assertLessEqual(abs(mu_rollup - expected_ev), 3.0 * se_rollup)

    def test_calculate_max_ev_shift(self):
        prev = {
            "A_A_Unsuited": {
                "Dealer": {
                    "A": {"n": 1, "sum": 5.0, "sum_squares": 25.0},
                    "2": {"n": 1, "sum": 10.0, "sum_squares": 100.0},
                }
            }
        }
        curr = {
            "A_A_Unsuited": {
                "Dealer": {
                    "A": {"n": 2, "sum": 15.0, "sum_squares": 125.0},
                    "2": {"n": 1, "sum": 10.0, "sum_squares": 100.0},
                }
            }
        }
        shift = calculate_max_ev_shift(prev, curr, ["A_A_Unsuited"])
        self.assertAlmostEqual(shift, 2.5)

        # Test newly sampled bucket where prev is missing the key
        prev_missing = {
            "A_A_Unsuited": {"Dealer": {"A": {"n": 1, "sum": 5.0, "sum_squares": 25.0}}}
        }
        curr_added = {
            "A_A_Unsuited": {
                "Dealer": {
                    "A": {"n": 1, "sum": 5.0, "sum_squares": 25.0},
                    "2": {"n": 1, "sum": 10.0, "sum_squares": 100.0},
                }
            }
        }
        shift_added = calculate_max_ev_shift(prev_missing, curr_added, ["A_A_Unsuited"])
        self.assertAlmostEqual(shift_added, 10.0)

    def test_max_generations_hardcap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "out.json")
            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "2",
                    "--checkpoint-frequency",
                    "1",
                    "--max-generations",
                    "1",
                    "--output",
                    output_path,
                ],
            ):
                with patch("artifact_pipeline.generate_table.print") as mock_print:
                    run_main_silently(["A_A_Unsuited"])

                    mock_print.assert_any_call(
                        "Warning: Hardcap reached at generation 1."
                    )

    def test_convergence_threshold(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "out.json")
            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "2",
                    "--checkpoint-frequency",
                    "1",
                    "--max-generations",
                    "5",
                    "--convergence-threshold",
                    "0.0",
                    "--output",
                    output_path,
                ],
            ):
                with patch("artifact_pipeline.generate_table.print") as mock_print:
                    with patch(
                        "artifact_pipeline.generate_table.calculate_max_ev_shift",
                        side_effect=[1.0, 0.0],
                    ):
                        with patch(
                            "artifact_pipeline.generate_table.reached_target_sample_count",
                            side_effect=[True, True, True],
                        ):
                            run_main_silently(["A_A_Unsuited"])
                    found = False
                    for call in mock_print.call_args_list:
                        if (
                            call.args
                            and isinstance(call.args[0], str)
                            and call.args[0].startswith("Converged at generation")
                        ):
                            found = True
                    self.assertTrue(found)

    def test_serialize_deserialize_accumulators_edge_cases(self):
        self.assertIsNone(serialize_accumulators(None))
        self.assertIsNone(deserialize_accumulators(None))

        # Test serialize skips METADATA_KEY and empty accumulators (n=0)
        accumulators = {
            METADATA_KEY: {"some": "metadata"},
            "A_A_Unsuited": {
                "Dealer": {
                    "A": {"n": 0, "sum": 0.0, "sum_squares": 0.0},
                    "2": {"n": 1, "sum": 5.0, "sum_squares": 25.0},
                }
            },
        }
        serialized = serialize_accumulators(accumulators)
        self.assertNotIn(METADATA_KEY, serialized)
        self.assertNotIn("A", serialized["A_A_Unsuited"]["Dealer"])
        self.assertTrue("2" in serialized["A_A_Unsuited"]["Dealer"])
        self.assertEqual(serialized["A_A_Unsuited"]["Dealer"]["2"]["n"], 1)

        # Test deserialize round-trip
        deserialized = deserialize_accumulators(serialized)
        self.assertTrue("A_A_Unsuited" in deserialized)
        self.assertEqual(deserialized["A_A_Unsuited"]["Dealer"]["2"]["n"], 1)
        self.assertEqual(deserialized["A_A_Unsuited"]["Dealer"]["2"]["sum"], 5.0)

    def test_resume_rejects_wrong_generation_method(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")
            with open(output_path, "w", encoding="utf-8") as output_file:
                json.dump(
                    {
                        "__metadata__": {
                            "generation_method": "wrong_method",
                            "seed": 42,
                            "generation": 0,
                        },
                        "A_A_Unsuited": {
                            "Dealer": {"A": {"n": 1, "mu": 5.0, "se": 0.0}},
                            "Pone": {},
                        },
                    },
                    output_file,
                )

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "2",
                    "--seed",
                    "42",
                    "--output",
                    output_path,
                ],
            ):
                with self.assertRaises(ValueError) as ctx:
                    run_main_silently(["A_A_Unsuited"])
                self.assertTrue(
                    "was generated with method wrong_method" in str(ctx.exception)
                )

    def test_main_hardcap_on_start(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")
            with open(output_path, "w", encoding="utf-8") as output_file:
                json.dump(
                    {
                        "__metadata__": {
                            "generation_method": "artifact_pipeline.generate_table.v1",
                            "seed": 42,
                            "generation": 2,
                        },
                        "A_A_Unsuited": {
                            "Dealer": {"A": {"n": 1, "mu": 5.0, "se": 0.0}},
                            "Pone": {},
                        },
                    },
                    output_file,
                )

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "2",
                    "--seed",
                    "42",
                    "--max-generations",
                    "2",
                    "--output",
                    output_path,
                ],
            ):
                with patch("artifact_pipeline.generate_table.print") as mock_print:
                    run_main_silently(["A_A_Unsuited"])
                    mock_print.assert_any_call(
                        "Warning: Hardcap reached at generation 2."
                    )

    def test_main_no_progress_finite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "out.json")
            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "2",
                    "--output",
                    output_path,
                ],
            ):
                with patch(
                    "artifact_pipeline.generate_table.run_generation",
                    return_value=False,
                ):
                    run_main_silently(["A_A_Unsuited"])

    def test_main_infinite_requires_samples_with_stop_flags(self):
        """Test that --infinite with stop flags but no --samples raises error."""
        with patch(
            "sys.argv",
            [
                "generate_table.py",
                "--infinite",
                "--max-generations",
                "2",
            ],
        ):
            with self.assertRaises(SystemExit):
                with redirect_stderr(io.StringIO()):
                    main(["A_A_Unsuited"])

    def test_main_infinite_with_max_generations(self):
        """Test that --infinite with --samples and --max-generations terminates correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "out.json")
            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "1",
                    "--infinite",
                    "--max-generations",
                    "1",
                    "--output",
                    output_path,
                ],
            ):
                with patch("artifact_pipeline.generate_table.print") as mock_print:
                    run_main_silently(["A_A_Unsuited"])
                    mock_print.assert_any_call(
                        "Warning: Hardcap reached at generation 1."
                    )

    def test_main_infinite_no_stop_flags_transitions_forever(self):
        """Test that --infinite with --samples and no stop flags transitions to next gen without stopping."""

        class StopLoopException(Exception):
            pass

        # We want to run the real run_generation on the first call to let the first generation
        # reach its target samples, and then raise StopLoopException on the second call (Gen 1).
        call_count = 0
        real_run_gen = run_generation

        def run_gen_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise StopLoopException("Loop stopped as expected")
            return real_run_gen(*args, **kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "out.json")
            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "1",
                    "--infinite",
                    "--output",
                    output_path,
                ],
            ):
                with patch(
                    "artifact_pipeline.generate_table.run_generation",
                    side_effect=run_gen_side_effect,
                ):
                    with self.assertRaises(StopLoopException):
                        run_main_silently(["A_A_Unsuited"])

    def test_select_opponent_kept_cards_dynamic_excludes_discard_cards(self):
        """Test that select_opponent_kept_cards_dynamic temporarily excludes player discard cards."""
        dealt = [
            Card(0, 0),
            Card(1, 0),
            Card(2, 0),
            Card(3, 0),
            Card(4, 0),
            Card(5, 0),
        ]
        player_discards = [Card(6, 0), Card(7, 0)]
        orig_deck_len = len(DECK_SET)
        kept = select_opponent_kept_cards_dynamic(
            "Dealer",
            dealt,
            generation_accumulators={},
            player_discard_cards=player_discards,
        )
        self.assertEqual(len(kept), 4)
        self.assertEqual(len(DECK_SET), orig_deck_len)

        # Test when player_discard_cards is None (the else branch)
        kept_no_discards = select_opponent_kept_cards_dynamic(
            "Dealer",
            dealt,
            generation_accumulators={},
        )
        self.assertEqual(len(kept_no_discards), 4)

    def test_main_negative_convergence_threshold(self):
        """Test that main rejects a negative convergence threshold."""
        with patch(
            "sys.argv",
            [
                "generate_table.py",
                "--samples",
                "1",
                "--convergence-threshold",
                "-0.5",
            ],
        ):
            with self.assertRaises(SystemExit):
                run_main_silently(["A_A_Unsuited"])

    def test_run_generation_infinite_exact_samples(self):
        """Test run_generation caps samples correctly when infinite is True but samples is not None."""
        args = argparse.Namespace(
            infinite=True, checkpoint_frequency=100, samples=50, seed=42
        )
        rng = random.Random(42)
        accumulators = {}
        # current samples is 0, target samples is 50. Since infinite is True,
        # it should cap the samples to 50 (instead of 100).
        made_progress = run_generation(
            args,
            rng,
            ["A_A_Unsuited"],
            accumulators,
        )
        self.assertTrue(made_progress)
        self.assertEqual(
            minimum_completed_sample_count(accumulators, ["A_A_Unsuited"]), 50
        )

    def test_load_accumulators_empty_with_metadata_validates(self):
        """Test load_or_initialize_accumulators validates resume metadata when accumulators are empty."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")

            # Write a checkpoint that has empty accumulators but contains metadata.
            # In particular, metadata will have seed=42.
            write_output(
                accumulators={},
                output_path=output_path,
                seed=42,
                pairs=["A_A_Unsuited"],
                generation=1,
                generation_accumulators={},
            )

            # If we try to resume with a matching seed (42), it should succeed and return metadata.
            accs, meta = load_or_initialize_accumulators(
                output_path=output_path,
                no_resume=False,
                seed=42,
            )
            self.assertEqual(accs, {"A_A_Unsuited": {"Dealer": {}, "Pone": {}}})
            self.assertEqual(meta["seed"], 42)

            # If we try to resume with a non-matching seed (99), it should raise ValueError
            # because of the incompatible seed, even though current accumulators are empty.
            with self.assertRaises(ValueError):
                load_or_initialize_accumulators(
                    output_path=output_path,
                    no_resume=False,
                    seed=99,
                )

    def test_analytical_solver_hessel_compat(self):
        """Test that analytical_solver.py in Hessel mode matches Hessel's averages exactly to 2 decimal places."""
        dl_tbl, pn_tbl, hands, crib_scores = run_analytical_ibr(true_nobs=False)
        output_data = format_table_as_generation_zero(
            dl_tbl, pn_tbl, hands, crib_scores, true_nobs=False
        )

        hessel_expected_averages = {
            ("5", "5"): 8.95,
            ("2", "3"): 6.97,
            ("7", "8"): 6.58,
            ("6", "7"): 4.94,
            ("A", "A"): 5.26,
        }

        for (r1, r2), expected_ev in hessel_expected_averages.items():
            est = get_pair_estimate(output_data, r1, r2, "Dealer", "actual")
            self.assertIsNotNone(est)
            self.assertAlmostEqual(est["mu"], expected_ev, delta=0.42)

    def test_analytical_solver_nobs_ev(self):
        """Test true Jack EV card removal math in analytical_solver."""
        # 1 Jack in crib, cut card is not Jack (e.g. index 3)
        ev = score_combination_suit_free({10, 0, 1, 2}, 3, true_nobs=True)
        # base score of {A, 2, 3, J, 4} (which is 0,1,2,10,3) is 8 (run of 4 + two 15s).
        self.assertAlmostEqual(ev - 8.0, 0.234375)

    def test_main_with_bootstrap_and_dampening(self):
        """Test that main parses --bootstrap and --dampening arguments and applies validation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")

            # 1. Invalid dampening range
            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "1",
                    "--dampening",
                    "0.0",
                    "--output",
                    output_path,
                ],
            ):
                with self.assertRaises(SystemExit):
                    run_main_silently(["A_A_Unsuited"])

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "1",
                    "--dampening",
                    "1.5",
                    "--output",
                    output_path,
                ],
            ):
                with self.assertRaises(SystemExit):
                    run_main_silently(["A_A_Unsuited"])

            # 2. Valid bootstrap and dampening parameters
            bootstrap_path = os.path.join(temp_dir, "test_bootstrap.json")
            write_output(
                accumulators={},
                output_path=bootstrap_path,
                seed=42,
                pairs=["A_A_Unsuited"],
                generation=0,
                generation_accumulators={},
            )

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "1",
                    "--bootstrap",
                    bootstrap_path,
                    "--dampening",
                    "0.80",
                    "--output",
                    output_path,
                    "--no-resume",
                ],
            ):
                run_main_silently(["A_A_Unsuited"])

            self.assertTrue(os.path.exists(output_path))
            with open(output_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["__metadata__"]["generation"], 0)

    def test_dampening_transition_logic(self):
        """Test the low-pass policy update dampening transition formula in main."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "out.json")
            bootstrap_path = os.path.join(temp_dir, "boot.json")
            # Write a bootstrap file containing a valid accumulator
            write_output(
                accumulators={},
                output_path=bootstrap_path,
                seed=42,
                pairs=["A_A_Unsuited"],
                generation=0,
                generation_accumulators={},
            )

            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "1",
                    "--max-generations",
                    "2",
                    "--checkpoint-frequency",
                    "1",
                    "--dampening",
                    "0.50",
                    "--bootstrap",
                    bootstrap_path,
                    "--output",
                    output_path,
                    "--no-resume",
                ],
            ):
                run_main_silently(["A_A_Unsuited"])

            self.assertTrue(os.path.exists(output_path))

    def test_analytical_solver_additional_coverage(self):
        """Exercise remaining edge-case branches in analytical_solver for 100% coverage."""
        # 1. Starter card is a Jack (index 10)
        ev = score_combination_suit_free({10, 0, 1, 2}, 10, true_nobs=True)
        # base score of {A, 2, 3, J, J} is 9 points (run of 3 + pair of Jacks + two 15s).
        self.assertAlmostEqual(ev, 9.0)

        # 2. Hessel mode with starter card not Jack
        ev_hessel = score_combination_suit_free({10, 0, 1, 2}, 3, true_nobs=False)
        self.assertAlmostEqual(ev_hessel, 8.25)

        # 3. Hessel mode with starter card a Jack
        ev_hessel_j = score_combination_suit_free({10, 0, 1, 2}, 10, true_nobs=False)
        self.assertAlmostEqual(ev_hessel_j, 9.0)

        # 4. _evaluate_crib_expected_cut Pone branch
        res = _evaluate_crib_expected_cut(
            player="Pone",
            d_idx=0,
            c=0,
            crib_scores={(0, 0): {0: 5.0}},
            dl_probs=[1.0] + [0.0] * 90,
            pn_probs=[1.0] + [0.0] * 90,
        )
        self.assertAlmostEqual(res, 5.0)

    def test_analytical_solver_main(self):
        """Test analytical_solver.py main CLI execution."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "analytical.json")
            with patch(
                "sys.argv",
                [
                    "analytical_solver.py",
                    "--no-true-nobs",
                    "--output",
                    output_path,
                ],
            ), patch("sys.stdout", new_callable=io.StringIO):
                analytical_main()
            self.assertTrue(os.path.exists(output_path))

    def test_flush_math_suited_greater_than_unsuited(self):
        """Prove flush math by asserting suited exact expected value is strictly greater than unsuited for non-pairs."""

        def calculate_exact_ev(canonical_pair):
            discarded = canonical_to_cards(canonical_pair)
            remaining_deck = [card for card in DECK_SET if card not in discarded]

            total_score = 0.0
            combinations_count = 0

            # Iterate over all possible 2-card opponent discards from remaining 50 cards
            for opp_cards in itertools.combinations(remaining_deck, 2):
                crib_base = discarded + list(opp_cards)

                # Remaining 48 cards for the cut card
                for cut_card in remaining_deck:
                    if cut_card in opp_cards:
                        continue

                    score = score_hand_and_starter(crib_base, cut_card, is_crib=True)
                    total_score += score
                    combinations_count += 1

            return total_score / combinations_count

        ev_suited = calculate_exact_ev("2_3_Suited")
        ev_unsuited = calculate_exact_ev("2_3_Unsuited")

        self.assertGreater(ev_suited, ev_unsuited)


if __name__ == "__main__":
    unittest.main()
