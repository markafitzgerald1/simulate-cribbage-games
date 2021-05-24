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
import Player from "./cribbage/Player";
import Points from "./cribbage/Points";
import ThePlay from "./cribbage/ThePlay";

const mersenneTwisterEngine: Engine = MersenneTwister19937.autoSeed();
const LAST_CARD_POINTS: Points = 1;

const handCount: number =
  process.argv.length > 2 ? parseInt(process.argv[2]) : 390000;
// console.log(`Worker simulating ${handCount} hands`);
let totalScore: [Points, Points] = [0, 0];
const startTimeNs: bigint = process.hrtime.bigint();
[...Array(handCount)].forEach((_) => {
  let allHands: AllHands = dealAllHands(mersenneTwisterEngine, DECK);
  // console.log(`allHands: ${allHands}.`);
  let playerToPlay: Player = Player.PONE;
  let score: [Points, Points] = [0, 0];
  let thePlay: ThePlay = ThePlay.create();
  while (
    allHands.poneHand.cards.length + allHands.dealerHand.cards.length >
    0
  ) {
    const playerToPlayHand: Hand = playerToPlay.isPone
      ? allHands.poneHand
      : allHands.dealerHand;
    const playableCards: readonly Card[] =
      thePlay.getPlayableCards(playerToPlayHand);
    if (playableCards.length > 0) {
      const playerToPlayPlay: Card = playableCards[0];
      const updatedHand: Hand = playerToPlayHand.play(playerToPlayPlay);
      if (playerToPlay.isPone) {
        allHands = new AllHands(updatedHand, allHands.dealerHand);
      } else {
        allHands = new AllHands(allHands.poneHand, updatedHand);
      }

      thePlay = thePlay.add(playerToPlayPlay);
    } else {
      thePlay = thePlay.addGo();
    }
    // console.log(`thePlay: ${thePlay}`);

    playerToPlay = playerToPlay.next;
  }

  // Add points from the final PlayTo31.
  score = [score[0] + thePlay.poneScore, score[1] + thePlay.dealerScore];
  // console.log(`score: [${score}]`);

  // TODO: move inside ThePlay
  // Last Card points
  const lastPlayerToPlay: Player = playerToPlay.next;
  // console.log(`!Last card for 1 point for ${lastPlayerToPlay}.`);
  score[lastPlayerToPlay.value] += LAST_CARD_POINTS;
  // console.log(`score: [${score}]`);

  totalScore[0] += score[0];
  totalScore[1] += score[1];
});
const elapsedTimeNs: bigint = process.hrtime.bigint() - startTimeNs;
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
