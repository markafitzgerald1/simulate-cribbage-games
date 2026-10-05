"""Enforced fallback refines and measures one model; other modes retain bytes."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from artifact_pipeline import generate_play_table as generator
from artifact_pipeline.promotion_gate import validate_promotion_resume
from artifact_pipeline.pegging import (
    ROLES,
    POINT_TYPES,
    LegacyHeuristicPolicy,
    TabularPeggingPolicy,
    policy_fingerprint,
)

FIXTURE = Path(__file__).with_name("fixtures") / "promotion_modes_192.json"


def context(index=0):
    return generator.AnalyticalContext(
        [1.0], [1.0], [], {}, [], [], [((0, 0, 1, 1, 2, 3), index, index)]
    )


def measured_fixture(kwargs, mean):
    # Precomputed moments, with real full/client/lines writers; no sampling.
    scalar = {"n": 2, "mu": mean, "se": 0.0, "moment_2": 0.0}
    return {
        "__metadata__": {
            "generation_method": generator.GENERATION_METHOD,
            "generated_at": "2026-10-05T00:00:00+00:00",
            "seed": kwargs["seed"],
            "policy_fingerprint": kwargs.get("play_policy_fingerprint"),
        },
        "A_2_3_4": {
            role: {
                **scalar,
                "opening": {
                    "0": {"n": 2, "mean": mean, "moment_2": 0.0, "responses": {"1": 2}}
                },
                "players": {
                    seat: {
                        **scalar,
                        "points": {point: dict(scalar) for point in POINT_TYPES},
                    }
                    for seat in ROLES
                },
            }
            for role in ROLES
        },
    }


def run_fixture(directory, mode, **options):
    settings = SimpleNamespace(
        outer=5,
        strict=False,
        passed=False,
        heuristic_changes=(2, 3, 3, 3, 3),
        heuristic_means=(0.2, 0.6, 0.6, 0.6, 0.6),
    )
    settings.__dict__.update(options)
    initial = context()
    events = {
        "samples": [],
        "refinements": [],
        "training": [],
        "gate": [],
        "checkpoints": [],
    }
    training_count = 0
    heuristic_count = 0

    def train(*args, **kwargs):
        nonlocal training_count
        del args
        training_count += 1
        previous = kwargs["initial_policies"] or {
            role: LegacyHeuristicPolicy() for role in ROLES
        }
        policies = {
            role: TabularPeggingPolicy(
                {str(training_count): training_count % 4}, previous[role]
            )
            for role in ROLES
        }
        events["training"].append(kwargs["seed"])
        return policies, [{"fixture_response": training_count}]

    def sample(discard, policies, **kwargs):
        nonlocal heuristic_count
        legacy = all(isinstance(p, LegacyHeuristicPolicy) for p in policies.values())
        final = "checkpoint" in kwargs
        if legacy and not final:
            mean = settings.heuristic_means[heuristic_count]
            heuristic_count += 1
        else:
            mean = 0.5 if len(events["samples"]) == 0 else 1.0
        table = measured_fixture(kwargs, mean)
        events["samples"].append((discard, policies, kwargs, legacy, final))
        if final:
            kwargs["checkpoint"](table)
            events["checkpoints"].append(
                json.loads((directory / "full.json").read_bytes())
            )
        return table

    def refine(current, table):
        sample_record = events["samples"][-1]
        index = (
            settings.heuristic_changes[heuristic_count - 1] if sample_record[3] else 1
        )
        next_context = context(index)
        changed = int(current.selected_discards != next_context.selected_discards)
        events["refinements"].append((current, table, sample_record))
        return next_context, changed, 0.25 if changed else 0.0

    def evaluate(policies, deals, seed, workers):
        events["gate"].append((policies, deals, seed, workers))
        return {
            "passed": settings.passed,
            "both_seats": {"n": deals, "mu": -1.0, "se": 0.1},
        }

    argv = [
        "generate_play_table.py",
        "--no-resume",
        "--hand-limit=1",
        "--workers=1",
        "--promotion-gate-deals=2",
        "--promotion-gate=" + mode,
        "--outer-iterations=" + str(settings.outer),
        "--output=" + str(directory / "full.json"),
        "--client-output=" + str(directory / "client.json"),
        "--lines-output=" + str(directory / "lines.json"),
    ]
    if settings.strict:
        argv.append("--fail-on-non-convergence")
    with patch("sys.argv", argv), patch.object(
        generator, "solve_initial_discard_policy", return_value=initial
    ), patch.object(
        generator, "train_iterative_best_response", side_effect=train
    ), patch.object(
        generator, "generate_play_table", side_effect=sample
    ), patch.object(
        generator, "refine_discard_policy", side_effect=refine
    ), patch(
        "artifact_pipeline.promotion_gate.evaluate_promotion", side_effect=evaluate
    ), patch(
        "builtins.print"
    ):
        generator.main()
    return events, {
        name: (directory / (name + ".json")).read_bytes()
        for name in ("full", "client", "lines")
    }


class TestEnforcedDiscards(unittest.TestCase):
    def test_failed_enforce_restarts_analytical_and_refines_the_measured_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            events, outputs = run_fixture(Path(directory), "enforce", strict=True)
        heuristic = [
            record for record in events["samples"] if record[3] and not record[4]
        ]
        self.assertEqual(len(heuristic), 4)
        final_discard, final_policies, _, _, final = events["samples"][-1]
        self.assertTrue(final)
        self.assertTrue(all(record[1] is final_policies for record in heuristic))
        self.assertEqual(
            heuristic[0][0],
            generator.selected_discards_to_policy(context().selected_discards),
        )
        self.assertEqual(
            final_discard,
            generator.selected_discards_to_policy(context(3).selected_discards),
        )
        self.assertTrue(all(record[2]["seed"] == 42 for record in heuristic))
        self.assertTrue(all(record[2]["samples"] == 200 for record in heuristic))
        self.assertEqual(
            len(events["training"]), 5
        )  # Four trained outer passes plus final IBR.
        self.assertEqual(len(events["gate"]), 1)
        metadata = json.loads(outputs["full"])["__metadata__"]
        self.assertTrue(metadata["joint_policy_converged"])
        provenance = metadata["promotion_gate"]["discard_refinement"]
        self.assertEqual(
            events["checkpoints"][0]["__metadata__"]["promotion_gate"][
                "discard_refinement"
            ],
            provenance,
        )
        self.assertEqual(provenance["policy"], "legacy-heuristic")
        # Known digest of both measured (0, 1, 1, 2) keeps; analytical keeps differ.
        self.assertEqual(
            provenance["discard_policy_fingerprint"],
            "3b1de804bb6b0b8e15d8bae6f03abfb734c2338623993e495234904f5575e1bc",
        )
        self.assertEqual(provenance["initialization"], "analytical")
        self.assertTrue(provenance["converged"])
        self.assertEqual(len(provenance["outer_iterations"]), 4)
        self.assertEqual(
            provenance["policy_fingerprint"], metadata["policy_fingerprint"]
        )
        self.assertEqual(
            provenance["policy_fingerprint"],
            ":".join(policy_fingerprint(final_policies[r]) for r in ROLES),
        )

    def test_actual_fallback_convergence_resets_and_controls_strict_failure(self):
        # A stable step interrupted by a policy-table shift must reset the streak.
        with tempfile.TemporaryDirectory() as directory:
            events, outputs = run_fixture(
                Path(directory),
                "enforce",
                outer=7,
                heuristic_changes=(2,) * 7,
                heuristic_means=(0.2, 0.2, 0.8, 0.8, 0.8, 0.8, 0.8),
            )
        heuristic = [
            record for record in events["samples"] if record[3] and not record[4]
        ]
        self.assertEqual(len(heuristic), 5)
        self.assertTrue(
            json.loads(outputs["full"])["__metadata__"]["joint_policy_converged"]
        )
        with tempfile.TemporaryDirectory() as directory:
            events, outputs = run_fixture(Path(directory), "enforce", outer=2)
            self.assertFalse(
                json.loads(outputs["full"])["__metadata__"]["joint_policy_converged"]
            )
        with tempfile.TemporaryDirectory() as directory:
            _, outputs = run_fixture(
                Path(directory), "enforce", heuristic_changes=(2, 3, 2, 3, 2)
            )
        self.assertFalse(
            json.loads(outputs["full"])["__metadata__"]["joint_policy_converged"]
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "did not converge"):
                run_fixture(
                    Path(directory),
                    "enforce",
                    strict=True,
                    heuristic_changes=(2, 3, 2, 3, 2),
                )
            self.assertFalse(Path(directory, "full.json").exists())

    def test_passing_enforce_retains_trained_refinement_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            events, outputs = run_fixture(Path(directory), "enforce", passed=True)
        self.assertFalse(any(record[3] for record in events["samples"]))
        gate = json.loads(outputs["full"])["__metadata__"]["promotion_gate"]
        self.assertEqual(gate["discard_refinement"]["policy"], "trained")
        last_refined = events["refinements"][-1][2][1]
        self.assertEqual(
            gate["discard_refinement"]["policy_fingerprint"],
            ":".join(policy_fingerprint(last_refined[r]) for r in ROLES),
        )

    def test_report_and_off_artifact_bytes_match_reviewed_head(self):
        fixture = json.loads(FIXTURE.read_bytes())
        for mode in ("report", "off"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                events, outputs = run_fixture(Path(directory), mode)
            self.assertEqual(
                {
                    name: hashlib.sha256(data).hexdigest()
                    for name, data in outputs.items()
                },
                fixture[mode],
            )
            self.assertEqual(events["training"], [42, 42, 42, 42, 47])
            self.assertFalse(any(record[3] for record in events["samples"]))
            self.assertNotIn(
                "discard_refinement",
                json.loads(outputs["full"])["__metadata__"]["promotion_gate"],
            )


class TestDiscardResume(unittest.TestCase):
    def test_fallback_resume_requires_current_discard_model_and_population(self):
        current = {
            "mode": "enforce",
            "measured_policy": "legacy-heuristic",
            "training_context_fingerprint": "trained-context",
            "discard_refinement": {
                "method": "fixed-play-v1",
                "policy_fingerprint": "legacy",
                "discard_policy_fingerprint": "actual-keeps",
            },
        }
        previous = {"__metadata__": {"promotion_gate": deepcopy(current)}}
        validate_promotion_resume(previous, current)
        for field in (
            "discard_refinement",
            "method",
            "policy_fingerprint",
            "discard_policy_fingerprint",
        ):
            changed = deepcopy(previous)
            gate = changed["__metadata__"]["promotion_gate"]
            if field == "discard_refinement":
                gate.pop(field)
            else:
                gate["discard_refinement"][field] = "different"
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, "promotion.*context"
            ):
                validate_promotion_resume(changed, current)
        bad = deepcopy(current)
        bad.pop("discard_refinement")
        with self.assertRaisesRegex(ValueError, "promotion.*context"):
            validate_promotion_resume(previous, bad)

    def test_fallback_resume_rejects_incomplete_refinement_identity(self):
        current = {
            "mode": "enforce",
            "measured_policy": "legacy-heuristic",
            "training_context_fingerprint": "same-context",
        }
        previous = {"__metadata__": {"promotion_gate": deepcopy(current)}}
        for invalid in (
            {},
            {
                "method": "",
                "policy_fingerprint": "legacy",
                "discard_policy_fingerprint": "keeps",
            },
            {
                "method": 1,
                "policy_fingerprint": "legacy",
                "discard_policy_fingerprint": "keeps",
            },
        ):
            current["discard_refinement"] = invalid
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                ValueError, "promotion.*context"
            ):
                validate_promotion_resume(previous, current)
