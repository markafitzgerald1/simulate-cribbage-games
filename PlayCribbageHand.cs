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
        [ThreadStatic] private static Random? random;

        static void Main(string[] args)
        {
            int totalHands = args.Length >= 1 ? Int32.Parse(args[0]) : 973000;
            int degreeOfParallelism = args.Length >= 2 ? Int32.Parse(args[1]) : Environment.ProcessorCount;
            Console.WriteLine($"Simluating {totalHands} hands with degree of parallelism {degreeOfParallelism}");
            var stopWatch = Stopwatch.StartNew();

            ParallelEnumerable.Range(0, totalHands)
                .WithDegreeOfParallelism(degreeOfParallelism)
                .ForAll((handNumber) =>
            {
                if (random == null)
                {
                    random = new Random();
                }

                var deal = DealTwoHands(random);
                // Console.WriteLine($"Deal: {string.Join(",", deal.Select(card => CardString(card)))}");
                var hands = new List<int>[] { deal.Take(4).ToList(), deal.Skip(4).ToList() };
                // Console.WriteLine($"Hands: {string.Join(",", hands[0].Select(card => CardString(card)))}; {string.Join(",", hands[1].Select(card => CardString(card)))}");
                var playerToPlay = 0;
                var playCount = 0;
                while (hands[0].Count() + hands[1].Count() > 0)
                {
                    if (hands[playerToPlay].Count() > 0)
                    {
                        var playerToPlayPlay = hands[playerToPlay][0];
                        hands[playerToPlay].RemoveAt(0);
                        playCount += CountingValue(playerToPlayPlay);
                        // Console.WriteLine($"Player {playerToPlay + 1} plays {CardString(playerToPlayPlay)} for {playCount}");
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
            var deal = new List<int>();
            do
            {
                int item = random.Next(52);
                if (!deal.Contains(item))
                {
                    deal.Add(item);
                }
            } while (deal.Count() < 8);
            return deal;
        }

        private static int CountingValue(int playerToPlayPlay)
        {
            return Math.Min((playerToPlayPlay % 13) + 1, 10);
        }

        private static string CardString(int playerToPlayPlay)
        {
            return $"{"A23456789TJQK"[playerToPlayPlay % 13]}{"♣♦♥♠"[playerToPlayPlay / 13]}";
        }
    }
}
