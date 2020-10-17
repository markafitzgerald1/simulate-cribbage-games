# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import sys
import random
import time
from multiprocessing import Process, cpu_count, Manager, Lock
import math
import argparse
import os
from runstats import Statistics
from statistics import NormalDist
import itertools
from functools import cache


class Card:
    """A French playing card"""

    indices = "A23456789TJQK"
    suits = "♣♦♥♠"
    english_suits = "CDHS"

    def __init__(self, index, suit):
        self.index = index
        self.suit = suit
        self.count = min(index + 1, 10)
        self.str = f"{Card.indices[index]}{Card.suits[suit]}"

    @classmethod
    def from_string(cls, specifier):
        return Card(
            Card.indices.find(specifier[0].capitalize()),
            max(
                Card.english_suits.find(specifier[1].capitalize()),
                Card.suits.find(specifier[1]),
            ),
        )

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


def parse_cards(specifier):
    return [
        Card.from_string(card_specifier)
        for card_specifier in (specifier.split(",") if specifier else [])
    ]


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


PAIR_POINTS = 2
FIFTEENS_POINTS = 2
FIFTEEN_COUNT = 15


KEPT_CARDS_LEN = 4


@cache
def hand_counts_fifteens_points(sorted_hand_plus_starter_counts):
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
    return hand_counts_fifteens_points(sorted_hand_plus_starter_counts)


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

    if is_crib and starter.suit == kept_hand_suits[0]:
        return 5

    return 4


JACK_INDEX = 10


def nobs_points(kept_hand, starter):
    for kept_card in kept_hand:
        if kept_card.index == JACK_INDEX and kept_card.suit == starter.suit:
            return 1

    return 0


def score_hand(kept_hand, starter, is_crib=False):
    hand_plus_starter_cards = kept_hand + [starter]
    return (
        pairs_plus_runs_points(hand_plus_starter_cards)
        + fifteens_points(hand_plus_starter_cards)
        + flush_points(kept_hand, starter, is_crib=is_crib)
        + nobs_points(kept_hand, starter)
    )


def formatted_hand_count(hands_simulated, total_hands_to_be_simulated):
    return f"n = {hands_simulated:{int(math.log10(total_hands_to_be_simulated)) + 1}}"


def get_confidence_interval(statistics, confidence_level):
    if len(statistics) == 1:
        return f"{statistics.mean():+9.5f}"

    z_statistic = NormalDist().inv_cdf(1 - (1 - confidence_level / 100) / 2)
    return f"{statistics.mean():+9.5f} ± {z_statistic * statistics.stddev() / math.sqrt(len(statistics)):8.5f}"


def statistics_push(statistics_dict, key, value):
    if key not in statistics_dict:
        statistics_dict[key] = Statistics()
    statistics_dict[key].push(value)


def statistics_dict_add(
    sum_stats_by_keep_by_type, stat_type_name, addend_stats_by_keep
):
    for keep, addend_stats in addend_stats_by_keep.items():
        if keep in sum_stats_by_keep_by_type:
            new_sum_stats_for_keep = sum_stats_by_keep_by_type[keep]
        else:
            new_sum_stats_for_keep = {
                "pone_play": Statistics(),
                "pone_hand": Statistics(),
                "pone": Statistics(),
                "dealer_play": Statistics(),
                "dealer_hand": Statistics(),
                "pone_minus_dealer_hand": Statistics(),
                "crib": Statistics(),
                "dealer": Statistics(),
                "pone_minus_dealer_play": Statistics(),
                "pone_minus_dealer": Statistics(),
            }

        new_sum_stats_for_keep[stat_type_name] += addend_stats
        sum_stats_by_keep_by_type[keep] = new_sum_stats_for_keep


