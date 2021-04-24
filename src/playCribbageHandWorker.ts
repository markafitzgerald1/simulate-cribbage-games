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
  // console.log(`Deal is ${deal}.`);
  let allHands: AllHands = dealAllHands(mersenneTwisterEngine, DECK);
  // console.log(
  //   `Hands are ${hands
  //     .map((hand) => hand.map((card) => card.toString()))
  //     .join("; ")}.`
  // );
  let playerToPlay = 0;
  let consecutiveGoCount = 0;
  let mostRecentlyPlayedIndex = undefined;
  let mostRecentlyPlayedIndexCount = 0;
  let score = [0, 0];
  let currentPlayTo31: PlayTo31 = PlayTo31.create();
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
      // console.log(
      //   `Player ${
      //     playerToPlay + 1
      //   } plays ${playerToPlayPlay} for ${playCount}; current play plays = ${currentPlayPlays}.`
      // );

      // Pairs points
      if (playerToPlayPlay.index.value === mostRecentlyPlayedIndex?.value) {
        mostRecentlyPlayedIndexCount++;
        if (mostRecentlyPlayedIndexCount === 4) {
          // console.log(
          //   `!Double pairs royale for 12 points for player ${playerToPlay + 1}`
          // );
          score[playerToPlay] += 12;
        } else if (mostRecentlyPlayedIndexCount === 3) {
          // console.log(
          //   `!Pairs royale for 6 points for player ${playerToPlay + 1}`
          // );
          score[playerToPlay] += 6;
        } else if (mostRecentlyPlayedIndexCount === 2) {
          // console.log(`!Pair for 2 points for player ${playerToPlay + 1}`);
          score[playerToPlay] += 2;
        }
      } else {
        mostRecentlyPlayedIndex = playerToPlayPlay.index;
        mostRecentlyPlayedIndexCount = 1;
      }

      // 15 and 31 count points
      if (currentPlayTo31.count == 15) {
        // console.log(`!15 for 2 points for player ${playerToPlay + 1}.`);
        score[playerToPlay] += 2;
      } else if (currentPlayTo31.count == 31) {
        // console.log(`!31 for 1 point for player ${playerToPlay + 1}.`);
        score[playerToPlay] += 1;
      }

      // Runs points
      if (currentPlayTo31.cards.length >= 3) {
        for (
          let runLength = currentPlayTo31.cards.length;
          runLength >= 3;
          runLength--
        ) {
          const sortedRecentPlayIndices = currentPlayTo31.cards
            .slice(-runLength)
            .map((play) => play.index);
          sortedRecentPlayIndices.sort((a, b) => a.value - b.value);
          let adjacentIndexCount = 0;
          for (let playIndex = 0; playIndex < runLength - 1; playIndex++) {
            if (
              sortedRecentPlayIndices[playIndex + 1].value -
                sortedRecentPlayIndices[playIndex].value ===
              1
            ) {
              adjacentIndexCount++;
            }
          }
          if (adjacentIndexCount === runLength - 1) {
            // console.log(
            //   `!Run for ${runLength} points for player ${playerToPlay + 1}.`
            // );
            score[playerToPlay] += runLength;
            break;
          }
        }
      }

      consecutiveGoCount = 0;
    } else {
      // console.log(`Player ${playerToPlay + 1} says "Go!"`);
      consecutiveGoCount++;
      if (consecutiveGoCount == 2) {
        // console.log(`!Go for 1 point for player ${playerToPlay + 1}.`);
        score[playerToPlay] += 1;

        // console.log("---resetting play count to 0---");
        consecutiveGoCount = 0;
        currentPlayTo31 = PlayTo31.create();
        mostRecentlyPlayedIndex = undefined;
        mostRecentlyPlayedIndexCount = 0;
      }
    }

    playerToPlay = (playerToPlay + 1) % 2;
  }

  // Last Card points
  const lastPlayerToPlay = (playerToPlay + 1) % 2;
  // console.log(`!Last card for 1 point for player ${lastPlayerToPlay + 1}.`);
  score[lastPlayerToPlay] += 1;

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
