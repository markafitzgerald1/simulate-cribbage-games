"""Verify one fixed-policy full/means/uncertainty/lines set before attachment."""

import argparse
import hashlib
from pathlib import Path
from typing import Any, Mapping

from artifact_pipeline.export_uncertainty import (
    build_sidecar,
    decode_sidecar,
    read_json,
)
from artifact_pipeline.generate_play_table import positive_int
from artifact_pipeline.pegging import ROLES, canonical_hand_key, get_canonical_hands
from artifact_pipeline.play_lines import build_lines, decode_lines


def verify_bundle(
    paths: Mapping[str, Path], manifest_sha256: str, release_samples: int | None = None
) -> dict[str, Any]:
    """Compare companions against this full table, including measured provenance."""
    full_bytes, means = paths["full"].read_bytes(), paths["means"].read_bytes()
    full = read_json(full_bytes)
    sidecar = decode_sidecar(paths["sidecar"].read_bytes(), means)
    lines = decode_lines(paths["lines"].read_bytes(), means)
    metadata = full["__metadata__"]
    if metadata.get("policy_manifest_sha256") != manifest_sha256:
        raise ValueError("Bundle policy manifest differs from its approved pin")
    if sidecar != build_sidecar("play", full_bytes, means):
        raise ValueError("Sidecar differs from this full measurement")
    if lines != build_lines(full, means):
        raise ValueError("Opening lines differ from this full measurement")
    if release_samples is not None:
        expected = {canonical_hand_key(hand) for hand in get_canonical_hands()}
        if set(full) - {"__metadata__"} != expected:
            raise ValueError("Release requires every canonical keep")
        if any(
            full[key][role]["n"] != release_samples
            for key in expected
            for role in ROLES
        ):
            raise ValueError("Release requires the approved samples in every cell")
        gate = metadata.get("promotion_gate", {})
        if gate.get("mode") != "enforce" or gate.get("passed") is not True:
            raise ValueError("Release requires a passed enforced promotion gate")
        if (
            metadata.get("measurement_backend") != "python-v3-fixed-policy"
            or metadata.get("joint_policy_converged") is not False
            or metadata.get("discard_refinement_converged") is not False
        ):
            raise ValueError("Release requires truthful fixed-policy provenance")
    print(
        f"Fixed-play bundle verified; means SHA-256 {hashlib.sha256(means).hexdigest()}"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-manifest-sha256", required=True)
    parser.add_argument("--release-samples", type=positive_int)
    for flag, suffix in [
        ("full", ""),
        ("means", ".client"),
        ("sidecar", ".uncertainty"),
        ("lines", ".lines"),
    ]:
        parser.add_argument(
            f"--{flag}", type=Path, default=Path(f"expected_play_points{suffix}.json")
        )
    args = parser.parse_args()
    verify_bundle(
        {name: getattr(args, name) for name in ("full", "means", "sidecar", "lines")},
        args.policy_manifest_sha256,
        args.release_samples,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
