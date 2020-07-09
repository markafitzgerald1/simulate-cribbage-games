import sys
import random

deck = range(52)
n_hands = int(sys.argv[1]) or 50000
print(f"Simulating {n_hands} hands")
for hand in range(n_hands):
    handCards = random.sample(range(52), 8)
    hands = [handCards[0:4], handCards[4:]]
    playerToPlay = 0
    while len(hands[0]) + len(hands[1]) > 0:
        if len(hands[playerToPlay]) > 0:
            playerToPlayPlay = hands[playerToPlay].pop()
            # print(f"Player {playerToPlay} has a play: {playerToPlayPlay}.")
        playerToPlay = (playerToPlay + 1) % 2
