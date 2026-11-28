# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Golden regression suite and generator for ``simulate_cribbage_games.py``.

Each case executes ``simulate_cribbage_games.py`` in a fresh temporary working
directory with an empty tally shelf, ``PYTHONHASHSEED=0``, and a fixed
``random.seed(12345)`` wrapper matching ``scratch/verify_upgrade.py``.

These golden files record what the legacy simulator does now, not what it should
do. They exist to catch unintended changes, and they are not evidence that
the recorded behavior is correct. Correctness belongs in unit tests that
assert the rules. A golden that changes because a bug was fixed is
regenerated, and its diff is reviewed. Comparison is exact after normalizing
timing figures in the simulator's performance lines and trailing newlines.

Known recorded defects:

- #267: in the second, fourth and later hands (where the players have swapped
  roles), simulation-based play, simulation-based discard and the
  play coach pass the nested simulation the scores in the game's original
  seat order instead of the current hand's pone-dealer order. Cases B, C and
  E reach an odd hand and record this.
- #268: the dynamic play coach starts from the live score and then replays
  the starter and earlier pegging. Case E records the double-counting.

README smoke-test coverage. Case names carry the README line number each
command had when the suite was written (2026-11-26):
- Commands with ``--process-count 2`` (readme_533, readme_547b) run with one
  process, because spawned workers under ``runpy.run_path`` hang on macOS and
  cannot share the parent's random seed deterministically. Their golden files
  match the default-worker cases readme_532 and readme_547a and say nothing
  about multi-process behavior. Commands with ``--infinite-game-count`` run a
  small finite count.
- Not covered: the multi-hand command combining dynamic discard, dynamic play
  and incomplete-game estimates (about 11.5 s even at minimal counts; cases B
  and C exercise dynamic play and discard separately, without estimates), and
  the two interactive play-against commands. Case E covers the interactive
  play coach instead: first pone's plays come from a scripted card cycle, and
  the game reaches an odd hand near 121.
