"""Independent whole-game physical oracle for conditional second-card choices."""

from collections import Counter
from contextlib import redirect_stdout
import importlib
import io
from itertools import combinations, combinations_with_replacement
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    LegacyHeuristicPolicy,
    TabularPeggingPolicy,
    policy_fingerprint,
    simulate_pegging,
)

second = importlib.import_module("scratch.exact_second_card")
exact = second.exact
dealer = second.dealer_book


def write_parents(directory):
    """Create tiny exact frozen parents, including non-empty reply entries."""
    hands = list(combinations_with_replacement(range(3), 4))
    pone_rows = [exact.exact_pone_hand((h, 3)) for h in hands]
    pone_policy = exact.build_pone(pone_rows)
    pone = {
        "hands": pone_rows,
        "evidence_sha256": exact.book.evidence_digest(pone_rows),
        "policy_fingerprint": policy_fingerprint(pone_policy),
    }
    choices = dealer.opening_choices(pone_rows)
    dealer_rows = [dealer.exact_dealer_hand((h, choices, 3)) for h in hands]
    reply = {
        "hands": dealer_rows,
        "evidence_sha256": exact.book.evidence_digest(dealer_rows),
        "policy_fingerprint": policy_fingerprint(dealer.build_dealer(dealer_rows)),
        "pone_policy_fingerprint": pone["policy_fingerprint"],
    }
    paths = tuple(str(Path(directory) / name) for name in ("pone.json", "dealer.json"))
    for path, report in zip(paths, (pone, reply)):
        Path(path).write_text(json.dumps(report), encoding="utf-8")
    return paths


def physical_second_oracle(test, own, parents, cells):
    """Enumerate distinct physical draws in complete games, independently of weights."""
    totals, weights = {}, Counter()
    pool = (card for card in range(12) if card not in (0, 1, 4, 8))
    for draw in combinations(pool, 4):
        opponent = tuple(sorted(card // 4 for card in draw))
        result = simulate_pegging(
            own, opponent, parents, random.Random(0), collect_decisions=True
        )
        decision = next(
            d
            for d in result.decisions
            if d.view.role == PONE and len(d.view.own_remaining) == 3
        )
        key = decision.view.key()
        test.assertTrue(key in cells)
        weights[key] += 1
        for rank in decision.view.legal_ranks:
            actions = dict(parents[PONE].actions)
            actions[key] = rank
            value = simulate_pegging(
                own,
                opponent,
                {PONE: TabularPeggingPolicy(actions), DEALER: parents[DEALER]},
                random.Random(0),
            ).delta(PONE)
            totals.setdefault(key, Counter())[rank] += int(value)
    return totals, weights


def physical_installed_total(own, parents, candidate):
    """Measure the installed non-empty second-card book in complete real games."""
    pool = (card for card in range(12) if card not in (0, 1, 4, 8))
    return sum(
        int(
            simulate_pegging(
                own,
                tuple(sorted(card // 4 for card in draw)),
                {PONE: candidate, DEALER: parents[DEALER]},
                random.Random(0),
            ).delta(PONE)
        )
        for draw in combinations(pool, 4)
    )


class TestSecondCard(unittest.TestCase):
    def test_conditional_gains_match_whole_game_physical_oracle(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = write_parents(directory)
            own = (0, 0, 1, 2)
            row = second.exact_second_hand((own, *paths, 3))
            _, _, parents = second.frozen_books(*paths)
            cells = {c["view_key"]: c for c in row["replies"]}
            totals, weights = physical_second_oracle(self, own, parents, cells)
            self.assertEqual(row["weight"], 70)
            self.assertEqual({k: c["weight"] for k, c in cells.items()}, weights)
            for key, cell in cells.items():
                baseline = totals[key][cell["heuristic_second"]]
                self.assertEqual(
                    {v["rank"]: v["gain_sum"] for v in cell["candidates"]},
                    {r: n - baseline for r, n in totals[key].items()},
                )
            candidate = second.build_second([row], parents[PONE])
            self.assertTrue(
                all(candidate.actions[k] == v for k, v in parents[PONE].actions.items())
            )
            self.assertEqual(candidate.fallback, LegacyHeuristicPolicy())
            self.assertEqual(
                physical_installed_total(own, parents, candidate),
                sum(
                    totals[key][
                        (
                            cell["override"]
                            if cell["override"] is not None
                            else cell["heuristic_second"]
                        )
                    ]
                    for key, cell in cells.items()
                ),
            )
            self.assertEqual(
                exact.enumerate_jobs(
                    [(own, *paths, 3)], "second", 2, second.exact_second_hand
                ),
                [row],
            )

    def test_forced_second_cards_are_not_enumerated(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = write_parents(directory)
            row = second.exact_second_hand(((0, 0, 0, 0), *paths, 3))
            self.assertEqual(row["simulations"], 0)
            self.assertTrue(
                all(
                    not c["candidates"] and c["override"] is None
                    for c in row["replies"]
                )
            )

    def test_parent_integrity_and_conditional_mass_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = write_parents(directory)
            with patch.object(
                exact, "opponent_hands", return_value=iter([((1, 1, 2, 2), 1)])
            ):
                with self.assertRaisesRegex(ValueError, "partition"):
                    second.exact_second_hand(((0, 0, 1, 2), *paths, 3))
            source = json.loads(Path(paths[1]).read_text(encoding="utf-8"))
            for field, message in (
                ("evidence_sha256", "digest"),
                ("policy_fingerprint", "fingerprint"),
                ("pone_policy_fingerprint", "different"),
            ):
                broken = dict(source, **{field: "wrong"})
                bad = Path(directory) / (field + ".json")
                bad.write_text(json.dumps(broken), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    second.frozen_books(paths[0], str(bad))

    def test_bounded_cli_and_paired_marginal_in_real_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = write_parents(directory)
            row = second.exact_second_hand(((0, 0, 1, 2), *paths, 3))
            output = Path(directory) / "result.json"
            argv = [
                "second",
                "--pone",
                paths[0],
                "--dealer",
                paths[1],
                "--output",
                str(output),
                "--workers",
                "1",
                "--gate-deals",
                "1000",
            ]
            with patch("sys.argv", argv), patch.object(
                exact, "enumerate_jobs", return_value=[row]
            ), redirect_stdout(io.StringIO()):
                second.main()
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["paired_marginal_gate"][DEALER]["mu"], 0)
            self.assertEqual(report["summary"]["epsilon_zero_different_keys"], 0)
            self.assertEqual(
                report["evidence_sha256"], exact.book.evidence_digest([row])
            )
            with patch("sys.argv", argv + ["--workers", "0"]), self.assertRaises(
                SystemExit
            ):
                second.main()


if __name__ == "__main__":
    unittest.main()
