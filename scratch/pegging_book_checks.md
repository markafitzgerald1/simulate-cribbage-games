# Issue #187: confirmation and pair-rule checks

This checkpoint runs A and B only. Dealer first replies and policy iteration
are deferred. Stage 1 data and its original policy remain frozen.

Choices fixed before new observations:

- Re-estimate the exact chosen lead for all 656 accepted keys on 2,500 fresh
  paired opponent keeps per key, using seed 42 with the separate
  `issue-187-pone-confirmation-v1` stream label. Both continuations are the
  heuristic. Do not choose a different lead using the fresh results.
- Require positive fresh gain at z >= 2. This confirmation screen requires
  more than a noisy positive sign, without demanding the original exploratory
  three-SE bar twice. It is not a family-wide significance guarantee.
- Sample 200 of the 1,151 rejected keys with an alternative lead uniformly
  without replacement, using the independent rejected-control stream label.
  Test their highest-original-mean alternative, with lower-rank tie breaking.
  The 13 four-of-a-kind keys have no alternative and are outside this control
  population. Controls are never installed in the restricted book.
- Evaluate the original and restricted books with the unchanged promotion
  gate on 200,000 deals, seed 43. Also measure their difference directly on
  those same duplicate deals, retaining the paired difference SE.
- Test one rule only: on the initial Pone decision, lead the lowest rank
  whose multiplicity is at least two; otherwise use the heuristic. Triples
  and four-of-a-kind count as repeated ranks. Later sequence resets and
  Dealer decisions always use the fallback. Tie breaking is fixed before
  looking at the pattern counts or gate results.
- Gate that rule against the heuristic and the frozen original book on
  200,000 deals, seed 44, separate from A and stage 1's gate seed 42.

For the null benchmark, count all 4,095 alternative-versus-heuristic training
comparisons, not just 656 selected entries. Under calibrated zero-mean normal
statistics the one-sided z >= 3 tail is about 0.0013499, giving 5.528 expected
threshold crossings if every tested alternative were null. Linearity of
expectation does not require independence between alternatives. This is a
nominal all-null benchmark, not an estimated false discovery count or a bound
on a selected entry's error probability. Non-normal finite-sample statistics,
nonzero effects and selecting the best lead limit that interpretation.

Fresh gain minus original gain is negative when the original estimate shrinks.
Summaries and pattern means weight canonical keys equally and are descriptive;
only gate results estimate strength on uniform physical keeps. Feature groups
overlap. A first lead's pegging count cannot exceed ten, including face cards;
that feature has zero keys and unavailable means, not zero estimated gains.

The book comparator is a scratch-only Pone specialization of the promotion
gate. It uses `gate_deals`, two games on one play seed and the same heuristic
Dealer. Dealer's candidate gain is zero and both-seat gain is half each
per-deal Pone gain. It does not modify the merged gate or subtract separately
estimated means to obtain a standard error.

## Reproduce

Use Python 3.14.4 with the repository requirements. Run from an isolated
temporary directory with this checkout on `PYTHONPATH` and a bootstrapped
tally shelf. Execute these in order:

```sh
python -m scratch.pegging_book_checks selection --samples 2500 --controls 200 --seed 42 --workers 8 --gate-deals 200000 --output selection.json
python -m scratch.pegging_book_checks patterns --confirmation selection.json --gate-deals 200000 --output patterns.json
```

The stage 1 input defaults to the retained file beside the script. The output
records its exact file digest, original and restricted policy fingerprints,
unrounded evidence digest, sample counts, choices, gate results and runtime.
The full selection evidence includes every accepted entry and sampled control.
The original evidence file is never rewritten.

## Results

The retained A report is `issue187_pone_confirmation.json`; B is
`issue187_pair_rule.json`. Pass the A file as `--confirmation` to replay B.
Numerical evidence is deterministic given the seed; wall-clock runtime varies.

All 656 accepted actions were retested. Of these, 655 stayed positive and
640 passed the fresh two-SE screen. The rejected-key controls had 44 positive
actions out of 200, with 16 passing the screen; none was installed.

Equal-key mean gain shrank from 0.619162 to 0.607196 points (1.93%). Quantiles
below weight canonical keys equally; the third column is the distribution of
paired per-key estimate changes, not the difference between column quantiles.

| Statistic | Original gain | Fresh gain | Fresh minus original |
| --- | ---: | ---: | ---: |
| Mean | 0.619162 | 0.607196 | -0.011966 |
| Minimum | 0.110800 | -0.024000 | -0.254400 |
| 5th percentile | 0.198400 | 0.148300 | -0.151300 |
| 25th percentile | 0.325700 | 0.321700 | -0.065400 |
| Median | 0.500800 | 0.493600 | -0.012800 |
| 75th percentile | 0.854800 | 0.854100 | 0.041400 |
| 95th percentile | 1.324600 | 1.323500 | 0.134600 |
| Maximum | 2.005600 | 2.006000 | 0.223200 |

Gate gains below are net pegging points per hand, mean +/- one standard error.
Each row uses 200,000 uniform physical gate deals. Dealer's candidate-seat
gain is exactly zero because all compared policies leave Dealer unchanged.

| Comparison | Seed | Pone gain +/- SE | Both-seat gain +/- SE | Pass |
| --- | ---: | ---: | ---: | --- |
| Original book minus heuristic | 43 | 0.185580 +/- 0.004088 | 0.092790 +/- 0.002044 | Yes |
| Restricted book minus heuristic | 43 | 0.185200 +/- 0.004019 | 0.092600 +/- 0.002009 | Yes |
| Restricted minus original book | 43 | -0.000380 +/- 0.000749 | -0.000190 +/- 0.000375 | No |
| Pair rule minus heuristic | 44 | 0.055530 +/- 0.003221 | 0.027765 +/- 0.001611 | Yes |
| Pair rule minus original book | 44 | -0.136270 +/- 0.003945 | -0.068135 +/- 0.001972 | No |

