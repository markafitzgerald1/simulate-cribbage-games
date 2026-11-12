"""Measure a fixed CFR policy in both seats with the existing Python v3 path."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from artifact_pipeline.fixed_play_inputs import load_fixed_discards
from artifact_pipeline.export_uncertainty import build_sidecar, encode_json
from artifact_pipeline.generate_play_table import (
    build_client_table,
    discard_keeps_fingerprint,
    generate_play_table,
    positive_int,
    promotion_gate_metadata,
    _write_json,
    _write_lines,
)
from artifact_pipeline.pegging import ROLES, get_canonical_hands, policy_fingerprint
from artifact_pipeline.play_measurement_jobs import (
    CellWorker,
    MeasurementJobs,
    measure_cells,
    sampler_digest,
)
from artifact_pipeline.promotion_gate import DEFAULT_GATE_DEALS, MINIMUM_GATE_DEALS
from artifact_pipeline.six_layer_policy import (
    SixLayerPolicy,
    read_manifest,
)


@dataclass(frozen=True)
class GateSettings:
    """Keep the unmodified gate's mode and deal budget together."""

    mode: str = "report"
    deals: int = DEFAULT_GATE_DEALS


def measure_fixed_table(
    manifest_path: Path,
    samples: int,
    seed: int,
    hands: Sequence[tuple[int, ...]] | None = None,
    gate: GateSettings = GateSettings(),
) -> dict[str, Any]:
    """Retain the original serial entry point as a reference path."""
    return _measure_fixed(
        manifest_path, MeasurementRequest(samples, seed, hands), gate, None
    )


@dataclass(frozen=True)
class MeasurementRequest:
    """Observation inputs, independent of worker scheduling."""

    samples: int
    seed: int
    hands: Sequence[tuple[int, ...]] | None = None


def measure_fixed_parallel(
    manifest_path: Path,
    request: MeasurementRequest,
    gate: GateSettings,
    jobs: MeasurementJobs,
) -> dict[str, Any]:
    """Measure single-owner streams with explicit pinned execution settings."""
    return _measure_fixed(manifest_path, request, gate, jobs)


