# Expected Opponent Hand Points Spike

## Recommendation

Defer a production expected-opponent-hand artifact.

Suit normalization makes a suit-aware table feasible to store, particularly in
a packed representation, but the value cannot change discard recommendations.
Once the user's full six-card deal is known, the same six cards are unavailable
for every one of the 15 discard choices. An opponent who cannot see the user's
selected discard therefore has the same possible deal, discard policy, and
starter distribution for every row. Adding the opponent expectation subtracts
the same constant from every candidate and leaves their ordering unchanged.

The estimate may still make a future presentation read more naturally. That is
a product-display question rather than a discard-analysis improvement, and it
does not justify the generation and browser costs on its own.

## Model

The objective model used for this spike is:

1. Remove the user's six known physical cards from the deck.
2. Deal the opponent six cards uniformly without replacement from the 46
   remaining cards.
3. Select the opponent's four kept ranks with the existing role-specific
   analytical `E(h +/- c)` policy: Dealer maximizes hand plus crib value, and
   Pone maximizes hand minus crib value.
4. Draw the starter uniformly from the 40 cards remaining after both six-card
   deals.
5. Score the opponent's kept hand using ordinary non-crib hand scoring.

Random discards are objective as a baseline but do not represent a rational
opponent. The legacy static strategy mixes rules of thumb with mathematical
components and is not suitable as the defining model. The policy-driven model
is reproducible and consistent with the artifact pipeline's mathematical
principle.

The analytical policy reached its configured 100 pair iterations and three
full-hand refinement iterations. It ended in the existing small pair-policy
cycle and with 183 changed full-hand discards, so the reported values are exact
conditional expectations for that bounded policy, not a claim of globally
converged optimal play. The discard-invariance conclusion does not depend on
which hidden-information opponent policy is chosen.

## Suitless Exact Analysis

The suitless model groups physical cards by rank. There are 18,395 valid
six-rank multisets after enforcing the four-card limit for each rank. Their
physical multiplicities sum to all `C(52, 6) = 20,358,520` six-card deals.

For a known rank hand `U`, opponent hand `H`, role policy keep `K(H)`, and
starter rank `r`, the exact expectation is proportional to:

```text
sum_H weight(H | U) * sum_r (4 - count_U(r) - count_H(r)) * score(K(H), r)
```

The denominator is `C(46, 6) * 40`. Inclusion-exclusion aggregates for subsets
of the six known cards make all 18,395 conditionals practical without a
quadratic loop over known and opponent hands.

On 2026-07-11, using Python 3.14.4 on arm64 macOS 26.5.1:

- bounded analytical policy construction took 373.6 seconds;
- all 18,395 exact conditional entries took 3.2 seconds afterward;
- sampling variance is exactly zero inside the rank model;
- Dealer expectations ranged from 6.794 to 8.578 points, with a population
  standard deviation of 0.244 across known rank deals; and
- Pone expectations ranged from 6.906 to 8.731 points, with a population
  standard deviation of 0.256 across known rank deals.

This variation is large enough to change the displayed opponent-side number
between different deals, but it remains constant among the 15 discard choices
within any one deal.

The full rank table with two JSON numbers per key measured 1,247,728 bytes
minified and 379,967 bytes with gzip. Its two raw float32 values per key require
147,160 bytes before an index.

## Suit-Aware Analysis

Cribbage scoring is unchanged by globally renaming the four suits. Canonicalizing
each physical deal across all 24 suit permutations reduces 20,358,520 physical
deals to 962,988 equivalence classes. For example, a four-club/two-diamond deal
is equivalent to the same rank-to-suit incidence expressed as four hearts and
two spades. A different assignment of ranks to those suits is not necessarily
equivalent.

The 962,988 count was calculated with the group-action fixed-point average:

```text
(20,358,520 + 6*450,216 + 3*2,600 + 8*5,512 + 6*0) / 24
= 962,988
```

