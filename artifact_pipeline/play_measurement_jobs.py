"""Single-owner fixed-policy cells with atomic completion and canonical reduction."""

from __future__ import annotations

import atexit
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import fcntl
from functools import partial
import hashlib
import json
import math
import multiprocessing
from pathlib import Path
import sys
from typing import Any, Iterator, Mapping, Sequence

from artifact_pipeline.fixed_play_inputs import load_fixed_discards
from artifact_pipeline.generate_play_table import (
    DiscardPolicy,
    _empty_entry_accumulators,
    _write_json,
    measure_play_cell,
)
from artifact_pipeline.pegging import POINT_TYPES, ROLES, canonical_hand_key
from artifact_pipeline.play_lines import OpeningLines
from artifact_pipeline.six_layer_policy import SixLayerPolicy, _unique_object

CATEGORIES = (
    "forced",
    "missing_menu_fallback",
    "off_support",
    "heuristic_equivalent",
    "trained",
)


@dataclass(frozen=True)
class MeasurementJobs:
    """Execution choices do not participate in the seeded observation stream."""

    generated_at: str
    workers: int = 1
    checkpoint_dir: Path | None = None
    manifest_sha256: str | None = None

    def validate(self) -> None:
        """Reject ambiguous timestamps and unsupported worker counts."""
        timestamp = datetime.fromisoformat(self.generated_at)
        if timestamp.utcoffset() is None:
            raise ValueError("Generation timestamp needs an explicit timezone")
        if (
            isinstance(self.workers, bool)
            or not isinstance(self.workers, int)
            or self.workers < 1
        ):
            raise ValueError("Workers must be a positive integer")


def sampler_digest() -> str:
    """Reject checkpoints from different code or interpreter arithmetic."""
    root = Path(__file__).parent
    binding = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.glob("*.py"))
        if not path.name.startswith("test_")
    }
    binding["python"] = sys.version
    return hashlib.sha256(_encode(binding)).hexdigest()


def _encode(document: Mapping[str, Any]) -> bytes:
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _read(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_bytes(), object_pairs_hook=_unique_object)
    if not isinstance(document, dict):
        raise ValueError("Checkpoint needs a JSON object")
    return document


@contextmanager
def _locked(directory: Path | None) -> Iterator[None]:
    if directory is None:
        yield
        return
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Checkpoint directory already has an owner") from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class CellWorker:
    """Keep the validated mappings process-local and reuse them across cells."""

    def __init__(
        self, policy: SixLayerPolicy, discards: DiscardPolicy, policy_path: Path
    ):
        self.policy = policy
        self.discards = discards
        self.policy_path = policy_path

    @classmethod
    def load(cls, manifest_path: Path, manifest_digest: str) -> CellWorker:
        """Validate the same pinned components in every process."""
        if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != manifest_digest:
            raise ValueError("Worker policy manifest digest mismatch")
        policy = SixLayerPolicy(manifest_path)
        try:
            discards = load_fixed_discards(
                manifest_path.parent, policy.manifest["discard_population"]
            )
        except BaseException:
            policy.close()
            raise
        return cls(policy, discards, manifest_path)

    def close(self) -> None:
        """Release the read-only mappings owned by this process."""
        self.policy.close()

    def measure(self, task: Mapping[str, Any]) -> dict[str, Any]:
        """Start an incomplete cell from sample zero with its original seed."""
        self.policy.reset_counts()
        entry = measure_play_cell(
            self.discards,
            {role: self.policy for role in ROLES},
            (task["hand"], task["role"], task["seed"]),
            _empty_entry_accumulators(),
            (task["samples"], task["samples"], None),
        )
        # Normalize JSON key types before ANY fresh or resumed parent reduction.
        payload = json.loads(
            _encode(
                {
                    "task": dict(task),
                    "entry": entry,
                    "counts": self.policy.decision_counts(),
                }
            )
        )
        payload = json.loads(_encode(payload))
        return {
            "sha256": hashlib.sha256(_encode(payload)).hexdigest(),
            "payload": payload,
        }


_WORKER: list[CellWorker] = []


def _initialize(manifest_path: Path, digest: str) -> None:
    worker = CellWorker.load(manifest_path, digest)
    _WORKER.append(worker)
    atexit.register(worker.close)


def _measure(task: Mapping[str, Any], directory: Path | None) -> dict[str, Any]:
    document = _WORKER[0].measure(task)
    if directory is not None:
        _write_json(str(directory / _cell_name(task)), document)
    return document


