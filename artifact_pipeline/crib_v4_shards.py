"""Single-generation v4 workers and fail-closed full-table assembly.

Only assembly may advance a policy. This module provides no release or dispatch
operation; its command-line workflow is a separately authorized shadow run.
"""

import argparse
import copy
import hashlib
import json
import math
import re
import os
from pathlib import Path
import shutil
import signal
import tempfile
import time

from artifact_pipeline import generate_table
from artifact_pipeline.crib_v4 import (
    _V4Run,
    _canonical_json,
    _check_metadata,
    _check_phase,
    _decode_groups,
    _digest,
    _empty_group,
    _fresh_state,
    _physical_group,
    _project_output,
    _prepare_transition,
    _rank_keys,
    _requested_pairs,
    _should_stop_after_complete,
    _transition,
    ROLES,
)
from artifact_pipeline.crib_precut import enforce_precut_report, precut_twin_report
from artifact_pipeline.export_uncertainty import (
    read_json,
    mean_buckets,
    _matching_means,
)

PLAN_CONTRACT = "crib-v4-eight-shard-plan-v1"
MANIFEST_CONTRACT = "crib-v4-shard-manifest-v1"
BUNDLE_CONTRACT = "crib-v4-assembled-bundle-v1"
SOURCE_FILES = (
    "artifact_pipeline/crib_v4_shards.py",
    "artifact_pipeline/crib_v4.py",
    "artifact_pipeline/crib_v4_state.py",
    "artifact_pipeline/crib_decomposition.py",
    "artifact_pipeline/crib_precut.py",
    "artifact_pipeline/generate_table.py",
    "artifact_pipeline/adapter.py",
    "artifact_pipeline/export_uncertainty.py",
    "artifact_pipeline/analytical_solver.py",
    "simulate_cribbage_games.py",
    "requirements.txt",
    ".python-version",
    ".github/workflows/shadow-crib-v4.yml",
)


def json_bytes(value):
    """Encode without dropping integer precision or invalid numeric diagnostics."""
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()


