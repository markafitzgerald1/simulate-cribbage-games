# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import contextlib
import inspect
import io
import itertools
import os
import random
import shelve
import tempfile
import unittest
from unittest.mock import patch
import simulate_cribbage_games


class TestSimulateCribbageGames(unittest.TestCase):
    def test_index_count_ace(self):
        self.assertEqual(simulate_cribbage_games.index_count(0), 1)

    def test_index_count_ten(self):
        self.assertEqual(simulate_cribbage_games.index_count(9), 10)

    def test_index_count_jack(self):
        self.assertEqual(simulate_cribbage_games.index_count(10), 10)

    def test_index_count_king(self):
        self.assertEqual(simulate_cribbage_games.index_count(12), 10)

    def test_suit_aware_hand_nobs_ev_respects_known_card_removal(self):
        """Known same-suit dealt cards reduce physical hand Nobs EV."""

        def expected_nobs(dealt):
            kept = dealt[:4]
            starters = [
                card for card in simulate_cribbage_games.DECK_SET if card not in dealt
            ]
            total_nobs = 0
            for starter in starters:
                indices = tuple(sorted([card.index for card in kept] + [starter.index]))
                base_score = (
                    simulate_cribbage_games.cached_pairs_runs_and_fifteens_points(
                        indices
                    )
                )
                total_nobs += (
                    simulate_cribbage_games.score_hand_and_starter(kept, starter)
                    - base_score
                )
            return total_nobs / len(starters)

        no_extra_club = [
            simulate_cribbage_games.Card(10, 0),
            simulate_cribbage_games.Card(0, 1),
            simulate_cribbage_games.Card(1, 2),
            simulate_cribbage_games.Card(2, 3),
            simulate_cribbage_games.Card(3, 1),
            simulate_cribbage_games.Card(4, 2),
        ]
        extra_club = [
            simulate_cribbage_games.Card(10, 0),
            simulate_cribbage_games.Card(0, 0),
            simulate_cribbage_games.Card(1, 2),
            simulate_cribbage_games.Card(2, 3),
            simulate_cribbage_games.Card(3, 1),
            simulate_cribbage_games.Card(4, 2),
        ]

        self.assertAlmostEqual(expected_nobs(no_extra_club), 12 / 46)
        self.assertAlmostEqual(expected_nobs(extra_club), 11 / 46)


def _dummy_shelf(temp_dir: str) -> shelve.Shelf[object]:
    return shelve.open(os.path.join(temp_dir, "tallies_shelf"), flag="c")


def _play_result_for(kept: tuple[simulate_cribbage_games.Card, ...]):
    def recorder(*args, **kwargs):
        del kwargs
        players_statistics = args[11]
        stats = simulate_cribbage_games.Statistics()
        stats.push(0)
        players_statistics[(kept, kept[0])] = {
            "first_pone_minus_first_dealer_game_points": stats,
            "first_pone_minus_first_dealer_play": stats,
        }

    return recorder


def _make_discard_recorder(
    recorded_scores: list[tuple[int, int]],
    recorded_slots: list[tuple[list[list[simulate_cribbage_games.Card]], bool, bool]],
):
    def recorder(*args, **kwargs):
        del kwargs
        recorded_scores.append((args[3], args[4]))
        recorded_slots.append((list(args[5:9]), args[15], args[18]))
        players_statistics = args[11]
        dealt = args[5] or args[6]
        stats = simulate_cribbage_games.Statistics()
        stats.push(0)
        players_statistics[(tuple(dealt[:4]), None)] = {
            "first_pone_minus_first_dealer_game_points": stats,
            "first_pone_minus_first_dealer_total_points": stats,
        }

    return recorder


