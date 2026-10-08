# Exact opening books: issue 187

These are reproducible research experiments beside the immutable simulator.
They replace neither production policies nor published artifacts. The sampled
stage 1 and A/B evidence remain unchanged and are historical checkpoints.

## Model and selection

Before inspecting results, epsilon was fixed at 1/1,000,000 net pegging points.
For each known four-card rank multiset, remove its physical cards. Enumerate
all feasible opponent rank multisets with multiplicity
`product(comb(4 - own_count[rank], opponent_count[rank]))`. Every conditional
population sums to `comb(48, 4) = 194580`; the own-hand population sums to
`comb(52, 4) = 270725`. Their ordered physical joint weight is 52677670500.
Suit distinctions have no effect on these deterministic pegging policies.

Every alternative shares the complete opponent population. Score differences
and multiplicity-weighted sums are integers. Choose the largest positive gain
sum, then the lowest rank on an exact tie; retain the heuristic on zero gain.
The smallest possible positive conditional gain is at least 1/194580, larger
than epsilon. Consequently epsilon zero produces exactly the same books.
There are no sampling standard errors or multiple-testing screens inside this
stated model. Exactness does not establish equilibrium or optimal play against
other policies. Later decisions use the heuristic in both seats.

Dealer replies condition on the frozen exact Pone opening policy: partition
Pone hands by their actual selected lead, then enumerate each distinct reply.
Keys come from the actual `PeggingState.view()`, including the opening public
history and remaining-card counts. Non-installed decisions fall back exactly
to `LegacyHeuristicPolicy`.

## Results

| Quantity | Sampled Pone book | Exact Pone book |
| --- | ---: | ---: |
| Installed opening overrides | 656 | 878 |
| Exact uniform physical population gain vs heuristic | 0.188706685 | 0.202740872 |
| Default gate Pone gain, one SE | 0.190935 +/- 0.004068 | 0.206630 +/- 0.004755 |
| Default gate both-seat gain, one SE | 0.0954675 +/- 0.002034 | 0.103315 +/- 0.002378 |

Dealer gain is zero in both Pone-only gate arms. All gates use the merged
`evaluate_promotion`, its default 200000 deals and seed 42. Gate minus exact
population estimates are 0.55 and 0.82 SE respectively, consistent with noise.

There are 237 changed decisions: 222 new overrides, 15 changed selected leads,
and none removed. All 656 sampled overrides have positive exact gain. Their
unweighted conditional mean shrinks from 0.619162195 to 0.607123254 (1.94%).
Exact-minus-sampled gain quantiles are: minimum -0.203225; fifth percentile
-0.114231; first quartile -0.053656; median -0.011989; third quartile 0.024377;
95th percentile 0.098868; maximum 0.177144. These conditional equal-key means
are different from the physical population means above.

Largest changed-decision improvements over the sampled choice include
A-2-8-10, changing 2 to 8 (+0.331046); A-3-5-K, changing 3 to K (+0.325069);
6-6-7-9, changing 9 to 6 (+0.322119). The largest sampled error among all
alternatives was 3-4-8-J, lead 8: sampled -0.635600, exact -0.900488.

Of 1105 kept rank multisets containing a repeated rank (including triples and
quads), 885 (80.09%) have a paired card among the exact best leads, allowing
ties. Their physical-weight fraction is 68485/87685 (78.10%). When two ranks
are paired, the report-only rules below choose the lowest eligible rank.

| Report-only rule | Exact gain vs heuristic | Exact gain vs exact book |
| --- | ---: | ---: |
| Always lead from a pair, otherwise heuristic | 0.052683327 | -0.150057546 |
| Lead lowest paired rank except a 5, otherwise heuristic | 0.074597000 | -0.128143872 |
| Lead lowest pair with count 6 through 10, otherwise heuristic | 0.068566815 | -0.134174058 |

The finite descriptive menu contains 1365 rules: contiguous pair-count ranges
or exclusion of one count, with optional thresholds on the lowest other card.
Excluding pair 5 is the best family; an additional low-card condition does not
improve it. These refinements capture only 36.8% and 33.8% of exact book gain.
No refined policy class was implemented or installed.

Dealer first replies have 23635 observed keys (23479 optional), 25 unobserved
of 23660 possible hand/lead combinations, and 10495 positive overrides.
Epsilon zero changes none. Every hand's partition again sums to 194580. The
exact Dealer gain against the frozen exact Pone book is 0.373200355. The merged
gate measures each trained seat against the heuristic in the opposite seat,
so its Dealer number has a different opponent population:

