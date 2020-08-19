/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

const randomJs = require("random-js");
const workerThreads = require("worker_threads");

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

const handCount = process.argv.length > 2 ? parseInt(process.argv[2]) : 390000;
// console.log(`Worker simulating ${handCount} hands`);
let totalScore = [0, 0];
const startTimeNs = process.hrtime.bigint();
[...Array(handCount)].forEach((_) => {
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
  let mostRecentlyPlayedIndex = undefined;
  let mostRecentlyPlayedIndexCount = 0;
  let score = [0, 0];
  let currentPlayPlays = [];
  while (hands[0].length + hands[1].length > 0) {
    const playableCards = hands[playerToPlay].filter(
      (card) => playCount + card.count <= 31
    );
    if (playableCards.length > 0) {
      const playerToPlayPlay = playableCards[0];
      hands[playerToPlay] = hands[playerToPlay].filter(
        (card) => card !== playerToPlayPlay
      );
      currentPlayPlays.push(playerToPlayPlay);
      playCount += playerToPlayPlay.count;
      // console.log(
      //   `Player ${
      //     playerToPlay + 1
      //   } plays ${playerToPlayPlay} for ${playCount}; current play plays = ${currentPlayPlays}.`
      // );

      // Pairs points
      if (playerToPlayPlay.index === mostRecentlyPlayedIndex) {
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
      if (playCount == 15) {
        // console.log(`!15 for 2 points for player ${playerToPlay + 1}.`);
        score[playerToPlay] += 2;
      } else if (playCount == 31) {
        // console.log(`!31 for 1 point for player ${playerToPlay + 1}.`);
        score[playerToPlay] += 1;
      }

      // Runs points
      if (currentPlayPlays.length >= 3) {
        for (
          let runLength = currentPlayPlays.length;
          runLength >= 3;
          runLength--
        ) {
          // console.log(`Checking for run of length ${runLength}...`);
          const sortedRecentPlayIndices = currentPlayPlays
            .slice(-runLength)
            .map((play) => play.index);
          sortedRecentPlayIndices.sort((a, b) => a - b);
          // console.log(
          //   `run length ${runLength} sorted indices: ${sortedRecentPlayIndices}`
          // );
          let adjacentIndexCount = 0;
          for (let playIndex = 0; playIndex < runLength - 1; playIndex++) {
            if (
              sortedRecentPlayIndices[playIndex + 1] -
                sortedRecentPlayIndices[playIndex] ===
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
        // [...Array(currentPlayPlays.length - 3 + 1).keys()]
        //   .map((runLength) => currentPlayPlays.length - runLength)
        //   .forEach((runLength) => {
        //     console.log(`Checking for run of length ${runLength}...`);
        //   const sortedRecentPlayIndices = currentPlayPlays
        //     .slice(-runLength)
        //     .map((play) => play.index);
        //   sortedRecentPlayIndices.sort((a, b) => a - b);
        //   console.log(
        //     `run length ${runLength} sorted indices: ${sortedRecentPlayIndices}`
        //   );
        //   let adjacentIndexCount = 0;
        //   for (playIndex in [...Array(runLength - 1)]) {
        //     console.log(`playIndex: ${playIndex}`);
        //     if (
        //       sortedRecentPlayIndices[playIndex + 1] -
        //         sortedRecentPlayIndices[playIndex] ===
        //       1
        //     ) {
        //       adjacentIndexCount++;
        //     }
        //   }
        //   if (adjacentIndexCount === runLength - 1) {
        //     console.log(
        //       `!Run for ${runLength} points for player ${playerToPlay + 1}.`
        //     );
        //     score[playerToPlay] += runLength;
        //     break;
        //   }
        // });
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
        playCount = 0;
        currentPlayPlays = [];
        mostRecentlyPlayedIndex = undefined;
        mostRecentlyPlayedIndexCount = 0;
      }
    }

    playerToPlay = (playerToPlay + 1) % 2;
  }

  // Last Card points
  lastPlayerToPlay = (playerToPlay + 1) % 2;
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

if (workerThreads.parentPort) {
  workerThreads.parentPort.postMessage(totalScore);
} else if (workerThreads.isMainThread) {
  console.log(
    `Average score: [${totalScore.map(
      (totalPlayerScore) => totalPlayerScore / handCount
    )}]`
  );
}
