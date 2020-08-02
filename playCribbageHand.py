# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import sys
import random
import time
from multiprocessing import Process, cpu_count


def simulate_hands(hand_count):
    deck = range(52)
    start_time_ns = time.time_ns()
    for hand in range(hand_count):
        handCards = random.sample(deck, 8)
        # print(f"Deal is {handCards}.")
        hands = [handCards[0:4], handCards[4:]]
        # print(f"Hands are {hands}.")
        playerToPlay = 0
        while hands[0] or hands[1]:
            if hands[playerToPlay]:
                playerToPlayPlay = hands[playerToPlay].pop()
                # print(f"Player {playerToPlay} has a play: {playerToPlayPlay}.")
            playerToPlay = (playerToPlay + 1) % 2
    elapsed_time_ns = time.time_ns() - start_time_ns
    print(
        f"Simulated {hand_count} hands in {elapsed_time_ns / 1000000000} seconds for {elapsed_time_ns / hand_count} ns per hand"
    )


if __name__ == "__main__":
    hand_count = int(sys.argv[1]) if len(sys.argv) > 1 else 55500
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
