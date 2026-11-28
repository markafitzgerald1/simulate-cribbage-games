"""Physical posterior oracles, paired scoring and fallback-population provenance."""

from collections import Counter
from contextlib import redirect_stdout
import importlib
import io
from itertools import combinations
import json
from pathlib import Path
from types import SimpleNamespace
import random
import tempfile
import unittest
from unittest.mock import patch

from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    LegacyHeuristicPolicy,
    TabularPeggingPolicy,
    simulate_pegging,
    policy_fingerprint,
)
from artifact_pipeline.promotion_gate import evaluate_promotion, gate_deals

product = importlib.import_module("scratch.book_product_checks")
population = importlib.import_module("scratch.book_keep_population")
fixtures = importlib.import_module("scratch.test_pegging_depth_cost")


def physical_full_gain(own, opponent, cell, prefix):
    """Compare two forced second plays inside complete actual games."""
    parents, lead = prefix
    hr = cell["reply"]
    key = product.second.second_state(own, opponent, lead, hr).view().key()
    actions = dict(parents[PONE].actions)
    values = []
    for rank in (cell["override"], cell["heuristic_second"]):
        actions[key] = rank
        values.append(
            simulate_pegging(
                own,
                opponent,
                {
                    PONE: TabularPeggingPolicy(dict(actions)),
                    DEALER: LegacyHeuristicPolicy(),
                },
                random.Random(0),
            ).delta(PONE)
        )
    return int(values[0] - values[1])


