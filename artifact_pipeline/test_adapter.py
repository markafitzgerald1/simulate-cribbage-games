import io
import tempfile
import unittest
from unittest.mock import patch

from diskcache import Cache  # type: ignore[import-untyped]

from artifact_pipeline.adapter import (
    Card,
    Index,
    DECK_SET,
    score_hand_and_starter,
    BEST_STATIC_SELECT_PONE_KEPT_CARDS,
    BEST_STATIC_SELECT_DEALER_KEPT_CARDS,
)
from simulate_cribbage_games import cached_expected_random_opponent_discard_crib_points


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

    def test_score_hand_and_starter_known_crib_flush(self):
        """Test crib flush scoring through the legacy adapter surface."""
        kept = [
            Card.from_string("AC"),
            Card.from_string("2C"),
            Card.from_string("3C"),
            Card.from_string("4C"),
        ]

        self.assertEqual(score_hand_and_starter(kept, Card.from_string("5C"), True), 12)
        self.assertEqual(score_hand_and_starter(kept, Card.from_string("5D"), True), 7)

    def test_static_selectors_return_four_original_cards(self):
        dealt = [
            Card.from_string("AC"),
            Card.from_string("2D"),
            Card.from_string("3H"),
            Card.from_string("4S"),
            Card.from_string("5C"),
            Card.from_string("6D"),
        ]

        pone_kept = BEST_STATIC_SELECT_PONE_KEPT_CARDS(dealt)
        dealer_kept = BEST_STATIC_SELECT_DEALER_KEPT_CARDS(dealt)

        self.assertEqual(len(pone_kept), 4)
        self.assertEqual(len(dealer_kept), 4)
        self.assertTrue(set(pone_kept).issubset(dealt))
        self.assertTrue(set(dealer_kept).issubset(dealt))

    def test_random_opponent_discard_crib_points_cold_cache_fill(self):
        expected_a2_unsuited_average = 4.434897959183673
        discarded_cards = (Card.from_string("AC"), Card.from_string("2D"))

        with tempfile.TemporaryDirectory() as cache_dir:
            temporary_cache = Cache(cache_dir)
            temporary_cache.stats(enable=True)
            cached_function = temporary_cache.memoize()(
                cached_expected_random_opponent_discard_crib_points.__wrapped__
            )

            with patch("sys.stdout", new_callable=io.StringIO):
                cold_value = cached_function(discarded_cards)
                warm_value = cached_function(discarded_cards)

            self.assertAlmostEqual(cold_value, expected_a2_unsuited_average)
            self.assertEqual(warm_value, cold_value)
            self.assertEqual(temporary_cache.stats(), (1, 1))


if __name__ == "__main__":
    unittest.main()
