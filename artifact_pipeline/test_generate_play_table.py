"""Tests for expected pegging artifact generation."""

import argparse
import itertools
import json
import math
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import mock_open, patch

from artifact_pipeline.generate_play_table import (
    AnalyticalContext,
    DEALER,
    DEFAULT_CLIENT_OUTPUT_PATH,
    DEFAULT_OUTPUT_PATH,
    DiscardPolicy,
    PONE,
    _parse_args,
    _representative_physical_hand,
    _sample_target_deal,
    _write_json,
    build_client_table,
    generate_play_table,
    main,
    maximum_play_shift,
    positive_float,
    play_values_from_table,
    positive_int,
    refine_discard_policy,
    sample_opponent_keep,
    sample_policy_deal,
    selected_discards_to_policy,
    solve_initial_discard_policy,
    validate_resume_table,
)
from artifact_pipeline.analytical_solver import (
    _select_discard_indices,
    get_analytical_pairs,
)
from artifact_pipeline.pegging import canonical_hand_key, get_canonical_hands


class FirstPolicy:  # pylint: disable=too-few-public-methods
    def select_rank(self, view, rng):
        del rng
        return view.legal_ranks[0]


def all_first_four_policy():
    mapping = {}
    for hand in itertools.combinations_with_replacement(range(13), 6):
        if max(hand.count(rank) for rank in set(hand)) > 4:
            continue
        for role in (PONE, DEALER):
            mapping[(role, hand)] = hand[:4]
    return DiscardPolicy(mapping)


