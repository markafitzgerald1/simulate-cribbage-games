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


if __name__ == "__main__":
    unittest.main()
