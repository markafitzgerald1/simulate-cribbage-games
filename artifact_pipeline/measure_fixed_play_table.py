"""Measure a fixed CFR policy in both seats with the existing Python v3 path."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from artifact_pipeline.export_uncertainty import build_sidecar, encode_json
from artifact_pipeline.generate_play_table import (
    DiscardPolicy,
    build_client_table,
    discard_keeps_fingerprint,
    generate_play_table,
    positive_int,
    promotion_gate_metadata,
    _write_json,
    _write_lines,
)
from artifact_pipeline.pegging import ROLES, get_canonical_hands, policy_fingerprint
from artifact_pipeline.promotion_gate import DEFAULT_GATE_DEALS, MINIMUM_GATE_DEALS
from artifact_pipeline.six_layer_policy import (
    SixLayerPolicy,
    read_manifest,
    verified_component,
    close_component,
    _unique_object,
)


@dataclass(frozen=True)
class GateSettings:
    """Keep the unmodified gate's mode and deal budget together."""

    mode: str = "report"
    deals: int = DEFAULT_GATE_DEALS


def load_fixed_discards(root: Path, spec: Mapping[str, Any]) -> DiscardPolicy:
    """Validate a complete frozen rank keep map; never refine or invent keeps."""
    data = verified_component(root, spec)
    try:
        document = json.loads(data[:], object_pairs_hook=_unique_object)
    finally:
        close_component(data)
    if not isinstance(document, dict) or not isinstance(document.get("keeps"), list):
        raise ValueError("Frozen discard document needs keep rows")
    keeps = {}
    for row in document["keeps"]:
        if (
            not isinstance(row, list)
            or len(row) != 3
            or not isinstance(row[1], list)
            or not isinstance(row[2], list)
        ):
            raise ValueError("Malformed discard row")
        role, dealt, kept = row
        if (
            role not in ROLES
            or len(dealt) != 6
            or len(kept) != 4
            or dealt != sorted(dealt)
            or kept != sorted(kept)
        ):
            raise ValueError("Invalid canonical discard row")
        if any(
            not isinstance(rank, int) or isinstance(rank, bool) or not 0 <= rank < 13
            for rank in (*dealt, *kept)
        ):
            raise ValueError("Invalid discard rank")
        available: Counter[int] = Counter(dealt)
        chosen: Counter[int] = Counter(kept)
        if max(available.values()) > 4 or chosen - available:
            raise ValueError("Impossible discard row")
        key = (role, tuple(dealt))
        if key in keeps:
            raise ValueError("Duplicate discard row")
        keeps[key] = tuple(kept)
    if len(keeps) != 2 * 18395:
        raise ValueError(
            "Frozen discards must cover every canonical six-card hand/role"
        )
    policy = DiscardPolicy(keeps)
    if discard_keeps_fingerprint(policy) != spec.get("keep_fingerprint"):
        raise ValueError("Discard population fingerprint mismatch")
    if (
        spec.get("converged") is not False
        or not isinstance(spec.get("description"), str)
        or not spec["description"].strip()
    ):
        raise ValueError(
            "Frozen discard population needs honest lack of convergence/limits"
        )
    return policy


def measure_fixed_table(
    manifest_path: Path,
    samples: int,
    seed: int,
    hands: Sequence[tuple[int, ...]] | None = None,
    gate: GateSettings = GateSettings(),
) -> dict[str, Any]:
    """Generate new observations only; no training, refinement or native input."""
    if gate.mode not in ("off", "report", "enforce"):
        raise ValueError("Invalid promotion gate mode")
    if gate.mode != "off" and gate.deals < MINIMUM_GATE_DEALS:
        raise ValueError("Too few promotion gate deals")
    with SixLayerPolicy(manifest_path) as policy:
        manifest = policy.manifest
        discards = load_fixed_discards(
            manifest_path.parent, manifest["discard_population"]
        )
        policies = {role: policy for role in ROLES}
        gate_report = promotion_gate_metadata(
            policies,
            argparse.Namespace(
                promotion_gate=gate.mode, promotion_gate_deals=gate.deals, seed=seed
            ),
        )
        if gate.mode == "enforce" and not gate_report["promotion_gate"]["passed"]:
            raise ValueError(
                "Fixed policy failed the safety gate; no replacement or refinement is allowed"
            )
        policy.reset_counts()
        fingerprint = ":".join(policy_fingerprint(policies[role]) for role in ROLES)
        table = generate_play_table(
            discards,
            policies,
            samples,
            seed,
            hands=hands,
            play_policy_fingerprint=fingerprint,
            discard_policy_fingerprint=discard_keeps_fingerprint(discards),
        )
        counts = policy.decision_counts()
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
        return table


def main() -> None:
    """Write the same full/means/lines/uncertainty schemas as the v3 pipeline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-manifest", type=Path, required=True)
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
    hands = get_canonical_hands()
    if args.hand_limit is not None:
        hands = hands[: args.hand_limit]
    full = measure_fixed_table(
        args.policy_manifest,
        args.samples,
        args.seed,
        hands,
        GateSettings(args.promotion_gate, args.promotion_gate_deals),
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