Exact physical enumeration is not practical for a complete table. One known
deal has `C(46, 6) * 40 = 374,672,760` opponent-deal/starter outcomes before
evaluating alternative discard candidates. Repeating that for 962,988
normalized known deals would exceed 360 trillion outcomes.

The physical pilot sampled six representative known deals covering one-suit,
4-2, 3-3, 2-2-2, paired-rank, and triple-rank patterns. It used 10,000 samples
per deal and opponent role, for 120,000 samples total, with seed 42. Physical
cards, flushes, and nobs were scored exactly. Discarded ranks came from the
analytical policy; when rank-equivalent physical cards could be kept, their
suits were selected without bias. This tests suit-aware scoring and removal but
does not claim a fully suit-optimized opponent policy.

The observed score standard deviations were 3.61 to 3.95 points, producing
standard errors of 0.036 to 0.039 at 10,000 samples. Differences from the
suitless baseline ranged from -0.014 to +0.071 points. Most were no larger than
about two pilot standard errors, so the pilot does not establish a reliable
per-entry suit correction at this sample count.

The pilot ran at about 76,814 samples per second on one process. Using its
largest observed standard deviation, a complete two-role normalized table is
projected to require:

| Target per-entry SE | Samples per entry | Total samples | Single-process time |
| --- | ---: | ---: | ---: |
| 0.04 | 9,729 | 18.74 billion | 2.8 days |
| 0.02 | 38,915 | 74.95 billion | 11.3 days |
| 0.01 | 155,660 | 299.80 billion | 45.2 days |

These are sampling-only projections. A fully suit-aware discard policy would
add work and should be measured separately before any production commitment.

## Artifact Implications

For 962,988 normalized keys and two role values:

| Representation | Estimated size | Notes |
| --- | ---: | --- |
| Minified JSON | 70.9 MB | Projected from representative physical keys and values |
| Gzip JSON | 21.6 MB | Rough projection using the rank table's compression ratio |
| Packed float32 values | 7.7 MB | Excludes a key-to-index implementation |
| Quantized int16 suit residuals | 3.9 MB | Requires a separately defined precision bound |
| Rank float32 baseline plus int16 residuals | 4.0 MB | Excludes indexing and transport framing |

Suit normalization therefore makes producer-side storage manageable. A single
JSON object remains unattractive for a browser because transfer size understates
its parsed JavaScript-object memory. A packed or rank-baseline-plus-residual
format is a plausible future direction if a presentation experiment establishes
user value, but it would require a deliberate browser contract, precision gate,
and consumer implementation.

## Acceptance Criteria Assessment

- A feasible model is documented for both exact suitless and sampled suit-aware
  analysis.
- Runtime, variance, noise floor, and candidate artifact sizes are measured or
  explicitly projected from measured data.
- Exact enumeration is practical for the rank model but not for a complete
  physical-card table; Monte Carlo or a more advanced exact aggregation would
  be required for suit-aware values.
- Opponent hand points change no discard rankings within a known six-card deal.
- Production should be deferred; normalized packed encodings remain future
  research for presentation only.
- All expensive opponent-hand analysis stays in the Python producer. No
  browser-side simulation is proposed.

## Reproducing the Analysis

Run the complete analysis from the repository root:

```sh
python artifact_pipeline/analyze_opponent_hand_points.py \
  --physical-samples=10000 \
  --seed=42 \
  --output=opponent_hand_points_analysis.json
```

For a bounded smoke run, reduce the analytical policy and output surface:

```sh
python artifact_pipeline/analyze_opponent_hand_points.py \
  --analytical-max-iterations=2 \
  --full-hand-policy-max-iterations=1 \
  --hand-limit=4 \
  --physical-samples=0 \
  --output=opponent_hand_points_analysis.smoke.json
```

The JSON output includes timing, state counts, exact role summaries, physical
pilot moments, runtime projections, and representation-size estimates. It is a
research report, not a published client artifact.
