# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import sys
import random
import time
from multiprocessing import Process, cpu_count, Manager, Lock
import math


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


def simulate_hands(hand_count, grand_total_score, grand_total_score_lock):
    deck = [Card(number % 13, number // 13) for number in range(52)]
    start_time_ns = time.time_ns()
    total_score = [0, 0]
    for hand in range(hand_count):
        hand_cards = random.sample(deck, 8)
        # print(f"Deal is {','.join([ str(card) for card in hand_cards ])}.")
        hands = [hand_cards[0:4], hand_cards[4:]]
        # print(
        #     f"Hands are {'; '.join([ ','.join([ str(card) for card in hand ]) for hand in hands ])}."
        # )
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
                # print(
                #     f"Player {player_to_play + 1} plays {player_to_play_play} for {play_count}; current play plays = {','.join([ str(play) for play in current_play_plays ])}"
                # )

                # Pairs points
                if player_to_play_play.index == most_recently_played_index:
                    most_recently_played_index_count += 1
                    if most_recently_played_index_count == 4:
                        # print(
                        #     f"!Double pairs royale for 12 points for player {player_to_play + 1}."
                        # )
                        score[player_to_play] += 12
                    elif most_recently_played_index_count == 3:
                        # print(
                        #     f"!Pairs royale for 6 points for player {player_to_play + 1}."
                        # )
                        score[player_to_play] += 6
                    elif most_recently_played_index_count == 2:
                        # print(f"!Pair for 2 points for player {player_to_play + 1}.")
                        score[player_to_play] += 2
                else:
                    most_recently_played_index = player_to_play_play.index
                    most_recently_played_index_count = 1

                # 15 and 31 count points
                if play_count == 15:
                    # print(f"!15 for 2 points for player {player_to_play + 1}.")
                    score[player_to_play] += 2
                elif play_count == 31:
                    # print(f"!31 for 1 point for player {player_to_play + 1}.")
                    score[player_to_play] += 1

                # Runs points
                for run_length in reversed(range(3, len(current_play_plays) + 1)):
                    sorted_recent_play_indices = sorted(
                        [play.index for play in current_play_plays[-run_length:]]
                    )
                    # print(
                    #     f"run length {run_length} sorted indices: {sorted(sorted_recent_play_indices)}"
                    # )
                    is_run = all(
                        [
                            diff[1] - diff[0] == 1
                            for diff in zip(
                                sorted_recent_play_indices,
                                sorted_recent_play_indices[1:],
                            )
                        ]
                    )
                    # print(f"run length {run_length} is a run: {is_run}")
                    if is_run:
                        # print(
                        #     f"!Run for {run_length} points for player {player_to_play + 1}."
                        # )
                        score[player_to_play] += run_length
                        break

                consecutive_go_count = 0
            else:
                # print(f'Player {player_to_play + 1} says "Go!"')
                consecutive_go_count += 1
                if consecutive_go_count == 2:
                    # print(f"!Go for 1 point for player {player_to_play + 1}.")
                    score[player_to_play] += 1

                    # print("---resetting play count to 0---")
                    consecutive_go_count = 0
                    play_count = 0
                    current_play_plays = []
                    most_recently_played_index = None
                    most_recently_played_index_count = 0

            player_to_play = (player_to_play + 1) % 2

        # Last Card points
        last_player_to_play = (player_to_play + 1) % 2
        # print(f"!Last card for 1 point for player {last_player_to_play + 1}.")
        score[last_player_to_play] += 1

        # print(f"Hand score: {score}")
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
    hand_count = int(sys.argv[1]) if len(sys.argv) > 1 else 37000
    process_count = int(sys.argv[2]) if len(sys.argv) > 2 else cpu_count()
    manager = Manager()
    grand_total_score = manager.list([0, 0])
    grand_total_score_lock = Lock()
    if process_count == 1:
        simulate_hands(hand_count, grand_total_score, grand_total_score_lock)
    else:
        hand_count = math.ceil(hand_count / process_count) * process_count
        # print(
        #     f"Simulating {hand_count} hands across {process_count} worker processes",
        #     flush=True,
        # )
        processes = [
            Process(
                target=simulate_hands,
                args=(
                    hand_count // process_count,
                    grand_total_score,
                    grand_total_score_lock,
                ),
            )
            for process_number in range(process_count)
        ]
        start_time_ns = time.time_ns()
        for process in processes:
            process.start()
        for process in processes:
            process.join()
        elapsed_time_ns = time.time_ns() - start_time_ns
        print(
            f"Simulated {hand_count} total hands in {elapsed_time_ns / 1000000000} seconds for {elapsed_time_ns / hand_count} ns per hand"
        )
    print(
        f"Overall average score: {[ grand_total / hand_count for grand_total in grand_total_score ]}"
    )
