/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

using System;
using System.Diagnostics;
using System.Threading;

namespace MarkAFitzgerald1
{
    class PlayCribbageHand
    {
        static void Main(string[] args)
        {
            var nHands = args.Length >= 1 ? Int64.Parse(args[0]) : 1000000;
            Console.WriteLine($"About to simluate {nHands} hands");
            var stopWatch = Stopwatch.StartNew();
            Thread.Sleep(1000);
            stopWatch.Stop();
            // Console.WriteLine($"Stopwatch frequency = {Stopwatch.Frequency} Hz");
            Console.WriteLine($"RunTime {1000000000L * stopWatch.ElapsedTicks / Stopwatch.Frequency} ns");
        }
    }
}
