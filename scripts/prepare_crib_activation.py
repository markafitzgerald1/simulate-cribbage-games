"""Prepare the exact approved terminal crib assets without publishing."""

import gzip
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path

from artifact_pipeline.export_uncertainty import (
    build_sidecar,
    decode_sidecar,
    encode_json,
)

MEANS_SHA256 = "b7cc6f03d73829158a9cf9a3f261a0d9a3501cc07b5a892b26cfe757868dd126"
FULL = "expected_crib_points.json"
MEANS = "expected_crib_points.client.json"
SIDECAR = "expected_crib_points.uncertainty.json"


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def prepare(final, assembled, output):
    """Verify assembly evidence and bind the release sidecar to exact source bytes."""
    result = json.loads((final / "bundle.json").read_bytes())
    assembly = json.loads((assembled / "bundle.json").read_bytes())
    for bundle, kind in ((result, "shadow"), (assembly, "generation")):
        if (
            bundle.get("contract") != "crib-v4-assembled-bundle-v1"
            or bundle.get("kind") != kind
            or bundle.get("success") is not True
            or bundle.get("terminal") is not True
            or bundle.get("generation") != 1
        ):
            raise ValueError("Activation requires a successful terminal generation")
    if result["plan_sha256"] != assembly["plan_sha256"]:
        raise ValueError("Activation bundle plans differ")
    if (
        result["files"][MEANS] != MEANS_SHA256
        or assembly["files"][MEANS] != MEANS_SHA256
        or digest(final / MEANS) != MEANS_SHA256
    ):
        raise ValueError("Activation client digest differs from the approved shadow")
    full_sha = digest(final / FULL)
    if result["files"][FULL] != full_sha or assembly["files"][FULL] != full_sha:
        raise ValueError("Activation full digest differs from its bundle")
    diagnostics = assembled / "diagnostics.json"
    if digest(diagnostics) != assembly["files"]["diagnostics.json"]:
        raise ValueError("Activation diagnostics digest differs from its bundle")
    shift = json.loads(diagnostics.read_bytes())["convergence_shift"]
    if (
        type(shift) not in (int, float)
        or not math.isfinite(shift)
        or not 0 <= shift <= 0.10
    ):
        raise ValueError("Activation table did not pass the 0.10 gate")
    means_bytes = (final / MEANS).read_bytes()
    sidecar = build_sidecar("crib", (final / FULL).read_bytes(), means_bytes)
    provenance = sidecar["provenance"]
    if (
        sidecar["schema"] != "expected-points-uncertainty.v2"
        or sidecar["source_full_sha256"] != full_sha
        or sidecar["record_groups"]["totals"]["record_count"] != 9076
        or provenance.get("precut_resolved_negative") != 0
    ):
        raise ValueError("Activation sidecar differs from the verified table")
    provenance["convergence_shift"] = shift
    sidecar_bytes = encode_json(sidecar)
    decode_sidecar(sidecar_bytes, means_bytes)
    output.mkdir()
    (output / MEANS).write_bytes(means_bytes)
    (output / SIDECAR).write_bytes(sidecar_bytes)
    with (final / FULL).open("rb") as source, (output / (FULL + ".gz")).open(
        "xb"
    ) as target:
        with gzip.GzipFile(
            filename="", fileobj=target, mode="wb", mtime=0
        ) as compressed:
            shutil.copyfileobj(source, compressed)


def verify_candidate(directory):
    """Check the downloaded prepared bytes before a release write."""
    means = (directory / MEANS).read_bytes()
    sidecar = decode_sidecar((directory / SIDECAR).read_bytes(), means)
    provenance = sidecar["provenance"]
    if (
        sidecar["schema"] != "expected-points-uncertainty.v2"
        or sidecar["means_sha256"] != MEANS_SHA256
        or sidecar["record_groups"]["totals"]["record_count"] != 9076
        or not 0 <= provenance["convergence_shift"] <= 0.10
        or provenance.get("precut_resolved_negative") != 0
    ):
        raise ValueError("Invalid v4 release candidate")
    with gzip.open(directory / (FULL + ".gz"), "rb") as handle:
        if (
            hashlib.file_digest(handle, "sha256").hexdigest()
            != sidecar["source_full_sha256"]
        ):
            raise ValueError("Candidate uncompressed source digest differs")


if __name__ == "__main__":
    if sys.argv[1] == "verify":
        verify_candidate(Path(sys.argv[2]))
    else:
        prepare(*map(Path, sys.argv[1:]))
