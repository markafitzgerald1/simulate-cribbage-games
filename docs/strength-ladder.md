# Strength ladder

How strong is each cribbage engine in this project? The ladder answers by
having engines play each other in full games to 121 and counting who wins.
Each match is 100,000 games: 50,000 deals, each played twice with the seats
swapped.

## From random play to the trainer's advice

Six players, each a way of discarding plus a way of pegging (playing cards
after the discard):

| Player | Discards | Pegging |
| --- | --- | --- |
| random | four cards kept at random | a random playable card |
| hand | the best hand on average over the 46 starters it has not seen | legacy heuristic |
| hand-crib | hand, plus its own crib or minus the opponent's, from the crib table | legacy heuristic |
| app-june | the trainer app's advice with its June 2026 crib and play tables | legacy heuristic |
| app-nov | the trainer app's advice with its November 2026 tables | legacy heuristic |
| app-nov-cfr | the same November advice | CFR+ |

Every row of this cross table is that player's win rate against each
column, in percent. Each cell's standard error is 0.03 to 0.11 points.

| | random | hand | hand-crib | app-june | app-nov | app-nov-cfr |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| random | | 1.07 | 0.67 | 0.72 | 0.68 | 0.68 |
| hand | 98.93 | | 46.07 | 45.41 | 45.64 | 40.07 |
| hand-crib | 99.33 | 53.93 | | 49.36 | 49.70 | 43.68 |
| app-june | 99.28 | 54.59 | 50.64 | | 50.27 | 44.59 |
| app-nov | 99.32 | 54.36 | 50.30 | 49.73 | | 44.42 |
| app-nov-cfr | 99.32 | 59.93 | 56.32 | 55.41 | 55.58 | |

What the numbers say:

- **A sensible player crushes random play.** hand, which keeps the best
  average hand and pegs with the legacy heuristic, wins 98.9% of games
  against random discards and random pegging. It lost both games of none of
  the 50,000 deal pairs.
- **Counting the crib adds 3.9 points.** hand-crib beats hand 53.93% +/-
  0.10%. Its keeps peg 0.57 points a game worse, yet it finishes 1.99 points
  a game ahead.
- **The play table adds little to heuristic pegging.** Adding the November
  play table to hand-crib's crib table (app-nov) wins 50.30% +/- 0.08%. The
  June advice wins 50.64% +/- 0.08% against hand-crib, but it also uses an
  older crib table. With heuristic pegging the November tables do slightly
  worse than the June ones, 49.73% +/- 0.07%. The November play table was
  measured with CFR+ pegging, so it recommends keeps for a player who pegs
  that way. The play table's release reports 49.724% +/- 0.023% for the
  same comparison with one crib table for both.
- **CFR+ pegging is the largest step after the crib.** With the same
  November discard rule, CFR+ pegging wins 55.58% +/- 0.09% against the
  legacy heuristic. Today's trainer advice with CFR+ pegging wins 59.93%
  against hand, a comparison of complete bots that differ in both discards
  and pegging.
- **These are bots, not people.** The ladder shows which advice wins when a
  bot follows it exactly. It does not show how much a person gains.

The app-june player applies the app's current ranking to the tables it
shipped in June 2026. The app's code then may have ranked keeps a little
differently.

## Hand points before and after the cut

These five players all peg with the legacy heuristic. Each hand-only player
scores all 15 four-card keeps and draws uniformly among the best.

| Player | How it ranks each keep |
| --- | --- |
| random keep | Uniform choice among the 15 keeps |
| pre-cut-rank | Four-card points for pairs, runs and fifteens |
| pre-cut-suit | The same points, plus four for a four-card flush |
| hand-48 | Average hand points over the 48 cards outside the keep |
| hand-46 | Average hand points over the 46 cards outside the deal, the hand rule used above |

Before the cut the hand has no starter to score for nobs. The legacy
suit-aware pre-cut flag attempts to read the missing starter's suit on a
flush. The ladder awards the four-card flush directly. Both post-cut
averages include flush and nobs points and enumerate physical starters.
The 48-card model treats the two discarded cards as possible starters for
ranking purposes. Real games always draw the starter from outside both
dealt hands. The legacy simulator uses a 48-card rank-only average in one
branch of its hand-plus-crib rule. The suit-aware 48-card rung here measures
the starter-pool change in isolation.

For 2C 3C 4C 4S JC JS, pre-cut-rank keeps 2C 3C 4C 4S for eight points
from a pair and two runs. Pre-cut-suit keeps 2C 3C 4C JC for nine points
from a run, a fifteen and a flush.

For AC 5C 6S 7D 9H JD, the 48-card model keeps 5C 6S 7D 9H. Across all
15 keeps its best total is 387 points over 48 starters, one more than the
5C 6S 7D JD keep. Excluding both discards reverses their order. The JD
keep leads with 374 over 46 starters versus 373 for the 9H keep.

