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

    def __init__(self, index, suit):
        self.index = index
        self.suit = suit
        self.count = min(index + 1, 10)
        self.str = f"{'A23456789TJQK'[index]}{'♣♦♥♠'[suit]}"

    def __str__(self):
        return self.str

    def __repr__(self):
        return f"Card({self.index}, {self.suit})"


def get_player_name(player_number):
    if player_number == 0:
        return "Pone"
    else:
        return "Dealer"


def simulate_hands(
    process_hand_count,
    overall_hand_count,
    players_statistics,
    players_statistics_lock,
    hide_pone_hand,
    hide_dealer_hand,
    hide_play_actions,
    hands_per_update,
    confidence_level,
):
    deck = [Card(number % 13, number // 13) for number in range(52)]
    (pone_statistics, dealer_statistics) = (Statistics(), Statistics())
    for hand in range(process_hand_count):
        hand_cards = random.sample(deck, 8)
        hands = [hand_cards[0:4], hand_cards[4:]]
        if not hide_pone_hand:
            print(
                f"{get_player_name(0):6} dealt {','.join([ str(card) for card in hands[0] ])}"
            )
        if not hide_dealer_hand:
            print(
                f"{get_player_name(1):6} dealt {','.join([ str(card) for card in hands[1] ])}"
            )
        player_to_play = 0
        play_count = 0
        consecutive_go_count = 0
        most_recently_played_index = None
        most_recently_played_index_count = 0
        score = [0, 0]
        current_play_plays = []
        while hands[0] or hands[1]:
            playable_cards = [
                card for card in hands[player_to_play] if play_count + card.count <= 31
            ]

            if playable_cards:
                player_to_play_play = playable_cards[-1]
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

        if not hide_play_actions:
            print(f"Hand score: {score}")
        pone_statistics.push(score[0])
        dealer_statistics.push(score[1])

        if (
            hand % hands_per_update == hands_per_update - 1
            or hand == process_hand_count - 1
        ):
            players_statistics_lock.acquire()
            players_statistics["pone"] += pone_statistics
            players_statistics["dealer"] += dealer_statistics
            pone_statistics.clear()
            dealer_statistics.clear()
            players_statistics_length = len(players_statistics["pone"])
            if players_statistics_length > 1:
                z_statistic = NormalDist().inv_cdf(1 - (1 - confidence_level / 100) / 2)
                print(
                    f"Mean scores {confidence_level}% confidence interval (n = {players_statistics_length:{int(math.log10(overall_hand_count)) + 1}}): ({players_statistics['pone'].mean():.4f} ± {z_statistic * players_statistics['pone'].stddev() / math.sqrt(players_statistics_length):.4f}, {players_statistics['dealer'].mean():.4f} ± {z_statistic * players_statistics['dealer'].stddev() / math.sqrt(players_statistics_length):.4f})"
                )
            else:
                print(
                    f"Mean scores {'':27} (n = {players_statistics_length}): ({players_statistics['pone'].mean():.4f} {'':8}, {players_statistics['dealer'].mean():.4f})"
                )
            players_statistics_lock.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--process-count",
        help="number of processes to use to simulate cribbage hand plays",
        type=int,
        default=cpu_count(),
    )
    parser.add_argument(
        "--hand-count",
        help="number of cribbage hand plays to simulate",
        type=int,
        default=1,
    )
    parser.add_argument(
        "--hide-workers-start-message",
        action="store_true",
        help="hide the workers startup details message",
    )
    parser.add_argument(
        "--hide-pone-hand",
        action="store_true",
        help="suppress deal-time output of pone hand contents",
    )
    parser.add_argument(
        "--hide-dealer-hand",
        action="store_true",
        help="suppress deal-time output of dealer hand contents",
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
        help="statistical confidence level of outputted confidence intervals",
        type=float,
        default=95,
    )

    args = parser.parse_args()

    manager = Manager()
    players_statistics = manager.dict(pone=Statistics(), dealer=Statistics())
    players_statistics_lock = Lock()
    if not args.hide_workers_start_message:
        print(
            f"Simulating {args.hand_count} hands",
            end="" if args.process_count > 1 else os.linesep,
            flush=args.process_count == 1,
        )
        if args.process_count > 1:
            print(
                f" with {args.process_count} worker process{'es' if args.process_count > 1 else ''}",
                flush=True,
            )

    args.hand_count = (
        math.ceil(args.hand_count / args.process_count) * args.process_count
    )
    simulate_hands_args = (
        args.hand_count // args.process_count,
        args.hand_count,
        players_statistics,
        players_statistics_lock,
        args.hide_pone_hand,
        args.hide_dealer_hand,
        args.hide_play_actions,
        args.hands_per_update,
        args.confidence_level,
    )
    if args.process_count == 1:
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
