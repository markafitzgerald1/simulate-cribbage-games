import random
deck = range(52)
for hand in range(46000):
    handCards = random.sample(range(52), 8)
    hands = [handCards[0:4], handCards[4:]]
    playerToPlay = 0
    while len(hands[0]) + len(hands[1]) > 0:
        if len(hands[playerToPlay]) > 0:
            playerToPlayPlay = hands[playerToPlay].pop()
            # print(f"Player {playerToPlay} has a play: {playerToPlayPlay}.")
        playerToPlay = (playerToPlay + 1) % 2