| Combined exact stages 1 and 2 vs heuristic | Gain | SE |
| --- | ---: | ---: |
| Pone | 0.206630 | 0.004755 |
| Dealer | 0.164830 | 0.004929 |
| Both seats, paired within deal | 0.185730 | 0.003061 |

The gate passes. Pone leads were not re-estimated against the Dealer book.
Production-style keeps remain unavailable in the saved artifacts; means and
fingerprints do not reconstruct actual discard populations, so no such arm is
invented.

Each stage enumerated 10676575 continuations on eight spawned workers. Pone
training took 173.75 seconds (280.25 seconds including two gates); Dealer took
171.25 seconds (225.93 seconds including its gate). A 20-hand pilot established
the cost before the Dealer run. No run approached 45 minutes.

## Independent review: verified claims and corrections

The Opus review at `/Volumes/CaseSensitiveCode/personal/agy-runs/` was read in
full. Determinism is verified by source inspection and unchanged RNG state,
not inferred from Dealer's paired gate SE being zero. That zero follows from
identical policies and shared draws even if the policy were stochastic.

The original eight tests let both full-deck and once-sampled mutants pass.
New sampler-boundary tests fail for both: they independently check card removal
and variation across actual draws. Physical-draw oracles additionally verify
the exact weights, removal and weighted score sums. A non-empty book now fires
inside a complete real simulation and the real merged promotion gate using
actual state views, so dead information keys cannot pass unnoticed.

Floating moment means really could break integer ties: equal sums of 80 over
20 observations gave different floating means. The new test failed before the
fix. Sampling now keeps authoritative integer gain sums and compares rational
means; the retained historical evidence is unchanged. Exact selection likewise
uses integer sums and tests integers above floating precision.

The original scratch tests were not collected by default CI discovery. A root
`test_pegging_research.py` loader now collects all 30 scratch regressions in
ordinary `coverage run`, without changing workflows. The original 100% scratch
coverage claim included a bounded real CLI run, not only eight unit tests;
that saved coverage file reproduced 100% lines and branches. The review was
right that eight tests alone did not establish it, but wrong to treat the
claim as unsupported by all retained validation. The current focused test run
covers 97% of research lines, including new guards and real integration;
remaining CLI-entry/progress guards are explicitly separate from the required
100% artifact-pipeline and reused-legacy coverage claims.

The raw research gate result is not a production release document; it is not
passed to release-summary readers requiring report mode. No production schema
fix is indicated. Training versus gate noise alone is not a selection-bias
estimate; exact quality above now answers that question inside this model.
Hardcoded deterministic continuations and short non-resumable runs are scoped
research choices, not changes to the generation contract.

Nine isolated mutations identify concrete failing assertions: full deck,
sample once, floating sampled ties, dead book keys, wrong exact population,
ignored physical weights, floating exact sums, ignored frozen Pone leads,
and missing Dealer public history. Integer ties were tested red before fixing;
new oracle tests were tested red against their respective scratch mutations.

## Reproduction and validation

From the repository root, with the supported interpreter and dependencies,
bootstrap the shelf as described in README. Run each command with a distinct
output path; gate seeds affect only independent Monte Carlo validation:

```sh
python -m scratch.exact_pegging_book pone --workers 8 --seed 42 --output /tmp/exact-pone.json
python -m scratch.exact_book_analysis --book /tmp/exact-pone.json --output /tmp/exact-pairs.json
python -m scratch.exact_dealer_book --pone /tmp/exact-pone.json --workers 8 --seed 42 --output /tmp/exact-dealer.json
python -m unittest test_pegging_research
```

The full required repository checks passed: default suite (351 tests, five
opt-in skips), artifact fast tests, all five slow analytical tests, combined
100% artifact-pipeline/legacy-ratchet line and branch coverage, mypy, pipeline
pylint, legacy duplicate-code and ratchet checks, flake8 and spelling. Explicit
research lint and spelling and the isolated README ten-hand smoke also passed.
Every reused immutable heuristic path had 100% coverage before research ran.
Mutation replacements and full integer evidence are retained beside this note.
Local logs and scratch mutants are under `/tmp/issue187-exact/`.

A subsequent approved phase will freeze these two books for Pone's second
card and measure the cost of all reachable optional decision layers. It will
not re-measure Pone opening leads or train deeper reply layers.
