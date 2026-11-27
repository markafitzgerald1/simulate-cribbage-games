# Strength ladder

Issue #263 measures how strong each engine version is by playing it against
the others in full games to 121. A player is a discard rule plus a pegging
policy. This first ladder holds discards fixed and steps pegging only:

| Rung | Pegging policy |
| --- | --- |
| `random` | a uniformly chosen playable card |
| `heuristic` | the legacy simulator's default play (`LegacyHeuristicPolicy`) |
| `cfr` | the pinned CFR+ six-layer policy (`SixLayerPolicy`) |

Every rung keeps the ranks named by the rank-only discard population that is
bound into the CFR policy manifest (`discard_population`). Among cards of a
kept rank it keeps the lowest suit index, so the rule ignores flushes and
nobs. Because the discards are shared, a rung's edge over the one below it is
pegging alone.

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
  --pairs 50000 --workers 8 --cross-table --seed 42 \
  --output ladder-50000.json
```

`<bundle>` is the CFR policy bundle that `bundle-cfr-inputs.yml` produced
from CFR run 45528665715, the same inputs `examples/fixed-play-inputs.json`
pins. The run below records these digests:

| Input | SHA-256 |
| --- | --- |
| `policy.json` | `bc096b75f956c2091c3be73cfe2d9eec0157c87bc30ef6e11e0b283e1007171b` |
| policy behavioral fingerprint | `97e802efc11697e9b992e6414a9b279ff4ebf5f064e1dc9a4dbbf2d567f30871` |
| discard population | `a956301cc916cfbf147dd14bff12dc0d3cf29b006a29eda2da7460bb178d12bf` |

Workers change nothing but the time taken. On an 8-core Apple M2 laptop,
the three matches (300,000 games) took 3 minutes 34 seconds of wall time,
about a minute of which was loading and verifying the policy. Peak memory
was about 770 MB.

## Recorded run: 50,000 deal pairs per match, seed 42

Run on commit c0b00bc of the #263 branch with Python 3.14.10. All figures
are for the first-named player. Each +/- is one standard error over 50,000
pairs.

| Match | Win % | Elo | As first Pone | As first Dealer | Pegging margin | Won both / split / lost both |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| heuristic vs random | 67.52 +/- 0.11 | 127.1 +/- 0.9 | 62.01 +/- 0.22 | 73.02 +/- 0.20 | 9.12 +/- 0.02 | 17,790 / 31,935 / 275 |
| cfr vs heuristic | 56.32 +/- 0.09 | 44.1 +/- 0.7 | 50.49 +/- 0.22 | 62.15 +/- 0.22 | 3.20 +/- 0.02 | 7,823 / 40,672 / 1,505 |
| cfr vs random | 68.63 +/- 0.11 | 136.0 +/- 0.9 | 63.29 +/- 0.22 | 73.97 +/- 0.20 | 9.77 +/- 0.02 | 18,814 / 31,000 / 186 |

The pegging margin is the mean, per game, of the first-named player's pegging
points minus the opponent's (his heels excluded). A game averages 9.1 to 9.2
hands. For cfr vs heuristic, pairing gives an SE of 0.09 points, against 0.16
if the games were independent.

What these numbers do and do not show:

- **CFR+ pegging beats the heuristic**, by 6.3 +/- 0.1 points of win rate,
  with the same discards.
- **Elo does not add along the ladder.** Chaining the two adjacent gaps gives
  127.1 + 44.1 = 171.2 Elo for CFR+ over random, but the direct match gives
  136.0. Because the cells share deals, their SEs cannot be combined in
  quadrature. Even the worst-case bound, the sum of the three SEs at about
  2.4 Elo, is far smaller than the 35-Elo gap. CFR+'s extra edge shows mostly
  against a competent opponent, not against random play.
- **Who deals first matters**, by 10 to 12 points of win rate in every match.
  Seat swapping cancels it within each pair.
- **The CFR rung is the stored policy throughout.** It made 3.60 million
  calls against the heuristic and 3.66 million against random. None fell
  back to the heuristic for a missing menu. 0.9% (against the heuristic) and
  4.3% (against random) were off-support. Off-support means a state outside
  the support its training certified, where it still samples its stored row.
  Its certificate does not cover those states, and they are more common
  against an opponent unlike the one it was trained against.
- **These are rank-only discards**, the CFR prior's frozen population, not
  the app's suit-aware tables. App-table rungs (`E(h +/- c)`,
  `E(h +/- c + deltaP)`) come next. Legacy discard and pegging rungs wait on
  #37's coverage of the legacy simulator, and on #265.