def file_digest(path):
    """Hash exact saved bytes, including their whitespace."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_files():
    root = Path(__file__).resolve().parents[1]
    names = set(SOURCE_FILES) | {
        str(path.relative_to(root))
        for path in (root / "artifact_pipeline").glob("*.py")
        if not path.name.startswith("test_")
    }
    return {name: file_digest(root / name) for name in sorted(names)}


def partition(groups):
    """Canonical round robin; retain empty shards for small acceptance tests."""
    return [groups[number::8] for number in range(8)]


def _seal(metadata, reference, provenance=None):
    plan = {
        "contract": PLAN_CONTRACT,
        "metadata": {k: v for k, v in metadata.items() if k != "estimator_state"},
        "shards": partition(_rank_keys(metadata["requested_pairs"])),
        "source_files": source_files(),
        "reference": reference,
        "provenance": (
            provenance
            if provenance is not None
            else {
                name: os.environ.get(name)
                for name in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_REPOSITORY")
            }
        ),
    }
    plan["sha256"] = _digest(plan)
    return plan


def initial_plan(args, pairs=None, reference=None):
    """Create one policy identity; production CLI fixes all experiment controls."""
    selected = _requested_pairs(pairs, generate_table)
    return _seal(_fresh_state(args, selected, generate_table), reference or {})


def _args(metadata, path):
    control = metadata["run_control"]
    return argparse.Namespace(
        output=str(path),
        samples=control["target_samples"],
        infinite=control["infinite"],
        checkpoint_frequency=1000,
        no_resume=False,
        seed=metadata["seed"],
        bootstrap=None,
        dampening=control["dampening"],
        max_generations=control["max_generations"],
        convergence_threshold=control["convergence_threshold"],
        fail_on_non_convergence=control["fail_on_non_convergence"],
        no_client_output=True,
        client_output=None,
        precut_guard="enforce",
    )


def validate_plan(plan):
    """Verify the external expected identity before reading any shard state."""
    if not isinstance(plan, dict) or set(plan) != {
        "contract",
        "metadata",
        "shards",
        "source_files",
        "reference",
        "provenance",
        "sha256",
    }:
        raise ValueError("Invalid generation plan shape")
    payload = {k: v for k, v in plan.items() if k != "sha256"}
    if plan["contract"] != PLAN_CONTRACT or _digest(payload) != plan["sha256"]:
        raise ValueError("Generation plan identity differs")
    if plan["source_files"] != source_files():
        raise ValueError("Generation plan source files differ")
    metadata = plan["metadata"]
    pairs = _requested_pairs(metadata["requested_pairs"], generate_table)
    if plan["shards"] != partition(_rank_keys(pairs)):
        raise ValueError("Generation plan partition differs")
    if metadata["phase"] != "sampling":
        raise ValueError("Generation plan is not a fresh policy generation")
    count = metadata["run_control"]["target_samples"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 2:
        raise ValueError("Generation plan target must be at least two")
    _check_metadata(
        {**metadata, "estimator_state": {}},
        _args(metadata, "unused"),
        pairs,
        generate_table,
    )
    return metadata


def _pairs(plan, groups):
    return [
        pair
        for pair in plan["metadata"]["requested_pairs"]
        if pair.rsplit("_", 1)[0] in groups
    ]


def _check_identity(state, plan, groups):
    expected = {**plan["metadata"], "requested_pairs": _pairs(plan, groups)}
    actual = {
        k: v
        for k, v in state.items()
        if k not in ("estimator_state", "precut_twin_report")
    }
    expected.pop("phase")
    actual.pop("phase")
    if _canonical_json(actual) != _canonical_json(expected):
        raise ValueError("Checkpoint differs from expected generation/policy plan")
    if state["phase"] not in ("sampling", "complete"):
        raise ValueError("A worker checkpoint cannot transition")


def _manifest(plan, number, files, complete):
    return {
        "contract": MANIFEST_CONTRACT,
        "plan_sha256": plan["sha256"],
        "shard": number,
        "groups": plan["shards"][number],
        "complete": complete,
        "files": dict(files),
    }


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Input must be a regular file: {path}")
    return read_json(path.read_bytes())


def protect_paths(inputs, outputs):
    """Include temporary paths and physical aliases before any writer opens."""
    for source in inputs:
        for output in outputs:
            if source.resolve() == output.resolve() or (
                source.exists() and output.exists() and source.samefile(output)
            ):
                raise ValueError("Output must not alias an input")


def _write_manifest(path, value):
    descriptor, name = tempfile.mkstemp(prefix=".manifest-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json_bytes(value))
        os.replace(name, path)
    finally:
        if Path(name).exists():
            Path(name).unlink()


def _snapshot_path(directory, name, digest):
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise ValueError("Invalid checkpoint digest")
    return directory / "snapshots" / f"{Path(name).stem}-{digest}.json"


def _snapshot_bytes(directory, name, digest):
    path = _snapshot_path(directory, name, digest)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or linked snapshot")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Checkpoint digest differs")
    return raw


def _save_snapshot(directory, name, raw):
    digest = hashlib.sha256(raw).hexdigest()
    path = _snapshot_path(directory, name, digest)
    path.parent.mkdir(exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".snapshot-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != raw:
                raise ValueError("Existing immutable snapshot differs") from None
    finally:
        Path(temporary).unlink()
    return digest


def _collect_snapshots(directory, files):
    root = directory / "snapshots"
    keep = {_snapshot_path(directory, name, digest) for name, digest in files.items()}
    if root.exists():
        for path in root.iterdir():
            if path not in keep:
                path.unlink()


def _worker_directory(directory):
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise ValueError("Worker directory is not a regular directory")
    if not directory.exists():
        return
    if not (directory / "manifest.json").exists() and any(directory.iterdir()):
        raise ValueError("Resume directory has no manifest")
    for path in directory.iterdir():
        if path.name not in ("manifest.json", "snapshots") and not path.name.startswith(
            (".working-", ".manifest-")
        ):
            raise ValueError("Foreign files in worker directory")
        if path.is_symlink():
            raise ValueError("Linked worker path")
    snapshots = directory / "snapshots"
    if snapshots.exists() and (
        not snapshots.is_dir()
        or any(p.is_symlink() or not p.is_file() for p in snapshots.iterdir())
    ):
        raise ValueError("Invalid snapshot directory")


def _load_manifest(plan, number, directory, require_complete=False):
    _worker_directory(directory)
    saved = _read(directory / "manifest.json")
    expected_names = {f"group-{group}.json" for group in plan["shards"][number]}
    if (
        set(saved)
        != {"contract", "plan_sha256", "shard", "groups", "complete", "files"}
        or any(
            saved[k] != v
            for k, v in _manifest(plan, number, {}, False).items()
            if k not in ("files", "complete")
        )
        or not isinstance(saved["complete"], bool)
        or not isinstance(saved["files"], dict)
        or not set(saved["files"]) <= expected_names
    ):
        raise ValueError("Resume manifest differs from plan or shard")
    if (require_complete or saved["complete"]) and (
        saved["complete"] is not True or set(saved["files"]) != expected_names
    ):
        raise ValueError("Incomplete shard manifest")
    snapshots = directory / "snapshots"
    if snapshots.exists():
        allowed = "|".join(
            re.escape(f"group-{group}-") for group in plan["shards"][number]
        )
        for path in snapshots.iterdir():
            if not path.name.startswith(".snapshot-") and (
                not allowed
                or re.fullmatch(f"(?:{allowed})[0-9a-f]{{64}}\\.json", path.name)
                is None
            ):
                raise ValueError("Foreign immutable snapshot")
    return saved


def _decode_checkpoint(plan, group, metadata):
    pairs = _pairs(plan, [group])
    _check_metadata(metadata, _args(plan["metadata"], "unused"), pairs, generate_table)
    _check_identity(metadata, plan, [group])
    decoded = _decode_groups(metadata, pairs, generate_table)
    _check_phase(metadata, decoded)
    return {
        **{k: v for k, v in metadata.items() if k != "precut_twin_report"},
        "estimator_state": decoded,
    }


def _new_group(plan, group):
    state = copy.deepcopy(plan["metadata"])
    state["requested_pairs"] = _pairs(plan, [group])
    physical = _physical_group(group, generate_table)
    state["estimator_state"] = {
        group: {role: _empty_group(physical, generate_table) for role in ROLES}
    }
    return state


def emit(event, **values):
    """Keep long jobs observable without exposing the policy payload."""
    print(json.dumps({"event": event, "time": time.time(), **values}), flush=True)


class ShardRun(_V4Run):
    """Enter the existing sampler only with freshly built or validated state."""

    def __init__(self, args, state, commit):
        super().__init__(
            args, state["requested_pairs"], generate_table, initial_state=state
        )
        self.commit_snapshot = commit

    def checkpoint(self):
        started = time.monotonic()
        result = super().checkpoint()
        raw = Path(self.args.output).read_bytes()
        self.commit_snapshot(raw)
        emit("checkpoint", seconds=time.monotonic() - started, bytes=len(raw))
        return result


def _resume_states(plan, number, directory, manifest):
    states = {}
    for group in plan["shards"][number]:
        name = f"group-{group}.json"
        if name in manifest["files"]:
            started = time.monotonic()
            emit("validation-start", group=group, shard=number)
            raw = _snapshot_bytes(directory, name, manifest["files"][name])
            states[group] = _decode_checkpoint(
                plan, group, read_json(raw)["__metadata__"]
            )
            if states[group]["phase"] == "complete":
                enforce_precut_report(precut_twin_report(states[group]))
            elif manifest["complete"]:
                raise ValueError("Complete manifest contains partial checkpoint")
            emit("validation-end", group=group, seconds=time.monotonic() - started)
    return states


def _commit_group(plan, number, directory, files, group):
    def commit(raw):
        name = f"group-{group}.json"
        updated = {**files, name: _save_snapshot(directory, name, raw)}
        _write_manifest(
            directory / "manifest.json", _manifest(plan, number, updated, False)
        )
        files.clear()
        files.update(updated)
        _collect_snapshots(directory, files)

    return commit


def _measure_groups(plan, number, directory, stop_at):
    manifest_path = directory / "manifest.json"
    manifest = (
        _load_manifest(plan, number, directory)
        if manifest_path.exists()
        else _manifest(plan, number, {}, False)
    )
    states = _resume_states(plan, number, directory, manifest)
    files = dict(manifest["files"])
    if not manifest_path.exists():
        _write_manifest(manifest_path, manifest)
    with tempfile.TemporaryDirectory(prefix=".working-", dir=directory) as scratch:
        for group in plan["shards"][number]:
            if stop_at is not None and time.time() >= stop_at:
                return False
            args = _args(plan["metadata"], Path(scratch) / f"group-{group}.json")
            state = states.get(group) or _new_group(plan, group)
            current = ShardRun(
                args, state, _commit_group(plan, number, directory, files, group)
            )
            previous_handler = signal.signal(signal.SIGINT, current.request_stop)
            try:
                while current.state["phase"] != "complete":
                    if stop_at is not None and time.time() >= stop_at:
                        return False
                    current.sample_pass()
                    emit(
                        "counts",
                        group=group,
                        generation=current.state["generation"],
                        counts={
                            role: {
                                name: stream["count"]
                                for name, stream in entry["streams"].items()
                            }
                            for role, entry in current.state["estimator_state"][
                                group
                            ].items()
                        },
                    )
            finally:
                signal.signal(signal.SIGINT, previous_handler)
    _write_manifest(manifest_path, _manifest(plan, number, files, True))
    _collect_snapshots(directory, files)
    return True


def measure_shard(plan, number, directory, stop_at=None):
    """Resume only committed snapshots; working files never supply state."""
    validate_plan(plan)
    if isinstance(number, bool) or number not in range(8):
        raise ValueError("Unknown shard number")
    directory = Path(directory)
    _worker_directory(directory)
    directory.parent.mkdir(parents=True, exist_ok=True)
    lock = Path(str(directory) + ".lock")
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise ValueError("Worker destination is locked") from error
    try:
        directory.mkdir(exist_ok=True)
        complete = _measure_groups(plan, number, directory, stop_at)
        emit("shard-complete", shard=number, complete=complete, plan=plan["sha256"])
        return complete
    finally:
        lock.rmdir()


def _load_shard(plan, directory, seen):
    manifest = _read(directory / "manifest.json")
    number = manifest.get("shard")
    if (
        isinstance(number, bool)
        or not isinstance(number, int)
        or number not in range(8)
        or number in seen
    ):
        raise ValueError("Duplicate or invalid shard")
    manifest = _load_manifest(plan, number, directory, require_complete=True)
    seen.add(number)
    groups = {}
    for group in plan["shards"][number]:
        started = time.monotonic()
        name = f"group-{group}.json"
        raw = _snapshot_bytes(directory, name, manifest["files"][name])
        state = _decode_checkpoint(plan, group, read_json(raw)["__metadata__"])
        if state["phase"] != "complete":
            raise ValueError("Assembly needs complete groups")
        groups[group] = state["estimator_state"][group]
        emit(
            "assembly-group-validated",
            group=group,
            seconds=time.monotonic() - started,
            bytes=len(raw),
        )
    return groups


def generation_diagnostics(state, report):
    """Persist measured convergence and guard/count facts without volatile timing."""
    shift = None
    if state["generation"] > 0:
        previous, measured, following = _prepare_transition(state, generate_table)
        shift = generate_table.calculate_max_ev_shift(
            previous, following, state["requested_pairs"], measured
        )
    return {
        "generation": state["generation"],
        "policy_sha256": state["policy_sha256"],
        "convergence_shift": shift if shift is None or math.isfinite(shift) else None,
        "guard": {
            status: sum(row["status"] == status for row in report["rows"])
            for status in ("resolved-positive", "unresolved", "resolved-negative")
        },
        "counts": {
            group: {
                role: {
                    name: stream["count"] for name, stream in entry["streams"].items()
                }
                for role, entry in roles.items()
            }
            for group, roles in state["estimator_state"].items()
        },
    }


def assemble(plan, directories, diagnostics=None):
    """Validate every expected group and then transition the whole table once."""
    started = time.monotonic()
    metadata = validate_plan(plan)
    emit("assembly-start", plan=plan["sha256"], generation=metadata["generation"])
    if len(directories) != 8:
        raise ValueError("Assembly requires eight shards")
    seen = set()
    groups = {}
    for directory in directories:
        groups.update(_load_shard(plan, Path(directory), seen))
    ordered = _rank_keys(metadata["requested_pairs"])
    if seen != set(range(8)) or set(groups) != set(ordered):
        raise ValueError("Assembly group coverage differs")
    state = {
        **copy.deepcopy(metadata),
        "phase": "complete",
        "estimator_state": {group: groups[group] for group in ordered},
    }
    report = precut_twin_report(state)
    enforce_precut_report(report)
    emit("assembly-validation-end", seconds=time.monotonic() - started)
    facts = generation_diagnostics(state, report)
    emit("assembly-diagnostics", **facts)
    if diagnostics is not None:
        diagnostics.update(facts)
    output = _project_output(state, generate_table)
    if _should_stop_after_complete(state, generate_table):
        emit(
            "assembly-terminal",
            seconds=time.monotonic() - started,
            convergence_shift=facts["convergence_shift"],
        )
        return output, None
    _transition(state, generate_table)
    emit("assembly-transition", seconds=time.monotonic() - started)
    return output, _seal(state, plan["reference"], plan["provenance"])


def client_bytes(output):
    """Match the existing client writer's exact serialization."""
    return (
        json.dumps(generate_table.build_client_table(output), separators=(",", ":"))
        + "\n"
    ).encode()