class TestGeneratePlayTable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.discard_policy = all_first_four_policy()
        cls.play_policies = {PONE: FirstPolicy(), DEALER: FirstPolicy()}

    def test_selected_discards_to_policy_and_physical_keep(self):
        policy = selected_discards_to_policy([((0, 1, 2, 3, 4, 5), 1, 2)])
        self.assertEqual(policy.kept_ranks(DEALER, (0, 1, 2, 3, 4, 5)), (2, 3, 4, 5))
        self.assertEqual(policy.kept_ranks(PONE, (0, 1, 2, 3, 4, 5)), (1, 3, 4, 5))
        cards = tuple((rank, 0) for rank in range(6))
        self.assertEqual(
            [card[0] for card in policy.keep_physical_cards(DEALER, cards)],
            [2, 3, 4, 5],
        )
        with self.assertRaises(ValueError):
            policy.kept_ranks(PONE, (0, 0, 0, 0, 0, 0))

    def test_solve_initial_discard_policy(self):
        solved = (
            [1.0],
            [2.0],
            [((0, 1, 2, 3, 4, 5), 1, {0: 3.0})],
            {(0, 0): {0: 4.0}},
            [[1.0] * 13],
            [[2.0] * 13],
        )
        selected = [((0, 1, 2, 3, 4, 5), 0, 0)]
        with patch(
            "artifact_pipeline.generate_play_table.run_analytical_ibr",
            return_value=solved,
        ), patch(
            "artifact_pipeline.generate_play_table._select_discard_indices",
            return_value=selected,
        ):
            context = solve_initial_discard_policy(2, 1)
        self.assertEqual(context.selected_discards, selected)
        self.assertEqual(context.dealer_table, [1.0])

    def test_analytical_discard_selection_can_add_play_values(self):
        hand = (0, 1, 2, 3, 4, 5)
        dealer_selected = _select_discard_indices(
            [(hand, 1, {1: 0.0, 2: 0.0})],
            [0.0] * 91,
            [0.0] * 91,
            dealer_play_values={(1, 3, 4, 5): 2.0},
        )
        pone_selected = _select_discard_indices(
            [(hand, 1, {1: 0.0, 2: 0.0})],
            [0.0] * 91,
            [0.0] * 91,
            pone_play_values={(2, 3, 4, 5): 3.0},
        )
        explicit_pairs_selected = _select_discard_indices(
            [(hand, 1, {1: 0.0, 2: 0.0})],
            [0.0] * 91,
            [0.0] * 91,
            analytical_pairs=get_analytical_pairs(),
            dealer_play_values={(1, 3, 4, 5): 2.0},
        )
        self.assertEqual(dealer_selected, [(hand, 2, 1)])
        self.assertEqual(pone_selected, [(hand, 1, 1)])
        self.assertEqual(explicit_pairs_selected, [(hand, 2, 1)])

    def test_policy_deal_and_conditioned_opponent_keep(self):
        pone, dealer = sample_policy_deal(random.Random(42), self.discard_policy)
        self.assertEqual(len(pone), 4)
        self.assertEqual(len(dealer), 4)
        target_deal = _sample_target_deal((0, 1, 2, 3), random.Random(42))
        self.assertEqual(len(target_deal), 6)
        self.assertEqual(tuple(card[0] for card in target_deal[:4]), (0, 1, 2, 3))
        opponent = sample_opponent_keep(
            (0, 0, 0, 0), DEALER, self.discard_policy, random.Random(42)
        )
        self.assertEqual(len(opponent), 4)
        self.assertEqual(opponent.count(0), 0)
        self.assertEqual(
            _representative_physical_hand((0, 0, 2, 2)),
            ((0, 0), (0, 1), (2, 0), (2, 1)),
        )

    def test_opponent_deal_excludes_sampled_target_discards(self):
        class ScriptedRandom:  # pylint: disable=too-few-public-methods
            def __init__(self):
                self.populations = []

            def sample(self, population, count):
                self.populations.append(tuple(population))
                if count == 2:
                    return [(4, 0), (5, 0)]
                return list(population[:count])

        rng = ScriptedRandom()
        sample_opponent_keep((0, 1, 2, 3), DEALER, self.discard_policy, rng)
        opponent_population = rng.populations[1]
        for removed_card in (
            (0, 0),
            (1, 0),
            (2, 0),
            (3, 0),
            (4, 0),
            (5, 0),
        ):
            self.assertNotIn(removed_card, opponent_population)

    def test_generate_full_and_client_table(self):
        table = generate_play_table(
            self.discard_policy,
            self.play_policies,
            samples=2,
            seed=42,
            hands=[(0, 1, 2, 3)],
        )
        self.assertEqual(table["__metadata__"]["hand_count"], 1)
        hand = table["A_2_3_4"]
        for target_role in (PONE, DEALER):
            entry = hand[target_role]
            self.assertEqual(entry["n"], 2)
            target = entry["players"][target_role]["mu"]
            opponent = entry["players"][DEALER if target_role == PONE else PONE]["mu"]
            self.assertAlmostEqual(entry["mu"], target - opponent)
            for player in (PONE, DEALER):
                player_entry = entry["players"][player]
                self.assertAlmostEqual(
                    player_entry["mu"],
                    sum(bucket["mu"] for bucket in player_entry["points"].values()),
                )
        client = build_client_table(table)
        self.assertNotIn("__metadata__", client)
        self.assertEqual(set(client["A_2_3_4"][PONE]), {"mu", "players"})
        self.assertEqual(
            set(client["A_2_3_4"][PONE]["players"][PONE]["points"]),
            {"fifteen", "thirty_one", "pair", "run", "go", "last_card"},
        )

    def test_seeded_generation_is_order_invariant_by_hand_key(self):
        first_hand = (0, 1, 2, 3)
        second_hand = (1, 2, 3, 4)
        forward = generate_play_table(
            self.discard_policy,
            self.play_policies,
            samples=2,
            seed=42,
            hands=[first_hand, second_hand],
        )
        reversed_order = generate_play_table(
            self.discard_policy,
            self.play_policies,
            samples=2,
            seed=42,
            hands=[second_hand, first_hand],
        )
        for hand in (first_hand, second_hand):
            hand_key = canonical_hand_key(hand)
            self.assertEqual(forward[hand_key], reversed_order[hand_key])

    def test_adaptive_sampling_and_generation_validation(self):
        table = generate_play_table(
            self.discard_policy,
            self.play_policies,
            samples=2,
            max_samples=3,
            target_standard_error=0.000001,
            seed=1,
            hands=[(0, 0, 0, 0)],
        )
        self.assertTrue(table["A_A_A_A"][PONE]["n"] in (2, 3))
        early_stop_table = generate_play_table(
            self.discard_policy,
            self.play_policies,
            samples=2,
            max_samples=5,
            target_standard_error=100.0,
            seed=2,
            hands=[(0, 0, 0, 0)],
        )
        self.assertEqual(early_stop_table["A_A_A_A"][PONE]["n"], 2)
        with self.assertRaises(ValueError):
            generate_play_table(
                self.discard_policy, self.play_policies, 0, 1, [(0, 1, 2, 3)]
            )
        with self.assertRaises(ValueError):
            generate_play_table(
                self.discard_policy,
                self.play_policies,
                1,
                1,
                [(0, 1, 2, 3)],
                target_standard_error=0.0,
            )
        with self.assertRaises(ValueError):
            generate_play_table(
                self.discard_policy,
                self.play_policies,
                2,
                1,
                [(0, 1, 2, 3)],
                target_standard_error=0.01,
            )
        with self.assertRaises(ValueError):
            generate_play_table(
                self.discard_policy,
                self.play_policies,
                2,
                1,
                [(0, 1, 2, 3)],
                max_samples=1,
            )
        with self.assertRaises(ValueError):
            generate_play_table(
                self.discard_policy,
                self.play_policies,
                1,
                1,
                [(0, 1, 2, 3)],
                checkpoint_frequency=0,
            )

    def test_seeded_resume_matches_fresh_generation(self):
        checkpoints = []
        partial_table = generate_play_table(
            self.discard_policy,
            self.play_policies,
            samples=2,
            seed=42,
            hands=[(0, 1, 2, 3)],
            checkpoint=lambda table: checkpoints.append(json.loads(json.dumps(table))),
        )
        resumed = generate_play_table(
            self.discard_policy,
            self.play_policies,
            samples=4,
            seed=42,
            hands=[(0, 1, 2, 3)],
            existing_table=partial_table,
        )
        fresh = generate_play_table(
            self.discard_policy,
            self.play_policies,
            samples=4,
            seed=42,
            hands=[(0, 1, 2, 3)],
        )
        self.assertEqual(resumed["A_2_3_4"], fresh["A_2_3_4"])
        self.assertEqual(len(checkpoints), 1)
        invalid_method = {"__metadata__": {"generation_method": "old", "seed": 42}}
        with self.assertRaises(ValueError):
            validate_resume_table(invalid_method, 42)
        invalid_seed = {
            "__metadata__": {
                "generation_method": "artifact_pipeline.generate_play_table.v2",
                "seed": 1,
            }
        }
        with self.assertRaises(ValueError):
            validate_resume_table(invalid_seed, 42)
        invalid_policy = {
            "__metadata__": {
                "generation_method": "artifact_pipeline.generate_play_table.v2",
                "seed": 42,
                "policy_fingerprint": "old",
            }
        }
        with self.assertRaises(ValueError):
            validate_resume_table(invalid_policy, 42, "new")

    def test_play_values_and_maximum_shift(self):
        table = {
            "__metadata__": {},
            "A_2_3_4": {
                PONE: {"mu": -1.0},
                DEALER: {"mu": 2.0},
            },
        }
        dealer, pone = play_values_from_table(table)
        self.assertEqual(dealer[(0, 1, 2, 3)], 2.0)
        self.assertEqual(pone[(0, 1, 2, 3)], -1.0)
        self.assertTrue(math.isinf(maximum_play_shift(None, table)))
        changed = {
            **table,
            "A_2_3_4": {
                PONE: {"mu": -0.5},
                DEALER: {"mu": 2.25},
            },
        }
        self.assertEqual(maximum_play_shift(table, changed), 0.5)

    def test_refine_discard_policy(self):
        context = AnalyticalContext(
            dealer_table=[1.0],
            pone_table=[2.0],
            hand_kept_evs=[((0, 1, 2, 3, 4, 5), 1, {0: 3.0})],
            crib_scores={(0, 0): {rank: 4.0 for rank in range(13)}},
            dealer_cut_table=[[1.0] * 13],
            pone_cut_table=[[2.0] * 13],
            selected_discards=[((0, 1, 2, 3, 4, 5), 0, 0)],
        )
        table = {
            "__metadata__": {},
            "A_2_3_4": {PONE: {"mu": -1.0}, DEALER: {"mu": 1.0}},
        }
        full_table = {"__metadata__": {}}
        for hand in get_canonical_hands():
            full_table[canonical_hand_key(hand)] = {
                PONE: {"mu": 0.0},
                DEALER: {"mu": 0.0},
            }
        selected = [((0, 1, 2, 3, 4, 5), 1, 0)]
        with patch(
            "artifact_pipeline.generate_play_table._select_discard_indices",
            return_value=selected,
        ) as select_mock, patch(
            "artifact_pipeline.generate_play_table._expected_crib_tables",
            return_value=([1.5], [1.75]),
        ), patch(
            "artifact_pipeline.generate_play_table._expected_crib_cut_tables",
            return_value=([[1.5] * 13], [[1.75] * 13]),
        ):
            refined, changed, shift = refine_discard_policy(context, table)
            # A partial table skips play values; a complete one folds them in.
            self.assertIsNone(select_mock.call_args.kwargs["dealer_play_values"])
            refine_discard_policy(context, full_table)
            self.assertIsNotNone(select_mock.call_args.kwargs["dealer_play_values"])
        self.assertEqual(refined.selected_discards, selected)
        self.assertEqual(changed, 1)
        self.assertEqual(shift, 0.5)

    def test_argument_helpers_and_json_writer(self):
        self.assertEqual(positive_int("2"), 2)
        with self.assertRaises(argparse.ArgumentTypeError):
            positive_int("0")
        self.assertEqual(positive_float("0.2"), 0.2)
        for value in ("0", "-1", "nan"):
            with self.assertRaises(argparse.ArgumentTypeError):
                positive_float(value)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "table.json"
            _write_json(str(path), {"b": 1, "a": 2})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")), {"a": 2, "b": 1}
            )
            compact_path = Path(directory) / "compact.json"
            _write_json(str(compact_path), {"b": 1, "a": 2}, compact=True)
            self.assertEqual(
                compact_path.read_text(encoding="utf-8"), '{"a":2,"b":1}\n'
            )

    def test_parse_args_defaults_and_overrides(self):
        with patch("sys.argv", ["generate_play_table.py"]):
            args = _parse_args()
        self.assertEqual(args.output, DEFAULT_OUTPUT_PATH)
        self.assertEqual(args.client_output, DEFAULT_CLIENT_OUTPUT_PATH)
        with patch(
            "sys.argv",
            [
                "generate_play_table.py",
                "--samples=2",
                "--max-samples=3",
                "--target-standard-error=0.2",
                "--hand-limit=1",
                "--fail-on-non-convergence",
            ],
        ):
            args = _parse_args()
        self.assertEqual(args.samples, 2)
        self.assertTrue(args.fail_on_non_convergence)

    def test_main_smoke_with_bounded_dependencies(self):
        args = argparse.Namespace(
            output="full.json",
            client_output="client.json",
            samples=1,
            max_samples=None,
            target_standard_error=None,
            seed=42,
            ibr_iterations=1,
            ibr_samples=1,
            rollouts_per_action=1,
            outer_iterations=3,
            policy_table_samples=1,
            analytical_max_iterations=1,
            full_hand_policy_max_iterations=1,
            hand_limit=1,
            fail_on_non_convergence=False,
            no_resume=False,
            checkpoint_frequency=1,
        )
        context = AnalyticalContext(
            dealer_table=[1.0],
            pone_table=[1.0],
            hand_kept_evs=[],
            crib_scores={},
            dealer_cut_table=[],
            pone_cut_table=[],
            selected_discards=[((0, 0, 0, 0, 1, 1), 0, 0)],
        )
        table = {
            "__metadata__": {},
            "A_A_A_A": {
                PONE: {"mu": 0.0, "players": {}},
                DEALER: {"mu": 0.0, "players": {}},
            },
        }

        def generate_with_checkpoint(*_args, **kwargs):
            if "checkpoint" in kwargs:
                kwargs["checkpoint"](table)
            return table

        checkpoint_json = json.dumps(
            {
                "__metadata__": {
                    "generation_method": "artifact_pipeline.generate_play_table.v2",
                    "seed": 42,
                }
            }
        )
        with patch(
            "artifact_pipeline.generate_play_table._parse_args", return_value=args
        ), patch(
            "artifact_pipeline.generate_play_table.solve_initial_discard_policy",
            return_value=context,
        ), patch(
            "artifact_pipeline.generate_play_table.selected_discards_to_policy",
            return_value=self.discard_policy,
        ), patch(
            "artifact_pipeline.generate_play_table.train_iterative_best_response",
            return_value=(self.play_policies, []),
        ), patch(
            "artifact_pipeline.generate_play_table.generate_play_table",
            side_effect=generate_with_checkpoint,
        ), patch(
            "artifact_pipeline.generate_play_table.refine_discard_policy",
            return_value=(context, 0, 0.0),
        ), patch(
            "artifact_pipeline.generate_play_table.build_client_table",
            return_value={"A_A_A_A": {}},
        ), patch(
            "artifact_pipeline.generate_play_table._write_json"
        ) as write_json, patch(
            "builtins.print"
        ), patch(
            "artifact_pipeline.generate_play_table.os.path.exists",
            side_effect=(True, False),
        ), patch(
            "builtins.open", mock_open(read_data=checkpoint_json)
        ):
            main()
            main()
        self.assertEqual(write_json.call_count, 8)

    def test_main_can_fail_on_non_convergence_without_hand_limit(self):
        args = argparse.Namespace(
            output="full.json",
            client_output="client.json",
            samples=1,
            max_samples=None,
            target_standard_error=None,
            seed=42,
            ibr_iterations=1,
            ibr_samples=1,
            rollouts_per_action=1,
            outer_iterations=1,
            policy_table_samples=1,
            analytical_max_iterations=1,
            full_hand_policy_max_iterations=1,
            hand_limit=None,
            fail_on_non_convergence=True,
            no_resume=False,
            checkpoint_frequency=1,
        )
        context = AnalyticalContext(
            dealer_table=[1.0],
            pone_table=[1.0],
            hand_kept_evs=[],
            crib_scores={},
            dealer_cut_table=[],
            pone_cut_table=[],
            selected_discards=[((0, 0, 0, 0, 1, 1), 0, 0)],
        )
        with patch(
            "artifact_pipeline.generate_play_table._parse_args", return_value=args
        ), patch(
            "artifact_pipeline.generate_play_table.solve_initial_discard_policy",
            return_value=context,
        ), patch(
            "artifact_pipeline.generate_play_table.selected_discards_to_policy",
            return_value=self.discard_policy,
        ), patch(
            "artifact_pipeline.generate_play_table.train_iterative_best_response",
            return_value=(self.play_policies, []),
        ), patch(
            "artifact_pipeline.generate_play_table.generate_play_table",
            return_value={
                "__metadata__": {},
                "A_A_A_A": {PONE: {"mu": 0.0}, DEALER: {"mu": 0.0}},
            },
        ), patch(
            "artifact_pipeline.generate_play_table.refine_discard_policy",
            return_value=(context, 1, 1.0),
        ):
            with self.assertRaises(RuntimeError):
                main()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
