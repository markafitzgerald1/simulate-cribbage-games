"""Bounded diagnostic only: time v4 against an artifact's saved frozen policy.

Run as a module from the repository root. JSON lines go to stdout; checkpoints
and logs belong outside production paths. This does not train or publish.
"""

import argparse
import hashlib
import json
import platform
import signal
import time
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from artifact_pipeline import crib_v4, generate_table
from artifact_pipeline.crib_v4_state import component_coefficients, projected_statistics


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


def precut_means(streams, rank_key):
    """Project individual crib means without cancelling their shared baseline."""
    first, second = rank_key.split("_")
    result = {}
    for variant in ("Unsuited", "Suited") if first != second else ("Unsuited",):
        terms = {}
        for rank in generate_table.Index.indices:
            weight = Fraction(4 - (rank == first) - (rank == second), 50)
            for kind in ("fifteens", "pairs", "runs", "flushes", "nobs"):
                coefficients = component_coefficients(rank, variant, "root", kind)
                for stream, values in coefficients.items():
                    for label, value in values.items():
                        block = terms.setdefault(stream, {})
                        block[label] = block.get(label, 0) + value * weight
        result[variant] = projected_statistics(streams, terms)
    return result


def main(argv=None):
    """Run one explicitly selected group under the saved generating policy."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rank-group", default="3_8")
    parser.add_argument("--samples", required=True, type=int)
    parser.add_argument("--checkpoint-frequency", default=400, type=int)
    parser.add_argument("--stop-at", type=float, help="Graceful deadline, Unix seconds")
    parser.add_argument("--source-sha256")
    parser.add_argument("--policy-sha256")
    options = parser.parse_args(argv)
    write_paths = (options.output, Path(f"{options.output}.tmp"))
    for path in write_paths:
        if options.source.resolve() == path.resolve() or (
            path.exists() and options.source.samefile(path)
        ):
            parser.error("source must differ from output and its temporary path")
    if options.checkpoint_frequency < 1:
        parser.error("checkpoint frequency must be positive")
    raw = options.source.read_bytes()
    payload = json.loads(raw)["__metadata__"]["generation_accumulators"]
    digest = hashlib.sha256(raw).hexdigest()
    policy_digest = crib_v4._policy_hash(payload)
    if options.source_sha256 and options.source_sha256 != digest:
        raise ValueError("diagnostic source hash differs")
    if options.policy_sha256 and options.policy_sha256 != policy_digest:
        raise ValueError("diagnostic policy hash differs")
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
    original_round = crib_v4._sample_round
    deadline_reached = False

    def check_deadline(current):
        nonlocal deadline_reached
        if options.stop_at is not None and time.time() >= options.stop_at:
            deadline_reached = True
            current.request_stop(None, None)

    def sample_round(*arguments):
        rows = original_round(*arguments)
        check_deadline(current)
        return rows

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
        check_deadline(current)
        if current.pending_stop:
            raise SystemExit(130)
        try:
            original_sample(current, key, role, policy)
        finally:
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
            result["generation"] != 0
            or result["policy_sha256"] != crib_v4._policy_hash(payload)
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
        patch.object(crib_v4, "_sample_round", sample_round),
    ):
        current = crib_v4._V4Run(args, pairs, generate_table)
        previous = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, current.request_stop)
        try:
            check_deadline(current)
            current.execute()
        except SystemExit as error:
            if error.code != 130:
                raise
        finally:
            signal.signal(signal.SIGINT, previous)
    # A stop on the final row occurs before sample_pass marks the phase.
    if current.state["phase"] == "sampling" and all(
        moments["count"] == options.samples
        for roles in current.state["estimator_state"].values()
        for entry in roles.values()
        for moments in entry["streams"].values()
    ):
        current.state["phase"] = "complete"
        with patch.object(crib_v4, "_write_checkpoint", checkpoint):
            current.checkpoint()
    complete = current.state["phase"] == "complete"
    for role, entry in current.state["estimator_state"][options.rank_group].items():
        if first != second:
            emit(
                "comparison",
                role=role,
                **comparison(entry["streams"], options.rank_group),
            )
        for variant, statistics in precut_means(
            entry["streams"], options.rank_group
        ).items():
            emit("mean", role=role, variant=variant, statistics=statistics)
    counts = {
        role: {name: moments["count"] for name, moments in entry["streams"].items()}
        for role, entry in current.state["estimator_state"][options.rank_group].items()
    }
    emit(
        "status",
        complete=complete,
        counts=counts,
        reason=(
            "interrupt"
            if current.pending_stop and not deadline_reached
            else "complete" if complete else "deadline"
        ),
        seconds=time.perf_counter() - start,
    )
    if current.pending_stop and not deadline_reached:
        raise SystemExit(130)
    return complete


if __name__ == "__main__":
    main()
