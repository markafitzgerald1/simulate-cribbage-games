import os
from pathlib import Path
import sys
import time
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

os.environ["RUN_SLOW_ANALYTICAL_TESTS"] = "1"

SLOW_TESTS = [
    "artifact_pipeline.test_generate_table.TestGenerateTable."
    "test_analytical_solver_hessel_compat",
    "artifact_pipeline.test_generate_table.TestGenerateTable."
    "test_analytical_solver_zero_weights_coverage",
    "artifact_pipeline.test_generate_table.TestGenerateTable."
    "test_analytical_solver_main",
    "artifact_pipeline.test_generate_table.TestGenerateTable."
    "test_dynamic_ibr_beats_hessel_paired",
    "artifact_pipeline.test_generate_table.TestGenerateTable."
    "test_dynamic_ibr_beats_historical_tables_paired",
]


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
    suite = unittest.defaultTestLoader.loadTestsFromNames(SLOW_TESTS)
    runner = unittest.TextTestRunner(verbosity=2, resultclass=ProgressResult)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
