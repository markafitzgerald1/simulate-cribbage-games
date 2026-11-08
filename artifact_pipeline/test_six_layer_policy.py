"""Independent actions, state transitions and negative policy-input fixtures."""

from dataclasses import replace
from contextlib import contextmanager
import json
import os
from pathlib import Path
import random
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

from artifact_pipeline.adapter import legacy_select_play_rank
from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    ROLES,
    LegacyHeuristicPolicy,
    PeggingState,
    PolicyView,
    policy_fingerprint,
    simulate_pegging,
)
from artifact_pipeline.six_layer_policy import (
    SixLayerPolicy,
    HANDS,
    _address,
    close_component,
    _go_actor,
    read_manifest,
)
from artifact_pipeline.test_fixed_policy_fixtures import bind, make_bundle

OWN = (0, 0, 1, 8)


@contextmanager
def temporary_directory():
    """Use unittest enterContext for automatic fixture cleanup."""
    with tempfile.TemporaryDirectory() as directory:
        yield directory


class TestUsedLegacyPolicy(unittest.TestCase):
    """Cover the complete immutable fallback chain before exercising the loader."""

    def test_explicit_fallback_rules(self):
        for ranks, count, sequence, expected in [
            ((0, 12), 1, (0,), 0),
            ((4, 8), 10, (4, 4), 4),
            ((9, 10, 12), 20, (5, 5, 7), 9),
        ]:
            self.assertEqual(legacy_select_play_rank(ranks, count, sequence), expected)

    def test_complete_game_acceptance(self):
        result = simulate_pegging(
            (0, 2, 3, 9),
            (8, 9, 10, 12),
            {r: LegacyHeuristicPolicy() for r in ROLES},
            random.Random(1),
        )
        self.assertEqual(result.total(PONE), 3)
        self.assertEqual(result.total(DEALER), 1)
        self.assertEqual(tuple(result.opening), (3, 9))
        self.assertEqual(result.players[PONE]["fifteen"], 2)
        self.assertEqual(result.players[PONE]["go"], 1)
        self.assertEqual(result.players[DEALER]["last_card"], 1)


