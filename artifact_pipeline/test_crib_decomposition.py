"""Independent finite-population oracles for the opt-in crib decomposition."""

import unittest
from collections import Counter, defaultdict
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations, permutations, product
from random import Random

from artifact_pipeline.crib_decomposition import (
    MATCHING_DISCARD_SUIT,
    NON_MATCHING_DISCARD_SUIT,
    ROOT,
    RANK_CATEGORIES,
    SUIT_CATEGORIES,
    CribGroup,
    _residual_cut,
    base_observation,
    bucket_populations,
    centering_values,
    reconstruct,
    relation,
    residual_observation,
    sample_hand,
    suit_observation,
)


JACK = 10
RANKS = (1, 2, 3, 4, JACK)
SUITS = (0, 1, 2)
HAND_SIZE = 3
CATEGORIES = (*RANK_CATEGORIES, *SUIT_CATEGORIES)


@dataclass(frozen=True, order=True)
class ToyCard:
    """Physical card in a deliberately small deck."""

    index: int
    suit: int


def toy_deck():
    return tuple(ToyCard(rank, suit) for rank, suit in product(RANKS, SUITS))


def twin_group():
    return CribGroup(
        toy_deck(),
        (ToyCard(1, 0), ToyCard(2, 1)),
        (ToyCard(1, 0), ToyCard(2, 0)),
        HAND_SIZE,
    )


def same_rank_group():
    return CribGroup(toy_deck(), (ToyCard(1, 0), ToyCard(1, 1)), None, HAND_SIZE)


def jack_group():
    return CribGroup(
        toy_deck(),
        (ToyCard(1, 0), ToyCard(JACK, 1)),
        (ToyCard(1, 0), ToyCard(JACK, 0)),
        HAND_SIZE,
    )


def full_deck_group():
    deck = tuple(ToyCard(rank, suit) for rank, suit in product(range(13), range(4)))
    return CribGroup(
        deck,
        (ToyCard(0, 0), ToyCard(1, 1)),
        (ToyCard(0, 0), ToyCard(1, 0)),
        6,
    )


def _rank_scores(ranks):
    """Score five ranks directly from cribbage subsets, independent of the core."""
    values = [10 if rank == JACK else rank for rank in ranks]
    fifteens = (
        sum(
            sum(values[position] for position in indices) == 15
            for size in range(2, 6)
            for indices in combinations(range(5), size)
        )
        * 2
    )
    pairs = sum(left == right for left, right in combinations(ranks, 2)) * 2
    runs = 0
    for length in (5, 4, 3):
        run_count = sum(
            sorted(subset) == list(range(min(subset), min(subset) + length))
            for subset in combinations(ranks, length)
        )
        if run_count:
            runs = run_count * length
            break
    return {"fifteens": fifteens, "pairs": pairs, "runs": runs}


def _full_deck_center_numerators(group, cut):
    """Count rank completions by multiplicity, apart from the core oracle."""
    remaining = group.remaining("Unsuited")
    starter = next(card for card in remaining if card.index == cut)
    rank_counts = Counter(card.index for card in remaining if card != starter)
    expected = {category: 0 for category in RANK_CATEGORIES}
    for left, right in combinations(sorted(rank_counts), 2):
        points = _rank_scores((0, 1, left, right, cut))
        for category in RANK_CATEGORIES:
            expected[category] += (
                rank_counts[left] * rank_counts[right] * points[category]
            )
    for rank, count in rank_counts.items():
        points = _rank_scores((0, 1, rank, rank, cut))
        for category in RANK_CATEGORIES:
            expected[category] += count * (count - 1) // 2 * points[category]
    return expected


def _check_full_deck_flush_rule(test_case, deck, discard):
    """Check every legal starter and opposing crib completion for a discard."""
    remaining = tuple(card for card in deck if card not in discard)
    own_suited = discard[0].suit == discard[1].suit
    for starter in remaining:
        can_flush = False
        for opponent_pair in combinations(
            (card for card in remaining if card != starter), 2
        ):
            observed = all(
                card.suit == starter.suit for card in (*discard, *opponent_pair)
            )
            if observed:
                test_case.assertTrue(own_suited)
                test_case.assertNotIn(
                    starter.index, (discard[0].index, discard[1].index)
                )
                can_flush = True
        if own_suited and starter.suit == discard[0].suit:
            test_case.assertTrue(can_flush)
        else:
            test_case.assertFalse(can_flush)