The full run used seed 42 on Python 3.14.10. Each of the ten matchups drew
50,000 independent deal pairs and played 100,000 games. The table gives
the first player's win rate and Elo gap, each with one standard error
computed over the deal pairs. Win-rate errors are in percentage points.

| Match | Win % | Elo gap |
| --- | ---: | ---: |
| pre-cut-rank vs random keep | 94.58 +/- 0.07 | 496.89 +/- 2.36 |
| pre-cut-suit vs random keep | 95.25 +/- 0.07 | 520.72 +/- 2.52 |
| pre-cut-suit vs pre-cut-rank | 51.98 +/- 0.07 | 13.73 +/- 0.46 |
| hand-48 vs random keep | 96.30 +/- 0.06 | 566.36 +/- 2.86 |
| hand-48 vs pre-cut-rank | 56.79 +/- 0.11 | 47.48 +/- 0.76 |
| hand-48 vs pre-cut-suit | 54.60 +/- 0.10 | 32.08 +/- 0.72 |
| hand-46 vs random keep | 96.23 +/- 0.06 | 562.84 +/- 2.83 |
| hand-46 vs pre-cut-rank | 56.66 +/- 0.11 | 46.52 +/- 0.76 |
| hand-46 vs pre-cut-suit | 54.91 +/- 0.10 | 34.21 +/- 0.72 |
| hand-46 vs hand-48 | 50.00 +/- 0.03 | -0.01 +/- 0.23 |

Counting pre-cut flushes lifted the win rate to 51.98% against suitless
scoring. Averaging over starters gave a larger edge against pre-cut
suit-aware scoring, with both models winning over 54.5% of games. The two
starter pools produced an essentially even head-to-head match.

The command needs no policy bundle or crib and play tables.

```bash
python -m artifact_pipeline.strength_ladder \
  --discards random --rungs heuristic,pre-cut-rank,pre-cut-suit,hand-48,hand-46 \
  --hand-player pre-cut-rank pre-cut-rank \
  --hand-player pre-cut-suit pre-cut-suit \
  --hand-player hand-48 post-cut-48 \
  --hand-player hand-46 post-cut-46 \
  --workers 8 --cross-table --seed 42 --pairs 50000 --output hand-50000.json
```

The CLI name `heuristic` uses random keeps here. The first cross table above
uses random pegging for its random player.

Issue #263 still calls for crib tables built against random and hand-only
opponents and a history of past defaults against one fixed reference.

## Pegging alone

The first ladder compares three ways of pegging. All three discard the same
way, so the differences below come from pegging alone.

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
  unrounded values) is 25 standard errors (1.4 Elo), so it is real, not
  noise. An Elo gap here describes one pairing, not a rating that holds
  against every opponent.
- **Who deals first matters about as much as CFR+'s edge.** In every match a
  player wins 10.6 to 12.0 points more often as first dealer than as first
  pone. That is about 5.3 to 6.0 points either side of its average.

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

The app players (`artifact_pipeline/table_discards.py`) rank the 15 possible
keeps as the trainer app does: the exact hand value over the 46 unseen
starters; the crib table's mean for the two discards, per starter rank and,
for suited or Jack discards, per starter suit; and the play table's mean
pegging margin for the kept ranks. The crib is added as dealer and
subtracted as pone. A check run while writing this page, outside the test
suite, ran the app's own TypeScript on 4,000 random deals: for each table
set all 60,000 keep values matched to within 1e-14, and every keep the
ladder chose was among the app's best. The app breaks exact ties by rank and
then suit; here the seat's random stream picks among them, so no suit is
favoured. 110 of those 4,000 deals (2.75%) had such a tie.

In the pegging ladder every rung keeps the ranks named by the rank-only
discard population bound into the CFR policy bundle (`discard_population`).
When a kept rank has several dealt cards to choose from, the seat's random
stream picks one. These are not the app's suit-aware discard tables.

## The full runs

[`strength-ladder-tables-50000.json`](strength-ladder-tables-50000.json)
holds the six-player cross table and
[`strength-ladder-50000.json`](strength-ladder-50000.json) the pegging
ladder. Each holds every match in both orientations: win rates as first pone
and as first dealer, point and pegging margins, game length, pair outcomes,
and the CFR policy's decision counts.

| Pegging match | As first pone | As first dealer | Pegging margin | Won both / split / lost both |
| --- | ---: | ---: | ---: | ---: |
| legacy heuristic vs random | 62.26% +/- 0.22 | 72.82% +/- 0.20 | 9.15 +/- 0.02 | 17,791 / 31,957 / 252 |
| CFR+ vs legacy heuristic | 50.33% +/- 0.22 | 62.31% +/- 0.22 | 3.19 +/- 0.02 | 7,812 / 40,698 / 1,490 |
| CFR+ vs random | 63.39% +/- 0.22 | 74.06% +/- 0.20 | 9.79 +/- 0.02 | 18,898 / 30,928 / 174 |

