# Strength ladder

How strong is each cribbage engine in this project? The ladder answers by
having engines play each other in full games to 121 and counting who wins.

## Results so far

The first ladder compares three ways of pegging (playing cards after the
discard). All three discard the same way, so the differences below come from
pegging alone. Each match is 100,000 games: 50,000 deals, each played twice
with the seats swapped.

| Match | Upper player wins | Elo gap |
| --- | ---: | ---: |
| legacy heuristic vs random | 67.54% +/- 0.11% | 127.3 +/- 0.9 |
| CFR+ vs legacy heuristic | 56.32% +/- 0.09% | 44.2 +/- 0.7 |
| CFR+ vs random | 68.72% +/- 0.11% | 136.8 +/- 0.9 |

The players:

- **random** plays a uniformly random playable card.
- **legacy heuristic** plays the simulator's long-standing default rule.
- **CFR+** is the six-layer pegging policy solved by counterfactual-regret
  minimization, the policy behind the newest published play table.

What the numbers say:

- **CFR+ pegs better than the legacy heuristic.** With identical discards it
  wins 56.3% of games against it, 6.3 percentage points better than an even
  match.
- **Against random play, better pegging adds little.** CFR+ wins 68.7% against
  random, only 1.2 points more than the heuristic's 67.5%. Its advantage
  shows against a competent opponent.
- **Elo gaps do not add up along the ladder.** 127.3 + 44.2 = 171.5, but CFR+
  measures 136.8 above random directly. The 34.7-point difference (from
  unrounded values) is 25 standard errors (1.4 Elo), so it is real, not noise. An Elo gap here
  describes one pairing, not a rating that holds against every opponent.
- **Who deals first matters about as much as CFR+'s edge.** In every match a
  player wins 10.6 to 12.0 points more often as first dealer than as first
  pone. That is about 5.3 to 6.0 points either side of its average.

Next: discard rungs, from a random keep up to the trainer's current advice
(issue #263).

## How a match is measured

A deal pair is two games on one seed with the seats swapped, so both players
hold the same cards in the same seat for as long as both games last
(`artifact_pipeline/ladder_game.py`). The game follows cribbage counting order
and stops at the first count that reaches 121: his heels, each pegging play,
the pone's hand, the dealer's hand, then the crib. The winner is recorded at
121.

The win rate is the mean over pairs of the upper player's share of the pair's
two games. Its standard error comes from the spread of those per-pair results,
because pairs are independent and the two games of a pair are not
(`artifact_pipeline/ladder_match.py`). Pairing helps: for CFR+ against the
heuristic the SE is 0.09 points, against 0.16 if the 100,000 games were
treated as independent. Each match draws its own deals, so the matches are
independent of each other and their standard errors combine by adding
variances. Elo is the delta-method transform of one match's win rate and SE.

Every rung keeps the ranks named by the rank-only discard population bound
into the CFR policy bundle (`discard_population`). When a kept rank has several
dealt cards to choose from, the seat's random stream picks one, so no suit is
favored. These are not the app's suit-aware discard tables.

## The full run

[`strength-ladder-50000.json`](strength-ladder-50000.json) holds every match
in both orientations: win rates as first pone and as first dealer, point and
pegging margins, game length, pair outcomes, and the CFR policy's decision
counts.

| Match | As first pone | As first dealer | Pegging margin | Won both / split / lost both |
| --- | ---: | ---: | ---: | ---: |
| legacy heuristic vs random | 62.26% +/- 0.22 | 72.82% +/- 0.20 | 9.15 +/- 0.02 | 17,791 / 31,957 / 252 |
| CFR+ vs legacy heuristic | 50.33% +/- 0.22 | 62.31% +/- 0.22 | 3.19 +/- 0.02 | 7,812 / 40,698 / 1,490 |
| CFR+ vs random | 63.39% +/- 0.22 | 74.06% +/- 0.20 | 9.79 +/- 0.02 | 18,898 / 30,928 / 174 |

The pegging margin is the mean, per game, of the upper player's pegging points
minus the opponent's (his heels excluded). A game averages 9.1 to 9.2 hands.

Against the heuristic the CFR policy was called 3.60 million times. 1.23
million calls were forced (one legal rank). None of the 2.38 million
non-forced calls fell back to the heuristic for a missing menu, so every one
used a stored row. 1.4% of them were off-support: a state with zero opponent
reach under the saved policy and prior, where the policy still samples its
stored row. "Off-support" does not mean untrained or uncertified. Against
random play the share was 6.5% of 2.40 million non-forced calls. These shares
describe these two opponents only.

## Reproducing it

```bash
python -m artifact_pipeline.strength_ladder \
  --policy-manifest <bundle>/policy.json \
  --policy-manifest-sha256 bc096b75f956c2091c3be73cfe2d9eec0157c87bc30ef6e11e0b283e1007171b \
  --pairs 50000 --workers 8 --cross-table --seed 42 \
  --output strength-ladder-50000.json
```

`<bundle>` is the `fixed-play-policy-inputs` artifact of
`bundle-cfr-inputs.yml` run 45528665715. That run bundled the outputs of
`generate-cfr-inputs.yml` run 45322543914, and these are the inputs
`examples/fixed-play-inputs.json` pins. `--policy-manifest-sha256` makes the
command refuse any other manifest. The report records these digests:

| Input | SHA-256 |
| --- | --- |
| `policy.json` | `bc096b75f956c2091c3be73cfe2d9eec0157c87bc30ef6e11e0b283e1007171b` |
| policy behavioral fingerprint | `97e802efc11697e9b992e6414a9b279ff4ebf5f064e1dc9a4dbbf2d567f30871` |
| discard population | `a956301cc916cfbf147dd14bff12dc0d3cf29b006a29eda2da7460bb178d12bf` |

The recorded run used commit b10875a and Python 3.14.10. Workers change
nothing but the time taken. They are forked, so more than one needs a
platform with the fork start method. On an 8-core Apple M2 laptop, the three
matches (300,000 games) took 2 minutes 56 seconds, about a minute of it
loading and verifying the policy. Peak memory was about 770 MB.
