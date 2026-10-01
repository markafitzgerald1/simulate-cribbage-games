"""Exact per-deal components of the opt-in shared-rank crib estimator.

This module only evaluates a fixed, supplied opponent policy. The production
generator does not call it until the separate v4 integration is implemented.
"""

from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from typing import Optional


RANK_CATEGORIES = ("fifteens", "pairs", "runs")
SUIT_CATEGORIES = ("flushes", "nobs")
ROOT = "root"
MATCHING_DISCARD_SUIT = "matching_discard_suit"
MATCHING_RANK_1_SUIT = "matching_rank_1_suit"
MATCHING_RANK_2_SUIT = "matching_rank_2_suit"
NON_MATCHING_DISCARD_SUIT = "non_matching_discard_suit"


@dataclass(frozen=True)
class CribGroup:
    """A rank multiset with its canonical physical discard variants."""

    deck: tuple
    unsuited: tuple
    suited: Optional[tuple]
    opponent_hand_size: int

    def __post_init__(self):
        ordered = tuple(sorted(self.deck, key=lambda card: (card.index, card.suit)))
        object.__setattr__(self, "deck", ordered)
        if len(set(ordered)) != len(ordered):
            raise ValueError("The physical deck contains duplicate cards")
        if not 2 <= self.opponent_hand_size < len(ordered) - 2:
            raise ValueError("The opponent hand leaves no starter population")
        if len(self.unsuited) != 2 or any(
            card not in ordered for card in self.unsuited
        ):
            raise ValueError("The unsuited discard must contain two deck cards")
        first, second = self.unsuited
        if first == second or first.suit == second.suit:
            raise ValueError("The unsuited discard must use distinct suits")
        if self.suited is None:
            if first.index != second.index:
                raise ValueError("A distinct-rank group requires a suited twin")
        else:
            if len(self.suited) != 2 or self.suited[0] != first:
                raise ValueError("The suited twin must share the first card")
            changed = self.suited[1]
            if (
                changed not in ordered
                or changed == first
                or changed.index != second.index
                or changed.suit != first.suit
            ):
                raise ValueError("The suited twin must replace only the second suit")

    def discard(self, variant):
        """Return the actual physical discard for a variant."""
        if variant == "Unsuited":
            return self.unsuited
        if variant == "Suited" and self.suited is not None:
            return self.suited
        raise ValueError(f"Unavailable discard variant: {variant}")

    def remaining(self, variant):
        """Return the 50-card production population, or its reduced analogue."""
        discarded = self.discard(variant)
        return tuple(card for card in self.deck if card not in discarded)

    def common(self):
        """Return cards physically available in both twin populations."""
        if self.suited is None:
            raise ValueError("Same-rank pairs have no paired population")
        excluded = {*self.unsuited, self.suited[1]}
        return tuple(card for card in self.deck if card not in excluded)

    def map_to_unsuited(self, suited_hand):
        """Map only the changed physical card, preserving opponent hand order."""
        if self.suited is None:
            raise ValueError("Same-rank pairs have no paired hand")
        return tuple(
            self.suited[1] if card == self.unsuited[1] else card for card in suited_hand
        )


def relation(discard, starter):
    """Apply the existing canonical starter-suit partition to physical cards."""
    first, second = discard
    if first.index == second.index:
        matching = starter.suit in (first.suit, second.suit)
        return MATCHING_DISCARD_SUIT if matching else NON_MATCHING_DISCARD_SUIT
    if first.suit == second.suit:
        return (
            MATCHING_DISCARD_SUIT
            if starter.suit == first.suit
            else NON_MATCHING_DISCARD_SUIT
        )
    by_suit = {
        first.suit: MATCHING_RANK_1_SUIT,
        second.suit: MATCHING_RANK_2_SUIT,
    }
    return by_suit.get(starter.suit, NON_MATCHING_DISCARD_SUIT)


def bucket_populations(group, variant):
    """Count fixed root/relation starter populations before sampling a hand."""
    discard = group.discard(variant)
    populations = {}
    for card in group.remaining(variant):
        root = (card.index, ROOT)
        bucket = (card.index, relation(discard, card))
        populations[root] = populations.get(root, 0) + 1
        populations[bucket] = populations.get(bucket, 0) + 1
    return populations


