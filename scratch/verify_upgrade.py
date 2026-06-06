import subprocess
import sys
import os
import difflib

# Seeding prefix for simulate_cribbage_games.py to ensure deterministic outputs
SEED_PREFIX = "import random; random.seed(12345); import sys; sys.argv = ['simulate_cribbage_games.py'] + {args}; import simulate_cribbage_games"

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
            "/tmp/crib_temp.json",
            "--no-resume",
        ],
    },
    # 9. Artifact pipeline: summarize table
    {
        "type": "pipeline",
        "cmd": [
            "artifact_pipeline/summarize_table.py",
            "/tmp/crib_temp.json",
            "--role",
            "Dealer",
        ],
    },
    # 10. Artifact pipeline: compare Hessel
    {
        "type": "pipeline",
        "cmd": [
            "artifact_pipeline/compare_hessel.py",
            "/tmp/crib_temp.json",
            "--role",
            "Dealer",
            "--view",
            "table",
        ],
    },
]


def run_cmd(python_bin, test_case):
    if test_case["type"] == "simulator":
        # Run via python -c to inject random seed before importing/executing main script
        code = SEED_PREFIX.format(args=repr(test_case["args"]))
        cmd = [python_bin, "-c", code]
    else:
        # Run pipeline script directly
        cmd = [python_bin] + test_case["cmd"]

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return res.returncode, res.stdout, res.stderr


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 verify_upgrade.py <python_3.9_bin> <python_3.14_bin>")
        sys.exit(1)

    python_39 = sys.argv[1]
    python_314 = sys.argv[2]

    print(f"Using Python 3.9 binary: {python_39}")
    print(f"Using Python 3.14 binary: {python_314}")
    print(
        f"Starting Python 3.9 vs 3.14 regression checks on {len(TEST_CASES)} cases..."
    )
    failed = False

    for idx, tc in enumerate(TEST_CASES, 1):
        print(
            f"Running Test Case {idx}/{len(TEST_CASES)}: {tc.get('args') or tc.get('cmd')} ... ",
            end="",
            flush=True,
        )

        code_39, out_39, err_39 = run_cmd(python_39, tc)
        code_314, out_314, err_314 = run_cmd(python_314, tc)

        # Standardize temporary file path differences in output if any
        out_39 = out_39.replace("/tmp/crib_temp.json", "crib_temp.json")
        out_314 = out_314.replace("/tmp/crib_temp.json", "crib_temp.json")
        err_39 = err_39.replace("/tmp/crib_temp.json", "crib_temp.json")
        err_314 = err_314.replace("/tmp/crib_temp.json", "crib_temp.json")

        if code_39 != code_314:
            print("FAILED (Exit Code mismatch)")
            print(f"Python 3.9 exit: {code_39}, Python 3.14 exit: {code_314}")
            print(f"Stderr 3.9:\n{err_39}")
            print(f"Stderr 3.14:\n{err_314}")
            failed = True
            continue

        if code_39 != 0:
            print(f"FAILED (Command failed under 3.9 with code {code_39})")
            print(f"Stderr 3.9:\n{err_39}")
            failed = True
            continue

        # Diff stdout
        if out_39 != out_314:
            print("FAILED (Stdout mismatch)")
            diff = difflib.unified_diff(
                out_39.splitlines(keepends=True),
                out_314.splitlines(keepends=True),
                fromfile="python_39_stdout",
                tofile="python_314_stdout",
            )
            sys.stdout.writelines(diff)
            failed = True
            continue

        print("PASSED")

    # Clean up temp file
    if os.path.exists("/tmp/crib_temp.json"):
        os.remove("/tmp/crib_temp.json")

    if failed:
        print("\nRegression testing FAILED. There are output or behavior mismatches.")
        sys.exit(1)
    else:
        print("\nRegression testing PASSED. Output is 100% identical and compatible!")
        sys.exit(0)


if __name__ == "__main__":
    main()
