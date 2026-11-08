"""Reachability accounting oracles with physical deals and real go/reset histories."""

from collections import Counter
from contextlib import redirect_stdout
from dataclasses import replace
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
    GO_ACTION,
    SEQUENCE_RESET,
    LegacyHeuristicPolicy,
    policy_fingerprint,
    simulate_pegging,
)

cost = importlib.import_module("scratch.pegging_depth_cost")
fixtures = importlib.import_module("scratch.test_exact_second_card")


def write_frozen(directory):
    """Build verified tiny exact policies for all three approved decision layers."""
    paths = fixtures.write_parents(directory)
    _, _, parents = cost.second.frozen_books(*paths)
    rows = [
        cost.second.exact_second_hand((h, *paths, 3))
        for h in combinations_with_replacement(range(3), 4)
    ]
    candidate = cost.second.build_second(rows, parents[PONE])
    report = {
        "hands": rows,
        "evidence_sha256": cost.exact.book.evidence_digest(rows),
        "policy_fingerprint": policy_fingerprint(candidate),
        "pone_policy_fingerprint": policy_fingerprint(parents[PONE]),
        "dealer_policy_fingerprint": policy_fingerprint(parents[DEALER]),
    }
    path = str(Path(directory) / "second.json")
    Path(path).write_text(json.dumps(report), encoding="utf-8")
    return (*paths, path)


def public_support_oracle(own, role, policies, opponents):
    """Build explicit consistent-hand sets from independent physical draw support."""
    oracle = {}
    for opponent in opponents:
        hands = {role: own, cost.other_role(role): opponent}
        result = simulate_pegging(
            hands[PONE],
            hands[DEALER],
            policies,
            random.Random(0),
            collect_decisions=True,
        )
        for trace in result.decisions:
            if trace.view.role == role:
                key = trace.view.key()
                oracle.setdefault(key, [trace.view, set()])[1].add(opponent)
    return oracle


