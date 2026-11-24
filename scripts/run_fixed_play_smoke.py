"""Exercise the bounded fixed-policy CLI and all four export paths offline."""

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

from artifact_pipeline.export_uncertainty import decode_sidecar
from artifact_pipeline.play_lines import decode_lines
from artifact_pipeline.test_fixed_policy_fixtures import make_bundle


def run_smoke(output_dir: Path) -> None:
    """Use portable synthetic inputs, never a downloaded policy or release."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        name: output_dir / f"expected_play_points{suffix}.json"
        for name, suffix in (
            ("output", ""),
            ("client-output", ".client"),
            ("lines-output", ".lines"),
            ("uncertainty-output", ".uncertainty"),
        )
    }
    with tempfile.TemporaryDirectory(dir=output_dir) as directory:
        manifest = make_bundle(Path(directory))
        command = [
            sys.executable,
            "-m",
            "artifact_pipeline.measure_fixed_play_table",
            "--policy-manifest",
            str(manifest),
            "--policy-manifest-sha256",
            hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "--workers",
            "2",
            "--samples",
            "25",
            "--hand-limit",
            "21",
            "--seed",
            "42",
            "--promotion-gate",
            "off",
            "--generated-at",
            "2026-10-12T16:00:00+00:00",
        ]
        for flag, path in paths.items():
            command.extend([f"--{flag}", str(path)])
        subprocess.run(command, check=True)
    means = paths["client-output"].read_bytes()
    sidecar = decode_sidecar(paths["uncertainty-output"].read_bytes(), means)
    lines = decode_lines(paths["lines-output"].read_bytes(), means)
    if (
        sidecar["record_groups"]["totals"]["record_count"] != 42
        or len(lines["entries"]) != 21
    ):
        raise ValueError("Bounded export lost measured cells")
    if sidecar["provenance"]["decision_count_trained"] <= 0:
        raise ValueError("Bounded fixture never exercised the supplied mixed policy")
    print("Fixed-policy bounded CLI: 42 cells, all companions paired")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("dist/fixed-play-smoke")
    )
    run_smoke(parser.parse_args().output_dir)


if __name__ == "__main__":  # pragma: no cover
    main()
