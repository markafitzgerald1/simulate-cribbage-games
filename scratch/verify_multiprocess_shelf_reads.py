"""Verify that workers reading the tally shelf under spawn and forkserver
see the exact same data as a direct parent read.

After seeding, opens TALLY_SHELF_PATH read-only in the parent and in children
started with multiprocessing.get_context("spawn") and "forkserver".
Asserts that parent, spawn child, and forkserver child read sorted(shelf.items())
identically and that the shelf is non-empty.

When invoked with --empty, runs against an empty shelf so the non-empty assertion
fails, proving that the check discriminates between populated and empty shelves.
"""

import argparse
import hashlib
import multiprocessing
import os
import pickle
import shelve
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import simulate_cribbage_games  # noqa: E402, F401
from simulate_cribbage_games import (  # noqa: E402
    GameScoreResultsTallies,
    TALLY_SHELF_PATH,
)

# Alias GameScoreResultsTallies in __main__ so shelve unpickling finds it
# when deserializing records written by simulate_cribbage_games.py.
main_mod = sys.modules.get("__main__")
if main_mod is not None:
    setattr(main_mod, "GameScoreResultsTallies", GameScoreResultsTallies)

SCRIPT = "simulate_cribbage_games.py"


def read_shelf_digest(shelf_path: str):
    """Return (key_count, sha256_hex) for the shelf contents."""
    cur_main = sys.modules.get("__main__")
    if cur_main is not None:
        setattr(cur_main, "GameScoreResultsTallies", GameScoreResultsTallies)

    with shelve.open(shelf_path, flag="r") as s:
        items = sorted(s.items(), key=lambda kv: kv[0])
    digest = hashlib.sha256(pickle.dumps(items)).hexdigest()
    return len(items), digest


def _worker_read_shelf(shelf_path: str, queue):
    """Worker target for spawn and forkserver children."""
    cur_main = sys.modules.get("__main__")
    if cur_main is not None:
        setattr(cur_main, "GameScoreResultsTallies", GameScoreResultsTallies)

    try:
        count, digest = read_shelf_digest(shelf_path)
        queue.put(("OK", count, digest))
    except Exception as exc:  # pylint: disable=broad-exception-caught
        queue.put(("ERR", str(exc), ""))


def verify_shelf_reads(shelf_path: str):
    """Assert parent, spawn, and forkserver read identical, non-empty items."""
    print(f"Reading shelf at: {shelf_path}")
    parent_count, parent_digest = read_shelf_digest(shelf_path)
    print(f"  Parent:     {parent_count} entries, digest {parent_digest[:16]}…")

    # Preload sqlite3 in forkserver server process to ensure clean initialization
    multiprocessing.set_forkserver_preload(["sqlite3"])

    child_results = {}
    for method in ("forkserver", "spawn"):
        ctx = multiprocessing.get_context(method)
        q = ctx.SimpleQueue()  # type: ignore[attr-defined]
        p = ctx.Process(  # type: ignore[attr-defined]
            target=_worker_read_shelf, args=(shelf_path, q)
        )
        p.start()
        p.join(timeout=30)
        assert p.exitcode == 0, f"{method} process failed with exitcode {p.exitcode}"
        assert not q.empty(), f"{method} process exited without sending result"
        status, count, digest = q.get()
        assert status == "OK", f"{method} process error: {count}"
        print(f"  {method.capitalize():11} {count} entries, digest {digest[:16]}…")
        child_results[method] = (count, digest)

    spawn_count, spawn_digest = child_results["spawn"]
    forkserver_count, forkserver_digest = child_results["forkserver"]

    # Assert all three are non-empty
    assert (
        parent_count > 0
    ), f"AssertionError: shelf is empty! parent_count={parent_count}"
    assert (
        spawn_count > 0
    ), f"AssertionError: spawn child read empty shelf! count={spawn_count}"
    assert (
        forkserver_count > 0
    ), f"AssertionError: forkserver child read empty shelf! count={forkserver_count}"

    # Assert exact equality across parent, spawn, and forkserver
    assert (
        parent_count == spawn_count == forkserver_count
    ), f"Count mismatch: parent={parent_count}, spawn={spawn_count}, forkserver={forkserver_count}"
    assert (
        parent_digest == spawn_digest == forkserver_digest
    ), f"Digest mismatch: parent={parent_digest}, spawn={spawn_digest}, forkserver={forkserver_digest}"

    print(
        f"\nSUCCESS: parent, spawn, and forkserver read exactly equal, "
        f"non-empty data ({parent_count} entries)."
    )


def seed_shelf(work_dir: str, python_bin: str, game_count: int = 200) -> str:
    """Seed a tally shelf in work_dir with simulation games."""
    shelf_path = os.path.join(work_dir, TALLY_SHELF_PATH)
    shelve.open(shelf_path, flag="c").close()

    script_path = os.path.abspath(SCRIPT)
    seed_code = (
        f"import random; random.seed(42); import sys; "
        f"sys.argv = ['simulate_cribbage_games.py', "
        f"'--game-count', '{game_count}', '--unlimited-hands-per-game', "
        f"'--tally-start-of-hand-position-results', "
        f"'--hide-play-actions', '--process-count', '1']; "
        f"import runpy; runpy.run_path({script_path!r}, run_name='__main__')"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = work_dir + os.pathsep + env.get("PYTHONPATH", "")
    res = subprocess.run(
        [python_bin, "-c", seed_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=work_dir,
        env=env,
        check=False,
    )
    assert res.returncode == 0, f"Tally seeding failed:\n{res.stderr}"
    return shelf_path


def main():
    parser = argparse.ArgumentParser(
        description="Verify multiprocess shelf read parity across spawn and forkserver."
    )
    parser.add_argument(
        "--empty",
        action="store_true",
        help="Run against an empty shelf to verify non-empty assertion fails.",
    )
    parser.add_argument(
        "--python-bin",
        default=sys.executable,
        help="Path to Python binary.",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as work_dir:
        if args.empty:
            print("=== Running negative check on EMPTY shelf ===")
            shelf_path = os.path.join(work_dir, TALLY_SHELF_PATH)
            shelve.open(shelf_path, flag="c").close()
            verify_shelf_reads(shelf_path)
        else:
            print("=== Running positive check on SEEDED shelf ===")
            print("Seeding tally shelf ...")
            shelf_path = seed_shelf(work_dir, args.python_bin, game_count=200)
            verify_shelf_reads(shelf_path)


if __name__ == "__main__":
    main()
