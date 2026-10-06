"""Enforce: a failed gate refines and measures with the heuristic, and says so."""

import itertools
import json
import tempfile
import unittest
from unittest.mock import patch

from artifact_pipeline import generate_play_table as generator
from artifact_pipeline.export_uncertainty import (
    LEGACY_HEURISTIC_FINGERPRINT,
    build_sidecar,
    decode_sidecar,
    encode_json,
)
from artifact_pipeline.generate_play_table import (
    DiscardPolicy,
    discard_keeps_fingerprint,
    generate_play_table,
    validate_resume_table,
)
from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    ROLES,
    LegacyHeuristicPolicy,
    policy_fingerprint,
)
from artifact_pipeline.play_lines import decode_lines
from artifact_pipeline.test_generate_play_table import FirstPolicy
from artifact_pipeline.test_promotion_gate import (
    CONTEXT,
    run_bounded_generation,
)

ANALYTICAL, TRAINED_REFINED, HEURISTIC_REFINED = 0, 1, 2


def keeping(start):
    """Keep four consecutive sorted ranks from every deal, from one offset."""
    mapping = {}
    for hand in itertools.combinations_with_replacement(range(13), 6):
        if max(hand.count(rank) for rank in set(hand)) <= 4:
            for role in ROLES:
                mapping[(role, hand)] = hand[start : start + 4]
    return DiscardPolicy(mapping)


DISCARD_POLICIES = {
    ANALYTICAL: keeping(0),
    TRAINED_REFINED: keeping(2),
    HEURISTIC_REFINED: keeping(1),
}


def tagged_context(tag):
    return generator.AnalyticalContext(
        [1.0], [1.0], [], {}, [], [], [((0, 0, 0, 0, 1, 1), tag, tag)]
    )


def is_heuristic(policies):
    return all(isinstance(policies[role], LegacyHeuristicPolicy) for role in ROLES)


class EnforcedRun:  # pylint: disable=too-few-public-methods
    """A small real generation whose discard steps are labelled stand-ins.

    Refinement returns a context tagged by the pegging model of the play
    table it was given, and each tag maps to its own discard policy, so the
    measured keeps reveal which play model refined them.
    """

    def __init__(self, passed, arguments=()):
        self.events = []
        self.heuristic_tables = set()
        real_sample = generator.generate_play_table

        def sample(discard_policy, policies, **kwargs):
            table = real_sample(discard_policy, policies, **kwargs)
            kind = "final" if "checkpoint" in kwargs else "table"
            self.events.append((kind, policies, discard_policy))
            if is_heuristic(policies):
                self.heuristic_tables.add(id(table))
            return table

        def refine(context, table):
            self.events.append(("refine", context, id(table)))
            tag = (
                HEURISTIC_REFINED
                if id(table) in self.heuristic_tables
                else TRAINED_REFINED
            )
            # A trained refinement always reports a change, so only the
            # heuristic refinement can converge.
            changed = int(
                tag == TRAINED_REFINED or context.selected_discards[0][1] != tag
            )
            return tagged_context(tag), changed, 0.0

        def gate(policies, deals, seed):
            self.events.append(("gate", policies, None))
            seat = {"n": deals, "mu": 0.5 if passed else -0.5, "se": 0.1}
            return {
                "deals": deals,
                "seed": seed,
                PONE: seat,
                DEALER: seat,
                "both_seats": seat,
                "passed": passed,
            }

        with tempfile.TemporaryDirectory() as directory:
            self.outputs, self.log = run_bounded_generation(
                directory,
                ["--promotion-gate-deals=2", "--outer-iterations=2", *arguments],
                patch.object(generator, "generate_play_table", sample),
                patch.object(generator, "refine_discard_policy", refine),
                patch.object(generator, "evaluate_promotion", gate),
                patch.object(
                    generator,
                    "selected_discards_to_policy",
                    lambda selected: DISCARD_POLICIES[selected[0][1]],
                ),
            )
        self.full = json.loads(self.outputs["full"])
        self.metadata = self.full["__metadata__"]

    def after_gate(self):
        names = [event[0] for event in self.events]
        return self.events[names.index("gate") + 1 :]

    def gated_policies(self):
        return next(event[1] for event in self.events if event[0] == "gate")