def _policy_discard(hand):
    """A fixed suit-sensitive test policy, with first-maximum tie behavior."""
    best = None
    choice = None
    for pair in combinations(hand, 2):
        priority = (
            pair[0].suit == pair[1].suit,
            sum(card.index for card in pair),
        )
        if best is None or priority > best:
            best, choice = priority, pair
    return choice


def _crib_scores(own_discard, hand, starters):
    opponent_discard = _policy_discard(hand)
    crib = (*own_discard, *opponent_discard)
    return {starter: _score_crib(crib, starter) for starter in starters}


def _score_crib(crib, starter):
    rank_points = _rank_scores(tuple(card.index for card in (*crib, starter)))
    return {
        **rank_points,
        "flushes": 5 * all(card.suit == starter.suit for card in crib),
        "nobs": int(
            any(card.index == JACK and card.suit == starter.suit for card in crib)
        ),
    }


def _reference_relation(discard, starter):
    """Derive the partition independently of the implementation helper."""
    first, second = discard
    if first.index == second.index:
        return (
            "matching_discard_suit"
            if starter.suit in (first.suit, second.suit)
            else "non_matching_discard_suit"
        )
    if first.suit == second.suit:
        return (
            "matching_discard_suit"
            if starter.suit == first.suit
            else "non_matching_discard_suit"
        )
    if starter.suit == first.suit:
        return "matching_rank_1_suit"
    if starter.suit == second.suit:
        return "matching_rank_2_suit"
    return "non_matching_discard_suit"


def _direct_expectations(group, variant):
    """Enumerate equally likely (ordered hand, legal starter) states directly."""
    discard = group.discard(variant)
    remaining = tuple(card for card in group.deck if card not in discard)
    totals = defaultdict(int)
    support = defaultdict(int)
    for hand in permutations(remaining, group.opponent_hand_size):
        starters = tuple(card for card in remaining if card not in hand)
        scores = _crib_scores(discard, hand, starters)
        for starter in starters:
            for bucket in (ROOT, _reference_relation(discard, starter)):
                identity = (starter.index, bucket)
                support[identity] += 1
                for category in CATEGORIES:
                    totals[(*identity, category)] += scores[starter][category]
    return {key: Fraction(total, support[key[:2]]) for key, total in totals.items()}


def _average(rows):
    totals = defaultdict(Fraction)
    for row in rows:
        for key, value in row.items():
            totals[key] += value
    return {key: value / len(rows) for key, value in totals.items()}


def _all_stream_means(group):
    unsuited_hands = tuple(
        permutations(group.remaining("Unsuited"), group.opponent_hand_size)
    )
    base = _average(
        tuple(base_observation(group, hand, _crib_scores) for hand in unsuited_hands)
    )
    centers = centering_values(group, _rank_scores)
    if group.suited is None:
        suit_hands = unsuited_hands
        residual = {}
    else:
        suit_hands = tuple(
            permutations(group.remaining("Suited"), group.opponent_hand_size)
        )
        forced = tuple(hand for hand in suit_hands if group.unsuited[1] in hand)
        residual = _average(
            tuple(residual_observation(group, hand, _crib_scores) for hand in forced)
        )
    suit = _average(
        tuple(
            suit_observation(group, hand, _crib_scores, centers) for hand in suit_hands
        )
    )
    return base, residual, suit, centers