def install_bundle(destination, files, decision):
    """Install once, or accept an exactly identical successful prior bundle."""
    if "bundle.json" in files or any(Path(name).name != name for name in files):
        raise ValueError("Bundle filenames must be flat and unreserved")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = Path(str(destination) + ".lock")
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise ValueError("Bundle destination is locked") from error
    staging = None
    try:
        payload = {
            **decision,
            "contract": BUNDLE_CONTRACT,
            "files": {
                name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()
            },
        }
        contents = {**files, "bundle.json": json_bytes(payload)}
        if destination.exists():
            if (
                destination.is_symlink()
                or set(p.name for p in destination.iterdir()) != set(contents)
                or any(
                    (destination / name).is_symlink()
                    or (destination / name).read_bytes() != raw
                    for name, raw in contents.items()
                )
            ):
                raise ValueError("Existing bundle differs")
            return
        staging = Path(tempfile.mkdtemp(prefix=".v4-assembly-", dir=destination.parent))
        for name, raw in contents.items():
            (staging / name).write_bytes(raw)
        staging.rename(destination)
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)
        lock.rmdir()


def read_bundle(directory):
    """Check successful bundle completion and every exact output digest."""
    directory = Path(directory)
    manifest = _read(directory / "bundle.json")
    if (
        manifest.get("contract") != BUNDLE_CONTRACT
        or manifest.get("success") is not True
    ):
        raise ValueError("Bundle is not a successful completion")
    files = manifest.get("files")
    if not isinstance(files, dict) or any(Path(name).name != name for name in files):
        raise ValueError("Invalid bundle file manifest")
    if set(p.name for p in directory.iterdir()) != {"bundle.json", *files}:
        raise ValueError("Bundle files differ")
    for name, digest in files.items():
        _read(directory / name)
        if file_digest(directory / name) != digest:
            raise ValueError("Bundle file digest differs")
    return manifest


