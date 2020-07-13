/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import java.util.ArrayList;
import java.util.stream.Collectors;
import java.util.stream.IntStream;

import org.apache.commons.math3.random.RandomDataGenerator;

public class PlayCribbageHand {
    public static void main(String[] argv) {
        final var deck = IntStream.range(0, 52).boxed().collect(Collectors.toCollection(ArrayList::new));
        final var nHands = argv.length >= 1 ? Integer.parseInt(argv[0]) : 1000;
        final var randomDataGenerator = new RandomDataGenerator();

        final var startTimeNs = System.nanoTime();
        IntStream.range(0, nHands).forEach((number) -> {
            randomDataGenerator.nextSample(deck, 8);
            // TODO: split into two hands

            // TODO: set player to play to 0

            // TODO: play cards from alternating hands until both hands empty (with
            // System.out output)
        });

        final var elapsedTimeNs = System.nanoTime() - startTimeNs;
        System.out.println(String.format("Simulated %d hands in %d ns for %f ns per hand", nHands, elapsedTimeNs,
                ((double) elapsedTimeNs) / nHands));
    }
}
