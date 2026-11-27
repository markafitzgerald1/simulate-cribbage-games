# Spike #260: per-play values for the first two pegging plays

Claude Code (Opus 5.5, medium effort), 2026-11-27, about 3 hours of agent
time in all. Reviewed by Codex (GPT-6.2 Sol, extra-high effort); see
"Reviews".

## Read this first (about 15 minutes of yours: 10 to read, 5 to decide)

- **Yes, and it is cheap.** One exact pass over every deal's game tree gives,
  for every legal card at each seat's first and second play, the expected
  final pegging margin when both seats follow the policy afterwards: 1.91
  million decisions, 3 minutes on this laptop (2.5 GB peak). It is exact
  integer arithmetic within the solved model. Codex found no defect in the
  valuation, and a separate Monte Carlo check agrees on 72 decisions,
  including 12 that only an off-policy earlier card reaches.
- **Size:** one byte per card (loss against the best card, in hundredths of a
  point) for the 1.45 million decisions the bot can lead a player into
  compresses to about 2.3 MB as a column on its own. In #910's per-hand
  shards the rows are already indexed; the integrated size still has to be
  measured.
- **New, and it changes how values should read:** the values, like the
  policy's frequencies, ignore your own discards and the starter. Measured on
  300 dealt hands per seat, conditioning on those cards changes the best card
  at 37% of Pone leads and 9% to 19% of the other first and second plays. On
  average following the table there costs 0.006 to 0.022 points; the worst
  case is 0.30. A card the table says costs 0.25 points or more is still not
  the best 0.1% of the time. Below 0.1 point the table's ranking is
  unreliable.
- **Recommendation: build the data set, as a column of #910's shard export,
  for #910's review slice, and show losses in bands rather than exact
  hundredths:** under 0.1 point "close call", 0.1 to 0.25 "probably worse",
  0.25 and over "costs about N points". It does not block slice 1.
- **Where things are:** branch `claude/spike-260` (pushed, no PR), under
  `scratch/play_values/`. A session hook refused writes outside this
  session's worktree, so the report lives here rather than at
  `.claude/worktrees/spike-260-report.md`. The issue comment at the end is
  posted on #260.

## Question

Can the first two pegging plays of each seat get a per-card value (expected
points for each legal card), derived from the solved policy, small enough
for a browser lookup?

## Method

### What the value is

At a decision `I` of seat `s`, the value of card `a` is the expected **final**
pegging margin of the hand (seat `s`'s pegging points minus the opponent's,
including any already scored before `I`) if `s` plays `a` now and both seats
follow the pinned policy afterwards. Points already scored are the same for
every card at `I`, so a card's loss against the best card is unaffected; a
display of remaining margin would subtract them.

The expectation is over deals consistent with `I`, weighted by the prior
times the opponent's policy probabilities on the way to `I`. Seat `s`'s own
earlier choices are fixed by the history, so they cancel. This is the
counterfactual value CFR itself uses, divided by the counterfactual reach.

Two kinds of decision need care:

- **The opponent never reaches it** (459,685 of the 1,910,167 tracked
  decisions): no value exists; the data marks it unavailable, never zero.
- **Only your own earlier off-policy card reaches it** (754,805 decisions):
  the value is well defined and is conditional on the recorded history,
  which is exactly what a player who deviated faces.

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
| Discard population (conditioning only) | bundle `population.json` | Codex matched it to its pin |
| Dealt hands and starters (conditioning only) | seeded shuffles, 300 deals | a sample of situations, not an input to any shipped value |

No card, weight or opponent choice is invented: every value is enumeration
over pinned, digest-checked inputs that published code produced. Codex also
found the positive-reach rows match the pinned support bits exactly.

### Exact pass