def reference_files(directory, require_complete=False):
    """Pin exact v3 means and the release provenance downloaded with them."""
    directory = Path(directory)
    names = (
        "expected_crib_points.json",
        "expected_crib_points.client.json",
        "release.json",
    )
    documents = {name: _read(directory / name) for name in names}
    full, means = (documents[name] for name in names[:2])
    release = documents["release.json"]
    if release.get("tag_name") != "expected-crib-points":
        raise ValueError("Shadow reference release tag differs")
    for name in names[:2]:
        assets = [
            asset for asset in release.get("assets", []) if asset.get("name") == name
        ]
        if len(assets) != 1:
            raise ValueError("Shadow reference asset membership differs")
        asset = assets[0]
        identifier = asset.get("id")
        if (
            isinstance(identifier, bool)
            or not isinstance(identifier, int)
            or identifier <= 0
        ):
            raise ValueError("Shadow reference asset ID is invalid")
        if asset.get("size") != (directory / name).stat().st_size or asset.get(
            "digest"
        ) != "sha256:" + file_digest(directory / name):
            raise ValueError("Shadow reference asset digest or size differs")
    if (
        full.get("__metadata__", {}).get("generation_method")
        != "artifact_pipeline.generate_table.v3"
    ):
        raise ValueError("Shadow reference must be the v3 table")
    if generate_table.build_client_table(full) != means:
        raise ValueError("Shadow reference means differ from full table")
    mean_buckets("crib", means)
    _matching_means(full, means)
    if require_complete and set(full) - {"__metadata__"} != set(
        generate_table.get_canonical_pairs()
    ):
        raise ValueError("Production reference must contain all canonical keys")
    return {name: file_digest(directory / name) for name in names}


