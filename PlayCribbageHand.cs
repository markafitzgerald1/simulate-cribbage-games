/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
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

            var cardGenerator = StatisticsModule.UniformDiscrete(0, 51);
            var dealGenerator = UtilityModule.Choose(52, 8);
            var prngState = UtilityModule.CreateRandomState();
            foreach (int handNumber in Enumerable.Range(0, totalHands))
            {
                var (deal, nextPrngState) = DealTwoHands(cardGenerator, prngState);
                // Console.WriteLine($"Deal: {string.Join(",", deal)}");
                var hands = new List<List<int>> { deal.GetRange(0, 4), deal.GetRange(4, 4) };
                var playerToPlay = 0;
                while (hands.ElementAt(0).Count() + hands.ElementAt(1).Count() > 0)
                {
                    if (hands.ElementAt(playerToPlay).Count() > 0)
                    {
                        var playerToPlayPlay = hands.ElementAt(playerToPlay).ElementAt(0);
                        hands.ElementAt(playerToPlay).RemoveAt(0);
                        // Console.WriteLine($"Player {playerToPlay + 1} has a play: {playerToPlayPlay}");
                    }
                    playerToPlay = (playerToPlay + 1) % 2;
                }
                prngState = nextPrngState;
            }

            stopWatch.Stop();
            // Console.WriteLine($"Stopwatch frequency = {Stopwatch.Frequency} Hz");
            Console.WriteLine($"Simulated {totalHands} hands in {1000000000L * stopWatch.ElapsedTicks / Stopwatch.Frequency} ns for {1000000000L * stopWatch.ElapsedTicks / Stopwatch.Frequency / totalHands} ns per hand");
        }

        private static (List<int>, RNG.PrngState) DealTwoHands(RNG.GeneratorFunction<int> cardGenerator, RNG.PrngState prngState)
        {
            var deal = new HashSet<int>();
            do
            {
                var (card, nextPrngState) = RandomModule.Next(cardGenerator, prngState);
                deal.Add(card);
                prngState = nextPrngState;
            } while (deal.Count() < 8);
            return (deal.ToList(), prngState);
        }
    }
}
