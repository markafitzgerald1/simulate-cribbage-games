"""Unit tests for the legacy pylint ratchet checking logic."""

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

from scripts.check_legacy_pylint_ratchet import (
    check_ratchet,
    load_baseline,
    save_baseline,
)


class TestCheckLegacyPylintRatchet(unittest.TestCase):
    """Test suite for legacy pylint ratchet check and baseline persistence."""

    def setUp(self) -> None:
        self.sample_msg_1 = {
            "path": "simulate_cribbage_games.py",
            "line": 46,
            "column": 0,
            "symbol": "too-few-public-methods",
            "message-id": "R0903",
            "message": "Too few public methods (1/2)",
            "type": "refactor",
            "obj": "GameScoreResultsTally",
        }
        self.sample_msg_2 = {
            "path": "simulate_cribbage_games.py",
            "line": 159,
            "column": 0,
            "symbol": "too-few-public-methods",
            "message-id": "R0903",
            "message": "Too few public methods (1/2)",
            "type": "refactor",
            "obj": "HandHistory",
        }
        self.sample_nested_block = {
            "path": "simulate_cribbage_games.py",
            "line": 721,
            "column": 4,
            "symbol": "too-many-nested-blocks",
            "message-id": "R1702",
            "message": "Too many nested blocks (6/5)",
            "type": "refactor",
            "obj": "play_hand",
        }

    def test_identical_sets_pass(self) -> None:
        """Case 1: Identical actual and baseline sets pass with exit code 0."""
        baseline = [self.sample_msg_1, self.sample_msg_2]
        actual = [self.sample_msg_1, self.sample_msg_2]

        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = check_ratchet(actual, baseline)

        self.assertEqual(code, 0)
        self.assertTrue("Legacy pylint ratchet passed" in buf_out.getvalue())
        self.assertEqual(buf_err.getvalue(), "")

    def test_new_symbol_on_baseline_line_fails(self) -> None:
        """Case 2: A new symbol reported on an existing baseline line fails."""
        baseline = [self.sample_msg_1]
        new_symbol_msg = dict(self.sample_msg_1)
        new_symbol_msg["symbol"] = "invalid-name"
        new_symbol_msg["message-id"] = "C0103"
        new_symbol_msg["message"] = "Invalid variable name"
        actual = [new_symbol_msg]

        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = check_ratchet(actual, baseline)

        self.assertEqual(code, 1)
        self.assertTrue("unexpected message(s) beyond baseline" in buf_err.getvalue())
        self.assertTrue("[invalid-name]" in buf_err.getvalue())

    def test_duplicate_baseline_key_fails(self) -> None:
        """Case 3: A second copy of a baseline key fails (frequency check)."""
        baseline = [self.sample_nested_block]
        actual = [self.sample_nested_block, self.sample_nested_block]

        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = check_ratchet(actual, baseline)

        self.assertEqual(code, 1)
        self.assertTrue("found 1 unexpected message(s)" in buf_err.getvalue())
        self.assertTrue("721:4: [too-many-nested-blocks]" in buf_err.getvalue())

    def test_message_on_new_line_fails(self) -> None:
        """Case 4: A message reported on a new line fails."""
        baseline = [self.sample_msg_1]
        new_line_msg = dict(self.sample_msg_1)
        new_line_msg["line"] = 999
        actual = [self.sample_msg_1, new_line_msg]

        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = check_ratchet(actual, baseline)

        self.assertEqual(code, 1)
        self.assertTrue("simulate_cribbage_games.py:999:0" in buf_err.getvalue())

    def test_cleared_notice_passes_and_prints_info(self) -> None:
        """Case 5: A cleared notice passes and prints an informational notice."""
        baseline = [self.sample_msg_1, self.sample_msg_2]
        actual = [self.sample_msg_1]

        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = check_ratchet(actual, baseline)

        self.assertEqual(code, 0)
        stdout_content = buf_out.getvalue()
        self.assertTrue(
            "INFO: 1 message(s) from baseline are no longer reported" in stdout_content
        )
        self.assertTrue("Run with --refresh to ratchet down" in stdout_content)
        self.assertTrue("Legacy pylint ratchet passed" in stdout_content)
        self.assertEqual(buf_err.getvalue(), "")

    def test_baseline_save_load_round_trip(self) -> None:
        """Test save_baseline and load_baseline JSON persistence round-trip."""
        messages = [self.sample_msg_1, self.sample_nested_block]
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "test_baseline.json"
            save_baseline(file_path, messages)
            self.assertTrue(file_path.is_file())

            loaded = load_baseline(file_path)
            self.assertEqual(loaded, messages)

    def test_load_baseline_missing_file_exits(self) -> None:
        """Test load_baseline exits cleanly with status 2 if file is missing."""
        missing_path = Path("/nonexistent/baseline/path.json")
        buf_err = io.StringIO()
        with redirect_stderr(buf_err), self.assertRaises(SystemExit) as cm:
            load_baseline(missing_path)
        self.assertEqual(cm.exception.code, 2)
        self.assertTrue("Baseline file not found" in buf_err.getvalue())


if __name__ == "__main__":
    unittest.main()
