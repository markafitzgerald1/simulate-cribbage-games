import java.util.stream.IntStream;

public class PlayCribbageHand {
    public static void main(String[] argv) {
        final var deck = IntStream.range(0, 52).toArray();
        final var nHands = argv.length >= 1 ? Integer.parseInt(argv[0]) : 1000;
        final var startTimeNs = System.nanoTime();

        // new org.apache.commons.math4.random.RandomUtils.DataGenerator();
        IntStream.range(0, nHands).forEach((number) -> {
            // System.out.println(number);
        });

        final var elapsedTimeNs = System.nanoTime() - startTimeNs;
        System.out.println(String.format("Simulated %d hands in %d ns for %f ns per hand", nHands, elapsedTimeNs,
                ((double) elapsedTimeNs) / nHands));
    }
}