class TestFailedEnforce(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.enforced = EnforcedRun(passed=False, arguments=["--promotion-gate=enforce"])

    def test_refines_from_the_analytical_policy_with_heuristic_tables_only(self):
        after = self.enforced.after_gate()
        refinements = [event for event in after if event[0] == "refine"]
        self.assertEqual(len(refinements), 2)
        self.assertIs(refinements[0][1], CONTEXT)
        self.assertTrue(
            all(event[2] in self.enforced.heuristic_tables for event in refinements)
        )
        self.assertTrue(
            all(is_heuristic(event[1]) for event in after if event[0] != "refine")
        )

    def test_measures_the_heuristic_on_the_heuristic_refined_keeps(self):
        final = [event for event in self.enforced.events if event[0] == "final"]
        self.assertEqual(len(final), 1)
        self.assertTrue(is_heuristic(final[0][1]))
        self.assertIs(final[0][2], DISCARD_POLICIES[HEURISTIC_REFINED])
        heuristic = policy_fingerprint(LegacyHeuristicPolicy())
        self.assertEqual(
            self.enforced.metadata["policy_fingerprint"], f"{heuristic}:{heuristic}"
        )

    def test_labels_the_measured_policy_and_keeps_everywhere(self):
        metadata = self.enforced.metadata
        self.assertEqual(metadata["measured_policy"], "legacy-heuristic")
        self.assertEqual(
            metadata["discard_policy_fingerprint"],
            discard_keeps_fingerprint(DISCARD_POLICIES[HEURISTIC_REFINED]),
        )
        gate = metadata["promotion_gate"]
        self.assertEqual((gate["mode"], gate["passed"]), ("enforce", False))
        refinement = gate["discard_refinement"]
        self.assertEqual(
            (refinement["policy"], refinement["initialization"]),
            ("legacy-heuristic", "analytical"),
        )
        self.assertEqual(len(refinement["outer_iterations"]), 2)
        self.assertEqual(
            [report["play_ibr"] for report in refinement["outer_iterations"]],
            [[], []],
        )
        lines = decode_lines(
            self.enforced.outputs["lines"], self.enforced.outputs["client"]
        )
        sidecar = build_sidecar(
            "play", self.enforced.outputs["full"], self.enforced.outputs["client"]
        )
        for provenance in (lines["provenance"], sidecar["provenance"]):
            self.assertEqual(provenance["measured_policy"], "legacy-heuristic")
        self.assertTrue("legacy heuristic" in self.enforced.log)

    def test_validators_reject_malformed_measured_policies(self):
        outputs = self.enforced.outputs
        lines = json.loads(outputs["lines"])
        sidecar = build_sidecar("play", outputs["full"], outputs["client"])
        for value in ("heuristic", "", None, 1, True, ["trained"], {"trained": 1}):
            lines["provenance"]["measured_policy"] = value
            sidecar["provenance"]["measured_policy"] = value
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "measured pegging policy"):
                    decode_lines(json.dumps(lines).encode(), outputs["client"])
                # Containers already fail the sidecar's scalar-provenance rule.
                with self.assertRaisesRegex(
                    ValueError, "measured pegging policy|scalar values only"
                ):
                    decode_sidecar(encode_json(sidecar), outputs["client"])
        full = json.loads(outputs["full"])
        full["__metadata__"]["measured_policy"] = "heuristic"
        with self.assertRaisesRegex(ValueError, "measured pegging policy"):
            build_sidecar("play", encode_json(full), outputs["client"])
        for value in ("legacy-heuristic", "absent"):
            if value == "absent":
                del lines["provenance"]["measured_policy"]
                del sidecar["provenance"]["measured_policy"]
            else:
                lines["provenance"]["measured_policy"] = value
                sidecar["provenance"]["measured_policy"] = value
            decode_lines(json.dumps(lines).encode(), outputs["client"])
            decode_sidecar(encode_json(sidecar), outputs["client"])

    def test_points_at_the_refinement_it_measured(self):
        self.assertEqual(
            self.enforced.metadata["measured_discard_refinement"],
            "promotion_gate.discard_refinement",
        )


