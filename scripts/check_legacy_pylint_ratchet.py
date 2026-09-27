"""Ratchet check for legacy simulator pylint notices.

Verifies that `simulate_cribbage_games.py` produces no pylint messages
beyond the committed baseline (comparing path, line, and symbol).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = REPO_ROOT / "simulate_cribbage_games.py"
DEFAULT_BASELINE = REPO_ROOT / ".pylint-legacy-baseline.json"
COUNT_PATTERN = re.compile(r"\(\s*(\d+)\s*/\s*\d+\s*\)")


def parse_measured_count(message: str) -> int | None:
    """Parse the actual measured count from an '(actual/limit)' message."""
    match = COUNT_PATTERN.search(message)
    if match:
        return int(match.group(1))
    return None


def run_pylint(target_path: Path) -> list[dict[str, Any]]:
    """Run pylint with JSON output on the target file."""
    if not target_path.is_absolute():
        resolved_target = (REPO_ROOT / target_path).resolve()
    else:
        resolved_target = target_path.resolve()

    try:
        rel_target = str(resolved_target.relative_to(REPO_ROOT))
    except ValueError:
        rel_target = str(resolved_target)

    cmd = [
        sys.executable,
        "-m",
        "pylint",
        "--persistent=n",
        "--output-format=json",
        rel_target,
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
        sys.stderr.write(
            f"Error running pylint (exit code {result.returncode}):\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}\n"
        )
        sys.exit(2)

    try:
        raw_messages: list[dict[str, Any]] = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        sys.stderr.write(
            f"Failed to parse pylint JSON output: {exc}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}\n"
        )
        sys.exit(2)

    normalized: list[dict[str, Any]] = []
    for msg in raw_messages:
        raw_path = msg.get("path", "")
        msg_path = Path(raw_path)
        if not msg_path.is_absolute():
            msg_path = (REPO_ROOT / msg_path).resolve()
        else:
            msg_path = msg_path.resolve()
        try:
            rel_path = str(msg_path.relative_to(REPO_ROOT))
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
    if not baseline_path.is_absolute():
        baseline_path = (REPO_ROOT / baseline_path).resolve()
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
    if not baseline_path.is_absolute():
        baseline_path = (REPO_ROOT / baseline_path).resolve()
    with baseline_path.open("w", encoding="utf-8") as f:
        json.dump(messages, f, indent=2)
        f.write("\n")


def _compare_count_messages(
    act_msgs: list[dict[str, Any]],
    base_msgs: list[dict[str, Any]],
    symbol: str,
) -> tuple[list[dict[str, Any]], int, int]:
    """Compare messages with '(actual/limit)' counts.

    Returns (unexpected, improved_decreased, improved_increased).
    """
    is_min = symbol.startswith("too-few-")
    act_pairs = [(parse_measured_count(m["message"]) or 0, m) for m in act_msgs]
    base_pairs = [(parse_measured_count(m["message"]) or 0, m) for m in base_msgs]
    act_pairs.sort(key=lambda p: p[0], reverse=not is_min)
    base_pairs.sort(key=lambda p: p[0], reverse=not is_min)

    unexpected: list[dict[str, Any]] = []
    imp_dec = 0
    imp_inc = 0
    common_len = min(len(act_pairs), len(base_pairs))
    for i in range(common_len):
        a_count, a_msg = act_pairs[i]
        b_count, _ = base_pairs[i]
        if is_min:
            if a_count < b_count:
                unexpected.append(
                    dict(a_msg, detail=f"count fell from {b_count} to {a_count}")
                )
            elif a_count > b_count:
                imp_inc += 1
        else:
            if a_count > b_count:
                unexpected.append(
                    dict(a_msg, detail=f"count rose from {b_count} to {a_count}")
                )
            elif a_count < b_count:
                imp_dec += 1

    if len(act_pairs) > len(base_pairs):
        for _, a_msg in act_pairs[len(base_pairs) :]:
            unexpected.append(
                dict(
                    a_msg,
                    detail=(
                        f"duplicate notice beyond baseline count of "
                        f"{len(base_pairs)}"
                    ),
                )
            )
    return unexpected, imp_dec, imp_inc


def _compare_key_messages(
    act_msgs: list[dict[str, Any]], base_msgs: list[dict[str, Any]] | None
) -> tuple[list[dict[str, Any]], int, int]:
    """Compare actual messages for a single key against baseline."""
    if base_msgs is None:
        return list(act_msgs), 0, 0

    has_counts = any(
        parse_measured_count(m["message"]) is not None for m in base_msgs
    ) or any(parse_measured_count(m["message"]) is not None for m in act_msgs)

    if not has_counts:
        if len(act_msgs) > len(base_msgs):
            return list(act_msgs[len(base_msgs) :]), 0, 0
        return [], 0, 0

    symbol = act_msgs[0]["symbol"] if act_msgs else base_msgs[0]["symbol"]
    return _compare_count_messages(act_msgs, base_msgs, symbol)


def _report_failure(unexpected: list[dict[str, Any]]) -> int:
    """Print error diagnostics for unexpected messages and return 1."""
    print(
        f"ERROR: Legacy pylint ratchet failed: found {len(unexpected)} "
        "unexpected message(s) beyond baseline:",
        file=sys.stderr,
    )
    for msg in unexpected:
        detail = f" ({msg['detail']})" if "detail" in msg else ""
        print(
            f"  {msg['path']}:{msg['line']}:{msg['column']}: "
            f"[{msg['symbol']}] ({msg['message-id']}) {msg['message']}{detail}",
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


def check_ratchet(actual: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> int:
    """Compare actual messages against baseline.

    Keys by (path, line, symbol). For messages with '(actual/limit)' counts,
    fails if the measured count worsens relative to the baseline (rises for
    maximum checks, falls for 'too-few-*' minimum checks). A count
    improvement or resolved notice prints an informational notice.
    """
    baseline_by_key: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
    for item in baseline:
        key = (item["path"], item["line"], item["symbol"])
        baseline_by_key.setdefault(key, []).append(item)

    actual_by_key: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
    for item in actual:
        key = (item["path"], item["line"], item["symbol"])
        actual_by_key.setdefault(key, []).append(item)

    unexpected: list[dict[str, Any]] = []
    improved_decreased = 0
    improved_increased = 0

    for key, act_msgs in actual_by_key.items():
        unexpected_for_key, imp_dec, imp_inc = _compare_key_messages(
            act_msgs, baseline_by_key.get(key)
        )
        unexpected.extend(unexpected_for_key)
        improved_decreased += imp_dec
        improved_increased += imp_inc

    cleared_count = sum(
        len(base_msgs) - len(actual_by_key.get(key, []))
        for key, base_msgs in baseline_by_key.items()
        if len(actual_by_key.get(key, [])) < len(base_msgs)
    )

    if cleared_count > 0:
        print(
            f"INFO: {cleared_count} message(s) from baseline are no longer "
            "reported (notices resolved). Run with --refresh to ratchet down."
        )

    if improved_decreased > 0:
        print(
            f"INFO: {improved_decreased} notice(s) improved over baseline "
            "(measured count decreased). Run with --refresh to ratchet down."
        )

    if improved_increased > 0:
        print(
            f"INFO: {improved_increased} notice(s) improved over baseline "
            "(measured count increased). Run with --refresh to ratchet down."
        )

    if unexpected:
        return _report_failure(unexpected)

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
