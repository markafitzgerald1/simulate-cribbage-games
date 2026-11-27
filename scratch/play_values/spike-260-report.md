# Spike #260: per-play values for the first two pegging plays

Claude Code (Opus 5.5, medium effort), 2026-11-27, about 1.5 hours of agent
time.

## Read this first (about 15 minutes of yours: 10 to read, 5 to decide)

- **Yes, and it is cheap.** One exact pass over every deal's game tree gives
  the expected pegging margin of every legal card at every first and second
  play of both seats: 1.91 million decisions, 3 minutes on this laptop
  (2.5 GB peak). It is exact integer arithmetic within the solved model, and
  a separate Monte Carlo check agrees (chi-square 176.7 on 185 cards).
- **Size:** 2.3 MB gzip for one byte per card (loss against the best card, in
  hundredths of a point) on the 1.45 million decisions the bot can lead you
  into. Inside #910's per-hand policy shards that needs no new index (+7% on
  their 33 MB). A standalone file with its own index is about 4.6 MB.
- **Ties are common and should read as ties.** Weighted by how often each
  decision comes up, the runner-up is within 0.01 point of the best card at
  63% of Pone leads, about 30% of Dealer first plays and Pone second plays,
  and 15% of Dealer second plays. Show any card within 0.01 point of the
  best as "as good as the best".
- **Recommendation: build the data set, as an extra column in #910's shard
  export, for #910's review slice.** It does not block slice 1. Frequencies
  alone cannot say what a deviation costs: the worst card at a Dealer first
  play costs 1.62 points on average, and a card the policy plays 0.1% of the
  time can be a rounding remnant rather than a near-tie.
