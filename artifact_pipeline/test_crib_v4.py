"""Checkpoint, resume, and opt-in routing tests for crib estimator v4."""

import contextlib
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from argparse import Namespace
from fractions import Fraction
from random import Random
from unittest.mock import patch

from artifact_pipeline import crib_v4, generate_table
from artifact_pipeline.crib_decomposition import (
    RANK_CATEGORIES,
    ROOT,
    base_observation,
    bucket_populations,
    centering_values,
    reconstruct,
    residual_observation,
    sample_hand,
    suit_observation,
)
from artifact_pipeline.test_crib_decomposition import _rank_scores, _scale_crib_scores
from artifact_pipeline.crib_v4 import (
    _V4Run,
    _bootstrap_policy,
    _centers,
    _physical_group,
    _run_control,
    _sample_round,
    _score_deal,
    _transition,
)

PAIRS = ["A_A_Unsuited", "A_2_Suited", "A_2_Unsuited"]


def fixture_centers(_group, legacy):
    return {
        cut: {kind: Fraction(0) for kind in RANK_CATEGORIES}
        for cut in range(len(legacy.Index.indices))
    }


def fixture_score_deal(_legacy, _role, _policy):
    def score(own, hand, starters):
        crib = (*own, *hand[:2])
        ranks = [card.index for card in crib]
        return {
            starter: {
                "fifteens": sum(ranks) + starter.index,
                "pairs": 2 * sum(rank == starter.index for rank in ranks),
                "runs": int(len(set(ranks)) == 4),
                "flushes": 5 * all(card.suit == starter.suit for card in crib),
                "nobs": int(
                    any(card.index == 10 and card.suit == starter.suit for card in crib)
                ),
            }
            for starter in starters
        }

    return score


def run_args(path, target=2, **changes):
    values = {
        "output": path,
        "samples": target,
        "infinite": False,
        "checkpoint_frequency": 2,
        "no_resume": False,
        "seed": 42,
        "bootstrap": None,
        "dampening": 0.5,
        "max_generations": None,
        "convergence_threshold": None,
        "fail_on_non_convergence": False,
        "no_client_output": False,
        "client_output": None,
    }
    values.update(changes)
    return Namespace(**values)


def read_json(path):
    with open(path, encoding="utf-8") as source:
        return json.load(source)


def read_bytes(path):
    with open(path, "rb") as source:
        return source.read()


def write_json(path, payload):
    with open(path, "w", encoding="utf-8") as destination:
        json.dump(payload, destination)


