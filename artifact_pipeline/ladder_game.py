"""Play one full cribbage game between two strength-ladder players (#263).

A player is a discard rule plus a pegging policy. The game follows cribbage
counting order and stops the moment either player reaches the target: his
heels at the cut, then each pegging action (a play scores all its points
together, a pair and 31 or a play and the last card), then Pone's hand,
Dealer's hand and Dealer's crib, each counted whole. The winner's final score
can therefore pass the target by the points of the count that reached it. Pegging uses the published rank-only rules in
`pegging.py` step by step, so the policies see exactly the views they see in
table generation and measurement. Hands and cribs are scored by the legacy
simulator's `score_hand_and_starter`, which the play and crib pipelines
already rely on.

Every random stream is derived from the game seed, the hand number and the
seat's role for that hand, never from which player sits there. Two games on
one seed with the players' seats swapped therefore see the same deals, which
is what the paired match in a later module relies on.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Mapping, Protocol, Sequence

from artifact_pipeline.adapter import Card, score_hand_and_starter
from artifact_pipeline.generate_play_table import PHYSICAL_DECK
from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    ROLES,
    PeggingPolicy,
    PeggingState,
    PolicyView,
    _empty_points,
    _play_rank,
    _say_go,
    _stable_seed,
    rank_count,
)

TARGET_SCORE = 121
HEELS_POINTS = 2
JACK_RANK = 10

PhysicalCard = tuple[int, int]
Split = tuple[tuple[PhysicalCard, ...], tuple[PhysicalCard, ...]]


class DiscardRule(Protocol):  # pylint: disable=too-few-public-methods
    """Choose four cards to keep and two to discard from six dealt cards."""

    def select_discard(
        self, role: str, dealt: Sequence[PhysicalCard], rng: random.Random
    ) -> Split:
        """Return (kept four, discarded two) for the given seat."""


@dataclass(frozen=True)
class LadderPlayer:
    """One rung on the strength ladder: a discard rule plus a pegging policy."""

    name: str
    discard_rule: DiscardRule
    pegging_policy: PeggingPolicy
    description: str = ""


class RandomDiscardRule:  # pylint: disable=too-few-public-methods
    """Keep four of the six dealt cards, all 15 choices equally likely."""

    def select_discard(
        self, role: str, dealt: Sequence[PhysicalCard], rng: random.Random
    ) -> Split:
        """Return a uniformly random split of the dealt cards."""
        del role
        kept_indices = set(rng.sample(range(len(dealt)), 4))
        kept = tuple(card for i, card in enumerate(dealt) if i in kept_indices)
        discarded = tuple(card for i, card in enumerate(dealt) if i not in kept_indices)
        return kept, discarded


class RandomPeggingPolicy:  # pylint: disable=too-few-public-methods
    """Play a uniformly chosen playable card, so duplicate ranks weigh more."""

    def select_rank(self, view: PolicyView, rng: random.Random) -> int:
        """Return the rank of a uniformly chosen playable card."""
        playable = [
            rank for rank in view.own_remaining if view.count + rank_count(rank) <= 31
        ]
        return rng.choice(playable)


def checked_split(role: str, dealt: Sequence[PhysicalCard], split: Split) -> Split:
    """Reject a discard that is not four kept and two discarded dealt cards."""
    kept, discarded = split
    if (
        len(kept) != 4
        or len(discarded) != 2
        or sorted((*kept, *discarded)) != sorted(dealt)
    ):
        raise ValueError(f"Invalid {role} discard {split} from {tuple(dealt)}")
    return split


def score_cards(
    cards: Sequence[PhysicalCard], starter: PhysicalCard, is_crib: bool
) -> int:
    """Score four physical cards with the starter, as a hand or as the crib."""
    return int(
        score_hand_and_starter(
            [Card(rank, suit) for rank, suit in cards],
            Card(*starter),
            is_crib=is_crib,
        )
    )


def play_pegging_to_target(
    kept_ranks: Mapping[str, Sequence[int]],
    policies: Mapping[str, PeggingPolicy],
    rng_by_role: Mapping[str, random.Random],
    scores_before: Mapping[str, int],
    target_score: int,
) -> tuple[str | None, dict[str, int]]:
    """Peg one hand, stopping after the first action that reaches the target.

    Returns the winning role (or None) and the points each role pegged; a
    play's points, including a last-card point, count together.
    """
    state = PeggingState(hands={role: sorted(kept_ranks[role]) for role in ROLES})
    points = {role: _empty_points() for role in ROLES}

    def pegged(role: str) -> int:
        return int(sum(points[role].values()))

    def winner() -> str | None:
        reached = [r for r in ROLES if scores_before[r] + pegged(r) >= target_score]
        return reached[0] if reached else None

    finished = False
    while not finished and winner() is None:
        view = state.view()
        if not view.legal_ranks:
            _say_go(state, points)
        else:
            selected = policies[view.role].select_rank(view, rng_by_role[view.role])
            finished = _play_rank(state, selected, points)
    return winner(), {role: pegged(role) for role in ROLES}


def deal_hand(
    rng: random.Random,
) -> tuple[tuple[PhysicalCard, ...], tuple[PhysicalCard, ...], PhysicalCard]:
    """Deal six cards to Pone, six to Dealer, and the starter."""
    cards = rng.sample(PHYSICAL_DECK, 13)
    return tuple(cards[:6]), tuple(cards[6:12]), cards[12]


@dataclass(frozen=True)
class GameOutcome:
    """Final scores of one game, by the seat each player started in.

    Pegging totals are play points only; his heels counts in the score but
    not in pegging.
    """

    first_pone_score: int
    first_dealer_score: int
    first_pone_pegging: int
    first_dealer_pegging: int
    hands_played: int

    @property
    def first_pone_won(self) -> bool:
        """Return whether the player who was Pone on the first hand won."""
        return self.first_pone_score > self.first_dealer_score


def _deal_and_discard(
    seats: tuple[LadderPlayer, LadderPlayer],
    seat_of: Mapping[str, int],
    game_seed: int,
    hand_index: int,
) -> tuple[dict[str, Split], PhysicalCard]:
    pone_dealt, dealer_dealt, starter = deal_hand(
        random.Random(_stable_seed(game_seed, "deal", hand_index))
    )
    dealt = {PONE: pone_dealt, DEALER: dealer_dealt}
    splits = {}
    for role in ROLES:
        rng = random.Random(_stable_seed(game_seed, "discard", hand_index, role))
        rule = seats[seat_of[role]].discard_rule
        splits[role] = checked_split(
            role, dealt[role], rule.select_discard(role, dealt[role], rng)
        )
    return splits, starter


def _pegging_streams(game_seed: int, hand_index: int) -> dict[str, random.Random]:
    return {
        role: random.Random(_stable_seed(game_seed, "peg", hand_index, role))
        for role in ROLES
    }


def play_game(
    first_pone: LadderPlayer,
    first_dealer: LadderPlayer,
    game_seed: int,
    target_score: int = TARGET_SCORE,
) -> GameOutcome:
    """Play one game to target_score; the deal alternates every hand."""
    seats = (first_pone, first_dealer)
    scores = [0, 0]
    pegging = [0, 0]
    hand_index = 0
    while True:
        seat_of = {PONE: hand_index % 2, DEALER: 1 - hand_index % 2}
        splits, starter = _deal_and_discard(seats, seat_of, game_seed, hand_index)
        hand_index += 1
        if starter[0] == JACK_RANK:
            scores[seat_of[DEALER]] += HEELS_POINTS
        _, pegged = play_pegging_to_target(
            {role: [card[0] for card in splits[role][0]] for role in ROLES},
            {role: seats[seat_of[role]].pegging_policy for role in ROLES},
            _pegging_streams(game_seed, hand_index - 1),
            {role: scores[seat_of[role]] for role in ROLES},
            target_score,
        )
        for role in ROLES:
            scores[seat_of[role]] += pegged[role]
            pegging[seat_of[role]] += pegged[role]
        # Pone's hand, then Dealer's hand, then the crib, stopping at the
        # first count that reaches the target.
        for role, cards, is_crib in (
            (PONE, splits[PONE][0], False),
            (DEALER, splits[DEALER][0], False),
            (DEALER, splits[PONE][1] + splits[DEALER][1], True),
        ):
            if max(scores) >= target_score:
                break
            scores[seat_of[role]] += score_cards(cards, starter, is_crib)
        if max(scores) >= target_score:
            return GameOutcome(scores[0], scores[1], pegging[0], pegging[1], hand_index)