The pegging margin is the mean, per game, of the upper player's pegging points
minus the opponent's (his heels excluded). A game averages 9.1 to 9.2 hands
in these matches and 8.9 to 9.3 in the cross table's.

Against the heuristic the CFR policy was called 3.60 million times. 1.23
million calls were forced (one legal rank). None of the 2.38 million
non-forced calls fell back to the heuristic for a missing menu, so every one
used a stored row. 1.4% of them were off-support: a state with zero opponent
reach under the saved policy and prior, where the policy still samples its
stored row. "Off-support" does not mean untrained or uncertified. Against
random play the share was 6.5% of 2.40 million non-forced calls. These shares
describe these two opponents only. In the cross table, with the app's
discards, the share was 1.5% against each heuristic player and 6.9% against
random, again with no fallbacks.

## Reproducing them

The pegging ladder:

```bash
python -m artifact_pipeline.strength_ladder \
  --policy-manifest <bundle>/policy.json \
  --policy-manifest-sha256 bc096b75f956c2091c3be73cfe2d9eec0157c87bc30ef6e11e0b283e1007171b \
  --pairs 50000 --workers 8 --cross-table --seed 42 \
  --output strength-ladder-50000.json
```

The cross table:

```bash
python -m artifact_pipeline.strength_ladder \
  --policy-manifest <bundle>/policy.json \
  --policy-manifest-sha256 bc096b75f956c2091c3be73cfe2d9eec0157c87bc30ef6e11e0b283e1007171b \
  --discards random \
  --rungs random,hand,hand-crib,app-june,app-nov,app-nov-cfr \
  --table-player hand heuristic none none \
  --table-player hand-crib heuristic crib-nov.json none \
  --table-player app-june heuristic crib-june.json play-june.json \
  --table-player app-nov heuristic crib-nov.json play-nov.json \
  --table-player app-nov-cfr cfr crib-nov.json play-nov.json \
  --pairs 50000 --workers 8 --cross-table --seed 42 \
  --output strength-ladder-tables-50000.json
```

`<bundle>` is the `fixed-play-policy-inputs` artifact of
`bundle-cfr-inputs.yml` run 45528665715. That run bundled the outputs of
`generate-cfr-inputs.yml` run 45322543914, and these are the inputs
`examples/fixed-play-inputs.json` pins. `--policy-manifest-sha256` makes the
command refuse any other manifest. The November tables are the
`expected_crib_points.client.json` asset of this repository's
`expected-crib-points` release as uploaded on 2026-11-06 and the
`expected_play_points.client.json` asset of `expected-play-points` as
uploaded on 2026-11-25; the trainer vendors the same bytes at commit
87bdc3f4. Those releases are replaced in place, so check a download against
the digest below. The June
tables are the trainer's `src/game/expectedCribPointsTable.json` at commit
f3697d51 and `src/game/expectedPlayPointsTable.json` at commit 91d7bd7e. The
reports record these digests:

| Input | SHA-256 |
| --- | --- |
| `policy.json` | `bc096b75f956c2091c3be73cfe2d9eec0157c87bc30ef6e11e0b283e1007171b` |
| policy behavioral fingerprint | `97e802efc11697e9b992e6414a9b279ff4ebf5f064e1dc9a4dbbf2d567f30871` |
| discard population (pegging ladder) | `a956301cc916cfbf147dd14bff12dc0d3cf29b006a29eda2da7460bb178d12bf` |
| crib table, November | `b7cc6f03d73829158a9cf9a3f261a0d9a3501cc07b5a892b26cfe757868dd126` |
| play table, November | `4ef452e27d34b7420700f0569fd121c26c1d9438c5f71f5d25d1c0feeaa7d90c` |
| crib table, June | `4cd8a9258d32973710361b9c2a764aea3b8c9a1178ab53e1c2aa38a53e030cc1` |
| play table, June | `7420b1804f64a32a73edb2fcc7fe9f53fe427510755c8b2b3723142e503cca5c` |

The pegging ladder was recorded at commit b10875a and the cross table at commit
d01923a, both on Python 3.14.10. Later commits change only input checks and
tests: the cross-table command above with `--pairs 300` gave identical match
statistics and provenance at d01923a and at 06cf7ea, whose code is this page's.
Workers change nothing but the time taken. They are forked, so more than one
needs a platform with the fork start method. On an 8-core Apple M2 laptop the
recorded pegging ladder (300,000 games) took 2 minutes 56 seconds, about a
minute of it loading and verifying the policy, with a peak of about 770 MB. The
recorded cross table (1.5 million games) took 47 minutes, with a peak of 1.1 GB.
