# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations
import sys
import random
import time
from multiprocessing import Process, Manager, Lock
import math
import argparse
import os
from runstats import Statistics  # type: ignore
from statistics import NormalDist
import itertools
from functools import cache
from collections import Counter
from typing import (
    Callable,
    Optional,
    Sequence,
    NewType,
    List,
    Dict,
    Tuple,
    Literal,
    NamedTuple,
    Union,
    Set,
)
from enum import Enum
from math import comb, hypot
from diskcache import Cache  # type: ignore
import shelve


MAX_CARD_COUNTING_VALUE = 10


def index_count(index):
    return min(index + 1, MAX_CARD_COUNTING_VALUE)


class Index:
    """A French playing card index"""

    indices = "A23456789TJQK"

    def __init__(self, index):
        self.index = index

    def __str__(self):
        return f"{Index.indices[self.index]}"


DECK_INDEX_COUNT: int = len(Index.indices)


class Card:
    """A French playing card"""

    suits = "♣♦♥♠"
    english_suits = "CDHS"

    def __init__(self, index, suit):
        self.index = index
        self.suit = suit
        self.count = index_count(index)
        self.str = f"{Index.indices[index]}{Card.suits[suit]}"

    @classmethod
    def from_string(cls, specifier: str) -> Card:
        if len(specifier) < 2:
            raise ValueError(f"Invalid card specifier: {specifier}")

        indices_index: int = Index.indices.find(specifier[0].capitalize())
        suits_index: int = max(
            Card.english_suits.find(specifier[1].capitalize()),
            Card.suits.find(specifier[1]),
        )
        if indices_index == -1 or suits_index == -1:
            raise ValueError(f"Invalid card specifier: {specifier}")

        return Card(indices_index, suits_index)

    def __eq__(self, value):
        return self.index == value.index and self.suit == value.suit

    def __lt__(self, other):
        return self.index < other.index or (
            self.index == other.index and self.suit < other.suit
        )

    def __hash__(self):
        return hash((self.index, self.suit))

    def __str__(self):
        return self.str

    def __repr__(self):
        return f"Card({self.index}, {self.suit})"


DECK_SUIT_COUNT = len(Card.suits)


def parse_cards(specifier: str) -> List[Card]:
    return [
        Card.from_string(card_specifier)
        for card_specifier in (specifier.split(",") if specifier else [])
    ]


class Go:
    """A 'Go' Cribbage play action"""

    STR = "Go"

    def __init__(self):
        self.index = None

    def __str__(self):
        return Go.STR

    def __repr__(self):
        return f"Go()"


PlayAction = Union[Card, Go]


def parse_play_action(specifier: str) -> PlayAction:
    return Go() if specifier.lower() == Go.STR.lower() else Card.from_string(specifier)


def parse_play_actions(specifier: str) -> List[PlayAction]:
    return [
        parse_play_action(play_action_specifier)
        for play_action_specifier in (specifier.split(",") if specifier else [])
    ]


class IndexHand:
    """A hand of Indexes"""

    def __init__(self, values):
        self.values = values

    @classmethod
    def from_values(cls, values):
        return IndexHand([Index(index_value) for index_value in values])

    def __str__(self):
        return f"[{','.join([str(value) for value in self.values])}]"


class Hand:
    """A hand of Cards"""

    def __init__(self, cards):
        self.cards = cards

    def __str__(self):
        return f"[{','.join([str(card) for card in self.cards])}]"


def get_player_name(player_number):
    if player_number == 0:
        return "Pone"
    else:
        return "Dealer"


Points = NewType("Points", int)
PAIR_POINTS: Points = Points(2)
FIFTEENS_POINTS: Points = Points(2)

PlayCount = NewType("PlayCount", int)
FIFTEEN_COUNT: PlayCount = PlayCount(15)


KEPT_CARDS_LEN = 4


@cache
def cached_fifteens_points(sorted_hand_plus_starter_counts):
    return FIFTEENS_POINTS * sum(
        map(
            lambda subset: sum(subset) == FIFTEEN_COUNT,
            itertools.chain.from_iterable(
                itertools.combinations(sorted_hand_plus_starter_counts, subset_size)
                for subset_size in range(2, KEPT_CARDS_LEN + 2)
            ),
        )
    )


def fifteens_points(hand_plus_starter_cards):
    sorted_hand_plus_starter_counts = tuple(
        sorted([c.count for c in hand_plus_starter_cards])
    )
    return cached_fifteens_points(sorted_hand_plus_starter_counts)


@cache
def pairs_points(sorted_hand_plus_starter_indices):
    return PAIR_POINTS * sum(
        map(
            lambda indices: indices[0] == indices[1],
            itertools.combinations(sorted_hand_plus_starter_indices, 2),
        )
    )


def runs_points_of_length(sorted_hand_plus_starter_indices, run_length):
    return sum(
        map(
            lambda length_subset: run_length
            * all(
                map(
                    lambda index_pair: index_pair[0] + 1 == index_pair[1],
                    zip(length_subset, length_subset[1:]),
                )
            ),
            itertools.combinations(sorted_hand_plus_starter_indices, run_length),
        )
    )


@cache
def runs_points(sorted_hand_plus_starter_indices):
    five_run_points = runs_points_of_length(sorted_hand_plus_starter_indices, 5)
    if five_run_points:
        return five_run_points

    four_run_points = runs_points_of_length(sorted_hand_plus_starter_indices, 4)
    if four_run_points:
        return four_run_points

    return runs_points_of_length(sorted_hand_plus_starter_indices, 3)


def pairs_plus_runs_points(hand_plus_starter_cards):
    sorted_hand_plus_starter_indices = tuple(
        sorted([c.index for c in hand_plus_starter_cards])
    )
    return pairs_points(sorted_hand_plus_starter_indices) + runs_points(
        sorted_hand_plus_starter_indices
    )


def flush_points(kept_hand, starter, is_crib=False):
    kept_hand_suits = [c.suit for c in kept_hand]
    for kept_card_suit in kept_hand_suits:
        if kept_card_suit != kept_hand_suits[0]:
            return 0

    if starter.suit == kept_hand_suits[0]:
        return 5

    return 4 if not is_crib else 0


JACK_INDEX = 10


def nobs_points(kept_hand, starter):
    for kept_card in kept_hand:
        if kept_card.index == JACK_INDEX and kept_card.suit == starter.suit:
            return 1

    return 0


@cache
def cached_pairs_runs_and_fifteens_points(sorted_kept_indices):
    return (
        pairs_points(sorted_kept_indices)
        + runs_points(sorted_kept_indices)
        + cached_fifteens_points(
            tuple(index_count(index) for index in sorted_kept_indices)
        )
    )


def pairs_runs_and_fifteens_points(kept_hand):
    return cached_pairs_runs_and_fifteens_points(
        tuple(sorted([card.index for card in kept_hand]))
    )


def score_hand_and_starter(kept_hand, starter, is_crib=False):
    hand_plus_starter_cards = [*kept_hand, starter]
    return (
        pairs_runs_and_fifteens_points(hand_plus_starter_cards)
        + flush_points(kept_hand, starter, is_crib=is_crib)
        + nobs_points(kept_hand, starter)
    )


def score_hand(kept_hand):
    return pairs_runs_and_fifteens_points(kept_hand) + flush_points(
        kept_hand, starter=None
    )


def formatted_game_count(games_simulated, total_games_to_be_simulated):
    return f"n = {games_simulated:{int(math.log10(total_games_to_be_simulated)) + 1}}"


def get_z_statistic(confidence_level):
    return NormalDist().inv_cdf(1 - (1 - confidence_level / 100) / 2)


def get_stddev_of_mean(statistics):
    if len(statistics) == 1:
        return None

    return statistics.stddev() / math.sqrt(len(statistics))


def get_confidence_interval(statistics, confidence_level):
    if len(statistics) == 1:
        return f"{statistics.mean():+10.5f}"

    return f"{statistics.mean():+10.5f} ± {get_z_statistic(confidence_level) * get_stddev_of_mean(statistics):8.5f}"


GamePoints = NewType("GamePoints", int)
NextAction = Tuple[Tuple[Card, ...], Optional[Card]]


def statistics_push(
    statistics_by_next_action: Dict[NextAction, Statistics],
    key: NextAction,
    value: Union[Points, Wins, GamePoints, bool],
):
    if key not in statistics_by_next_action:
        statistics_by_next_action[key] = Statistics()
    statistics_by_next_action[key].push(value)


# TODO: replace repeated constant strings with constants or Enum
PlayersStatistic = Literal[
    "first_pone_play",
    "first_pone_hand",
    "first_pone_crib",
    "first_pone_total_points",
    "first_pone_game_points",
    "first_pone_wins",
    "first_dealer_play",
    "first_dealer_hand",
    "first_dealer_crib",
    "first_dealer_total_points",
    "first_dealer_game_points",
    "first_dealer_wins",
    "first_pone_minus_first_dealer_play",
    "first_pone_minus_first_dealer_hand",
    "first_pone_minus_first_dealer_crib",
    "first_pone_minus_first_dealer_total_points",
    "first_pone_minus_first_dealer_game_points",
]


def statistics_dict_add(
    sum_stats_by_next_action_by_type: Dict[
        NextAction, Dict[PlayersStatistic, Statistics]
    ],
    player_statistic_type: PlayersStatistic,
    addend_stats_by_next_action: Dict[NextAction, Statistics],
):
    for next_action, addend_stats in addend_stats_by_next_action.items():
        if next_action in sum_stats_by_next_action_by_type:
            new_sum_stats_for_keep = sum_stats_by_next_action_by_type[next_action]
        else:
            new_sum_stats_for_keep = {
                "first_pone_play": Statistics(),
                "first_pone_hand": Statistics(),
                "first_pone_crib": Statistics(),
                "first_pone_total_points": Statistics(),
                "first_pone_game_points": Statistics(),
                "first_pone_wins": Statistics(),
                "first_dealer_play": Statistics(),
                "first_dealer_hand": Statistics(),
                "first_dealer_crib": Statistics(),
                "first_dealer_total_points": Statistics(),
                "first_dealer_game_points": Statistics(),
                "first_dealer_wins": Statistics(),
                "first_pone_minus_first_dealer_play": Statistics(),
                "first_pone_minus_first_dealer_hand": Statistics(),
                "first_pone_minus_first_dealer_crib": Statistics(),
                "first_pone_minus_first_dealer_total_points": Statistics(),
                "first_pone_minus_first_dealer_game_points": Statistics(),
            }

        new_sum_stats_for_keep[player_statistic_type] += addend_stats
        sum_stats_by_next_action_by_type[next_action] = new_sum_stats_for_keep


