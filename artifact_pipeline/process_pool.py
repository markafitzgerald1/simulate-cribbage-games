"""Bounded, ordered process work with frozen pass snapshots and RSS reporting."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor
from itertools import islice
from importlib import import_module
import multiprocessing
import os
import sys
from typing import Any
from types import ModuleType

resource: ModuleType | None
try:
    resource = import_module("resource")
except ImportError:
    resource = None

_WORKER_STATE: tuple[Callable[[Any, Any], Any], Any] | None = None

# ProcessPoolExecutor raises ValueError above this many workers on Windows.
WINDOWS_MAX_WORKERS = 61


def max_process_workers() -> int | None:
    """Return the platform's hard worker limit, or None when it has none."""
    return WINDOWS_MAX_WORKERS if sys.platform == "win32" else None


def default_worker_count() -> int:
    """Use every available CPU, but never more than the platform allows."""
    count = getattr(os, "process_cpu_count", os.cpu_count)() or 1
    return min(count, max_process_workers() or count)


def validate_worker_count(workers: int) -> int:
    """Reject counts the platform's process pool would refuse mid-run."""
    if workers <= 0:
        raise ValueError("Workers must be positive")
    maximum = max_process_workers()
    if maximum is not None and workers > maximum:
        raise ValueError(f"Workers cannot exceed {maximum} on this platform")
    return workers


def _initialize_worker(function: Callable[[Any, Any], Any], context: Any) -> None:
    """Install one immutable snapshot per worker, rather than per task."""
    global _WORKER_STATE  # pylint: disable=global-statement
    _WORKER_STATE = (function, context)


def _peak_rss_bytes() -> int | None:
    """Normalize macOS bytes and Linux KiB to peak RSS bytes at the call."""
    if resource is None:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def _worker_job(task: Any) -> tuple[Any, int, int | None]:
    # The peak is sampled before ProcessPoolExecutor pickles and queues the
    # returned value, so it excludes any growth from serializing the result.
    if _WORKER_STATE is None:
        raise RuntimeError("Process worker has no pass snapshot")
    function, context = _WORKER_STATE
    value = function(context, task)
    return value, os.getpid(), _peak_rss_bytes()


def ordered_process_map(
    function: Callable[[Any, Any], Any],
    context: Any,
    tasks: Iterable[Any],
    workers: int,
) -> Iterator[Any]:
    """Yield in input order with bounded pending work and report worker memory."""
    peaks: dict[int, int] = {}
    # Spawn avoids inheriting legacy SQLite connections and works on macOS and
    # Linux. The bounded map keeps large rollout observation lists off the queue.
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_initialize_worker,
        initargs=(function, context),
    ) as pool:
        inputs = iter(tasks)
        pending = deque(
            pool.submit(_worker_job, task) for task in islice(inputs, 2 * workers)
        )
        while pending:
            value, pid, peak = pending.popleft().result()
            if peak is not None:
                peaks[pid] = max(peaks.get(pid, 0), peak)
            yield value
            pending.extend(pool.submit(_worker_job, task) for task in islice(inputs, 1))
    for pid, peak in sorted(peaks.items()):
        print(
            f"[play-workers] pid {pid}: peak RSS before result serialization "
            f"{peak / 1024**2:.1f} MiB",
            file=sys.stderr,
            flush=True,
        )
