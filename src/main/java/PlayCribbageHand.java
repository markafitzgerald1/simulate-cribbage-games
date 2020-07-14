/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.Random;
import java.util.stream.IntStream;

public class PlayCribbageHand {
    public static void main(String[] argv) {
        final var nHands = argv.length >= 1 ? Integer.parseInt(argv[0]) : 1000;
        final var random = new Random();

        final var startTimeNs = System.nanoTime();
        IntStream.range(0, nHands).forEach((number) -> {
            final var handsCards = dealTwoHands(random);
            // System.out.println(String.format("Deal: %s", Arrays.toString(handsCards)));

            final var handsCardsList = Arrays.asList(handsCards);
            final var poneHand = new ArrayList<Integer>(handsCardsList.subList(0, 4));
            final var dealerHand = new ArrayList<Integer>(handsCardsList.subList(4, 8));

            var poneToPlay = true;

            while (!poneHand.isEmpty() && !dealerHand.isEmpty()) {
                // TODO: merge blocks via hand array
                if (poneToPlay && !poneHand.isEmpty()) {
                    final var playerToPlayPlay = poneHand.get(poneHand.size() - 1);
                    poneHand.remove(poneHand.size() - 1);
                    // System.out.println(String.format("Pone has a play: %s", playerToPlayPlay));
                } else if (!poneToPlay && !dealerHand.isEmpty()) {
                    final var playerToPlayPlay = dealerHand.get(dealerHand.size() - 1);
                    dealerHand.remove(dealerHand.size() - 1);
                    // System.out.println(String.format("Dealer has a play: %s", playerToPlayPlay));
                }
                poneToPlay = !poneToPlay;
            }
        });

        final var elapsedTimeNs = System.nanoTime() - startTimeNs;
        System.out.println(String.format("Simulated %d hands in %d ns for %f ns per hand", nHands, elapsedTimeNs,
                ((double) elapsedTimeNs) / nHands));
    }

    private static Integer[] dealTwoHands(final Random random) {
        var deal = new LinkedHashSet<Integer>();
        do {
            deal.add(random.nextInt(52));
        } while (deal.size() < 8);
        return (Integer[]) deal.toArray(new Integer[8]);
    }
}
