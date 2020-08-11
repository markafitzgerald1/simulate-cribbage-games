/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.Random;
import java.util.stream.IntStream;

public class PlayCribbageHand {
    @SuppressWarnings("unchecked")
    public static void main(String[] argv) {
        final var nHands = argv.length >= 1 ? Integer.parseInt(argv[0]) : 1700000;
        final var random = new Random();

        final var startTimeNs = System.nanoTime();
        IntStream.range(0, nHands).parallel().forEach((number) -> {
            final var handsCards = dealTwoHands(random);
            // System.out.println(String.format("Deal: %s",
            // Arrays.stream(handsCards).map(card ->
            // getCardString(card)).collect(Collectors.toList())));

            final var handsCardsList = Arrays.asList(handsCards);
            final var hands = new ArrayList[] { new ArrayList<Integer>(handsCardsList.subList(0, 4)),
                    new ArrayList<Integer>(handsCardsList.subList(4, 8)) };
            // System.out.println(String.format("Hands: %s",
            // Arrays.stream(hands).map(hand -> ((ArrayList<Integer>) hand).stream()
            // .map(card -> getCardString(card)).collect(Collectors.toList()))
            // .collect(Collectors.toList())));

            var playerToPlay = 0;
            var playCount = 0;
            var consecutiveGoCount = 0;
            while (hands[0].size() + hands[1].size() > 0) {
                final var currentPlayCount = playCount;
                final var playableCard = ((ArrayList<Integer>) hands[playerToPlay]).stream()
                        .filter(card -> currentPlayCount + getPlayCount((int) card) <= 31).findFirst();
                if (playableCard.isPresent()) {
                    final var playerToPlayPlay = playableCard.get();
                    hands[playerToPlay].remove(playerToPlayPlay);
                    playCount += getPlayCount(playerToPlayPlay);
                    // System.out.println(String.format("Player %d plays %s for %d", (playerToPlay +
                    // 1),
                    // getCardString(playerToPlayPlay), playCount));
                    consecutiveGoCount = 0;
                } else {
                    // System.out.println(String.format("Player %d says \"Go!\"", (playerToPlay +
                    // 1)));
                    consecutiveGoCount++;
                    if (consecutiveGoCount == 2) {
                        // System.out.println("Resetting play count to 0.");
                        consecutiveGoCount = 0;
                        playCount = 0;
                    }
                }

                playerToPlay = (playerToPlay + 1) % 2;
            }
        });

        final var elapsedTimeNs = System.nanoTime() - startTimeNs;
        System.out.println(String.format("Simulated %d hands in %f s for %f ns per hand", nHands,
                elapsedTimeNs / 1000000000d, ((double) elapsedTimeNs) / nHands));
    }

    private static Integer[] dealTwoHands(final Random random) {
        var deal = new LinkedHashSet<Integer>();
        do {
            deal.add(random.nextInt(52));
        } while (deal.size() < 8);
        return (Integer[]) deal.toArray(new Integer[8]);
    }

    private static int getPlayCount(int playerToPlayPlay) {
        return Math.min((playerToPlayPlay % 13) + 1, 10);
    }

    private static String getCardString(int card) {
        return String.format("%c%c", "A23456789TJQK".charAt(card % 13), "♣♦♥♠".charAt(card / 13));
    }
}
