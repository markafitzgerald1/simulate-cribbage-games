"""Python Version / Core Dependency Upgrade Regression Checker.

This script executes a suite of representative test cases (covering both
game simulations and artifact table generation) using two different Python
interpreters. It verifies that their exit codes, stdout, stderr, and generated
JSON files match 100% identically (with elapsed performance stats normalized).

Usage:
    python3 scratch/verify_upgrade.py <old_python_bin> <new_python_bin>

Customizing / Genericizing for Future Upgrades:
    - Test cases are configured in the `TEST_CASES` list. To check new features,
      flags, or scripts added in future versions, simply add entries to `TEST_CASES`.
    - If future database shelves use a name other than
      'start_of_hand_position_results_tallies_shelf', update the shelf name inside the
      database shelf initialization block in `main()`.
    - Path isolation, stdout/stderr normalization, and exit code/diff checks are
      fully generic and will work for any pair of Python interpreters and scripts.

Note:
    Once full test automation is achieved (such as issue #37, which seeks 100%
    unit and acceptance test coverage across simulate_cribbage_games.py), this
    script may no longer be necessary as unit and integration tests will
    implicitly guarantee compatibility.
"""

import subprocess
import sys
import os
import difflib
import re
import tempfile
import shutil
import shelve

# Seeding prefix for simulate_cribbage_games.py to ensure deterministic outputs
SEED_PREFIX = (
    "import random; random.seed(12345); import sys; "
    "sys.argv = ['simulate_cribbage_games.py'] + {args}; "
    "import runpy; runpy.run_path({script_path}, run_name='__main__')"
)

# Test cases configured for regression verification.
# All temporary file outputs (like 'crib_temp.json') use relative paths to run inside
# isolated workspaces. No absolute paths to '/tmp' are needed.
TEST_CASES = [
    # 1. Base simulator run (one hand)
    {"type": "simulator", "args": []},
    # 2. Simulate play of 10 hands
    {"type": "simulator", "args": ["--game-count", "10", "--hide-play-actions"]},
    # 3. Simulate play of 5 games
    {
        "type": "simulator",
        "args": [
            "--game-count",
            "5",
            "--unlimited-hands-per-game",
            "--hide-play-actions",
        ],
    },
    # 4. Fixed dealt and kept cards for pone
    {
        "type": "simulator",
        "args": [
            "--first-pone-dealt-cards",
            "AC,2D,3H,4S,5C,6D",
            "--first-pone-kept-cards",
            "2D,3H,4S,5C",
            "--hide-first-pone-hands",
            "--hide-first-dealer-hands",
            "--hide-play-actions",
            "--game-count",
            "20",
        ],
    },
    # 5. Select each possible kept hand for pone
    {
        "type": "simulator",
        "args": [
            "--first-pone-dealt-cards",
            "AC,2D,3H,4S,5C,6D",
            "--first-pone-select-each-possible-kept-hand",
            "--hide-first-pone-hands",
            "--hide-first-dealer-hands",
            "--hide-play-actions",
            "--games-per-update",
            "5",
            "--game-count",
            "20",
        ],
    },
    # 6. Play from mid-play position
    {
        "type": "simulator",
        "args": [
            "--first-pone-kept-cards",
            "QD,TC,4D,AH",
            "--initial-play-actions",
            "4D,8H",
            "--select-each-post-initial-play",
            "--hide-first-pone-hands",
            "--hide-first-dealer-hands",
            "--hide-play-actions",
            "--game-count",
            "20",
            "--games-per-update",
            "5",
        ],
    },
    # 7. Dynamic simulation hand
    {
        "type": "simulator",
        "args": [
            "--process-count",
            "1",
            "--game-count",
            "1",
            "--first-pone-discard-based-on-simulations",
            "10",
            "--first-dealer-discard-based-on-simulations",
            "10",
        ],
    },
    # 8. Artifact pipeline: generate tiny table
    {
        "type": "pipeline",
        "cmd": [
            "artifact_pipeline/generate_table.py",
            "--samples",
            "5",
            "--seed",
            "42",
            "--output",
            "crib_temp.json",
            "--no-resume",
        ],
    },
    # 9. Artifact pipeline: summarize table
    {
        "type": "pipeline",
        "cmd": [
            "artifact_pipeline/summarize_table.py",
            "crib_temp.json",
            "--role",
            "Dealer",
        ],
    },
    # 10. Artifact pipeline: compare Hessel
    {
        "type": "pipeline",
        "cmd": [
            "artifact_pipeline/compare_hessel.py",
            "crib_temp.json",
            "--role",
            "Dealer",
            "--view",
            "table",
        ],
    },
]


def sanitize_output(output):
    """Normalize elapsed times/speeds to ensure deterministic diffing."""
    lines = []
    for line in output.splitlines():
        line = re.sub(
            r" at \S+ games/s \(\S+ ns/game\) in \S+ s",
            " at <SPEED> games/s (<TIME> ns/game) in <ELAPSED> s",
            line,
        )
        lines.append(line)
    return "\n".join(lines)


