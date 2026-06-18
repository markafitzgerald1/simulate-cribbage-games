import unittest

from artifact_pipeline.adapter import (
    Card,
    Index,
    DECK_SET,
    score_hand_and_starter,
    score_hand_and_starter_breakdown,
    cached_pairs_runs_and_fifteens_points,
    BEST_STATIC_SELECT_PONE_KEPT_CARDS,
    BEST_STATIC_SELECT_DEALER_KEPT_CARDS,
    score_hand_over_starters,
)


class TestAdapter(unittest.TestCase):
    def test_imports(self):
        """Test that the adapter successfully imports legacy structures."""
        self.assertIsNotNone(Card)
        self.assertIsNotNone(Index)
        self.assertIsNotNone(DECK_SET)
        self.assertIsNotNone(score_hand_and_starter)
        self.assertIsNotNone(score_hand_and_starter_breakdown)
        self.assertIsNotNone(cached_pairs_runs_and_fifteens_points)
        self.assertIsNotNone(BEST_STATIC_SELECT_PONE_KEPT_CARDS)
        self.assertIsNotNone(BEST_STATIC_SELECT_DEALER_KEPT_CARDS)
        self.assertIsNotNone(score_hand_over_starters)

    def test_card_creation(self):
        """Test basic Card interaction via adapter."""
        card = Card(0, 0)
        self.assertEqual(card.index, 0)
        self.assertEqual(card.suit, 0)

    def test_index_indices(self):
        """Test Index metadata is available."""
        num_ranks = 13
        self.assertEqual(len(Index.indices), num_ranks)

    def test_deck_set_valid(self):
        """Test DECK_SET is properly populated."""
        deck_size = 52
        self.assertEqual(len(DECK_SET), deck_size)

    def test_score_hand_and_starter(self):
        """Test scoring function availability and basic execution."""
        kept = [Card(0, 0), Card(1, 0), Card(2, 0), Card(3, 0)]
        starter = Card(4, 0)
        score = score_hand_and_starter(kept, starter, is_crib=True)
        self.assertTrue(isinstance(score, int))

    def test_score_hand_and_starter_breakdown(self):
        """Test crib scoring categories are exposed without changing totals."""
        kept = [Card(0, 0), Card(1, 0), Card(2, 0), Card(10, 0)]
        starter = Card(3, 0)

        breakdown = score_hand_and_starter_breakdown(kept, starter, is_crib=True)

        self.assertEqual(breakdown["fifteens"], 4)
        self.assertEqual(breakdown["pairs"], 0)
        self.assertEqual(breakdown["runs"], 4)
        self.assertEqual(breakdown["flushes"], 5)
        self.assertEqual(breakdown["nobs"], 1)
        self.assertEqual(breakdown["total"], 14)
        self.assertEqual(
            breakdown["total"], score_hand_and_starter(kept, starter, is_crib=True)
        )

    def test_score_hand_over_starters(self):
        """Test score_hand_over_starters matches score_hand_and_starter for all deck starters."""
        kept = [Card(0, 0), Card(1, 0), Card(2, 0), Card(10, 0)]
        starters = [card for card in DECK_SET if card not in kept]

        scores = score_hand_over_starters(kept, starters)

        self.assertEqual(len(scores), len(starters))
        for starter in starters:
            expected = score_hand_and_starter(kept, starter, is_crib=False)
            self.assertEqual(scores[starter], expected)


if __name__ == "__main__":
    unittest.main()