def _root_populations(group):
    return {
        cut: size
        for (cut, bucket), size in bucket_populations(group, "Unsuited").items()
        if bucket == ROOT
    }


def centering_values(group, rank_score):
    """Enumerate the exact two-card rank-completion center for every cut."""
    remaining = group.remaining("Unsuited")
    centers = {}
    for cut in {card.index for card in remaining}:
        starter = next(card for card in remaining if card.index == cut)
        completions = tuple(card for card in remaining if card != starter)
        totals = {category: 0 for category in RANK_CATEGORIES}
        for two_cards in combinations(completions, 2):
            ranks = (
                group.unsuited[0].index,
                group.unsuited[1].index,
                two_cards[0].index,
                two_cards[1].index,
                cut,
            )
            points = rank_score(ranks)
            for category in RANK_CATEGORIES:
                totals[category] += points[category]
        denominator = len(completions) * (len(completions) - 1) // 2
        centers[cut] = {
            category: Fraction(totals[category], denominator)
            for category in RANK_CATEGORIES
        }
    return centers


def sample_hand(group, stream, rng):
    """Sample one ordered hand using the stream's specified physical population."""
    size = group.opponent_hand_size
    if stream == "base" or (stream == "suit" and group.suited is None):
        return tuple(rng.sample(group.remaining("Unsuited"), size))
    if stream == "residual" and group.suited is not None:
        hand = rng.sample(group.common(), size - 1) + [group.unsuited[1]]
        rng.shuffle(hand)
        return tuple(hand)
    if stream == "suit" and group.suited is not None:
        return tuple(rng.sample((*group.common(), group.unsuited[1]), size))
    raise ValueError(f"Unavailable estimator stream: {stream}")


def _evaluate(group, variant, hand, score_deal):
    """Select the opponent discard once, then evaluate all remaining starters."""
    remaining = group.remaining(variant)
    if len(hand) != group.opponent_hand_size or len(set(hand)) != len(hand):
        raise ValueError("Invalid ordered opponent hand")
    if any(card not in remaining for card in hand):
        raise ValueError("Opponent hand is outside its physical population")
    starters = tuple(card for card in remaining if card not in hand)
    scores = score_deal(group.discard(variant), hand, starters)
    if set(scores) != set(starters):
        raise ValueError("Scorer must return every remaining physical starter")
    counts = {}
    category_sums = {}
    rank_scores = {}
    discard = group.discard(variant)
    for starter in starters:
        points = scores[starter]
        rank_points = tuple(points[category] for category in RANK_CATEGORIES)
        previous = rank_scores.setdefault(starter.index, rank_points)
        if rank_points != previous:
            raise ValueError("Rank categories must be starter-suit invariant")
        _add_starter(counts, category_sums, discard, starter, points)
    return counts, category_sums, rank_scores


def _add_starter(counts, category_sums, discard, starter, points):
    for bucket in (ROOT, relation(discard, starter)):
        key = (starter.index, bucket)
        counts[key] = counts.get(key, 0) + 1
        for category in SUIT_CATEGORIES:
            value_key = (*key, category)
            category_sums[value_key] = (
                category_sums.get(value_key, 0) + points[category]
            )


def base_observation(group, unsuited_hand, score_deal):
    """Return all shared rank-baseline coordinates for one ordinary hand."""
    counts, _sums, rank_scores = _evaluate(group, "Unsuited", unsuited_hand, score_deal)
    populations = _root_populations(group)
    population_size = len(group.deck) - 2
    starter_count = population_size - group.opponent_hand_size
    values = {}
    for cut, size in populations.items():
        weight = Fraction(
            population_size * counts.get((cut, ROOT), 0),
            starter_count * size,
        )
        for position, category in enumerate(RANK_CATEGORIES):
            values[("B", cut, category)] = (
                weight * rank_scores.get(cut, (0, 0, 0))[position]
            )
    return values