def difference_quantiles(absolute):
    """Linear empirical quantiles of descriptive root-mean differences."""
    differences = sorted(row["difference"] for row in absolute)
    quantiles = {}
    for fraction in (0, 0.05, 0.5, 0.95, 1):
        position = fraction * (len(differences) - 1)
        lower, upper = math.floor(position), math.ceil(position)
        quantiles[str(fraction)] = differences[lower] + (position - lower) * (
            differences[upper] - differences[lower]
        )
    return quantiles


def _comparison(output, reference):
    twins = []
    for row in output["__metadata__"]["precut_twin_report"]["rows"]:
        group, role = row["rank_group"], row["role"]
        own = group.split("_")
        previous_gap = sum(
            (4 - own.count(rank))
            / 50
            * (
                reference[f"{group}_Suited"][role][rank]["mu"]
                - reference[f"{group}_Unsuited"][role][rank]["mu"]
            )
            for rank in "A23456789TJQK"
        )
        twins.append(
            {
                "rank_group": group,
                "role": role,
                "v3_gap": previous_gap,
                "v4_gap": row["gap"]["mu"],
            }
        )
    absolute = [
        {
            "identity": f"{key}/{role}/{rank}",
            "v3_mu": reference[key][role][rank]["mu"],
            "v4_mu": bucket["mu"],
            "difference": bucket["mu"] - reference[key][role][rank]["mu"],
        }
        for key, roles in output.items()
        if key != "__metadata__"
        for role, cuts in roles.items()
        for rank, bucket in cuts.items()
    ]
    quantiles = difference_quantiles(absolute)
    return {
        "scope": "descriptive-v3-v4-differences-policies-may-differ-not-paired-or-calibrated",
        "twins": twins,
        "v3_negative": sum(row["v3_gap"] < 0 for row in twins),
        "absolute": absolute,
        "record_count": len(absolute),
        "difference_quantiles": quantiles,
        "quantile_method": "linear interpolation at (N-1)*q",
        "max_absolute_difference": max(
            absolute, key=lambda row: abs(row["difference"])
        ),
    }


