/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

const randomJs = require("random-js");

const mersenneTwisterEngine = randomJs.MersenneTwister19937.autoSeed();
const deck = Array.from(Array(52).keys());

const nHands = process.argv.length > 2 ? parseInt(process.argv[2]) : 365000;

const countingValue = (card) => Math.min((card % 13) + 1, 10);
const cardIndex = (card) => "A23456789TJQK".split("")[card % 13];
const cardSuit = (card) => "♣♦♥♠".split("")[Math.floor(card / 13)];
const cardString = (card) => `${cardIndex(card)}${cardSuit(card)}`;

// console.log(`Worker simulating ${nHands} hands`);
const startTimeNs = process.hrtime.bigint();
[...Array(nHands)].forEach((_) => {
  const deal = randomJs.sample(mersenneTwisterEngine, deck, 8);
  // console.log(`Deal is ${deal.map(cardString)}.`);
  const hands = [deal.slice(0, 4), deal.slice(4)];
  // console.log(
  //   `Hands are ${hands.map((hand) => hand.map(cardString)).join("; ")}.`
  // );
  let playerToPlay = 0;
  let playCount = 0;
  let consecutiveGoCount = 0;
  while (hands[0].length + hands[1].length > 0) {
    if (hands[playerToPlay].length > 0) {
      const playableCards = hands[playerToPlay].filter(
        (card) => playCount + countingValue(card) <= 31
      );
      if (playableCards.length > 0) {
        const playerToPlayPlay = playableCards[0];
        hands[playerToPlay] = hands[playerToPlay].filter(
          (card) => card !== playerToPlayPlay
        );
        playCount += countingValue(playerToPlayPlay);
        // console.log(
        //   `Player ${playerToPlay} plays ${cardString(
        //     playerToPlayPlay
        //   )} for ${playCount}.`
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
