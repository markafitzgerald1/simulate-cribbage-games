"""Independent first-exchange attribution and exact-byte pairing checks."""

from copy import deepcopy
import hashlib
import json
import math
import random
import unittest
from unittest.mock import patch

from artifact_pipeline.generate_play_table import (
    GENERATION_METHOD,
    build_client_table,
    generate_play_table,
    validate_resume_table,
)
from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    POINT_TYPES,
    PeggingResult,
    simulate_pegging,
)
from artifact_pipeline.play_lines import OpeningLines, build_lines, decode_lines


class RandomPolicy:  # pylint: disable=too-few-public-methods
    def select_rank(self, view, rng):
        return rng.choice(view.legal_ranks)


def measured_result(lead, response, role, delta):
    players = {seat: dict.fromkeys(POINT_TYPES, 0.0) for seat in (PONE, DEALER)}
    players[PONE]["pair"] = 10 + (delta if role == PONE else 0)
    players[DEALER]["pair"] = 10 + (delta if role == DEALER else 0)
    return PeggingResult(players, opening=[lead, response])


class TestPlayLines(unittest.TestCase):
    def fixture(self):
        # Lead A has three different outcomes. Dealer lead 9 has two responses:
        # the non-modal response's -8 must contribute to its lead mean too.
        scripted = [
            (0, 4, PONE, 2),
            (0, 5, PONE, 6),
            (1, 6, PONE, -3),
            (0, 4, PONE, -2),
            (2, 4, PONE, 0),
            (8, 0, DEALER, 4),
            (8, 0, DEALER, 0),
            (8, 1, DEALER, -8),
            (9, 3, DEALER, 0),
            (9, 2, DEALER, 0),
        ]
        with patch(
            "artifact_pipeline.generate_play_table.sample_opponent_keep",
            return_value=(4, 5, 6, 7),
        ), patch(
            "artifact_pipeline.generate_play_table.simulate_pegging",
            side_effect=[measured_result(*row) for row in scripted],
        ) as simulate:
            full = generate_play_table(
                None, {}, 5, 42, hands=[(0, 1, 2, 3)], play_policy_fingerprint="frozen"
            )
        self.assertEqual(simulate.call_count, 10)
        full["__metadata__"]["joint_policy_converged"] = False
        means = json.dumps(build_client_table(full)).encode()
        return full, means, build_lines(full, means)

    def test_generator_lead_counts_and_all_outcome_attribution(self):
        full, _means, data = self.fixture()
        self.assertAlmostEqual(full["A_2_3_4"][PONE]["mu"], 0.6)
        self.assertAlmostEqual(full["A_2_3_4"][DEALER]["mu"], -0.8)
        pone, dealer = data["entries"][0]
        self.assertEqual(
            pone, [[0, 3, 2.0, 2.3], [1, 1, None, None], [2, 1, None, None]]
        )
        self.assertEqual(dealer, [[8, 3, -1.333, 3.5, 0, 2], [9, 2, 0.0, 0.0, 2, 1]])
        # Counts give lead frequency 3/5 and response frequency 2/3,
        # independent of the role's whole-hand mean or the modal outcome mean.
        self.assertEqual(sum(row[1] for row in dealer), 5)
        self.assertEqual(dealer[0][1] / 5, 0.6)
        self.assertAlmostEqual(dealer[0][5] / dealer[0][1], 2 / 3)
        self.assertNotIn(3, [row[0] for row in pone])

    def test_digest_pairs_exact_bytes_including_whitespace(self):
        _full, means, data = self.fixture()
        encoded = json.dumps(data).encode()
        self.assertEqual(data["means_sha256"], hashlib.sha256(means).hexdigest())
        self.assertEqual(decode_lines(encoded, means), data)
        for wrong in (
            means + b"\n",
            b"{}",
            json.dumps(json.loads(means), indent=2).encode(),
        ):
            with self.subTest(wrong=wrong[:15]), self.assertRaises(ValueError):
                decode_lines(encoded, wrong)

    def test_observation_uses_actual_policy_calls_and_rng(self):
        selected = []

        class RecordingPolicy(RandomPolicy):  # pylint: disable=too-few-public-methods
            def select_rank(self, view, rng):
                rank = super().select_rank(view, rng)
                selected.append((view.role, rank))
                return rank

        policies = {PONE: RecordingPolicy(), DEALER: RecordingPolicy()}
        rng = random.Random(17)
        result = simulate_pegging((0, 1, 2, 3), (4, 5, 6, 7), policies, rng)
        self.assertEqual(result.opening, [selected[0][1], selected[1][1]])
        self.assertEqual([seat for seat, _rank in selected[:2]], [PONE, DEALER])
        self.assertEqual(len(selected), 8)
        plain_rng = random.Random(17)
        plain = simulate_pegging(
            (0, 1, 2, 3),
            (4, 5, 6, 7),
            {PONE: RandomPolicy(), DEALER: RandomPolicy()},
            plain_rng,
        )
        self.assertEqual(result.players, plain.players)
        self.assertEqual(rng.getstate(), plain_rng.getstate())
        forced = simulate_pegging(
            (0, 0, 0, 0), (1, 1, 1, 1), policies, random.Random(1)
        )
        self.assertEqual(forced.opening, [0, 1])

    def test_checkpoint_exact_moments_and_incomplete_counts(self):
        lines = OpeningLines()
        for value in (2, 6, -2):
            lines.add([0, 4], value)
        saved = json.loads(json.dumps(lines.checkpoint()))
        restored = OpeningLines.restore(saved, 3)
        lines.add([0, 5], -5)
        restored.add([0, 5], -5)
        self.assertEqual(restored.checkpoint(), lines.checkpoint())
        with self.assertRaisesRegex(ValueError, "lead counts"):
            OpeningLines.restore(saved, 4)
        saved["0"]["responses"]["4"] = 2
        with self.assertRaisesRegex(ValueError, "response counts"):
            OpeningLines.restore(saved, 3)

    def test_published_precision_does_not_round_positive_se_to_zero(self):
        lines = OpeningLines()
        lines.add([0, 1], 1.23456)
        lines.add([0, 1], 1.23458)
        self.assertEqual(lines.rows(PONE), [[0, 2, 1.235, 0.00001]])
        self.assertEqual(OpeningLines().rows(PONE), [])

    def test_publication_normalizes_negative_zero_without_changing_checkpoint(self):
        lines = OpeningLines()
        lines.add([0, 1], -0.0004)
        lines.add([0, 1], -0.0004)
        before = deepcopy(lines.checkpoint())
        rows = lines.rows(PONE)
        self.assertEqual(math.copysign(1, rows[0][2]), 1)
        self.assertEqual(json.dumps(rows), "[[0, 2, 0.0, 0.0]]")
        self.assertEqual(lines.checkpoint(), before)

    def test_mode_uses_count_before_rank(self):
        lines = OpeningLines()
        for response in (0, 3, 3):
            lines.add([9, response], 0)
        self.assertEqual(lines.rows(DEALER), [[9, 3, 0.0, 0.0, 3, 2]])

    def test_publication_sorts_leads_observed_out_of_order(self):
        lines = OpeningLines()
        for lead, delta in ((2, 6), (0, 4), (2, 10), (1, 1)):
            lines.add([lead, 3], delta)
        self.assertEqual(
            lines.rows(PONE), [[0, 1, None, None], [1, 1, None, None], [2, 2, 8.0, 2.0]]
        )

    def test_fractional_checkpoint_preserves_mean_and_central_moment(self):
        lines = OpeningLines()
        for delta in (1 / 7, -2 / 11, 4 / 13):
            lines.add([0, 1], delta)
        original = deepcopy(lines.deltas[0])
        saved = json.loads(json.dumps(lines.checkpoint()))
        self.assertEqual(saved["0"]["mean"], original.mean)
        self.assertEqual(saved["0"]["moment_2"], original.moment_2)
        restored = OpeningLines.restore(saved, 3)
        self.assertEqual(restored.deltas[0], original)
        lines.add([0, 2], -5 / 17)
        restored.add([0, 2], -5 / 17)
        self.assertEqual(restored.checkpoint(), lines.checkpoint())

    def test_resume_rejects_v2_generation_method(self):
        old = {
            "__metadata__": {
                "generation_method": "artifact_pipeline.generate_play_table.v2",
                "seed": 42,
            }
        }
        with self.assertRaisesRegex(ValueError, "generation method"):
            validate_resume_table(old, 42)

    def test_reader_rejects_non_object_and_malformed_containers_as_value_error(self):
        _full, means, data = self.fixture()
        for document in (
            None,
            True,
            1,
            "text",
            [],
            {},
            {**data, "qualifications": []},
            {**data, "provenance": {}},
            {**data, "keys": None},
            {**data, "keys": [{}]},
            {**data, "entries": None},
            {**data, "keys": {}, "entries": {}},
            {**data, "entries": [[{}, []]]},
            {**data, "entries": [[[], {}]]},
            {**data, "entries": [[None, []]]},
            {**data, "entries": [[[None], []]]},
            {**data, "entries": [[[[0, 2, 10**400, 0]], []]]},
        ):
            with self.subTest(document=document), self.assertRaises(ValueError):
                decode_lines(json.dumps(document).encode(), means)

    def test_reader_requires_rank_order_keys_and_ascending_lead_rows(self):
        _full, means, data = self.fixture()
        data["keys"] = ["A_A_A_A", "2_2_2_2"]
        data["entries"] = [
            [[[0, 2, 0, 0]], [[3, 2, 0, 0, 0, 1]]],
            [[[1, 2, 0, 0]], [[3, 2, 0, 0, 1, 1]]],
        ]
        self.assertEqual(decode_lines(json.dumps(data).encode(), means), data)
        reversed_keys = {
            **data,
            "keys": data["keys"][::-1],
            "entries": data["entries"][::-1],
        }
        with self.assertRaises(ValueError):
            decode_lines(json.dumps(reversed_keys).encode(), means)
        _full, means, data = self.fixture()
        for role_index in (0, 1):
            broken = deepcopy(data)
            broken["entries"][0][role_index].reverse()
            with self.subTest(role_index=role_index), self.assertRaises(ValueError):
                decode_lines(json.dumps(broken).encode(), means)

    def test_rank_order_provenance_and_old_checkpoint_rejection(self):
        full, means, _data = self.fixture()
        full["2_3_4_5"] = deepcopy(full["A_2_3_4"])
        data = build_lines(full, means)
        self.assertEqual(data["keys"], ["A_2_3_4", "2_3_4_5"])
        self.assertEqual(data["provenance"]["policy_fingerprint"], "frozen")
        self.assertIs(data["provenance"]["joint_policy_converged"], False)
        self.assertEqual(data["provenance"]["generation_method"], GENERATION_METHOD)
        del full["A_2_3_4"][PONE]["opening"]
        with self.assertRaisesRegex(ValueError, "lead counts"):
            generate_play_table(
                None, {}, 5, 42, hands=[(0, 1, 2, 3)], existing_table=full
            )

    def test_reader_requires_qualifications_and_frozen_policy(self):
        _full, means, data = self.fixture()
        for field, value in (
            ("qualifications", {}),
            ("qualifications", {**data["qualifications"], "policy": ""}),
            ("qualifications", {**data["qualifications"], "missing": 0}),
            ("provenance", {**data["provenance"], "joint_policy_converged": 0}),
            ("provenance", {**data["provenance"], "policy_fingerprint": ""}),
            ("provenance", {**data["provenance"], "generation_method": 0}),
            ("keys", ["2_A_3_4"]),
        ):
            broken = {**data, field: value}
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                decode_lines(json.dumps(broken).encode(), means)

    def test_reader_rejects_missing_seed(self):
        _full, means, data = self.fixture()
        del data["provenance"]["seed"]
        with self.assertRaises(ValueError):
            decode_lines(json.dumps(data).encode(), means)

    def test_reader_rejects_object_and_other_non_integer_seeds(self):
        _full, means, data = self.fixture()
        for seed in ({}, {"seed": 42}, [], None, "42", 42.0, True, False):
            broken = deepcopy(data)
            broken["provenance"]["seed"] = seed
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                decode_lines(json.dumps(broken).encode(), means)

    def test_reader_accepts_integer_seed_without_coercion(self):
        _full, means, data = self.fixture()
        for seed in (-1, 0, 42, 2**64):
            data["provenance"]["seed"] = seed
            with self.subTest(seed=seed):
                decoded = decode_lines(json.dumps(data).encode(), means)
                self.assertEqual(decoded["provenance"]["seed"], seed)
                self.assertIs(type(decoded["provenance"]["seed"]), int)

    def test_reader_rejects_invalid_positional_data(self):
        _full, means, data = self.fixture()
        mutations = [
            ("schema", "old"),
            ("ranks", ""),
            ("roles", [DEALER, PONE]),
            ("precision", {}),
            ("columns", []),
            ("entries", []),
            ("keys", ["A_2_3_4", "A_2_3_4"]),
            ("keys", ["A_2_3"]),
            ("keys", ["A_2_3_X"]),
            ("keys", ["A_2_3_10"]),
            ("entries", [[[]]]),
        ]
        for field, value in mutations:
            broken = {**data, field: value}
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                decode_lines(json.dumps(broken).encode(), means)
        for row in (
            [0, 1, 0, None],
            [0, 1, None, 0],
            [0, 2, None, 0],
            [0, 2, 0, -1],
            [0, 2, float("nan"), 0],
            [0, 2, 0, "0"],
            [0, 2, True, 0],
            [True, 2, 0, 0],
            [13, 2, 0, 0],
            [0, True, None, None],
            [0, 0, None, None],
            [0],
            [4, 2, 0, 0],
            ["0", 2, 0, 0],
        ):
            broken = deepcopy(data)
            broken["entries"][0][0] = [row]
            with self.subTest(row=row), self.assertRaises(ValueError):
                decode_lines(json.dumps(broken).encode(), means)
        for response, count in ((True, 1), (13, 1), (4, 1), (0, True), (0, 0), (0, 4)):
            broken = deepcopy(data)
            broken["entries"][0][1] = [[8, 3, 0, 0, response, count]]
            with self.subTest(response=response, count=count), self.assertRaises(
                ValueError
            ):
                decode_lines(json.dumps(broken).encode(), means)
        broken = deepcopy(data)
        broken["entries"][0][0].append(broken["entries"][0][0][0])
        with self.assertRaises(ValueError):
            decode_lines(json.dumps(broken).encode(), means)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
