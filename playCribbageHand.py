# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import sys
import random
import time
from multiprocessing import Process, cpu_count


class Card:
    """A French playing card"""

    def __init__(self, index, suit):
        self.index = index
        self.suit = suit
        self.count = min(index + 1, 10)
        self.str = f"{'A23456789TJQK'[index]}{'♣♦♥♠'[suit]}"

    def __str__(self):
        return self.str


def simulate_hands(hand_count):
    deck = [Card(number % 13, number // 13) for number in range(52)]
    start_time_ns = time.time_ns()
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
        while hands[0] or hands[1]:
            if hands[player_to_play]:
                playable_cards = [
                    card
                    for card in hands[player_to_play]
                    if play_count + card.count <= 31
                ]

                if playable_cards:
                    player_to_play_play = playable_cards[-1]
                    hands[player_to_play].remove(player_to_play_play)
                    this_play_count = player_to_play_play.count
                    play_count += this_play_count
                    # print(
                    #     f"Player {player_to_play} plays {player_to_play_play} for {play_count}."
                    # )
                    consecutive_go_count = 0
                else:
                    # print(f'Player {player_to_play} says "Go!"')
                    consecutive_go_count += 1
                    if consecutive_go_count == 2:
                        # print("Resetting play count to 0.")
                        consecutive_go_count = 0
                        play_count = 0

            player_to_play = (player_to_play + 1) % 2
    elapsed_time_ns = time.time_ns() - start_time_ns
    print(
        f"Simulated {hand_count} hands in {elapsed_time_ns / 1000000000} seconds for {elapsed_time_ns / hand_count} ns per hand"
    )


if __name__ == "__main__":
    hand_count = int(sys.argv[1]) if len(sys.argv) > 1 else 37000
    process_count = int(sys.argv[2]) if len(sys.argv) > 2 else cpu_count()
    if process_count == 1:
        simulate_hands(hand_count)
    else:
        print(
            f"Simulating {hand_count} hands across {process_count} worker processes",
            flush=True,
        )
        processes = [
            Process(target=simulate_hands, args=(hand_count // process_count,))
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
