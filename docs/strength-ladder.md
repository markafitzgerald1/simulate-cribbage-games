# Strength ladder

Issue #263 measures how strong each engine version is by playing it against
the others in full games to 121. A player is a discard rule plus a pegging
policy. This first ladder holds discards fixed and steps pegging only:

| Rung | Pegging policy |
| --- | --- |
| `random` | a uniformly chosen playable card |
| `heuristic` | the legacy simulator's default play (`LegacyHeuristicPolicy`) |
| `cfr` | the CFR+ six-layer policy (`SixLayerPolicy`) from the given bundle |

Every rung keeps the ranks named by the rank-only discard population bound
into the bundle's manifest (`discard_population`). When a kept rank has
several dealt cards to choose from, the seat's discard stream picks one, so
no suit is favored. Because the discards are shared, a rung's edge over a
lower rung is pegging alone.

## How a match is measured

A deal pair is two games on one seed with the seats swapped, so both players
hold the same cards in the same seat for as long as both games last
(`artifact_pipeline/ladder_game.py`). The reported win rate is the mean over
pairs of the upper rung's share of the pair's two games. Its standard error
comes from the spread of those per-pair results, because pairs are
independent and the two games of a pair are not
(`artifact_pipeline/ladder_match.py`). The JSON report also gives the SE the
same win rate would have if all 2n games were independent, for comparison
only.

Every match uses the same pair seeds, so cells of the cross table share deals
and are correlated. Each cell's SE is valid for that cell alone. Elo is the
delta-method transform of one cell's win rate and SE. It summarizes that
pairing, not a rating that adds up across opponents.

## Reproducing the recorded run

```bash
python -m artifact_pipeline.strength_ladder \
  --policy-manifest <bundle>/policy.json \
  --policy-manifest-sha256 bc096b75f956c2091c3be73cfe2d9eec0157c87bc30ef6e11e0b283e1007171b \
  --pairs 50000 --workers 8 --cross-table --seed 42 \
  --output ladder-50000.json
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

Workers change nothing but the time taken. They are forked, so more than one
needs a platform with the fork start method. On an 8-core Apple M2 laptop,
the three matches (300,000 games) took 3 minutes 11 seconds of wall time,
about a minute of which was loading and verifying the policy. Peak memory
was about 770 MB.

## Recorded run: 50,000 deal pairs per match, seed 42

Run on commit fcbc0cc of the #263 branch with Python 3.14.10. All figures
are for the first-named player, in percent or points. Each +/- is one
standard error over 50,000 pairs.

| Match | Win % | Elo | Win % as first Pone | Win % as first Dealer | Pegging margin | Won both / split / lost both |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| heuristic vs random | 67.53 +/- 0.11 | 127.2 +/- 0.9 | 62.00 +/- 0.22 | 73.05 +/- 0.20 | 9.12 +/- 0.02 | 17,798 / 31,930 / 272 |
| cfr vs heuristic | 56.32 +/- 0.09 | 44.1 +/- 0.7 | 50.47 +/- 0.22 | 62.16 +/- 0.22 | 3.20 +/- 0.02 | 7,820 / 40,676 / 1,504 |
| cfr vs random | 68.61 +/- 0.11 | 135.9 +/- 0.9 | 63.27 +/- 0.22 | 73.96 +/- 0.20 | 9.77 +/- 0.02 | 18,798 / 31,017 / 185 |

The pegging margin is the mean, per game, of the first-named player's pegging
points minus the opponent's (his heels excluded). A game averages 9.1 to 9.2
hands. For cfr vs heuristic, pairing gives an SE of 0.09 percentage points,
against 0.16 if the games were independent.

What these numbers do and do not show:

- **CFR+ pegging beats the heuristic** with the same discards: it wins
  56.32% of games, 6.32 +/- 0.09 percentage points above an even match.
- **Elo does not add along the ladder.** Chaining the two adjacent gaps gives
  127.2 + 44.1 = 171.3 Elo for CFR+ over random, but the direct match gives
  135.9. Because the cells share deals, their SEs cannot be combined in
  quadrature. Even the worst-case bound, the sum of the three SEs at 2.4 Elo,
  is far smaller than the 35-Elo gap. Against random play, CFR+ wins only
  1.1 percentage points more often than the heuristic does (68.61% against
  67.53%). That is far less than its 6.3-point edge when the two meet
  directly.
- **Dealing first is worth about as much as the CFR+ edge.** In every match,
  a player wins 10.7 to 11.7 percentage points more often as first Dealer
  than as first Pone. That is about 5.3 to 5.8 points either side of its
  average, on the same scale as CFR+'s 6.3 points above even. Seat swapping
  weights both starting seats equally.
- **What the CFR rung did.** Against the heuristic it was called 3.60
  million times. 1.23 million calls were forced (a single legal card). Of
  the 2.38 million non-forced calls, none fell back to the heuristic for a
  missing menu, so every one used a stored row. 1.4% of them were
  off-support: a state with zero opponent reach under the saved policy and
  prior, where it still samples its stored row. "Off-support" does not mean
  untrained or uncertified. Against random play the off-support share was
  6.5% of 2.40 million non-forced calls. These shares describe these two
  opponents only.
- **These are rank-only discards**, the CFR prior's frozen population, not
  the app's suit-aware tables. App-table rungs (`E(h +/- c)`,
  `E(h +/- c + deltaP)`) come next. Legacy discard and pegging rungs wait on
  #37's coverage of the legacy simulator, and on #265.
