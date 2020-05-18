[...Array(4675000)].forEach(_ => {
    const hands = [[0, 1, 2, 3], [4, 5, 6, 7]];
    let playerToPlay = 0;
    while (hands[0].length + hands[1].length > 0) {
        if (hands[playerToPlay].length > 0) {
            const playerToPlayPlay = hands[playerToPlay].pop();
            // console.log(`Player ${playerToPlay} has a play: ${playerToPlayPlay}.`);
        }
        playerToPlay = (playerToPlay + 1) % 2;
    }
});