class TestPlayBasedOnSimulationSeatFlip(unittest.TestCase):
    """Regression tests for seat-aligned scores in ``play_based_on_simulation``."""

    SCORE = simulate_cribbage_games.GameScore(
        simulate_cribbage_games.Points(100),
        simulate_cribbage_games.Points(7),
        simulate_cribbage_games.Points(8),
        simulate_cribbage_games.Points(4),
        simulate_cribbage_games.Points(95),
        simulate_cribbage_games.Points(11),
        simulate_cribbage_games.Points(9),
        simulate_cribbage_games.Points(3),
    )

    def _run_play_recorder_case(
        self,
        pone_is_parent_game_first_pone: bool,
        root_simulation_first_pone_is_next_to_play: bool,
        player: simulate_cribbage_games.Player,
    ) -> tuple[int, int]:
        dealt = simulate_cribbage_games.parse_cards("9D,TS,7D,5H,JH,AH")
        kept = simulate_cribbage_games.parse_cards("TS,5H,JH,AH")
        starter = simulate_cribbage_games.Card.from_string("2C")
        initial_actions = simulate_cribbage_games.parse_play_actions(
            "" if player == simulate_cribbage_games.PONE else "KH"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with _dummy_shelf(temp_dir) as shelf:
                with patch.object(
                    simulate_cribbage_games,
                    "simulate_games",
                    side_effect=_play_result_for(tuple(kept)),
                ) as simulate:
                    chosen = simulate_cribbage_games.play_based_on_simulation(
                        1,
                        True,
                        self.SCORE,
                        root_simulation_first_pone_is_next_to_play,
                        dealt,
                        kept,
                        starter,
                        initial_actions,
                        player,
                        pone_is_parent_game_first_pone,
                        False,
                        False,
                        False,
                        True,
                        shelf,
                    )
        self.assertTrue(chosen in kept)
        simulate.assert_called_once()
        args = simulate.call_args.args
        if player == simulate_cribbage_games.PONE:
            self.assertEqual(
                args[5:9],
                (
                    simulate_cribbage_games.parse_cards("9D,TS,7D,5H,JH,AH"),
                    [],
                    simulate_cribbage_games.parse_cards("TS,5H,JH,AH"),
                    [],
                ),
            )
        else:
            self.assertEqual(
                args[5:9],
                (
                    [],
                    simulate_cribbage_games.parse_cards("9D,TS,7D,5H,JH,AH"),
                    [],
                    simulate_cribbage_games.parse_cards("TS,5H,JH,AH"),
                ),
            )
        return args[3], args[4]

    def test_even_hand_pone_passes_first_pone_then_first_dealer_score(self) -> None:
        self.assertEqual(
            self._run_play_recorder_case(
                pone_is_parent_game_first_pone=True,
                root_simulation_first_pone_is_next_to_play=True,
                player=simulate_cribbage_games.PONE,
            ),
            (119, 118),
        )

    def test_even_hand_dealer_passes_first_pone_then_first_dealer_score(self) -> None:
        self.assertEqual(
            self._run_play_recorder_case(
                pone_is_parent_game_first_pone=True,
                root_simulation_first_pone_is_next_to_play=False,
                player=simulate_cribbage_games.DEALER,
            ),
            (119, 118),
        )

    def test_odd_hand_pone_passes_current_pone_then_current_dealer_score(self) -> None:
        self.assertEqual(
            self._run_play_recorder_case(
                pone_is_parent_game_first_pone=False,
                root_simulation_first_pone_is_next_to_play=False,
                player=simulate_cribbage_games.PONE,
            ),
            (118, 119),
        )

    def test_odd_hand_dealer_passes_current_pone_then_current_dealer_score(
        self,
    ) -> None:
        self.assertEqual(
            self._run_play_recorder_case(
                pone_is_parent_game_first_pone=False,
                root_simulation_first_pone_is_next_to_play=True,
                player=simulate_cribbage_games.DEALER,
            ),
            (118, 119),
        )

    def _run_end_to_end_probe(
        self,
        pone_score: int,
        dealer_score: int,
        pone_is_parent_game_first_pone: bool,
        root_simulation_first_pone_is_next_to_play: bool,
    ) -> simulate_cribbage_games.PlayAction:
        dealt = simulate_cribbage_games.parse_cards("9D,TS,7D,5H,JH,AH")
        kept = simulate_cribbage_games.parse_cards("TS,5H,JH,AH")
        starter = simulate_cribbage_games.Card.from_string("2C")
        initial_actions = simulate_cribbage_games.parse_play_actions("KH")
        score = simulate_cribbage_games.GameScore(
            simulate_cribbage_games.Points(pone_score),
            simulate_cribbage_games.Points(0),
            simulate_cribbage_games.Points(0),
            simulate_cribbage_games.Points(0),
            simulate_cribbage_games.Points(dealer_score),
            simulate_cribbage_games.Points(0),
            simulate_cribbage_games.Points(0),
            simulate_cribbage_games.Points(0),
        )
        saved_state = random.getstate()
        random.seed(12345)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                with _dummy_shelf(temp_dir) as shelf:
                    return simulate_cribbage_games.play_based_on_simulation(
                        100,
                        True,
                        score,
                        root_simulation_first_pone_is_next_to_play,
                        dealt,
                        kept,
                        starter,
                        initial_actions,
                        simulate_cribbage_games.DEALER,
                        pone_is_parent_game_first_pone,
                        False,
                        False,
                        False,
                        True,
                        shelf,
                    )
        finally:
            random.setstate(saved_state)

    def test_end_to_end_even_hand_dealer_picks_five_of_hearts(self) -> None:
        chosen = self._run_end_to_end_probe(
            pone_score=118,
            dealer_score=119,
            pone_is_parent_game_first_pone=True,
            root_simulation_first_pone_is_next_to_play=False,
        )
        self.assertEqual(chosen, simulate_cribbage_games.Card.from_string("5H"))

    def test_end_to_end_odd_hand_dealer_picks_five_of_hearts(self) -> None:
        chosen = self._run_end_to_end_probe(
            pone_score=119,
            dealer_score=118,
            pone_is_parent_game_first_pone=False,
            root_simulation_first_pone_is_next_to_play=True,
        )
        self.assertEqual(chosen, simulate_cribbage_games.Card.from_string("5H"))


class TestDiscardBasedOnSimulationSeatFlip(unittest.TestCase):
    """Regression tests for seat-aligned scores in simulation-based discarding."""

    def _run_two_hand_sim_discard_calls(
        self, use_coach: bool = False
    ) -> list[tuple[int, int]]:
        recorded_scores: list[tuple[int, int]] = []
        recorded_slots: list[
            tuple[list[list[simulate_cribbage_games.Card]], bool, bool]
        ] = []
        saved_state = random.getstate()
        random.seed(12345)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                with _dummy_shelf(temp_dir) as shelf:
                    with (
                        patch.object(
                            simulate_cribbage_games,
                            "simulate_games",
                            side_effect=_make_discard_recorder(
                                recorded_scores, recorded_slots
                            ),
                        ),
                        patch.object(
                            simulate_cribbage_games,
                            "keep_user_selected",
                            side_effect=lambda dealt: dealt[:4],
                        ),
                        patch.object(
                            simulate_cribbage_games,
                            "BEST_STATIC_SELECT_PONE_KEPT_CARDS",
                            side_effect=lambda dealt: dealt[:4],
                        ),
                        patch.object(
                            simulate_cribbage_games,
                            "BEST_STATIC_SELECT_DEALER_KEPT_CARDS",
                            side_effect=lambda dealt: dealt[:4],
                        ),
                        contextlib.redirect_stdout(io.StringIO()),
                    ):
                        if use_coach:
                            pone_sel = simulate_cribbage_games.keep_user_selected
                            dealer_sel = simulate_cribbage_games.keep_user_selected
                            pone_sim = None
                            dealer_sim = None
                        else:
                            pone_sel = (
                                simulate_cribbage_games.DEFAULT_SELECT_PONE_KEPT_CARDS
                            )
                            dealer_sel = (
                                simulate_cribbage_games.DEFAULT_SELECT_DEALER_KEPT_CARDS
                            )
                            pone_sim = 1
                            dealer_sim = 1

                        result = simulate_cribbage_games.simulate_game(
                            [],
                            [],
                            simulate_cribbage_games.DECK_LIST,
                            [],
                            [],
                            None,
                            2,
                            pone_sel,
                            pone_sim,
                            False,
                            dealer_sel,
                            dealer_sim,
                            False,
                            simulate_cribbage_games.play_first,
                            None,
                            simulate_cribbage_games.play_first,
                            None,
                            1 if use_coach else None,
                            None,
                            False,
                            False,
                            False,
                            shelf,
                            True,
                            True,
                            itertools.cycle(()),
                            itertools.cycle(()),
                            set(),
                            simulate_cribbage_games.Points(50),
                            simulate_cribbage_games.Points(30),
                            None,
                            [],
                            True,
                        )
        finally:
            random.setstate(saved_state)

        self.assertEqual(
            [
                (s.first_pone_points, s.first_dealer_points)
                for s in result.start_of_hand_scores
            ],
            [(50, 30), (63, 41)],
        )
        self.assertEqual(len(recorded_scores), 4)
        parse = simulate_cribbage_games.parse_cards
        self.assertEqual(
            recorded_slots,
            [
                ([parse("AH,8S,AC,7D,JD,KC"), [], [], []], True, False),
                ([[], parse("5D,JH,2H,JC,9S,8C"), [], []], False, True),
                ([parse("4D,TH,2S,QC,AS,QS"), [], [], []], True, False),
                ([[], parse("TS,TD,6C,8H,AH,QH"), [], []], False, True),
            ],
        )
        return recorded_scores

    def test_simulate_game_even_hand_sim_discard_pone_and_dealer_scores(self) -> None:
        calls = self._run_two_hand_sim_discard_calls(use_coach=False)
        self.assertEqual(calls[0], (50, 30))
        self.assertEqual(calls[1], (50, 30))

    def test_simulate_game_odd_hand_sim_discard_pone_swaps_parent_scores(self) -> None:
        calls = self._run_two_hand_sim_discard_calls(use_coach=False)
        self.assertEqual(calls[2], (41, 63))

    def test_simulate_game_odd_hand_sim_discard_dealer_swaps_parent_scores(
        self,
    ) -> None:
        calls = self._run_two_hand_sim_discard_calls(use_coach=False)
        self.assertEqual(calls[3], (41, 63))

    def test_simulate_game_even_hand_coach_discard_pone_and_dealer_scores(
        self,
    ) -> None:
        calls = self._run_two_hand_sim_discard_calls(use_coach=True)
        self.assertEqual(calls[0], (50, 30))
        self.assertEqual(calls[1], (50, 30))

    def test_simulate_game_odd_hand_coach_discard_pone_swaps_parent_scores(
        self,
    ) -> None:
        calls = self._run_two_hand_sim_discard_calls(use_coach=True)
        self.assertEqual(calls[2], (41, 63))

    def test_simulate_game_odd_hand_coach_discard_dealer_swaps_parent_scores(
        self,
    ) -> None:
        calls = self._run_two_hand_sim_discard_calls(use_coach=True)
        self.assertEqual(calls[3], (41, 63))


def _simulate_game_frame():
    """Return the innermost ``simulate_game`` frame on the current stack."""
    for frame_info in inspect.stack():
        if frame_info.function == "simulate_game":
            return frame_info.frame
    raise AssertionError("play_based_on_simulation called outside simulate_game")


class TestPlayCallSitesSeatFlip(unittest.TestCase):
    """Check what ``simulate_game``'s two play call sites pass in each hand.

    ``play_based_on_simulation`` is replaced by a recorder that answers with the
    first legal play, so the game runs normally while every call's hand, acting
    seat, ``root_simulation_first_pone_is_next_to_play`` and
    ``pone_is_parent_game_first_pone`` arguments are captured.
    """

    def _run_two_hand_play_calls(
        self, use_coach: bool
    ) -> set[tuple[int, int, bool, bool]]:
        recorded: set[tuple[int, int, bool, bool]] = set()

        def recorder(*args, **kwargs):
            del kwargs
            frame = _simulate_game_frame()
            recorded.add((frame.f_locals["hand"], args[8], args[3], args[9]))
            return frame.f_locals["legal_play_actions"][0]

        saved_state = random.getstate()
        random.seed(12345)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                with _dummy_shelf(temp_dir) as shelf:
                    with (
                        patch.object(
                            simulate_cribbage_games,
                            "play_based_on_simulation",
                            side_effect=recorder,
                        ),
                        patch.object(
                            simulate_cribbage_games,
                            "play_user_selected",
                            side_effect=lambda playable, count, current: 0,
                        ),
                        patch("builtins.input", return_value=""),
                        contextlib.redirect_stdout(io.StringIO()),
                    ):
                        if use_coach:
                            select_play = simulate_cribbage_games.play_user_selected
                            play_sims = None
                        else:
                            select_play = simulate_cribbage_games.play_first
                            play_sims = 1
                        simulate_cribbage_games.simulate_game(
                            [],
                            [],
                            simulate_cribbage_games.DECK_LIST,
                            [],
                            [],
                            None,
                            2,
                            simulate_cribbage_games.DEFAULT_SELECT_PONE_KEPT_CARDS,
                            None,
                            False,
                            simulate_cribbage_games.DEFAULT_SELECT_DEALER_KEPT_CARDS,
                            None,
                            False,
                            select_play,
                            play_sims,
                            select_play,
                            play_sims,
                            None,
                            1 if use_coach else None,
                            False,
                            False,
                            False,
                            shelf,
                            True,
                            True,
                            itertools.cycle(()),
                            itertools.cycle(()),
                            set(),
                            simulate_cribbage_games.Points(50),
                            simulate_cribbage_games.Points(30),
                            None,
                            [],
                            True,
                        )
        finally:
            random.setstate(saved_state)
        return recorded

    # Each tuple is (hand, acting seat, first pone to play, hand pone is first
    # pone). Hand 0: first pone is the hand's pone (seat 0). Hand 1: first pone
    # deals, so the hand's pone (seat 0) is first dealer.
    EXPECTED = {
        (0, simulate_cribbage_games.PONE, True, True),
        (0, simulate_cribbage_games.DEALER, False, True),
        (1, simulate_cribbage_games.PONE, False, False),
        (1, simulate_cribbage_games.DEALER, True, False),
    }

    def test_simulation_play_call_site_passes_hand_seating(self) -> None:
        self.assertEqual(self._run_two_hand_play_calls(use_coach=False), self.EXPECTED)

    def test_coach_play_call_site_passes_hand_seating(self) -> None:
        self.assertEqual(self._run_two_hand_play_calls(use_coach=True), self.EXPECTED)


if __name__ == "__main__":
    unittest.main()