"""

from __future__ import annotations

import argparse
import difflib
import os
from pathlib import Path
import re
import shelve
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent
SIMULATOR_SCRIPT = REPO_ROOT / "simulate_cribbage_games.py"
GOLDEN_DIR = REPO_ROOT / "tests" / "golden" / "legacy"
TALLY_SHELF_NAME = "start_of_hand_position_results_tallies_shelf"
CASE_TIMEOUT_SECONDS = 120
PERFORMANCE_LINE = re.compile(
    r"^(Simulated [0-9]+ games(?: with [0-9]+ worker processes)? at )"
    r"-?[0-9]+\.[0-9]{3} games/s \(-?[0-9]+ ns/game\) in "
    r"-?[0-9]+(?:\.[0-9]+)?(?:e[+-][0-9]+)? s$",
    re.MULTILINE,
)

SEED_PREFIX = (
    "import random; random.seed(12345); import sys; "
    "sys.argv = ['simulate_cribbage_games.py'] + {args}; "
    "import runpy; runpy.run_path({script_path}, run_name='__main__')"
)

GOLDEN_CASES: dict[str, list[str]] = {
    "readme_526_basic_hands": ["--game-count", "10"],
    "readme_527_basic_games": ["--game-count", "10", "--unlimited-hands-per-game"],
    "readme_528_summary_hands": [
        "--game-count",
        "50",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
    ],
    "readme_529_summary_games": [
        "--game-count",
        "20",
        "--games-per-update",
        "10",
        "--unlimited-hands-per-game",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
    ],
    "readme_530_random_pone": [
        "--game-count",
        "20",
        "--games-per-update",
        "10",
        "--unlimited-hands-per-game",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--first-pone-keep-random",
        "--first-pone-play-random",
    ],
    "readme_531_random_dealer": [
        "--game-count",
        "20",
        "--games-per-update",
        "10",
        "--unlimited-hands-per-game",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--first-dealer-keep-random",
        "--first-dealer-play-random",
    ],
    "readme_532_fixed_pone": [
        "--first-pone-dealt-cards",
        "AC,2D,3H,4S,5C,6D",
        "--first-pone-kept-cards",
        "2D,3H,4S,5C",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--game-count",
        "50",
    ],
    "readme_533_fixed_pone_single_process": [
        "--first-pone-dealt-cards",
        "AC,2D,3H,4S,5C,6D",
        "--first-pone-kept-cards",
        "2D,3H,4S,5C",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--game-count",
        "50",
        "--process-count",
        "1",
    ],
    "readme_534_fixed_dealer": [
        "--first-dealer-dealt-cards",
        "AC,2D,3H,4S,5C,6D",
        "--first-dealer-kept-cards",
        "AC,2D,3H,4S",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--game-count",
        "50",
    ],
    "readme_535_all_pone_keeps": [
        "--first-pone-dealt-cards",
        "AC,2D,3H,4S,5C,6D",
        "--first-pone-select-each-possible-kept-hand",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--games-per-update",
        "30",
        "--game-count",
        "30",
    ],
    "readme_536_all_dealer_keeps": [
        "--first-dealer-dealt-cards",
        "AC,2D,3H,4S,5C,6D",
        "--first-dealer-select-each-possible-kept-hand",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--games-per-update",
        "30",
        "--game-count",
        "30",
    ],
    "readme_537_dealer_keeps_late_score": [
        "--first-dealer-dealt-cards",
        "JH,TS,6S,6C,4C,AD",
        "--first-dealer-select-each-possible-kept-hand",
        "--initial-pone-score",
        "105",
        "--initial-dealer-score",
        "117",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--game-count",
        "30",
        "--games-per-update",
        "30",
    ],
    "readme_538_pone_leads_known_starter": [
        "--first-pone-dealt-cards",
        "JH,TS,6S,6C,4C,AD",
        "--first-pone-kept-cards",
        "TS,6S,4C,AD",
        "--initial-starter",
        "2S",
        "--select-each-post-initial-play",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--game-count",
        "40",
        "--games-per-update",
        "20",
    ],
    "readme_539_pone_leads_fixed_dealt": [
        "--first-pone-dealt-cards",
        "JH,TS,6S,6C,4C,AD",
        "--first-pone-kept-cards",
        "TS,6S,4C,AD",
        "--select-each-post-initial-play",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--game-count",
        "40",
        "--games-per-update",
        "20",
    ],
    "readme_540a_pone_leads_kept_only": [
        "--first-pone-kept-cards",
        "TS,6S,4C,AD",
        "--select-each-post-initial-play",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--game-count",
        "40",
        "--games-per-update",
        "20",
    ],
    "readme_540b_pone_leads_run_hand": [
        "--first-pone-kept-cards",
        "6c,7d,8h,9s",
        "--select-each-post-initial-play",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--game-count",
        "40",
        "--games-per-update",
        "20",
    ],
    "readme_541_pone_leads_partial_kept": [
        "--first-pone-kept-cards",
        "4C,AD",
        "--select-each-post-initial-play",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--game-count",
        "40",
        "--games-per-update",
        "20",
    ],
    "readme_542_pone_mid_play_known_discard": [
        "--first-pone-dealt-cards",
        "KC,QD,TC,8S,4D,AH",
        "--first-pone-kept-cards",
        "QD,TC,4D,AH",
        "--initial-play-actions",
        "4D,8H",
        "--select-each-post-initial-play",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--game-count",
        "30",
        "--games-per-update",
        "15",
    ],
    "readme_543_pone_mid_play_unknown_discard": [
        "--first-pone-kept-cards",
        "QD,TC,4D,AH",
        "--initial-play-actions",
        "4D,8H",
        "--select-each-post-initial-play",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--game-count",
        "30",
        "--games-per-update",
        "15",
    ],
    "readme_544_pone_mid_play_late_game": [
        "--first-pone-kept-cards",
        "6s,6h,7c,ks",
        "--select-each-post-initial-play",
        "--game-count",
        "30",
        "--games-per-update",
        "15",
        "--unlimited-hands-per-game",
        "--initial-pone-score",
        "106",
        "--initial-dealer-score",
        "106",
        "--initial-play-actions",
        "6s,ts",
        "--hide-play-actions",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
    ],
    "readme_545_dealer_mid_play_known_discard": [
        "--first-dealer-dealt-cards",
        "8C,4D,TH,9S,KC,KD",
        "--first-dealer-kept-cards",
        "8C,4D,TH,9S",
        "--initial-play-actions",
        "4C",
        "--select-each-post-initial-play",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--game-count",
        "40",
        "--games-per-update",
        "20",
    ],
    "readme_546_dealer_mid_play_unknown_discard": [
        "--first-dealer-kept-cards",
        "8C,4D,TH,9S",
        "--initial-play-actions",
        "4C",
        "--select-each-post-initial-play",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--game-count",
        "40",
        "--games-per-update",
        "20",
    ],
    "readme_547a_pone_non_default_initial_play": [
        "--first-pone-dealt-cards",
        "2s,4h,9s,9c,7c,qh",
        "--first-pone-kept-cards",
        "2s,4h,9s,9c",
        "--initial-play-actions",
        "9c,qs",
        "--select-each-post-initial-play",
        "--game-count",
        "30",
        "--games-per-update",
        "15",
        "--hide-play-actions",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
    ],
    "readme_547b_pone_non_default_single_process": [
        "--first-pone-dealt-cards",
        "2s,4h,9s,9c,7c,qh",
        "--first-pone-kept-cards",
        "2s,4h,9s,9c",
        "--initial-play-actions",
        "9c,qs",
        "--select-each-post-initial-play",
        "--game-count",
        "30",
        "--games-per-update",
        "15",
        "--hide-play-actions",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--process-count",
        "1",
    ],
    "readme_548_dealer_non_default_discard": [
        "--first-dealer-dealt-cards",
        "2d,3h,6h,8d,9d,qc",
        "--first-dealer-kept-cards",
        "2d,3h,8d,qc",
        "--initial-play-actions",
        "4c,8d,kd",
        "--select-each-post-initial-play",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--game-count",
        "30",
        "--games-per-update",
        "15",
    ],
    "readme_549_dealer_second_sequence_go": [
        "--first-dealer-kept-cards",
        "tc,3s,8c,9h",
        "--initial-play-actions",
        "th,tc,td,go,ac,go,go",
        "--select-each-post-initial-play",
        "--game-count",
        "40",
        "--games-per-update",
        "20",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
    ],
    "readme_550_dealer_keeps_third_leg_game": [
        "--first-dealer-dealt-cards",
        "AC,2S,6C,TD,JD,KC",
        "--first-dealer-select-each-possible-kept-hand",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--unlimited-hands-per-game",
        "--game-count",
        "30",
        "--initial-pone-score",
        "87",
        "--initial-dealer-score",
        "85",
        "--games-per-update",
        "30",
    ],
    "readme_551_single_hand_sim_discard": [
        "--process-count",
        "1",
        "--game-count",
        "1",
        "--first-pone-discard-based-on-simulations",
        "20",
        "--first-dealer-discard-based-on-simulations",
        "20",
    ],
    "readme_552_single_hand_sim_discard_and_play": [
        "--process-count",
        "1",
        "--game-count",
        "1",
        "--first-pone-discard-based-on-simulations",
        "10",
        "--first-dealer-discard-based-on-simulations",
        "10",
        "--first-pone-play-based-on-simulations",
        "20",
        "--first-dealer-play-based-on-simulations",
        "20",
    ],
    "case_a_known_issue_2023_02_12": [
        "--first-dealer-dealt-cards",
        "9♦,T♠,7♦,5♥,J♥,A♥",
        "--first-dealer-kept-cards",
        "T♠,5♥,J♥,A♥",
        "--initial-play-actions",
        "K♥",
        "--select-each-post-initial-play",
        "--hide-first-pone-hands",
        "--hide-first-dealer-hands",
        "--hide-play-actions",
        "--game-count",
        "40",
        "--games-per-update",
        "20",
        "--initial-pone-score",
        "118",
        "--initial-dealer-score",
        "119",
    ],
    "case_b_multi_hand_sim_play": [
        "--process-count",
        "1",
        "--game-count",
        "2",
        "--unlimited-hands-per-game",
        "--first-pone-play-based-on-simulations",
        "30",
        "--first-dealer-play-based-on-simulations",
        "30",
    ],
    "case_c_multi_hand_sim_discard": [
        "--process-count",
        "1",
        "--game-count",
        "2",
        "--unlimited-hands-per-game",
        "--first-pone-discard-based-on-simulations",
        "10",
        "--first-dealer-discard-based-on-simulations",
        "10",
    ],
    "case_d_single_hand_sim_play": [
        "--process-count",
        "1",
        "--game-count",
        "1",
        "--first-pone-play-based-on-simulations",
        "30",
        "--first-dealer-play-based-on-simulations",
        "30",
    ],
    "case_d_single_hand_sim_discard": [
        "--process-count",
        "1",
        "--game-count",
        "1",
        "--first-pone-discard-based-on-simulations",
        "10",
        "--first-dealer-discard-based-on-simulations",
        "10",
    ],
    "case_e_multi_hand_coach_play": [
        "--process-count",
        "1",
        "--game-count",
        "1",
        "--unlimited-hands-per-game",
        "--first-pone-play-user-entered",
        "--coach-play-simulated-hand-count",
        "10",
        "--initial-pone-score",
        "100",
        "--initial-dealer-score",
        "100",
    ],
}

# Scripted stdin for interactive cases. The simulator re-prompts until it reads
# a playable card, so cycling through every card plays the first legal card in
# this order and keeps the run deterministic.
CARD_CYCLE_INPUT = (
    "\n".join(
        [rank + suit for rank in "A23456789TJQK" for suit in ("C", "D", "H", "S")] * 400
    )
    + "\n"
)
GOLDEN_STDIN: dict[str, str] = {
    "case_e_multi_hand_coach_play": CARD_CYCLE_INPUT,
}


def sanitize_output(output: str) -> str:
    """Normalize timing fields in complete simulator performance lines."""
    return PERFORMANCE_LINE.sub(
        r"\g<1><SPEED> games/s (<TIME> ns/game) in <ELAPSED> s", output
    )


def format_golden_record(returncode: int, stdout: str, stderr: str) -> str:
    """Format exit code, normalized stdout, and normalized stderr for comparison."""
    return (
        f"EXIT_CODE: {returncode}\n"
        "--- STDOUT ---\n"
        f"{sanitize_output(stdout).removesuffix('\n')}\n"
        "--- STDERR ---\n"
        f"{sanitize_output(stderr).removesuffix('\n')}\n"
        "--- END ---\n"
    )


def run_simulator_case(case_name: str) -> tuple[int, str]:
    """Run ``simulate_cribbage_games.py`` in an isolated seeded temp directory."""
    return run_seeded_simulator(GOLDEN_CASES[case_name], GOLDEN_STDIN.get(case_name))


def run_seeded_simulator(
    args: list[str], scripted_input: str | None = None
) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="legacy_golden_") as temp_dir:
        shelf_path = os.path.join(temp_dir, TALLY_SHELF_NAME)
        with shelve.open(shelf_path, flag="c"):
            pass

        env = os.environ.copy()
        env["PYTHONHASHSEED"] = "0"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        code = SEED_PREFIX.format(
            script_path=repr(str(SIMULATOR_SCRIPT)), args=repr(args)
        )
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=temp_dir,
                env=env,
                encoding="utf-8",
                input=scripted_input,
                stdin=subprocess.DEVNULL if scripted_input is None else None,
                capture_output=True,
                check=False,
                timeout=CASE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise AssertionError(
                f"Simulator run timed out after {CASE_TIMEOUT_SECONDS} s: {args}"
            ) from None
        return (
            result.returncode,
            format_golden_record(result.returncode, result.stdout, result.stderr),
        )


class TestPlayRolloutScores(unittest.TestCase):
    def test_dealer_takes_immediate_win_after_heels(self) -> None:
        returncode, output = run_seeded_simulator(
            [
                "--game-count",
                "1",
                "--initial-pone-score",
                "119",
                "--initial-dealer-score",
                "117",
                "--initial-starter",
                "JC",
                "--first-dealer-kept-cards",
                "TS,5H,9H,AH",
                "--initial-play-actions",
                "KH",
                "--first-dealer-play-based-on-simulations",
                "10",
            ]
        )
        self.assertEqual(returncode, 0, output)
        self.assertRegex(output, r"His heels/nibs for 2 for Dealer \[119-119\]")
        self.assertRegex(output, r"5♥ first play:.*-4\.000 ±\s+0\.000 Δ-peg")
        self.assertRegex(output, r"Dealer plays 5♥ for 15\b")
        self.assertRegex(output, r"!15 for 2 points for Dealer\. \[119-121\]")

    def test_dealer_reaches_candidate_after_scoring_prefix(self) -> None:
        returncode, output = run_seeded_simulator(
            [
                "--game-count",
                "1",
                "--initial-pone-score",
                "113",
                "--initial-dealer-score",
                "117",
                "--initial-starter",
                "QC",
                "--first-pone-kept-cards",
                "7C,8C,2S,3H",
                "--first-dealer-kept-cards",
                "8D,8H,AH,5H",
                "--initial-play-actions",
                "7C",
                "--first-dealer-play-based-on-simulations",
                "10",
            ]
        )
        self.assertEqual(returncode, 0, output)
        self.assertRegex(output, r"!15 for 2 points for Dealer\. \[113-119\]")
        self.assertRegex(output, r"!Pair for 2 points for Pone\. \[115-119\]")
        # Replaying the fifteen from 119 ends every nested game before the
        # candidate, so even the ace would report a guaranteed dealer win.
        self.assertRegex(
            output,
            r"!Pair for 2 points for Pone\. \[115-119\]\n"
            r"Simulating each of the 3 possible dealer plays[^\n]*\n"
            r"8♦ first play:[^\n]*\nA♥ first play:\s+\+",
        )
        self.assertRegex(output, r"Dealer plays 8♦ for 31\b")
        self.assertRegex(output, r"for 6 points for Dealer\. \[115-121\]")


def assert_case_matches_golden(test_case: unittest.TestCase, case_name: str) -> None:
    """Assert that running ``case_name`` matches its committed golden file."""
    golden_path = GOLDEN_DIR / f"{case_name}.txt"
    test_case.assertTrue(golden_path.is_file(), f"Missing golden file: {golden_path}")
    _, actual = run_simulator_case(case_name)
    expected = golden_path.read_text(encoding="utf-8")
    if actual != expected:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(True),
                actual.splitlines(True),
                str(golden_path),
                f"actual:{case_name}",
            )
        )
        test_case.fail(f"Golden output mismatch for {case_name}:\n{diff}")


class TestPositionTallies(unittest.TestCase):
    def test_dealer_discard_rollouts_do_not_tally(self) -> None:
        from simulate_cribbage_games import GameScoreResultsTallies

        args = [
            "--first-dealer-discard-based-on-simulations",
            "1",
            "--tally-start-of-hand-position-results",
            "--unlimited-hands-per-game",
            "--game-count",
            "1",
        ]
        code = SEED_PREFIX.format(script_path=repr(str(SIMULATOR_SCRIPT)), args=args)
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=temp_dir,
                env={**os.environ, "PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8"},
                encoding="utf-8",
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
                timeout=CASE_TIMEOUT_SECONDS,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertRegex(result.stdout, "in order to select discard")
            # Rollouts hide play actions, so only outer hands show a starter.
            # Count increments to catch unfinished rollouts that write zeros.
            hands_played = result.stdout.count("Cut/starter card is:")
            self.assertEqual(
                result.stdout.count("game results tallies incremented to"),
                hands_played,
            )
            # The CLI pickles its tally type as __main__.GameScoreResultsTallies.
            with (
                patch.object(
                    sys.modules["__main__"],
                    "GameScoreResultsTallies",
                    GameScoreResultsTallies,
                    create=True,
                ),
                shelve.open(
                    os.path.join(temp_dir, TALLY_SHELF_NAME), flag="r"
                ) as shelf,
            ):
                self.assertEqual(
                    sum(shelf["0-0[D]"][:2]),
                    1,
                    "the opening position should record only the completed game",
                )
                self.assertEqual(len(shelf), hands_played)
                for position, tally in shelf.items():
                    self.assertEqual(sum(tally[:2]), 1, position)


class TestReadmeSmokeGoldenOutputsPart1(unittest.TestCase):
    """Golden checks for the first half of the README smoke tests."""

    def test_readme_526_basic_hands(self) -> None:
        assert_case_matches_golden(self, "readme_526_basic_hands")

    def test_readme_527_basic_games(self) -> None:
        assert_case_matches_golden(self, "readme_527_basic_games")

    def test_readme_528_summary_hands(self) -> None:
        assert_case_matches_golden(self, "readme_528_summary_hands")

    def test_readme_529_summary_games(self) -> None:
        assert_case_matches_golden(self, "readme_529_summary_games")

    def test_readme_530_random_pone(self) -> None:
        assert_case_matches_golden(self, "readme_530_random_pone")

    def test_readme_531_random_dealer(self) -> None:
        assert_case_matches_golden(self, "readme_531_random_dealer")

    def test_readme_532_fixed_pone(self) -> None:
        assert_case_matches_golden(self, "readme_532_fixed_pone")

    def test_readme_533_fixed_pone_single_process(self) -> None:
        assert_case_matches_golden(self, "readme_533_fixed_pone_single_process")

    def test_readme_534_fixed_dealer(self) -> None:
        assert_case_matches_golden(self, "readme_534_fixed_dealer")

    def test_readme_535_all_pone_keeps(self) -> None:
        assert_case_matches_golden(self, "readme_535_all_pone_keeps")

    def test_readme_536_all_dealer_keeps(self) -> None:
        assert_case_matches_golden(self, "readme_536_all_dealer_keeps")

    def test_readme_537_dealer_keeps_late_score(self) -> None:
        assert_case_matches_golden(self, "readme_537_dealer_keeps_late_score")

    def test_readme_538_pone_leads_known_starter(self) -> None:
        assert_case_matches_golden(self, "readme_538_pone_leads_known_starter")

    def test_readme_539_pone_leads_fixed_dealt(self) -> None:
        assert_case_matches_golden(self, "readme_539_pone_leads_fixed_dealt")


class TestReadmeSmokeGoldenOutputsPart2(unittest.TestCase):
    """Golden checks for the second half of the README smoke tests."""

    def test_readme_540a_pone_leads_kept_only(self) -> None:
        assert_case_matches_golden(self, "readme_540a_pone_leads_kept_only")

    def test_readme_540b_pone_leads_run_hand(self) -> None:
        assert_case_matches_golden(self, "readme_540b_pone_leads_run_hand")

    def test_readme_541_pone_leads_partial_kept(self) -> None:
        assert_case_matches_golden(self, "readme_541_pone_leads_partial_kept")

    def test_readme_542_pone_mid_play_known_discard(self) -> None:
        assert_case_matches_golden(self, "readme_542_pone_mid_play_known_discard")

    def test_readme_543_pone_mid_play_unknown_discard(self) -> None:
        assert_case_matches_golden(self, "readme_543_pone_mid_play_unknown_discard")

    def test_readme_544_pone_mid_play_late_game(self) -> None:
        assert_case_matches_golden(self, "readme_544_pone_mid_play_late_game")

    def test_readme_545_dealer_mid_play_known_discard(self) -> None:
        assert_case_matches_golden(self, "readme_545_dealer_mid_play_known_discard")

    def test_readme_546_dealer_mid_play_unknown_discard(self) -> None:
        assert_case_matches_golden(self, "readme_546_dealer_mid_play_unknown_discard")

    def test_readme_547a_pone_non_default_initial_play(self) -> None:
        assert_case_matches_golden(self, "readme_547a_pone_non_default_initial_play")

    def test_readme_547b_pone_non_default_single_process(self) -> None:
        assert_case_matches_golden(self, "readme_547b_pone_non_default_single_process")

    def test_readme_548_dealer_non_default_discard(self) -> None:
        assert_case_matches_golden(self, "readme_548_dealer_non_default_discard")

    def test_readme_549_dealer_second_sequence_go(self) -> None:
        assert_case_matches_golden(self, "readme_549_dealer_second_sequence_go")

    def test_readme_550_dealer_keeps_third_leg_game(self) -> None:
        assert_case_matches_golden(self, "readme_550_dealer_keeps_third_leg_game")

    def test_readme_551_single_hand_sim_discard(self) -> None:
        assert_case_matches_golden(self, "readme_551_single_hand_sim_discard")

    def test_readme_552_single_hand_sim_discard_and_play(self) -> None:
        assert_case_matches_golden(self, "readme_552_single_hand_sim_discard_and_play")


class TestSeatFlipAndKnownIssueGoldenOutputs(unittest.TestCase):
    """Golden checks for the 2023-02-12 known issue and dynamic seat-flip cases."""

    def test_case_a_known_issue_2023_02_12(self) -> None:
        assert_case_matches_golden(self, "case_a_known_issue_2023_02_12")

    def test_case_b_multi_hand_sim_play(self) -> None:
        assert_case_matches_golden(self, "case_b_multi_hand_sim_play")

    def test_case_c_multi_hand_sim_discard(self) -> None:
        assert_case_matches_golden(self, "case_c_multi_hand_sim_discard")

    def test_case_d_single_hand_sim_play(self) -> None:
        assert_case_matches_golden(self, "case_d_single_hand_sim_play")

    def test_case_d_single_hand_sim_discard(self) -> None:
        assert_case_matches_golden(self, "case_d_single_hand_sim_discard")

    def test_case_e_multi_hand_coach_play(self) -> None:
        assert_case_matches_golden(self, "case_e_multi_hand_coach_play")


def regenerate_golden_outputs(case_names: list[str]) -> None:
    """Regenerate the explicitly selected cases after all runs succeed."""
    if not case_names:
        raise ValueError("Specify at least one golden case to regenerate")
    for case_name in case_names:
        if case_name not in GOLDEN_CASES:
            raise ValueError(f"Unknown golden case: {case_name}")

    outputs = {}
    for case_name in case_names:
        returncode, output_text = run_simulator_case(case_name)
        if returncode != 0:
            raise RuntimeError(
                f"Case {case_name} exited with {returncode}:\n{output_text}"
            )
        outputs[case_name] = output_text

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for case_name, output_text in outputs.items():
        golden_path = GOLDEN_DIR / f"{case_name}.txt"
        golden_path.write_text(output_text, encoding="utf-8")
        print(f"Wrote {golden_path}", flush=True)


class TestGoldenHarness(unittest.TestCase):
    """Check normalization and failure handling for the golden harness."""

    def test_normalization_preserves_diagnostics(self) -> None:
        timing = "Simulated 10 games at 1.234 games/s (810000000 ns/game) in 8.1 s"
        diagnostics = f"Warning: {timing}\n{timing} (estimate only)\n\n"
        self.assertEqual(
            sanitize_output(diagnostics + timing + "\n"),
            diagnostics
            + "Simulated 10 games at <SPEED> games/s (<TIME> ns/game) in <ELAPSED> s\n",
        )

    def test_timeout_names_the_case(self) -> None:
        with patch.object(
            subprocess, "run", side_effect=subprocess.TimeoutExpired("python", 120)
        ) as run:
            with self.assertRaisesRegex(
                AssertionError, r"Simulator run timed out after 120 s: .*--game-count"
            ):
                run_simulator_case("readme_526_basic_hands")
        options = run.call_args.kwargs
        self.assertEqual(options["timeout"], 120)
        self.assertEqual(options["encoding"], "utf-8")
        self.assertEqual(options["stdin"], subprocess.DEVNULL)
        self.assertEqual(options["env"]["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(options["env"]["PYTHONUTF8"], "1")

    def test_interactive_case_receives_scripted_stdin(self) -> None:
        with patch.object(
            subprocess, "run", side_effect=subprocess.TimeoutExpired("python", 120)
        ) as run:
            with self.assertRaises(AssertionError):
                run_simulator_case("case_e_multi_hand_coach_play")
        options = run.call_args.kwargs
        self.assertIsNone(options["stdin"])
        self.assertTrue(options["input"].startswith("AC\nAD\nAH\nAS\n2C\n"))
        self.assertEqual(options["input"].count("\n"), 52 * 400)

    def test_regeneration_rejects_unknown_case_before_running(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "fixtures"
            with (
                patch(f"{__name__}.GOLDEN_DIR", output_dir),
                patch(f"{__name__}.run_simulator_case", return_value=(0, "ok")) as run,
                self.assertRaisesRegex(ValueError, "Unknown golden case"),
            ):
                regenerate_golden_outputs(["readme_526_basic_hands", "unknown"])
            run.assert_not_called()
            self.assertFalse(output_dir.exists())

    def test_regeneration_waits_for_all_cases_to_succeed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            fixture = output_dir / "readme_526_basic_hands.txt"
            fixture.write_text("original", encoding="utf-8")
            with (
                patch(f"{__name__}.GOLDEN_DIR", output_dir),
                patch(
                    f"{__name__}.run_simulator_case",
                    side_effect=[(0, "new"), (1, "bad")],
                ),
                self.assertRaisesRegex(RuntimeError, "readme_527_basic_games"),
            ):
                regenerate_golden_outputs(
                    ["readme_526_basic_hands", "readme_527_basic_games"]
                )
            self.assertEqual(fixture.read_text(encoding="utf-8"), "original")
            self.assertEqual(list(output_dir.iterdir()), [fixture])


def main() -> None:
    """CLI entrypoint supporting ``--regenerate`` or ``unittest`` execution."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--regenerate", action="store_true")
    known, remaining = parser.parse_known_args()
    if known.regenerate:
        regenerate_golden_outputs(remaining)
        return
    unittest.main(argv=[sys.argv[0], *remaining])


if __name__ == "__main__":
    main()
