"""Pin ordered sampler inputs separately from the decomposition algebra."""

import unittest
from fractions import Fraction
from itertools import product
from random import Random

from artifact_pipeline.crib_decomposition import (
    RANK_CATEGORIES,
    ROOT,
    SUIT_CATEGORIES,
    CribGroup,
    bucket_populations,
    reconstruct,
    sample_hand,
)
from artifact_pipeline.test_crib_decomposition import (
    JACK,
    ToyCard,
    _all_stream_means,
    _direct_expectations,
    full_deck_group,
)


class RecordingRNG:
    """Record populations and random operations while using the standard RNG."""

    def __init__(self, seed):
        self.random = Random(seed)
        self.calls = []

    def sample(self, population, count):
        self.calls.append(("sample", tuple(population), count))
        return self.random.sample(population, count)

    def shuffle(self, values):
        self.calls.append(("shuffle", tuple(values)))
        self.random.shuffle(values)


class TestCribSamplingContract(unittest.TestCase):
    """Prove the sampler chooses the populations required by each stream."""

    def test_sampler_populations_and_residual_shuffle(self):
        group = full_deck_group()
        deck = tuple(ToyCard(rank, suit) for rank, suit in product(range(13), range(4)))
        first, second, changed = ToyCard(0, 0), ToyCard(1, 1), ToyCard(1, 0)
        base_population = tuple(card for card in deck if card not in (first, second))
        common = tuple(card for card in deck if card not in (first, second, changed))
        for stream, population in (
            ("base", base_population),
            ("suit", (*common, second)),
        ):
            recorder = RecordingRNG(42)
            sample_hand(group, stream, recorder)
            self.assertEqual(
                recorder.calls,
                [("sample", population, 6)],
                f"{stream} must draw its exact ordered contract population",
            )
        recorder = RecordingRNG(43)
        hand = sample_hand(group, "residual", recorder)
        self.assertEqual(
            [call[0] for call in recorder.calls],
            ["sample", "shuffle"],
            "residual must shuffle after appending the forced card",
        )
        self.assertEqual(recorder.calls[0], ("sample", common, 5))
        self.assertEqual(recorder.calls[1][1][-1], second)
        self.assertEqual(set(hand), set(recorder.calls[1][1]))
        self.assertEqual(hand[0], second)

    def test_sampler_golden_seed_preserves_population_order(self):
        group = full_deck_group()
        cases = (
            ("base", 2, ((1, 0), (1, 3), (12, 2), (6, 1), (3, 0), (11, 0))),
            ("base", 42, ((10, 2), (2, 1), (0, 2), (4, 3), (4, 1), (4, 0))),
            ("residual", 43, ((1, 1), (3, 0), (5, 1), (0, 3), (11, 3), (12, 3))),
            ("suit", 44, ((7, 1), (9, 0), (9, 1), (11, 3), (2, 2), (3, 2))),
            ("suit", 10, ((9, 3), (0, 3), (7, 2), (8, 1), (1, 1), (0, 1))),
        )
        for stream, seed, expected in cases:
            with self.subTest(stream=stream, seed=seed):
                observed = sample_hand(group, stream, Random(seed))
                self.assertEqual(
                    tuple((card.index, card.suit) for card in observed), expected
                )

    def test_group_requires_rank_1_then_rank_2(self):
        group = full_deck_group()
        with self.assertRaisesRegex(ValueError, "in rank order"):
            CribGroup(
                group.deck,
                (ToyCard(1, 0), ToyCard(0, 1)),
                (ToyCard(1, 0), ToyCard(0, 0)),
                6,
            )
        self.assertLess(group.unsuited[0].index, group.unsuited[1].index)
        self.assertEqual(group.suited[0], group.unsuited[0])
        self.assertEqual(group.suited[1].index, group.unsuited[1].index)

    def test_four_suit_toy_deck_reconstruction_and_relation_multiplicity(self):
        deck = tuple(
            ToyCard(rank, suit) for rank, suit in product((1, 2, JACK), range(4))
        )
        group = CribGroup(
            deck, (ToyCard(1, 0), ToyCard(2, 1)), (ToyCard(1, 0), ToyCard(2, 0)), 3
        )
        streams = _all_stream_means(group)
        for variant in ("Unsuited", "Suited"):
            populations = bucket_populations(group, variant)
            reference = _direct_expectations(group, variant)
            self.assertEqual(populations[(JACK, ROOT)], 4)
            self.assertEqual(
                populations[(JACK, "non_matching_discard_suit")],
                2 if variant == "Unsuited" else 3,
            )
            for cut, bucket in populations:
                actual = reconstruct(streams[:3], variant, cut, bucket)
                for category in (*RANK_CATEGORIES, *SUIT_CATEGORIES):
                    self.assertEqual(
                        actual[category], reference[(cut, bucket, category)]
                    )
            for cut, bucket in populations:
                if bucket != ROOT:
                    continue
                for category in (*RANK_CATEGORIES, *SUIT_CATEGORIES, "total"):
                    mixture = sum(
                        Fraction(count, populations[(cut, ROOT)])
                        * reconstruct(streams[:3], variant, cut, relation)[category]
                        for (rank, relation), count in populations.items()
                        if rank == cut and relation != ROOT
                    )
                    self.assertEqual(
                        mixture, reconstruct(streams[:3], variant, cut)[category]
                    )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
