# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import sys
import random
import time

deck = range(52)
n_hands = int(sys.argv[1]) if len(sys.argv) > 1 else 50000
start_time_ns = time.time_ns()
for hand in range(n_hands):
    handCards = random.sample(deck, 8)
    # print(f"Deal is {handCards}.")
    hands = [handCards[0:4], handCards[4:]]
    # print(f"Hands are {hands}.")
    playerToPlay = 0
    while len(hands[0]) + len(hands[1]) > 0:
        if len(hands[playerToPlay]) > 0:
            playerToPlayPlay = hands[playerToPlay].pop()
            # print(f"Player {playerToPlay} has a play: {playerToPlayPlay}.")
        playerToPlay = (playerToPlay + 1) % 2
elapsed_time_ns = time.time_ns() - start_time_ns
print(
    f"Simulated {n_hands} hands in {elapsed_time_ns / 1000000000} seconds for {elapsed_time_ns / n_hands} ns per hand"
)
