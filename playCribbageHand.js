const { Worker } = require("worker_threads");
const os = require("os");

const nHands = process.argv.length > 2 ? parseInt(process.argv[2]) : 730000;
const nWorkers =
  process.argv.length > 3 ? parseInt(process.argv[3]) : os.cpus().length;

if (nWorkers === 1) {
  require("./playCribbageHandWorker");
} else {
  console.log(`Simulating ${nHands} hands across ${nWorkers} worker threads`);
  const startTimeNs = process.hrtime.bigint();
  let nWorkersDone = 0;
  const workers = Array.from(Array(nWorkers).keys()).map(
    (_) =>
      new Worker("./playCribbageHandWorker.js", {
        argv: [Math.floor(nHands / nWorkers)],
      })
  );
  workers.forEach((worker) =>
    worker.on("exit", (code) => {
      nWorkersDone++;
      if (nWorkersDone === workers.length) {
        const elapsedTimeNs = process.hrtime.bigint() - startTimeNs;
        console.log(
          `Simulated ${nHands} total hands in ${elapsedTimeNs} ns for ${
            elapsedTimeNs / BigInt(nHands)
          } ns per hand`
        );
      }
    })
  );
}
