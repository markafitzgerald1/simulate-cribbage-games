"""Verify that workers reading the tally shelf under spawn and forkserver
see the same data as a direct parent read.

Seeds a tally shelf with a short simulation, then opens it read-only in
the parent and in children started with ``spawn`` and ``forkserver``.
Each child returns ``sorted(shelf.items())``, hashed for comparison.
Asserts all three are exactly equal and non-empty.

Then repeats the check on an empty shelf and asserts the non-empty guard
catches it, proving the positive check is not vacuously true.
"""

import hashlib
import multiprocessing
import os
import pickle
import shelve
import subprocess
import sys
import tempfile

# Import the canonical shelf path from the simulator so the script
# cannot drift from the constant the fix introduced.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from simulate_cribbage_games import TALLY_SHELF_PATH  # noqa: E402

SCRIPT = "simulate_cribbage_games.py"


def read_shelf_hash(shelf_path):
    """Return (key_count, sha256_hex) for the shelf contents."""
    with shelve.open(shelf_path, flag="r") as s:
        items = sorted(s.items(), key=lambda kv: kv[0])
    digest = hashlib.sha256(pickle.dumps(items)).hexdigest()
    return len(items), digest


def child_read_shelf(shelf_path, result_dict, label):
    """Target for a child process: read the shelf and store the hash."""
    key_count, digest = read_shelf_hash(shelf_path)
    result_dict[label] = (key_count, digest)


def check_reads(shelf_path, expect_nonempty):
    """Open the shelf in parent, spawn child, forkserver child; compare."""
    parent_count, parent_hash = read_shelf_hash(shelf_path)

    manager = multiprocessing.Manager()
    result_dict = manager.dict()

    for method in ("spawn", "forkserver"):
        ctx = multiprocessing.get_context(method)
        p = ctx.Process(
            target=child_read_shelf,
            args=(shelf_path, result_dict, method),
        )
        p.start()
        p.join(timeout=30)
        if p.exitcode != 0:
            return False, f"{method} child exited {p.exitcode}"

    spawn_count, spawn_hash = result_dict["spawn"]
    forkserver_count, forkserver_hash = result_dict["forkserver"]

    if expect_nonempty and parent_count == 0:
        return False, "parent read 0 entries (expected non-empty shelf)"

    if not expect_nonempty and parent_count > 0:
        return False, f"parent read {parent_count} entries (expected empty shelf)"

    if parent_hash != spawn_hash:
        return False, (
            f"spawn hash mismatch: parent={parent_hash[:16]}… "
            f"spawn={spawn_hash[:16]}…"
        )
    if parent_hash != forkserver_hash:
        return False, (
            f"forkserver hash mismatch: parent={parent_hash[:16]}… "
            f"forkserver={forkserver_hash[:16]}…"
        )

    return True, (
        f"all three reads equal, {parent_count} entries, " f"hash={parent_hash[:16]}…"
    )


def main():
    python_bin = sys.argv[1] if len(sys.argv) > 1 else sys.executable
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    with tempfile.TemporaryDirectory() as work_dir:
        src_file = os.path.join(src_dir, SCRIPT)
        dst_file = os.path.join(work_dir, SCRIPT)
        with open(src_file) as f:
            content = f.read()
        with open(dst_file, "w") as f:
            f.write(content)

        shelf_path = os.path.join(work_dir, TALLY_SHELF_PATH)

        # --- Positive check: seeded non-empty shelf ---
        print("Step 1: Seeding tally shelf ...")
        shelve.open(shelf_path, flag="c").close()

        seed_code = (
            f"import random; random.seed(42); import sys; "
            f"sys.argv = ['simulate_cribbage_games.py', "
            f"'--game-count', '500', '--unlimited-hands-per-game', "
            f"'--tally-start-of-hand-position-results', "
            f"'--hide-play-actions', '--process-count', '1']; "
            f"import runpy; runpy.run_path({dst_file!r}, run_name='__main__')"
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = work_dir + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [python_bin, "-c", seed_code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=work_dir,
            env=env,
        )
        if result.returncode != 0:
            print(f"FAIL: tally seeding exited {result.returncode}")
            print(result.stderr[-500:])
            sys.exit(1)

        print("Step 2: Positive check (non-empty shelf) ...")
        ok, msg = check_reads(shelf_path, expect_nonempty=True)
        print(f"  {msg}")
        if not ok:
            print("FAIL: positive check failed")
            sys.exit(1)
        print("  PASS")

        # --- Negative check: empty shelf ---
        print("Step 3: Negative check (empty shelf) ...")
        with tempfile.TemporaryDirectory() as empty_dir:
            empty_shelf = os.path.join(empty_dir, TALLY_SHELF_PATH)
            shelve.open(empty_shelf, flag="c").close()

            ok_empty, msg_empty = check_reads(empty_shelf, expect_nonempty=True)
            print(f"  {msg_empty}")
            if ok_empty:
                print("FAIL: empty shelf passed the non-empty check")
                sys.exit(1)
            print("  PASS (empty shelf correctly detected)")

        print("\nAll checks passed.")


if __name__ == "__main__":
    main()