def simulate_hands(
    process_hand_count,
    overall_hand_count,
    pone_dealt_cards,
    dealer_dealt_cards,
    pone_kept_cards,
    dealer_kept_cards,
    players_statistics,
    players_statistics_lock,
    pone_select_kept_cards,
    dealer_select_kept_cards,
    pone_select_play,
    dealer_select_play,
    hide_pone_hand,
    hide_dealer_hand,
    hide_play_actions,
    hands_per_update,
    confidence_level,
):
    try:
        DEALT_CARDS_LEN = 6
        if len(pone_dealt_cards) not in [0, DEALT_CARDS_LEN] or len(
            dealer_dealt_cards
        ) not in [0, DEALT_CARDS_LEN]:
            raise ValueError(
                f"If specifying player dealt cards exactly {DEALT_CARDS_LEN} must be specified"
            )

        if len(pone_kept_cards) not in [0, KEPT_CARDS_LEN] or len(
            dealer_kept_cards
        ) not in [0, KEPT_CARDS_LEN]:
            raise ValueError(
                f"If specifying player kept cards exactly {KEPT_CARDS_LEN} must be specified"
            )

        deck_less_fixed_cards = [
            Card(number % 13, number // 13)
            for number in range(52)
            if Card(number % 13, number // 13) not in pone_dealt_cards
            and Card(number % 13, number // 13) not in dealer_dealt_cards
        ]
        (
            pone_statistics,
            pone_play_statistics,
            pone_hand_statistics,
            dealer_statistics,
            dealer_play_statistics,
            dealer_hand_statistics,
            crib_statistics,
            pone_minus_dealer_play_statistics,
            pone_minus_dealer_hand_statistics,
            pone_minus_dealer_statistics,
        ) = (
            {},
            {},
            {},
            {},
            {},
            {},
            {},
            {},
            {},
            {},
        )
        pone_dealt_cards_possible_keeps = itertools.cycle(
            itertools.combinations(pone_dealt_cards, KEPT_CARDS_LEN)
        )
        dealer_dealt_cards_possible_keeps = itertools.cycle(
            itertools.combinations(dealer_dealt_cards, KEPT_CARDS_LEN)
        )
        for hand in range(process_hand_count):
            if pone_dealt_cards or dealer_dealt_cards:
                random_hand_cards = random.sample(
                    deck_less_fixed_cards, DEALT_CARDS_LEN
                )
                if pone_dealt_cards:
                    dealt_hands = [pone_dealt_cards.copy(), random_hand_cards]
                else:
                    dealt_hands = [random_hand_cards, dealer_dealt_cards.copy()]
            else:
                random_hand_cards = random.sample(
                    deck_less_fixed_cards, DEALT_CARDS_LEN * 2
                )
                dealt_hands = [
                    random_hand_cards[0:DEALT_CARDS_LEN],
                    random_hand_cards[DEALT_CARDS_LEN:],
                ]
            if not hide_pone_hand:
                print(f"{get_player_name(0):6} dealt {Hand(dealt_hands[0])}")
            if not hide_dealer_hand:
                print(f"{get_player_name(1):6} dealt {Hand(dealt_hands[1])}")
            deck_less_dealt_cards = list(
                set(deck_less_fixed_cards).difference(set(random_hand_cards))
            )

            if pone_kept_cards:
                kept_pone_hand = [
                    card for card in dealt_hands[0] if card in pone_kept_cards
                ]
            elif pone_select_kept_cards:
                kept_pone_hand = pone_select_kept_cards(dealt_hands[0])
            elif pone_dealt_cards:
                kept_pone_hand = list(next(pone_dealt_cards_possible_keeps))
            else:
                raise ValueError(
                    "Iterating through all possible kept hands not supported with non-fixed deals."
                )

            if dealer_kept_cards:
                kept_dealer_hand = [
                    card for card in dealt_hands[1] if card in dealer_kept_cards
                ]
            elif dealer_select_kept_cards:
                kept_dealer_hand = dealer_select_kept_cards(dealt_hands[1])
            elif dealer_dealt_cards:
                kept_dealer_hand = list(next(dealer_dealt_cards_possible_keeps))
            else:
                raise ValueError(
                    "Iterating through all possible kept hands not supported with non-fixed deals."
                )

            kept_hands = [kept_pone_hand, kept_dealer_hand]
            hands = [kept_hand.copy() for kept_hand in kept_hands]

            pone_discarded_cards = (
                [card for card in dealt_hands[0] if card not in pone_kept_cards]
                if pone_kept_cards
                else [card for card in dealt_hands[0] if card not in kept_hands[0]]
            )
            if not hide_pone_hand:
                print(f"{get_player_name(0):6} discarded {Hand(pone_discarded_cards)}")
            dealer_discarded_cards = (
                [card for card in dealt_hands[1] if card not in dealer_kept_cards]
                if dealer_kept_cards
                else [card for card in dealt_hands[1] if card not in kept_hands[1]]
            )
            if not hide_dealer_hand:
                print(
                    f"{get_player_name(1):6} discarded {Hand(dealer_discarded_cards)}"
                )

            if len(hands[0]) != KEPT_CARDS_LEN or len(hands[1]) != KEPT_CARDS_LEN:
                raise ValueError(
                    f"Kept non-{KEPT_CARDS_LEN} number of cards in one of {Hand(hands[0])} or {Hand(hands[1])}"
                )

            if not hide_pone_hand:
                print(f"{get_player_name(0):6} kept {Hand(hands[0])}")
            if not hide_dealer_hand:
                print(f"{get_player_name(1):6} kept {Hand(hands[1])}")

            score = [0, 0]

            starter = random.sample(deck_less_dealt_cards, 1)[0]
            if not hide_play_actions:
                print(f"Cut/starter card is: {starter}")
            if starter.index == 10:
                if not hide_play_actions:
                    print(f"His heels/nibs for 2 for {get_player_name(1)}")
                score[1] += 2

            player_to_play = 0
            play_count = 0
            consecutive_go_count = 0
            most_recently_played_index = None
            most_recently_played_index_count = 0
            current_play_plays = []
            while hands[0] or hands[1]:
                playable_cards = [
                    card
                    for card in hands[player_to_play]
                    if play_count + card.count <= 31
                ]

                if playable_cards:
                    player_to_play_play = playable_cards[
                        pone_select_play(playable_cards)
                        if player_to_play == 0
                        else dealer_select_play(playable_cards)
                    ]
                    hands[player_to_play].remove(player_to_play_play)
                    current_play_plays.append(player_to_play_play)
                    play_count += player_to_play_play.count
                    if not hide_play_actions:
                        print(
                            f"{get_player_name(player_to_play):6} plays {player_to_play_play} for {play_count}"
                        )

                    # Pairs points
                    if player_to_play_play.index == most_recently_played_index:
                        most_recently_played_index_count += 1
                        if most_recently_played_index_count == 4:
                            if not hide_play_actions:
                                print(
                                    f"!Double pairs royale for 12 points for {get_player_name(player_to_play)}."
                                )
                            score[player_to_play] += 12
                        elif most_recently_played_index_count == 3:
                            if not hide_play_actions:
                                print(
                                    f"!Pairs royale for 6 points for {get_player_name(player_to_play)}."
                                )
                            score[player_to_play] += 6
                        elif most_recently_played_index_count == 2:
                            if not hide_play_actions:
                                print(
                                    f"!Pair for 2 points for {get_player_name(player_to_play)}."
                                )
                            score[player_to_play] += PAIR_POINTS
                    else:
                        most_recently_played_index = player_to_play_play.index
                        most_recently_played_index_count = 1

                    # 15 and 31 count points
                    if play_count == FIFTEEN_COUNT:
                        if not hide_play_actions:
                            print(
                                f"!{FIFTEEN_COUNT} for 2 points for {get_player_name(player_to_play)}."
                            )
                        score[player_to_play] += FIFTEENS_POINTS
                    elif play_count == 31:
                        if not hide_play_actions:
                            print(
                                f"!31 for 1 point for {get_player_name(player_to_play)}."
                            )
                        score[player_to_play] += 1

                    # Runs points
                    for run_length in reversed(range(3, len(current_play_plays) + 1)):
                        sorted_recent_play_indices = sorted(
                            [play.index for play in current_play_plays[-run_length:]]
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
                            if not hide_play_actions:
                                print(
                                    f"!Run for {run_length} points for {get_player_name(player_to_play)}."
                                )
                            score[player_to_play] += run_length
                            break

                    consecutive_go_count = 0
                else:
                    if not hide_play_actions:
                        print(f'{get_player_name(player_to_play):6} says "Go!"')
                    consecutive_go_count += 1
                    if consecutive_go_count == 2:
                        if not hide_play_actions:
                            print(
                                f"!Go for 1 point for {get_player_name(player_to_play)}."
                            )
                        score[player_to_play] += 1

                        if not hide_play_actions:
                            print("---resetting play count to 0---")
                        consecutive_go_count = 0
                        play_count = 0
                        current_play_plays = []
                        most_recently_played_index = None
                        most_recently_played_index_count = 0

                player_to_play = (player_to_play + 1) % 2

            # Last Card points
            last_player_to_play = (player_to_play + 1) % 2
            if not hide_play_actions:
                print(
                    f"!Last card for 1 point for {get_player_name(last_player_to_play)}."
                )
            score[last_player_to_play] += 1

            pone_hand_points = score_hand(kept_hands[0], starter)
            if not hide_play_actions:
                print(
                    f"Pone hand {Hand(reversed(sorted(kept_hands[0])))} with starter {starter} points: {pone_hand_points}"
                )

            dealer_hand_points = score_hand(kept_hands[1], starter)
            if not hide_play_actions:
                print(
                    f"Dealer hand {Hand(reversed(sorted(kept_hands[1])))} with starter {starter} points: {dealer_hand_points}"
                )

            crib_cards = pone_discarded_cards + dealer_discarded_cards
            crib_points = score_hand(crib_cards, starter, is_crib=True)
            if not hide_play_actions:
                print(
                    f"Crib {Hand(reversed(sorted(crib_cards)))} with starter {starter} points: {crib_points}"
                )

            if not hide_play_actions:
                print(f"Hand cut + play + hands + crib score: {score}")

            if pone_dealt_cards and not pone_kept_cards:
                kept_cards = tuple(kept_pone_hand)
            elif dealer_dealt_cards and not dealer_kept_cards:
                kept_cards = tuple(kept_dealer_hand)
            else:
                kept_cards = None

            statistics_push(pone_play_statistics, kept_cards, score[0])
            statistics_push(pone_hand_statistics, kept_cards, pone_hand_points)
            statistics_push(pone_statistics, kept_cards, pone_hand_points)
            statistics_push(dealer_play_statistics, kept_cards, score[1])
            statistics_push(dealer_hand_statistics, kept_cards, dealer_hand_points)
            statistics_push(crib_statistics, kept_cards, crib_points)
            statistics_push(
                dealer_statistics,
                kept_cards,
                score[1] + dealer_hand_points + crib_points,
            )
            statistics_push(
                pone_minus_dealer_play_statistics, kept_cards, score[0] - score[1]
            )
            statistics_push(
                pone_minus_dealer_hand_statistics,
                kept_cards,
                pone_hand_points - dealer_hand_points,
            )
            statistics_push(
                pone_minus_dealer_statistics,
                kept_cards,
                score[0]
                + pone_hand_points
                - score[1]
                - dealer_hand_points
                - crib_points,
            )

            if (
                hand % hands_per_update == hands_per_update - 1
                or hand == process_hand_count - 1
            ):
                players_statistics_lock.acquire()

                statistics_dict_add(
                    players_statistics, "pone_play", pone_play_statistics
                )
                pone_play_statistics.clear()

                statistics_dict_add(
                    players_statistics, "pone_hand", pone_hand_statistics
                )
                pone_hand_statistics.clear()

                statistics_dict_add(players_statistics, "pone", pone_statistics)
                pone_statistics.clear()

                statistics_dict_add(
                    players_statistics, "dealer_play", dealer_play_statistics
                )
                dealer_play_statistics.clear()

                statistics_dict_add(
                    players_statistics, "dealer_hand", dealer_hand_statistics
                )
                dealer_hand_statistics.clear()

                statistics_dict_add(players_statistics, "crib", crib_statistics)
                crib_statistics.clear()

                statistics_dict_add(players_statistics, "dealer", dealer_statistics)
                dealer_statistics.clear()

                statistics_dict_add(
                    players_statistics,
                    "pone_minus_dealer_play",
                    pone_minus_dealer_play_statistics,
                )
                pone_minus_dealer_play_statistics.clear()

                statistics_dict_add(
                    players_statistics,
                    "pone_minus_dealer_hand",
                    pone_minus_dealer_hand_statistics,
                )
                pone_minus_dealer_hand_statistics.clear()

                statistics_dict_add(
                    players_statistics,
                    "pone_minus_dealer",
                    pone_minus_dealer_statistics,
                )
                pone_minus_dealer_statistics.clear()

                players_statistics_length = len(players_statistics[kept_cards]["pone"])
                z_statistic = NormalDist().inv_cdf(1 - (1 - confidence_level / 100) / 2)

                # TODO: calculate correlation based on overall stats and per keep, not interval stats
                # if players_statistics_length > 1:
                #     dealer_stddev = players_statistics["dealer"].stddev()
                #     pone_stddev = players_statistics["pone"].stddev()
                #     pone_minus_dealer_stddev = players_statistics[
                #         "pone_minus_dealer"
                #     ].stddev()
                # else:
                #     dealer_stddev, pone_stddev, pone_minus_dealer_stddev = 0, 0, 0
                # correlation = (
                #     (pone_minus_dealer_stddev ** 2 - pone_stddev ** 2 - dealer_stddev ** 2)
                #     / (2 * pone_stddev * dealer_stddev)
                #     if pone_stddev != 0 and dealer_stddev != 0
                #     else None
                # )

                if players_statistics_length > 1:
                    print(
                        f"Mean play statistics {confidence_level}% confidence intervals ({formatted_hand_count(players_statistics_length, overall_hand_count)}):"
                    )
                else:
                    print(f"Mean play statistics:")

                sorted_players_statistics = sorted(
                    players_statistics.items(),
                    key=lambda item: item[1]["pone_minus_dealer"].mean(),
                    reverse=bool(pone_dealt_cards),
                )
                for keep, keep_stats in sorted_players_statistics:
                    if keep:
                        # print(
                        #     f"For kept {Hand(keep)}, discard {Hand(set(pone_dealt_cards or dealer_dealt_cards) - set(keep))}: "
                        # )
                        print(
                            f"{Hand(keep)} - {Hand(set(pone_dealt_cards or dealer_dealt_cards) - set(keep))}: {keep_stats['pone_minus_dealer_play'].mean():+9.5f} Δ-peg + {keep_stats['pone_minus_dealer_hand'].mean():+9.5f} Δ-hand - {keep_stats['crib'].mean():+9.5f} crib = {get_confidence_interval(keep_stats['pone_minus_dealer'], confidence_level)} overall"
                        )
                    if (
                        abs(
                            keep_stats["pone_minus_dealer"].mean()
                            - sorted_players_statistics[0][1][
                                "pone_minus_dealer"
                            ].mean()
                        )
                        < 2  # TODO: convert into command-line option
                    ):
                        print(
                            f"Pone              Play    points: {get_confidence_interval(keep_stats['pone_play'], confidence_level)}"
                        )
                        print(
                            f"Dealer            Play    points: {get_confidence_interval(keep_stats['dealer_play'], confidence_level)}"
                        )
                        print(
                            f"Pone minus Dealer Play    points: {get_confidence_interval(keep_stats['pone_minus_dealer_play'], confidence_level)}"
                        )
                        print(
                            f"Pone              Hand    points: {get_confidence_interval(keep_stats['pone_hand'], confidence_level)}"
                        )
                        print(
                            f"Pone              Overall points: {get_confidence_interval(keep_stats['pone'], confidence_level)}"
                        )
                        print(
                            f"Dealer            Hand    points: {get_confidence_interval(keep_stats['dealer_hand'], confidence_level)}"
                        )
                        print(
                            f"Pone minus Dealer Hand    points: {get_confidence_interval(keep_stats['pone_minus_dealer_hand'], confidence_level)}"
                        )
                        print(
                            f"Crib              Hand    points: {get_confidence_interval(keep_stats['crib'], confidence_level)}"
                        )
                        print(
                            f"Dealer            Overall points: {get_confidence_interval(keep_stats['dealer'], confidence_level)}"
                        )
                        print(
                            f"Pone minus Dealer Overall points: {get_confidence_interval(keep_stats['pone_minus_dealer'], confidence_level)}"
                        )

                # correlation_str = f"{correlation:+8.5f}" if correlation else "undefined"
                # print(f"Pone   and Dealer Overall points correlation: {correlation_str}")
                players_statistics_lock.release()
    except KeyboardInterrupt:
        sys.exit(0)


def keep_random(dealt_cards):
    return random.sample(dealt_cards, KEPT_CARDS_LEN)


def keep_first_four(dealt_cards):
    return dealt_cards[0:KEPT_CARDS_LEN]


def play_first(playable_cards):
    return 0


def play_random(playable_cards):
    return random.randrange(0, len(playable_cards))


def play_highest_count(playable_cards):
    play_card = None
    play_index = None
    for index, card in enumerate(playable_cards):
        if not play_card or card.count > play_card.count:
            play_card = card
            play_index = index
    return play_index


def play_user_selected(playable_cards):
    print(f"Playable cards are {','.join([str(card) for card in playable_cards])}.")
    selected_card = None
    while selected_card not in range(0, len(playable_cards)):
        selected_card_input = input("Enter the base-0 card index to play: ")
        try:
            selected_card = int(selected_card_input)
        except ValueError:
            print(f"{selected_card_input} is not a valid selection")
    return selected_card


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--process-count",
        help="number of processes to use to simulate cribbage hand plays",
        type=int,
        default=1,
    )

    pone_discard_algorithm_group = parser.add_mutually_exclusive_group()
    pone_discard_algorithm_group.add_argument(
        "--pone-keep-random",
        action="store_true",
        help="have pone discard randomly",
    )
    pone_discard_algorithm_group.add_argument(
        "--pone-keep-each-possibility",
        action="store_true",
        help="have pone discard in each possible manner",
    )
    pone_discard_algorithm_group.add_argument(
        "--pone-keep-first-four",
        action="store_true",
        help="have pone keep the first four cards dealt to pone",
    )

    dealer_discard_algorithm_group = parser.add_mutually_exclusive_group()
    dealer_discard_algorithm_group.add_argument(
        "--dealer-keep-random",
        action="store_true",
        help="have dealer discard randomly",
    )
    dealer_discard_algorithm_group.add_argument(
        "--dealer-keep-each-possibility",
        action="store_true",
        help="have dealer discard in each possible manner",
    )
    dealer_discard_algorithm_group.add_argument(
        "--dealer-keep-first-four",
        action="store_true",
        help="have dealer keep the first four cards dealt to dealer",
    )

    pone_play_algorithm_group = parser.add_mutually_exclusive_group()
    pone_play_algorithm_group.add_argument(
        "--pone-play-user-entered",
        action="store_true",
        help="prompt user to enter pone plays",
    )
    pone_play_algorithm_group.add_argument(
        "--pone-play-first",
        action="store_true",
        help="have pone play first legal card from hand",
    )
    pone_play_algorithm_group.add_argument(
        "--pone-play-random",
        action="store_true",
        help="have pone play random legal card from hand",
    )
    pone_play_algorithm_group.add_argument(
        "--pone-play-highest-count",
        action="store_true",
        help="have pone play highest count legal card from hand",
    )

    dealer_play_algorithm_group = parser.add_mutually_exclusive_group()
    dealer_play_algorithm_group.add_argument(
        "--dealer-play-user-entered",
        action="store_true",
        help="prompt user to enter dealer plays",
    )
    dealer_play_algorithm_group.add_argument(
        "--dealer-play-first",
        action="store_true",
        help="have dealer play first legal card from hand",
    )
    dealer_play_algorithm_group.add_argument(
        "--dealer-play-random",
        action="store_true",
        help="have dealer play random legal card from hand",
    )
    dealer_play_algorithm_group.add_argument(
        "--dealer-play-highest-count",
        action="store_true",
        help="have dealer play highest count legal card from hand",
    )

    hand_count_group = parser.add_mutually_exclusive_group()
    hand_count_group.add_argument(
        "--hand-count",
        help="number of cribbage hand plays to simulate",
        type=int,
        default=1,
    )
    hand_count_group.add_argument(
        "--infinite-hand-count",
        action="store_true",
        help="simulate an infinite number of cribbage hands",
    )
    parser.add_argument(
        "--hide-workers-start-message",
        action="store_true",
        help="hide the workers startup details message",
    )
    parser.add_argument(
        "--hide-pone-hand",
        action="store_true",
        help="suppress output of pone dealt hand and discard",
    )
    parser.add_argument(
        "--hide-dealer-hand",
        action="store_true",
        help="suppress output of dealer hand and discard",
    )
    parser.add_argument(
        "--hide-play-actions",
        action="store_true",
        help="suppress output of play actions (cards played, Go, points scored, count reset)",
    )
    parser.add_argument(
        "--hands-per-update",
        help="number of hands to similate per statistics update",
        type=int,
        default=5000,
    )
    parser.add_argument(
        "--confidence-level",
        help="statistical confidence level percentage of outputted confidence intervals",
        type=float,
        default=95,
    )

    specified_dealt_cards_group = parser.add_mutually_exclusive_group()
    specified_dealt_cards_group.add_argument(
        "--pone-dealt-cards",
        help="cards dealt to pone",
    )
    specified_dealt_cards_group.add_argument(
        "--dealer-dealt-cards",
        help="cards dealt to dealer",
    )

    specified_kept_cards_group = parser.add_mutually_exclusive_group()
    specified_kept_cards_group.add_argument(
        "--pone-kept-cards",
        help="cards kept by pone",
    )
    specified_kept_cards_group.add_argument(
        "--dealer-kept-cards",
        help="cards kept by dealer",
    )

    args = parser.parse_args()

    [pone_dealt_cards, dealer_dealt_cards, pone_kept_cards, dealer_kept_cards] = [
        parse_cards(specifier)
        for specifier in [
            args.pone_dealt_cards,
            args.dealer_dealt_cards,
            args.pone_kept_cards,
            args.dealer_kept_cards,
        ]
    ]

    manager = Manager()
    players_statistics = manager.dict()
    players_statistics_lock = Lock()
    args.hand_count = (
        sys.maxsize
        if args.infinite_hand_count
        else (math.ceil(args.hand_count / args.process_count) * args.process_count)
    )
    if not args.hide_workers_start_message:
        print(
            f"Simulating {args.hand_count if args.hand_count != sys.maxsize else 'infinite'} hands",
            end="" if args.process_count > 1 else os.linesep,
            flush=args.process_count == 1,
        )
        if args.process_count > 1:
            print(
                f" with {args.process_count} worker process{'es' if args.process_count > 1 else ''}",
                flush=True,
            )

    if args.pone_keep_random:
        pone_select_kept_cards = keep_random
    elif args.pone_keep_each_possibility:
        pone_select_kept_cards = None
    else:
        pone_select_kept_cards = keep_first_four

    if args.dealer_keep_random:
        dealer_select_kept_cards = keep_random
    elif args.dealer_keep_each_possibility:
        dealer_select_kept_cards = None
    else:
        dealer_select_kept_cards = keep_first_four

    if args.pone_play_user_entered:
        pone_select_play = play_user_selected
    elif args.pone_play_first:
        pone_select_play = play_first
    elif args.pone_play_random:
        pone_select_play = play_random
    else:
        pone_select_play = play_highest_count

    if args.dealer_play_user_entered:
        dealer_select_play = play_user_selected
    elif args.dealer_play_first:
        dealer_select_play = play_first
    elif args.dealer_play_random:
        dealer_select_play = play_random
    else:
        dealer_select_play = play_highest_count

    simulate_hands_args = (
        args.hand_count // args.process_count,
        args.hand_count,
        pone_dealt_cards,
        dealer_dealt_cards,
        pone_kept_cards,
        dealer_kept_cards,
        players_statistics,
        players_statistics_lock,
        pone_select_kept_cards,
        dealer_select_kept_cards,
        pone_select_play,
        dealer_select_play,
        args.hide_pone_hand,
        args.hide_dealer_hand,
        args.hide_play_actions,
        args.hands_per_update,
        args.confidence_level,
    )
    if args.process_count == 1:
        start_time_ns = time.time_ns()
        simulate_hands(*simulate_hands_args)
    else:
        processes = [
            Process(target=simulate_hands, args=simulate_hands_args)
            for process_number in range(args.process_count)
        ]
        start_time_ns = time.time_ns()
        for process in processes:
            process.start()
        try:
            for process in processes:
                process.join()
        except KeyboardInterrupt:
            sys.exit(0)

    elapsed_time_ns = time.time_ns() - start_time_ns
    ns_per_s = 1000000000
    print(
        f"Simulated {args.hand_count} hands with {args.process_count} worker processes at {args.hand_count / (elapsed_time_ns / ns_per_s):.0f} hands/s ({elapsed_time_ns / args.hand_count:.0f} ns/hand) in {elapsed_time_ns / ns_per_s} s"
    )