class TestDepthCost(unittest.TestCase):
    def test_joined_table_bytes_match_independent_json_serialization(self):
        view = cost.second.second_state((0, 0, 1, 2), (1, 1, 2, 2), 0, 1).view()
        policy = cost.second.TabularPeggingPolicy({view.key(): 0})
        layers = {
            f"Pone-{number}": cost.serialized_layer(
                [(key, [view, 1])], policy, random.Random(0)
            )
            for number, key in enumerate(("first", "second", "third"), 1)
        }
        for cell in layers.values():
            cell["compact_json_bytes"] = cell["json_entry_bytes"] + 2
        sizes = cost.full_table_sizes(layers)
        expected = json.dumps(
            {"first": 0, "second": 0, "third": 0}, separators=(",", ":")
        )
        self.assertEqual(sizes[PONE]["compact_json_bytes"], len(expected))
        self.assertEqual(sizes[PONE]["entries"], 3)
        self.assertEqual(sizes[DEALER]["compact_json_bytes"], 2)

    def test_original_hand_reconstruction_in_real_go_and_reset_sequences(self):
        rng = random.Random(123)
        policies = {r: LegacyHeuristicPolicy() for r in (PONE, DEALER)}
        seen = Counter()
        for _ in range(300):
            cards = rng.sample(range(52), 8)
            hands = {
                PONE: tuple(sorted(c // 4 for c in cards[:4])),
                DEALER: tuple(sorted(c // 4 for c in cards[4:])),
            }
            result = simulate_pegging(
                hands[PONE], hands[DEALER], policies, rng, collect_decisions=True
            )
            for decision in result.decisions:
                try:
                    recovered = cost.initial_hand(decision.view)
                except ValueError as error:
                    self.fail(f"Valid real public history was rejected: {error}")
                self.assertEqual(recovered, hands[decision.view.role])
                self.assertTrue(len(decision.view.legal_ranks) > 1)
                self.assertTrue(cost.layer_name(decision.view) in cost.LAYERS)
                seen["go"] += GO_ACTION in decision.view.public_history
                seen["reset"] += SEQUENCE_RESET in decision.view.public_history
        self.assertGreater(seen["go"], 0)
        self.assertGreater(seen["reset"], 0)

    def test_rank_support_and_sweep_count_match_physical_draw_oracle(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = write_frozen(directory)
            own = (0, 0, 1, 2)
            policies = cost.frozen_policies(paths)
            draws = combinations((c for c in range(12) if c not in (0, 1, 4, 8)), 4)
            opponents = set(tuple(sorted(c // 4 for c in draw)) for draw in draws)
            for role in (PONE, DEALER):
                row = cost.count_hand((own, role, paths, 3))
                oracle = public_support_oracle(own, role, policies, opponents)
                self.assertEqual(row["rank_deals"], len(opponents))
                self.assertEqual(row["physical_mass"], 70)
                for layer, cell in row["layers"].items():
                    values = [
                        v for v in oracle.values() if cost.layer_name(v[0]) == layer
                    ]
                    self.assertEqual(cell["sets"], len(values))
                    self.assertEqual(
                        cell["consistent_hands"], sum(len(v[1]) for v in values)
                    )
                    self.assertEqual(
                        cell["simulations"],
                        sum(len(v[1]) * len(v[0].legal_ranks) for v in values),
                    )
                    self.assertEqual(
                        cell["support_histogram"],
                        dict(Counter(len(v[1]) for v in values)),
                    )
                timing = cost.benchmark_hand((own, role, paths, 3))
                for layer, cell in row["layers"].items():
                    self.assertEqual(
                        timing["layers"][layer]["simulations"], cell["simulations"]
                    )
                combined = cost.combine_counts([row])
                self.assertEqual(
                    sum(v.get("sets", 0) for v in combined.values()), len(oracle)
                )
                self.assertTrue(
                    all(v.get("compact_json_bytes", 2) > 0 for v in combined.values())
                )

    def test_integrity_and_public_history_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = write_frozen(directory)
            source = json.loads(Path(paths[2]).read_text(encoding="utf-8"))
            for field in (
                "evidence_sha256",
                "policy_fingerprint",
                "dealer_policy_fingerprint",
                "pone_policy_fingerprint",
            ):
                bad = Path(directory) / (field + ".json")
                bad.write_text(
                    json.dumps(dict(source, **{field: "wrong"})), encoding="utf-8"
                )
                with self.assertRaises(ValueError):
                    cost.frozen_policies((*paths[:2], str(bad)))
            view = cost.second.second_state((0, 0, 1, 2), (1, 1, 2, 2), 0, 1).view()
            with self.assertRaisesRegex(ValueError, "Reset"):
                cost.initial_hand(replace(view, public_history=(SEQUENCE_RESET,)))
            with self.assertRaisesRegex(ValueError, "acting"):
                cost.initial_hand(replace(view, role=DEALER))
            with patch.object(cost, "initial_hand", return_value=(0, 0, 0, 0)):
                with self.assertRaisesRegex(ValueError, "disjoint"):
                    cost.count_hand(((0, 0, 1, 2), PONE, paths, 3))

    def test_bounded_cli_both_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = write_frozen(directory)
            output = Path(directory) / "cost.json"
            for mode, worker in (
                ("counts", cost.count_hand),
                ("benchmark", cost.benchmark_hand),
            ):
                rows = [worker(((0, 0, 1, 2), PONE, paths, 3))]
                args = [
                    "cost",
                    mode,
                    "--pone",
                    paths[0],
                    "--dealer",
                    paths[1],
                    "--second",
                    paths[2],
                    "--output",
                    str(output),
                    "--keys",
                    "1",
                    "--workers",
                    "1",
                ]
                with patch("sys.argv", args), patch.object(
                    cost.exact, "enumerate_jobs", return_value=rows
                ), redirect_stdout(io.StringIO()):
                    cost.main()
                self.assertTrue(output.is_file())
            with patch("sys.argv", args + ["--keys", "0"]), self.assertRaises(
                SystemExit
            ):
                cost.main()


if __name__ == "__main__":
    unittest.main()
