import unittest
import io
import math
import os
import json
import random
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import argparse
from artifact_pipeline.generate_table import (
    accumulator_to_statistics,
    accumulators_to_output,
    build_metadata,
    calculate_max_ev_shift,
    get_canonical_pairs,
    canonical_to_cards,
    load_or_initialize_accumulators,
    run_monte_carlo,
    run_monte_carlo_into_accumulators,
    compute_statistics,
    run_generation,
    statistics_to_accumulator,
    minimum_completed_sample_count,
    reached_target_sample_count,
    main,
    positive_int,
)


def run_main_silently(override_pairs=None):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        main(override_pairs)


def _make_main_args(output_path, samples="1", seed="42", no_resume=False, extra=None):
    args = [
        "generate_table.py",
        "--samples",
        samples,
        "--seed",
        seed,
        "--output",
        output_path,
    ]
    if no_resume:
        args.append("--no-resume")
    if extra:
        args.extend(extra)
    return args


def _run_seeded_fresh(output_path, samples="1", seed="42", pairs=None, extra=None):
    args = _make_main_args(output_path, samples, seed, no_resume=True, extra=extra)
    with patch("sys.argv", args):
        run_main_silently(pairs or ["A_A_Unsuited"])


def _run_seeded_resume(output_path, samples="2", seed="42", pairs=None):
    args = _make_main_args(output_path, samples, seed)
    with patch("sys.argv", args):
        run_main_silently(pairs or ["A_A_Unsuited"])