- **Main caveat:** like the frequencies, the values ignore your own discards
  and the starter (the solved model's prior does not condition on them), and
  they are pegging-margin points, not win rate.
- **Where things are:** this report and the code are committed locally on
  branch `claude/spike-260` in the sim worktree `mystifying-nash-c67a13`,
  under `scratch/play_values/`. A session hook refused writes to
  `.claude/worktrees/spike-260-report.md` and to a separate `spike-260`
  worktree, so both moved here. Nothing pushed, published or posted.

## Question

Can the first two pegging plays of each seat get a per-card value (expected
points for each legal card), derived from the solved policy, small enough
for a browser lookup?

## Method

### What the value is

At a decision `I` of seat `s`, the value of card `a` is the expected final
pegging margin (seat `s`'s pegging points minus the opponent's, over the rest
of the hand's play) if `s` plays `a` now and both seats follow the pinned
policy afterwards. The expectation is over the deals consistent with `I`,
weighted by the prior times the opponent's policy probabilities on the way to
`I`. Seat `s`'s own earlier choices are fixed by the history, so they cancel.
This is the counterfactual value CFR itself uses, divided by the
counterfactual reach.

"First two plays" means stages 0 to 3 of the menus: Pone's first card,
Dealer's first card, Pone's second card, Dealer's second card. This matches
the bot-match result in the issue (the bot's own first two cards).

### Inputs and where each comes from

| Input | Source | Check |
|---|---|---|
| Pegging rules | `native/cfr/src/game.rs`, checked against the Python engine through `pegging_golden.txt` | reused unchanged |
| Menus | bundle run 45528665715 | folder digest equals `digests.json` `reproducible` |
| Trees | rebuilt in memory with `Tree::build` | folder digest equals `digests.json` `reproducible` |
| Offsets | derived from the menus | digest equals the bundle manifest |
| Policy (rounded, 1,000 units per menu) | bundle `policy.bin` | SHA-256 equals the bundle manifest |
| Prior over (Pone hand, Dealer hand), including the pinned discard population | bundle `prior.bin` | SHA-256 equals the bundle manifest |

Nothing else enters the numbers. No card, weight or opponent choice is
invented: every value is enumeration over pinned, digest-checked inputs that
published code produced.

### Exact pass

`scratch/play_values` is a small Rust package that depends on `native/cfr` and uses
its menus, trees and rules; it adds only a valuation walk. Per deal, it walks
the tree once carrying two integer weights (the prior times every policy
probability on the path except one seat's own, which count as 1,000) and
returns the subtree's joint value scaled the way `solve::joint_value` scales
it. At each stage 0 to 3 node it adds `weight × child value` per card and
`weight × 1000^(6 − depth)` as reach. Everything is `i128`, so the sums are
exact; the only floating-point step is the final division, so each value is
exact to double precision. The magnitudes stay inside the bound
`MASS_LIMIT` was chosen for.

Run on the bundle (Apple M2, 6 threads, machine shared with other jobs):
190 s wall, 426 s CPU, 2.5 GB peak memory.

### Monte Carlo check

The `mc` mode never reads a tree or the exact accumulators. It samples the
opponent's hand from the prior row, plays forward with `game::State`, looks
each decision up in the menus by its history, samples the opponent's cards
from the policy, follows the target's history for the seat's own earlier
cards, and rejects deals that leave the target's history. At the target it
plays each legal card and then plays out with the policy for both seats.

Targets: 60 decisions, 15 per stage, sampled by how often play reaches them
(prior × both seats' policy reach), 185 cards in all, 40,000 accepted deals
each (every target reached 40,000). Standard errors 0.005 to 0.020 points.

| Stage | Cards | Chi-square | Largest abs(z) |
|---|---|---|---|
| Pone card 1 | 52 | 59.6 | 2.30 |
| Dealer card 1 | 54 | 53.6 | 2.87 |
| Pone card 2 | 41 | 26.2 | 1.67 |
| Dealer card 2 | 38 | 37.3 | 2.38 |
| All | 185 | 176.7 | 2.87 |

8 of 185 cards lie beyond 2 standard errors (about 8.5 expected) and none
beyond 3. Cards within one decision share the reached deals, so they are not
fully independent, but nothing points to a bias: the mean z is −0.06.

A second check needs no sampling. The policy's own expected value at each
decision sits on average 0.00012 (Pone card 1), 0.00020 (Dealer card 1),
0.00016 (Pone card 2) and 0.00028 (Dealer card 2) points below its best
card, which fits the policy's certified exposure of at most 0.001 points.
And the reach of each stage sums to the share of deals with a real choice
there (0.9997 for Pone's lead, the rest being four-of-a-kind hands).

## Results

Per stage, weighted by how often each decision comes up under the prior and
both seats' policy:

| Stage | Opponent can reach | Policy also reaches | Most frequent card is best | Worst card's loss | Runner-up within 0.01 pt | Within 0.05 pt |
|---|---|---|---|---|---|---|
| Pone card 1 | 1,807 | 1,807 | 91% | 0.66 | 63% | 66% |
| Dealer card 1 | 23,491 | 23,491 | 94% | 1.62 | 30% | 34% |
| Pone card 2 | 74,698 | 44,304 | 94% | 1.24 | 31% | 35% |
| Dealer card 2 | 1,350,486 | 626,075 | 97% | 1.43 | 15% | 20% |

"Opponent can reach" totals 1.45 million decisions, which matches the
issue's 1.4 million second-play rows. Only 0.67 million are reached when you
also follow the policy; a person who deviates at the first card reaches the
rest, and every one of them has a well-defined value. Values run up to 16
points from the acting seat's side, and the largest loss for one card is
20.6 points (a Dealer second card).

Examples (value is your expected pegging margin; percentages are the
policy's):

| Decision | Cards: policy, value |
|---|---|
| Pone leads from A-2-5-7 | A 19.5%, −1.144; 2 80.4%, −1.143; 7 0.1%, −1.192; 5 0%, −1.995 |
| Pone leads from 4-4-5-6 | 4 100%, −0.965; 6 0%, −2.044; 5 0%, −2.327 |
| Dealer from 3-6-7-T after a 3 | 3 100%, +2.200; T 0%, +0.219; 7 0%, −0.172; 6 0%, −0.332 |
| Dealer from 5-9-Q-K after a 4 | 9 77.6%, +0.049; Q 15.6%, +0.048; K 6.8%, +0.048; 5 0%, −1.078 |
| Pone second card from 9-T-J-Q after Q, 5 | 9 29.3%, −3.752; J 70.6%, −3.752; T 0.1%, −3.786 |

The last two rows show why frequencies alone mislead. In 5-9-Q-K the 9 at
77.6% is no better than the K at 6.8%: they are tied. In 9-T-J-Q the T at
0.1% is a remnant of rounding the policy to 1,000 units and really costs
0.034 points. Across mixed decisions, the spread between cards the policy
plays at all reaches 0.59 points at Pone's lead and 7 points at Dealer's
first card, always on cards it plays a few times in a thousand. Values
separate "mixes equally" from "almost never plays, for a reason".

## Uncertainty

- **Arithmetic:** exact, then one double division (relative error about
  10^−16). The Monte Carlo agreement is evidence that the walk computes what
  this report says it does.
- **Model:** these are values inside the solved game and inherit its limits,
  which the policy frequencies share:
  - rank-only hands;
  - a prior over the two kept hands that does not condition on a player's own
    discards or the starter, so the value of a lead does not change with the
    cards you threw or the cut;
  - a pinned discard population that the bundle itself marks as not converged
    and not jointly refined with the pegging policy;
  - the policy's 0.001-point exposure, which bounds the gain from deviating
    only in aggregate, not per decision.
- **Objective:** pegging margin, not win rate and not hand or crib points.

## Cost and size of the full run

- **Compute:** the run above is the full run for stages 0 to 3: about 3
  minutes and 2.5 GB here, so a 4-vCPU hosted runner should take roughly 5
  to 10 minutes. It needs the menus, policy and prior, which the shard export
  job already has, and rebuilds the trees in memory, so no 8 GB tree files.
- **Data**, for the 1.45 million decisions the opponent can reach (3.69
  million cards):

  | Encoding | Raw | gzip, one file per seat and hand | gzip, one file |
  |---|---|---|---|
  | Loss vs best, 1 byte per card, 0.01 pt, capped at 2.55 | 3.69 MB | 2.28 MB | 2.07 MB |
  | Value, 2 bytes per card, 0.01 pt | 7.38 MB | 4.67 MB | 4.28 MB |
  | History index, u64 per decision | 11.6 MB | 2.34 MB | |

  In #910's shards the rows are already indexed by history, so one loss byte
  per card adds about 2.3 MB to their 33 MB, roughly 1 KB to a typical
  hand's pair of shards. A standalone file needs the index as well: about
  4.6 MB. 283,338 cards (8%) lose more than 2.54 points and would read "2.55
  or more" under the one-byte encoding, which is probably enough for a review
  screen; the two-byte encoding keeps them exact.

## How near-ties should read

- At a display precision of 0.01 point, gaps under 0.005 already print as
  equal. They are the equilibrium's mixed cards plus rounding noise.
- Suggested wording: within 0.01 point of the best, "as good as the best";
  otherwise "costs N.NN points of pegging, on average". Do not rank tied
  cards by frequency.
- Because the exposure bound is an aggregate, a per-decision gap of a few
  hundredths is a real difference in this model, but small next to the
  model's own limits above. Calling 0.01 to 0.05 "slightly worse" is honest;
  calling it a mistake is not.

## Recommendation

Of the issue's three options, **build the data set**, with two conditions:

1. Ship it as a column of #910's shard export, produced by the same
   published workflow from the same pins, rather than as a separate release
   with its own index. That keeps the table-provenance rule: the values are
   regenerated from published code off the laptop, alongside the frequencies
   they describe.
2. Do it for #910's review slice, after slice 1's shards merge. Slice 1 does
   not need values, and nothing here changes the policy or the released
   table.

"Frequencies only" would leave the review unable to say what a deviation
costs, and would present ties as preferences. "Go to #910" without values is
fine for slice 1 but not for the review screen this spike was for.

Open questions for later, not blockers:

- Conditioning on the player's own discards and the starter would make a
  value specific to the dealt hand, but needs a prior per twelve-card deal
  and a policy solved against it; the frequencies have the same gap.
- Turning pegging margin into win rate needs a game-score model; the
  bot-match numbers in the issue are the only measurement so far.

## Code

`scratch/play_values/` on branch `claude/spike-260`, committed locally with
`--no-gpg-sign`, not pushed:

- `src/main.rs`: `exact` (the valuation walk, with digest checks on every
  input and on the rebuilt trees) and `mc` (the independent Monte Carlo
  check).
- `analyze.py`: summaries, Monte Carlo targets and examples; standard
  library only.

It is spike code, with no tests and outside the `native/cfr` gates. If the
data set is built, the valuation walk belongs in `native/cfr` or the shard
exporter, with tests: an exhaustive small-game oracle like the ones
`solve.rs` already has, and a mutation check on the weight bookkeeping.

To reproduce, from `scratch/play_values`:

```sh
cargo build --release
target/release/play-values exact BUNDLE values.bin
python3 analyze.py BUNDLE values.bin OUT 15
target/release/play-values mc BUNDLE OUT/targets.txt 40000 260 mc.csv
```

Outputs from this run are in the session scratchpad, which may be cleared:
`values.bin`, `summary.json`, `examples.json`, `targets.txt`, `mc.csv` and
the logs.

## Draft issue comment (not posted)

Claude Code (Opus 5.5, medium effort), on Mark's behalf: spike result. Yes: per-card values for each seat's first two plays can be computed exactly from the pinned policy and prior (bundle run 45528665715), and they are small. One exact pass over every deal's tree (integer arithmetic, reusing `native/cfr`'s menus, trees and rules, with every input digest-checked against its pin, including the rebuilt trees) valued all 1.91 million stage 0 to 3 decisions in about 3 minutes on a laptop. An independent Monte Carlo check (forward play with `State` and menu lookup, no trees) on 60 decisions sampled by how often they come up agreed: chi-square 176.7 on 185 cards, none beyond 3 standard errors. The value is the expected pegging margin of each card when both seats follow the policy afterwards. Size: one byte per card (loss against the best, in hundredths of a point) over the 1.45 million decisions the bot can lead a player into is 2.3 MB gzip; inside #910's per-hand shards that needs no new index (about 4.6 MB standalone with one). Near-ties are common: weighted by how often they come up, the runner-up is within 0.01 point of the best at 63% of Pone leads and 15% to 31% of the other first and second plays, so such cards should read as equal, and frequencies alone mislead (a card at 77.6% can be tied with one at 6.8%, and a card at 0.1% can be a rounding remnant that costs 0.03 points). Recommendation: build the data set as a column of #910's shard export, for its review slice, after slice 1. Caveat: like the frequencies, the values ignore the player's discards and the starter, and they are pegging points, not win rate. Full report and code are on a local branch; nothing was published.
