/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import { Engine } from "random-js";
import Points from "./cribbage/Points";
import AllHands from "./cribbage/AllHands";
import DECK from "./cribbage/DECK";
import dealAllHands from "./cribbage/dealAllHands";
import ThePlay from "./cribbage/ThePlay";
import Hand from "./cribbage/Hand";
import Card from "./cribbage/Card";

export default (
  mersenneTwisterEngine: Engine,
  handCount: number,
  hidePoneHand: boolean,
  hideDealerHand: boolean,
  workerNumber?: number
): [Points, Points] => {
  // console.log(`Worker simulating ${handCount} hands`);
  let totalScore: [Points, Points] = [0, 0];
  const startTimeNs: bigint = process.hrtime.bigint();
  const workerNumberPrefix = workerNumber ? `[worker ${workerNumber}] ` : "";
  [...Array(handCount)].forEach((_) => {
    let allHands: AllHands = dealAllHands(mersenneTwisterEngine, DECK);
    if (!hidePoneHand) {
      console.log(`${workerNumberPrefix}Pone   dealt ${allHands.poneHand}`);
    }
    if (!hideDealerHand) {
      console.log(`${workerNumberPrefix}Dealer dealt ${allHands.dealerHand}`);
    }

    let thePlay: ThePlay = ThePlay.create();
    while (
      allHands.poneHand.cards.length + allHands.dealerHand.cards.length >
      0
    ) {
      const playerToPlayHand: Hand = thePlay.nextPlayerToPlay.isPone
        ? allHands.poneHand
        : allHands.dealerHand;
      const playableCards: readonly Card[] =
        thePlay.getPlayableCards(playerToPlayHand);
      if (playableCards.length > 0) {
        const playerToPlayPlay: Card = playableCards[0];
        const updatedHand: Hand = playerToPlayHand.play(playerToPlayPlay);
        if (thePlay.nextPlayerToPlay.isPone) {
          allHands = new AllHands(updatedHand, allHands.dealerHand);
        } else {
          allHands = new AllHands(allHands.poneHand, updatedHand);
        }

        thePlay = thePlay.add(playerToPlayPlay);
      } else {
        thePlay = thePlay.addGo();
      }
      // console.log(`thePlay: ${thePlay}`);
    }

    totalScore[0] += thePlay.poneScore;
    totalScore[1] += thePlay.dealerScore;
  });
  const elapsedTimeNs: bigint = process.hrtime.bigint() - startTimeNs;
  console.log(
    `${workerNumberPrefix}Simulated ${handCount} hands in ${elapsedTimeNs} ns for ${
      elapsedTimeNs / BigInt(handCount)
    } ns per hand`
  );

  return totalScore;
};