def _count_dealer_samples(output_path, pair="A_A_Unsuited"):
    with open(output_path, "r", encoding="utf-8") as output_file:
        data = json.load(output_file)
    return sum(stats["n"] for stats in data[pair]["Dealer"].values()), data


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
        self.assertEqual(len(checkpoint_calls), 1)

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
            ), patch(
                "artifact_pipeline.generate_table.get_canonical_pairs",
                return_value=["A_A_Unsuited"],
            ):
                run_main_silently()

            self.assertTrue(os.path.exists(output_path))

            with open(output_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            num_canonical_pairs = 1
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

            _run_seeded_fresh(output_path)
            _run_seeded_resume(output_path, samples="1")

            total_samples, _ = _count_dealer_samples(output_path)
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

            _run_seeded_fresh(output_path)
            _run_seeded_resume(output_path)

            total_samples, _ = _count_dealer_samples(output_path)
            self.assertEqual(total_samples, 2)

    def test_seeded_resume_rejects_different_seed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")

            _run_seeded_fresh(output_path)

            with self.assertRaises(ValueError):
                _run_seeded_resume(output_path, seed="43")

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

            with self.assertRaises(ValueError):
                _run_seeded_resume(output_path)

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

            _run_seeded_fresh(
                output_path,
                samples="2",
                extra=["--checkpoint-frequency", "1"],
            )

            total_samples, _ = _count_dealer_samples(output_path)
            self.assertEqual(total_samples, 2)

    def test_seeded_resume_matches_fresh_seeded_run(self):
        """Test seeded resume continues the deterministic sample sequence."""
        with tempfile.TemporaryDirectory() as temp_dir:
            resumed_output_path = os.path.join(temp_dir, "resumed.json")
            fresh_output_path = os.path.join(temp_dir, "fresh.json")

            _run_seeded_fresh(resumed_output_path)
            _run_seeded_resume(resumed_output_path)

            _run_seeded_fresh(fresh_output_path, samples="2")

            _, resumed_data = _count_dealer_samples(resumed_output_path)
            _, fresh_data = _count_dealer_samples(fresh_output_path)

            self.assertEqual(resumed_data, fresh_data)

    # pylint: disable=too-many-locals
    def test_hessel_fixture(self):
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

                    self.assertLessEqual(abs(mu_rollup - expected_ev), 2.58 * se_rollup)
                else:
                    # pylint: disable=cell-var-from-loop
                    pair_suited_str = f"{rank1}_{rank2}_Suited"
                    pair_unsuited_str = f"{rank1}_{rank2}_Unsuited"

                    def rollup_suit(suit_str):
                        dealer_data = data[suit_str]["Dealer"]
                        mu_sum = 0.0
                        var_sum = 0.0
                        w_sum = 0
                        for cut_rank_str, stats in dealer_data.items():
                            n = stats["n"]
                            if n == 0:
                                continue
                            # pylint: disable=cell-var-from-loop
                            discard_count = (1 if rank1 == cut_rank_str else 0) + (
                                1 if rank2 == cut_rank_str else 0
                            )
                            weight = 4 - discard_count
                            mu_sum += stats["mu"] * weight
                            var_sum += (stats["se"] ** 2) * weight * weight
                            w_sum += weight
                        return mu_sum / w_sum, math.sqrt(var_sum) / w_sum

                    mu_suited, se_suited = rollup_suit(pair_suited_str)
                    mu_unsuited, se_unsuited = rollup_suit(pair_unsuited_str)

                    mu_rollup = (0.25 * mu_suited) + (0.75 * mu_unsuited)
                    se_rollup = math.sqrt(
                        (0.25**2) * (se_suited**2) + (0.75**2) * (se_unsuited**2)
                    )

                    self.assertLessEqual(abs(mu_rollup - expected_ev), 2.58 * se_rollup)
                    self.assertGreater(
                        mu_suited + 2.58 * math.sqrt(se_suited**2 + se_unsuited**2),
                        mu_unsuited,
                    )

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

    def test_resume_validates_metadata_with_empty_accumulators(self):
        """Metadata is checked even when accumulators have no samples."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "expected_crib_points.json")
            with open(output_path, "w", encoding="utf-8") as output_file:
                json.dump(
                    {
                        "__metadata__": build_metadata(42),
                        "A_A_Unsuited": {
                            "Dealer": {},
                            "Pone": {},
                        },
                    },
                    output_file,
                )

            with self.assertRaises(ValueError):
                load_or_initialize_accumulators(output_path, False, 99)

    def test_calculate_max_ev_shift_dropped_bucket(self):
        """Shift counts a bucket that existed previously but not now."""
        prev = {
            "A_A_Unsuited": {
                "Dealer": {
                    "A": {"n": 1, "sum": 7.0, "sum_squares": 49.0},
                },
            },
        }
        curr = {"A_A_Unsuited": {"Dealer": {}}}
        shift = calculate_max_ev_shift(prev, curr, ["A_A_Unsuited"])
        self.assertAlmostEqual(shift, 7.0)

    def test_calculate_max_ev_shift_new_bucket(self):
        """Shift counts a bucket that appears only in current."""
        prev = {"A_A_Unsuited": {"Dealer": {}}}
        curr = {
            "A_A_Unsuited": {
                "Dealer": {
                    "A": {"n": 1, "sum": 3.0, "sum_squares": 9.0},
                },
            },
        }
        shift = calculate_max_ev_shift(prev, curr, ["A_A_Unsuited"])
        self.assertAlmostEqual(shift, 3.0)

    def test_calculate_max_ev_shift_neither_exists(self):
        """Shift is zero when neither side has any data."""
        shift = calculate_max_ev_shift({}, {}, ["A_A_Unsuited"])
        self.assertAlmostEqual(shift, 0.0)

    def test_custom_expected_crib_points_ignoring_suit(self):
        """Test the monkeypatched ignoring-suit expected crib points handler."""
        # pylint: disable=import-outside-toplevel
        import simulate_cribbage_games
        from artifact_pipeline.generate_table import select_opponent_kept_cards_dynamic

        gen_acc = {
            "A_2_Unsuited": {"Dealer": {"A": {"n": 1, "sum": 5.0, "sum_squares": 25.0}}}
        }

        from artifact_pipeline.adapter import Card

        def fake_keep(opponent_dealt):
            del opponent_dealt
            return simulate_cribbage_games.expected_random_opponent_discard_crib_points_ignoring_suit(
                0, 1
            )

        with patch(
            "artifact_pipeline.adapter.keep_max_post_cut_hand_plus_crib_points",
            fake_keep,
        ):
            val = select_opponent_kept_cards_dynamic(
                "Pone", [Card(0, 0)], generation_accumulators=gen_acc
            )
            self.assertAlmostEqual(val, 0.3)

    def test_keyboard_interrupt_handling(self):
        """Test KeyboardInterrupt prints checkpoint and raises SystemExit."""
        with patch(
            "sys.argv",
            [
                "generate_table.py",
                "--samples",
                "1",
                "--seed",
                "42",
                "--output",
                "irrelevant_path.json",
            ],
        ):
            with patch(
                "artifact_pipeline.generate_table.run_generation",
                side_effect=KeyboardInterrupt,
            ):
                with self.assertRaises(SystemExit) as cm:
                    main(["A_A_Unsuited"])
                self.assertEqual(cm.exception.code, 130)

    def test_max_generations_hardcap_at_start(self):
        """Test hardcap check at the beginning of the generation loop."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "out.json")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "__metadata__": {
                            "generation_method": "artifact_pipeline.generate_table.v1",
                            "seed": 42,
                            "seed_was_specified": True,
                            "generation": 2,
                            "generation_accumulators": None,
                        }
                    },
                    f,
                )
            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "2",
                    "--checkpoint-frequency",
                    "1",
                    "--max-generations",
                    "2",
                    "--seed",
                    "42",
                    "--output",
                    output_path,
                ],
            ):
                with patch("artifact_pipeline.generate_table.print") as mock_print:
                    run_main_silently(["A_A_Unsuited"])
                    mock_print.assert_any_call(
                        "Warning: Hardcap reached at generation 2."
                    )

    def test_main_finite_no_progress_break(self):
        """Test made_progress = False break in finite runs."""
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
                    "--seed",
                    "42",
                    "--output",
                    output_path,
                ],
            ):
                with patch(
                    "artifact_pipeline.generate_table.run_generation",
                    return_value=False,
                ):
                    run_main_silently(["A_A_Unsuited"])
                    self.assertTrue(os.path.exists(output_path))

    def test_convergence_threshold_generation_accumulators_none(self):
        """Test convergence check does not raise when generation_accumulators is None."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "out.json")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "__metadata__": {
                            "generation_method": "artifact_pipeline.generate_table.v1",
                            "seed": 42,
                            "seed_was_specified": True,
                            "generation": 1,
                            "generation_accumulators": None,
                        },
                        "A_A_Unsuited": {
                            "Dealer": {"A": {"n": 1, "mu": 4.0, "se": 0.0}},
                            "Pone": {"A": {"n": 1, "mu": 4.0, "se": 0.0}},
                        },
                    },
                    f,
                )
            with patch(
                "sys.argv",
                [
                    "generate_table.py",
                    "--samples",
                    "2",
                    "--checkpoint-frequency",
                    "1",
                    "--convergence-threshold",
                    "0.1",
                    "--seed",
                    "42",
                    "--output",
                    output_path,
                ],
            ):
                run_main_silently(["A_A_Unsuited"])
                self.assertTrue(os.path.exists(output_path))


if __name__ == "__main__":
    unittest.main()