def _decode_full(plan, saved):
    groups = _rank_keys(plan["metadata"]["requested_pairs"])
    if set(saved["estimator_state"]) != set(groups):
        raise ValueError("Final checkpoint group coverage differs")
    decoded = {}
    for group in groups:
        started = time.monotonic()
        local = {
            **saved,
            "requested_pairs": _pairs(plan, [group]),
            "estimator_state": {group: saved["estimator_state"][group]},
        }
        decoded.update(_decode_checkpoint(plan, group, local)["estimator_state"])
        emit("final-group-validated", group=group, seconds=time.monotonic() - started)
    return decoded


def final_output(plan, directory, reference):
    """Rebuild from terminal moments; never execute sampling or a transition."""
    metadata = validate_plan(plan)
    manifest = read_bundle(directory)
    if (
        manifest.get("kind") != "generation"
        or manifest.get("terminal") is not True
        or manifest.get("plan_sha256") != plan["sha256"]
    ):
        raise ValueError("Final output needs this plan's terminal generation")
    if reference_files(reference) != plan["reference"]:
        raise ValueError("Shadow reference digest differs from plan")
    saved = _read(Path(directory) / "expected_crib_points.json")["__metadata__"]
    pairs = metadata["requested_pairs"]
    _check_metadata(saved, _args(metadata, "unused"), pairs, generate_table)
    _check_identity(saved, plan, _rank_keys(pairs))
    decoded = _decode_full(plan, saved)
    if saved["phase"] != "complete":
        raise ValueError("Final output needs a complete checkpoint")
    _check_phase(saved, decoded)
    state = {k: v for k, v in saved.items() if k != "precut_twin_report"}
    state["estimator_state"] = decoded
    enforce_precut_report(precut_twin_report(state))
    if not _should_stop_after_complete(state, generate_table):
        raise ValueError("Final generation is not converged")
    output = _project_output(state, generate_table)
    client_digest = hashlib.sha256(client_bytes(output)).hexdigest()
    if client_digest != manifest["files"].get("expected_crib_points.client.json"):
        raise ValueError("Rebuilt client digest differs from assembled bundle")
    baseline = _read(Path(reference) / "expected_crib_points.json")
    return output, _comparison(output, baseline)


