/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

const randomJs = require("random-js");

const mersenneTwisterEngine = randomJs.MersenneTwister19937.autoSeed();
const deck = Array.from(Array(52).keys());

const nHands = process.argv.length > 2 ? parseInt(process.argv[2]) : 730000;
const startTimeNs = process.hrtime.bigint();
console.log(`Simulating ${nHands} hands`);
[...Array(nHands)].forEach((_) => {
  const handCards = randomJs.sample(mersenneTwisterEngine, deck, 8);
  const hands = [handCards.slice(0, 4), handCards.slice(4)];
  // console.log(`Deal: ${hands}.`);
  let playerToPlay = 0;
  while (hands[0].length + hands[1].length > 0) {
    if (hands[playerToPlay].length > 0) {
      const playerToPlayPlay = hands[playerToPlay].pop();
      // console.log(`Player ${playerToPlay} has a play: ${playerToPlayPlay}.`);
    }
    playerToPlay = (playerToPlay + 1) % 2;
  }
});
const elapsedTimeNs = process.hrtime.bigint() - startTimeNs;
console.log(
  `Simulated ${nHands} hands in ${elapsedTimeNs} ns for ${
    elapsedTimeNs / BigInt(nHands)
  } ns per hand`
);
