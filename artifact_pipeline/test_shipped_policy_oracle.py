"""Bounded unit oracle for shipped geometric training and enforced measurement."""

import hashlib
import json
from pathlib import Path
import random
import tempfile
import unittest

from artifact_pipeline.generate_play_table import (
    GENERATION_METHOD,
    _empty_entry_accumulators,
    _record_result,
    _entry_to_output,
    _write_json,
    build_client_table,
)
from artifact_pipeline.export_uncertainty import export_files
from artifact_pipeline.pegging import (
    ROLES,
    PONE,
    canonical_hand_key,
    simulate_pegging,
    train_iterative_best_response,
)
from artifact_pipeline.play_lines import build_lines
from artifact_pipeline.promotion_gate import promotion_gate
from artifact_pipeline.test_geometric_compatibility import sample_physical_ranks

SOURCE = "a775cff92a21d7f0c921dd3529d7f7e798f2d6d3"


def unit_measurements(policies):
    """Sixteen deterministic unit cases, not a generation or quality experiment."""
    entries, traces = {}, []
    for hand_index, hand in enumerate(((0, 1, 2, 3), (4, 5, 6, 7))):
        entries[canonical_hand_key(hand)] = {}
        for role_index, role in enumerate(ROLES):
            accumulators = _empty_entry_accumulators()
            for index, opponent in enumerate(
                ((8, 9, 10, 11), (0, 4, 8, 12), (2, 5, 7, 10), (1, 6, 9, 11))
            ):
                rng = random.Random(1000 + 100 * hand_index + 10 * role_index + index)
                pone, dealer = (hand, opponent) if role == PONE else (opponent, hand)
                result = simulate_pegging(
                    pone, dealer, policies, rng, collect_decisions=True
                )
                _record_result(accumulators, role, result)
                traces.append(
                    {
                        "players": result.players,
                        "opening": result.opening,
                        "rng_sha256": hashlib.sha256(
                            repr(rng.getstate()).encode("utf-8")
                        ).hexdigest(),
                    }
                )
            entries[canonical_hand_key(hand)][role] = _entry_to_output(accumulators)
    return entries, traces


def shipped_oracle():
    trained, reports = None, []
    # Production's two outer training passes, then its final training pass.
    for seed in (42, 42, 44):
        trained, training = train_iterative_best_response(
            sample_physical_ranks,
            iterations=2,
            samples_per_role=24,
            rollouts_per_action=2,
            seed=seed,
            initial_policies=trained,
            averaging="geometric",
            workers=1,
        )
        reports.append(training)
    measured, gate = promotion_gate(trained, "enforce", 64, 42, 1)
    _, trained_traces = unit_measurements(trained)
    full, measured_traces = unit_measurements(measured)
    full["__metadata__"] = {
        "generation_method": GENERATION_METHOD,
        "generated_at": "2026-10-05T00:00:00+00:00",
        "seed": 42,
        "policy_fingerprint": gate["measured_policy_fingerprint"],
        "joint_policy_converged": False,
        "measured_policy": gate["measured_policy"],
        "policy_averaging": (
            None if gate["measured_policy"] == "legacy-heuristic" else "geometric"
        ),
        "promotion_gate": gate,
    }
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _write_json(str(root / "full.json"), full)
        _write_json(str(root / "client.json"), build_client_table(full), compact=True)
        _write_json(
            str(root / "lines.json"),
            build_lines(full, (root / "client.json").read_bytes()),
            compact=True,
        )
        export_files(
            "play", root / "full.json", root / "client.json", root / "sidecar.json"
        )
        hashes = {
            name: hashlib.sha256((root / (name + ".json")).read_bytes()).hexdigest()
            for name in ("full", "client", "lines", "sidecar")
        }
    return {
        "training_reports": reports,
        "gate": gate,
        "trained_traces_sha256": hashlib.sha256(
            json.dumps(trained_traces, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "measured_traces_sha256": hashlib.sha256(
            json.dumps(measured_traces, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "artifact_sha256": hashes,
    }


class TestShippedPolicyOracle(unittest.TestCase):
    def test_geometric_enforce_matches_pre_fix_unit_bytes(self):
        fixture = json.loads(
            Path(__file__)
            .with_name("fixtures")
            .joinpath("geometric_enforce_before_tabular_fix.json")
            .read_bytes()
        )
        self.assertEqual(fixture["source_commit"], SOURCE)
        self.assertEqual(
            fixture["source_pegging_sha256"],
            "e9bb6ea52056678ba858060d3e18ccae83529c4a16472ad6fcd3888cbc1fce1b",
        )
        self.assertEqual(shipped_oracle(), fixture["oracle"])


if __name__ == "__main__":
    unittest.main()
