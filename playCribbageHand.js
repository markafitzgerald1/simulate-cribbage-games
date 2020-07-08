const randomJs = require('random-js');

const mersenneTwisterEngine = randomJs.MersenneTwister19937.autoSeed();
const deck = Array.from(Array(52).keys());

[...Array(500000)].forEach(_ => {
    const handCards = randomJs.sample(mersenneTwisterEngine, deck, 8);
    const hands = [handCards.slice(0, 4), handCards.slice(4)];
    let playerToPlay = 0;
    while (hands[0].length + hands[1].length > 0) {
        if (hands[playerToPlay].length > 0) {
            const playerToPlayPlay = hands[playerToPlay].pop();
            // console.log(`Player ${playerToPlay} has a play: ${playerToPlayPlay}.`);
        }
        playerToPlay = (playerToPlay + 1) % 2;
    }
});