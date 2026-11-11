"""The committed golden pegging file is what the Python engine writes."""

from pathlib import Path
import tempfile
import unittest

from artifact_pipeline import pegging_golden


class PeggingGoldenTest(unittest.TestCase):
    def test_committed_file_matches_the_python_engine(self) -> None:
        # Catches a Python rules change that would leave the Rust check
        # comparing against stale scores.
        with tempfile.TemporaryDirectory() as folder:
            written = Path(folder) / "golden.txt"
            pegging_golden.main(["--output", str(written)])
            self.assertEqual(
                written.read_text(encoding="utf-8"),
                pegging_golden.GOLDEN.read_text(encoding="utf-8"),
            )

    def test_every_line_is_a_feasible_scored_deal(self) -> None:
        lines = pegging_golden.GOLDEN.read_text(encoding="utf-8").splitlines()
        self.assertGreater(len(lines), 5000)
        scored = 0
        for line in lines:
            pone, dealer, pone_points, dealer_points = map(int, line.split(" "))
            self.assertEqual(pone % pegging_golden.PONE_STEP, 0)
            self.assertEqual(dealer % pegging_golden.DEALER_STEP, 0)
            scored += pone_points + dealer_points > 0
        self.assertGreater(scored, len(lines) // 2)


if __name__ == "__main__":
    unittest.main()