`scratch/play_values` is a small Rust package that depends on `native/cfr`
and uses its menus, trees and rules; it adds only a valuation walk. Per deal,
it walks the tree once carrying two integer weights (the prior times every
policy probability on the path except one seat's own, which count as 1,000)
and returns the subtree's joint value scaled the way `solve::joint_value`
scales it. At each stage 0 to 3 node it adds `weight × child value` per card
and `weight × 1000^(6 − depth)` as reach. Everything is `i128`, so the sums
are exact; the only floating-point step is the final division. The
magnitudes stay inside the bound `MASS_LIMIT` was chosen for (Codex checked
the bound and ran the walker on a hand-computed tree).

Run on the bundle (Apple M2, 6 threads, machine shared with other jobs):
190 s wall, 426 s CPU, 2.5 GB peak memory.

### Monte Carlo check

The `mc` mode never reads a tree or the exact accumulators. It samples the
opponent's hand from the prior row, plays forward with `game::State`, looks
each decision up in the menus by its history, samples the opponent's cards
from the policy, follows the target's history for the seat's own earlier
cards, and rejects deals that leave the target's history. At the target it
plays each legal card and then plays out with the policy for both seats.

Two sets of targets, every one reaching its full sample count:

- 60 decisions, 15 per stage, sampled by how often play reaches them; 185
  cards, 40,000 accepted deals each.
- 12 second-play decisions that only an earlier off-policy card reaches,
  sampled by opponent reach; 30 cards, 20,000 deals each.

| Check | Result |
|---|---|
| Card means against exact values, 215 cards | sum of squared z 185.6, mean z −0.05, 8 beyond 2, none beyond 3 |
| Off-policy targets alone, 30 cards | none beyond 2 |
| Acceptance rate against exact reach, 72 targets | largest abs(z) 2.50 |

The sum of squared z-scores is descriptive, not a chi-square test: cards of
one decision share their sampled deals. The acceptance check matters because
an error that scales every reach alike leaves the means unchanged; Codex
showed a doubled reach fails it by 143 standard errors.

A second check needs no sampling. The policy's own expected value at each
decision sits on average 0.00012 (Pone card 1), 0.00020 (Dealer card 1),
0.00016 (Pone card 2) and 0.00028 (Dealer card 2) points below its best
card, which fits the policy's certified exposure of at most 0.001 points.

## Results

Per stage, weighted by how often each decision comes up under the prior and
both seats' policy:

| Stage | Opponent can reach | Policy also reaches | Most frequent card is best | Worst card's loss | Runner-up shows 0.00 loss |
|---|---|---|---|---|---|
| Pone card 1 | 1,807 | 1,807 | 91% | 0.66 | 62% |
| Dealer card 1 | 23,491 | 23,491 | 94% | 1.62 | 28% |
| Pone card 2 | 74,698 | 44,304 | 94% | 1.24 | 29% |
| Dealer card 2 | 1,350,486 | 626,075 | 97% | 1.43 | 13% |

"Shows 0.00 loss" means the runner-up's loss rounds to zero at 0.01-point
precision (a gap under 0.005), the rule the one-byte encoding can express.

The opponent can reach 1.45 million decisions in all, which matches the
issue's 1.4 million second-play rows; 695,677 are also reached when you
follow the policy (670,379 of them second plays). Values run up to 16 points
from the acting seat's side, and the largest loss for one card is 20.6
points (a Dealer second card).

Examples (value is your expected final pegging margin; percentages are the
policy's):

| Decision | Cards: policy, value |
|---|---|
| Pone leads from A-2-5-7 | A 19.5%, −1.144; 2 80.4%, −1.143; 7 0.1%, −1.192; 5 0%, −1.995 |
| Pone leads from 4-4-5-6 | 4 100%, −0.965; 6 0%, −2.044; 5 0%, −2.327 |
| Dealer from 3-6-7-T after a 3 | 3 100%, +2.200; T 0%, +0.219; 7 0%, −0.172; 6 0%, −0.332 |
| Dealer from 5-9-Q-K after a 4 | 9 77.6%, +0.049; Q 15.6%, +0.048; K 6.8%, +0.048; 5 0%, −1.078 |
| Pone second card from 9-T-J-Q after Q, 5 | 9 29.3%, −3.752; J 70.6%, −3.752; T 0.1%, −3.786 |
| Dealer from 4-5-9-9 after a 5 (rare) | 5 45.1%, 7.04 points worse than the 9 |

Frequencies alone mislead in both directions. In 5-9-Q-K the 9 at 77.6% beats
the K at 6.8% by only 0.0008 points: a near-tie. In 9-T-J-Q the T at 0.1%
costs 0.034 points; whether that frequency is a remnant of rounding the
policy to 1,000 units cannot be told from the rounded policy, so it stays
open. And in 4-5-9-9 after a 5 the policy plays a card costing 7 points
almost half the time: the decision is so rare that the policy's 0.001-point
exposure, an aggregate bound, does not constrain it. Values show all three
cases for what they are.

## Conditioning on your own discards and the starter

### Method

The solved model's prior describes the two kept hands without the player's
discards or the starter. To measure what that costs, `conditioning.py` deals
300 physical hands (seeded), takes each seat's kept hand from the pinned
discard population, and builds the opponent's distribution twice:

- **Baseline:** the prior row of the player's kept hand, exactly what the
  spike's values use. Rerunning the baseline through the same code path
  reproduces the spike's values exactly (largest difference 0.0).
- **Conditioned:** the prior's own construction (`cfr_prior.py`) with the
  opponent's cards drawn only from the 45 cards the player cannot see. Both
  components (uniform four-card hands, and six-card hands mapped through the
  population's keeps) keep the weight they have in the prior row, so card
  removal is the only change. Weights are rounded to integers with a total
  of 2^50.

The `rows` mode then values every first and second play of each scenario's
hand both ways (1,200 scenarios, 67 s), and the comparison weights each
decision by how often it comes up for that hand under the conditioned
distribution and the policy.

### Results (300 hands per seat; ± is one standard error over hands)

| Stage | Best card changes (by 0.005 pt or more) | Cost of following the table | 95th percentile per hand | Worst hand | A "0.00 loss" card is 0.05 pt or more worse |
|---|---|---|---|---|---|
| Pone card 1 | 37% | 0.022 ± 0.003 | 0.111 | 0.302 | 32% |
| Dealer card 1 | 17% | 0.014 ± 0.001 | 0.049 | 0.080 | 15% |
| Pone card 2 | 19% | 0.014 ± 0.001 | 0.041 | 0.082 | 18% |
| Dealer card 2 | 9% | 0.006 ± 0.0003 | 0.016 | 0.032 | 6% |

How a card's loss in the table holds up once your cards are counted (all
stages, by occurrence):

| Loss in the table | Share that conditioning reverses |
|---|---|
| under 0.005 ("0.00") | 14% are 0.05 or more worse |
| 0.005 to 0.05 | 32% are actually the best card |
| 0.05 to 0.1 | 15% are actually the best card |
| 0.1 to 0.25 | 3.6% are actually the best card |
| 0.25 and over | 0.1% are actually the best card |

A card's loss moves by a median 0.01 to 0.03 points and a 90th percentile
0.11 to 0.15 points.

### What it means

The table is good advice in aggregate: following it costs a few hundredths of
a point per decision against the hand-specific best. But its small gaps are
not facts about your hand. Losses under 0.1 point, and every displayed tie,
depend on cards the table does not see. Losses of 0.25 and over almost never
do.

Hand-specific values would need a value per own six cards and starter rather
than per kept hand. For the Dealer seat that touches every Pone tree, so it is
a different design (on-demand computation or a much larger table) and out of
scope here. The policy itself was solved against the unconditioned prior, so
its frequencies carry the same limitation.

## Uncertainty

- **Arithmetic:** exact, then one double division. The Monte Carlo and reach
  checks are evidence the walk computes what this report says.
- **Model:** values inside the solved game inherit its limits, which the
  policy frequencies share:
  - rank-only hands;
  - a prior that does not see your discards or the starter (measured above);
  - a pinned discard population that the bundle marks as not converged and
    not jointly refined with the pegging policy;
  - the policy's 0.001-point exposure bounds the gain from deviating only in
    aggregate, so a rare decision can carry a large loss on a card the policy
    plays often (the 4-5-9-9 example).
- **Objective:** pegging margin, not win rate and not hand or crib points.
- **Conditioning sample:** 300 hands per seat; the standard errors above are
  over hands, and the kept hands come from the population, not from a
  player's own choices.

## Cost and size of the full run

- **Compute:** the run above is the full run for stages 0 to 3: about 3
  minutes and 2.5 GB here, so a 4-vCPU hosted runner should take roughly 5
  to 10 minutes. It needs the menus, policy and prior, which the shard export
  job already has, and rebuilds the trees in memory, so no 8 GB tree files.
- **Data**, for the 1.45 million decisions the opponent can reach (3.69
  million cards), as a column on its own:

  | Encoding | Raw | gzip, one file per seat and hand | gzip, one file |
  |---|---|---|---|
  | Loss vs best, 1 byte per card, 0.01 pt, byte 255 for 2.55 or more | 3.69 MB | 2.28 MB | 2.07 MB |
  | Value, 2 bytes per card, 0.01 pt, uncapped | 7.38 MB | 4.67 MB | 4.28 MB |
  | History index, u64 per decision | 11.6 MB | 2.34 MB | |

  These are estimates for a column compressed alone. Codex appended the
  column to a real shard and found the gzip cost differs (for Dealer
  9-J-Q-K: 3,999 bytes alone, 4,238 bytes added), so measure the integrated
  export before quoting its increase. 283,338 cards encode as byte 255 and
  284,380 lose more than 2.54 points; with the banded display below, one
  byte is more than enough.

## How values should read

Given the conditioning result, show bands rather than exact hundredths:

| Loss in the table | Wording |
|---|---|
| under 0.1 | "close call: depends on your discards and the cut" |
| 0.1 to 0.25 | "probably worse, by about 0.1 to 0.25 points" |
| 0.25 and over | "costs about N.N points of pegging" |

Do not rank cards within the close-call band by value or by frequency, and
call the unit "points of pegging", never win rate.

## Recommendation

Of the issue's three options, **build the data set**, with three
conditions:

1. Ship it as a column of #910's shard export, produced by the same
   published workflow from the same pins, rather than as a separate release
   with its own index. That keeps the table-provenance rule: values are
   regenerated from published code off the laptop, beside the frequencies
   they describe.
2. Do it for #910's review slice, after slice 1's shards merge. Slice 1 does
   not need values, and nothing here changes the policy or the released
   table.
3. Display the bands above, so the review never claims a precision the model
   does not have for your hand.

"Frequencies only" would leave the review unable to say what a deviation
costs, and would present ties and rare large losses as preferences. "Go to
#910" without values is fine for slice 1 but not for the review screen this
spike was for.

Later, not blockers: hand-specific values (above), and turning pegging margin
into win rate, which needs a game-score model.

## Reviews

| Reviewer | Head reviewed | Outcome |
|---|---|---|
| Claude Opus 5.5 (author) | 3c49171 | self-review; spike as first reported |
| Codex GPT-6.2 Sol, extra-high | 3c49171 | no valuation defect; 2 must-fix and 3 should-fix in the report's definitions, tie rule, Monte Carlo coverage, examples and size wording, 2 nits; all addressed in the next commit |
| Codex GPT-6.2 Sol, extra-high | next commit | see the commit after it |

## Code

`scratch/play_values/` on branch `claude/spike-260`:

- `src/main.rs`: `exact` (the valuation walk, with digest checks on every
  input and on the rebuilt trees), `rows` (the same walk for given opponent
  weights) and `mc` (the independent Monte Carlo check).
- `analyze.py`: summaries, Monte Carlo targets and examples.
- `check_mc.py`: card means and acceptance rates against the exact output.
- `conditioning.py`: builds the baseline and conditioned scenarios and
  compares their values.

Spike code: no tests, outside the `native/cfr` gates. If the data set is
built, the walk belongs in `native/cfr` or the shard exporter, with an
exhaustive small-game oracle like those `solve.rs` has and mutation checks
on the weight bookkeeping.

To reproduce, from `scratch/play_values` (Python scripts use the standard
library only):

```sh
cargo build --release
target/release/play-values exact BUNDLE values.bin
python3 analyze.py BUNDLE values.bin OUT 15
target/release/play-values mc BUNDLE OUT/targets.txt 40000 260 mc.csv
python3 check_mc.py BUNDLE values.bin mc.csv
python3 conditioning.py build BUNDLE 300 2601 scenarios.bin
target/release/play-values rows BUNDLE scenarios.bin rows.bin
python3 conditioning.py compare rows.bin values.bin conditioning.json
```

## Issue comment (posted on #260)

Claude Code (Opus 5.5, medium effort), on Mark's behalf: spike result. Report and code: branch `claude/spike-260`, `scratch/play_values/spike-260-report.md` (no PR). **Yes, per-card values are cheap and exact.** One integer pass over every deal's tree, reusing `native/cfr`'s menus, trees and rules with every input digest-checked against its pin, gives the expected final pegging margin of every legal card at each seat's first and second play (1.91 million decisions) in about 3 minutes on a laptop. Codex (GPT-6.2 Sol, extra-high) found no defect in the valuation, and an independent Monte Carlo check agreed on 72 decisions, including off-policy ones, for both values and reach. **Size:** one byte per card (loss against the best, 0.01 point) over the 1.45 million decisions the bot can lead a player into is about 2.3 MB gzip as a column; in #910's per-hand shards the rows are already indexed, and the integrated size still needs measuring. **Main finding:** like the policy's frequencies, the values ignore the player's own discards and the starter. On 300 dealt hands per seat, conditioning on them changes the best card at 37% of Pone leads and 9% to 19% of other first and second plays, at an average cost of 0.006 to 0.022 points (worst 0.30). A card the table says costs 0.25 points or more is almost never best (0.1%); below 0.1 point the table's ranking is unreliable. **Recommendation:** build the data set as a column of #910's shard export, for its review slice after slice 1, and display losses in bands ("close call" under 0.1, "probably worse" 0.1 to 0.25, "costs about N points" from 0.25) rather than as exact hundredths.