def residual_observation(group, suited_hand, score_deal):
    """Return forced-inclusion rank differences, including the inclusion weight."""
    if group.suited is None or group.unsuited[1] not in suited_hand:
        raise ValueError("Residual observations require the changed card")
    unsuited_hand = group.map_to_unsuited(suited_hand)
    suited_counts, _suited_sums, suited_scores = _evaluate(
        group, "Suited", suited_hand, score_deal
    )
    unsuited_counts, _unsuited_sums, unsuited_scores = _evaluate(
        group, "Unsuited", unsuited_hand, score_deal
    )
    populations = _root_populations(group)
    values = {}
    for cut, size in populations.items():
        values.update(
            _residual_cut(
                group,
                (cut, size),
                (suited_counts, suited_scores),
                (unsuited_counts, unsuited_scores),
            )
        )
    return values


def _residual_cut(group, bucket, suited, unsuited):
    cut, size = bucket
    suited_counts, suited_scores = suited
    unsuited_counts, unsuited_scores = unsuited
    count = suited_counts.get((cut, ROOT), 0)
    if count != unsuited_counts.get((cut, ROOT), 0):
        raise ValueError("Mapped twins must share starter-rank counts")
    starter_count = len(group.deck) - 2 - group.opponent_hand_size
    weight = Fraction(group.opponent_hand_size * count, starter_count * size)
    return {
        ("D", cut, category): weight
        * (
            suited_scores.get(cut, (0, 0, 0))[position]
            - unsuited_scores.get(cut, (0, 0, 0))[position]
        )
        for position, category in enumerate(RANK_CATEGORIES)
    }


def suit_observation(group, suited_hand, score_deal, centers):
    """Return jointly sampled relation corrections, flush and nobs coordinates."""
    if group.suited is not None and any(
        card not in group.remaining("Suited") for card in suited_hand
    ):
        raise ValueError("Suit hand is outside the suited population")
    variants = ("Unsuited", "Suited") if group.suited else ("Unsuited",)
    values = {}
    for variant in variants:
        hand = suited_hand
        if variant == "Unsuited" and group.suited:
            hand = group.map_to_unsuited(suited_hand)
        values.update(_suit_variant(group, variant, hand, score_deal, centers))
    return values


def _suit_variant(group, variant, hand, score_deal, centers):
    deal = _evaluate(group, variant, hand, score_deal)
    populations = bucket_populations(group, variant)
    values = {}
    for (cut, bucket), size in populations.items():
        weight = Fraction(
            len(group.deck) - 2,
            (len(group.deck) - 2 - group.opponent_hand_size) * size,
        )
        for category in SUIT_CATEGORIES:
            values[(category, variant, cut, bucket)] = weight * deal[1].get(
                (cut, bucket, category), 0
            )
        if bucket != ROOT:
            values.update(
                _relation_correction(
                    group, (variant, cut, bucket), populations, deal, centers
                )
            )
    return values


def _relation_correction(group, identity, populations, deal, centers):
    variant, cut, bucket = identity
    counts, _category_sums, rank_scores = deal
    population_size = len(group.deck) - 2
    starter_count = population_size - group.opponent_hand_size
    occupancy_shift = Fraction(population_size, starter_count) * (
        Fraction(counts.get((cut, bucket), 0), populations[(cut, bucket)])
        - Fraction(counts.get((cut, ROOT), 0), populations[(cut, ROOT)])
    )
    return {
        ("C", variant, cut, bucket, category): occupancy_shift
        * (rank_scores.get(cut, (0, 0, 0))[position] - centers[cut][category])
        for position, category in enumerate(RANK_CATEGORIES)
    }


def reconstruct(streams, variant, cut, bucket=ROOT):
    """Project component observations or their means into a measured crib EV."""
    base, residual, suit = streams
    values = {}
    for category in RANK_CATEGORIES:
        values[category] = base[("B", cut, category)]
        if variant == "Suited":
            values[category] += residual[("D", cut, category)]
        if bucket != ROOT:
            values[category] += suit[("C", variant, cut, bucket, category)]
    for category in SUIT_CATEGORIES:
        values[category] = suit[(category, variant, cut, bucket)]
    values["total"] = sum(values.values())
    return values
