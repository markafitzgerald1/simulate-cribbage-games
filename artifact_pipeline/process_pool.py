"""Bounded, ordered process work with frozen pass snapshots and RSS reporting."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor
from itertools import islice
import multiprocessing
import os
import resource
import sys
from typing import Any

_WORKER_STATE: tuple[Callable[[Any, Any], Any], Any] | None = None


def _initialize_worker(function: Callable[[Any, Any], Any], context: Any) -> None:
    """Install one immutable snapshot per worker, rather than per task."""
    global _WORKER_STATE  # pylint: disable=global-statement
    _WORKER_STATE = (function, context)


def _peak_rss_bytes() -> int:
    """Normalize macOS bytes and Linux KiB to whole-process peak RSS bytes."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def _worker_job(task: Any) -> tuple[Any, int, int]:
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
            peaks[pid] = max(peaks.get(pid, 0), peak)
            yield value
            pending.extend(pool.submit(_worker_job, task) for task in islice(inputs, 1))
    for pid, peak in sorted(peaks.items()):
        print(
            f"[play-workers] pid {pid}: peak RSS {peak / 1024**2:.1f} MiB",
            file=sys.stderr,
            flush=True,
        )
