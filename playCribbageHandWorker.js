/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

const randomJs = require("random-js");

const mersenneTwisterEngine = randomJs.MersenneTwister19937.autoSeed();

class Card {
  constructor(index, suit) {
    this.index = index;
    this.suit = suit;
    this.count = Math.min(index + 1, 10);
    this.str = `${"A23456789TJQK".split("")[index]}${"♣♦♥♠".split("")[suit]}`;
  }

  toString() {
    return this.str;
  }
}

const deck = Array.from(Array(52).keys()).map(
  (number) => new Card(number % 13, Math.floor(number / 13))
);

const nHands = process.argv.length > 2 ? parseInt(process.argv[2]) : 390000;
// console.log(`Worker simulating ${nHands} hands`);
const startTimeNs = process.hrtime.bigint();
[...Array(nHands)].forEach((_) => {
  const deal = randomJs.sample(mersenneTwisterEngine, deck, 8);
  // console.log(`Deal is ${deal}.`);
  const hands = [deal.slice(0, 4), deal.slice(4)];
  // console.log(
  //   `Hands are ${hands
  //     .map((hand) => hand.map((card) => card.toString()))
  //     .join("; ")}.`
  // );
  let playerToPlay = 0;
  let playCount = 0;
  let consecutiveGoCount = 0;
  while (hands[0].length + hands[1].length > 0) {
    if (hands[playerToPlay].length > 0) {
      const playableCards = hands[playerToPlay].filter(
        (card) => playCount + card.count <= 31
      );
      if (playableCards.length > 0) {
        const playerToPlayPlay = playableCards[0];
        hands[playerToPlay] = hands[playerToPlay].filter(
          (card) => card !== playerToPlayPlay
        );
        playCount += playerToPlayPlay.count;
        // console.log(
        //   `Player ${playerToPlay} plays ${playerToPlayPlay} for ${playCount}.`
        // );
        consecutiveGoCount = 0;
      } else {
        // console.log(`Player ${playerToPlay} says "Go!"`);
        consecutiveGoCount++;
        if (consecutiveGoCount == 2) {
          // console.log("Resetting play count to 0.");
          consecutiveGoCount = 0;
          playCount = 0;
        }
      }
    }
    playerToPlay = (playerToPlay + 1) % 2;
  }
});
const elapsedTimeNs = process.hrtime.bigint() - startTimeNs;
console.log(
  `Worker simulated ${nHands} hands in ${elapsedTimeNs} ns for ${
    elapsedTimeNs / BigInt(nHands)
  } ns per hand`
);