class TestSixLayerPolicy(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(temporary_directory()))
        self.path = make_bundle(self.root)

    def change(self, name, value):
        document = json.loads(self.path.read_text())
        document[name] = value
        self.path.write_text(json.dumps(document))

    def rebind(self, name):
        document = json.loads(self.path.read_text())
        document[name].update(bind(self.root, document[name]["file"]))
        self.path.write_text(json.dumps(document))

    def test_cdf_boundaries_zero_mass_and_live_simulation(self):
        view = PeggingState({PONE: list(OWN), DEALER: [4] * 4}).view()
        with SixLayerPolicy(self.path) as policy:
            for draw, expected in [(0, 0), (499, 0), (500, 8), (999, 8)]:
                rng = Mock(spec=random.Random)
                rng.randrange.return_value = draw
                self.assertEqual(policy.select_rank(view, rng), expected)
                rng.randrange.assert_called_once_with(1000)
            rng = Mock(spec=random.Random)
            rng.randrange.return_value = 999
            result = simulate_pegging(
                OWN, (4, 4, 4, 4), {r: policy for r in ROLES}, rng
            )
            self.assertEqual(result.opening[0], 8)
            self.assertGreater(policy.decision_counts()["trained"], 0)
            self.assertGreater(policy.decision_counts()["missing_menu_fallback"], 0)
            self.assertGreater(policy.decision_counts()["forced"], 0)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            policy.select_rank(view, random.Random(1))
        policy.close()

    def test_pure_and_off_support_rows_do_not_draw(self):
        with SixLayerPolicy(self.path) as policy:
            for lead, expected, category in [
                (0, 0, "heuristic_equivalent"),
                (1, 1, "off_support"),
            ]:
                state = PeggingState(
                    {PONE: [4] * 3, DEALER: list(OWN)},
                    next_role=DEALER,
                    count=lead + 1,
                    sequence=[lead],
                    public_history=[lead],
                    last_player=PONE,
                )
                rng = Mock(spec=random.Random)
                self.assertEqual(policy.select_rank(state.view(), rng), expected)
                rng.randrange.assert_not_called()
                self.assertEqual(policy.decision_counts()[category], 1)
            policy.reset_counts()
            self.assertEqual(sum(policy.decision_counts().values()), 0)

    def test_dealer_mixed_row_returns_stored_actions_not_heuristic(self):
        # After a Five lead the stored Dealer row is half Ace, half Nine while
        # the heuristic plays Nine, so a heuristic Dealer fails at low draws.
        state = PeggingState(
            {PONE: [4] * 3, DEALER: list(OWN)},
            next_role=DEALER,
            count=5,
            sequence=[4],
            public_history=[4],
            last_player=PONE,
        )
        self.assertEqual(
            LegacyHeuristicPolicy().select_rank(state.view(), random.Random(0)), 8
        )
        with SixLayerPolicy(self.path) as policy:
            for draw, expected in [(0, 0), (499, 0), (500, 8), (999, 8)]:
                rng = Mock(spec=random.Random)
                rng.randrange.return_value = draw
                self.assertEqual(policy.select_rank(state.view(), rng), expected)
                rng.randrange.assert_called_once_with(1000)
            self.assertEqual(policy.decision_counts()["trained"], 4)

    def test_public_history_reconstruction_go_and_31(self):
        heuristic = {r: LegacyHeuristicPolicy() for r in ROLES}
        saw_go = saw_reset = saw_31 = False
        with SixLayerPolicy(self.path) as policy:
            for seed in range(150):
                dealt = random.Random(seed).sample(range(52), 8)
                hands = {
                    PONE: tuple(sorted(card // 4 for card in dealt[:4])),
                    DEALER: tuple(sorted(card // 4 for card in dealt[4:])),
                }
                result = simulate_pegging(
                    hands[PONE],
                    hands[DEALER],
                    heuristic,
                    random.Random(seed),
                    collect_decisions=True,
                )
                for decision in result.decisions:
                    view = decision.view
                    key, _ = _address(view)
                    self.assertEqual(HANDS[key % 1820], hands[view.role])
                    saw_go |= -1 in view.public_history
                    saw_reset |= -2 in view.public_history
                    # A reset without preceding goes is caused by31.
                    saw_31 |= (
                        -2 in view.public_history and -1 not in view.public_history
                    )
                    policy.select_rank(view, random.Random(seed))
        self.assertTrue(saw_go and saw_reset and saw_31)

    def test_go_and_reset_pack_to_fixed_history_nibbles(self):
        # Hand-packed producer codes, low nibble first: rank r -> r + 1,
        # go -> 0xE, sequence reset -> 0xF. A swap of the go and reset codes
        # would miss every post-go row and silently fall back to heuristics.
        after_go = PolicyView(
            role=PONE,
            own_remaining=(6, 12),
            count=0,
            sequence=(),
            opponent_remaining_count=1,
            passed_roles=(),
            public_history=(0, 8, 6, 7, -1, 4, -1, -1, -2),
        )
        after_31 = PolicyView(
            role=DEALER,
            own_remaining=(1, 4),
            count=0,
            sequence=(),
            opponent_remaining_count=1,
            passed_roles=(),
            public_history=(2, 7, 9, 7, 1, -2),
        )
        for view, own, code in [
            (after_go, (0, 6, 6, 12), 0xF_EE5E_8791),
            (after_31, (1, 4, 7, 7), 0xF2_8A83),
        ]:
            key, actual = _address(view)
            self.assertEqual(actual, code)
            self.assertEqual(key // len(HANDS), ROLES.index(view.role))
            self.assertEqual(HANDS[key % len(HANDS)], own)

    def test_fingerprint_binds_prior_bytes(self):
        with SixLayerPolicy(self.path) as first:
            before = policy_fingerprint(first)
        prior = self.root / "prior.bin"
        data = bytearray(prior.read_bytes())
        data[-1] ^= 1
        prior.write_bytes(data)
        self.rebind("prior")
        with SixLayerPolicy(self.path) as second:
            self.assertNotEqual(before, policy_fingerprint(second))

    def test_missing_history_and_bounded_mapping_lifecycle(self):
        with patch(
            "artifact_pipeline.six_layer_policy.close_component", wraps=close_component
        ) as closed, SixLayerPolicy(self.path, cache_limit=1) as policy:
            policy.select_rank(
                PeggingState({PONE: list(OWN), DEALER: [4] * 4}).view(),
                random.Random(1),
            )
            closed.reset_mock()
            dealer = PeggingState(
                {PONE: [4] * 3, DEALER: list(OWN)},
                next_role=DEALER,
                count=5,
                sequence=[4],
                public_history=[4],
            )
            policy.select_rank(dealer.view(), random.Random(2))
            closed.assert_called_once()
            self.assertTrue(closed.call_args.args[0].closed)
            dealer.count, dealer.sequence, dealer.public_history = 4, [3], [3]
            self.assertEqual(
                policy.select_rank(dealer.view(), random.Random(3)),
                LegacyHeuristicPolicy().select_rank(dealer.view(), random.Random(3)),
            )
            closed.assert_called_once()

    def test_fingerprint_binds_actual_probability_bytes_and_returns_a_copy(self):
        with SixLayerPolicy(self.path) as first:
            before = policy_fingerprint(first)
            copy = first.manifest
            copy["support"]["mask"] = 2
            self.assertEqual(first.manifest["support"]["mask"], 1)
        probabilities = self.root / "probabilities.bin"
        data = bytearray(probabilities.read_bytes())
        struct.pack_into("<3H", data, 0, 400, 0, 600)
        probabilities.write_bytes(data)
        self.rebind("probabilities")
        with SixLayerPolicy(self.path) as second:
            self.assertNotEqual(before, policy_fingerprint(second))

    def test_input_and_cdf_mutants(self):
        for component in ["probabilities", "offsets", "support", "prior"]:
            document = json.loads(self.path.read_text())
            saved = document[component]["sha256"]
            document[component]["sha256"] = "f" * 64
            self.path.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "mismatch"):
                SixLayerPolicy(self.path)
            document[component]["sha256"] = saved
            self.path.write_text(json.dumps(document))
        probabilities = self.root / "probabilities.bin"
        probabilities.write_bytes(struct.pack("<12H", *([1] * 12)))
        self.rebind("probabilities")
        with self.assertRaisesRegex(ValueError, "sum"):
            SixLayerPolicy(self.path)

    def test_malformed_json_and_schema(self):
        for text in [
            "[]",
            '{"schema":"wrong"}',
            '{"schema":"six-layer-pegging-policy.v1","schema":"six-layer-pegging-policy.v1"}',
        ]:
            self.path.write_text(text)
            with self.assertRaises(ValueError):
                read_manifest(self.path)

    def test_invalid_caller_views(self):
        view = PeggingState({PONE: list(OWN), DEALER: [4] * 4}).view()
        for bad in [
            replace(view, role="other"),
            replace(view, public_history=tuple([0] * 17)),
            replace(view, public_history=(13,)),
            replace(view, public_history=(-2,)),
            replace(view, public_history=(9, 9, 9, 0, 0)),
            replace(view, count=1),
            replace(view, own_remaining=(0, 0, 0, 0, 0)),
        ]:
            with self.assertRaises(ValueError):
                _address(bad)
        with self.assertRaisesRegex(ValueError, "previous"):
            _go_actor(1, -1, {0})

    def test_manifest_shape_and_descriptor_rejections(self):
        original = json.loads(self.path.read_text())
        variants = []
        for name, value in [
            ("prior", []),
            ("menus", None),
            ("menus", [1]),
            ("probability_denominator", 999),
            ("probability_denominator", 1000.0),
            ("fallback", {}),
        ]:
            variant = json.loads(json.dumps(original))
            variant[name] = value
            variants.append(variant)
        for field, value in [
            ("file", "../policy.bin"),
            ("file", ""),
            ("bytes", True),
            ("sha256", 3),
        ]:
            variant = json.loads(json.dumps(original))
            variant["prior"][field] = value
            variants.append(variant)
        for mask in [True, 0]:
            variant = json.loads(json.dumps(original))
            variant["support"]["mask"] = mask
            variants.append(variant)
        for hand in [None, [0] * 5, [False, 0, 1, 8]]:
            variant = json.loads(json.dumps(original))
            variant["menus"][0]["own_hand"] = hand
            variants.append(variant)
        variant = json.loads(json.dumps(original))
        variant["menus"].append(variant["menus"][0])
        variants.append(variant)
        for variant in variants:
            with self.subTest(variant=variant):
                self.path.write_text(json.dumps(variant))
                with self.assertRaises(ValueError):
                    SixLayerPolicy(self.path)
        self.path.write_text(json.dumps(original))
        for limit in [0, True]:
            with self.assertRaises(ValueError):
                SixLayerPolicy(self.path, cache_limit=limit)
        self.path.write_text("{}")
        with self.assertRaises(ValueError):
            read_manifest(self.path)

    def test_binary_shape_and_menu_mutants(self):
        original = json.loads(self.path.read_text())
        menu_path = self.root / original["menus"][0]["file"]
        original_menu = menu_path.read_bytes()
        for offset, format_code, value in [
            (0, "<Q", 1),
            (18, "<B", 13),
            (20, "<B", 6),
            (21, "<B", 1),
            (22, "<B", 3),
        ]:
            data = bytearray(original_menu)
            struct.pack_into(format_code, data, offset, value)
            # Duplicated actions are also invalid irrespective of digest.
            if offset == 0:
                data += bytes(data)
            menu_path.write_bytes(data)
            document = json.loads(json.dumps(original))
            document["menus"][0].update(bind(self.root, menu_path.name))
            self.path.write_text(json.dumps(document))
            with self.assertRaises(ValueError):
                SixLayerPolicy(self.path)
        menu_path.write_bytes(original_menu + b"x")
        document = json.loads(json.dumps(original))
        document["menus"][0].update(bind(self.root, menu_path.name))
        self.path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "Truncated menu"):
            SixLayerPolicy(self.path)
        menu_path.write_bytes(original_menu)
        self.path.write_text(json.dumps(original))
        for name, payload in [
            ("offsets", struct.pack("<4I", 1, 3, 6, 9)),
            ("probabilities", b"x"),
            ("prior", b"x" * 8),
            ("support", b"\x04" * 4),
        ]:
            destination = self.root / original[name]["file"]
            saved = destination.read_bytes()
            destination.write_bytes(payload)
            self.rebind(name)
            with self.assertRaises(ValueError):
                SixLayerPolicy(self.path)
            destination.write_bytes(saved)
            self.path.write_text(json.dumps(original))

    def test_legal_menu_and_invalid_rng_fail_loudly(self):
        view = PeggingState({PONE: list(OWN), DEALER: [4] * 4}).view()
        with SixLayerPolicy(self.path) as policy:
            rng = Mock(spec=random.Random)
            rng.randrange.return_value = 1000
            with self.assertRaisesRegex(ValueError, "CDF"):
                policy.select_rank(view, rng)
        document = json.loads(self.path.read_text())
        destination = self.root / document["menus"][0]["file"]
        data = bytearray(destination.read_bytes())
        data[18] = 12
        destination.write_bytes(data)
        document["menus"][0].update(bind(self.root, destination.name))
        self.path.write_text(json.dumps(document))
        with SixLayerPolicy(self.path) as policy:
            with self.assertRaisesRegex(ValueError, "real legal"):
                policy.select_rank(view, random.Random(1))

    def test_empty_components_and_invalid_history_counts(self):
        document = json.loads(self.path.read_text())
        for name in ["probabilities", "offsets", "support"]:
            destination = self.root / document[name]["file"]
            destination.write_bytes(b"")
            document[name].update(bind(self.root, destination.name))
        document["menus"] = []
        self.path.write_text(json.dumps(document))
        with SixLayerPolicy(self.path) as policy:
            view = PeggingState({PONE: list(OWN), DEALER: [4] * 4}).view()
            self.assertEqual(policy.select_rank(view, random.Random(1)), 1)
            self.assertEqual(policy.decision_counts()["missing_menu_fallback"], 1)
        base = PeggingState({PONE: list(OWN), DEALER: [4] * 4}).view()
        for history in [(9, 9, 9, 9), (0, -1, 1, 1), (9, 9, 9, 0, -2, 9)]:
            with self.assertRaises(ValueError):
                _address(replace(base, public_history=history))

    def test_fingerprint_rejects_bad_behavioral_identity(self):
        policy = Mock()
        for value in [1, "a", "X" * 64]:
            policy.behavioral_fingerprint = value
            with self.assertRaises(ValueError):
                policy_fingerprint(policy)

    @unittest.skipUnless(
        os.environ.get("CFR_POLICY_MANIFEST"),
        "Optional real artifact is not configured",
    )
    def test_optional_real_input(self):
        with SixLayerPolicy(Path(os.environ["CFR_POLICY_MANIFEST"])) as policy:
            result = simulate_pegging(
                OWN, (3, 4, 6, 12), {r: policy for r in ROLES}, random.Random(42)
            )
            self.assertTrue(result.total(PONE) + result.total(DEALER) > 0)


if __name__ == "__main__":
    unittest.main()