DECK_CARD_COUNT: int = DECK_INDEX_COUNT * DECK_SUIT_COUNT
DECK_LIST = [
    Card(number % DECK_INDEX_COUNT, number // DECK_INDEX_COUNT)
    for number in range(DECK_CARD_COUNT)
]
DECK_SET = set(DECK_LIST)


@cache
def cached_get_current_play_run_length(current_play_play_indices_tuple):
    for run_length in reversed(range(3, len(current_play_play_indices_tuple) + 1)):
        sorted_recent_play_indices = sorted(
            [index for index in current_play_play_indices_tuple[-run_length:]]
        )
        adjacent_index_count = 0
        for play_index in range(run_length - 1):
            diff_with_next = (
                sorted_recent_play_indices[play_index + 1]
                - sorted_recent_play_indices[play_index]
            )
            if diff_with_next == 1:
                adjacent_index_count += 1
        if adjacent_index_count == run_length - 1:
            return run_length

    return 0


PlayTo31 = NewType("PlayTo31", List[PlayAction])


def get_current_play_run_length(current_play_to_31_cards: Sequence[Card]):
    return cached_get_current_play_run_length(
        tuple([card.index for card in current_play_to_31_cards])
    )


PlayableCardIndex = NewType("PlayableCardIndex", int)
PlaySelector = Callable[[Sequence[Card], PlayCount, Sequence[Card]], PlayableCardIndex]
START_OF_PLAY_COUNT: PlayCount = PlayCount(0)


Player = Literal[0, 1]
MAX_SCORE: Points = Points(121)


class GameScore(NamedTuple):
    first_pone_initial: Points
    first_pone_play: Points
    first_pone_hand: Points
    first_pone_crib: Points
    first_dealer_initial: Points
    first_dealer_play: Points
    first_dealer_hand: Points
    first_dealer_crib: Points

    @property
    def pone_total(self) -> Points:
        return Points(
            self.first_pone_initial
            + self.first_pone_play
            + self.first_pone_hand
            + self.first_pone_crib
        )

    @property
    def dealer_total(self) -> Points:
        return Points(
            self.first_dealer_initial
            + self.first_dealer_play
            + self.first_dealer_hand
            + self.first_dealer_crib
        )

    def __str__(self) -> str:
        return f"{self.pone_total}-{self.dealer_total}"

    def __repr__(self) -> str:
        return f"GameScore({self.first_pone_initial}, {self.first_pone_play}, {self.first_pone_hand}, {self.first_pone_crib}, {self.first_dealer_initial}, {self.first_dealer_play}, {self.first_dealer_hand}, {self.first_dealer_crib})"


class GamePlayer(Enum):
    FIRST_PONE = 0
    FIRST_DEALER = 1


class PointsType(Enum):
    PLAY = 0
    HAND = 1
    CRIB = 2


def add_to_game_score(
    game_score: GameScore,
    game_player: GamePlayer,
    points_type: PointsType,
    points: Points,
) -> GameScore:
    # TODO: shorten up this code - very likely unnecessarily verbose
    current_game_player_score = (
        (
            game_score.first_pone_initial
            + game_score.first_pone_play
            + game_score.first_pone_hand
            + game_score.first_pone_crib
        )
        if game_player == GamePlayer.FIRST_PONE
        else game_score.first_dealer_initial
        + game_score.first_dealer_play
        + game_score.first_dealer_hand
        + game_score.first_dealer_crib
    )
    maximum_current_game_player_points = MAX_SCORE - current_game_player_score
    scorable_points = min(points, maximum_current_game_player_points)

    return GameScore(
        game_score.first_pone_initial,
        Points(
            game_score.first_pone_play
            + (
                scorable_points
                if game_player == GamePlayer.FIRST_PONE
                and points_type == PointsType.PLAY
                else Points(0)
            ),
        ),
        Points(
            game_score.first_pone_hand
            + (
                scorable_points
                if game_player == GamePlayer.FIRST_PONE
                and points_type == PointsType.HAND
                else Points(0)
            ),
        ),
        Points(
            game_score.first_pone_crib
            + (
                scorable_points
                if game_player == GamePlayer.FIRST_PONE
                and points_type == PointsType.CRIB
                else Points(0)
            ),
        ),
        game_score.first_dealer_initial,
        Points(
            game_score.first_dealer_play
            + (
                scorable_points
                if game_player == GamePlayer.FIRST_DEALER
                and points_type == PointsType.PLAY
                else Points(0)
            ),
        ),
        Points(
            game_score.first_dealer_hand
            + (
                scorable_points
                if game_player == GamePlayer.FIRST_DEALER
                and points_type == PointsType.HAND
                else Points(0)
            ),
        ),
        Points(
            game_score.first_dealer_crib
            + (
                scorable_points
                if game_player == GamePlayer.FIRST_DEALER
                and points_type == PointsType.CRIB
                else Points(0)
            ),
        ),
    )


def game_over(game_score: GameScore) -> bool:
    return (
        max(
            game_score.first_pone_initial
            + game_score.first_pone_play
            + game_score.first_pone_hand
            + game_score.first_pone_crib,
            game_score.first_dealer_initial
            + game_score.first_dealer_play
            + game_score.first_dealer_hand
            + game_score.first_dealer_crib,
        )
        >= MAX_SCORE
    )


NIBS_SCORE_POINTS: Points = Points(2)
DOUBLE_PAIRS_ROYALE_POINTS: Points = Points(12)
PAIRS_ROYALE_POINTS: Points = Points(6)
THIRTY_ONE_COUNT_POINTS: Points = Points(1)
GO_POINTS: Points = Points(1)
LAST_CARD_POINTS: Points = Points(1)
PONE: Player = 0
DEALER: Player = 1


CardCount = NewType("CardCount", int)
DEALT_CARDS_LEN: CardCount = CardCount(6)


class GameSimulationResult(NamedTuple):
    kept_cards: Tuple[Card, ...]
    score: GameScore
    start_of_hand_scores: List[StartOfHandScore]
    non_kept_card_kept_or_non_kept_initial_played_card_played: bool


def create_play_to_31() -> PlayTo31:
    played_cards: List[PlayAction] = []
    return PlayTo31(played_cards)


def get_game_player(player_to_play: Player, hand: int) -> GamePlayer:
    return GamePlayer((player_to_play + hand) % 2)


def get_play_to_31_cards(play_to_31: PlayTo31) -> Sequence[Card]:
    return [card for card in play_to_31 if isinstance(card, Card)]


class StartOfHandScore(NamedTuple):
    first_pone_points: Points
    first_dealer_points: Points
    dealer_is_first_pone: bool

    def __repr__(self) -> str:
        return f"StartOfHandScore({self.first_pone_points}, {self.first_dealer_points}, {self.dealer_is_first_pone})"

    def __str__(self) -> str:
        return f"{self.first_pone_points}{'[D]' if self.dealer_is_first_pone else ''}-{self.first_dealer_points}{'' if self.dealer_is_first_pone else '[D]'}"


def simulate_game(
    first_pone_dealt_cards: List[Card],
    first_dealer_dealt_cards: List[Card],
    deck_less_fixed_cards: Sequence[Card],
    first_pone_kept_cards: List[Card],
    first_dealer_kept_cards: List[Card],
    initial_starter: Optional[Card],
    maximum_hands_per_game: int,
    first_pone_select_kept_cards,
    first_pone_discard_based_on_simulations: Optional[int],
    first_pone_select_each_possible_kept_hand: bool,
    first_dealer_select_kept_cards,
    first_dealer_discard_based_on_simulations: Optional[int],
    first_dealer_select_each_possible_kept_hand: bool,
    first_pone_select_play,
    first_pone_play_based_on_simulations: Optional[int],
    first_dealer_select_play,
    first_dealer_play_based_on_simulations: Optional[int],
    estimate_incomplete_game_wins_and_game_points: bool,
    hide_first_pone_hands: bool,
    hide_first_dealer_hands: bool,
    first_pone_dealt_cards_possible_keeps_cycle,  # type: itertools.cycle[Tuple[Card, ...]]
    first_dealer_dealt_cards_possible_keeps_cycle,  # type: itertools.cycle[Tuple[Card, ...]]
    dropped_keeps,
    initial_first_pone_score: Points,
    initial_first_dealer_score: Points,
    post_initial_play: Optional[Card],
    initial_play_actions: List[PlayAction],
    hide_play_actions: bool,
) -> GameSimulationResult:
    assert (
        len(set(first_pone_dealt_cards + first_pone_kept_cards)) <= DEALT_CARDS_LEN
    ), f"No more than {DEALT_CARDS_LEN} specified first pone dealt or kept cards expected but {len(set(first_pone_dealt_cards + first_pone_kept_cards))} ({Hand(set(first_pone_dealt_cards + first_pone_kept_cards))}) specified"
    assert (
        len(set(first_dealer_dealt_cards + first_dealer_kept_cards)) <= DEALT_CARDS_LEN
    ), f"No more than {DEALT_CARDS_LEN} specified first dealer dealt or kept cards expected but {len(set(first_dealer_dealt_cards + first_dealer_kept_cards))} ({Hand(set(first_dealer_dealt_cards + first_dealer_kept_cards))}) specified"

    first_kept_pone_hand: List[Card] = []
    first_kept_dealer_hand: List[Card] = []
    game_score: GameScore = GameScore(
        initial_first_pone_score,
        Points(0),
        Points(0),
        Points(0),
        initial_first_dealer_score,
        Points(0),
        Points(0),
        Points(0),
    )
    non_kept_initial_played_card_played: bool = False
    not_all_kept_cards_in_kept_hand: bool = False
    post_initial_play_is_illegal: bool = False
    start_of_hand_scores: List[StartOfHandScore] = []
    for hand in range(maximum_hands_per_game):
        pone_is_first_pone: bool = hand % 2 == 0
        pone_is_first_dealer: bool = not pone_is_first_pone
        dealer_is_first_dealer: bool = pone_is_first_pone
        dealer_is_first_pone: bool = not dealer_is_first_dealer

        start_of_hand_scores.append(
            StartOfHandScore(
                game_score.pone_total, game_score.dealer_total, dealer_is_first_pone
            )
        )

        is_first_simulation_hand: bool = not hand
        if is_first_simulation_hand and (
            first_pone_dealt_cards
            or first_pone_kept_cards
            or first_dealer_dealt_cards
            or first_dealer_kept_cards
        ):
            pone_dealt_or_kept_cards = set(
                (
                    first_pone_dealt_cards
                    if pone_is_first_pone
                    else first_dealer_dealt_cards
                )
                + (
                    first_pone_kept_cards
                    if pone_is_first_pone
                    else first_dealer_kept_cards
                )
            )
            assert (
                len(pone_dealt_or_kept_cards) <= DEALT_CARDS_LEN
            ), f"No more than {DEALT_CARDS_LEN} specified dealt or kept pone cards expected but {len(pone_dealt_or_kept_cards)} specified"

            dealer_dealt_or_kept_cards = set(
                (
                    first_dealer_dealt_cards
                    if dealer_is_first_dealer
                    else first_pone_dealt_cards
                )
                + (
                    first_dealer_kept_cards
                    if dealer_is_first_dealer
                    else first_pone_kept_cards
                )
            )
            assert (
                len(dealer_dealt_or_kept_cards) <= DEALT_CARDS_LEN
            ), f"No more than {DEALT_CARDS_LEN} specified dealt or kept dealer cards expected but {len(dealer_dealt_or_kept_cards)} specified"

            random_hand_cards = random.sample(
                deck_less_fixed_cards,
                2 * DEALT_CARDS_LEN
                - len(pone_dealt_or_kept_cards | dealer_dealt_or_kept_cards),
            )
            dealt_hands = [
                [
                    *pone_dealt_or_kept_cards,
                    *random_hand_cards[
                        0 : (DEALT_CARDS_LEN - len(pone_dealt_or_kept_cards))
                    ],
                ],
                [
                    *dealer_dealt_or_kept_cards,
                    *random_hand_cards[
                        (DEALT_CARDS_LEN - len(pone_dealt_or_kept_cards)) :
                    ],
                ],
            ]
        else:
            random_hand_cards = random.sample(
                deck_less_fixed_cards, DEALT_CARDS_LEN * 2
            )
            dealt_hands = [
                random_hand_cards[0:DEALT_CARDS_LEN],
                random_hand_cards[DEALT_CARDS_LEN:],
            ]

        assert (
            len(dealt_hands[0]) == DEALT_CARDS_LEN
            and len(dealt_hands[1]) == DEALT_CARDS_LEN
        ), f"{DEALT_CARDS_LEN} dealt cards expected in each hand but {len(dealt_hands[0])} and {len(dealt_hands[1])} actually dealt"

        show_pone_hand: bool = (pone_is_first_pone and not hide_first_pone_hands) or (
            pone_is_first_dealer and not hide_first_dealer_hands
        )
        if show_pone_hand:
            print(
                f"{get_player_name(0):6} dealt {Hand(dealt_hands[0])} (sorted: {Hand(sorted(dealt_hands[0], reverse=True))})"
            )
        show_dealer_hand: bool = (
            dealer_is_first_dealer and not hide_first_dealer_hands
        ) or (dealer_is_first_pone and not hide_first_pone_hands)
        if show_dealer_hand:
            print(
                f"{get_player_name(1):6} dealt {Hand(dealt_hands[1])} (sorted: {Hand(sorted(dealt_hands[1], reverse=True))})"
            )
        deck_less_dealt_cards = list(
            set(deck_less_fixed_cards).difference(set(random_hand_cards))
        )

        pone_kept_cards: List[Card] = (
            first_pone_kept_cards if pone_is_first_pone else first_dealer_kept_cards
        )
        if is_first_simulation_hand and pone_kept_cards:
            if len(pone_kept_cards) == KEPT_CARDS_LEN:
                kept_pone_hand = [
                    card for card in dealt_hands[0] if card in pone_kept_cards
                ]
            else:
                kept_pone_hand = first_pone_select_kept_cards(dealt_hands[0])
                if not hide_first_pone_hands:
                    print(
                        f"{get_player_name(0):6} keeps {Hand(kept_pone_hand)} (sorted: {Hand(sorted(kept_pone_hand, reverse=True))})"
                    )
                if not all(
                    pone_kept_card in kept_pone_hand
                    for pone_kept_card in pone_kept_cards
                ):
                    if not hide_first_pone_hands:
                        print(
                            f"...but then {Hand(set(pone_kept_cards).difference(kept_pone_hand))} would not be kept by pone"
                        )
                    not_all_kept_cards_in_kept_hand = True
                    break
        elif not (
            is_first_simulation_hand and first_pone_select_each_possible_kept_hand
        ):
            if (
                first_pone_discard_based_on_simulations
                and pone_is_first_pone
                or first_dealer_discard_based_on_simulations
                and pone_is_first_dealer
            ):
                if first_pone_discard_based_on_simulations and pone_is_first_pone:
                    simulated_hand_count = first_pone_discard_based_on_simulations
                elif first_dealer_discard_based_on_simulations and pone_is_first_dealer:
                    simulated_hand_count = first_dealer_discard_based_on_simulations
                else:
                    raise AssertionError()

                kept_pone_hand = player_select_kept_cards_based_on_simulation(
                    simulated_hand_count,
                    hide_first_pone_hands
                    if pone_is_first_pone
                    else hide_first_dealer_hands,
                    game_score,
                    dealt_hands[0],
                    PONE,
                    estimate_incomplete_game_wins_and_game_points,
                )
            else:
                kept_pone_hand = (
                    first_pone_select_kept_cards(dealt_hands[0])
                    if pone_is_first_pone
                    else first_dealer_select_kept_cards(dealt_hands[0])
                )
                if (
                    first_pone_select_kept_cards == keep_user_selected
                    and pone_is_first_pone
                    or first_dealer_select_kept_cards == keep_user_selected
                    and pone_is_first_dealer
                ):
                    static_strategy_pone_kept_cards = (
                        BEST_STATIC_SELECT_PONE_KEPT_CARDS(dealt_hands[0])
                    )
                    if set(kept_pone_hand) != set(static_strategy_pone_kept_cards):
                        print(
                            f"(Static discard coach would have kept: {Hand(sorted(static_strategy_pone_kept_cards, reverse=True))})"
                        )
                    else:
                        print(
                            "(Static coach would have kept the same cards as user did.)"
                        )

                    dynamic_strategy_pone_kept_cards = (
                        player_select_kept_cards_based_on_simulation(
                            320,
                            hide_first_pone_hands
                            if pone_is_first_pone
                            else hide_first_dealer_hands,
                            game_score,
                            dealt_hands[0],
                            PONE,
                            estimate_incomplete_game_wins_and_game_points,
                        )
                    )
                    dynamic_and_static_pone_discard_coaches_agree = set(
                        static_strategy_pone_kept_cards
                    ) == set(dynamic_strategy_pone_kept_cards)
                    if set(kept_pone_hand) != set(dynamic_strategy_pone_kept_cards):
                        print(
                            f"(Dynamic discard coach {'agrees' if dynamic_and_static_pone_discard_coaches_agree else 'disagrees'} with static discard coach and {'also ' if dynamic_and_static_pone_discard_coaches_agree else ''}would have instead kept: {Hand(sorted(dynamic_strategy_pone_kept_cards, reverse=True))})"
                        )
                    else:
                        print(
                            "(Dynamic discard coach would have kept the same cards as user did.)"
                        )

        elif is_first_simulation_hand and first_pone_dealt_cards:
            optional_kept_pone_hand = None
            while (
                not optional_kept_pone_hand
                or tuple(optional_kept_pone_hand) in dropped_keeps
            ):
                optional_kept_pone_hand = list(
                    next(first_pone_dealt_cards_possible_keeps_cycle)
                )
            kept_pone_hand = first_kept_pone_hand = optional_kept_pone_hand
        else:
            raise ValueError(
                "Iterating through all possible kept hands not supported with non-fixed deals."
            )

        dealer_kept_cards: List[Card] = (
            first_dealer_kept_cards if dealer_is_first_dealer else first_pone_kept_cards
        )
        if is_first_simulation_hand and dealer_kept_cards:
            if len(dealer_kept_cards) == KEPT_CARDS_LEN:
                kept_dealer_hand = [
                    card for card in dealt_hands[1] if card in dealer_kept_cards
                ]
            else:
                kept_dealer_hand = first_dealer_select_kept_cards(dealt_hands[1])
                if not hide_first_dealer_hands:
                    print(
                        f"{get_player_name(1):6} would keep {Hand(kept_dealer_hand)} (sorted: {Hand(sorted(kept_dealer_hand, reverse=True))})"
                    )
                if not all(
                    dealer_kept_card in kept_dealer_hand
                    for dealer_kept_card in dealer_kept_cards
                ):
                    if not hide_first_dealer_hands:
                        print(
                            f"...but then {Hand(set(dealer_kept_cards).difference(kept_dealer_hand))} would not be kept by dealer"
                        )
                    not_all_kept_cards_in_kept_hand = True
                    break
        elif not (
            is_first_simulation_hand and first_dealer_select_each_possible_kept_hand
        ):
            if (
                first_dealer_discard_based_on_simulations
                and dealer_is_first_dealer
                or first_pone_discard_based_on_simulations
                and dealer_is_first_pone
            ):
                if first_dealer_discard_based_on_simulations and dealer_is_first_dealer:
                    simulated_hand_count = first_dealer_discard_based_on_simulations
                elif first_pone_discard_based_on_simulations and dealer_is_first_pone:
                    simulated_hand_count = first_pone_discard_based_on_simulations
                else:
                    raise AssertionError()

                kept_dealer_hand = player_select_kept_cards_based_on_simulation(
                    simulated_hand_count,
                    hide_first_dealer_hands
                    if dealer_is_first_dealer
                    else hide_first_pone_hands,
                    game_score,
                    dealt_hands[1],
                    DEALER,
                    estimate_incomplete_game_wins_and_game_points,
                )
            else:
                kept_dealer_hand = (
                    first_dealer_select_kept_cards(dealt_hands[1])
                    if dealer_is_first_dealer
                    else first_pone_select_kept_cards(dealt_hands[1])
                )
                if (
                    first_dealer_select_kept_cards == keep_user_selected
                    and dealer_is_first_dealer
                    or first_pone_select_kept_cards == keep_user_selected
                    and dealer_is_first_pone
                ):
                    static_strategy_dealer_kept_cards = (
                        BEST_STATIC_SELECT_DEALER_KEPT_CARDS(dealt_hands[1])
                    )
                    if set(kept_dealer_hand) != set(static_strategy_dealer_kept_cards):
                        print(
                            f"(Static discard coach would have instead kept: {Hand(sorted(static_strategy_dealer_kept_cards, reverse=True))}.)"
                        )
                    else:
                        print(
                            "(Static discard coach would have kept the same cards as user did.)"
                        )

                    dynamic_strategy_dealer_kept_cards = (
                        player_select_kept_cards_based_on_simulation(
                            320,
                            hide_first_dealer_hands
                            if dealer_is_first_dealer
                            else hide_first_pone_hands,
                            game_score,
                            dealt_hands[1],
                            DEALER,
                            estimate_incomplete_game_wins_and_game_points,
                        )
                    )
                    dynamic_and_static_discard_coaches_agree = set(
                        static_strategy_dealer_kept_cards
                    ) == set(dynamic_strategy_dealer_kept_cards)
                    if set(kept_dealer_hand) != set(dynamic_strategy_dealer_kept_cards):
                        print(
                            f"(Dynamic discard coach {'agrees' if dynamic_and_static_discard_coaches_agree else 'disagrees'} with static discard coach and {'also ' if dynamic_and_static_discard_coaches_agree else ''}would have instead kept: {Hand(sorted(dynamic_strategy_dealer_kept_cards, reverse=True))}.)"
                        )
                    else:
                        print(
                            "(Dynamic discard coach would have kept the same cards as user did.)"
                        )

        elif is_first_simulation_hand and first_dealer_dealt_cards:
            optional_kept_dealer_hand = None
            while (
                not optional_kept_dealer_hand
                or tuple(optional_kept_dealer_hand) in dropped_keeps
            ):
                optional_kept_dealer_hand = list(
                    next(first_dealer_dealt_cards_possible_keeps_cycle)
                )
            kept_dealer_hand = first_kept_dealer_hand = optional_kept_dealer_hand
        else:
            raise ValueError(
                "Iterating through all possible kept hands not supported with non-fixed deals."
            )

        kept_hands: List[Sequence[Card]] = [kept_pone_hand, kept_dealer_hand]
        hands = [list(kept_hand) for kept_hand in kept_hands]

        pone_discarded_cards = [
            card for card in dealt_hands[0] if card not in kept_hands[0]
        ]
        if show_pone_hand:
            print(f"{get_player_name(0):6} discarded {Hand(pone_discarded_cards)}")

        dealer_discarded_cards = [
            card for card in dealt_hands[1] if card not in kept_hands[1]
        ]
        if show_dealer_hand:
            print(f"{get_player_name(1):6} discarded {Hand(dealer_discarded_cards)}")

        if len(hands[0]) > KEPT_CARDS_LEN or len(hands[1]) > KEPT_CARDS_LEN:
            raise ValueError(
                f"Kept too many cards in one of {Hand(hands[0])} or {Hand(hands[1])}"
            )

        if show_pone_hand:
            print(f"{get_player_name(0):6} kept {Hand(hands[0])}")
        if show_dealer_hand:
            print(f"{get_player_name(1):6} kept {Hand(hands[1])}")

        starter = (
            initial_starter
            if is_first_simulation_hand and initial_starter
            else random.sample(deck_less_dealt_cards, 1)[0]
        )
        if not hide_play_actions:
            print(f"Cut/starter card is: {starter}")
        if starter.index == 10:
            dealer_game_player = GamePlayer((hand + 1) % 2)
            game_score = add_to_game_score(
                game_score, dealer_game_player, PointsType.PLAY, NIBS_SCORE_POINTS
            )
            if not hide_play_actions:
                print(f"His heels/nibs for 2 for {get_player_name(1)} [{game_score}]")
            if game_over(game_score):
                break

        player_to_play: Player = 0
        play_count: PlayCount = START_OF_PLAY_COUNT
        consecutive_go_count = 0
        most_recently_played_index = None
        most_recently_played_index_count = 0
        plays_to_31: List[PlayTo31] = [create_play_to_31()]
        remaining_initial_play_actions: List[PlayAction] = list(initial_play_actions)
        remaining_post_initial_play = post_initial_play
        while hands[0] or hands[1]:
            legal_play_actions: List[PlayAction] = [
                card
                for card in hands[player_to_play]
                if play_count + card.count <= THIRTY_ONE_COUNT
            ]
            if not legal_play_actions:
                legal_play_actions = [Go()]

            player_to_play_play: PlayAction

            first_pone_to_play = (
                player_to_play == 0
                and pone_is_first_pone
                or player_to_play == 1
                and dealer_is_first_pone
            )
            if len(legal_play_actions) > 1 and (
                first_pone_to_play
                and first_pone_play_based_on_simulations
                or not first_pone_to_play
                and first_dealer_play_based_on_simulations
            ):
                if first_pone_to_play and first_pone_play_based_on_simulations:
                    simulated_play_count = first_pone_play_based_on_simulations
                elif not first_pone_to_play and first_dealer_play_based_on_simulations:
                    simulated_play_count = first_dealer_play_based_on_simulations
                else:
                    raise AssertionError()

                player_to_play_play = play_based_on_simulation(
                    simulated_play_count,
                    True,
                    game_score,
                    first_pone_to_play,
                    dealt_hands[player_to_play],
                    kept_hands[player_to_play],
                    starter,
                    [
                        play_action
                        for play_to_31 in plays_to_31
                        for play_action in play_to_31
                    ],
                    player_to_play,
                    pone_is_first_pone,
                    estimate_incomplete_game_wins_and_game_points,
                )
            else:
                select_play = (
                    first_pone_select_play
                    if first_pone_to_play
                    else first_dealer_select_play
                )
                if (
                    is_first_simulation_hand
                    and (not remaining_initial_play_actions)
                    and remaining_post_initial_play
                ):
                    if remaining_post_initial_play not in hands[player_to_play]:
                        non_kept_initial_played_card_played = True
                        break
                    if (
                        play_count + remaining_post_initial_play.count
                        > THIRTY_ONE_COUNT
                    ):
                        post_initial_play_is_illegal = True
                        break
                    player_to_play_play = remaining_post_initial_play
                    remaining_post_initial_play = None
                elif is_first_simulation_hand and remaining_initial_play_actions:
                    player_to_play_play = remaining_initial_play_actions.pop(0)
                elif len(legal_play_actions) == 1 and select_play != play_user_selected:
                    player_to_play_play = legal_play_actions[0]
                elif (
                    len(legal_play_actions) == 1
                    and select_play == play_user_selected
                    and str(legal_play_actions[0]) == Go.STR
                ):
                    input(f"Press enter to say Go: ")
                    player_to_play_play = legal_play_actions[0]
                else:
                    player_to_play_play = legal_play_actions[
                        select_play(
                            legal_play_actions,
                            play_count,
                            get_play_to_31_cards(plays_to_31[-1]),
                        )
                    ]
                    if (
                        select_play == play_user_selected
                        and len(legal_play_actions) > 1
                    ):
                        static_strategy_player_to_play_play = legal_play_actions[
                            DEFAULT_SELECT_PLAY(
                                [
                                    playable_card
                                    for playable_card in legal_play_actions
                                    if isinstance(playable_card, Card)
                                ],
                                play_count,
                                get_play_to_31_cards(plays_to_31[-1]),
                            )
                        ]
                        if player_to_play_play != static_strategy_player_to_play_play:
                            print(
                                f"(Static play coach would have instead played: {static_strategy_player_to_play_play}.)"
                            )
                        else:
                            print(
                                "(Static play coach would have played the same card as user did.)"
                            )

                        dynamic_strategy_player_to_play_play = play_based_on_simulation(
                            1800,
                            False,
                            game_score,
                            first_pone_to_play,
                            dealt_hands[player_to_play],
                            kept_hands[player_to_play],
                            starter,
                            [
                                play_action
                                for play_to_31 in plays_to_31
                                for play_action in play_to_31
                            ],
                            player_to_play,
                            pone_is_first_pone,
                            estimate_incomplete_game_wins_and_game_points,
                        )
                        dynamic_and_static_play_coaches_agree = (
                            static_strategy_player_to_play_play
                            == dynamic_strategy_player_to_play_play
                        )
                        if player_to_play_play != dynamic_strategy_player_to_play_play:
                            print(
                                f"(Dynamic play coach {'agrees' if dynamic_and_static_play_coaches_agree else 'disagrees'} with static play coach and {'also ' if dynamic_and_static_play_coaches_agree else ''}would have instead played: {dynamic_strategy_player_to_play_play}.)"
                            )
                        else:
                            print(
                                "(Dynamic play coach would have played the same card as user did.)"
                            )

            plays_to_31[-1].append(player_to_play_play)

            if isinstance(player_to_play_play, Card):
                play_count += player_to_play_play.count
                if not hide_play_actions:
                    print(
                        f"{get_player_name(player_to_play):6} plays {player_to_play_play} for {play_count} ({';'.join([str(Hand(p)) for p in plays_to_31])})"
                    )
                hands[player_to_play].remove(player_to_play_play)

                # Pairs points
                if player_to_play_play.index == most_recently_played_index:
                    most_recently_played_index_count += 1
                    if most_recently_played_index_count == 4:
                        game_score = add_to_game_score(
                            game_score,
                            get_game_player(player_to_play, hand),
                            PointsType.PLAY,
                            DOUBLE_PAIRS_ROYALE_POINTS,
                        )
                        if not hide_play_actions:
                            print(
                                f"!Double pairs royale for {DOUBLE_PAIRS_ROYALE_POINTS} points for {get_player_name(player_to_play)}. [{game_score}]"
                            )
                        if game_over(game_score):
                            break
                    elif most_recently_played_index_count == 3:
                        game_score = add_to_game_score(
                            game_score,
                            get_game_player(player_to_play, hand),
                            PointsType.PLAY,
                            PAIRS_ROYALE_POINTS,
                        )
                        if not hide_play_actions:
                            print(
                                f"!Pairs royale for {PAIRS_ROYALE_POINTS} points for {get_player_name(player_to_play)}. [{game_score}]"
                            )
                        if game_over(game_score):
                            break
                    elif most_recently_played_index_count == 2:
                        game_score = add_to_game_score(
                            game_score,
                            get_game_player(player_to_play, hand),
                            PointsType.PLAY,
                            PAIR_POINTS,
                        )
                        if not hide_play_actions:
                            print(
                                f"!Pair for {PAIR_POINTS} points for {get_player_name(player_to_play)}. [{game_score}]"
                            )
                        if game_over(game_score):
                            break
                else:
                    most_recently_played_index = player_to_play_play.index
                    most_recently_played_index_count = 1

                # 15 and 31 count points
                if play_count == FIFTEEN_COUNT:
                    game_score = add_to_game_score(
                        game_score,
                        get_game_player(player_to_play, hand),
                        PointsType.PLAY,
                        FIFTEENS_POINTS,
                    )
                    if not hide_play_actions:
                        print(
                            f"!{FIFTEEN_COUNT} for {FIFTEENS_POINTS} points for {get_player_name(player_to_play)}. [{game_score}]"
                        )
                    if game_over(game_score):
                        break
                elif play_count == THIRTY_ONE_COUNT:
                    game_score = add_to_game_score(
                        game_score,
                        get_game_player(player_to_play, hand),
                        PointsType.PLAY,
                        THIRTY_ONE_COUNT_POINTS,
                    )
                    if not hide_play_actions:
                        print(
                            f"!{THIRTY_ONE_COUNT} for {THIRTY_ONE_COUNT_POINTS} point for {get_player_name(player_to_play)}. [{game_score}]"
                        )
                    if game_over(game_score):
                        break

                current_play_run_length = get_current_play_run_length(
                    get_play_to_31_cards(plays_to_31[-1])
                )
                if current_play_run_length:
                    game_score = add_to_game_score(
                        game_score,
                        get_game_player(player_to_play, hand),
                        PointsType.PLAY,
                        current_play_run_length,
                    )
                    if not hide_play_actions:
                        print(
                            f"!Run for {current_play_run_length} points for {get_player_name(player_to_play)}. [{game_score}]"
                        )
                    if game_over(game_score):
                        break

                consecutive_go_count = 0
            else:
                if not hide_play_actions:
                    print(f"{get_player_name(player_to_play):6} says 'Go'")

                consecutive_go_count += 1
                if consecutive_go_count == 2:
                    game_score = add_to_game_score(
                        game_score,
                        get_game_player(player_to_play, hand),
                        PointsType.PLAY,
                        GO_POINTS,
                    )
                    if not hide_play_actions:
                        print(
                            f"!Go for {GO_POINTS} point for {get_player_name(player_to_play)}. [{game_score}]"
                        )
                    if game_over(game_score):
                        break

                    if not hide_play_actions:
                        print(f"---resetting play count to {START_OF_PLAY_COUNT}---")
                    consecutive_go_count = 0
                    play_count = START_OF_PLAY_COUNT
                    plays_to_31.append(create_play_to_31())
                    most_recently_played_index = None
                    most_recently_played_index_count = 0

            player_to_play = 1 if player_to_play == 0 else 0

        if (
            not_all_kept_cards_in_kept_hand
            or non_kept_initial_played_card_played
            or post_initial_play_is_illegal
            or game_over(game_score)
        ):
            break

        # Last Card points
        last_player_to_play: Player = 1 if player_to_play == 0 else 0
        game_score = add_to_game_score(
            game_score,
            get_game_player(last_player_to_play, hand),
            PointsType.PLAY,
            LAST_CARD_POINTS,
        )
        if not hide_play_actions:
            print(
                f"!Last card for {LAST_CARD_POINTS} point for {get_player_name(last_player_to_play)} [{game_score}]."
            )
        if game_over(game_score):
            break

        pone_hand_points = score_hand_and_starter(kept_hands[0], starter)
        game_score = add_to_game_score(
            game_score, get_game_player(PONE, hand), PointsType.HAND, pone_hand_points
        )
        if not hide_play_actions:
            print(
                f"!{Hand(reversed(sorted(kept_hands[0])))} hand + starter {starter} scores {pone_hand_points:2} points for Pone.   [{game_score}]"
            )
        if game_over(game_score):
            break

        dealer_hand_points = score_hand_and_starter(kept_hands[1], starter)
        game_score = add_to_game_score(
            game_score,
            get_game_player(DEALER, hand),
            PointsType.HAND,
            dealer_hand_points,
        )
        if not hide_play_actions:
            print(
                f"!{Hand(reversed(sorted(kept_hands[1])))} hand + starter {starter} scores {dealer_hand_points:2} points for Dealer. [{game_score}]"
            )
        if game_over(game_score):
            break

        crib_cards = pone_discarded_cards + dealer_discarded_cards
        crib_points = score_hand_and_starter(crib_cards, starter, is_crib=True)
        game_score = add_to_game_score(
            game_score, get_game_player(DEALER, hand), PointsType.CRIB, crib_points
        )
        if not hide_play_actions:
            print(
                f"!{Hand(reversed(sorted(crib_cards)))} crib + starter {starter} scores {crib_points:2} points for Dealer. [{game_score}]"
            )
            print(
                f"+++ Game score is [{game_score}] for first pone and first dealer after {hand+1} hands played."
            )
            print()
        if game_over(game_score):
            break

    if (
        first_pone_dealt_cards
        and len(first_pone_dealt_cards) > 1
        and not first_pone_kept_cards
    ):
        kept_cards = tuple(first_kept_pone_hand)
    elif (
        first_dealer_dealt_cards
        and len(first_dealer_dealt_cards) > 1
        and not first_dealer_kept_cards
    ):
        kept_cards = tuple(first_kept_dealer_hand)
    else:
        kept_cards = tuple()

    return GameSimulationResult(
        kept_cards,
        game_score,
        start_of_hand_scores,
        not_all_kept_cards_in_kept_hand
        or non_kept_initial_played_card_played
        or post_initial_play_is_illegal,
    )


Skunks = NewType("Skunks", int)
TRIPLE_SKUNK_SCORE: Points = Points(30)
DOUBLE_SKUNK_SCORE: Points = Points(60)
SKUNK_SCORE: Points = Points(90)
TRIPLE_SKUNK: Skunks = Skunks(3)
DOUBLE_SKUNK: Skunks = Skunks(2)
SKUNK: Skunks = Skunks(1)


def get_skunks(score: Points) -> Skunks:
    if score <= TRIPLE_SKUNK_SCORE:
        return TRIPLE_SKUNK
    elif score <= DOUBLE_SKUNK_SCORE:
        return DOUBLE_SKUNK
    elif score <= SKUNK_SCORE:
        return SKUNK
    else:
        return Skunks(0)


def game_points(
    pone_score: Points, dealer_score: Points
) -> Tuple[GamePoints, GamePoints]:
    if pone_score >= MAX_SCORE:
        return (GamePoints(get_skunks(dealer_score) + 1), GamePoints(0))
    elif dealer_score >= MAX_SCORE:
        return (GamePoints(0), GamePoints(get_skunks(pone_score) + 1))
    else:
        return (GamePoints(0), GamePoints(0))


def get_mean_difference_in_stddevs(statistics1, statistics2):
    if len(statistics1) == 1 or len(statistics2) == 1:
        return math.inf

    mean_difference = abs(statistics1.mean() - statistics2.mean())
    mean_difference_stddev = hypot(
        get_stddev_of_mean(statistics1),
        get_stddev_of_mean(statistics2),
    )
    return (mean_difference / mean_difference_stddev) if mean_difference_stddev else 0


def get_length_across_all_keys(players_statistics):
    return sum(
        [
            len(players_statistics[key]["first_pone_total_points"])
            for (key, stats) in players_statistics.items()
        ]
    )


Tally = NewType("Tally", int)


class GameScoreResultsTallies(NamedTuple):
    first_pone_wins: Tally
    first_dealer_wins: Tally
    first_pone_game_points: Tally
    first_dealer_game_points: Tally

    def add(
        self, game_score_results_talles: GameScoreResultsTallies
    ) -> GameScoreResultsTallies:
        return GameScoreResultsTallies(
            Tally(self.first_pone_wins + game_score_results_talles.first_pone_wins),
            Tally(self.first_dealer_wins + game_score_results_talles.first_dealer_wins),
            Tally(
                self.first_pone_game_points
                + game_score_results_talles.first_pone_game_points
            ),
            Tally(
                self.first_dealer_game_points
                + game_score_results_talles.first_dealer_game_points
            ),
        )

    def __repr__(self) -> str:
        return f"GameScoreResultsTallies({self.first_pone_wins}, {self.first_dealer_wins}, {self.first_pone_game_points}, {self.first_dealer_game_points})"

    def __str__(self) -> str:
        return f"{self.first_pone_wins}-{self.first_dealer_wins} wins, {self.first_pone_game_points}-{self.first_dealer_game_points} game points"


Wins = NewType("Wins", int)
ExpectedWins = NewType("ExpectedWins", float)


def simulate_games(
    process_game_count,
    overall_game_count,
    maximum_hands_per_game: int,
    initial_first_pone_score: Points,
    initial_first_dealer_score: Points,
    first_pone_dealt_cards: List[Card],
    first_dealer_dealt_cards: List[Card],
    first_pone_kept_cards: Sequence[Card],
    first_dealer_kept_cards: Sequence[Card],
    initial_starter: Optional[Card],
    initial_play_actions: List[PlayAction],
    players_statistics: Dict[NextAction, Statistics],
    players_statistics_lock,
    first_pone_select_kept_cards,
    first_pone_discard_based_on_simulations: Optional[int],
    first_pone_select_each_possible_kept_hand: bool,
    first_dealer_select_kept_cards,
    first_dealer_discard_based_on_simulations: Optional[int],
    first_dealer_select_each_possible_kept_hand: bool,
    first_pone_select_play: PlaySelector,
    first_pone_play_based_on_simulations: Optional[int],
    first_dealer_select_play: PlaySelector,
    first_dealer_play_based_on_simulations: Optional[int],
    tally_start_of_hand_position_results: bool,
    estimate_incomplete_game_wins_and_game_points: bool,
    start_of_hand_position_results_tallies: shelve.DbfilenameShelf,
    select_each_post_initial_play: bool,
    hide_first_pone_hands: bool,
    hide_first_dealer_hands: bool,
    hide_play_actions: bool,
    games_per_update: int,
    show_statistics_updates: bool,
    confidence_level,
    start_time_ns,
    show_calc_cache_usage_stats,
):
    assert (
        len(set(first_pone_dealt_cards + list(first_pone_kept_cards)))
        <= DEALT_CARDS_LEN
    ), f"No more than {DEALT_CARDS_LEN} specified first pone dealt or kept cards expected but {len(set(first_pone_dealt_cards + list(first_pone_kept_cards)))} specified"
    assert (
        len(set(first_dealer_dealt_cards + list(first_dealer_kept_cards)))
        <= DEALT_CARDS_LEN
    ), f"No more than {DEALT_CARDS_LEN} specified first dealer dealt or kept cards expected but {len(set(first_dealer_dealt_cards + list(first_dealer_kept_cards)))} specified"

    try:
        if show_calc_cache_usage_stats:
            expected_random_opponent_discard_crib_points_cache.stats()

        first_pone_kept_including_played_cards = list(
            set(
                list(first_pone_kept_cards)
                + [
                    initial_play_action
                    for initial_play_action in initial_play_actions[0::2]
                    if isinstance(initial_play_action, Card)
                ]
            )
        )
        assert (
            len(first_pone_kept_including_played_cards) <= KEPT_CARDS_LEN
        ), f"No more than {KEPT_CARDS_LEN} directly or play specified first pone kept cards expected but {len(first_pone_kept_including_played_cards)} ({Hand(first_pone_kept_including_played_cards)}) specified"

        first_dealer_kept_including_played_cards = list(
            set(
                list(first_dealer_kept_cards)
                + [
                    initial_play_action
                    for initial_play_action in initial_play_actions[1::2]
                    if isinstance(initial_play_action, Card)
                ]
            )
        )
        assert (
            len(first_dealer_kept_including_played_cards) <= KEPT_CARDS_LEN
        ), f"No more than {KEPT_CARDS_LEN} directly or play specified first dealer kept cards expected but {len(first_dealer_kept_including_played_cards)} ({Hand(first_dealer_kept_including_played_cards)}) specified"

        deck_less_fixed_cards = [
            card
            for card in DECK_SET
            if card
            not in itertools.chain(
                first_pone_dealt_cards,
                first_pone_kept_including_played_cards,
                first_dealer_dealt_cards,
                first_dealer_kept_including_played_cards,
                [initial_starter] if initial_starter else [],
            )
        ]

        first_pone_play_statistics: Dict[NextAction, Statistics] = {}
        first_pone_hand_statistics: Dict[NextAction, Statistics] = {}
        first_pone_crib_statistics: Dict[NextAction, Statistics] = {}
        overall_first_pone_points_statistics: Dict[NextAction, Statistics] = {}
        first_pone_game_points_statistics: Dict[NextAction, Statistics] = {}
        first_pone_wins_statistics: Dict[NextAction, Statistics] = {}
        first_dealer_play_statistics: Dict[NextAction, Statistics] = {}
        first_dealer_hand_statistics: Dict[NextAction, Statistics] = {}
        first_dealer_crib_statistics: Dict[NextAction, Statistics] = {}
        overall_first_dealer_points_statistics: Dict[NextAction, Statistics] = {}
        first_dealer_game_points_statistics: Dict[NextAction, Statistics] = {}
        first_dealer_wins_statistics: Dict[NextAction, Statistics] = {}
        first_pone_minus_first_dealer_play_statistics: Dict[NextAction, Statistics] = {}
        first_pone_minus_first_dealer_hand_statistics: Dict[NextAction, Statistics] = {}
        first_pone_minus_first_dealer_crib_statistics: Dict[NextAction, Statistics] = {}
        first_pone_minus_first_dealer_total_points_statistics: Dict[
            NextAction, Statistics
        ] = {}
        first_pone_minus_first_dealer_game_points_statistics: Dict[
            NextAction, Statistics
        ] = {}

        pone_dealt_cards_possible_keeps = list(
            itertools.combinations(first_pone_dealt_cards, KEPT_CARDS_LEN)
        )
        pone_dealt_cards_possible_keeps_cycle = itertools.cycle(
            pone_dealt_cards_possible_keeps
        )
        dealer_dealt_cards_possible_keeps = list(
            itertools.combinations(first_dealer_dealt_cards, KEPT_CARDS_LEN)
        )
        dealer_dealt_cards_possible_keeps_cycle = itertools.cycle(
            dealer_dealt_cards_possible_keeps
        )
        dropped_keeps: Set[Tuple[Card, ...]] = set()
        pone_kept_cards_possible_plays_cycle = (
            itertools.cycle(first_pone_kept_including_played_cards)
            if first_pone_kept_including_played_cards and select_each_post_initial_play
            else None
        )
        dealer_kept_cards_possible_plays_cycle = (
            itertools.cycle(first_dealer_kept_including_played_cards)
            if first_dealer_kept_including_played_cards
            and select_each_post_initial_play
            else None
        )
        dropped_initial_plays = set()
        post_initial_player = len(initial_play_actions) % 2
        for game in range(process_game_count):
            post_initial_play: Optional[Card] = None
            game_simulation_result: Optional[GameSimulationResult] = None
            while (
                not game_simulation_result
                or game_simulation_result.non_kept_card_kept_or_non_kept_initial_played_card_played
            ):
                post_initial_play = None
                if post_initial_player == PONE and pone_kept_cards_possible_plays_cycle:
                    while (
                        not post_initial_play
                        or post_initial_play in dropped_initial_plays
                        or post_initial_play in initial_play_actions
                    ):
                        post_initial_play = next(pone_kept_cards_possible_plays_cycle)
                elif (
                    post_initial_player == DEALER
                    and dealer_kept_cards_possible_plays_cycle
                ):
                    while (
                        not post_initial_play
                        or post_initial_play in dropped_initial_plays
                        or post_initial_play in initial_play_actions
                    ):
                        post_initial_play = next(dealer_kept_cards_possible_plays_cycle)

                game_simulation_result = simulate_game(
                    first_pone_dealt_cards,
                    first_dealer_dealt_cards,
                    deck_less_fixed_cards,
                    first_pone_kept_including_played_cards,
                    first_dealer_kept_including_played_cards,
                    initial_starter,
                    maximum_hands_per_game,
                    first_pone_select_kept_cards,
                    first_pone_discard_based_on_simulations,
                    first_pone_select_each_possible_kept_hand,
                    first_dealer_select_kept_cards,
                    first_dealer_discard_based_on_simulations,
                    first_dealer_select_each_possible_kept_hand,
                    first_pone_select_play,
                    first_pone_play_based_on_simulations,
                    first_dealer_select_play,
                    first_dealer_play_based_on_simulations,
                    estimate_incomplete_game_wins_and_game_points,
                    hide_first_pone_hands,
                    hide_first_dealer_hands,
                    pone_dealt_cards_possible_keeps_cycle,
                    dealer_dealt_cards_possible_keeps_cycle,
                    dropped_keeps,
                    initial_first_pone_score,
                    initial_first_dealer_score,
                    post_initial_play,
                    initial_play_actions,
                    hide_play_actions,
                )

            first_pone_total_points = Points(
                game_simulation_result.score.first_pone_play
                + game_simulation_result.score.first_pone_hand
                + game_simulation_result.score.first_pone_crib
            )
            first_dealer_total_points = Points(
                game_simulation_result.score.first_dealer_play
                + game_simulation_result.score.first_dealer_hand
                + game_simulation_result.score.first_dealer_crib
            )

            final_first_pone_score = Points(
                initial_first_pone_score + first_pone_total_points
            )
            final_first_dealer_score = Points(
                initial_first_dealer_score + first_dealer_total_points
            )

            first_pone_game_points: GamePoints
            first_dealer_game_points: GamePoints
            (first_pone_game_points, first_dealer_game_points) = game_points(
                final_first_pone_score, final_first_dealer_score
            )

            first_pone_wins: Wins = Wins(1 if first_pone_game_points > 0 else 0)
            first_dealer_wins: Wins = Wins(1 if first_dealer_game_points > 0 else 0)

            if tally_start_of_hand_position_results:
                for (
                    game_simulation_result_start_of_next_hand_score
                ) in game_simulation_result.start_of_hand_scores:
                    shelf_start_of_hand_score_key: str = str(
                        game_simulation_result_start_of_next_hand_score
                    )
                    if (
                        shelf_start_of_hand_score_key
                        not in start_of_hand_position_results_tallies
                    ):
                        start_of_hand_position_results_tallies[
                            shelf_start_of_hand_score_key
                        ] = GameScoreResultsTallies(
                            Tally(0), Tally(0), Tally(0), Tally(0)
                        )
                    start_of_hand_position_results_tallies[
                        shelf_start_of_hand_score_key
                    ] = start_of_hand_position_results_tallies[
                        shelf_start_of_hand_score_key
                    ].add(
                        GameScoreResultsTallies(
                            Tally(first_pone_wins),
                            Tally(first_dealer_wins),
                            Tally(first_pone_game_points),
                            Tally(first_dealer_game_points),
                        )
                    )
                    print(
                        f"Start of hand score {game_simulation_result_start_of_next_hand_score} game results tallies incremented to {start_of_hand_position_results_tallies[shelf_start_of_hand_score_key]}"
                    )

            next_action: NextAction = (
                game_simulation_result.kept_cards,
                post_initial_play,
            )

            if (
                estimate_incomplete_game_wins_and_game_points
                and first_pone_game_points == 0
                and first_dealer_game_points == 0
            ):
                next_dealer_is_first_pone: bool = (
                    len(game_simulation_result.start_of_hand_scores) % 2 == 1
                )
                start_of_next_hand_score: StartOfHandScore = StartOfHandScore(
                    final_first_pone_score,
                    final_first_dealer_score,
                    next_dealer_is_first_pone,
                )
                try:
                    start_of_hand_position_results_tallies_entry: GameScoreResultsTallies = start_of_hand_position_results_tallies[
                        str(start_of_next_hand_score)
                    ]
                    tallied_game_count = (
                        start_of_hand_position_results_tallies_entry.first_pone_wins
                        + start_of_hand_position_results_tallies_entry.first_dealer_wins
                    )
                    if tallied_game_count:
                        first_pone_expected_wins: ExpectedWins = ExpectedWins(
                            (
                                start_of_hand_position_results_tallies_entry.first_pone_wins
                            )
                            / tallied_game_count
                        )
                        first_pone_expected_game_points: ExpectedWins = ExpectedWins(
                            (
                                start_of_hand_position_results_tallies_entry.first_pone_game_points
                            )
                            / tallied_game_count
                        )
                        first_dealer_expected_wins: ExpectedWins = ExpectedWins(
                            (
                                start_of_hand_position_results_tallies_entry.first_dealer_wins
                            )
                            / tallied_game_count
                        )
                        first_dealer_expected_game_points: ExpectedWins = ExpectedWins(
                            (
                                start_of_hand_position_results_tallies_entry.first_dealer_game_points
                            )
                            / tallied_game_count
                        )
                        # TODO: remove 'COULD BE' and actually use the expected game points estimate
                        print(
                            f"{first_pone_expected_wins-first_dealer_expected_wins:+5.3f} wins Δ, {first_pone_expected_game_points-first_dealer_expected_game_points:+5.3f} game points Δ over {tallied_game_count} simulated games COULD BE substituted in at {start_of_next_hand_score=} after NextAction: ({Hand(sorted(next_action[0], reverse=True))}, {next_action[1]})."
                        )
                except KeyError:
                    print(
                        f"{0:+5.3f} wins Δ, {0:+5.3f} game points Δ retained as no simulated games are available at {start_of_next_hand_score=} after NextAction: ({Hand(sorted(next_action[0], reverse=True))}, {next_action[1]})."
                    )

            if not hide_play_actions:
                print(
                    f"+++ Score at end of game simulation: [{initial_first_pone_score + first_pone_total_points}-{initial_first_dealer_score + first_dealer_total_points}] for first pone and first dealer."
                )
                print(
                    f"### Game points at end of game simulation: [[{first_pone_game_points}-{first_dealer_game_points}]] for pone and dealer."
                )
                print()

            # TODO: used namedtuple
            statistics_push(
                first_pone_play_statistics,
                next_action,
                game_simulation_result.score.first_pone_play,
            )
            statistics_push(
                first_pone_hand_statistics,
                next_action,
                game_simulation_result.score.first_pone_hand,
            )
            statistics_push(
                first_pone_crib_statistics,
                next_action,
                game_simulation_result.score.first_pone_crib,
            )
            statistics_push(
                overall_first_pone_points_statistics,
                next_action,
                first_pone_total_points,
            )
            statistics_push(
                first_pone_game_points_statistics,
                next_action,
                first_pone_game_points,
            )
            statistics_push(
                first_pone_wins_statistics,
                next_action,
                first_pone_wins,
            )

            statistics_push(
                first_dealer_play_statistics,
                next_action,
                game_simulation_result.score.first_dealer_play,
            )
            statistics_push(
                first_dealer_hand_statistics,
                next_action,
                game_simulation_result.score.first_dealer_hand,
            )
            statistics_push(
                first_dealer_crib_statistics,
                next_action,
                game_simulation_result.score.first_dealer_crib,
            )
            statistics_push(
                overall_first_dealer_points_statistics,
                next_action,
                first_dealer_total_points,
            )
            statistics_push(
                first_dealer_game_points_statistics,
                next_action,
                first_dealer_game_points,
            )
            statistics_push(
                first_dealer_wins_statistics,
                next_action,
                first_dealer_wins,
            )

            statistics_push(
                first_pone_minus_first_dealer_play_statistics,
                next_action,
                Points(
                    game_simulation_result.score.first_pone_play
                    - game_simulation_result.score.first_dealer_play
                ),
            )
            statistics_push(
                first_pone_minus_first_dealer_hand_statistics,
                next_action,
                Points(
                    game_simulation_result.score.first_pone_hand
                    - game_simulation_result.score.first_dealer_hand
                ),
            )
            statistics_push(
                first_pone_minus_first_dealer_crib_statistics,
                next_action,
                Points(
                    game_simulation_result.score.first_pone_crib
                    - game_simulation_result.score.first_dealer_crib
                ),
            )
            statistics_push(
                first_pone_minus_first_dealer_total_points_statistics,
                next_action,
                Points(first_pone_total_points - first_dealer_total_points),
            )
            statistics_push(
                first_pone_minus_first_dealer_game_points_statistics,
                next_action,
                Points(first_pone_game_points - first_dealer_game_points),
            )

            if (
                game % games_per_update == games_per_update - 1
                or game == process_game_count - 1
            ):
                players_statistics_lock.acquire()

                statistics_dict_add(
                    players_statistics, "first_pone_play", first_pone_play_statistics
                )
                first_pone_play_statistics.clear()

                statistics_dict_add(
                    players_statistics, "first_pone_hand", first_pone_hand_statistics
                )
                first_pone_hand_statistics.clear()

                statistics_dict_add(
                    players_statistics, "first_pone_crib", first_pone_crib_statistics
                )
                first_pone_crib_statistics.clear()

                statistics_dict_add(
                    players_statistics,
                    "first_pone_total_points",
                    overall_first_pone_points_statistics,
                )
                overall_first_pone_points_statistics.clear()

                statistics_dict_add(
                    players_statistics,
                    "first_pone_game_points",
                    first_pone_game_points_statistics,
                )
                first_pone_game_points_statistics.clear()

                statistics_dict_add(
                    players_statistics,
                    "first_pone_wins",
                    first_pone_wins_statistics,
                )
                first_pone_game_points_statistics.clear()

                statistics_dict_add(
                    players_statistics,
                    "first_dealer_play",
                    first_dealer_play_statistics,
                )
                first_dealer_play_statistics.clear()

                statistics_dict_add(
                    players_statistics,
                    "first_dealer_hand",
                    first_dealer_hand_statistics,
                )
                first_dealer_hand_statistics.clear()

                statistics_dict_add(
                    players_statistics,
                    "first_dealer_crib",
                    first_dealer_crib_statistics,
                )
                first_dealer_crib_statistics.clear()

                statistics_dict_add(
                    players_statistics,
                    "first_dealer_total_points",
                    overall_first_dealer_points_statistics,
                )
                overall_first_dealer_points_statistics.clear()

                statistics_dict_add(
                    players_statistics,
                    "first_dealer_game_points",
                    first_dealer_game_points_statistics,
                )
                first_dealer_game_points_statistics.clear()

                statistics_dict_add(
                    players_statistics,
                    "first_dealer_wins",
                    first_dealer_wins_statistics,
                )
                first_dealer_wins_statistics.clear()

                statistics_dict_add(
                    players_statistics,
                    "first_pone_minus_first_dealer_play",
                    first_pone_minus_first_dealer_play_statistics,
                )
                first_pone_minus_first_dealer_play_statistics.clear()

                statistics_dict_add(
                    players_statistics,
                    "first_pone_minus_first_dealer_hand",
                    first_pone_minus_first_dealer_hand_statistics,
                )
                first_pone_minus_first_dealer_hand_statistics.clear()

                statistics_dict_add(
                    players_statistics,
                    "first_pone_minus_first_dealer_crib",
                    first_pone_minus_first_dealer_crib_statistics,
                )
                first_pone_minus_first_dealer_crib_statistics.clear()

                statistics_dict_add(
                    players_statistics,
                    "first_pone_minus_first_dealer_total_points",
                    first_pone_minus_first_dealer_total_points_statistics,
                )
                first_pone_minus_first_dealer_total_points_statistics.clear()

                statistics_dict_add(
                    players_statistics,
                    "first_pone_minus_first_dealer_game_points",
                    first_pone_minus_first_dealer_game_points_statistics,
                )
                first_pone_minus_first_dealer_game_points_statistics.clear()

                players_statistics_length = get_length_across_all_keys(
                    players_statistics
                )
                if show_statistics_updates:
                    if players_statistics_length > 1:
                        print(
                            f"Mean play statistics {confidence_level}% confidence intervals ({formatted_game_count(players_statistics_length, overall_game_count)}):"
                        )
                    else:
                        print(f"Mean play statistics:")

                sorted_players_statistics = sorted(
                    players_statistics.items(),
                    key=lambda item: (
                        item[1]["first_pone_minus_first_dealer_game_points"].mean(),
                        item[1]["first_pone_minus_first_dealer_total_points"].mean(),
                    ),
                    reverse=bool(
                        (len(first_pone_dealt_cards) < len(first_dealer_dealt_cards))
                        or (
                            len(first_pone_kept_including_played_cards)
                            < len(first_dealer_kept_including_played_cards)
                        )
                    ),
                )
                for (
                    keep,
                    post_initial,
                ), keep_stats in sorted_players_statistics:
                    if show_statistics_updates:
                        keep_stats_len = len(keep_stats["first_pone_total_points"])
                        if keep:
                            print(
                                f"{Hand(keep)} - {Hand(set(first_pone_dealt_cards or first_dealer_dealt_cards) - set(keep))} (n={keep_stats_len})",
                                end="",
                            )
                        if post_initial:
                            print(
                                f"post-initial play {post_initial} (n={keep_stats_len})",
                                end="",
                            )
                        if keep or post_initial:
                            print(
                                f": {get_confidence_interval(keep_stats['first_pone_minus_first_dealer_game_points'], confidence_level)} game points; {keep_stats['first_pone_minus_first_dealer_play'].mean():+9.5f} Δ-peg + {keep_stats['first_pone_minus_first_dealer_hand'].mean():+9.5f} Δ-hand + {keep_stats['first_pone_minus_first_dealer_crib'].mean():+9.5f} crib = {get_confidence_interval(keep_stats['first_pone_minus_first_dealer_total_points'], confidence_level)} overall"
                            )

                    if len(keep_stats["first_pone_minus_first_dealer_game_points"]) > 1:
                        mean_game_points_differential_in_stddevs = (
                            get_mean_difference_in_stddevs(
                                keep_stats["first_pone_minus_first_dealer_game_points"],
                                sorted_players_statistics[-1][1][
                                    "first_pone_minus_first_dealer_game_points"
                                ],
                            )
                        )
                        mean_total_points_differential_in_stddevs = (
                            get_mean_difference_in_stddevs(
                                keep_stats[
                                    "first_pone_minus_first_dealer_total_points"
                                ],
                                sorted_players_statistics[-1][1][
                                    "first_pone_minus_first_dealer_total_points"
                                ],
                            )
                        )
                        drop_confidence_level = 2 * get_z_statistic(confidence_level)
                        if (
                            (
                                mean_game_points_differential_in_stddevs
                                > drop_confidence_level
                            )
                            or mean_game_points_differential_in_stddevs == 0
                            and (
                                mean_total_points_differential_in_stddevs
                                > drop_confidence_level
                            )
                        ):
                            if keep:
                                dropped_keeps.add(tuple(keep))
                            if post_initial:
                                dropped_initial_plays.add(post_initial)

                    if (
                        keep not in dropped_keeps
                        and post_initial not in dropped_initial_plays
                    ):
                        if show_statistics_updates:
                            print(
                                f"First Pone                    Play  points: {get_confidence_interval(keep_stats['first_pone_play'], confidence_level)}"
                            )
                            print(
                                f"First Pone                    Hand  points: {get_confidence_interval(keep_stats['first_pone_hand'], confidence_level)}"
                            )
                            print(
                                f"First Pone                    Crib  points: {get_confidence_interval(keep_stats['first_pone_crib'], confidence_level)}"
                            )
                            print(
                                f"First Pone                    Total points: {get_confidence_interval(keep_stats['first_pone_total_points'], confidence_level)}"
                            )
                            print(
                                f"First Pone                    Game  points: {get_confidence_interval(keep_stats['first_pone_game_points'], confidence_level)}"
                            )
                            print(
                                f"First Pone                    Game  wins  : {get_confidence_interval(keep_stats['first_pone_wins'], confidence_level)}"
                            )
                            print(
                                "-----------------------------------------------------"
                            )
                            print(
                                f"First Dealer                  Play  points: {get_confidence_interval(keep_stats['first_dealer_play'], confidence_level)}"
                            )
                            print(
                                f"First Dealer                  Hand  points: {get_confidence_interval(keep_stats['first_dealer_hand'], confidence_level)}"
                            )
                            print(
                                f"First Dealer                  Crib  points: {get_confidence_interval(keep_stats['first_dealer_crib'], confidence_level)}"
                            )
                            print(
                                f"First Dealer                  Total points: {get_confidence_interval(keep_stats['first_dealer_total_points'], confidence_level)}"
                            )
                            print(
                                f"First Dealer                  Game  points: {get_confidence_interval(keep_stats['first_dealer_game_points'], confidence_level)}"
                            )
                            print(
                                f"First Dealer                  Game  wins  : {get_confidence_interval(keep_stats['first_dealer_wins'], confidence_level)}"
                            )
                            print(
                                "-----------------------------------------------------"
                            )
                            print(
                                f"First Pone minus First Dealer Play  points: {get_confidence_interval(keep_stats['first_pone_minus_first_dealer_play'], confidence_level)}"
                            )
                            print(
                                f"First Pone minus First Dealer Hand  points: {get_confidence_interval(keep_stats['first_pone_minus_first_dealer_hand'], confidence_level)}"
                            )
                            print(
                                f"First Pone minus First Dealer Crib  points: {get_confidence_interval(keep_stats['first_pone_minus_first_dealer_crib'], confidence_level)}"
                            )
                            print(
                                f"First Pone minus First Dealer Total points: {get_confidence_interval(keep_stats['first_pone_minus_first_dealer_total_points'], confidence_level)}"
                            )
                            print(
                                f"First Pone minus First Dealer Game  points: {get_confidence_interval(keep_stats['first_pone_minus_first_dealer_game_points'], confidence_level)}"
                            )

                if show_statistics_updates:
                    print(
                        f"Simulated {players_statistics_length} games at {simulation_performance_statistics(start_time_ns, players_statistics_length)}"
                    )

                # correlation_str = f"{correlation:+8.5f}" if correlation else "undefined"
                # print(f"Pone   and Dealer Overall points correlation: {correlation_str}")
                players_statistics_lock.release()

                if show_calc_cache_usage_stats:
                    print("pairs_points:", pairs_points.cache_info())
                    print("runs_points:", runs_points.cache_info())
                    print("fifteens_points:", cached_fifteens_points.cache_info())
                    print(
                        "pairs, runs and fifteens points:",
                        cached_pairs_runs_and_fifteens_points.cache_info(),
                    )
                    print(
                        "max kept pre-cut points ignoring suit",
                        cached_keep_max_pre_cut_hand_points_ignoring_suit.cache_info(),
                    )
                    print(
                        "expected_random_opponent_discard_crib_points_ignoring_suit:",
                        expected_random_opponent_discard_crib_points_ignoring_suit.cache_info(),
                    )
                    print(
                        "max kept post-cut points ignoring suit",
                        cached_keep_max_post_cut_hand_points_ignoring_suit.cache_info(),
                    )
                    print(
                        "average_post_cut_hand_points_ignoring_suit_and_discarded:",
                        average_post_cut_hand_points_ignoring_suit_and_discarded.cache_info(),
                    )
                    print(
                        "max kept post-cut hand ± crib points ignoring suit",
                        cached_keep_max_post_cut_hand_plus_or_minus_crib_points_ignoring_suit.cache_info(),
                    )
                    print(
                        f"expected_random_opponent_discard_crib_points_cache.stats(): {expected_random_opponent_discard_crib_points_cache.stats()}"
                    )
                    print(
                        "cached_get_current_play_run_length",
                        cached_get_current_play_run_length.cache_info(),
                    )
                    print(
                        "start_of_hand_position_results_tallies unique position count",
                        len(start_of_hand_position_results_tallies),
                    )
                    start_of_hand_position_results_tallies_all_positions_occurrence_count: int = sum(
                        [
                            game_score_results_tally.first_pone_wins
                            + game_score_results_tally.first_dealer_wins
                            for game_score_results_tally in start_of_hand_position_results_tallies.values()
                        ]
                    )
                    print(
                        "start_of_hand_position_results_tallies all positions occurrence count",
                        f"{start_of_hand_position_results_tallies_all_positions_occurrence_count}",
                    )

                if (game_simulation_result.kept_cards) and len(
                    pone_dealt_cards_possible_keeps
                ) + len(dealer_dealt_cards_possible_keeps) - len(dropped_keeps) <= 1:
                    if show_statistics_updates:
                        print(
                            "Ending simulation as only one discard option remains under consideration."
                        )
                    break
                elif (
                    first_pone_kept_including_played_cards
                    and select_each_post_initial_play
                    and post_initial_player == PONE
                    and len(
                        set(first_pone_kept_including_played_cards).difference(
                            set(initial_play_actions)
                        )
                    )
                    - len(dropped_initial_plays)
                    <= 1
                ):
                    if show_statistics_updates:
                        print(
                            "Ending simulation as only one pone play option remains under consideration."
                        )
                    break
                elif (
                    first_dealer_kept_including_played_cards
                    and select_each_post_initial_play
                    and post_initial_player == DEALER
                    and len(
                        set(first_dealer_kept_including_played_cards).difference(
                            set(initial_play_actions)
                        )
                    )
                    - len(dropped_initial_plays)
                    <= 1
                ):
                    if show_statistics_updates:
                        print(
                            "Ending simulation as only one dealer play option remains under consideration."
                        )
                    break

    except KeyboardInterrupt:
        sys.exit(0)


# TODO: change return type from Sequence[Card] to Tuple[Card, Card] for increased type checking precision
def keep_user_selected(dealt_cards: Sequence[Card]) -> Sequence[Card]:
    selected_discards: Sequence[Card] = []
    while (
        len(selected_discards) != DEALT_CARDS_LEN - KEPT_CARDS_LEN
        or selected_discards[0] not in dealt_cards
        or selected_discards[1] not in dealt_cards
        or selected_discards[0] == selected_discards[1]
    ):
        selected_discards_input: str = input(
            f"Enter the cards to discard from {Hand(sorted(dealt_cards, reverse=True))}: "
        )
        try:
            selected_discards = parse_cards(selected_discards_input)
        except ValueError:
            print(f"{selected_discards_input} is not a valid selected discard")
    assert selected_discards is not None
    return [
        dealt_card for dealt_card in dealt_cards if dealt_card not in selected_discards
    ]


def keep_random(dealt_cards):
    return random.sample(dealt_cards, KEPT_CARDS_LEN)


def keep_first_four(dealt_cards):
    return dealt_cards[0:KEPT_CARDS_LEN]


@cache
def cached_keep_max_pre_cut_hand_points_ignoring_suit(sorted_dealt_indices):
    max_score = None
    max_score_kept_hand = None
    for score, kept_hand in map(
        lambda sorted_kept_indices: (
            cached_pairs_runs_and_fifteens_points(sorted_kept_indices),
            sorted_kept_indices,
        ),
        itertools.combinations(sorted_dealt_indices, KEPT_CARDS_LEN),
    ):
        if not max_score or score > max_score:
            max_score = score
            max_score_kept_hand = kept_hand
    return max_score_kept_hand


def find_kept_cards(dealt_cards, kept_indices):
    for kept_cards in itertools.combinations(dealt_cards, KEPT_CARDS_LEN):
        if kept_indices == tuple(sorted([c.index for c in kept_cards])):
            return kept_cards


def keep_max_pre_cut_hand_points_ignoring_suit(dealt_cards):
    return find_kept_cards(
        dealt_cards,
        cached_keep_max_pre_cut_hand_points_ignoring_suit(
            tuple(sorted([c.index for c in dealt_cards]))
        ),
    )


def keep_max_pre_cut_hand_points(dealt_cards):
    max_score = None
    max_score_kept_hand = None
    for score, kept_hand in map(
        lambda kept_hand: (score_hand(kept_hand), kept_hand),
        itertools.combinations(dealt_cards, KEPT_CARDS_LEN),
    ):
        if not max_score or score > max_score:
            max_score = score
            max_score_kept_hand = kept_hand
    return max_score_kept_hand


@cache
def cached_keep_max_post_cut_hand_points_ignoring_suit(sorted_dealt_indices):
    max_all_starters_total_score = None
    max_all_starters_total_score_kept_hand = None
    for sorted_kept_indices in itertools.combinations(
        sorted_dealt_indices, KEPT_CARDS_LEN
    ):
        all_starters_total_score = 0
        for starter_index in range(DECK_INDEX_COUNT):
            available_starter_index_count = (
                DECK_SUIT_COUNT - sorted_dealt_indices.count(starter_index)
            )
            possible_post_cut_hand = tuple(
                sorted([*sorted_kept_indices, starter_index])
            )
            post_cut_score = cached_pairs_runs_and_fifteens_points(
                possible_post_cut_hand
            )
            all_starters_total_score += post_cut_score * available_starter_index_count
        if (
            not max_all_starters_total_score
            or all_starters_total_score > max_all_starters_total_score
        ):
            max_all_starters_total_score = all_starters_total_score
            max_all_starters_total_score_kept_hand = sorted_kept_indices
    return max_all_starters_total_score_kept_hand


def keep_max_post_cut_hand_points_ignoring_suit(dealt_cards):
    return find_kept_cards(
        dealt_cards,
        cached_keep_max_post_cut_hand_points_ignoring_suit(
            tuple(sorted([c.index for c in dealt_cards]))
        ),
    )


def neither_flush_nor_nobs_possible(dealt_cards):
    return (
        not (any([dealt_card.index == JACK_INDEX for dealt_card in dealt_cards]))
        and Counter([dealt_card.suit for dealt_card in dealt_cards]).most_common(1)[0][
            1
        ]
        < KEPT_CARDS_LEN
    )


# TODO: factor out code in common with keep_max_pre_cut_points()
def keep_max_post_cut_hand_points(dealt_cards):
    if neither_flush_nor_nobs_possible(dealt_cards):
        return keep_max_post_cut_hand_points_ignoring_suit(dealt_cards)

    max_total_score = None
    max_total_score_kept_hand = None
    for kept_hand in itertools.combinations(dealt_cards, KEPT_CARDS_LEN):
        total_score = 0
        for starter in [card for card in DECK_SET if card not in dealt_cards]:
            score = score_hand_and_starter(kept_hand, starter)
            total_score += score
        if not max_total_score or total_score > max_total_score:
            max_total_score = total_score
            max_total_score_kept_hand = kept_hand
    return max_total_score_kept_hand


@cache
def expected_random_opponent_discard_crib_points_ignoring_suit(
    discard1: int, discard2: int
):
    total_possible_hand_plus_starter_points = 0
    total_possible_hand_plus_starter_count = 0
    for starter_index in range(DECK_INDEX_COUNT):
        available_starter_index_count = DECK_SUIT_COUNT - [discard1, discard2].count(
            starter_index
        )
        for possible_opponent_discard_1 in range(DECK_INDEX_COUNT):
            available_opponent_discard_1_count = (
                DECK_SUIT_COUNT
                - [
                    discard1,
                    discard2,
                    starter_index,
                ].count(possible_opponent_discard_1)
            )
            for possible_opponent_discard_2 in range(DECK_INDEX_COUNT):
                available_opponent_discard_2_count = (
                    DECK_SUIT_COUNT
                    - [
                        discard1,
                        discard2,
                        starter_index,
                        possible_opponent_discard_1,
                    ].count(possible_opponent_discard_2)
                )
                possible_hand_plus_starter_count = (
                    available_starter_index_count
                    * available_opponent_discard_1_count
                    * available_opponent_discard_2_count
                )
                total_possible_hand_plus_starter_count += (
                    possible_hand_plus_starter_count
                )
                total_possible_hand_plus_starter_points += (
                    possible_hand_plus_starter_count
                    * cached_pairs_runs_and_fifteens_points(
                        tuple(
                            sorted(
                                [
                                    discard1,
                                    discard2,
                                    possible_opponent_discard_1,
                                    possible_opponent_discard_2,
                                    starter_index,
                                ]
                            )
                        )
                    )
                )
    return (
        total_possible_hand_plus_starter_points / total_possible_hand_plus_starter_count
    )


# TODO: factor out code in common with keep_max_post_cut_hand_plus_or_minus_crib_points()
@cache
def cached_keep_max_post_cut_hand_plus_or_minus_crib_points_ignoring_suit(
    sorted_dealt_indices: Sequence[int], plus_crib: bool
):
    assert (
        len(sorted_dealt_indices) == DEALT_CARDS_LEN
    ), f"{DEALT_CARDS_LEN} indices expected but {len(sorted_dealt_indices)} handed in"

    sorted_dealt_indices_counter = Counter(sorted_dealt_indices)
    max_average_score = None
    max_average_score_kept_hand = None
    for sorted_kept_indices in itertools.combinations(
        sorted_dealt_indices, KEPT_CARDS_LEN
    ):
        total_kept_hand_and_starters_hand_score = 0
        kept_hand_and_starter_count = 0
        for starter_index in range(DECK_INDEX_COUNT):
            available_starter_index_count = (
                DECK_SUIT_COUNT - sorted_dealt_indices.count(starter_index)
            )
            total_kept_hand_and_starters_hand_score += (
                cached_pairs_runs_and_fifteens_points(
                    tuple(sorted([*sorted_kept_indices, starter_index]))
                )
                * available_starter_index_count
            )
            kept_hand_and_starter_count += available_starter_index_count

        average_hand_score = (
            total_kept_hand_and_starters_hand_score / kept_hand_and_starter_count
        )

        sorted_kept_indices_counter = Counter(sorted_kept_indices)
        discarded_dealt_indices_counter = (
            sorted_dealt_indices_counter - sorted_kept_indices_counter
        )
        discarded_dealt_indices = list(discarded_dealt_indices_counter.elements())
        average_crib_score = (
            1 if plus_crib else -1
        ) * expected_random_opponent_discard_crib_points_ignoring_suit(
            *discarded_dealt_indices
        )

        average_score = average_hand_score + average_crib_score

        if not max_average_score or average_score > max_average_score:
            max_average_score = average_score
            max_average_score_kept_hand = sorted_kept_indices
    return max_average_score_kept_hand


def keep_max_post_cut_hand_plus_or_minus_crib_points_ignoring_suit(
    dealt_cards: Sequence[Card], plus_crib: bool
):
    assert (
        len(dealt_cards) == DEALT_CARDS_LEN
    ), f"{DEALT_CARDS_LEN} cards expected but {len(dealt_cards)} handed in"

    return find_kept_cards(
        dealt_cards,
        cached_keep_max_post_cut_hand_plus_or_minus_crib_points_ignoring_suit(
            tuple(sorted([c.index for c in dealt_cards])), plus_crib
        ),
    )


def keep_max_post_cut_hand_minus_crib_points_ignoring_suit(dealt_cards: Sequence[Card]):
    assert (
        len(dealt_cards) == DEALT_CARDS_LEN
    ), f"{DEALT_CARDS_LEN} cards expected but {len(dealt_cards)} handed in"

    return keep_max_post_cut_hand_plus_or_minus_crib_points_ignoring_suit(
        dealt_cards, plus_crib=False
    )


def keep_max_post_cut_hand_plus_crib_points_ignoring_suit(dealt_cards: Sequence[Card]):
    assert (
        len(dealt_cards) == DEALT_CARDS_LEN
    ), f"{DEALT_CARDS_LEN} cards expected but {len(dealt_cards)} handed in"

    return keep_max_post_cut_hand_plus_or_minus_crib_points_ignoring_suit(
        dealt_cards, plus_crib=True
    )


DEFAULT_SELECT_PONE_KEPT_CARDS = keep_max_post_cut_hand_minus_crib_points_ignoring_suit
DEFAULT_SELECT_DEALER_KEPT_CARDS = keep_max_post_cut_hand_plus_crib_points_ignoring_suit


expected_random_opponent_discard_crib_points_cache = Cache(
    "expected_random_opponent_discard_crib_points_cache", eviction_policy="none"
)


@expected_random_opponent_discard_crib_points_cache.memoize()
def cached_expected_random_opponent_discard_crib_points(
    suit_normalized_sorted_discarded_dealt_cards: Tuple[Card, ...],
):
    deck_less_dealt_cards = [
        card
        for card in DECK_SET
        if card not in suit_normalized_sorted_discarded_dealt_cards
    ]
    total_kept_hand_possible_cribs_score = 0
    kept_hand_starter_and_opponent_discard_count = 0
    for starter in deck_less_dealt_cards:
        deck_less_dealt_cards_and_starter = [
            card for card in deck_less_dealt_cards if card != starter
        ]
        for possible_opponent_discard in itertools.combinations(
            deck_less_dealt_cards_and_starter, 2
        ):
            possible_crib = [
                *suit_normalized_sorted_discarded_dealt_cards,
                *possible_opponent_discard,
            ]
            kept_hand_possible_crib_score = score_hand_and_starter(
                possible_crib, starter, is_crib=True
            )
            total_kept_hand_possible_cribs_score += kept_hand_possible_crib_score
            kept_hand_starter_and_opponent_discard_count += 1

    average_crib_score = (
        total_kept_hand_possible_cribs_score
        / kept_hand_starter_and_opponent_discard_count
    )
    print(
        f"Adding to disk cache cached_expected_random_opponent_discard_crib_points({Index.indices[suit_normalized_sorted_discarded_dealt_cards[0].index]}-{Index.indices[suit_normalized_sorted_discarded_dealt_cards[1].index]} {'  ' if suit_normalized_sorted_discarded_dealt_cards[0].suit == suit_normalized_sorted_discarded_dealt_cards[1].suit else 'un'}suited) = {average_crib_score}"
    )
    return average_crib_score


def expected_random_opponent_discard_crib_points(discarded_dealt_cards: List[Card]):
    is_suited_discard: bool = (
        discarded_dealt_cards[0].suit == discarded_dealt_cards[1].suit
    )
    sorted_discarded_dealt_cards: List[Card] = sorted(
        discarded_dealt_cards, reverse=True
    )
    suit_normalized_discarded_dealt_cards = [
        Card(sorted_discarded_dealt_cards[0].index, 0),
        Card(sorted_discarded_dealt_cards[1].index, 0 if is_suited_discard else 1),
    ]
    return cached_expected_random_opponent_discard_crib_points(
        tuple(suit_normalized_discarded_dealt_cards)
    )


@cache
def average_post_cut_hand_points_ignoring_suit_and_discarded(sorted_kept_indices):
    total_kept_hand_and_starters_hand_score = 0
    kept_hand_and_starter_count = 0
    for starter_index in range(DECK_INDEX_COUNT):
        available_starter_index_count = DECK_SUIT_COUNT - sorted_kept_indices.count(
            starter_index
        )
        total_kept_hand_and_starters_hand_score += (
            cached_pairs_runs_and_fifteens_points(
                tuple(sorted([*sorted_kept_indices, starter_index]))
            )
            * available_starter_index_count
        )
        kept_hand_and_starter_count += available_starter_index_count

    return total_kept_hand_and_starters_hand_score / kept_hand_and_starter_count


# TODO: factor out code in common with keep_max_post_cut_hand_points()
# TODO: factor out code in common with cached_keep_max_post_cut_hand_plus_or_minus_crib_points_ignoring_suit()
def keep_max_post_cut_hand_plus_or_minus_crib_points(dealt_cards, plus_crib):
    neither_flush_nor_nobs_is_possible = neither_flush_nor_nobs_possible(dealt_cards)
    max_average_score = None
    max_average_score_kept_hand = None
    for kept_hand in itertools.combinations(dealt_cards, KEPT_CARDS_LEN):
        if neither_flush_nor_nobs_is_possible:
            average_hand_score = (
                average_post_cut_hand_points_ignoring_suit_and_discarded(
                    tuple(sorted([c.index for c in kept_hand]))
                )
            )
        else:
            total_kept_hand_and_starters_hand_score = 0
            kept_hand_and_starter_count = 0
            for starter in [card for card in DECK_SET if card not in dealt_cards]:
                total_kept_hand_and_starters_hand_score += score_hand_and_starter(
                    kept_hand, starter
                )
                kept_hand_and_starter_count += 1
            average_hand_score = (
                total_kept_hand_and_starters_hand_score / kept_hand_and_starter_count
            )

        discarded_dealt_cards = [card for card in dealt_cards if card not in kept_hand]
        average_crib_score = (
            1 if plus_crib else -1
        ) * expected_random_opponent_discard_crib_points(discarded_dealt_cards)

        average_score = average_hand_score + average_crib_score

        if not max_average_score or average_score > max_average_score:
            max_average_score = average_score
            max_average_score_kept_hand = kept_hand
    return max_average_score_kept_hand


def keep_max_post_cut_hand_minus_crib_points(dealt_cards):
    return keep_max_post_cut_hand_plus_or_minus_crib_points(
        dealt_cards, plus_crib=False
    )


def keep_max_post_cut_hand_plus_crib_points(dealt_cards):
    return keep_max_post_cut_hand_plus_or_minus_crib_points(dealt_cards, plus_crib=True)


BEST_STATIC_SELECT_PONE_KEPT_CARDS = keep_max_post_cut_hand_minus_crib_points
BEST_STATIC_SELECT_DEALER_KEPT_CARDS = keep_max_post_cut_hand_plus_crib_points


def play_first(
    playable_cards: Sequence[Card],
    current_play_count: PlayCount,
    current_play_to_31_cards: Sequence[Card],
) -> PlayableCardIndex:
    return PlayableCardIndex(0)


def play_random(
    playable_cards: Sequence[Card],
    current_play_count: PlayCount,
    current_play_to_31_cards: Sequence[Card],
) -> PlayableCardIndex:
    return PlayableCardIndex(random.randrange(0, len(playable_cards)))


def play_highest_count(
    playable_cards: Sequence[Card],
    current_play_count: PlayCount,
    current_play_to_31_cards: Sequence[Card],
) -> PlayableCardIndex:
    play_card = None
    play_index = None
    for index, card in enumerate(playable_cards):
        if not play_card or card.count > play_card.count:
            play_card = card
            play_index = index
    assert play_index is not None
    return PlayableCardIndex(play_index)


THIRTY_ONE_COUNT: PlayCount = PlayCount(31)


def play_to_fixed_count(
    playable_cards: Sequence[Card],
    current_play_count: PlayCount,
    *target_play_counts: PlayCount,
) -> Optional[PlayableCardIndex]:
    for index, card in enumerate(playable_cards):
        if current_play_count + card.count in target_play_counts:
            return PlayableCardIndex(index)
    return None


def play_pair(
    playable_cards: Sequence[Card], current_play_to_31_cards: Sequence[Card]
) -> Optional[PlayableCardIndex]:
    if current_play_to_31_cards:
        for index, card in enumerate(playable_cards):
            if card.index == current_play_to_31_cards[-1].index:
                return PlayableCardIndex(index)
    return None


def play_15_or_31_else_highest_count(
    playable_cards: Sequence[Card],
    current_play_count: PlayCount,
    current_play_to_31_cards: Sequence[Card],
) -> PlayableCardIndex:
    play_to_fixed_count_index = play_to_fixed_count(
        playable_cards, current_play_count, FIFTEEN_COUNT, THIRTY_ONE_COUNT
    )
    return (
        play_to_fixed_count_index
        if play_to_fixed_count_index is not None
        else play_highest_count(
            playable_cards, current_play_count, current_play_to_31_cards
        )
    )


def play_pair_else_15_or_31_else_highest_count(
    playable_cards: Sequence[Card],
    current_play_count: PlayCount,
    current_play_to_31_cards: Sequence[Card],
) -> PlayableCardIndex:
    if (
        play_pair_index := play_pair(playable_cards, current_play_to_31_cards)
    ) is not None:
        return play_pair_index

    return play_15_or_31_else_highest_count(
        playable_cards, current_play_count, current_play_to_31_cards
    )


def play_15_else_pair_else_31_else_highest_count(
    playable_cards: Sequence[Card],
    current_play_count: PlayCount,
    current_play_to_31_cards: Sequence[Card],
) -> PlayableCardIndex:
    if (
        play_15_index := play_to_fixed_count(
            playable_cards, current_play_count, FIFTEEN_COUNT
        )
    ) is not None:
        return play_15_index

    if (
        play_pair_index := play_pair(playable_cards, current_play_to_31_cards)
    ) is not None:
        return play_pair_index

    if (
        play_31_index := play_to_fixed_count(
            playable_cards, current_play_count, THIRTY_ONE_COUNT
        )
    ) is not None:
        return play_31_index

    return play_highest_count(
        playable_cards, current_play_count, current_play_to_31_cards
    )


def play_run(
    playable_cards: Sequence[Card], current_play_to_31_cards: Sequence[Card]
) -> Optional[PlayableCardIndex]:
    best_play_index: Optional[PlayableCardIndex] = None
    best_play_run_length: Optional[int] = None
    for index, playable_card in enumerate(playable_cards):
        play_run_length = get_current_play_run_length(
            [*current_play_to_31_cards, playable_card]
        )
        if play_run_length and (
            best_play_index is None or play_run_length > best_play_run_length
        ):
            best_play_index = PlayableCardIndex(index)
            best_play_run_length = play_run_length
    return best_play_index


def play_run_else_15_else_pair_else_31_else_highest_count(
    playable_cards: Sequence[Card],
    current_play_count: PlayCount,
    current_play_to_31_cards: Sequence[Card],
) -> PlayableCardIndex:
    if (run_index := play_run(playable_cards, current_play_to_31_cards)) is not None:
        return run_index

    return play_15_else_pair_else_31_else_highest_count(
        playable_cards, current_play_count, current_play_to_31_cards
    )


def play_low_lead(
    playable_cards: Sequence[Card], current_play_count: PlayCount
) -> Optional[PlayableCardIndex]:
    if current_play_count > 0:
        return None

    play_card: Optional[Card] = None
    play_index: Optional[PlayableCardIndex] = None
    for index, card in enumerate(playable_cards):
        if card.count < 5 and (play_card is None or card.count > play_card.count):
            play_card = card
            play_index = PlayableCardIndex(index)
    return play_index


def play_low_lead_else_run_else_15_else_pair_else_31_else_highest_count(
    playable_cards: Sequence[Card],
    current_play_count: PlayCount,
    current_play_to_31_cards: Sequence[Card],
) -> PlayableCardIndex:
    if (
        low_lead_index := play_low_lead(playable_cards, current_play_count)
    ) is not None:
        return low_lead_index

    return play_run_else_15_else_pair_else_31_else_highest_count(
        playable_cards, current_play_count, current_play_to_31_cards
    )


def play_run_else_15_else_pair_else_31_else_16_to_20_count_else_highest_count(
    playable_cards: Sequence[Card],
    current_play_count: PlayCount,
    current_play_to_31_cards: Sequence[Card],
) -> PlayableCardIndex:
    if (run_index := play_run(playable_cards, current_play_to_31_cards)) is not None:
        return run_index

    if (
        play_15_index := play_to_fixed_count(
            playable_cards, current_play_count, FIFTEEN_COUNT
        )
    ) is not None:
        return play_15_index

    if (
        play_pair_index := play_pair(playable_cards, current_play_to_31_cards)
    ) is not None:
        return play_pair_index

    if (
        play_31_index := play_to_fixed_count(
            playable_cards, current_play_count, THIRTY_ONE_COUNT
        )
    ) is not None:
        return play_31_index

    if (
        play_16_to_20_index := play_to_fixed_count(
            playable_cards,
            current_play_count,
            *range(FIFTEEN_COUNT + 1, THIRTY_ONE_COUNT - MAX_CARD_COUNTING_VALUE),
        )
    ) is not None:
        return play_16_to_20_index

    return play_highest_count(
        playable_cards, current_play_count, current_play_to_31_cards
    )


def play_low_lead_else_run_else_15_else_pair_else_31_else_16_to_20_count_else_highest_count(
    playable_cards: Sequence[Card],
    current_play_count: PlayCount,
    current_play_to_31_cards: Sequence[Card],
) -> PlayableCardIndex:
    if (
        low_lead_index := play_low_lead(playable_cards, current_play_count)
    ) is not None:
        return low_lead_index

    return play_run_else_15_else_pair_else_31_else_16_to_20_count_else_highest_count(
        playable_cards, current_play_count, current_play_to_31_cards
    )


def play_pairs_royale(
    playable_cards: Sequence[Card], current_play_to_31_cards: Sequence[Card]
) -> Optional[PlayableCardIndex]:
    if len(current_play_to_31_cards) >= 2:
        for index, card in enumerate(playable_cards):
            if (
                card.index
                == current_play_to_31_cards[-1].index
                == current_play_to_31_cards[-2].index
            ):
                return PlayableCardIndex(index)
    return None


def play_low_lead_else_pairs_royale_else_run_else_15_else_pair_else_31_else_16_to_20_count_else_highest_count(
    playable_cards: Sequence[Card],
    current_play_count: PlayCount,
    current_play_to_31_cards: Sequence[Card],
) -> PlayableCardIndex:
    if (
        low_lead_index := play_low_lead(playable_cards, current_play_count)
    ) is not None:
        return low_lead_index

    if (
        play_pairs_royale_index := play_pairs_royale(
            playable_cards, current_play_to_31_cards
        )
    ) is not None:
        return play_pairs_royale_index

    return play_run_else_15_else_pair_else_31_else_16_to_20_count_else_highest_count(
        playable_cards, current_play_count, current_play_to_31_cards
    )


DEFAULT_SELECT_PLAY = play_low_lead_else_pairs_royale_else_run_else_15_else_pair_else_31_else_16_to_20_count_else_highest_count


def play_based_on_simulation(
    simulated_hand_count: int,
    hide_hand: bool,
    current_game_score: GameScore,
    first_pone_to_play: bool,
    player_to_play_dealt_hand: List[Card],
    player_to_play_kept_hand: Sequence[Card],
    starter: Card,
    initial_play_actions: List[PlayAction],
    player: Player,
    pone_is_parent_game_first_pone: bool,
    estimate_incomplete_game_wins_and_game_points: bool,
):
    played_cards: List[Card] = [
        initial_play_action
        for initial_play_action in initial_play_actions[player::2]
        if isinstance(initial_play_action, Card)
    ]
    possible_play_count: int = KEPT_CARDS_LEN - len(played_cards)
    total_play_simulation_count: int = possible_play_count * simulated_hand_count
    if not hide_hand:
        print(
            f"Simulating each of the {possible_play_count} possible plays {simulated_hand_count} times in order to select the play:"
        )
    manager = Manager()
    simulated_players_statistics: Dict[NextAction, Statistics] = manager.dict()
    simulated_players_statistics_lock = Lock()
    CONFIDENCE_LEVEL: int = 95
    player_to_play_is_first_pone: bool = (
        pone_is_parent_game_first_pone
        and first_pone_to_play
        or not pone_is_parent_game_first_pone
        and not first_pone_to_play
    )
    player_to_play_is_first_dealer: bool = (
        pone_is_parent_game_first_pone
        and not first_pone_to_play
        or not pone_is_parent_game_first_pone
        and first_pone_to_play
    )
    simulate_games(
        total_play_simulation_count,
        total_play_simulation_count,
        1,
        Points(
            current_game_score.first_pone_initial
            + current_game_score.first_pone_play
            + current_game_score.first_pone_hand
            + current_game_score.first_pone_crib
        ),
        Points(
            current_game_score.first_dealer_initial
            + current_game_score.first_dealer_play
            + current_game_score.first_dealer_hand
            + current_game_score.first_dealer_crib
        ),
        player_to_play_dealt_hand if player_to_play_is_first_pone else [],
        player_to_play_dealt_hand if player_to_play_is_first_dealer else [],
        player_to_play_kept_hand if player_to_play_is_first_pone else [],
        player_to_play_kept_hand if player_to_play_is_first_dealer else [],
        starter,
        initial_play_actions,
        simulated_players_statistics,
        simulated_players_statistics_lock,
        DEFAULT_SELECT_PONE_KEPT_CARDS,
        False,
        False,
        DEFAULT_SELECT_DEALER_KEPT_CARDS,
        False,
        False,
        DEFAULT_SELECT_PLAY,
        None,
        DEFAULT_SELECT_PLAY,
        None,
        tally_start_of_hand_position_results,
        estimate_incomplete_game_wins_and_game_points,
        start_of_hand_position_results_tallies,
        True,
        True,
        True,
        True,
        sys.maxsize,
        False,
        CONFIDENCE_LEVEL,
        time.time_ns(),
        False,
    )

    sorted_simulated_players_statistics = sorted(
        simulated_players_statistics.items(),
        key=lambda item: (
            item[1]["first_pone_minus_first_dealer_game_points"].mean(),
            item[1]["first_pone_minus_first_dealer_play"].mean(),
        ),
        reverse=(player == PONE),
    )
    if not hide_hand:
        for (
            keep,
            post_initial,
        ), post_initial_stats in sorted_simulated_players_statistics:
            print(
                f"{post_initial} first play: {get_confidence_interval(post_initial_stats['first_pone_minus_first_dealer_game_points'], CONFIDENCE_LEVEL)} game points; {post_initial_stats['first_pone_minus_first_dealer_play'].mean():+9.5f} Δ-peg + {post_initial_stats['first_pone_minus_first_dealer_hand'].mean():+9.5f} Δ-hand + {post_initial_stats['first_pone_minus_first_dealer_crib'].mean():+9.5f} crib = {get_confidence_interval(post_initial_stats['first_pone_minus_first_dealer_total_points'], CONFIDENCE_LEVEL)} overall"
            )

    return sorted_simulated_players_statistics[0][0][1]


def play_user_selected(
    playable_cards: Sequence[Card],
    current_play_count: PlayCount,
    current_play_to_31_cards: Sequence[Card],
) -> PlayableCardIndex:
    selected_card: Optional[Card] = None
    while not selected_card or selected_card not in playable_cards:
        selected_card_input: str = input(
            f"Enter the card to play (legal plays = [{','.join([str(card) for card in playable_cards])}]): "
        )
        try:
            selected_card = Card.from_string(selected_card_input)
        except ValueError:
            if not selected_card_input and len(playable_cards) == 1:
                selected_card = playable_cards[0]
            else:
                print(f"{selected_card_input} is not a valid selection")
    assert selected_card is not None
    return PlayableCardIndex(playable_cards.index(selected_card))


def simulation_performance_statistics(start_time_ns, games_simulated):
    elapsed_time_ns = time.time_ns() - start_time_ns
    ns_per_s = 1000000000
    return f"{games_simulated / (elapsed_time_ns / ns_per_s):.3f} games/s ({elapsed_time_ns / games_simulated:.0f} ns/game) in {elapsed_time_ns / ns_per_s} s"


POSSIBLE_DISCARD_COUNT: int = comb(DEALT_CARDS_LEN, DEALT_CARDS_LEN - KEPT_CARDS_LEN)


def player_select_kept_cards_based_on_simulation(
    simulated_hand_count: int,
    hide_hand: bool,
    current_game_score: GameScore,
    dealt_hand: List[Card],
    player: Player,
    estimate_incomplete_game_wins_and_game_points: bool,
):
    TOTAL_DISCARD_SIMULATION_COUNT: int = POSSIBLE_DISCARD_COUNT * simulated_hand_count
    if not hide_hand:
        print(
            f"Simulating each of the {POSSIBLE_DISCARD_COUNT} possible discard {simulated_hand_count} times in order to select discard"
        )
    manager = Manager()
    simulated_players_statistics: Dict[NextAction, Statistics] = manager.dict()
    simulated_players_statistics_lock = Lock()
    CONFIDENCE_LEVEL: int = 95
    simulate_games(
        TOTAL_DISCARD_SIMULATION_COUNT,
        TOTAL_DISCARD_SIMULATION_COUNT,
        1,
        Points(
            current_game_score.first_pone_initial
            + current_game_score.first_pone_play
            + current_game_score.first_pone_hand
            + current_game_score.first_pone_crib
        ),
        Points(
            current_game_score.first_dealer_initial
            + current_game_score.first_dealer_play
            + current_game_score.first_dealer_hand
            + current_game_score.first_dealer_crib
        ),
        dealt_hand if player == PONE else [],
        dealt_hand if player == DEALER else [],
        [],
        [],
        None,
        [],
        simulated_players_statistics,
        simulated_players_statistics_lock,
        DEFAULT_SELECT_PONE_KEPT_CARDS,
        False,
        player == PONE,
        DEFAULT_SELECT_DEALER_KEPT_CARDS,
        False,
        player == DEALER,
        DEFAULT_SELECT_PLAY,
        None,
        DEFAULT_SELECT_PLAY,
        None,
        tally_start_of_hand_position_results,
        estimate_incomplete_game_wins_and_game_points,
        start_of_hand_position_results_tallies,
        False,
        True,
        True,
        True,
        sys.maxsize,
        False,
        CONFIDENCE_LEVEL,
        time.time_ns(),
        False,
    )

    sorted_simulated_players_statistics = sorted(
        simulated_players_statistics.items(),
        key=lambda item: (
            item[1]["first_pone_minus_first_dealer_game_points"].mean(),
            item[1]["first_pone_minus_first_dealer_total_points"].mean(),
        ),
        reverse=(player == PONE),
    )
    if not hide_hand:
        for (
            keep,
            post_initial,
        ), keep_stats in sorted_simulated_players_statistics:
            print(
                f"{Hand(sorted(keep, reverse=True))} - {Hand(sorted(set(dealt_hand) - set(keep), reverse=True))}: {get_confidence_interval(keep_stats['first_pone_minus_first_dealer_game_points'], CONFIDENCE_LEVEL)} game points; {keep_stats['first_pone_minus_first_dealer_play'].mean():+9.5f} Δ-peg + {keep_stats['first_pone_minus_first_dealer_hand'].mean():+9.5f} Δ-hand + {keep_stats['first_pone_minus_first_dealer_crib'].mean():+9.5f} crib = {get_confidence_interval(keep_stats['first_pone_minus_first_dealer_total_points'], CONFIDENCE_LEVEL)} overall"
            )

    return sorted_simulated_players_statistics[0][0][0]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--process-count",
        help="number of processes to use to simulate cribbage games",
        type=int,
        default=1,
    )

    first_pone_discard_algorithm_group = parser.add_mutually_exclusive_group()
    first_pone_discard_algorithm_group.add_argument(
        "--first-pone-keep-user-selected",
        action="store_true",
        help="have first pone discard based on user selections",
    )
    first_pone_discard_algorithm_group.add_argument(
        "--first-pone-keep-random",
        action="store_true",
        help="have first pone discard randomly",
    )
    first_pone_discard_algorithm_group.add_argument(
        "--first-pone-keep-first-four",
        action="store_true",
        help="have first pone keep the first four cards dealt to pone",
    )
    first_pone_discard_algorithm_group.add_argument(
        "--first-pone-maximize-pre-cut-hand-points-ignoring-suit",
        action="store_true",
        help="have first pone keep the cards which maximize points in hand before the cut ignoring suit",
    )
    first_pone_discard_algorithm_group.add_argument(
        "--first-pone-maximize-pre-cut-hand-points",
        action="store_true",
        help="have first pone keep the cards which maximize points in hand before the cut",
    )
    first_pone_discard_algorithm_group.add_argument(
        "--first-pone-maximize-post-cut-hand-points-ignoring-suit",
        action="store_true",
        help="have first pone keep the cards which maximize points in hand after the cut ignoring suit",
    )
    first_pone_discard_algorithm_group.add_argument(
        "--first-pone-maximize-post-cut-hand-points",
        action="store_true",
        help="have first pone keep the cards which maximize points in hand after the cut",
    )
    first_pone_discard_algorithm_group.add_argument(
        "--first-pone-maximize-post-cut-hand-minus-crib-points-ignoring-suit",
        action="store_true",
        help="have first pone keep the cards which maximize points in hand minus crib ignoring suit after the cut",
    )
    first_pone_discard_algorithm_group.add_argument(
        "--first-pone-maximize-post-cut-hand-minus-crib-points",
        action="store_true",
        help="have first pone keep the cards which maximize points in hand minus crib after the cut",
    )

    parser.add_argument(
        "--first-pone-discard-based-on-simulations",
        help="have first pone keep the cards which on average maximize pone minus dealer game otherwise scored points in simulated single hands",
        type=int,
    )

    parser.add_argument(
        "--first-pone-select-each-possible-kept-hand",
        action="store_true",
        help="have first pone keep each possible kept hand",
    )

    first_dealer_discard_algorithm_group = parser.add_mutually_exclusive_group()
    first_dealer_discard_algorithm_group.add_argument(
        "--first-dealer-keep-user-selected",
        action="store_true",
        help="have first dealer discard based on user selections",
    )
    first_dealer_discard_algorithm_group.add_argument(
        "--first-dealer-keep-random",
        action="store_true",
        help="have first dealer discard randomly",
    )
    first_dealer_discard_algorithm_group.add_argument(
        "--first-dealer-keep-first-four",
        action="store_true",
        help="have first dealer keep the first four cards dealt to dealer",
    )
    first_dealer_discard_algorithm_group.add_argument(
        "--first-dealer-maximize-pre-cut-hand-points-ignoring-suit",
        action="store_true",
        help="have first dealer keep the cards which maximize points in hand before the cut ignoring suit",
    )
    first_dealer_discard_algorithm_group.add_argument(
        "--first-dealer-maximize-pre-cut-hand-points",
        action="store_true",
        help="have first dealer keep the cards which maximize points in hand before the cut",
    )
    first_dealer_discard_algorithm_group.add_argument(
        "--first-dealer-maximize-post-cut-hand-points-ignoring-suit",
        action="store_true",
        help="have first dealer keep the cards which maximize points in hand after the cut ignoring suit",
    )
    first_dealer_discard_algorithm_group.add_argument(
        "--first-dealer-maximize-post-cut-hand-points",
        action="store_true",
        help="have first dealer keep the cards which maximize points in hand after the cut",
    )
    first_dealer_discard_algorithm_group.add_argument(
        "--first-dealer-maximize-post-cut-hand-plus-crib-points-ignoring-suit",
        action="store_true",
        help="have first dealer keep the cards which maximize points in hand plus crib after the cut ignoring suit",
    )
    first_dealer_discard_algorithm_group.add_argument(
        "--first-dealer-maximize-post-cut-hand-plus-crib-points",
        action="store_true",
        help="have first dealer keep the cards which maximize points in hand plus crib after the cut",
    )

    parser.add_argument(
        "--first-dealer-discard-based-on-simulations",
        help="have first dealer keep the cards which on average maximize dealer minus pone game otherwise scored points in simulated single hands",
        type=int,
    )

    parser.add_argument(
        "--first-dealer-select-each-possible-kept-hand",
        action="store_true",
        help="have first dealer keep each possible kept hand",
    )

    first_pone_play_algorithm_group = parser.add_mutually_exclusive_group()
    first_pone_play_algorithm_group.add_argument(
        "--first-pone-play-user-entered",
        action="store_true",
        help="prompt user to enter first pone plays",
    )
    first_pone_play_algorithm_group.add_argument(
        "--first-pone-play-first",
        action="store_true",
        help="have first pone play first legal card from hand",
    )
    first_pone_play_algorithm_group.add_argument(
        "--first-pone-play-random",
        action="store_true",
        help="have first pone play random legal card from hand",
    )
    first_pone_play_algorithm_group.add_argument(
        "--first-pone-play-highest-count",
        action="store_true",
        help="have first pone play highest count legal card from hand",
    )
    first_pone_play_algorithm_group.add_argument(
        "--first-pone-play-15-or-31-else-highest-count",
        action="store_true",
        help="have first pone play 15-2 or 31 for 2 otherwise the highest count legal card from hand",
    )
    first_pone_play_algorithm_group.add_argument(
        "--first-pone-play-pair-else-15-or-31-else-highest-count",
        action="store_true",
    )
    first_pone_play_algorithm_group.add_argument(
        "--first-pone-play-15-else-pair-else-31-else-highest-count",
        action="store_true",
    )
    first_pone_play_algorithm_group.add_argument(
        "--first-pone-play-run-else-15-else-pair-else-31-else-highest-count",
        action="store_true",
    )
    first_pone_play_algorithm_group.add_argument(
        "--first-pone-play-low-lead-else-run-else-15-else-pair-else-31-else-highest-count",
        action="store_true",
    )
    first_pone_play_algorithm_group.add_argument(
        "--first-pone-play-low-lead-else-run-else-15-else-pair-else-31-else-16-to-20-count-else-highest-count",
        action="store_true",
    )
    first_pone_play_algorithm_group.add_argument(
        "--first-pone-play-low-lead-else-pairs-royale-else-run-else-15-else-pair-else-31-else-16-to-20-count-else-highest-count",
        action="store_true",
    )

    parser.add_argument(
        "--first-pone-play-based-on-simulations",
        help="have first pone play the cards which on average maximize pone minus dealer game otherwise scored points in simulated single hands",
        type=int,
    )

    first_dealer_play_algorithm_group = parser.add_mutually_exclusive_group()
    first_dealer_play_algorithm_group.add_argument(
        "--first-dealer-play-user-entered",
        action="store_true",
        help="prompt user to enter first dealer plays",
    )
    first_dealer_play_algorithm_group.add_argument(
        "--first-dealer-play-first",
        action="store_true",
        help="have first dealer play first legal card from hand",
    )
    first_dealer_play_algorithm_group.add_argument(
        "--first-dealer-play-random",
        action="store_true",
        help="have first dealer play random legal card from hand",
    )
    first_dealer_play_algorithm_group.add_argument(
        "--first-dealer-play-highest-count",
        action="store_true",
        help="have first dealer play highest count legal card from hand",
    )
    first_dealer_play_algorithm_group.add_argument(
        "--first-dealer-play-15-or-31-else-highest-count",
        action="store_true",
        help="have first dealer play 15-2 or 31 for 2 otherwise the highest count legal card from hand",
    )
    first_dealer_play_algorithm_group.add_argument(
        "--first-dealer-play-pair-else-15-or-31-else-highest-count",
        action="store_true",
    )
    first_dealer_play_algorithm_group.add_argument(
        "--first-dealer-play-15-else-pair-else-31-else-highest-count",
        action="store_true",
    )
    first_dealer_play_algorithm_group.add_argument(
        "--first-dealer-play-run-else-15-else-pair-else-31-else-highest-count",
        action="store_true",
    )
    first_dealer_play_algorithm_group.add_argument(
        "--first-dealer-play-low-lead-else-run-else-15-else-pair-else-31-else-highest-count",
        action="store_true",
    )
    first_dealer_play_algorithm_group.add_argument(
        "--first-dealer-play-low-lead-else-run-else-15-else-pair-else-31-else-16-to-20-count-else-highest-count",
        action="store_true",
    )
    first_dealer_play_algorithm_group.add_argument(
        "--first-dealer-play-low-lead-else-pairs-royale-else-run-else-15-else-pair-else-31-else-16-to-20-count-else-highest-count",
        action="store_true",
    )

    parser.add_argument(
        "--first-dealer-play-based-on-simulations",
        help="have first dealer play the cards which on average minimize pone minus dealer game otherwise scored points in simulated single hands",
        type=int,
    )

    parser.add_argument(
        "--select-each-post-initial-play",
        action="store_true",
        help="have the next play to play post initial played card rotate through each possible play per simulated hand",
    )

    game_count_group = parser.add_mutually_exclusive_group()
    game_count_group.add_argument(
        "--game-count",
        help="number of cribbage games to simulate",
        type=int,
        default=1,
    )
    game_count_group.add_argument(
        "--infinite-game-count",
        action="store_true",
        help="simulate an infinite number of cribbage games",
    )

    hand_count_group = parser.add_mutually_exclusive_group()
    hand_count_group.add_argument(
        "--maximum-hands-per-game",
        help="maximum number of cribbage hands to simulate per game",
        type=int,
        default=1,
    )
    hand_count_group.add_argument(
        "--unlimited-hands-per-game",
        action="store_true",
        help="simulate an unlimited number of hands per game",
    )

    parser.add_argument(
        "--hide-workers-start-message",
        action="store_true",
        help="hide the workers startup details message",
    )
    parser.add_argument(
        "--hide-first-pone-hands",
        action="store_true",
        help="suppress output of first pone dealt hand and discard",
    )
    parser.add_argument(
        "--hide-first-dealer-hands",
        action="store_true",
        help="suppress output of first dealer hand and discard",
    )
    parser.add_argument(
        "--hide-play-actions",
        action="store_true",
        help="suppress output of play actions (cards played, Go, points scored, count reset)",
    )
    parser.add_argument(
        "--tally-start-of-hand-position-results",
        action="store_true",
    )
    parser.add_argument(
        "--estimate-incomplete-game-wins-and-game-points",
        action="store_true",
    )
    parser.add_argument(
        "--show-calc-cache-usage-stats",
        action="store_true",
        help="show calculation cache usage statistics",
    )
    parser.add_argument(
        "--games-per-update",
        help="number of games to similate per statistics update",
        type=int,
        default=5000,
    )
    parser.add_argument(
        "--confidence-level",
        help="statistical confidence level percentage of outputted confidence intervals",
        type=float,
        default=95,
    )

    parser.add_argument(
        "--first-pone-dealt-cards",
        help="cards dealt to first pone",
    )
    parser.add_argument(
        "--first-dealer-dealt-cards",
        help="cards dealt to first dealer",
    )

    parser.add_argument(
        "--first-pone-kept-cards",
        help="cards kept by first pone",
    )
    parser.add_argument(
        "--first-dealer-kept-cards",
        help="cards kept by first dealer",
    )

    parser.add_argument("--initial-starter")

    parser.add_argument("--initial-pone-score")
    parser.add_argument("--initial-dealer-score")
    parser.add_argument(
        "--initial-play-actions",
        help="play actions (cards or 'go') already taken in the current hand in their taken order",
    )

    args = parser.parse_args()

    [
        first_pone_dealt_cards,
        first_dealer_dealt_cards,
        first_pone_kept_cards,
        first_dealer_kept_cards,
    ] = [
        parse_cards(specifier)
        for specifier in [
            args.first_pone_dealt_cards,
            args.first_dealer_dealt_cards,
            args.first_pone_kept_cards,
            args.first_dealer_kept_cards,
        ]
    ]
    initial_starter: Optional[Card] = (
        Card.from_string(args.initial_starter) if args.initial_starter else None
    )
    initial_play_actions: List[PlayAction] = parse_play_actions(
        args.initial_play_actions
    )

    manager = Manager()
    players_statistics: Dict[NextAction, Statistics] = manager.dict()
    players_statistics_lock = Lock()
    game_count = (
        sys.maxsize
        if args.infinite_game_count
        else (math.ceil(args.game_count / args.process_count) * args.process_count)
    )
    maximum_hands_per_game = (
        sys.maxsize if args.unlimited_hands_per_game else args.maximum_hands_per_game
    )
    if not args.hide_workers_start_message:
        print(
            f"Simulating {game_count if game_count != sys.maxsize else 'infinite'} games of up to {maximum_hands_per_game if maximum_hands_per_game != sys.maxsize else 'unlimited'} hands each",
            end="" if args.process_count > 1 else os.linesep,
            flush=args.process_count == 1,
        )
        if args.process_count > 1:
            print(
                f" with {args.process_count} worker process{'es' if args.process_count > 1 else ''}",
                flush=True,
            )
        print()

    # TODO: eliminate snake case to kebab case args names duplication from code
    if args.first_pone_keep_user_selected:
        first_pone_select_kept_cards = keep_user_selected
    elif args.first_pone_keep_random:
        first_pone_select_kept_cards = keep_random
    elif args.first_pone_keep_first_four:
        first_pone_select_kept_cards = keep_first_four
    elif args.first_pone_maximize_pre_cut_hand_points_ignoring_suit:
        first_pone_select_kept_cards = keep_max_pre_cut_hand_points_ignoring_suit
    elif args.first_pone_maximize_pre_cut_hand_points:
        first_pone_select_kept_cards = keep_max_pre_cut_hand_points
    elif args.first_pone_maximize_post_cut_hand_points_ignoring_suit:
        first_pone_select_kept_cards = keep_max_post_cut_hand_points_ignoring_suit
    elif args.first_pone_maximize_post_cut_hand_points:
        first_pone_select_kept_cards = keep_max_post_cut_hand_points
    elif args.first_pone_maximize_post_cut_hand_minus_crib_points_ignoring_suit:
        first_pone_select_kept_cards = (
            keep_max_post_cut_hand_minus_crib_points_ignoring_suit
        )
    elif args.first_pone_maximize_post_cut_hand_minus_crib_points:
        first_pone_select_kept_cards = keep_max_post_cut_hand_minus_crib_points
    else:
        first_pone_select_kept_cards = DEFAULT_SELECT_PONE_KEPT_CARDS

    if args.first_dealer_keep_user_selected:
        first_dealer_select_kept_cards = keep_user_selected
    elif args.first_dealer_keep_random:
        first_dealer_select_kept_cards = keep_random
    elif args.first_dealer_keep_first_four:
        first_dealer_select_kept_cards = keep_first_four
    elif args.first_dealer_maximize_pre_cut_hand_points_ignoring_suit:
        first_dealer_select_kept_cards = keep_max_pre_cut_hand_points_ignoring_suit
    elif args.first_dealer_maximize_pre_cut_hand_points:
        first_dealer_select_kept_cards = keep_max_pre_cut_hand_points
    elif args.first_dealer_maximize_post_cut_hand_points_ignoring_suit:
        first_dealer_select_kept_cards = keep_max_post_cut_hand_points_ignoring_suit
    elif args.first_dealer_maximize_post_cut_hand_points:
        first_dealer_select_kept_cards = keep_max_post_cut_hand_points
    elif args.first_dealer_maximize_post_cut_hand_plus_crib_points_ignoring_suit:
        first_dealer_select_kept_cards = (
            keep_max_post_cut_hand_plus_crib_points_ignoring_suit
        )
    elif args.first_dealer_maximize_post_cut_hand_plus_crib_points:
        first_dealer_select_kept_cards = keep_max_post_cut_hand_plus_crib_points
    else:
        first_dealer_select_kept_cards = DEFAULT_SELECT_DEALER_KEPT_CARDS

    first_pone_select_play: PlaySelector
    if args.first_pone_play_user_entered:
        first_pone_select_play = play_user_selected
    elif args.first_pone_play_first:
        first_pone_select_play = play_first
    elif args.first_pone_play_random:
        first_pone_select_play = play_random
    elif args.first_pone_play_highest_count:
        first_pone_select_play = play_highest_count
    elif args.first_pone_play_15_or_31_else_highest_count:
        first_pone_select_play = play_15_or_31_else_highest_count
    elif args.first_pone_play_pair_else_15_or_31_else_highest_count:
        first_pone_select_play = play_pair_else_15_or_31_else_highest_count
    elif args.first_pone_play_15_else_pair_else_31_else_highest_count:
        first_pone_select_play = play_15_else_pair_else_31_else_highest_count
    elif args.first_pone_play_run_else_15_else_pair_else_31_else_highest_count:
        first_pone_select_play = play_run_else_15_else_pair_else_31_else_highest_count
    elif (
        args.first_pone_play_low_lead_else_run_else_15_else_pair_else_31_else_highest_count
    ):
        first_pone_select_play = (
            play_low_lead_else_run_else_15_else_pair_else_31_else_highest_count
        )
    elif (
        args.first_pone_play_low_lead_else_run_else_15_else_pair_else_31_else_16_to_20_count_else_highest_count
    ):
        first_pone_select_play = play_low_lead_else_run_else_15_else_pair_else_31_else_16_to_20_count_else_highest_count
    elif (
        args.first_pone_play_low_lead_else_pairs_royale_else_run_else_15_else_pair_else_31_else_16_to_20_count_else_highest_count
    ):
        first_pone_select_play = play_low_lead_else_pairs_royale_else_run_else_15_else_pair_else_31_else_16_to_20_count_else_highest_count
    else:
        first_pone_select_play = DEFAULT_SELECT_PLAY

    dealer_play_selector: PlaySelector
    if args.first_dealer_play_user_entered:
        first_dealer_select_play = play_user_selected
    elif args.first_dealer_play_first:
        first_dealer_select_play = play_first
    elif args.first_dealer_play_random:
        first_dealer_select_play = play_random
    elif args.first_dealer_play_highest_count:
        first_dealer_select_play = play_highest_count
    elif args.first_dealer_play_15_or_31_else_highest_count:
        first_dealer_select_play = play_15_or_31_else_highest_count
    elif args.first_dealer_play_pair_else_15_or_31_else_highest_count:
        first_dealer_select_play = play_pair_else_15_or_31_else_highest_count
    elif args.first_dealer_play_15_else_pair_else_31_else_highest_count:
        first_dealer_select_play = play_15_else_pair_else_31_else_highest_count
    elif args.first_dealer_play_run_else_15_else_pair_else_31_else_highest_count:
        first_dealer_select_play = play_run_else_15_else_pair_else_31_else_highest_count
    elif (
        args.first_dealer_play_low_lead_else_run_else_15_else_pair_else_31_else_highest_count
    ):
        first_dealer_select_play = (
            play_low_lead_else_run_else_15_else_pair_else_31_else_highest_count
        )
    elif (
        args.first_dealer_play_low_lead_else_run_else_15_else_pair_else_31_else_16_to_20_count_else_highest_count
    ):
        first_dealer_select_play = play_low_lead_else_run_else_15_else_pair_else_31_else_16_to_20_count_else_highest_count
    elif (
        args.first_dealer_play_low_lead_else_pairs_royale_else_run_else_15_else_pair_else_31_else_16_to_20_count_else_highest_count
    ):
        first_dealer_select_play = play_low_lead_else_pairs_royale_else_run_else_15_else_pair_else_31_else_16_to_20_count_else_highest_count
    else:
        first_dealer_select_play = DEFAULT_SELECT_PLAY

    initial_pone_score = Points(
        int(args.initial_pone_score) if args.initial_pone_score else 0
    )
    initial_dealer_score = Points(
        int(args.initial_dealer_score) if args.initial_dealer_score else 0
    )

    tally_start_of_hand_position_results: bool = (
        args.tally_start_of_hand_position_results
        and args.process_count == 1
        and not first_pone_dealt_cards
        and not first_dealer_dealt_cards
        and not first_pone_kept_cards
        and not first_dealer_kept_cards
        and not initial_starter
        and not initial_play_actions
        and first_pone_select_kept_cards == DEFAULT_SELECT_PONE_KEPT_CARDS
        and first_dealer_select_kept_cards == DEFAULT_SELECT_DEALER_KEPT_CARDS
        and first_pone_select_play == DEFAULT_SELECT_PLAY
        and first_dealer_select_play == DEFAULT_SELECT_PLAY
        and initial_pone_score == 0
        and initial_dealer_score == 0
        and not args.first_pone_select_each_possible_kept_hand
        and not args.first_dealer_select_each_possible_kept_hand
        and not args.select_each_post_initial_play
    )
    start_of_hand_position_results_tallies: shelve.DbfilenameShelf
    start_of_hand_position_results_tallies_shelf_name: str = (
        "start_of_hand_position_results_tallies_shelf"
    )
    try:
        start_of_hand_position_results_tallies = shelve.open(
            start_of_hand_position_results_tallies_shelf_name,
            flag=("c" if tally_start_of_hand_position_results else "r"),
        )
    except Exception:
        start_of_hand_position_results_tallies = shelve.open(
            start_of_hand_position_results_tallies_shelf_name
        )

    start_time_ns = time.time_ns()
    simulate_games_args = (
        game_count // args.process_count,
        game_count,
        maximum_hands_per_game,
        initial_pone_score,
        initial_dealer_score,
        first_pone_dealt_cards,
        first_dealer_dealt_cards,
        first_pone_kept_cards,
        first_dealer_kept_cards,
        initial_starter,
        initial_play_actions,
        players_statistics,
        players_statistics_lock,
        first_pone_select_kept_cards,
        args.first_pone_discard_based_on_simulations,
        args.first_pone_select_each_possible_kept_hand,
        first_dealer_select_kept_cards,
        args.first_dealer_discard_based_on_simulations,
        args.first_dealer_select_each_possible_kept_hand,
        first_pone_select_play,
        args.first_pone_play_based_on_simulations,
        first_dealer_select_play,
        args.first_dealer_play_based_on_simulations,
        tally_start_of_hand_position_results,
        args.estimate_incomplete_game_wins_and_game_points,
        start_of_hand_position_results_tallies,
        args.select_each_post_initial_play,
        args.hide_first_pone_hands,
        args.hide_first_dealer_hands,
        bool(args.hide_play_actions),
        args.games_per_update,
        True,
        args.confidence_level,
        start_time_ns,
        args.show_calc_cache_usage_stats,
    )
    if args.process_count == 1:
        simulate_games(*simulate_games_args)
    else:
        processes = [
            Process(target=simulate_games, args=simulate_games_args)
            for process_number in range(args.process_count)
        ]
        for process in processes:
            process.start()
        try:
            for process in processes:
                process.join()
        except KeyboardInterrupt:
            sys.exit(0)

    print(
        f"Simulated {get_length_across_all_keys(players_statistics)} games with {args.process_count} worker processes at {simulation_performance_statistics(start_time_ns, game_count)}"
    )
