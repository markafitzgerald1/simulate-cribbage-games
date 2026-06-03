import os
from pathlib import Path
import sys
import time
import unittest
from typing import Iterable, List

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

os.environ["RUN_SLOW_ANALYTICAL_TESTS"] = "1"

TEST_PREFIX = "artifact_pipeline.test_generate_table.TestGenerateTable."

SLOW_TEST_GROUPS = {
    "hessel-compat": [
        TEST_PREFIX + "test_analytical_solver_hessel_compat",
    ],
    "support": [
        TEST_PREFIX + "test_analytical_solver_zero_weights_coverage",
        TEST_PREFIX + "test_analytical_solver_main",
        TEST_PREFIX + "test_dynamic_ibr_beats_hessel_paired",
    ],
    "historical-compat": [
        TEST_PREFIX + "test_dynamic_ibr_beats_historical_tables_paired",
    ],
}

SLOW_TESTS = [
    test_name for group_tests in SLOW_TEST_GROUPS.values() for test_name in group_tests
]


def _selected_tests(args: Iterable[str]) -> List[str]:
    selected: List[str] = []
    unknown: List[str] = []
    for arg in args:
        if arg in SLOW_TEST_GROUPS:
            selected.extend(SLOW_TEST_GROUPS[arg])
        elif arg in SLOW_TESTS:
            selected.append(arg)
        else:
            unknown.append(arg)
    if unknown:
        groups = ", ".join(sorted(SLOW_TEST_GROUPS))
        raise ValueError(f"Unknown slow test group/name: {unknown}. Groups: {groups}")
    return selected or SLOW_TESTS


class ProgressResult(unittest.TextTestResult):
    def startTest(self, test):
        self._test_started_at = time.monotonic()
        self.stream.writeln(f"[slow-start] {test.id()}")
        self.stream.flush()
        super().startTest(test)

    def addSuccess(self, test):
        elapsed = time.monotonic() - self._test_started_at
        self.stream.writeln(f"[slow-pass] {test.id()} ({elapsed:.1f}s)")
        self.stream.flush()
        super().addSuccess(test)


def main():
    suite = unittest.defaultTestLoader.loadTestsFromNames(_selected_tests(sys.argv[1:]))
    runner = unittest.TextTestRunner(verbosity=2, resultclass=ProgressResult)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