def _protect_directory(inputs, destination):
    destination = Path(destination)
    if destination.is_symlink() or any(
        path.resolve().is_relative_to(destination.resolve())
        or (path.is_dir() and destination.resolve().is_relative_to(path.resolve()))
        for path in inputs
    ):
        raise ValueError("Output directory must not contain an input")
    protect_paths(inputs, [destination, Path(str(destination) + ".lock")])


def _production_args(bootstrap):
    metadata = {
        "seed": 42,
        "run_control": {
            "target_samples": 22000,
            "infinite": False,
            "dampening": 0.5,
            "max_generations": 2,
            "convergence_threshold": 0.10,
            "fail_on_non_convergence": True,
        },
    }
    args = _args(metadata, "unused")
    args.bootstrap = str(bootstrap)
    return args


def _bundle_output(output, next_plan):
    files = {
        "expected_crib_points.json": json_bytes(output),
        "expected_crib_points.client.json": client_bytes(output),
    }
    if next_plan is not None:
        files["next-plan.json"] = json_bytes(next_plan)
    return files


def _options(argv):
    """Fixed production-sized shadow stages; execution needs separate approval."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="stage", required=True)
    for name in ("plan", "measure", "assemble", "finalize"):
        command = subparsers.add_parser(name)
        command.add_argument("--output", type=Path, required=True)
        if name != "plan":
            command.add_argument("--plan", type=Path, required=True)
    subparsers.choices["plan"].add_argument("--bootstrap", type=Path, required=True)
    for name in ("plan", "finalize"):
        subparsers.choices[name].add_argument("--reference", type=Path, required=True)
    measure = subparsers.choices["measure"]
    measure.add_argument("--shard", type=int, choices=range(8), required=True)
    measure.add_argument("--stop-at", type=float, required=True)
    subparsers.choices["assemble"].add_argument(
        "--shards", nargs=8, type=Path, required=True
    )
    subparsers.choices["finalize"].add_argument("--assembled", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv=None):
    """Run only the requested fixed-budget shadow stage."""
    options = _options(argv)
    if options.stage == "plan":
        inputs = [options.bootstrap, options.reference, *options.reference.iterdir()]
        _protect_directory(inputs, options.output)
        reference = reference_files(options.reference, require_complete=True)
        plan = initial_plan(_production_args(options.bootstrap), reference=reference)
        install_bundle(
            options.output,
            {"plan.json": json_bytes(plan)},
            {"kind": "plan", "success": True, "plan_sha256": plan["sha256"]},
        )
        return
    plan = _read(options.plan)
    inputs = [options.plan]
    if options.stage == "measure":
        _protect_directory(inputs, options.output)
        paths = [
            options.output / "manifest.json",
            *[
                options.output / f"group-{g}.json"
                for g in plan["shards"][options.shard]
            ],
        ]
        protect_paths(inputs, paths + [Path(str(path) + ".tmp") for path in paths])
        if not measure_shard(plan, options.shard, options.output, options.stop_at):
            raise SystemExit("Sampling deadline reached; shard is incomplete")
        return
    if options.stage == "assemble":
        inputs += [path for directory in options.shards for path in directory.iterdir()]
        _protect_directory(inputs, options.output)
        diagnostics = {}
        output, next_plan = assemble(plan, options.shards, diagnostics)
        files = {
            **_bundle_output(output, next_plan),
            "diagnostics.json": json_bytes(diagnostics),
        }
        terminal = next_plan is None
    else:
        inputs += [
            options.assembled,
            options.reference,
            *options.assembled.iterdir(),
            *options.reference.iterdir(),
        ]
        _protect_directory(inputs, options.output)
        output, comparison = final_output(plan, options.assembled, options.reference)
        files = {
            **_bundle_output(output, None),
            "comparison.json": json_bytes(comparison),
        }
        terminal = True
    install_bundle(
        options.output,
        files,
        {
            "kind": "generation" if options.stage == "assemble" else "shadow",
            "success": True,
            "plan_sha256": plan["sha256"],
            "generation": output["__metadata__"]["generation"],
            "terminal": terminal,
        },
    )


if __name__ == "__main__":
    main()