def run_cmd(python_bin, temp_dir, test_case):
    """Execute a single test case using the specified Python binary in an isolated workspace."""
    env = os.environ.copy()
    # Ensure import resolution checks the isolated temp directory first
    env["PYTHONPATH"] = temp_dir + os.pathsep + env.get("PYTHONPATH", "")

    if test_case["type"] == "simulator":
        # Run via python -c to inject random seed before executing main script
        script_path = os.path.join(temp_dir, "simulate_cribbage_games.py")
        code = SEED_PREFIX.format(
            script_path=repr(script_path), args=repr(test_case["args"])
        )
        cmd = [python_bin, "-c", code]
    else:
        # Run pipeline script directly with absolute path
        script_path = os.path.abspath(test_case["cmd"][0])
        cmd = [python_bin, script_path] + test_case["cmd"][1:]

    res = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=temp_dir,
        env=env,
        check=False,
    )
    return res.returncode, sanitize_output(res.stdout), sanitize_output(res.stderr)


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 verify_upgrade.py <old_python_bin> <new_python_bin>")
        sys.exit(1)

    python_old = os.path.abspath(shutil.which(sys.argv[1]) or sys.argv[1])
    python_new = os.path.abspath(shutil.which(sys.argv[2]) or sys.argv[2])

    print(f"Using Old Python binary: {python_old}")
    print(f"Using New Python binary: {python_new}")

    # Set up isolated scratch workspaces per interpreter to prevent shelf file issues
    # and warm/cold cache cross-contamination.
    temp_dir_old = tempfile.mkdtemp(prefix="verify_upgrade_old_")
    temp_dir_new = tempfile.mkdtemp(prefix="verify_upgrade_new_")

    try:
        # Copy legacy simulator file to isolated folders
        shutil.copy(
            "simulate_cribbage_games.py",
            os.path.join(temp_dir_old, "simulate_cribbage_games.py"),
        )
        shutil.copy(
            "simulate_cribbage_games.py",
            os.path.join(temp_dir_new, "simulate_cribbage_games.py"),
        )

        # Initialize empty shelves on current environment platforms
        for temp_dir in [temp_dir_old, temp_dir_new]:
            shelf_path = os.path.join(
                temp_dir, "start_of_hand_position_results_tallies_shelf"
            )
            with shelve.open(shelf_path, flag="c"):
                pass

        print(
            f"Starting Old vs New Python regression checks on {len(TEST_CASES)} cases..."
        )
        failed = False

        for idx, tc in enumerate(TEST_CASES, 1):
            print(
                f"Running Test Case {idx}/{len(TEST_CASES)}: {tc.get('args') or tc.get('cmd')} ... ",
                end="",
                flush=True,
            )

            code_old, out_old, err_old = run_cmd(python_old, temp_dir_old, tc)
            code_new, out_new, err_new = run_cmd(python_new, temp_dir_new, tc)

            if code_old != code_new:
                print("FAILED (Exit Code mismatch)")
                print(f"Old Python exit: {code_old}, New Python exit: {code_new}")
                print(f"Stderr Old:\n{err_old}")
                print(f"Stderr New:\n{err_new}")
                failed = True
                continue

            if code_old != 0:
                print(f"FAILED (Command failed under Old Python with code {code_old})")
                print(f"Stderr Old:\n{err_old}")
                failed = True
                continue

            # Diff stdout
            if out_old != out_new:
                print("FAILED (Stdout mismatch)")
                diff = difflib.unified_diff(
                    out_old.splitlines(keepends=True),
                    out_new.splitlines(keepends=True),
                    fromfile="old_python_stdout",
                    tofile="new_python_stdout",
                )
                sys.stdout.writelines(diff)
                failed = True
                continue

            # Diff stderr (ensures warnings/deprecation notices are caught)
            if err_old != err_new:
                print("FAILED (Stderr mismatch)")
                diff = difflib.unified_diff(
                    err_old.splitlines(keepends=True),
                    err_new.splitlines(keepends=True),
                    fromfile="old_python_stderr",
                    tofile="new_python_stderr",
                )
                sys.stdout.writelines(diff)
                failed = True
                continue

            # For generate_table.py case, diff actual file contents
            if tc.get("cmd") and "generate_table.py" in tc["cmd"][0]:
                file_old = os.path.join(temp_dir_old, "crib_temp.json")
                file_new = os.path.join(temp_dir_new, "crib_temp.json")
                if os.path.exists(file_old) and os.path.exists(file_new):
                    with open(file_old, "r") as f:
                        content_old = f.read()
                    with open(file_new, "r") as f:
                        content_new = f.read()
                    if content_old != content_new:
                        print("FAILED (Generated JSON mismatch)")
                        diff = difflib.unified_diff(
                            content_old.splitlines(keepends=True),
                            content_new.splitlines(keepends=True),
                            fromfile="crib_temp_old.json",
                            tofile="crib_temp_new.json",
                        )
                        sys.stdout.writelines(diff)
                        failed = True
                        continue

            print("PASSED")

    finally:
        # Clean up isolated workspaces (workspace-relative json files are cleaned up automatically here)
        shutil.rmtree(temp_dir_old, ignore_errors=True)
        shutil.rmtree(temp_dir_new, ignore_errors=True)

    if failed:
        print("\nRegression testing FAILED. There are output or behavior mismatches.")
        sys.exit(1)
    else:
        print("\nRegression testing PASSED. Output is 100% identical and compatible!")
        sys.exit(0)


if __name__ == "__main__":
    main()
