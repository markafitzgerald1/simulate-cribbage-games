/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import { Worker } from "worker_threads";
const os = require("os");

const handCount = process.argv.length > 2 ? parseInt(process.argv[2]) : 730000;
const workerCount =
  process.argv.length > 3 ? parseInt(process.argv[3]) : os.cpus().length;

if (workerCount === 1) {
  require("./playCribbageHandWorker");
} else {
  const evenHandCount = Math.ceil(handCount / workerCount) * workerCount;
  console.log(
    `Simulating ${evenHandCount} hands across ${workerCount} worker threads`
  );
  const startTimeNs = process.hrtime.bigint();
  let nWorkersDone = 0;
  const workers = Array.from(Array(workerCount).keys()).map(
    (_) =>
      new Worker("./src/playCribbageHandWorker.js", {
        argv: [Math.floor(evenHandCount / workerCount)],
      })
  );
  const grandTotalScore = [0, 0];
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
          `Simulated ${evenHandCount} total hands in ${elapsedTimeNs} ns for ${
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
