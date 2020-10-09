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
            Card.english_suits.find(specifier[1].capitalize()),
        )

    def __eq__(self, value):
        return self.index == value.index and self.suit == value.suit

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
    DEALT_CARDS_LEN = 6
    if len(pone_dealt_cards) not in [0, DEALT_CARDS_LEN] or len(
        dealer_dealt_cards
    ) not in [0, DEALT_CARDS_LEN]:
        raise ValueError(
            f"If specifying player dealt cards exactly {DEALT_CARDS_LEN} must be specified"
        )

    if len(pone_kept_cards) not in [0, DEALT_CARDS_LEN] or len(
        dealer_kept_cards
    ) not in [0, KEPT_CARDS_LEN]:
        raise ValueError(
            f"If specifying player kept cards exactly {KEPT_CARDS_LEN} must be specified"
        )

    deck_less_fixed_cards = {
        Card(number % 13, number // 13)
        for number in range(52)
        if Card(number % 13, number // 13) not in pone_dealt_cards
        and Card(number % 13, number // 13) not in dealer_dealt_cards
    }
    (pone_statistics, dealer_statistics, pone_minus_dealer_statistics) = (
        Statistics(),
        Statistics(),
        Statistics(),
    )
    for hand in range(process_hand_count):
        if pone_dealt_cards or dealer_dealt_cards:
            random_hand_cards = random.sample(deck_less_fixed_cards, DEALT_CARDS_LEN)
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
        deck_less_dealt_cards = deck_less_fixed_cards.difference(set(random_hand_cards))

        kept_hands = [
            [card for card in dealt_hands[0] if card in pone_kept_cards]
            if pone_kept_cards
            else pone_select_kept_cards(dealt_hands[0]),
            [card for card in dealt_hands[1] if card in dealer_kept_cards]
            if dealer_kept_cards
            else dealer_select_kept_cards(dealt_hands[1]),
        ]
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
            print(f"{get_player_name(1):6} discarded {Hand(dealer_discarded_cards)}")

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
                card for card in hands[player_to_play] if play_count + card.count <= 31
            ]

            if playable_cards:
                # TODO: replace two play selection algorithms with tuple argument if faster
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
                        score[player_to_play] += 2
                else:
                    most_recently_played_index = player_to_play_play.index
                    most_recently_played_index_count = 1

                # 15 and 31 count points
                if play_count == 15:
                    if not hide_play_actions:
                        print(
                            f"!15 for 2 points for {get_player_name(player_to_play)}."
                        )
                    score[player_to_play] += 2
                elif play_count == 31:
                    if not hide_play_actions:
                        print(f"!31 for 1 point for {get_player_name(player_to_play)}.")
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
                        print(f"!Go for 1 point for {get_player_name(player_to_play)}.")
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
            print(f"!Last card for 1 point for {get_player_name(last_player_to_play)}.")
        score[last_player_to_play] += 1

        # TODO: score hands here
        # if not hide_play_actions:
        # print(f"Pone hand points: -PH-")
        # print(f"Dealer hand points: -DH-")
        # TODO: score crib here
        # if not hide_play_actions:
        # print(f"Crib points: -CR-")

        if not hide_play_actions:
            print(f"Hand score: {score}")

        pone_statistics.push(score[0])
        dealer_statistics.push(score[1])
        pone_minus_dealer_statistics.push(score[0] - score[1])

        if (
            hand % hands_per_update == hands_per_update - 1
            or hand == process_hand_count - 1
        ):
            players_statistics_lock.acquire()
            players_statistics["pone"] += pone_statistics
            players_statistics["dealer"] += dealer_statistics
            players_statistics["pone_minus_dealer"] += pone_minus_dealer_statistics
            pone_statistics.clear()
            dealer_statistics.clear()
            players_statistics_length = len(players_statistics["pone"])
            z_statistic = NormalDist().inv_cdf(1 - (1 - confidence_level / 100) / 2)
            if players_statistics_length > 1:
                dealer_stddev = players_statistics["dealer"].stddev()
                pone_stddev = players_statistics["pone"].stddev()
                pone_minus_dealer_stddev = players_statistics[
                    "pone_minus_dealer"
                ].stddev()
            else:
                dealer_stddev, pone_stddev, pone_minus_dealer_stddev = 0, 0, 0
            correlation = (
                (pone_minus_dealer_stddev ** 2 - pone_stddev ** 2 - dealer_stddev ** 2)
                / (2 * pone_stddev * dealer_stddev)
                if pone_stddev != 0 and dealer_stddev != 0
                else None
            )
            correlation_str = f"{correlation:.5f}" if correlation else "undefined"
            print(
                f"Mean scores {confidence_level}% confidence interval (n = {players_statistics_length:{int(math.log10(overall_hand_count)) + 1}}): ({players_statistics['pone'].mean():.5f} ± {z_statistic * pone_stddev / math.sqrt(players_statistics_length):.5f}, {players_statistics['dealer'].mean():.5f} ± {z_statistic * dealer_stddev / math.sqrt(players_statistics_length):.5f}) = {players_statistics['pone_minus_dealer'].mean():.5f} ± {z_statistic * pone_minus_dealer_stddev / math.sqrt(players_statistics_length):.5f}; ρ = {correlation_str}"
            )
            players_statistics_lock.release()


KEPT_CARDS_LEN = 4


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
    print(f"Playable cards are {','.join([ str(card) for card in playable_cards ])}.")
    selected_card = None
    while selected_card not in range(0, len(playable_cards)):
        try:
            selected_card_input = input("Enter the base-0 card index to play: ")
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
        "--pone-keep-random", action="store_true", help="have pone discard randomly",
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
        "--pone-dealt-cards", help="cards dealt to pone",
    )
    specified_dealt_cards_group.add_argument(
        "--dealer-dealt-cards", help="cards dealt to dealer",
    )

    specified_kept_cards_group = parser.add_mutually_exclusive_group()
    specified_kept_cards_group.add_argument(
        "--pone-kept-cards", help="cards kept by pone",
    )
    specified_kept_cards_group.add_argument(
        "--dealer-kept-cards", help="cards kept by dealer",
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
    players_statistics = manager.dict(
        pone=Statistics(), dealer=Statistics(), pone_minus_dealer=Statistics()
    )
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
    else:
        pone_select_kept_cards = keep_first_four

    if args.dealer_keep_random:
        dealer_select_kept_cards = keep_random
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
        for process in processes:
            process.join()

    elapsed_time_ns = time.time_ns() - start_time_ns
    ns_per_s = 1000000000
    print(
        f"Simulated {args.hand_count} hands with {args.process_count} worker processes at {args.hand_count / (elapsed_time_ns / ns_per_s):.0f} hands/s ({elapsed_time_ns / args.hand_count:.0f} ns/hand) in {elapsed_time_ns / ns_per_s} s"
    )
