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
import DiscardResult from "./cribbage/DiscardResult";

export default (
  mersenneTwisterEngine: Engine,
  handCount: number,
  hidePoneHand: boolean,
  hideDealerHand: boolean,
  hidePlayActions: boolean,
  workerNumber?: number
): [Points, Points] => {
  // console.log(`Worker simulating ${handCount} hands`);
  const totalScore: [Points, Points] = [0, 0];
  const startTimeNs: bigint = process.hrtime.bigint();
  const workerNumberPrefix = workerNumber ? `[worker ${workerNumber}] ` : "";
  const logHand = (role: string, action: string, hand: Hand | Card[]) => {
    const hide = role === "Pone" ? hidePoneHand : hideDealerHand;
    if (hide) return;
    const cards = hand instanceof Hand ? hand.cards : hand;
    const cardsString = hand instanceof Hand ? hand.toString() : `[${hand}]`;
    console.log(
      `${workerNumberPrefix}${role.padEnd(7)}${action.padEnd(10)}${cardsString} (sorted: [${[...cards]
        .sort(Card.compare)
        .reverse()}])`
    );
  };

  [...Array(handCount)].forEach(() => {
    const dealtHands: AllHands = dealAllHands(mersenneTwisterEngine, DECK);
    logHand("Pone", "dealt", dealtHands.poneHand);
    logHand("Dealer", "dealt", dealtHands.dealerHand);

    const poneDiscardResult: DiscardResult = discard(dealtHands.poneHand);
    const dealerDiscardResult: DiscardResult = discard(dealtHands.dealerHand);
    logHand("Pone", "discarded", poneDiscardResult.discards);
    logHand("Dealer", "discarded", dealerDiscardResult.discards);

    const keptHands: AllHands = new AllHands(
      poneDiscardResult.hand,
      dealerDiscardResult.hand
    );
    logHand("Pone", "kept", keptHands.poneHand);
    logHand("Dealer", "kept", keptHands.dealerHand);

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
    if (!hidePlayActions) {
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
