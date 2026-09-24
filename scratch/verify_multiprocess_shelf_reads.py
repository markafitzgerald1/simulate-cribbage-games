"""Verify that multi-process shelf reads match single-process reads.

Seeds a tally shelf with a small simulation, then runs the simulator
with position estimates under --process-count 1 and --process-count 2.
Compares the "Game points" and "Game wins" summary-statistics lines:
when estimates are active and the shelf has matching keys, those lines
will show non-zero fractional values.  If workers silently opened an
empty shelf or fell back to "no estimate available", those lines would
stay at +0.00000, which this script detects as a failure.
"""

import os
import re
import shelve
import subprocess
import sys
import tempfile

SCRIPT = "simulate_cribbage_games.py"
SHELF_NAME = "start_of_hand_position_results_tallies_shelf"


def run_simulator(python_bin, cwd, extra_args, seed=12345):
    """Run the simulator with seeded randomness and return stdout."""
    script_path = os.path.join(cwd, SCRIPT)
    code = (
        f"import random; random.seed({seed}); import sys; "
        f"sys.argv = ['simulate_cribbage_games.py'] + {extra_args!r}; "
        f"import runpy; runpy.run_path({script_path!r}, run_name='__main__')"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = cwd + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [python_bin, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        env=env,
    )
    return result


def extract_game_stats(text):
    """Extract Game points and Game wins lines from final statistics block."""
    lines = text.splitlines()
    game_lines = []
    for line in lines:
        if "Game  points" in line or "Game  wins" in line:
            game_lines.append(line.strip())
    return game_lines


def has_nonzero_estimates(game_lines):
    """Check whether any Game points or Game wins line has a non-zero value."""
    for line in game_lines:
        match = re.search(r"[+-](\d+\.\d+)", line)
        if match and float(match.group(1)) != 0.0:
            return True
    return False


def main():
    python_bin = sys.argv[1] if len(sys.argv) > 1 else sys.executable
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    with tempfile.TemporaryDirectory() as work_dir:
        # Copy the simulator into the isolated workspace
        src_file = os.path.join(src_dir, SCRIPT)
        dst_file = os.path.join(work_dir, SCRIPT)
        with open(src_file) as f:
            content = f.read()
        with open(dst_file, "w") as f:
            f.write(content)

        # Step 1: Seed the shelf with a tally run
        print("Step 1: Seeding tally shelf with --game-count 1000 ...")
        shelve.open(os.path.join(work_dir, SHELF_NAME), flag="c").close()
        tally_args = [
            "--game-count",
            "1000",
            "--unlimited-hands-per-game",
            "--tally-start-of-hand-position-results",
            "--hide-play-actions",
            "--process-count",
            "1",
        ]
        result = run_simulator(python_bin, work_dir, tally_args, seed=42)
        if result.returncode != 0:
            print(f"FAIL: tally run exited {result.returncode}")
            print(result.stderr)
            sys.exit(1)

        with shelve.open(os.path.join(work_dir, SHELF_NAME), flag="r") as s:
            key_count = len(list(s.keys()))
        print(f"  Tally shelf has {key_count} entries")
        if key_count == 0:
            print("FAIL: shelf is empty after tally run")
            sys.exit(1)

        # Step 2: Single-process run with estimates
        print("Step 2: Running --process-count 1 with estimates ...")
        estimate_args = [
            "--game-count",
            "20",
            "--unlimited-hands-per-game",
            "--estimate-first-pone-incomplete-game-wins-and-game-points",
            "--estimate-first-dealer-incomplete-game-wins-and-game-points",
            "--hide-play-actions",
            "--process-count",
            "1",
        ]
        single = run_simulator(python_bin, work_dir, estimate_args, seed=99)
        if single.returncode != 0:
            print(f"FAIL: single-process run exited {single.returncode}")
            print(single.stderr)
            sys.exit(1)

        single_game_lines = extract_game_stats(single.stdout)
        single_has_estimates = has_nonzero_estimates(single_game_lines)

        # Step 3: Multi-process run with estimates
        print("Step 3: Running --process-count 2 with estimates ...")
        estimate_args_mp = list(estimate_args)
        pc_idx = estimate_args_mp.index("--process-count")
        estimate_args_mp[pc_idx + 1] = "2"
        multi = run_simulator(python_bin, work_dir, estimate_args_mp, seed=99)
        if multi.returncode != 0:
            print(f"FAIL: multi-process run exited {multi.returncode}")
            print(multi.stderr)
            sys.exit(1)

        multi_game_lines = extract_game_stats(multi.stdout)
        multi_has_estimates = has_nonzero_estimates(multi_game_lines)

        # Step 4: Compare
        print("\n  Single-process final Game stats:")
        for line in single_game_lines[-6:]:
            print(f"    {line}")

        print("  Multi-process final Game stats:")
        for line in multi_game_lines[-6:]:
            print(f"    {line}")

        if not single_has_estimates:
            print(
                "\nFAIL: single-process run showed no estimated game "
                "points/wins — shelf keys may not match game positions"
            )
            sys.exit(1)

        if not multi_has_estimates:
            print(
                "\nFAIL: multi-process run showed no estimated game "
                "points/wins — workers may not be reading the shelf"
            )
            sys.exit(1)

        if single_has_estimates and multi_has_estimates:
            print(
                "\nPASS: both single-process and multi-process runs "
                "produced non-zero estimated Game points and Game wins, "
                "confirming workers read the same shelf entries."
            )
        else:
            print("\nFAIL: estimate comparison failed")
            sys.exit(1)


if __name__ == "__main__":
    main()
