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
import discard from "./cribbage/discard";

export default (
  mersenneTwisterEngine: Engine,
  handCount: number,
  hidePoneHand: boolean,
  hideDealerHand: boolean,
  hidePlayActions: boolean,
  workerNumber?: number
): [Points, Points] => {
  // console.log(`Worker simulating ${handCount} hands`);
  let totalScore: [Points, Points] = [0, 0];
  const startTimeNs: bigint = process.hrtime.bigint();
  const workerNumberPrefix = workerNumber ? `[worker ${workerNumber}] ` : "";
  [...Array(handCount)].forEach((_) => {
    let dealtHands: AllHands = dealAllHands(mersenneTwisterEngine, DECK);
    if (!hidePoneHand) {
      console.log(`${workerNumberPrefix}Pone   dealt ${dealtHands.poneHand}`);
    }
    if (!hideDealerHand) {
      console.log(`${workerNumberPrefix}Dealer dealt ${dealtHands.dealerHand}`);
    }

    const keptHands: AllHands = new AllHands(
      discard(dealtHands.poneHand).hand,
      discard(dealtHands.dealerHand).hand
    );
    if (!hidePoneHand) {
      console.log(`${workerNumberPrefix}Pone   kept  ${keptHands.poneHand}`);
    }
    if (!hideDealerHand) {
      console.log(`${workerNumberPrefix}Dealer kept  ${keptHands.dealerHand}`);
    }

    let playHands: AllHands = keptHands;
    let thePlay: ThePlay = ThePlay.create();
    while (
      playHands.poneHand.cards.length + playHands.dealerHand.cards.length >
      0
    ) {
      const playerToPlayHand: Hand = thePlay.nextPlayerToPlay.isPone
        ? playHands.poneHand
        : playHands.dealerHand;
      const playableCards: readonly Card[] =
        thePlay.getPlayableCards(playerToPlayHand);
      if (playableCards.length > 0) {
        const playerToPlayPlay: Card = playableCards[0];
        const updatedHand: Hand = playerToPlayHand.remove(playerToPlayPlay);
        if (thePlay.nextPlayerToPlay.isPone) {
          playHands = new AllHands(updatedHand, playHands.dealerHand);
        } else {
          playHands = new AllHands(playHands.poneHand, updatedHand);
        }

        thePlay = thePlay.add(playerToPlayPlay);
      } else {
        thePlay = thePlay.addGo();
      }
    }
    if (!hidePoneHand) {
      console.log(`thePlay: ${thePlay}`);
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
