"""Unit tests for the legacy pylint ratchet checking logic."""

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.check_legacy_pylint_ratchet import (
    REPO_ROOT,
    check_ratchet,
    load_baseline,
    parse_measured_count,
    run_pylint,
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

    def test_parse_measured_count(self) -> None:
        """Test parse_measured_count extracts actual count or returns None."""
        self.assertEqual(parse_measured_count("Too many arguments (33/5)"), 33)
        self.assertEqual(parse_measured_count("Too few public methods (1/2)"), 1)
        self.assertEqual(parse_measured_count("Too many nested blocks (6/5)"), 6)
        self.assertIsNone(parse_measured_count("Invalid variable name"))
        self.assertIsNone(parse_measured_count('Unnecessary "else" after "return"'))

    def test_worsened_notice_fails(self) -> None:
        """Test a notice whose measured count rises above baseline fails."""
        baseline_msg = {
            "path": "simulate_cribbage_games.py",
            "line": 3590,
            "column": 0,
            "symbol": "too-many-arguments",
            "message-id": "R0913",
            "message": "Too many arguments (10/5)",
            "type": "refactor",
            "obj": "sample_fn",
        }
        worsened_msg = dict(baseline_msg)
        worsened_msg["message"] = "Too many arguments (11/5)"

        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = check_ratchet([worsened_msg], [baseline_msg])

        self.assertEqual(code, 1)
        err = buf_err.getvalue()
        self.assertTrue("found 1 unexpected message(s)" in err)
        self.assertTrue("count rose from 10 to 11" in err)
        self.assertTrue("[too-many-arguments]" in err)

    def test_improved_notice_passes_and_prints_info(self) -> None:
        """Test a notice whose measured count falls passes and prints INFO."""
        baseline_msg = {
            "path": "simulate_cribbage_games.py",
            "line": 3590,
            "column": 0,
            "symbol": "too-many-arguments",
            "message-id": "R0913",
            "message": "Too many arguments (10/5)",
            "type": "refactor",
            "obj": "sample_fn",
        }
        improved_msg = dict(baseline_msg)
        improved_msg["message"] = "Too many arguments (9/5)"

        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = check_ratchet([improved_msg], [baseline_msg])

        self.assertEqual(code, 0)
        out = buf_out.getvalue()
        self.assertTrue(
            "INFO: 1 notice(s) improved over baseline (measured count decreased)" in out
        )
        self.assertTrue("Legacy pylint ratchet passed" in out)
        self.assertEqual(buf_err.getvalue(), "")

    def test_multi_message_worsened_fails(self) -> None:
        """Test one worsened message among multiple on the same line fails."""
        baseline = [dict(self.sample_nested_block) for _ in range(4)]
        actual = [dict(self.sample_nested_block) for _ in range(3)]
        worsened = dict(self.sample_nested_block)
        worsened["message"] = "Too many nested blocks (7/5)"
        actual.append(worsened)

        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = check_ratchet(actual, baseline)

        self.assertEqual(code, 1)
        err = buf_err.getvalue()
        self.assertTrue("count rose from 6 to 7" in err)

    def test_multi_message_improved_passes(self) -> None:
        """Test one improved message among multiple on the same line passes."""
        baseline = [dict(self.sample_nested_block) for _ in range(4)]
        actual = [dict(self.sample_nested_block) for _ in range(3)]
        improved = dict(self.sample_nested_block)
        improved["message"] = "Too many nested blocks (5/5)"
        actual.append(improved)

        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = check_ratchet(actual, baseline)

        self.assertEqual(code, 0)
        out = buf_out.getvalue()
        self.assertTrue(
            "INFO: 1 notice(s) improved over baseline (measured count decreased)" in out
        )

    def test_relative_target_path_resolves_and_runs(self) -> None:
        """Test relative target path is resolved against REPO_ROOT before running."""
        mock_proc = MagicMock(returncode=0, stdout="[]", stderr="")
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            result = run_pylint(Path("simulate_cribbage_games.py"))

        self.assertEqual(result, [])
        mock_run.assert_called_once()
        cmd_called = mock_run.call_args[0][0]
        self.assertEqual(cmd_called[-1], "simulate_cribbage_games.py")
        self.assertEqual(mock_run.call_args[1]["cwd"], REPO_ROOT)

    def test_fatal_or_usage_exit_prints_both_stdout_and_stderr(self) -> None:
        """Test fatal or usage exits print both captured stdout and stderr."""
        # Test fatal error (code 1)
        mock_fatal = MagicMock(
            returncode=1,
            stdout='[{"type": "fatal", "message": "No module"}]',
            stderr="fatal stderr message",
        )
        buf_err = io.StringIO()
        with patch("subprocess.run", return_value=mock_fatal):
            with redirect_stderr(buf_err), self.assertRaises(SystemExit) as cm:
                run_pylint(Path("simulate_cribbage_games.py"))

        self.assertEqual(cm.exception.code, 2)
        err = buf_err.getvalue()
        self.assertTrue("Error running pylint (exit code 1):" in err)
        self.assertTrue('stdout:\n[{"type": "fatal", "message": "No module"}]' in err)
        self.assertTrue("stderr:\nfatal stderr message" in err)

        # Test usage error (code 32)
        mock_usage = MagicMock(
            returncode=32,
            stdout="usage stdout message",
            stderr="usage stderr message",
        )
        buf_err_usage = io.StringIO()
        with patch("subprocess.run", return_value=mock_usage):
            with redirect_stderr(buf_err_usage), self.assertRaises(SystemExit) as cm2:
                run_pylint(Path("simulate_cribbage_games.py"))

        self.assertEqual(cm2.exception.code, 2)
        err_usage = buf_err_usage.getvalue()
        self.assertTrue("Error running pylint (exit code 32):" in err_usage)
        self.assertTrue("stdout:\nusage stdout message" in err_usage)
        self.assertTrue("stderr:\nusage stderr message" in err_usage)


if __name__ == "__main__":
    unittest.main()