class TestCribDecomposition(unittest.TestCase):
    """Compare the algebra to a separate exhaustive state enumeration."""

    @classmethod
    def setUpClass(cls):
        cls.twins = twin_group()
        cls.twin_streams = _all_stream_means(cls.twins)
        cls.twin_reference = {
            variant: _direct_expectations(cls.twins, variant)
            for variant in ("Unsuited", "Suited")
        }
        cls.same_rank = same_rank_group()
        cls.same_streams = _all_stream_means(cls.same_rank)
        cls.same_reference = _direct_expectations(cls.same_rank, "Unsuited")
        cls.jacks = jack_group()
        cls.jack_streams = _all_stream_means(cls.jacks)
        cls.jack_reference = {
            variant: _direct_expectations(cls.jacks, variant)
            for variant in ("Unsuited", "Suited")
        }

    def test_exact_root_and_relation_reconstruction(self):
        for group, streams, reference_by_variant in (
            (self.twins, self.twin_streams, self.twin_reference),
            (self.same_rank, self.same_streams, {"Unsuited": self.same_reference}),
            (self.jacks, self.jack_streams, self.jack_reference),
        ):
            base, residual, suit, _centers = streams
            for variant, reference in reference_by_variant.items():
                populations = bucket_populations(group, variant)
                self.assertEqual(set(populations), set(key[:2] for key in reference))
                for cut, bucket in populations:
                    actual = reconstruct((base, residual, suit), variant, cut, bucket)
                    for category in CATEGORIES:
                        self.assertEqual(
                            actual[category],
                            reference[(cut, bucket, category)],
                            (variant, cut, bucket, category),
                        )
                    self.assertEqual(
                        actual["total"],
                        sum(
                            reference[(cut, bucket, category)]
                            for category in CATEGORIES
                        ),
                    )

    def test_centering_is_exact_and_does_not_change_corrections(self):
        group = self.twins
        _base, _residual, centered, centers = self.twin_streams
        remaining = group.remaining("Unsuited")
        for cut in {card.index for card in remaining}:
            first_cut = next(card for card in remaining if card.index == cut)
            completions = tuple(card for card in remaining if card != first_cut)
            expected = {
                category: Fraction(
                    sum(
                        _rank_scores((1, 2, left.index, right.index, cut))[category]
                        for left, right in combinations(completions, 2)
                    ),
                    len(completions) * (len(completions) - 1) // 2,
                )
                for category in RANK_CATEGORIES
            }
            self.assertEqual(centers[cut], expected)
        zero_centers = {
            cut: {category: Fraction(0) for category in RANK_CATEGORIES}
            for cut in centers
        }
        all_hands = tuple(
            permutations(group.remaining("Suited"), group.opponent_hand_size)
        )
        without_center = _average(
            tuple(
                suit_observation(group, hand, _crib_scores, zero_centers)
                for hand in all_hands
            )
        )
        for key in centered:
            if key[0] == "C":
                self.assertEqual(centered[key], without_center[key])

    def test_full_deck_center(self):
        group = full_deck_group()
        centers = centering_values(group, _rank_scores)
        denominator = 1176
        for cut in (0, 1, 10):
            expected = _full_deck_center_numerators(group, cut)
            for category in RANK_CATEGORIES:
                self.assertEqual(
                    centers[cut][category] * denominator, expected[category]
                )

    def test_full_deck_integer_scale(self):
        group = full_deck_group()
        centers = centering_values(group, _rank_scores)
        rows = (
            base_observation(
                group, sample_hand(group, "base", Random(42)), _crib_scores
            ),
            residual_observation(
                group, sample_hand(group, "residual", Random(43)), _crib_scores
            ),
            suit_observation(
                group,
                sample_hand(group, "suit", Random(44)),
                _crib_scores,
                centers,
            ),
        )
        for row in rows:
            for value in row.values():
                self.assertEqual((value * 310464).denominator, 1)

    def test_relation_mixture_per_hand_and_after_reconstruction(self):
        group = self.twins
        streams = self.twin_streams
        hand = next(
            iter(permutations(group.remaining("Suited"), group.opponent_hand_size))
        )
        one_row = suit_observation(group, hand, _crib_scores, streams[3])
        for variant in ("Unsuited", "Suited"):
            populations = bucket_populations(group, variant)
            for cut, bucket in populations:
                if bucket != ROOT:
                    continue
                relatives = [
                    (relation_name, count)
                    for (rank, relation_name), count in populations.items()
                    if rank == cut and relation_name != ROOT
                ]
                for rows in (one_row, streams[2]):
                    for category in RANK_CATEGORIES:
                        self.assertEqual(
                            sum(
                                Fraction(count, populations[(cut, ROOT)])
                                * rows[("C", variant, cut, name, category)]
                                for name, count in relatives
                            ),
                            0,
                        )
                    for category in SUIT_CATEGORIES:
                        self.assertEqual(
                            sum(
                                Fraction(count, populations[(cut, ROOT)])
                                * rows[(category, variant, cut, name)]
                                for name, count in relatives
                            ),
                            rows[(category, variant, cut, ROOT)],
                        )
                root = reconstruct(streams[:3], variant, cut)
                mixture = {
                    category: sum(
                        Fraction(count, populations[(cut, ROOT)])
                        * reconstruct(streams[:3], variant, cut, name)[category]
                        for name, count in relatives
                    )
                    for category in (*CATEGORIES, "total")
                }
                self.assertEqual(root, mixture)

    def test_mutations_have_independent_counterexamples(self):
        base, residual, suit, _centers = self.twin_streams
        reference = self.twin_reference["Suited"]
        self.assertTrue(any(value < 0 for value in residual.values()))
        self.assertTrue(
            any(
                _policy_discard(hand)
                != _policy_discard(self.twins.map_to_unsuited(hand))
                for hand in permutations(self.twins.remaining("Suited"), HAND_SIZE)
                if self.twins.unsuited[1] in hand
            )
        )
        self.assertTrue(
            any(
                reference[(cut, ROOT, "nobs")] > 0
                for cut, bucket in bucket_populations(self.twins, "Suited")
                if bucket == ROOT
            )
        )
        self.assertTrue(
            any(
                reconstruct((base, residual, suit), "Suited", cut)["total"]
                != reconstruct(
                    (base, {key: 0 for key in residual}, suit), "Suited", cut
                )["total"]
                for cut, bucket in bucket_populations(self.twins, "Suited")
                if bucket == ROOT
            )
        )
        without_nobs = {
            key: (0 if key[0] == "nobs" else value) for key, value in suit.items()
        }
        self.assertTrue(
            any(
                reconstruct((base, residual, without_nobs), "Suited", cut)["total"]
                != sum(reference[(cut, ROOT, category)] for category in CATEGORIES)
                for cut, bucket in bucket_populations(self.twins, "Suited")
                if bucket == ROOT
            )
        )
        gaps = [
            sum(residual[("D", cut, category)] for category in RANK_CATEGORIES)
            for cut, bucket in bucket_populations(self.twins, "Suited")
            if bucket == ROOT
        ]
        self.assertTrue(any(gap < 0 for gap in gaps))
        self.assertTrue(any(max(Fraction(0), gap) != gap for gap in gaps))
        clamped_residual = {
            key: max(Fraction(0), value) for key, value in residual.items()
        }
        self.assertTrue(
            any(
                reconstruct((base, clamped_residual, suit), "Suited", cut)["total"]
                != sum(reference[(cut, ROOT, category)] for category in CATEGORIES)
                for cut, bucket in bucket_populations(self.twins, "Suited")
                if bucket == ROOT
            )
        )
        total_gaps = [
            reconstruct((base, residual, suit), "Suited", cut)["total"]
            - reconstruct((base, residual, suit), "Unsuited", cut)["total"]
            for cut, bucket in bucket_populations(self.twins, "Suited")
            if bucket == ROOT
        ]
        self.assertTrue(any(gap < 0 for gap in total_gaps))

    def test_zero_occupancy_and_structural_missing_relations(self):
        group = self.twins
        centers = self.twin_streams[3]
        populations = bucket_populations(group, "Suited")
        self.assertNotIn((1, MATCHING_DISCARD_SUIT), populations)
        self.assertNotIn((2, MATCHING_DISCARD_SUIT), populations)
        hand = (ToyCard(1, 1), ToyCard(1, 2), ToyCard(3, 0))
        row = suit_observation(group, hand, _crib_scores, centers)
        self.assertEqual(row[("flushes", "Suited", 1, ROOT)], 0)
        self.assertEqual(row[("nobs", "Suited", 1, ROOT)], 0)
        self.assertTrue(
            ("C", "Suited", 1, NON_MATCHING_DISCARD_SUIT, "fifteens") in row
        )
        self.assertEqual(
            row[("C", "Suited", 1, NON_MATCHING_DISCARD_SUIT, "fifteens")],
            0,
        )
        self.assertTrue(
            any(
                row[("C", "Suited", 3, MATCHING_DISCARD_SUIT, category)] != 0
                for category in RANK_CATEGORIES
            )
        )

    def test_exact_flush_rule_possibility_and_opponent_nobs(self):
        for group in (self.twins, jack_group()):
            for variant in ("Unsuited", "Suited"):
                discard = group.discard(variant)
                remaining = group.remaining(variant)
                for starter in remaining:
                    possible = {
                        _score_crib((*discard, *opponent_pair), starter)["flushes"]
                        for opponent_pair in combinations(
                            tuple(card for card in remaining if card != starter), 2
                        )
                    }
                    if variant == "Unsuited" or starter.index in (
                        discard[0].index,
                        discard[1].index,
                    ):
                        self.assertEqual(possible, {0})
                    elif starter.suit == discard[0].suit:
                        self.assertTrue(5 in possible)
                    else:
                        self.assertEqual(possible, {0})
        own_non_jack = self.twins.unsuited
        opponent_jack = (ToyCard(JACK, 0), ToyCard(3, 1))
        starter = ToyCard(4, 0)
        self.assertEqual(
            _score_crib((*own_non_jack, *opponent_jack), starter)["nobs"], 1
        )
        self.assertEqual(
            _score_crib((*own_non_jack, *opponent_jack), ToyCard(4, 1))["nobs"],
            0,
        )
        self.assertEqual(
            _score_crib((*jack_group().suited, ToyCard(2, 1), ToyCard(3, 2)), starter)[
                "nobs"
            ],
            1,
        )

    def test_full_deck_flush_rule_for_every_rank_twin(self):
        deck = full_deck_group().deck
        for first_rank in range(13):
            for second_rank in range(first_rank, 13):
                first = ToyCard(first_rank, 0)
                unsuited = (first, ToyCard(second_rank, 1))
                with self.subTest(discard=unsuited):
                    _check_full_deck_flush_rule(self, deck, unsuited)
                if first_rank != second_rank:
                    suited = (first, ToyCard(second_rank, 0))
                    with self.subTest(discard=suited):
                        _check_full_deck_flush_rule(self, deck, suited)

    def test_relation_and_sampling_boundaries(self):
        group = self.twins
        for stream in ("base", "residual", "suit"):
            hand = sample_hand(group, stream, Random(42))
            self.assertEqual(len(hand), HAND_SIZE)
            if stream == "residual":
                self.assertTrue(group.unsuited[1] in hand)
        self.assertEqual(
            len(sample_hand(self.same_rank, "suit", Random(42))), HAND_SIZE
        )
        self.assertEqual(
            relation(group.unsuited, ToyCard(3, 0)),
            "matching_rank_1_suit",
        )
        self.assertEqual(
            relation(group.unsuited, ToyCard(3, 1)),
            "matching_rank_2_suit",
        )
        self.assertEqual(relation(group.suited, ToyCard(3, 0)), MATCHING_DISCARD_SUIT)
        self.assertEqual(
            relation(self.same_rank.unsuited, ToyCard(3, 1)),
            MATCHING_DISCARD_SUIT,
        )
        with self.assertRaises(ValueError):
            sample_hand(self.same_rank, "residual", Random(1))
        with self.assertRaises(ValueError):
            group.discard("Missing")

    def test_invalid_physical_inputs_are_rejected(self):
        deck = toy_deck()
        first, second = ToyCard(1, 0), ToyCard(2, 1)
        suited = (first, ToyCard(2, 0))
        invalid = (
            (deck + (first,), (first, second), suited, HAND_SIZE),
            (deck, (first, second), suited, len(deck) - 2),
            (deck, (first, ToyCard(99, 1)), suited, HAND_SIZE),
            (deck, (first, ToyCard(2, 0)), suited, HAND_SIZE),
            (deck, (first, second), None, HAND_SIZE),
            (deck, (first, second), (ToyCard(3, 0), suited[1]), HAND_SIZE),
            (deck, (first, second), (first, ToyCard(2, 2)), HAND_SIZE),
            (deck, (first, ToyCard(1, 1)), (first, first), HAND_SIZE),
        )
        for arguments in invalid:
            with self.subTest(arguments=arguments[1:]):
                with self.assertRaises(ValueError):
                    CribGroup(*arguments)
        with self.assertRaises(ValueError):
            self.same_rank.common()
        with self.assertRaises(ValueError):
            self.same_rank.map_to_unsuited(())

    def test_incomplete_or_inconsistent_scorer_is_rejected(self):
        group = self.twins
        hand = sample_hand(group, "base", Random(42))
        with self.assertRaises(ValueError):
            base_observation(group, hand[:2], _crib_scores)
        with self.assertRaises(ValueError):
            base_observation(group, (*hand[:2], group.unsuited[1]), _crib_scores)
        with self.assertRaises(ValueError):
            base_observation(group, hand, lambda _discard, _hand, _starters: {})

        def inconsistent(discard, dealt, starters):
            scores = _crib_scores(discard, dealt, starters)
            first = next(
                card
                for card in starters
                if sum(other.index == card.index for other in starters) > 1
            )
            twin = next(
                card
                for card in starters
                if (card.index == first.index and card != first)
            )
            scores[twin]["pairs"] += 2
            return scores

        with self.assertRaises(ValueError):
            base_observation(group, hand, inconsistent)
        with self.assertRaises(ValueError):
            residual_observation(group, hand, _crib_scores)
        with self.assertRaises(ValueError):
            residual_observation(self.same_rank, hand, _crib_scores)
        with self.assertRaises(ValueError):
            suit_observation(
                group, (*hand[:2], group.suited[0]), _crib_scores, self.twin_streams[3]
            )
        with self.assertRaises(ValueError):
            _residual_cut(
                group,
                (1, 2),
                ({(1, ROOT): 1}, {1: (0, 0, 0)}),
                ({(1, ROOT): 0}, {1: (0, 0, 0)}),
            )


if __name__ == "__main__":
    unittest.main()