class V4CheckpointFixture(unittest.TestCase):
    """Share isolated checkpoints and fast scoring across v4 test cases."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory)
        for target in (
            "artifact_pipeline.crib_v4._centers",
            "artifact_pipeline.crib_v4._score_deal",
        ):
            replacement = (
                fixture_centers if target.endswith("_centers") else fixture_score_deal
            )
            mock = patch(target, replacement)
            mock.start()
            self.addCleanup(mock.stop)

    def path(self, name):
        return os.path.join(self.directory, name)

    def run_table(self, path, target=2, pairs=None, **changes):
        args = run_args(path, target, **changes)
        with contextlib.redirect_stdout(io.StringIO()):
            return crib_v4.run(args, PAIRS if pairs is None else pairs, generate_table)


class TestV4Checkpoint(V4CheckpointFixture):
    """Exercise the real state machine with a fast fixed scorer fixture."""

    def test_seeded_twins_and_same_rank_resume_match_fresh(self):
        resumed = self.path("resumed.json")
        fresh = self.path("fresh.json")
        self.run_table(resumed, 3, checkpoint_frequency=1)
        self.run_table(resumed, 7, checkpoint_frequency=4)
        self.run_table(fresh, 7, checkpoint_frequency=3)
        self.assertEqual(read_json(resumed), read_json(fresh))
        self.assertEqual(
            read_json(resumed)["__metadata__"]["estimator_state"]["A_2"]["Dealer"][
                "streams"
            ]["residual"]["count"],
            7,
        )
        self.assertNotIn(
            "residual",
            read_json(resumed)["__metadata__"]["estimator_state"]["A_A"]["Pone"][
                "streams"
            ],
        )
        self.assertEqual(read_json(resumed)["A_2_Suited"]["Dealer"]["A"]["n"], 7)

    def test_unseeded_saved_nonce_continues_without_reseeding(self):
        resumed = self.path("unseeded.json")
        fresh = self.path("unseeded-fresh.json")
        with patch(
            "artifact_pipeline.crib_v4.secrets.token_hex", return_value="ab" * 32
        ):
            self.run_table(resumed, 2, seed=None, pairs=["A_A_Unsuited"])
            self.run_table(fresh, 4, seed=None, pairs=["A_A_Unsuited"])
        with patch(
            "artifact_pipeline.crib_v4.secrets.token_hex",
            side_effect=AssertionError("resume requested a new nonce"),
        ):
            self.run_table(resumed, 4, seed=None, pairs=["A_A_Unsuited"])
        self.assertEqual(read_json(resumed), read_json(fresh))
        self.assertEqual(read_json(resumed)["__metadata__"]["seed"], None)
        with self.assertRaises(ValueError):
            self.run_table(resumed, 4, seed=42, pairs=["A_A_Unsuited"])

    def test_failure_after_vector_computation_preserves_disk_checkpoint(self):
        path = self.path("failed.json")
        original = _sample_round

        def fail_after_vectors(*arguments):
            original(*arguments)
            raise RuntimeError("after complete vectors, before commit")

        with patch(
            "artifact_pipeline.crib_v4._sample_round", side_effect=fail_after_vectors
        ):
            with self.assertRaisesRegex(RuntimeError, "before commit"):
                self.run_table(path, 2, pairs=["A_A_Unsuited"])
        saved = read_json(path)["__metadata__"]["estimator_state"]["A_A"]["Dealer"]
        self.assertEqual(saved["streams"]["base"]["count"], 0)
        self.run_table(path, 2, pairs=["A_A_Unsuited"])
        fresh = self.path("fresh.json")
        self.run_table(fresh, 2, pairs=["A_A_Unsuited"])
        self.assertEqual(read_json(path), read_json(fresh))

    def test_sigint_flag_finishes_complete_round(self):
        args = run_args(self.path("interrupt.json"), 3, checkpoint_frequency=3)
        current = _V4Run(args, ["A_A_Unsuited"], generate_table)
        original = _sample_round

        def request_after_vectors(*arguments):
            row = original(*arguments)
            current.request_stop(None, None)
            return row

        with patch(
            "artifact_pipeline.crib_v4._sample_round", side_effect=request_after_vectors
        ):
            with self.assertRaises(SystemExit) as stopped:
                current.execute()
        self.assertEqual(stopped.exception.code, 130)
        streams = read_json(args.output)["__metadata__"]["estimator_state"]["A_A"][
            "Dealer"
        ]["streams"]
        self.assertEqual({item["count"] for item in streams.values()}, {1})
        self.run_table(args.output, 3, pairs=["A_A_Unsuited"])

    def test_iterative_complete_and_pending_resume_transition_once(self):
        fresh = self.path("iterative-fresh.json")
        settings = {"max_generations": 2, "checkpoint_frequency": 1}
        self.run_table(fresh, 2, pairs=["A_A_Unsuited"], **settings)
        self.assertEqual(read_json(fresh)["__metadata__"]["generation"], 1)
        for phase, target in (
            ("complete", "interrupt-complete.json"),
            ("transition_pending", "interrupt-pending.json"),
        ):
            path = self.path(target)
            function = (
                "artifact_pipeline.crib_v4._should_stop_after_complete"
                if phase == "complete"
                else "artifact_pipeline.crib_v4._transition"
            )
            with patch(function, side_effect=RuntimeError("pause")):
                with self.assertRaisesRegex(RuntimeError, "pause"):
                    self.run_table(path, 2, pairs=["A_A_Unsuited"], **settings)
            self.assertEqual(read_json(path)["__metadata__"]["phase"], phase)
            self.run_table(path, 2, pairs=["A_A_Unsuited"], **settings)
            self.assertEqual(read_json(path), read_json(fresh))

    def test_rejects_incompatible_metadata_before_writing(self):
        source = self.path("valid.json")
        self.run_table(source, 2, pairs=["A_A_Unsuited"])
        baseline = read_json(source)
        mutations = (
            lambda meta: meta.update(
                generation_method="artifact_pipeline.generate_table.v3"
            ),
            lambda meta: meta.pop("estimator_state"),
            lambda meta: meta.update(estimator_contract="unknown"),
            lambda meta: meta.update(scale=1),
            lambda meta: meta.update(python_version="0.0"),
            lambda meta: meta.update(selector_contract="different"),
            lambda meta: meta.update(rng_contract="different"),
            lambda meta: meta.update(deck_order="different"),
            lambda meta: meta.update(policy_sha256="0" * 64),
            lambda meta: meta.update(requested_pairs=["A_2_Unsuited"]),
            lambda meta: meta.update(randomness_key=["seed", 99]),
            lambda meta: meta.update(phase="wrong"),
            lambda meta: meta.update(generation=-1),
            lambda meta: meta.update(generation=True),
            lambda meta: meta["run_control"].update(target_samples=True),
            lambda meta: meta["estimator_state"]["A_A"]["Dealer"].update(
                centering_numerators=["0"]
            ),
            lambda meta: meta["estimator_state"]["A_A"]["Dealer"]["streams"][
                "base"
            ].update(count=3),
            lambda meta: meta["estimator_state"]["A_A"]["Dealer"]["streams"][
                "base"
            ].update(next_index=True),
            lambda meta: meta["estimator_state"]["A_A"]["Dealer"]["streams"][
                "base"
            ].update(scale=True),
            lambda meta: meta["estimator_state"]["A_A"]["Dealer"]["streams"][
                "base"
            ].update(labels=["missing"]),
            lambda meta: meta["estimator_state"]["A_A"]["Dealer"]["streams"][
                "base"
            ].update(sum_xx_upper=[[0, 0, "-1"]]),
            lambda meta: meta["estimator_state"].pop("A_A"),
            lambda meta: meta["estimator_state"]["A_A"].pop("Pone"),
            lambda meta: meta["estimator_state"]["A_A"]["Dealer"].pop(
                "centering_denominator"
            ),
            lambda meta: meta["estimator_state"]["A_A"]["Dealer"]["streams"].pop(
                "suit"
            ),
        )
        for mutate in mutations:
            target = self.path("mutated.json")
            altered = copy.deepcopy(baseline)
            mutate(altered["__metadata__"])
            write_json(target, altered)
            before = read_bytes(target)
            with self.subTest(mutate=mutate):
                with self.assertRaises((ValueError, TypeError, KeyError)):
                    self.run_table(target, 2, pairs=["A_A_Unsuited"])
            self.assertEqual(read_bytes(target), before)

    def test_rejects_legacy_client_and_target_or_mode_changes(self):
        path = self.path("valid.json")
        self.run_table(path, 2, pairs=["A_A_Unsuited"])
        with self.assertRaises(ValueError):
            self.run_table(path, 1, pairs=["A_A_Unsuited"])
        with self.assertRaises(ValueError):
            self.run_table(path, 2, pairs=["A_2_Suited"])
        with self.assertRaises(ValueError):
            self.run_table(path, 2, pairs=["A_A_Unsuited"], infinite=True)
        with self.assertRaises(ValueError):
            self.run_table(path, 2, pairs=["A_A_Unsuited"], dampening=0.7)
        with self.assertRaises(ValueError):
            self.run_table(path, 2, pairs=["A_A_Unsuited"], seed=99)
        with self.assertRaises(ValueError):
            self.run_table(path, 2, pairs=["A_A_Unsuited"], max_generations=2)
        larger = self.path("larger.json")
        self.run_table(larger, 4, pairs=["A_A_Unsuited"])
        with self.assertRaises(ValueError):
            self.run_table(larger, 3, pairs=["A_A_Unsuited"])
        with self.assertRaises(ValueError):
            self.run_table(self.path("valid.client.json"), 2, pairs=["A_A_Unsuited"])
        legacy_path = self.path("legacy.json")
        write_json(
            legacy_path,
            {
                "__metadata__": {
                    "generation_method": "artifact_pipeline.generate_table.v3",
                }
            },
        )
        with self.assertRaises(ValueError):
            self.run_table(legacy_path, 2, pairs=["A_A_Unsuited"])

    def test_client_omits_checkpoint_and_policy_state(self):
        full = self.run_table(
            self.path("client.json"), 2, pairs=["A_2_Suited", "A_2_Unsuited"]
        )
        client = read_json(self.path("client.client.json"))
        self.assertEqual(
            set(client["__metadata__"]),
            {
                "generation_method",
                "seed",
                "seed_was_specified",
                "generation",
                "use_control_variates",
            },
        )
        self.assertNotIn("estimator_state", client["__metadata__"])
        self.assertNotIn("starter_suit_relation", client["A_2_Unsuited"]["Dealer"]["3"])
        self.assertTrue("starter_suit_relation" in client["A_2_Suited"]["Dealer"]["3"])
        self.assertEqual(
            client["A_2_Suited"]["Dealer"]["3"]["mu"],
            generate_table.round_client_mu(full["A_2_Suited"]["Dealer"]["3"]["mu"]),
        )
        no_client = self.path("no-client.json")
        self.run_table(no_client, 2, pairs=["A_A_Unsuited"], no_client_output=True)
        self.assertFalse(os.path.exists(self.path("no-client.client.json")))

    def test_displayed_buckets_are_rebuilt_from_authoritative_moments(self):
        path = self.path("authoritative.json")
        original = self.run_table(path, 2, pairs=["A_A_Unsuited"])
        altered = read_json(path)
        altered["A_A_Unsuited"]["Dealer"]["A"]["mu"] = -999.0
        write_json(path, altered)
        self.run_table(path, 3, pairs=["A_A_Unsuited"])
        fresh = self.path("authoritative-fresh.json")
        self.run_table(fresh, 3, pairs=["A_A_Unsuited"])
        self.assertEqual(read_json(path), read_json(fresh))
        self.assertNotEqual(original["A_A_Unsuited"]["Dealer"]["A"]["mu"], -999.0)

    def test_cli_routing_requires_opt_in(self):
        arguments = [
            "generate_table.py",
            "--estimator-v4",
            "--samples=2",
            f"--output={self.path('cli.json')}",
        ]
        with patch.object(sys, "argv", arguments), patch(
            "artifact_pipeline.crib_v4.run"
        ) as routed:
            generate_table.main(["A_A_Unsuited"])
        self.assertEqual(routed.call_count, 1)
        self.assertEqual(routed.call_args.args[1], ["A_A_Unsuited"])
        self.assertIs(routed.call_args.args[2], generate_table)
        with patch.object(
            sys, "argv", [*arguments, "--use-control-variates"]
        ), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            generate_table.main(["A_A_Unsuited"])

    def test_fixed_policy_bootstrap_and_real_selector_scoring(self):
        bootstrap = self.path("bootstrap.json")
        write_json(
            bootstrap,
            {
                "__metadata__": {
                    "generation_method": "artifact_pipeline.generate_table.v3"
                },
                "A_A_Unsuited": {"Dealer": {"A": {"n": 1, "mu": 4.0, "se": 0.0}}},
            },
        )
        policy, digest = _bootstrap_policy(
            run_args(self.path("out.json"), bootstrap=bootstrap), generate_table
        )
        self.assertEqual(policy["A_A_Unsuited"]["Dealer"]["A"]["mu"], 4.0)
        self.assertEqual(len(digest), 64)
        centers = _centers(_physical_group("A_A", generate_table), generate_table)
        self.assertEqual(set(centers), set(range(13)))
        self.assertTrue(
            all(
                (value * 1176).denominator == 1
                for categories in centers.values()
                for value in categories.values()
            )
        )

        def physical_rank_score(ranks):
            points = generate_table.score_hand_and_starter_breakdown(
                [generate_table.Card(rank, 0) for rank in ranks[:4]],
                generate_table.Card(ranks[4], 1),
                is_crib=True,
            )
            return {kind: points[kind] for kind in RANK_CATEGORIES}

        group = _physical_group("A_A", generate_table)
        reference = centering_values(group, physical_rank_score)
        self.assertEqual(centers, reference)
        hand = group.remaining("Unsuited")[:6]
        starters = group.remaining("Unsuited")[6:]
        selected = generate_table.select_opponent_kept_cards_dynamic(
            "Dealer", list(hand), None
        )
        discarded = [card for card in hand if card not in selected]
        scored = _score_deal(generate_table, "Dealer", None)(
            group.unsuited, hand, starters
        )
        self.assertEqual(
            scored[starters[0]],
            generate_table.score_hand_and_starter_breakdown(
                [*group.unsuited, *discarded], starters[0], is_crib=True
            ),
        )

    def test_run_control_and_invalid_selection(self):
        fixed = run_args(self.path("x.json"))
        self.assertEqual(_run_control(fixed)["mode"], "fixed_finite")
        self.assertEqual(
            _run_control(run_args(self.path("x.json"), None, infinite=True))["mode"],
            "fixed_unbounded",
        )
        self.assertEqual(
            _run_control(run_args(self.path("x.json"), 2, max_generations=2))["mode"],
            "iterative",
        )
        for pairs in (
            [],
            ["missing"],
            ["A_2_Suited"],
            ["A_2_Unsuited"],
            ["A_A_Unsuited", "A_A_Unsuited"],
        ):
            with self.subTest(pairs=pairs):
                with self.assertRaises(ValueError):
                    self.run_table(self.path("invalid.json"), 2, pairs=pairs)
        with self.assertRaises(ValueError):
            self.run_table(self.path("small.json"), 1, pairs=["A_A_Unsuited"])

    def test_phase_and_nonce_corruption_are_rejected(self):
        source = self.path("phase.json")
        self.run_table(source, 3, pairs=["A_A_Unsuited"])
        initial = read_json(source)
        cases = (
            (2, lambda meta: meta["run_control"].update(target_samples=2)),
            (4, lambda meta: meta["run_control"].update(target_samples=4)),
            (3, lambda meta: meta.update(phase="transition_pending")),
        )
        for target, mutate in cases:
            path = self.path("bad-phase.json")
            altered = copy.deepcopy(initial)
            mutate(altered["__metadata__"])
            write_json(path, altered)
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    self.run_table(path, target, pairs=["A_A_Unsuited"])
        unseeded = self.path("nonce.json")
        self.run_table(unseeded, 2, pairs=["A_A_Unsuited"], seed=None)
        for key in (None, ["nonce", "short"], ["nonce", "z" * 64]):
            altered = read_json(unseeded)
            altered["__metadata__"]["randomness_key"] = key
            path = self.path("bad-nonce.json")
            write_json(path, altered)
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    self.run_table(path, 2, pairs=["A_A_Unsuited"], seed=None)

    def test_bootstrap_hash_and_iterative_settings_are_pinned(self):
        bootstrap = self.path("bootstrap.json")
        write_json(
            bootstrap,
            {
                "__metadata__": {
                    "generation_method": "artifact_pipeline.generate_table.v3",
                },
                "A_A_Unsuited": {"Dealer": {"A": {"n": 1, "mu": 4.0, "se": 0.0}}},
            },
        )
        path = self.path("with-bootstrap.json")
        self.run_table(path, 2, pairs=["A_A_Unsuited"], bootstrap=bootstrap)
        self.run_table(path, 3, pairs=["A_A_Unsuited"], bootstrap=bootstrap)
        with open(bootstrap, "a", encoding="utf-8") as destination:
            destination.write(" ")
        with self.assertRaises(ValueError):
            self.run_table(path, 3, pairs=["A_A_Unsuited"], bootstrap=bootstrap)
        iterative = self.path("iterative.json")
        self.run_table(iterative, 2, pairs=["A_A_Unsuited"], max_generations=2)
        with self.assertRaises(ValueError):
            self.run_table(iterative, 3, pairs=["A_A_Unsuited"], max_generations=2)

    def test_unbounded_stop_and_corrupt_in_memory_round(self):
        path = self.path("unbounded.json")
        args = run_args(path, None, infinite=True, seed=42, checkpoint_frequency=3)
        current = _V4Run(args, ["A_A_Unsuited"], generate_table)
        original = _sample_round

        def stop_after_vectors(*arguments):
            row = original(*arguments)
            current.request_stop(None, None)
            return row

        with patch(
            "artifact_pipeline.crib_v4._sample_round", side_effect=stop_after_vectors
        ):
            with self.assertRaises(SystemExit):
                current.execute()
        self.assertEqual(
            read_json(path)["__metadata__"]["run_control"]["mode"], "fixed_unbounded"
        )
        self.assertEqual(
            read_json(path)["__metadata__"]["estimator_state"]["A_A"]["Dealer"][
                "streams"
            ]["base"]["count"],
            1,
        )
        resumed = _V4Run(args, ["A_A_Unsuited"], generate_table)
        self.assertEqual(
            resumed.state["estimator_state"]["A_A"]["Dealer"]["streams"]["base"][
                "count"
            ],
            1,
        )
        current.pending_stop = True
        with self.assertRaises(SystemExit):
            current.execute()

        bad = self.path("partial.json")
        with patch("artifact_pipeline.crib_v4.add_row", return_value=None):
            with self.assertRaisesRegex(ValueError, "inconsistent"):
                self.run_table(bad, 2, pairs=["A_A_Unsuited"])
        self.assertEqual(
            read_json(bad)["__metadata__"]["estimator_state"]["A_A"]["Dealer"][
                "streams"
            ]["base"]["count"],
            0,
        )

    def test_iterative_convergence_and_failure_boundaries(self):
        # A three-generation cap distinguishes convergence at 1 from the cap at 2.
        for threshold, expected_generation in ((1e9, 1), (0.0, 2)):
            with self.subTest(threshold=threshold):
                path = self.path(f"convergence-{threshold}.json")
                output = self.run_table(
                    path,
                    2,
                    pairs=["A_A_Unsuited"],
                    max_generations=3,
                    convergence_threshold=threshold,
                )
                self.assertEqual(
                    output["__metadata__"]["generation"],
                    expected_generation,
                    "convergence and hard-cap outcomes must be distinguishable",
                )
        failing = self.path("failing.json")
        with self.assertRaises(RuntimeError):
            self.run_table(
                failing,
                2,
                pairs=["A_A_Unsuited"],
                max_generations=1,
                convergence_threshold=0.0,
                fail_on_non_convergence=True,
            )

    def test_unequal_stream_counts_and_stop_before_transition(self):
        path = self.path("unequal.json")
        self.run_table(path, 2, pairs=["A_A_Unsuited"])
        altered = read_json(path)
        base = altered["__metadata__"]["estimator_state"]["A_A"]["Dealer"]["streams"][
            "base"
        ]
        suit = altered["__metadata__"]["estimator_state"]["A_A"]["Dealer"]["streams"][
            "suit"
        ]
        suit["count"] = 1
        suit["next_index"] = 1
        suit["sum_x"] = ["0"] * len(suit["labels"])
        suit["sum_xx_upper"] = []
        self.assertEqual(base["count"], 2)
        write_json(path, altered)
        with self.assertRaisesRegex(ValueError, "unequal active stream counts"):
            self.run_table(path, 2, pairs=["A_A_Unsuited"])

        pending = self.path("stop-pending.json")
        args = run_args(pending, 2, max_generations=2)
        current = _V4Run(args, ["A_A_Unsuited"], generate_table)
        checkpoint = current.checkpoint

        def stop_at_pending():
            result = checkpoint()
            if current.state["phase"] == "transition_pending":
                current.request_stop(None, None)
            return result

        with patch.object(current, "checkpoint", side_effect=stop_at_pending):
            with self.assertRaises(SystemExit):
                current.execute()
        self.assertEqual(
            read_json(pending)["__metadata__"]["phase"], "transition_pending"
        )


class TestV4IntegrationInvariants(V4CheckpointFixture):
    """Connect v4 projections, policy boundaries, and seeds to their contracts."""

    def test_suited_projections_match_core_with_nonzero_residual(self):
        """Tie saved v4 means to the core oracle using its seed-43 scorer."""
        group = _physical_group("A_2", generate_table)
        centers = centering_values(group, _rank_scores)
        hands = {
            stream: sample_hand(group, stream, Random(seed))
            for stream, seed in (("base", 42), ("residual", 43), ("suit", 44))
        }
        observations = (
            base_observation(group, hands["base"], _scale_crib_scores),
            residual_observation(group, hands["residual"], _scale_crib_scores),
            suit_observation(group, hands["suit"], _scale_crib_scores, centers),
        )
        self.assertTrue(
            any(observations[1].values()), "fixture residual must be nonzero"
        )
        # Repeat each core fixture row twice so the real checkpoint has N=2.
        with patch("artifact_pipeline.crib_v4._centers", return_value=centers), patch(
            "artifact_pipeline.crib_v4._score_deal", return_value=_scale_crib_scores
        ), patch(
            "artifact_pipeline.crib_v4.sample_hand",
            side_effect=lambda _group, stream, _rng: hands[stream],
        ):
            output = self.run_table(
                self.path("oracle-projection.json"),
                pairs=["A_2_Suited", "A_2_Unsuited"],
                no_client_output=True,
            )
        for cut, relation_name in bucket_populations(group, "Suited"):
            expected = reconstruct(observations, "Suited", cut, relation_name)
            actual = output["A_2_Suited"]["Dealer"][generate_table.Index.indices[cut]]
            if relation_name != ROOT:
                actual = actual["starter_suit_relation"][relation_name]
            for category, value in expected.items():
                with self.subTest(cut=cut, relation=relation_name, category=category):
                    self.assertEqual(
                        actual["points"][category]["mu"],
                        float(value),
                        "v4 suited means must include the core residual",
                    )
            self.assertEqual(actual["mu"], float(expected["total"]))

    def test_transition_resets_moments_under_new_policy(self):
        """A fresh-versus-resumed comparison cannot by itself detect pooling."""
        path = self.path("transition-moments.json")
        current = _V4Run(
            run_args(path, max_generations=2), ["A_A_Unsuited"], generate_table
        )
        current.sample_pass()
        previous = read_json(path)["__metadata__"]
        self.assertEqual(previous["generation"], 0)
        _transition(current.state, generate_table)
        transitioned = current.checkpoint()["__metadata__"]
        self.assertEqual(transitioned["generation"], 1)
        self.assertNotEqual(transitioned["policy_sha256"], previous["policy_sha256"])
        for roles in transitioned["estimator_state"].values():
            for role, entry in roles.items():
                for stream, moments in entry["streams"].items():
                    with self.subTest(role=role, stream=stream):
                        self.assertEqual(
                            moments["count"], 0, "new policy must start with zero rows"
                        )
                        self.assertEqual(moments["next_index"], 0)
                        self.assertEqual(set(moments["sum_x"]), {"0"})
                        self.assertEqual(moments["sum_xx_upper"], [])
        current.execute()
        actual = read_json(path)["__metadata__"]
        fresh = self.run_table(
            self.path("transition-fresh.json"),
            pairs=["A_A_Unsuited"],
            max_generations=2,
        )["__metadata__"]
        self.assertNotEqual(actual["estimator_state"], previous["estimator_state"])
        self.assertEqual(actual["policy_sha256"], fresh["policy_sha256"])
        self.assertEqual(actual["generation"], fresh["generation"])
        self.assertEqual(actual["estimator_state"], fresh["estimator_state"])

    def test_row_seed_identity_and_suit_index_are_golden(self):
        """Pin the contract's seed JSON through the real sampling-round caller."""
        current = _V4Run(
            run_args(self.path("golden-row.json")),
            ["A_2_Suited", "A_2_Unsuited"],
            generate_table,
        )
        current.state.update(generation=3, policy_sha256="ab" * 32)
        for moments in current.state["estimator_state"]["A_2"]["Dealer"][
            "streams"
        ].values():
            moments.update(count=7, next_index=7)
        # These literal fields come from the approved eight-field row identity.
        prefix = (
            '["shared-rank-relation-v1",["seed",42],3,"'
            + "ab" * 32
            + '","A_2","Dealer",'
        )
        with patch("artifact_pipeline.crib_v4.random.Random", wraps=Random) as factory:
            _sample_round(
                current.state,
                ("A_2", "Dealer"),
                _physical_group("A_2", generate_table),
                generate_table,
                None,
            )
        self.assertEqual(factory.call_count, 3)
        for call, stream in zip(factory.call_args_list, ("base", "residual", "suit")):
            with self.subTest(stream=stream):
                self.assertEqual(
                    call.args,
                    (f'{prefix}"{stream}",7]',),
                    f"{stream} row seed must preserve all eight fields and index 7",
                )


if __name__ == "__main__":
    unittest.main()
