"""Acceptance test for multi-process runs of the legacy simulator.

Exact output can't be compared here, unlike the single-process golden
cases: spawned workers don't inherit the parent's random seed, and their
progress output interleaves. The test checks invariants of the final
summary instead.
"""

import os
import shelve
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LEGACY_SIMULATOR = Path(__file__).resolve().parent / "simulate_cribbage_games.py"
TALLY_SHELF = "start_of_hand_position_results_tallies_shelf"
GAME_COUNT = 200
TIMEOUT_SECONDS = 120
COMMAND = (
    "--first-pone-dealt-cards",
    "AC,2D,3H,4S,5C,6D",
    "--first-pone-kept-cards",
    "2D,3H,4S,5C",
    "--hide-first-pone-hands",
    "--hide-first-dealer-hands",
    "--hide-play-actions",
    "--game-count",
    str(GAME_COUNT),
    "--process-count",
    "2",
)


def run_two_workers(working_directory: str) -> subprocess.CompletedProcess[str]:
    """Run COMMAND, killing the whole process group if it hangs.

    A plain timeout kills only the parent and leaves hung workers behind,
    so the run gets its own session and the group is killed on timeout.
    """
    with subprocess.Popen(
        [sys.executable, str(LEGACY_SIMULATOR), *COMMAND],
        cwd=working_directory,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        # Unbuffered, so each worker's summary reaches the pipe while it still
        # holds the statistics lock and n = 100 cannot print after n = 200.
        # The variable, unlike -u, also reaches spawned workers.
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
        start_new_session=True,
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"two-worker run hung for {TIMEOUT_SECONDS} s; stderr:\n{stderr}"
            ) from None
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


@unittest.skipIf(os.name == "nt", "the hang guard kills a POSIX process group")
class TestLegacyMultiprocessRun(unittest.TestCase):
    """A two-worker run completes and reports every game."""

    def assert_completes(self, shelf_entries: dict[str, int]) -> None:
        with tempfile.TemporaryDirectory() as working_directory:
            with shelve.open(
                os.path.join(working_directory, TALLY_SHELF), flag="c"
            ) as shelf:
                shelf.update(shelf_entries)
            result = run_two_workers(working_directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        lines = result.stdout.splitlines()
        completion = f"Simulated {GAME_COUNT} games with 2 worker processes "
        self.assertTrue(lines[-1].startswith(completion), result.stdout)
        final_summary = lines[
            lines.index(
                f"Mean play statistics 95% confidence intervals (n = {GAME_COUNT}):"
            ) :
        ]
        # Pone never owns the crib, so its crib points total exactly zero.
        zero_crib = "First Pone                    Crib  points:   +0.00000 ±  0.00000"
        self.assertEqual(final_summary.count(zero_crib), 1, result.stdout)

    def test_empty_shelf(self) -> None:
        # The README's setup creates an empty shelf, which compared equal to
        # the empty statistics proxy and was swapped for the shelf's path.
        self.assert_completes({})

    def test_non_empty_shelf(self) -> None:
        self.assert_completes({"not a position": 0})


if __name__ == "__main__":
    unittest.main()
