# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import unittest
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


if __name__ == "__main__":
    unittest.main()
