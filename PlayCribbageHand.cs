/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

using System;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using FsRandom;
using RNG = FsRandom.RandomNumberGenerator;

namespace MarkAFitzgerald1
{
    class PlayCribbageHand
    {
        static void Main(string[] args)
        {
            int totalHands = args.Length >= 1 ? Int32.Parse(args[0]) : 1000000;
            Console.WriteLine($"About to simluate {totalHands} hands");
            var stopWatch = Stopwatch.StartNew();

            var dealGenerator = UtilityModule.Choose(52, 8);
            var prngState = UtilityModule.CreateRandomState();
            foreach (int handNumber in Enumerable.Range(0, totalHands))
            {
                // Console.WriteLine($"Simulating hand number {handNumber + 1}...");
                var (deal, nextPrngState) = RandomModule.Next(dealGenerator, prngState);
                var dealArray = deal.ToArray();
                var (_, nextNextPrngState) = RandomModule.Next(ArrayModule.ShuffleInPlace<int>(dealArray), nextPrngState);
                // Console.WriteLine($"Deal: {string.Join(",", dealArray)}");
                prngState = nextNextPrngState;
            }

            stopWatch.Stop();
            // Console.WriteLine($"Stopwatch frequency = {Stopwatch.Frequency} Hz");
            Console.WriteLine($"Simulated {totalHands} hands in {1000000000L * stopWatch.ElapsedTicks / Stopwatch.Frequency} ns for {1000000000L * stopWatch.ElapsedTicks / Stopwatch.Frequency / totalHands} ns per hand");
        }
    }
}