The restriction is slightly worse by point estimate, with no resolved strength
difference (z = -0.51). The pair rule improves the heuristic but is clearly
worse than the original book (z = -34.54). It matches 394/656 overrides (60.1%)
and captures about 29% of the original book's gain on the same seed-44 deals.
The book's seed-44 gain is 0.191800, implied by the two paired comparisons;
its marginal standard error is not reconstructed from their marginal errors.

| Overlapping feature | Keys | Original mean | Fresh mean |
| --- | ---: | ---: | ---: |
| Lead from repeated rank | 406 | 0.708724 | 0.703022 |
| Lead from exact pair | 356 | 0.714148 | 0.706773 |
| Lead is lowest | 167 | 0.565042 | 0.552618 |
| Lead is highest | 257 | 0.603675 | 0.596283 |
| Lead is middle | 232 | 0.675276 | 0.658571 |
| Lead count above ten | 0 | Unavailable | Unavailable |
| Lead count equals ten | 220 | 0.620275 | 0.612749 |
| Lead is J, Q or K | 181 | 0.617969 | 0.611931 |
| Hand has repeated rank | 435 | 0.691092 | 0.685005 |
| Hand has two pairs | 15 | 0.587947 | 0.553013 |
| Hand has triple | 51 | 0.665961 | 0.672306 |
| Hand has three-rank run | 65 | 0.630603 | 0.622978 |
| Hand has four-rank run | 5 | 0.530400 | 0.588720 |

Examples of confirmation, ranks shown as cards:

- A A 2 9, lead 2 -> A: original +1.4188, fresh +1.4188 +/- 0.0600;
  retained.
- A 2 7 7, lead 2 -> 7: original +0.3580, fresh +0.1036 +/- 0.0708;
  removed by the two-SE screen despite staying positive.
- 5 9 J Q, lead J -> Q: original +0.1372, fresh -0.0240 +/- 0.0382;
  the sole negative replication, removed. Its fresh sign is itself uncertain.

A took 329.7 seconds total, including 120.1 seconds for 4,280,000 paired
rollout simulations on eight workers. B took 90.0 seconds. No samples were
reduced; neither run approached 45 minutes. Stage 1 remains unchanged.

## Validation and mutation evidence

Required repository validation passed: 321 default tests (five opt-in skips),
284 artifact fast tests (five opt-in skips), all five slow analytical tests,
and 100% artifact-pipeline/legacy-ratchet line and branch coverage. The fast
artifact coverage run resets the data file; append the root legacy-ratchet
tests before checking the combined gate. All required type, lint and spelling
checks and the isolated README `--game-count 10` example passed, with empty
stderr and plausible scoring.

All 17 scratch tests passed (eight stage 1 and nine new tests). The new scratch
module has 100% line and branch coverage, including bounded real CLI runs for
both stages. Tests exercise real serial/two-worker numerical equality and
seed changes. Four retained 2,500-sample rows were replayed serially with exact
equality: a passing accepted key, a positive rejected-by-confirmation key, the
negative accepted key and a rejected control. Reused immutable heuristic
functions and branches had 100% unit coverage before this experiment.

`issue187_book_checks_mutations.json` records 15 single-change mutations,
their exact replacements and the named test that failed for each. These cover
unpaired totals, reused training streams, repeated play seeds, an exclusive
confirmation threshold, the wrong frozen control choice, ignoring the fresh
screen, reversed shrinkage, reversed comparison gain, lost shared-deal
covariance, a changed pair tie, Dealer/reset overrides, face rank used as
count, counting only selected hypotheses and ignored input/evidence hashes.
Every mutation produced an assertion failure in its intended test in an
isolated scratch copy. Mutation copies and logs are local under
`/tmp/issue187-book-checks/mutations/`; other validation and experiment logs
are under `/tmp/issue187-book-checks/`.

## Proposed next checkpoint, not executed

Keep the accepted stage 1 Pone book frozen. For Dealer replies, classify
reply-from-own-pair, pairing the public lead, making fifteen, and run-holding
features, but install only sampled and freshly validated actions. This Pone
experiment supplies no Dealer pattern evidence; the weak pair-rule capture
argues for conditional state measurements rather than assuming the same rule.

A rank-only upper bound is 23,647 feasible Dealer-hand/lead keys and 76,882
distinct replies (each of 1,820 hands times 13 ranks, excluding the 13
impossible exhausted-rank leads). At 2,500 samples per conditional state that
is 192.205 million forced-reply simulations, about 90 minutes at A's observed
worker throughput, before fresh validation or rare-lead conditioning costs.

Propose 7,500 uniform physical Pone keeps per Dealer hand, grouped by the
actual frozen-book lead, forcing every distinct reply on each shared keep.
That is about 44.36 million training simulations (21 minutes extrapolated),
then a separate 7,500-keep stream testing only accepted replies against the
heuristic (at most 27.3 million simulations, 13 minutes extrapolated). Both
runs leave room below 45 minutes for overhead. Conditional counts vary; report
thin/unobserved cells and leave them on heuristic fallback, with a minimum
sample threshold fixed in advance. Keep the z >= 3 selection and fresh z >= 2
confirmation screens. The eventual Dealer/combined gates and any Pone
retraining need their own approved checkpoint. No Dealer calculation has run.
