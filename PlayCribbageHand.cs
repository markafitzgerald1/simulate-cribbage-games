/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;

namespace MarkAFitzgerald1
{
    class PlayCribbageHand
    {
        [ThreadStatic] private static Random random;

        static void Main(string[] args)
        {
            int totalHands = args.Length >= 1 ? Int32.Parse(args[0]) : 1000000;
            // Console.WriteLine($"About to simluate {totalHands} hands");
            var stopWatch = Stopwatch.StartNew();

            ParallelEnumerable.Range(0, totalHands).ForAll((handNumber) =>
            {
                if (random == null)
                {
                    random = new Random();
                }
                var deal = DealTwoHands(random);
                // Console.WriteLine($"Deal: {string.Join(",", deal)}");
                var hands = new List<int>[] { deal.Take(4).ToList(), deal.Skip(4).ToList() };
+                // Console.WriteLine($"Hands: {string.Join(",", hands[0])} and {string.Join(",", hands[1])}");                var playerToPlay = 0;
                while (hands[0].Count() + hands[1].Count() > 0)
                {
                    if (hands[playerToPlay].Count() > 0)
                    {
                        var playerToPlayPlay = hands[playerToPlay][0];
                        hands[playerToPlay].RemoveAt(0);
                        // Console.WriteLine($"Player {playerToPlay + 1} has a play: {playerToPlayPlay}");
                    }
                    playerToPlay = (playerToPlay + 1) % 2;
                }
            }
            );

            stopWatch.Stop();
            // Console.WriteLine($"Stopwatch frequency = {Stopwatch.Frequency} Hz");
            Console.WriteLine($"Simulated {totalHands} hands in {1000000000L * stopWatch.ElapsedTicks / Stopwatch.Frequency} ns for {1000000000L * stopWatch.ElapsedTicks / Stopwatch.Frequency / totalHands} ns per hand");
        }

        private static List<int> DealTwoHands(Random random)
        {
            var deal = new HashSet<int>();
            do
            {
                deal.Add(random.Next(52));
            } while (deal.Count() < 8);
            return deal.ToList();
        }
    }
}
