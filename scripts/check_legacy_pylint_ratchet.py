"""Ratchet check for legacy simulator pylint notices.

Verifies that `simulate_cribbage_games.py` produces no pylint messages
beyond the committed baseline (comparing path, line, and symbol).
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = REPO_ROOT / "simulate_cribbage_games.py"
DEFAULT_BASELINE = REPO_ROOT / ".pylint-legacy-baseline.json"


def run_pylint(target_path: Path) -> list[dict[str, Any]]:
    """Run pylint with JSON output on the target file."""
    cmd = [
        sys.executable,
        "-m",
        "pylint",
        "--persistent=n",
        "--output-format=json",
        str(target_path.relative_to(REPO_ROOT)),
    ]
    result = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # Pylint exit code bitmask: 1 = fatal, 32 = usage error.
    if result.returncode & 33 != 0:
        sys.stderr.write(f"Error running pylint:\n{result.stderr}\n")
        sys.exit(2)

    try:
        raw_messages: list[dict[str, Any]] = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        sys.stderr.write(
            f"Failed to parse pylint JSON output: {exc}\n{result.stdout}\n"
        )
        sys.exit(2)

    normalized: list[dict[str, Any]] = []
    for msg in raw_messages:
        raw_path = msg.get("path", "")
        try:
            rel_path = str(Path(raw_path).resolve().relative_to(REPO_ROOT))
        except ValueError:
            rel_path = Path(raw_path).name

        normalized.append(
            {
                "path": rel_path,
                "line": int(msg.get("line", 0)),
                "column": int(msg.get("column", 0)),
                "symbol": str(msg.get("symbol", "")),
                "message-id": str(msg.get("message-id", "")),
                "message": str(msg.get("message", "")),
                "type": str(msg.get("type", "")),
                "obj": str(msg.get("obj", "")),
            }
        )

    # Sort deterministically
    normalized.sort(
        key=lambda item: (
            item["path"],
            item["line"],
            item["column"],
            item["symbol"],
            item["message"],
        )
    )
    return normalized


def load_baseline(baseline_path: Path) -> list[dict[str, Any]]:
    """Load baseline messages from the committed JSON file."""
    if not baseline_path.is_file():
        sys.stderr.write(
            f"Baseline file not found at {baseline_path}.\n"
            "Run with --refresh to create the baseline.\n"
        )
        sys.exit(2)
    with baseline_path.open("r", encoding="utf-8") as f:
        data: list[dict[str, Any]] = json.load(f)
    return data


def save_baseline(baseline_path: Path, messages: list[dict[str, Any]]) -> None:
    """Save normalized messages to baseline JSON file."""
    with baseline_path.open("w", encoding="utf-8") as f:
        json.dump(messages, f, indent=2)
        f.write("\n")


def check_ratchet(actual: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> int:
    """Compare actual messages against baseline by (path, line, symbol).

    Returns 0 if no unexpected messages exist, 1 otherwise.
    """
    baseline_counter = Counter(
        (item["path"], item["line"], item["symbol"]) for item in baseline
    )
    actual_counter = Counter(
        (item["path"], item["line"], item["symbol"]) for item in actual
    )

    unexpected: list[dict[str, Any]] = []
    seen_counts: Counter[tuple[str, int, str]] = Counter()
    for msg in actual:
        key = (msg["path"], msg["line"], msg["symbol"])
        seen_counts[key] += 1
        if seen_counts[key] > baseline_counter.get(key, 0):
            unexpected.append(msg)

    cleared_count = 0
    for key, count in baseline_counter.items():
        act_count = actual_counter.get(key, 0)
        if act_count < count:
            cleared_count += count - act_count

    if cleared_count > 0:
        print(
            f"INFO: {cleared_count} message(s) from baseline are no longer "
            "reported (notices resolved). Run with --refresh to ratchet down."
        )

    if unexpected:
        print(
            f"ERROR: Legacy pylint ratchet failed: found {len(unexpected)} "
            "unexpected message(s) beyond baseline:",
            file=sys.stderr,
        )
        for msg in unexpected:
            print(
                f"  {msg['path']}:{msg['line']}:{msg['column']}: "
                f"[{msg['symbol']}] ({msg['message-id']}) {msg['message']}",
                file=sys.stderr,
            )
        print(
            "\nNew pylint notices on simulate_cribbage_games.py are not permitted.\n"
            "If this change was caused by a deliberate tooling or dependency upgrade,\n"
            "update the baseline using: python scripts/check_legacy_pylint_ratchet.py --refresh\n"
            "and state the rationale in the pull request description.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Legacy pylint ratchet passed: {len(actual)} message(s) reported, "
        "matching baseline (no new messages)."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ratchet check for legacy simulator pylint notices."
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE,
        help="Path to baseline JSON file (default: %(default)s)",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
        help="Target file to check (default: %(default)s)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh the baseline file with current pylint output",
    )
    args = parser.parse_args()

    actual = run_pylint(args.target)

    if args.refresh:
        save_baseline(args.baseline, actual)
        print(
            f"Refreshed baseline at {args.baseline} with " f"{len(actual)} message(s)."
        )
        return 0

    baseline = load_baseline(args.baseline)
    return check_ratchet(actual, baseline)


if __name__ == "__main__":
    sys.exit(main())
