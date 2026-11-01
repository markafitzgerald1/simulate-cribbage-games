"""Bounded diagnostic only: time v4 against an artifact's saved frozen policy.

Run as a module from the repository root. JSON lines go to stdout; checkpoints
and logs belong outside production paths. This does not train or publish.
"""

import argparse
import hashlib
import json
import platform
import time
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from artifact_pipeline import crib_v4, generate_table
from artifact_pipeline.crib_v4_state import projected_statistics


def emit(event, **values):
    """Write a flushed machine-readable progress record."""
    print(json.dumps({"event": event, **values}), flush=True)


def comparison(streams, rank_key):
    """Project the pre-cut twin gap, retaining all cross-cut covariance."""
    first, second = rank_key.split("_")
    residual = {}
    suit = {}
    for rank in generate_table.Index.indices:
        weight = Fraction(4 - (rank == first) - (rank == second), 50)
        for kind in ("fifteens", "pairs", "runs"):
            residual[f"{rank}/residual/{kind}"] = weight
        for variant, sign in (("Suited", 1), ("Unsuited", -1)):
            for kind in ("flushes", "nobs"):
                suit[f"{rank}/{variant}/root/{kind}"] = sign * weight
    terms = {"residual": residual, "suit": suit}
    return {
        name: projected_statistics(streams, coefficients)
        for name, coefficients in (
            ("gap", terms),
            ("residual", {"residual": residual}),
            (
                "flush",
                {"suit": {k: v for k, v in suit.items() if k.endswith("flushes")}},
            ),
            ("nobs", {"suit": {k: v for k, v in suit.items() if k.endswith("nobs")}}),
        )
    }


def main():
    """Run one explicitly selected group under the saved generating policy."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rank-group", default="3_8")
    parser.add_argument("--samples", required=True, type=int)
    parser.add_argument("--checkpoint-frequency", default=400, type=int)
    options = parser.parse_args()
    if options.source.resolve() == options.output.resolve():
        parser.error("source and diagnostic output must differ")
    if options.checkpoint_frequency < 1:
        parser.error("checkpoint frequency must be positive")
    raw = options.source.read_bytes()
    payload = json.loads(raw)["__metadata__"]["generation_accumulators"]
    digest = hashlib.sha256(raw).hexdigest()
    emit(
        "manifest",
        source_sha256=digest,
        policy_sha256=crib_v4._policy_hash(payload),
        runtime=platform.python_version(),
        platform=platform.platform(),
        rank_group=options.rank_group,
        seed=42,
        samples=options.samples,
        checkpoint_frequency=options.checkpoint_frequency,
    )
    args = argparse.Namespace(
        output=str(options.output),
        samples=options.samples,
        infinite=False,
        checkpoint_frequency=options.checkpoint_frequency,
        no_resume=False,
        seed=42,
        bootstrap=None,
        dampening=0.5,
        max_generations=None,
        convergence_threshold=None,
        fail_on_non_convergence=False,
        no_client_output=True,
        client_output=None,
    )
    first, second = options.rank_group.split("_")
    pairs = [f"{options.rank_group}_Unsuited"]
    if first != second:
        pairs.insert(0, f"{options.rank_group}_Suited")
    original_write = crib_v4._write_checkpoint
    original_sample = crib_v4._V4Run.sample_group
    original_load = crib_v4._load_state

    def checkpoint(state, args, legacy):
        start = time.perf_counter()
        result = original_write(state, args, legacy)
        emit(
            "checkpoint",
            seconds=time.perf_counter() - start,
            bytes=options.output.stat().st_size,
        )
        return result

    def sample(current, key, role, policy):
        start = time.perf_counter()
        streams = current.state["estimator_state"][key][role]["streams"]
        before = streams["base"]["count"]
        original_sample(current, key, role, policy)
        emit(
            "group",
            role=role,
            rows=streams["base"]["count"] - before,
            target=streams["base"]["count"],
            seconds_including_write=time.perf_counter() - start,
        )

    def load(*arguments):
        start = time.perf_counter()
        result = original_load(*arguments)
        if (
            result["policy_sha256"] != crib_v4._policy_hash(payload)
            or result["bootstrap_sha256"] != digest
        ):
            raise ValueError("diagnostic source and resumed policy differ")
        emit("load", seconds=time.perf_counter() - start)
        return result

    start = time.perf_counter()
    with (
        patch.object(crib_v4, "_bootstrap_policy", return_value=(payload, digest)),
        patch.object(crib_v4, "_write_checkpoint", checkpoint),
        patch.object(crib_v4._V4Run, "sample_group", sample),
        patch.object(crib_v4, "_load_state", load),
    ):
        current = crib_v4._V4Run(args, pairs, generate_table)
        current.execute()
    emit("complete", seconds=time.perf_counter() - start)
    if first != second:
        for role, entry in current.state["estimator_state"][options.rank_group].items():
            emit(
                "comparison",
                role=role,
                **comparison(entry["streams"], options.rank_group),
            )


if __name__ == "__main__":
    main()
