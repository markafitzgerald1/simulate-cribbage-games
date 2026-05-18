import unittest

from artifact_pipeline.adapter import (
    Card,
    Index,
    DECK_SET,
    score_hand_and_starter,
    BEST_STATIC_SELECT_PONE_KEPT_CARDS,
    BEST_STATIC_SELECT_DEALER_KEPT_CARDS,
)


class TestAdapter(unittest.TestCase):
    def test_imports(self):
        """Test that the adapter successfully imports legacy structures."""
        self.assertIsNotNone(Card)
        self.assertIsNotNone(Index)
        self.assertIsNotNone(DECK_SET)
        self.assertIsNotNone(score_hand_and_starter)
        self.assertIsNotNone(BEST_STATIC_SELECT_PONE_KEPT_CARDS)
        self.assertIsNotNone(BEST_STATIC_SELECT_DEALER_KEPT_CARDS)

    def test_card_creation(self):
        """Test basic Card interaction via adapter."""
        c = Card(0, 0)
        self.assertEqual(c.index, 0)
        self.assertEqual(c.suit, 0)

    def test_index_indices(self):
        """Test Index metadata is available."""
        NUM_RANKS = 13
        self.assertEqual(len(Index.indices), NUM_RANKS)

    def test_deck_set_valid(self):
        """Test DECK_SET is properly populated."""
        DECK_SIZE = 52
        self.assertEqual(len(DECK_SET), DECK_SIZE)

    def test_score_hand_and_starter(self):
        """Test scoring function availability and basic execution."""
        kept = [Card(0, 0), Card(1, 0), Card(2, 0), Card(3, 0)]
        starter = Card(4, 0)
        score = score_hand_and_starter(kept, starter, is_crib=True)
        self.assertTrue(isinstance(score, int))


if __name__ == "__main__":
    unittest.main()