def _parallel_cells(
    worker: CellWorker,
    request: MeasurementRequest,
    jobs: MeasurementJobs,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    requested = sorted(
        request.hands if request.hands is not None else get_canonical_hands()
    )
    canonical = get_canonical_hands()
    if len(set(requested)) != len(requested) or any(
        hand not in canonical for hand in requested
    ):
        raise ValueError("Measurement hands must be unique canonical keeps")
    binding = {
        "schema": "fixed-play-complete-cells.v1",
        "generation_method": metadata["generation_method"],
        "sampler_sha256": sampler_digest(),
        "policy_manifest_sha256": metadata["policy_manifest_sha256"],
        "policy_fingerprint": metadata["policy_fingerprint"],
        "discard_policy_fingerprint": metadata["discard_policy_fingerprint"],
        "seed": request.seed,
        "samples": request.samples,
        "promotion_gate": metadata.get("promotion_gate", {}),
        "hands": [list(hand) for hand in requested],
        "generated_at": jobs.generated_at,
    }
    cells, counts = measure_cells(worker.policy_path, binding, jobs, worker)
    return {
        "cells": cells,
        "counts": counts,
        "generated_at": jobs.generated_at,
        "hand_count": len(requested),
        "sampler_sha256": binding["sampler_sha256"],
    }


def _measure_fixed(
    manifest_path: Path,
    request: MeasurementRequest,
    gate: GateSettings,
    jobs: MeasurementJobs | None,
) -> dict[str, Any]:
    """Generate new observations only; no training, refinement or native input."""
    if gate.mode not in ("off", "report", "enforce"):
        raise ValueError("Invalid promotion gate mode")
    if gate.mode != "off" and gate.deals < MINIMUM_GATE_DEALS:
        raise ValueError("Too few promotion gate deals")
    if (
        not isinstance(request.samples, int)
        or isinstance(request.samples, bool)
        or request.samples < 1
    ):
        raise ValueError("Samples must be a positive integer")
    manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if jobs is not None:
        jobs.validate()
        if jobs.manifest_sha256 is not None and manifest_digest != jobs.manifest_sha256:
            raise ValueError("Pinned policy manifest digest mismatch")
    with SixLayerPolicy(manifest_path) as policy:
        manifest = policy.manifest
        discards = load_fixed_discards(
            manifest_path.parent, manifest["discard_population"]
        )
        policies = {role: policy for role in ROLES}
        gate_report = promotion_gate_metadata(
            policies,
            argparse.Namespace(
                promotion_gate=gate.mode,
                promotion_gate_deals=gate.deals,
                seed=request.seed,
            ),
        )
        if gate.mode == "enforce" and not gate_report["promotion_gate"]["passed"]:
            raise ValueError(
                "Fixed policy failed the safety gate; no replacement or refinement is allowed"
            )
        policy.reset_counts()
        table = generate_play_table(
            discards,
            policies,
            request.samples,
            request.seed,
            hands=request.hands if jobs is None else [],
            play_policy_fingerprint=":".join(
                policy_fingerprint(policies[role]) for role in ROLES
            ),
            discard_policy_fingerprint=discard_keeps_fingerprint(discards),
        )
        counts = policy.decision_counts()
        if jobs is not None:
            table["__metadata__"]["policy_manifest_sha256"] = manifest_digest
            worker = CellWorker(policy, discards, manifest_path)
            parallel = _parallel_cells(
                worker, request, jobs, {**table["__metadata__"], **gate_report}
            )
            table.update(parallel.pop("cells"))
            counts = parallel.pop("counts")
            table["__metadata__"].update(parallel)
        total = sum(counts.values())
        table["__metadata__"].update(
            {
                **gate_report,
                "measurement_backend": "python-v3-fixed-policy",
                "measured_policy": "trained",
                "joint_policy_converged": False,
                "discard_refinement_converged": False,
                "policy_manifest_sha256": hashlib.sha256(
                    manifest_path.read_bytes()
                ).hexdigest(),
                "policy_training_prior_sha256": manifest["prior"]["sha256"],
                "discard_population_description": manifest["discard_population"][
                    "description"
                ],
                "decision_count_total": total,
                "decision_count_denominator": "Final measurement select_rank calls; automatic goes excluded",
                "decision_support_definition": "Saved-policy opponent counterfactual reach under the training prior; not historical training reach",
                **{
                    f"decision_count_{category}": count
                    for category, count in counts.items()
                },
                **{
                    f"decision_share_{category}": count / total if total else 0.0
                    for category, count in counts.items()
                },
            }
        )
        if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != manifest_digest:
            raise ValueError("Policy manifest changed during measurement")
        return table


def main() -> None:
    """Write the same full/means/lines/uncertainty schemas as the v3 pipeline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-manifest", type=Path, required=True)
    parser.add_argument("--policy-manifest-sha256", required=True)
    parser.add_argument("--workers", type=positive_int, default=1)
    parser.add_argument("--checkpoint-dir", type=Path)
    parser.add_argument(
        "--generated-at",
        help="One timezone-qualified timestamp for all workers/resumes",
    )
    parser.add_argument("--samples", type=positive_int, default=13000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--hand-limit", type=positive_int)
    parser.add_argument(
        "--promotion-gate", choices=("off", "report", "enforce"), default="report"
    )
    parser.add_argument(
        "--promotion-gate-deals", type=positive_int, default=DEFAULT_GATE_DEALS
    )
    parser.add_argument("--output", default="expected_play_points.json")
    parser.add_argument("--client-output", default="expected_play_points.client.json")
    parser.add_argument("--lines-output", default="expected_play_points.lines.json")
    parser.add_argument(
        "--uncertainty-output", default="expected_play_points.uncertainty.json"
    )
    args = parser.parse_args()
    outputs = [
        Path(getattr(args, name)).resolve()
        for name in ("output", "client_output", "lines_output", "uncertainty_output")
    ]
    if len(set(outputs)) != 4:
        parser.error("All output paths must be distinct")
    # Input aliases, including symlinks, must not destroy the fixed inputs.
    manifest = read_manifest(args.policy_manifest)
    components = [
        manifest[name]
        for name in (
            "probabilities",
            "offsets",
            "support",
            "prior",
            "discard_population",
        )
    ]
    inputs = {
        args.policy_manifest.resolve(),
        *(
            (args.policy_manifest.parent / spec["file"]).resolve()
            for spec in (*components, *manifest["menus"])
        ),
    }
    # The writer stages each output beside the path as given, at
    # "<given name>.tmp-<pid>", even when that path is a symlink.
    staging = [
        (
            Path(getattr(args, name)).absolute().parent.resolve(),
            Path(getattr(args, name)).name,
        )
        for name in ("output", "client_output", "lines_output", "uncertainty_output")
    ]
    if inputs.intersection(outputs) or any(
        path.parent == directory and path.name.startswith(f"{stem}.tmp-")
        for path in inputs
        for directory, stem in staging
    ):
        parser.error("Outputs must not alias fixed policy inputs")
    if args.checkpoint_dir is not None:
        checkpoint = args.checkpoint_dir.resolve()
        if args.generated_at is None:
            parser.error(
                "--checkpoint-dir requires the original --generated-at timestamp"
            )
        if any(
            path == checkpoint or checkpoint in path.parents
            for path in (*inputs, *outputs)
        ):
            parser.error(
                "Checkpoint directory must be separate from inputs and outputs"
            )
    hands = get_canonical_hands()
    if args.hand_limit is not None:
        hands = hands[: args.hand_limit]
    full = measure_fixed_parallel(
        args.policy_manifest,
        MeasurementRequest(args.samples, args.seed, hands),
        GateSettings(args.promotion_gate, args.promotion_gate_deals),
        MeasurementJobs(
            args.generated_at or datetime.now(timezone.utc).isoformat(),
            args.workers,
            args.checkpoint_dir,
            args.policy_manifest_sha256,
        ),
    )
    _write_json(args.output, full)
    _write_json(args.client_output, build_client_table(full), compact=True)
    _write_lines(args.lines_output, args.client_output, full)
    sidecar = build_sidecar(
        "play", Path(args.output).read_bytes(), Path(args.client_output).read_bytes()
    )
    _write_json(args.uncertainty_output, json.loads(encode_json(sidecar)), compact=True)


if __name__ == "__main__":  # pragma: no cover
    main()