class TestMeasuredPolicyMatchesFingerprint(unittest.TestCase):
    def test_label_must_agree_with_the_policy_fingerprint(self):
        self.assertEqual(
            LEGACY_HEURISTIC_FINGERPRINT,
            policy_fingerprint(LegacyHeuristicPolicy()),
        )
        failed = EnforcedRun(passed=False, arguments=["--promotion-gate=enforce"])
        passed = EnforcedRun(passed=True, arguments=["--promotion-gate=enforce"])
        self.assertEqual(
            passed.metadata["measured_discard_refinement"], "outer_iterations"
        )
        for run, wrong in ((failed, "trained"), (passed, "legacy-heuristic")):
            outputs = run.outputs
            decode_lines(outputs["lines"], outputs["client"])
            sidecar = build_sidecar("play", outputs["full"], outputs["client"])
            lines = json.loads(outputs["lines"])
            lines["provenance"]["measured_policy"] = wrong
            sidecar["provenance"]["measured_policy"] = wrong
            with self.subTest(wrong=wrong):
                with self.assertRaisesRegex(ValueError, "measured pegging policy"):
                    decode_lines(json.dumps(lines).encode(), outputs["client"])
                with self.assertRaisesRegex(ValueError, "measured pegging policy"):
                    decode_sidecar(encode_json(sidecar), outputs["client"])


