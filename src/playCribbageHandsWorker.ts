/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import { MersenneTwister19937 } from "random-js";
import { parentPort } from "worker_threads";
import playCribbageHands from "./playCribbageHands";

if (!parentPort) {
  throw new Error("Module must be run as a Worker.");
}

const handCount: number =
  process.argv.length > 2 ? parseInt(process.argv[2]) : 390000;
// console.log(`Worker simulating ${handCount} hands`);
parentPort.postMessage(
  playCribbageHands(MersenneTwister19937.autoSeed(), handCount)
);
