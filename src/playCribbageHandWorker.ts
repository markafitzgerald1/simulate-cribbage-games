/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import { MersenneTwister19937 } from "random-js";
import { Engine } from "random-js/dist/types";
import Card from "./cribbage/Card";
import DECK from "./cribbage/DECK";
import dealAllHands from "./cribbage/dealAllHands";
import AllHands from "./cribbage/AllHands";
import Hand from "./cribbage/Hand";
import { parentPort, isMainThread } from "worker_threads";
import PlayTo31 from "./cribbage/PlayTo31";

const mersenneTwisterEngine: Engine = MersenneTwister19937.autoSeed();

const handCount = process.argv.length > 2 ? parseInt(process.argv[2]) : 390000;
// console.log(`Worker simulating ${handCount} hands`);
let totalScore = [0, 0];
const startTimeNs = process.hrtime.bigint();
[...Array(handCount)].forEach((_) => {
  let allHands: AllHands = dealAllHands(mersenneTwisterEngine, DECK);
  // console.log(`allHands: ${allHands}.`);
  let playerToPlay = 0;
  let score = [0, 0];
  let currentPlayTo31: PlayTo31 = PlayTo31.create();
  let currentPlayTo31InitialPlayer: number = 0;
  while (
    allHands.poneHand.cards.length + allHands.dealerHand.cards.length >
    0
  ) {
    const playerToPlayHand: Hand =
      playerToPlay === 0 ? allHands.poneHand : allHands.dealerHand;
    const playableCards: readonly Card[] = currentPlayTo31.getPlayableCards(
      playerToPlayHand
    );
    if (playableCards.length > 0) {
      const playerToPlayPlay = playableCards[0];
      const updatedHand = playerToPlayHand.play(playerToPlayPlay);
      if (playerToPlay === 0) {
        allHands = new AllHands(updatedHand, allHands.dealerHand);
      } else {
        allHands = new AllHands(allHands.poneHand, updatedHand);
      }

      currentPlayTo31 = currentPlayTo31.add(playerToPlayPlay);
      // console.log(`currentPlayTo31: ${currentPlayTo31}`);
    } else {
      currentPlayTo31 = currentPlayTo31.addGo();
      // console.log(`currentPlayTo31: ${currentPlayTo31}`);
      if (currentPlayTo31.currentConsecutiveGoCount == 2) {
        score = [
          score[0] +
            (currentPlayTo31InitialPlayer === 0
              ? currentPlayTo31.poneScore
              : currentPlayTo31.dealerScore),
          score[1] +
            (currentPlayTo31InitialPlayer === 0
              ? currentPlayTo31.dealerScore
              : currentPlayTo31.poneScore),
        ];
        // console.log(`score: [${score}]`);

        // console.log("---starting new PlayTo31...");
        currentPlayTo31 = PlayTo31.create();
        currentPlayTo31InitialPlayer = (playerToPlay + 1) % 2;
      }
    }

    playerToPlay = (playerToPlay + 1) % 2;
  }

  // Add points from the final PlayTo31.  TODO: factor out copy-paste
  score = [
    score[0] +
      (currentPlayTo31InitialPlayer === 0
        ? currentPlayTo31.poneScore
        : currentPlayTo31.dealerScore),
    score[1] +
      (currentPlayTo31InitialPlayer === 0
        ? currentPlayTo31.dealerScore
        : currentPlayTo31.poneScore),
  ];
  // console.log(`score: [${score}]`);

  // Last Card points
  const lastPlayerToPlay = (playerToPlay + 1) % 2;
  // console.log(`!Last card for 1 point for player ${lastPlayerToPlay + 1}.`);
  score[lastPlayerToPlay] += 1;
  // console.log(`score: [${score}]`);

  totalScore[0] += score[0];
  totalScore[1] += score[1];
});
const elapsedTimeNs = process.hrtime.bigint() - startTimeNs;
console.log(
  `Worker simulated ${handCount} hands in ${elapsedTimeNs} ns for ${
    elapsedTimeNs / BigInt(handCount)
  } ns per hand`
);

if (parentPort) {
  parentPort.postMessage(totalScore);
} else if (isMainThread) {
  console.log(
    `Average score: [${totalScore.map(
      (totalPlayerScore) => totalPlayerScore / handCount
    )}]`
  );
}