class TestResumeAcrossModes(unittest.TestCase):
    def test_report_and_off_drop_enforced_labels_from_a_resumed_table(self):
        def passing_gate(_policies, deals, seed):
            seat = {"n": deals, "mu": 0.5, "se": 0.1}
            return {
                "deals": deals,
                "seed": seed,
                PONE: seat,
                DEALER: seat,
                "both_seats": seat,
                "passed": True,
            }

        gate = patch.object(generator, "evaluate_promotion", passing_gate)
        enforced_only = (
            "measured_policy",
            "discard_policy_fingerprint",
            "measured_discard_refinement",
        )
        for mode in ("report", "off"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                first, _ = run_bounded_generation(
                    directory, ["--promotion-gate=enforce"], gate
                )
                self.assertTrue(
                    all(
                        name in json.loads(first["full"])["__metadata__"]
                        for name in enforced_only
                    )
                )
                outputs, _ = run_bounded_generation(
                    directory, [f"--promotion-gate={mode}"], gate, resume=True
                )
                metadata = json.loads(outputs["full"])["__metadata__"]
                self.assertFalse(any(name in metadata for name in enforced_only))
                self.assertEqual(
                    metadata.get("promotion_gate", {}).get("mode", "off"), mode
                )
                lines = decode_lines(outputs["lines"], outputs["client"])
                self.assertFalse("measured_policy" in lines["provenance"])


class TestEnforceAgainstReport(unittest.TestCase):
    def test_passing_enforce_measures_what_report_measures(self):
        report = EnforcedRun(passed=True)
        enforced = EnforcedRun(passed=True, arguments=["--promotion-gate=enforce"])
        self.assertEqual([event[0] for event in enforced.after_gate()], ["final"])
        final = enforced.after_gate()[0]
        self.assertIs(final[1], enforced.gated_policies())
        self.assertIs(final[2], DISCARD_POLICIES[TRAINED_REFINED])
        self.assertEqual(enforced.outputs["client"], report.outputs["client"])
        metadata = enforced.full.pop("__metadata__")
        report_metadata = report.full.pop("__metadata__")
        self.assertEqual(enforced.full, report.full)
        self.assertEqual(metadata["measured_policy"], "trained")
        self.assertEqual(
            metadata["discard_policy_fingerprint"],
            discard_keeps_fingerprint(DISCARD_POLICIES[TRAINED_REFINED]),
        )
        self.assertFalse("discard_refinement" in metadata["promotion_gate"])
        self.assertFalse("measured_policy" in report_metadata)
        self.assertFalse("discard_policy_fingerprint" in report_metadata)
        lines = json.loads(enforced.outputs["lines"])
        self.assertEqual(lines["provenance"].pop("measured_policy"), "trained")
        self.assertEqual(lines, json.loads(report.outputs["lines"]))

    def test_report_does_not_act_on_a_failed_gate(self):
        report = EnforcedRun(passed=False)
        self.assertEqual([event[0] for event in report.after_gate()], ["final"])
        self.assertIs(report.after_gate()[0][1], report.gated_policies())
        self.assertFalse("measured_policy" in report.metadata)


class TestEnforcedConvergence(unittest.TestCase):
    def test_fallback_convergence_is_what_is_reported_and_required(self):
        # Four passes let the deterministic heuristic refinement settle while
        # the trained refinement never does.
        run = EnforcedRun(
            passed=False,
            arguments=[
                "--promotion-gate=enforce",
                "--outer-iterations=4",
                "--fail-on-non-convergence",
            ],
        )
        trained_passes = run.metadata["outer_iterations"][:-1]
        self.assertEqual(len(trained_passes), 4)
        self.assertTrue(
            all(report["changed_discards"] == 1 for report in trained_passes)
        )
        self.assertTrue(run.metadata["joint_policy_converged"])
        self.assertTrue(
            run.metadata["promotion_gate"]["discard_refinement"]["converged"]
        )

    def test_enforce_requires_the_measured_refinement_to_converge(self):
        for passed in (False, True):
            with self.subTest(passed=passed), self.assertRaisesRegex(
                RuntimeError, "did not converge"
            ):
                EnforcedRun(
                    passed=passed,
                    arguments=["--promotion-gate=enforce", "--fail-on-non-convergence"],
                )


class TestDiscardResumeIdentity(unittest.TestCase):
    def test_fingerprint_follows_the_keeps_not_their_order(self):
        first = DiscardPolicy({(PONE, (0, 1, 2, 3, 4, 5)): (0, 1, 2, 3)})
        reordered = DiscardPolicy(
            dict(
                reversed(
                    list(DISCARD_POLICIES[ANALYTICAL].kept_by_role_and_hand.items())
                )
            )
        )
        self.assertEqual(
            discard_keeps_fingerprint(reordered),
            discard_keeps_fingerprint(DISCARD_POLICIES[ANALYTICAL]),
        )
        self.assertEqual(
            len(
                {
                    discard_keeps_fingerprint(policy)
                    for policy in DISCARD_POLICIES.values()
                }
            ),
            3,
        )
        self.assertEqual(
            discard_keeps_fingerprint(first),
            "1ca58a22fc00a1afc2d8d9f5bb3dbdf3d5902fcfbc3c3c12c4ef95bbc98585ed",
        )

    def test_resume_requires_the_same_measured_keeps(self):
        policies = {PONE: FirstPolicy(), DEALER: FirstPolicy()}
        table = generate_play_table(
            DISCARD_POLICIES[ANALYTICAL],
            policies,
            samples=2,
            seed=42,
            hands=[(0, 1, 2, 3)],
            discard_policy_fingerprint="analytical keeps",
        )
        self.assertEqual(
            table["__metadata__"]["discard_policy_fingerprint"], "analytical keeps"
        )
        with self.assertRaisesRegex(ValueError, "different discard keeps"):
            generate_play_table(
                DISCARD_POLICIES[ANALYTICAL],
                policies,
                samples=3,
                seed=42,
                hands=[(0, 1, 2, 3)],
                existing_table=table,
                discard_policy_fingerprint="refined keeps",
            )
        resumed = generate_play_table(
            DISCARD_POLICIES[ANALYTICAL],
            policies,
            samples=3,
            seed=42,
            hands=[(0, 1, 2, 3)],
            existing_table=table,
            discard_policy_fingerprint="analytical keeps",
        )
        self.assertEqual(resumed["A_2_3_4"][PONE]["n"], 3)
        validate_resume_table(table, 42)
        without = {"__metadata__": dict(table["__metadata__"])}
        del without["__metadata__"]["discard_policy_fingerprint"]
        with self.assertRaisesRegex(ValueError, "different discard keeps"):
            validate_resume_table(without, 42, None, "analytical keeps")


if __name__ == "__main__":
    unittest.main()