def physical_posterior_oracle(cell, row, own, parents):
    """Enumerate physical draws independently of the production rank weights."""
    mass = Counter()
    gains = 0
    for draw in combinations((c for c in range(12) if c not in (0, 1, 4, 8)), 4):
        opponent = tuple(sorted(c // 4 for c in draw))
        lead = row["lead"]
        first = product.second.dealer_book.after_lead_state(opponent, own, lead).view()
        br = parents[DEALER].select_rank(first, random.Random(0))
        hr = LegacyHeuristicPolicy().select_rank(first, random.Random(0))
        if br == cell["reply"]:
            mass["book"] += 1
        if hr != cell["reply"]:
            continue
        mass["heuristic"] += 1
        mass["intersection"] += br == hr
        gains += physical_full_gain(own, opponent, cell, (parents, lead))
    return mass, gains


class TestProductChecks(unittest.TestCase):
    def test_physical_posterior_and_payoff_oracle(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = fixtures.write_frozen(directory)
            source, parents, _ = product.load_books(paths)
            own = (0, 0, 1, 2)
            row = next(r for r in source["hands"] if tuple(r["hand"]) == own)
            report = product.transfer_hand((row, paths, 3))
            cell = report["cells"][0]
            self.assertTrue(cell["override"] is not None)
            mass, gains = physical_posterior_oracle(cell, row, own, parents)
            self.assertEqual(cell["weight"], mass["book"])
            self.assertEqual(cell["heuristic_weight"], mass["heuristic"])
            self.assertEqual(cell["intersection_weight"], mass["intersection"])
            self.assertEqual(cell["heuristic_gain_sum"], gains)
            summary = product.transfer_summary([report])
            self.assertAlmostEqual(
                summary["frequency_contribution_to_gap"]
                + summary["posterior_contribution_to_gap"],
                summary["exact_gain_book_dealer"]["mu"]
                - summary["exact_gain_heuristic_dealer"]["mu"],
            )

    def test_posterior_overlap_known_finite_populations(self):
        cells = []
        for b, h, i, g in ((10, 10, 10, 2), (10, 20, 5, -2), (10, 0, 0, 0)):
            cells.append(
                {
                    "weight": b,
                    "heuristic_weight": h,
                    "intersection_weight": i,
                    "override": 0,
                    "heuristic_gain_sum": g,
                    "candidates": [{"rank": 0, "gain_sum": 2}],
                }
            )
        summary = product.transfer_summary([{"own_weight": 1, "cells": cells}])
        self.assertEqual(cells[0]["total_variation"], 0)
        self.assertEqual(cells[1]["total_variation"], 0.75)
        self.assertIsNone(cells[2]["total_variation"])
        self.assertEqual(summary["heuristic_unsupported_keys"], 1)
        self.assertEqual(summary["heuristic_negative_keys"], 1)

    def test_joint_and_unilateral_reports_match_real_promotion_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = fixtures.write_frozen(directory)
            _, parents, combined = product.load_books(paths)
            report = product.evaluate_policy_comparisons(
                product.matchup_games(parents, combined),
                gate_deals(1000, 42),
                "uniform",
            )
            gate = evaluate_promotion(parents, 1000, 42)
            for seat in (PONE, DEALER, "both_seats"):
                self.assertEqual(
                    report["report_only_gate"]["books12"][seat], gate[seat]
                )
            for name, roles in report["games"].items():
                self.assertAlmostEqual(
                    roles[PONE]["delta"]["mu"], -roles[DEALER]["delta"]["mu"]
                )
                self.assertAlmostEqual(
                    roles[PONE]["delta_difference"]["mu"],
                    -roles[DEALER]["delta_difference"]["mu"],
                )
                if name == "heuristic-both":
                    self.assertEqual(roles[PONE]["points_difference"]["se"], 0)
            fixed = product.evaluate_policy_comparisons(
                product.matchup_games(parents, combined),
                [((0, 0, 0, 1), (0, 1, 1, 1), 0)] * 2,
                "physical scoring fixture",
            )["games"]["books12-both"]
            for role, points, difference in ((PONE, 8, 2), (DEALER, 9, 4)):
                self.assertEqual(fixed[role]["points"]["mu"], points)
                self.assertEqual(fixed[role]["points_difference"]["mu"], difference)
                self.assertEqual(fixed[role]["points_difference"]["se"], 0)

    def test_loadable_maps_match_real_games(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = fixtures.write_frozen(directory)
            _, parents, combined = product.load_books(paths)
            sizes = product.policy_sizes(parents, combined)
            self.assertEqual(sizes["pone-lead"]["entries"], len(parents[PONE].actions))
            self.assertGreater(sizes["dealer-reply"]["gzip_bytes"], 0)
            merged = {**parents[PONE].actions, **parents[DEALER].actions}
            loaded = TabularPeggingPolicy(json.loads(json.dumps(merged)))
            self.assertEqual(
                policy_fingerprint(loaded),
                policy_fingerprint(TabularPeggingPolicy(merged)),
            )
            for pone, dealer, seed in gate_deals(20, 42):
                self.assertEqual(
                    simulate_pegging(
                        pone,
                        dealer,
                        {PONE: loaded, DEALER: loaded},
                        random.Random(seed),
                    ),
                    simulate_pegging(pone, dealer, parents, random.Random(seed)),
                )

    def test_joint_point_differences_are_paired_not_absolute_errors(self):
        heuristic = {r: LegacyHeuristicPolicy() for r in (PONE, DEALER)}
        games = product.matchup_games(heuristic, heuristic)
        report = product.evaluate_policy_comparisons(
            games, gate_deals(1000, 7), "same policies"
        )
        for seats in report["games"].values():
            self.assertGreater(seats[PONE]["points"]["se"], 0)
            self.assertEqual(seats[PONE]["points_difference"]["se"], 0)
        self.assertEqual(report["joint_3a_marginal"][PONE]["delta"]["se"], 0)

    def test_fallback_builder_uses_production_settings_and_verifies_keeps(self):
        generator = population.generator
        context = object()
        kept = {(r, (0, 0, 1, 1, 2, 2)): (0, 1, 2, 2) for r in (PONE, DEALER)}
        policy = generator.DiscardPolicy(kept)

        def fallback(gate, original, args, hands):
            self.assertIs(original, context)
            self.assertEqual(
                (args.outer_iterations, args.policy_table_samples, args.seed),
                (2, 200, 42),
            )
            self.assertEqual(len(hands), 1820)
            gate["discard_refinement"] = {"policy": "legacy-heuristic"}
            return {}, context, False

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "keeps.json"
            with patch.object(
                generator, "solve_initial_discard_policy", return_value=context
            ) as solve, patch.object(
                generator, "heuristic_fallback", side_effect=fallback
            ), patch.object(
                generator, "selected_discards_to_policy", return_value=policy
            ):
                # The real context carries selections; a lightweight fixture does too.

                context = SimpleNamespace(selected_discards=[])
                solve.return_value = context
                report = population.build_population(path)
            solve.assert_called_once_with(40, 2)
            self.assertEqual(population.read_population(path)[1], policy)
            self.assertEqual(report["six_hand_physical_weight_per_role"][PONE], 216)
            broken = json.loads(path.read_text(encoding="utf-8"))
            broken["keeps_sha256"] = "wrong"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "digest"):
                population.read_population(path)

    def test_physical_population_draws_use_actual_twelve_card_deals(self):
        draws = []

        def keep(role, cards):
            draws.append((role, tuple(cards)))
            return tuple(cards[:4])

        policy = SimpleNamespace(keep_physical_cards=keep)
        first = list(population.production_deals(policy, 20, 42))
        replay = list(population.production_deals(policy, 20, 42))
        self.assertEqual(first, replay)
        self.assertEqual(len(set(s for _, _, s in first)), 20)
        for index in range(0, len(draws), 2):
            pone, dealer = draws[index][1], draws[index + 1][1]
            self.assertEqual(len(set(pone + dealer)), 12)
            self.assertEqual(len(pone), 6)
            self.assertEqual(len(dealer), 6)

    def test_report_cli_guards_parent_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = fixtures.write_frozen(directory)
            report = json.loads(Path(paths[2]).read_text(encoding="utf-8"))
            report["policy_fingerprint"] = "wrong"
            bad = Path(directory) / "bad.json"
            bad.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                product.load_books((*paths[:2], str(bad)))
            output = Path(directory) / "sizes.json"
            args = [
                "product",
                "sizes",
                "--pone",
                paths[0],
                "--dealer",
                paths[1],
                "--second",
                paths[2],
                "--output",
                str(output),
            ]
            with patch("sys.argv", args), redirect_stdout(io.StringIO()):
                product.main()
            self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
