hands = [[0, 1, 2, 3], [4, 5, 6, 7]]
playerToPlay = 0
while len(hands[0]) + len(hands[1]) > 0:
    if len(hands[playerToPlay]) > 0:
        playerToPlayPlay = hands[playerToPlay].pop()
        print(f"Player {playerToPlay} has a play: {playerToPlayPlay}.")
    playerToPlay = (playerToPlay + 1) % 2
