"""Pinned first-shard diagnostic, never production generation or publication."""

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import sys
import time

from artifact_pipeline import crib_v4
from scripts import measure_crib_v4

GROUPS = ("3_8", "2_3", "7_8", "4_J", "A_A")
SOURCE_SHA256 = "a0464f8c805f782c27040bb366e0775455cd2fa02eb5e458d70bb0e6b9c69666"
CLIENT_SHA256 = "4cd8a9258d32973710361b9c2a764aea3b8c9a1178ab53e1c2aa38a53e030cc1"
POLICY_SHA256 = "2a2a584f1f31fc28f3aa42988f0be8659eafde5e1776cac27c09f1d2e6f114d0"


def verified_inputs(source, client):
    """Fail closed before any output is written or any policy is used."""
    for path, expected in ((source, SOURCE_SHA256), (client, CLIENT_SHA256)):
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"pinned input hash differs: {path.name}")
    payload = json.loads(source.read_bytes())["__metadata__"]["generation_accumulators"]
    if crib_v4._policy_hash(payload) != POLICY_SHA256:
        raise ValueError("pinned saved generating policy differs")
    if (
        platform.python_implementation() != "CPython"
        or platform.python_version() != "3.14.4"
    ):
        raise ValueError("diagnostic requires CPython 3.14.4")
    expected = ("shared-rank-relation-v1", "uniform-two-card-rank-completion-v1")
    if (crib_v4.ESTIMATOR_CONTRACT, crib_v4.CENTERING_CONTRACT) != expected:
        raise ValueError("diagnostic estimator contracts differ")


def validate_resume_run(
    document, repository, workflow=".github/workflows/diagnose-crib-v4.yml"
):
    """Accept artifacts only from a completed manual diagnostic in this repo."""
    if (
        document.get("event") != "workflow_dispatch"
        or document.get("status") != "completed"
        or document.get("path") != workflow
        or (document.get("repository") or {}).get("full_name") != repository
        or (document.get("head_repository") or {}).get("full_name") != repository
    ):
        raise ValueError(
            "resume run is not a completed manual diagnostic from this repository"
        )


def manifest(groups=GROUPS, samples=4000, extra_paths=()):
    """Pin producer source bytes as well as the explicit experiment identity."""
    root = Path(__file__).resolve().parents[1]
    paths = [
        *sorted((root / "artifact_pipeline").glob("*.py")),
        root / "simulate_cribbage_games.py",
        Path(__file__).resolve(),
        root / "scripts/measure_crib_v4.py",
        root / "requirements.txt",
        *(root / path for path in extra_paths),
    ]
    return {
        "source_sha256": SOURCE_SHA256,
        "client_sha256": CLIENT_SHA256,
        "policy_sha256": POLICY_SHA256,
        "seed": 42,
        "samples": samples,
        "groups": list(groups),
        "python": platform.python_version(),
        "files": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths
        },
    }


def run(source, client, output, stop_at, *, groups=GROUPS, samples=4000, identity=None):
    """Run only the declared groups, retaining separate authoritative files."""
    paths = [output / name for name in ("manifest.json", "summary.json")]
    for key in groups:
        paths.extend(
            output / f"group-{key}.{suffix}" for suffix in ("json", "json.tmp", "jsonl")
        )
    for path in paths:
        for original in (source, client):
            if original.resolve() == path.resolve() or (
                path.exists() and original.samefile(path)
            ):
                raise ValueError("diagnostic writer aliases an input")
    output.mkdir(parents=True, exist_ok=True)
    statuses = {key: "not_started" for key in groups}
    summary_path = output / "summary.json"
    summary = {
        "complete": False,
        "groups": statuses,
        "commit": os.environ.get("GITHUB_SHA"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "stop_at": stop_at,
    }
    try:
        verified_inputs(source, client)
        identity = manifest(groups, samples) if identity is None else identity
        identity_path = output / "manifest.json"
        checkpoints = list(output.glob("group-*.json"))
        if identity_path.exists():
            if json.loads(identity_path.read_text()) != identity:
                raise ValueError(
                    "resume manifest differs from pinned experiment/source"
                )
        elif checkpoints:
            raise ValueError("resume checkpoints require their manifest")
        if not identity_path.exists():
            identity_path.write_text(json.dumps(identity, indent=2) + "\n")
        for key in groups:
            if time.time() >= stop_at:
                break
            statuses[key] = "failed"
            with (output / f"group-{key}.jsonl").open("a", encoding="utf-8") as log:
                with measure_output(log):
                    complete = measure_crib_v4.main(
                        [
                            "--source",
                            str(source),
                            "--output",
                            str(output / f"group-{key}.json"),
                            "--rank-group",
                            key,
                            "--samples",
                            str(samples),
                            "--checkpoint-frequency",
                            "1000",
                            "--source-sha256",
                            SOURCE_SHA256,
                            "--policy-sha256",
                            POLICY_SHA256,
                            "--stop-at",
                            str(stop_at),
                        ]
                    )
            statuses[key] = "complete" if complete else "incomplete"
            if not complete:
                break
        summary["complete"] = all(value == "complete" for value in statuses.values())
    except BaseException as error:
        summary["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        summary_path.write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary), flush=True)
    return summary


class measure_output:
    """Mirror progress to the Actions log and the resumable artifact log."""

    def __init__(self, log):
        self.log = log
        self.previous = sys.stdout

    def __enter__(self):
        sys.stdout = self
        return self

    def write(self, value):
        self.log.write(value)
        self.previous.write(value)

    def flush(self):
        self.log.flush()
        self.previous.flush()

    def __exit__(self, *_error):
        sys.stdout = self.previous


def main():
    """Entrypoint with no target, seed or group override."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stop-at", type=float, required=True)
    args = parser.parse_args()
    run(args.source, args.client, args.output, args.stop_at)


if __name__ == "__main__":
    main()
