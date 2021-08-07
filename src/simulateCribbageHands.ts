/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import { hideBin } from "yargs/helpers";
import yargs from "yargs/yargs";
import Points from "./cribbage/Points";
import { MersenneTwister19937 } from "random-js";
import playCribbageHands from "./playCribbageHands";
import { Worker } from "worker_threads";

const HAND_COUNT = "hand-count";
const WORKER_COUNT = "worker-count";
const HIDE_PONE_HAND = "hide-pone-hand";
const HIDE_DEALER_HAND = "hide-dealer-hand";
const argv = yargs(hideBin(process.argv))
  .option(HAND_COUNT, {
    type: "number",
    default: 1,
  })
  .option(WORKER_COUNT, {
    type: "number",
    default: 1,
  })
  .option(HIDE_PONE_HAND, {
    type: "boolean",
    default: false,
  })
  .option(HIDE_DEALER_HAND, {
    type: "boolean",
    default: false,
  })
  .strict()
  .parseSync();

if (argv[WORKER_COUNT] === 1) {
  const totalScore: [Points, Points] = playCribbageHands(
    MersenneTwister19937.autoSeed(),
    argv[HAND_COUNT],
    argv[HIDE_PONE_HAND],
    argv[HIDE_DEALER_HAND]
  );
  console.log(
    `Average score: [${totalScore.map(
      (totalPlayerScore) => totalPlayerScore / argv[HAND_COUNT]
    )}]`
  );
} else {
  const evenHandCount =
    Math.ceil(argv[HAND_COUNT] / argv[WORKER_COUNT]) * argv[WORKER_COUNT];
  console.log(
    `Simulating ${evenHandCount} hands across ${argv[WORKER_COUNT]} worker threads`
  );
  const startTimeNs = process.hrtime.bigint();
  let nWorkersDone = 0;
  const workers = Array.from(Array(argv[WORKER_COUNT]).keys()).map(
    (workerNumber) =>
      new Worker("./src/playCribbageHandsWorker.js", {
        argv: [
          Math.floor(evenHandCount / argv[WORKER_COUNT]),
          argv[HIDE_PONE_HAND],
          argv[HIDE_DEALER_HAND],
          workerNumber + 1,
        ],
      })
  );
  const grandTotalScore: [Points, Points] = [0, 0];
  workers.forEach((worker) => {
    worker.once("message", (totalScore) => {
      grandTotalScore[0] += totalScore[0];
      grandTotalScore[1] += totalScore[1];
    });
    worker.on("exit", (code) => {
      nWorkersDone++;
      if (nWorkersDone === workers.length) {
        const elapsedTimeNs = process.hrtime.bigint() - startTimeNs;
        console.log(
          `Simulated ${evenHandCount} total hands with ${
            argv[WORKER_COUNT]
          } workers in ${elapsedTimeNs} ns for ${
            elapsedTimeNs / BigInt(evenHandCount)
          } ns per hand`
        );
        console.log(
          `Overall average score: [${grandTotalScore.map(
            (grandTotalPlayerScore) => grandTotalPlayerScore / evenHandCount
          )}]`
        );
      }
    });
  });
}
