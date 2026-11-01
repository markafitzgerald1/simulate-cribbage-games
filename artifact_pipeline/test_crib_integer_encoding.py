"""Independent integer formulas that constrain individual estimator rows."""

import unittest
from collections import Counter
from random import Random

from artifact_pipeline.crib_decomposition import (
    RANK_CATEGORIES,
    centering_values,
    residual_observation,
    sample_hand,
    suit_observation,
)
from artifact_pipeline.test_crib_decomposition import (
    _crib_scores,
    _full_deck_center_numerators,
    _rank_scores,
    _reference_relation,
    _scale_crib_scores,
    full_deck_group,
)

SCALE = 310464


def _scores_by_cut(group, variant, hand, scorer):
    discard = group.discard(variant)
    starters = tuple(card for card in group.deck if card not in (*discard, *hand))
    return {
        starter.index: points
        for starter, points in scorer(discard, hand, starters).items()
    }


def _occupancy_coefficients(group, variant, hand):
    discard = group.discard(variant)
    population = tuple(card for card in group.deck if card not in discard)
    starters = tuple(card for card in population if card not in hand)
    root_sizes = Counter(card.index for card in population)
    sizes = Counter(
        (card.index, _reference_relation(discard, card)) for card in population
    )
    root_counts = Counter(card.index for card in starters)
    relation_counts = Counter(
        (card.index, _reference_relation(discard, card)) for card in starters
    )
    return {
        (cut, relation): (300 // size) * relation_counts[(cut, relation)]
        - (300 // root_sizes[cut]) * root_counts[cut]
        for (cut, relation), size in sizes.items()
    }


def _centered_encoding(group, variant, hand, numerators):
    scores = _scores_by_cut(group, variant, hand, _crib_scores)
    expected = {}
    exercised = 0
    for (cut, relation), coefficient in _occupancy_coefficients(
        group, variant, hand
    ).items():
        for category in RANK_CATEGORIES:
            score = scores.get(cut, {}).get(category, 0)
            h_num = numerators[cut][category]
            expected[("C", variant, cut, relation, category)] = coefficient * (
                1176 * score - h_num
            )
            exercised += bool(coefficient and h_num)
    return expected, exercised


def _residual_encoding(group, hand):
    mapped = group.map_to_unsuited(hand)
    suited = _scores_by_cut(group, "Suited", hand, _scale_crib_scores)
    unsuited = _scores_by_cut(group, "Unsuited", mapped, _scale_crib_scores)
    counts = Counter(
        card.index for card in group.deck if card not in (*group.suited, *hand)
    )
    root_sizes = Counter(
        card.index for card in group.deck if card not in group.unsuited
    )
    return {
        ("D", cut, category): (42336 // root_sizes[cut])
        * counts[cut]
        * (suited[cut][category] - unsuited[cut][category])
        for cut in range(13)
        for category in RANK_CATEGORIES
    }


class TestCribIntegerEncoding(unittest.TestCase):
    """Averaged identities alone cannot constrain a fixed centering constant."""

    def test_centering_integer_encoding_subtracts_h_numerator(self):
        group = full_deck_group()
        hand = sample_hand(group, "suit", Random(44))
        centers = centering_values(group, _rank_scores)
        numerators = {
            cut: _full_deck_center_numerators(group, cut) for cut in range(13)
        }
        row = suit_observation(group, hand, _crib_scores, centers)
        exercised = 0
        for variant in ("Unsuited", "Suited"):
            dealt = hand if variant == "Suited" else group.map_to_unsuited(hand)
            expected, sensitive_count = _centered_encoding(
                group, variant, dealt, numerators
            )
            exercised += sensitive_count
            for coordinate, encoded in expected.items():
                actual = SCALE * row[coordinate]
                self.assertEqual(actual.denominator, 1)
                self.assertEqual(
                    actual.numerator,
                    encoded,
                    f"{coordinate}: encoding must use 1176*R - h_num",
                )
        self.assertGreater(exercised, 0)

    def test_random_43_nonzero_residual_uses_42336_over_k(self):
        group = full_deck_group()
        hand = sample_hand(group, "residual", Random(43))
        row = residual_observation(group, hand, _scale_crib_scores)
        expected = _residual_encoding(group, hand)
        for coordinate, encoded in expected.items():
            actual = SCALE * row[coordinate]
            self.assertEqual(actual.denominator, 1)
            self.assertEqual(
                actual.numerator,
                encoded,
                f"{coordinate}: residual encoding must use 42336/k * m * deltaR",
            )
        exercised = sum(bool(value) for value in expected.values())
        self.assertGreater(exercised, 0, "Random(43) must exercise a nonzero residual")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
