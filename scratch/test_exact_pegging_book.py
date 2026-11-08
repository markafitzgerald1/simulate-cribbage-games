"""Physical enumeration oracles, exact selection and real policy integration."""

from collections import Counter
from fractions import Fraction
import importlib
import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import tempfile
from types import SimpleNamespace
from itertools import combinations
import random
import unittest
from unittest.mock import patch
from artifact_pipeline import promotion_gate

from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    LegacyHeuristicPolicy,
    PeggingState,
    simulate_from_state,
    simulate_pegging,
)

exact = importlib.import_module("scratch.exact_pegging_book")
book = importlib.import_module("scratch.pegging_opening_book")


class TestExactBook(unittest.TestCase):
    def test_physical_oracle_includes_all_draws_and_excludes_removed_cards(self):
        own = (0, 0, 1, 2)
        pool = tuple(card for card in range(12) if card not in (0, 1, 4, 8))
        oracle = Counter(
            tuple(sorted(card // 4 for card in draw)) for draw in combinations(pool, 4)
        )
        weights = dict(exact.opponent_hands(own, ranks=3))
        self.assertEqual(weights, oracle)
        self.assertEqual(sum(weights.values()), 70)
        self.assertNotIn((0, 0, 0, 0), weights)
        self.assertEqual(weights[(0, 0, 1, 1)], 3)
        self.assertEqual(sum(w for _, w in exact.opponent_hands((0, 0, 0, 0))), 194580)
        self.assertEqual(sum(exact.physical_weight(h) for h in exact.HANDS), 270725)

    def test_exact_leads_match_independent_physical_deal_oracle(self):
        own = (0, 0, 1, 2)
        h = LegacyHeuristicPolicy()
        totals = {rank: 0 for rank in set(own)}
        pool = tuple(card for card in range(12) if card not in (0, 1, 4, 8))
        for draw in combinations(pool, 4):
            state = PeggingState(
                {PONE: list(own), DEALER: [card // 4 for card in draw]}
            )
            for rank in totals:
                totals[rank] += int(
                    simulate_from_state(
                        state,
                        {PONE: h, DEALER: h},
                        random.Random(817),
                        forced_rank=rank,
                    ).delta(PONE)
                )
        row = exact.exact_pone_hand((own, 3))
        self.assertEqual(row["weight"], 70)
        self.assertEqual(
            row["simulations"], 3 * len(dict(exact.opponent_hands(own, 3)))
        )
        baseline = totals[row["heuristic_lead"]]
        self.assertEqual({v["rank"]: v["delta_sum"] for v in row["candidates"]}, totals)
        self.assertEqual(
            {v["rank"]: v["gain_sum"] for v in row["candidates"]},
            {r: value - baseline for r, value in totals.items()},
        )

    def test_integer_selection_handles_true_ties_and_epsilon_grid(self):
        candidates = [
            {"rank": 0, "gain_sum": 2**60},
            {"rank": 1, "gain_sum": 2**60 + 1},
            {"rank": 2, "gain_sum": 0},
        ]
        self.assertEqual(exact.choose_override(candidates, 2, 194580), 1)
        candidates[1]["gain_sum"] = 2**60
        self.assertEqual(exact.choose_override(candidates, 2, 194580), 0)
        self.assertIsNone(exact.choose_override([{"rank": 0, "gain_sum": 0}], 0, 70))
        self.assertIsNone(exact.choose_override([{"rank": 0, "gain_sum": -1}], 1, 70))
        self.assertEqual(
            exact.choose_override([{"rank": 0, "gain_sum": 1}], 1, 194580), 0
        )
        self.assertLess(exact.EPSILON, Fraction(1, 194580))
        self.assertIsNone(exact.choose_override(candidates, 2, 0))

    def test_policy_key_matches_real_state_and_fires_in_complete_game(self):
        own, opponent = (0, 0, 1, 8), (0, 1, 1, 2)
        policy = book.build_policy([{"hand": list(own), "override": 0}])
        state = PeggingState({PONE: list(own), DEALER: list(opponent)})
        self.assertEqual(book.opening_view(own), state.view())
        h = LegacyHeuristicPolicy()
        reference = simulate_pegging(
            own, opponent, {PONE: h, DEALER: h}, random.Random(42)
        )
        result = simulate_pegging(
            own, opponent, {PONE: policy, DEALER: h}, random.Random(42)
        )
        self.assertEqual(reference.opening[0], 1)
        self.assertEqual(result.opening[0], 0)
        # Opening trace proves the table fired; all subsequent choices still fall back.
        self.assertNotEqual(result.opening, reference.opening)

    def test_nonempty_book_fires_inside_real_promotion_gate(self):
        own, opponent = (0, 0, 1, 8), (0, 0, 1, 1)
        policy = book.build_policy([{"hand": list(own), "override": 0}])
        with patch.object(
            promotion_gate, "gate_deals", return_value=[(own, opponent, 42)] * 1000
        ):
            report = promotion_gate.evaluate_promotion(
                {PONE: policy, DEALER: LegacyHeuristicPolicy()}, 1000, 42
            )
        self.assertEqual(report[PONE], {"n": 1000, "mu": -2, "se": 0})
        self.assertEqual(report[DEALER], {"n": 1000, "mu": 0, "se": 0})
        self.assertEqual(report["both_seats"], {"n": 1000, "mu": -1, "se": 0})

    def test_dealer_conditioning_matches_whole_game_physical_oracle(self):
        dealer = importlib.import_module("scratch.exact_dealer_book")
        own = (0, 0, 1, 2)
        choices = {h: max(h) for h, _ in exact.opponent_hands(own, 3)}
        pone_policy = book.build_policy(
            [{"hand": list(h), "override": r} for h, r in choices.items()]
        )
        row = dealer.exact_dealer_hand((own, choices, 3))
        totals = {}
        weights = Counter()
        for draw in combinations(
            (card for card in range(12) if card not in (0, 1, 4, 8)), 4
        ):
            pone = tuple(sorted(card // 4 for card in draw))
            lead = choices[pone]
            weights[lead] += 1
            reference = simulate_pegging(
                pone,
                own,
                {PONE: pone_policy, DEALER: LegacyHeuristicPolicy()},
                random.Random(42),
                collect_decisions=True,
            )
            decision = next(d for d in reference.decisions if d.view.role == DEALER)
            self.assertTrue(lead in [c["lead"] for c in row["leads"]])
            self.assertEqual(
                next(c["view_key"] for c in row["leads"] if c["lead"] == lead),
                decision.view.key(),
            )
            for rank in set(own):
                totals.setdefault(lead, Counter())[rank] += int(
                    simulate_pegging(
                        pone,
                        own,
                        {
                            PONE: pone_policy,
                            DEALER: exact.TabularPeggingPolicy(
                                {decision.view.key(): rank}
                            ),
                        },
                        random.Random(42),
                    ).delta(DEALER)
                )
        self.assertEqual(row["weight"], 70)
        self.assertEqual({c["lead"]: c["weight"] for c in row["leads"]}, weights)
        for cell in row["leads"]:
            self.assertEqual(
                {c["rank"]: c["delta_sum"] for c in cell["candidates"]},
                totals[cell["lead"]],
            )
        self.assertEqual(dealer.build_dealer([row]).fallback, LegacyHeuristicPolicy())
        self.assertEqual(
            exact.enumerate_jobs(
                [(own, choices, 3)], "dealer", 1, dealer.exact_dealer_hand
            ),
            exact.enumerate_jobs(
                [(own, choices, 3)], "dealer", 2, dealer.exact_dealer_hand
            ),
        )

    def test_pair_refinements_are_report_only_and_exact(self):
        analysis = importlib.import_module("scratch.exact_book_analysis")
        rows = [
            {
                "hand": [4, 4, 8, 9],
                "heuristic_lead": 9,
                "own_weight": 96,
                "candidates": [
                    {"rank": 4, "gain_sum": -100},
                    {"rank": 8, "gain_sum": 0},
                    {"rank": 9, "gain_sum": 0},
                ],
            },
            {
                "hand": [0, 5, 5, 9],
                "heuristic_lead": 0,
                "own_weight": 96,
                "candidates": [
                    {"rank": 0, "gain_sum": 0},
                    {"rank": 5, "gain_sum": 140},
                    {"rank": 9, "gain_sum": 70},
                ],
            },
        ]
        self.assertEqual(analysis.pair_choice(rows[0], range(1, 11)), 4)
        self.assertEqual(analysis.pair_choice(rows[0], [6, 7, 8, 9, 10]), 9)
        self.assertEqual(analysis.pair_choice(rows[1], [6], ("le", 1)), 5)
        self.assertEqual(analysis.pair_choice(rows[1], [6], ("gt", 1)), 0)
        self.assertEqual(
            analysis.rule_score(rows, range(1, 11)),
            Fraction(3840, exact.POPULATION_WEIGHT),
        )
        report = analysis.pair_analysis(rows)
        self.assertEqual(report["paired_keys"], 2)
        self.assertEqual(report["pair_is_one_exact_best_keys"], 1)
        self.assertEqual(report["candidate_rules"], 1365)
        self.assertEqual(
            report["best_interval"]["gain_vs_heuristic"]["mu"],
            float(Fraction(13440, exact.POPULATION_WEIGHT)),
        )

    def test_exact_guards_reject_wrong_weight_randomness_and_fractional_points(self):
        job = ((0, 0, 1, 2), 3)
        with patch.object(
            exact, "opponent_hands", return_value=[((1, 1, 2, 2), 1)]
        ), self.assertRaises(ValueError):
            exact.exact_pone_hand(job)
        with self.assertRaises(ValueError):
            exact.integer_delta(SimpleNamespace(delta=lambda _role: 0.5), PONE)
        original = exact.simulate_from_state

        def randomizing(state, policies, rng, **kwargs):
            rng.random()
            return original(state, policies, rng, **kwargs)

        with patch.object(
            exact, "simulate_from_state", side_effect=randomizing
        ), self.assertRaises(ValueError):
            exact.exact_pone_hand(job)
        with patch.object(
            book, "rollout_leads", return_value={0: 0.5, 1: 0}
        ), self.assertRaises(ValueError):
            book.train_hand(((0, 1, 1, 1), 2, 42))

    def test_exact_cli_and_frozen_input_hash_guards(self):
        dealer = importlib.import_module("scratch.exact_dealer_book")
        analysis = importlib.import_module("scratch.exact_book_analysis")
        original = exact.checks.read_book(
            Path(book.__file__).with_name("issue187_pone_opening_book.json")
        )
        original["hands"] = [
            r for r in original["hands"] if r["key"] in ("A_A_2_9", "A_A_A_A")
        ]
        original["policy_fingerprint"] = exact.policy_fingerprint(
            book.build_policy(original["hands"])
        )
        original["evidence_sha256"] = book.evidence_digest(original["hands"])
        rows = [
            exact.exact_pone_hand((tuple(r["hand"]), 13)) for r in original["hands"]
        ]
        with tempfile.TemporaryDirectory() as directory:
            source, pone, replies, rules = [
                Path(directory, n + ".json")
                for n in ("source", "pone", "dealer", "rules")
            ]
            source.write_text(json.dumps(original))
            arguments = [
                "exact",
                "pone",
                "--sampled=" + str(source),
                "--output=" + str(pone),
                "--workers=1",
                "--gate-deals=1000",
            ]
            with patch("sys.argv", arguments), patch.object(
                exact, "enumerate_jobs", return_value=rows
            ), redirect_stdout(io.StringIO()):
                exact.main()
            frozen = dealer.read_pone(pone)
            self.assertEqual(frozen["summary"]["keys"], 2)
            self.assertEqual(frozen["sampled_gate"][PONE]["n"], 1000)
            with patch(
                "sys.argv",
                ["analysis", "--book=" + str(pone), "--output=" + str(rules)],
            ), redirect_stdout(io.StringIO()):
                analysis.main()
            fixture = dealer.exact_dealer_hand(
                (
                    (0, 0, 1, 2),
                    {h: min(h) for h, _ in exact.opponent_hands((0, 0, 1, 2), 3)},
                    3,
                )
            )
            with patch(
                "sys.argv",
                [
                    "dealer",
                    "--pone=" + str(pone),
                    "--output=" + str(replies),
                    "--workers=1",
                    "--gate-deals=1000",
                ],
            ), patch.object(
                exact, "enumerate_jobs", return_value=[fixture]
            ), redirect_stdout(
                io.StringIO()
            ):
                dealer.main()
            self.assertEqual(
                json.loads(replies.read_bytes())["combined_gate"][PONE]["n"], 1000
            )
            for field in ("evidence_sha256", "policy_fingerprint"):
                pone.write_text(json.dumps({**frozen, field: "bad"}))
                with self.assertRaises(ValueError):
                    dealer.read_pone(pone)
            with patch("sys.argv", arguments + ["--workers=0"]), redirect_stderr(
                io.StringIO()
            ), self.assertRaises(SystemExit):
                exact.main()
            with patch(
                "sys.argv",
                [
                    "dealer",
                    "--pone=" + str(pone),
                    "--output=" + str(replies),
                    "--gate-deals=999",
                ],
            ), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                dealer.main()
            pone.write_text(json.dumps({**frozen, "evidence_sha256": "bad"}))
            with patch(
                "sys.argv",
                ["analysis", "--book=" + str(pone), "--output=" + str(rules)],
            ), self.assertRaises(ValueError):
                analysis.main()

    def test_pool_preserves_every_result_across_progress_boundary(self):
        jobs = [((0, 0, 1, 2), 3)] * 100
        with redirect_stderr(io.StringIO()) as output:
            rows = exact.enumerate_jobs(jobs, "pone", 2)
        self.assertEqual(len(rows), 100)
        self.assertTrue(all(row == rows[0] for row in rows))
        self.assertTrue("100/100" in output.getvalue())

    def test_pone_pool_schedule_and_deterministic_continuations(self):
        jobs = [((0, 0, 1, 2), 3), ((0, 1, 2, 2), 3)]
        self.assertEqual(
            exact.enumerate_jobs(jobs, "pone", 1), exact.enumerate_jobs(jobs, "pone", 2)
        )
        with self.assertRaises(ValueError):
            exact.enumerate_jobs(jobs, "pone", 0)
        h = LegacyHeuristicPolicy()
        state = PeggingState({PONE: [0, 0, 1, 8], DEALER: [0, 1, 1, 2]})
        rng = random.Random(42)
        before = rng.getstate()
        reference = simulate_from_state(state, {PONE: h, DEALER: h}, rng)
        self.assertEqual(rng.getstate(), before)
        self.assertEqual(
            reference,
            simulate_from_state(state, {PONE: h, DEALER: h}, random.Random(99)),
        )


if __name__ == "__main__":
    unittest.main()
