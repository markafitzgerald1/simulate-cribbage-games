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


def simulate_hands(
    hand_count,
    grand_total_score,
    grand_total_score_lock,
    hide_pone_hand,
    hide_dealer_hand,
    hide_play_actions,
):
    deck = [Card(number % 13, number // 13) for number in range(52)]
    total_score = [0, 0]
    start_time_ns = time.time_ns()
    for hand in range(hand_count):
        hand_cards = random.sample(deck, 8)
        hands = [hand_cards[0:4], hand_cards[4:]]
        # TODO: resolve output inconsistency: Pone/Dealer here, Player 1/2 elsewhere
        if not hide_pone_hand:
            print(f"Pone dealt {','.join([ str(card) for card in hands[0] ])}")
        if not hide_dealer_hand:
            print(f"Dealer dealt {','.join([ str(card) for card in hands[1] ])}")
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
                        f"Player {player_to_play + 1} plays {player_to_play_play} for {play_count}"
                    )

                # Pairs points
                if player_to_play_play.index == most_recently_played_index:
                    most_recently_played_index_count += 1
                    if most_recently_played_index_count == 4:
                        if not hide_play_actions:
                            print(
                                f"!Double pairs royale for 12 points for player {player_to_play + 1}."
                            )
                        score[player_to_play] += 12
                    elif most_recently_played_index_count == 3:
                        if not hide_play_actions:
                            print(
                                f"!Pairs royale for 6 points for player {player_to_play + 1}."
                            )
                        score[player_to_play] += 6
                    elif most_recently_played_index_count == 2:
                        if not hide_play_actions:
                            print(
                                f"!Pair for 2 points for player {player_to_play + 1}."
                            )
                        score[player_to_play] += 2
                else:
                    most_recently_played_index = player_to_play_play.index
                    most_recently_played_index_count = 1

                # 15 and 31 count points
                if play_count == 15:
                    if not hide_play_actions:
                        print(f"!15 for 2 points for player {player_to_play + 1}.")
                    score[player_to_play] += 2
                elif play_count == 31:
                    if not hide_play_actions:
                        print(f"!31 for 1 point for player {player_to_play + 1}.")
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
                                f"!Run for {run_length} points for player {player_to_play + 1}."
                            )
                        score[player_to_play] += run_length
                        break

                consecutive_go_count = 0
            else:
                if not hide_play_actions:
                    print(f'Player {player_to_play + 1} says "Go!"')
                consecutive_go_count += 1
                if consecutive_go_count == 2:
                    if not hide_play_actions:
                        print(f"!Go for 1 point for player {player_to_play + 1}.")
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
            print(f"!Last card for 1 point for player {last_player_to_play + 1}.")
        score[last_player_to_play] += 1

        if not hide_play_actions:
            print(f"Hand score: {score}")
        total_score[0] += score[0]
        total_score[1] += score[1]
    elapsed_time_ns = time.time_ns() - start_time_ns
    print(
        f"Simulated {hand_count} hands in {elapsed_time_ns / 1000000000} seconds for {elapsed_time_ns / hand_count} ns per hand"
    )
    # print(f"Average score: {[ total / hand_count for total in total_score ]}")
    grand_total_score_lock.acquire()
    grand_total_score[0] += total_score[0]
    grand_total_score[1] += total_score[1]
    grand_total_score_lock.release()


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

    args = parser.parse_args()

    manager = Manager()
    grand_total_score = manager.list([0, 0])
    grand_total_score_lock = Lock()
    if not args.hide_workers_start_message:
        print(
            f"Simulating {args.hand_count} hands",
            end="" if args.process_count > 1 else os.linesep,
            flush=args.process_count == 1,
        )
        if args.process_count > 1:
            print(
                f" in {args.process_count} worker process{'es' if args.process_count > 1 else ''}",
                flush=True,
            )
    simulate_hands_args = (
        args.hand_count // args.process_count,
        grand_total_score,
        grand_total_score_lock,
        args.hide_pone_hand,
        args.hide_dealer_hand,
        args.hide_play_actions,
    )
    if args.process_count == 1:
        simulate_hands(*simulate_hands_args)
    else:
        args.hand_count = (
            math.ceil(args.hand_count / args.process_count) * args.process_count
        )
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
        print(
            f"Simulated {args.hand_count} total hands in {elapsed_time_ns / 1000000000} seconds for {elapsed_time_ns / args.hand_count} ns per hand"
        )
    print(
        f"Overall average score: {[ grand_total / args.hand_count for grand_total in grand_total_score ]}"
    )
