import sys
import random
import time

deck = range(52)
n_hands = int(sys.argv[1]) or 50000
start_time_ns = time.time_ns()
for hand in range(n_hands):
    handCards = random.sample(deck, 8)
    hands = [handCards[0:4], handCards[4:]]
    playerToPlay = 0
    while len(hands[0]) + len(hands[1]) > 0:
        if len(hands[playerToPlay]) > 0:
            playerToPlayPlay = hands[playerToPlay].pop()
            # print(f"Player {playerToPlay} has a play: {playerToPlayPlay}.")
        playerToPlay = (playerToPlay + 1) % 2
elapsed_time_ns = time.time_ns() - start_time_ns
print(
    f"Simulated {n_hands} hands in {elapsed_time_ns} ns for {elapsed_time_ns / n_hands} ns per hand"
)