def _validate_cell(document: Mapping[str, Any], task: Mapping[str, Any]) -> None:
    payload = document.get("payload", {})
    if (
        payload.get("task") != task
        or document.get("sha256") != hashlib.sha256(_encode(payload)).hexdigest()
    ):
        raise ValueError("Cell digest or task identity mismatch")
    samples = task["samples"]
    entry, counts = payload["entry"], payload["counts"]
    if (
        set(counts) != set(CATEGORIES)
        or any(
            not isinstance(n, int) or isinstance(n, bool) or n < 0
            for n in counts.values()
        )
        or sum(counts.values()) != 8 * samples
    ):
        raise ValueError("Invalid final measurement decision counts")
    statistics = [entry]
    for role in ROLES:
        player = entry["players"][role]
        statistics.extend([player, *(player["points"][point] for point in POINT_TYPES)])
    for stats in statistics:
        if (
            not isinstance(stats["n"], int)
            or isinstance(stats["n"], bool)
            or stats["n"] != samples
            or any(
                not isinstance(stats[name], (int, float))
                or isinstance(stats[name], bool)
                or not math.isfinite(stats[name])
                for name in ("mu", "se")
            )
            or stats["se"] < 0
        ):
            raise ValueError("Invalid complete-cell statistics")
    OpeningLines.restore(entry["opening"], samples)


def _tasks(binding: Mapping[str, Any]) -> list[dict[str, Any]]:
    digest = hashlib.sha256(_encode(binding)).hexdigest()
    return [
        {
            "run_sha256": digest,
            "hand": hand,
            "role": role,
            "samples": binding["samples"],
            "seed": binding["seed"],
        }
        for hand in binding["hands"]
        for role in ROLES
    ]


def _cell_name(task: Mapping[str, Any]) -> str:
    return f'{canonical_hand_key(task["hand"])}.{task["role"]}.json'


def _prepare(
    directory: Path | None,
    binding: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if directory is None:
        return {}
    path = directory / "run.json"
    if path.exists():
        if _read(path) != binding:
            raise ValueError(
                "Checkpoint run inputs, code, timestamp or schedule changed"
            )
    else:
        if any(directory.glob("*.json")):
            raise ValueError("Cell files without a run manifest")
        _write_json(str(path), binding)
    expected = {_cell_name(task) for task in tasks}
    actual = {path.name for path in directory.glob("*.json")} - {"run.json"}
    if actual - expected:
        raise ValueError("Unexpected or duplicate checkpoint cells")
    completed = {}
    for task in tasks:
        name = _cell_name(task)
        if name in actual:
            document = _read(directory / name)
            _validate_cell(document, task)
            completed[name] = document
    return completed


def measure_cells(
    manifest_path: Path,
    binding: Mapping[str, Any],
    jobs: MeasurementJobs,
    serial_worker: CellWorker,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Abort on a worker failure; preserve only independently complete cells."""
    jobs.validate()
    tasks = _tasks(binding)
    with _locked(jobs.checkpoint_dir):
        completed = _prepare(jobs.checkpoint_dir, binding, tasks)
        pending = [task for task in tasks if _cell_name(task) not in completed]

        def accept(document: dict[str, Any], task: Mapping[str, Any]) -> None:
            _validate_cell(document, task)
            name = _cell_name(task)
            if name in completed:
                raise ValueError("Duplicate completed cell")
            if jobs.checkpoint_dir is not None and jobs.workers == 1:
                _write_json(str(jobs.checkpoint_dir / name), document)
            completed[name] = document
            print(
                f"[fixed-play] complete {len(completed)}/{len(tasks)}",
                file=sys.stderr,
                flush=True,
            )

        if jobs.workers == 1:
            for task in pending:
                accept(serial_worker.measure(task), task)
        elif pending:
            executor = ProcessPoolExecutor(
                max_workers=jobs.workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=partial(
                    _initialize, manifest_path, binding["policy_manifest_sha256"]
                ),
            )
            try:
                futures = {
                    executor.submit(_measure, task, jobs.checkpoint_dir): task
                    for task in pending
                }
                for future in as_completed(futures):
                    accept(future.result(), futures[future])
            except BaseException:
                # Python 3.14 provides this API; pinned older mypy stubs do not.
                getattr(executor, "terminate_workers")()
                raise
            finally:
                executor.shutdown(wait=True, cancel_futures=True)
        if len(completed) != len(tasks):
            raise ValueError("Missing complete cells")
        table: dict[str, Any] = {}
        counts: Counter[str] = Counter({category: 0 for category in CATEGORIES})
        for task in tasks:
            payload = completed[_cell_name(task)]["payload"]
            table.setdefault(canonical_hand_key(task["hand"]), {})[task["role"]] = (
                payload["entry"]
            )
            counts.update(payload["counts"])
        return table, dict(counts)
