# Joint exact-book policy research: issue 187

This report freezes the accepted exact Pone lead, Dealer first-reply and Pone
second-card tables. It adds report-only measurements and regenerates the
existing heuristic discard population. It changes no legacy code, generator,
promotion gate, published format, qualifications, release assets or workflows.
No Pone leads or later-layer decisions are retrained.

## 1. Why the second-card advice transfers poorly

For every one of the 9868 second-card overrides, enumerate every feasible
Dealer rank keep after removing Pone's original four cards. Weight each keep
by its physical multiplicity. Compare the actual first reply selected by the
frozen Dealer book with the reply selected by the heuristic. This reuses the
same rank-only uniform hidden-hand prior as the exact books.

For a key, let b and h be the physical masses yielding its observed reply
under those two deterministic policies, and i the mass in both populations.
Their normalized posterior overlap is i / max(b, h), and total variation is
1 minus that overlap. An absent heuristic key has no heuristic posterior;
it is recorded as unavailable, rather than treating an empty population as a
probability distribution. All full information keys remain unchanged.

| Posterior or selected-action result | Value |
| --- | ---: |
| Override keys | 9868 |
| Positive exact gain against heuristic Dealer | 5143 |
| Negative exact gain against heuristic Dealer | 3659 |
| Zero exact gain with heuristic support | 878 |
| No heuristic support | 188 |
| Book-visit-weighted TV, supported keys only | 0.662203 |
| Heuristic-visit-weighted TV | 0.590257 |
| Book-weighted TV counting absent support as one | 0.664433 |
| Book override visit probability | 0.444537 |
| Heuristic override visit probability | 0.381433 |
| Negative overrides: heuristic visit probability | 0.151447 |
| Absent keys: book visit probability | 0.002934 |
| Exact gain against frozen Dealer book | +0.325780811 |
| Exact gain against heuristic Dealer | +0.007011320 |
| Exact gain gap | +0.318769491 |
| Changed key frequencies: gap contribution | +0.055794697 |
| Changed conditional posteriors: gap contribution | +0.262974793 |

The decomposition is an identity, not a correlation argument: for original
hand weight w and conditional gains gB and gH, sum
w * [(b-h)*gB + h*(gB-gH)] over keys and divide by the physical ordered-hand
population 52677670500. Posterior changes account for 82.50% of the gap;
changed frequencies account for 17.50%. The heuristic exact gain agrees with
the earlier independent gate marginal +0.008130 +/- 0.003919.

The advice is correct within its frozen Dealer-book model. It is opponent
specific, and 3659 entries are actually negative advice under the heuristic
Dealer posterior. It cannot be called universally good advice. This difference
is not an implementation error or residual selection bias.

## 2. Both seats use the same role-aware policy

Every report plays six arms on identical cards and one common play seed per
deal. The uniform arm uses the unmodified promotion gate's default 200000
physical deals and seed 42. All displayed uncertainties are one standard error.
Absolute point errors and errors of paired differences are stored separately;
net delta is Pone points minus Dealer points. Dealer's net delta and delta
change are exactly the negatives of Pone's, so they are not separate gains
that can be added together. Both seats use the same ensemble of role-keyed
books with heuristic fallback.

| Both-seat policy | Pone points | Dealer points | Pone points change | Dealer points change | Pone net delta | Pone net delta change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Heuristic | +1.942705 +/- 0.003832 | +3.274660 +/- 0.004242 | +0.000000 +/- 0.000000 | +0.000000 +/- 0.000000 | -1.331955 +/- 0.005833 | +0.000000 +/- 0.000000 |
| Stages 1+2 | +2.005700 +/- 0.004167 | +3.500865 +/- 0.004520 | +0.062995 +/- 0.004046 | +0.226205 +/- 0.004070 | -1.495165 +/- 0.005878 | -0.163210 +/- 0.005983 |
| Stages 1+2+3a | +2.071005 +/- 0.004142 | +3.243870 +/- 0.004395 | +0.128300 +/- 0.004166 | -0.030790 +/- 0.004233 | -1.172865 +/- 0.005754 | +0.159090 +/- 0.006198 |

Adding 3a to joint stages 1+2 gives Pone net delta
+0.322300 +/- 0.004107, decomposed into Pone's own points
+0.065305 +/- 0.002382 and Dealer's own points
-0.256995 +/- 0.003136. This agrees with the exact +0.325781 expectation
within the uniform measurement error. It is the relevant joint-policy quantity
for means measured with the same play policy in both seats.

The heuristic cross-opponent checks are positive in each candidate seat:

| Population and candidate | Pone against heuristic Dealer | Dealer against heuristic Pone | Within-deal both-seat average |
| --- | ---: | ---: | ---: |
| Uniform books12 | +0.206630 +/- 0.004755 | +0.164830 +/- 0.004929 | +0.185730 +/- 0.003061 |
| Uniform books123 | +0.214760 +/- 0.005507 | +0.164830 +/- 0.004929 | +0.189795 +/- 0.003228 |
| Production keeps books12 | +0.180780 +/- 0.004488 | +0.241665 +/- 0.004503 | +0.211223 +/- 0.002929 |
| Production keeps books123 | +0.233855 +/- 0.005456 | +0.241665 +/- 0.004503 | +0.237760 +/- 0.003155 |

These cross arms test the heuristic opponent, not worst-case opponent strength.
Stage 1+2 is robust to that specific opponent in both seats. Stage 3a has a
large joint-policy effect despite its small uniform cross-opponent marginal.
The previous first-exchange cutoff recommendation was based on the unilateral
marginal; it does not hold for the product's joint-policy metric. This result
supports retaining 3a as a meaningful candidate, while leaving deeper gains
and a policy-iteration equilibrium unclaimed.

## 3. Production-style population without invented discards

The population builder calls the actual solve_initial_discard_policy(40, 2),
then heuristic_fallback with two outer passes, 200 policy-table samples and
seed 42 over all 1820 kept-hand keys. These are the production workflow's
existing analytical and enforced-fallback settings. It performs no capped
policy training or full final generation. Each role's 18395 six-rank hands
has its actual selected four-card keep. Physical six-hand weights sum to
20358520 per role. The two-pass refinement is capped and not converged;
this matches the existing production setting rather than claiming a new
converged discard optimum.

The reconstruction took 327.63 seconds, including 173.18 seconds for the
analytical initialization. The keep-policy fingerprint is
326f6541973eeb44d763f3efc4182f0884f77e6473013e3bef739c4c6856c720;
the compact keep-row digest is
b9361d95ccbbc70ffda29a4061b4c01f327e56aac36b42dc066ef5c2598711cb.

The report draws twelve distinct physical cards using sample_policy_deal,
keeps each seat's chosen four from its six, and plays all six arms on those
same keeps. Its separate labeled stream is reproducible at seed 42 and
200000 deals. The common heuristic-refined keeps are held fixed across
policies; candidate-specific discard refinement would be a later production
integration step. No discard population was invented and the default uniform
safety gate is unchanged.

| Both-seat policy | Pone points | Dealer points | Pone points change | Dealer points change | Pone net delta | Pone net delta change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Heuristic | +2.280625 +/- 0.004811 | +3.483640 +/- 0.004993 | +0.000000 +/- 0.000000 | +0.000000 +/- 0.000000 | -1.203015 +/- 0.006385 | +0.000000 +/- 0.000000 |
| Stages 1+2 | +2.362580 +/- 0.005251 | +3.723470 +/- 0.005420 | +0.081955 +/- 0.004314 | +0.239830 +/- 0.004096 | -1.360890 +/- 0.006526 | -0.157875 +/- 0.005816 |
| Stages 1+2+3a | +2.413735 +/- 0.005191 | +3.471365 +/- 0.005192 | +0.133110 +/- 0.004532 | -0.012275 +/- 0.004399 | -1.057630 +/- 0.006284 | +0.145385 +/- 0.006171 |

Joint 3a marginal on production keeps is
+0.303260 +/- 0.004228 Pone net delta, comprising own points
+0.051155 +/- 0.002561 and Dealer points -0.252105 +/- 0.003495.
The report-only safety averages are shown above: +0.211223 +/- 0.002929
for stages 1+2 and +0.237760 +/- 0.003155 for stages 1+2+3a.

## 4. Retrievable policy: measured feasibility, no published format

The size experiment makes compact sorted JSON rank-action maps keyed by the
complete actual PolicyView.key() string. A real simulation test loads merged
role maps into one TabularPeggingPolicy in both seats and proves identical
complete games. These are research encodings measured in memory, not new
published assets or a supported schema.

| Loadable map | Entries | Raw bytes | gzip bytes |
| --- | ---: | ---: | ---: |
| pone-lead | 878 | 40571 | 2711 |
| dealer-reply | 10495 | 555523 | 34221 |
| books12 | 11373 | 596093 | 37132 |
| books123 | 21241 | 1116863 | 78072 |
| pone-second | 9868 | 520771 | 40112 |

The merged stages 1+2 map is about 1.42 MB of measured Python dictionary,
unique key strings and values; JSON parsing took about 0.003 seconds locally.
The merged stages 1+2+3a map is about 2.29 MB. These measurements exclude
other generator data and peak allocation during parsing. Stages 1+2 are small
enough for a generator input and release asset. They are also small enough
for a trainer opponent implemented as lookup plus the matching deterministic
fallback. That performs no opponent-hand enumeration or pegging rollout in
the browser and reveals no hidden cards. Even the 3a sparse map is small;
the prior full-depth hypothetical map has a different scale.

A future portable contract must specify all seven key fields, zero-based
ranks, role names, tuple ordering and go/reset encoding. Python repr keys
need either an exact browser codec or a versioned language-neutral codec.
A browser fallback port requires Python golden tests; it cannot silently
substitute a different heuristic. An unrecognized or illegal table action
falls through to the same heuristic, as TabularPeggingPolicy already does.

Proposed digest binding: hash exact canonical action bytes as actions_sha256,
retain the semantic policy fingerprint including fallback identity, and pair
an envelope with means_sha256 of the exact client means bytes produced by
that frozen policy. Specify format/key-codec and fallback versions and verify
both digests before loading. Publish the book and means together only after
separate integration approval. Existing heuristic means cannot truthfully be
paired with this book merely by hashing them; no such binding was created here.

## 5. What measuring production means would require

Existing generate_play_table already accepts fixed policies for both seats.
The future generator integration needs a validated book loader and a frozen
policy choice in the main orchestration. Initialize from the analytical
context, refine discards with refine_discards(fixed_policies=books12), skip
the current iterative play training and final training pass, and measure
with the same frozen books in both seats on those book-refined keeps.
The report-only heuristic-refined keeps above must not substitute for that
refinement in a published candidate run.

Keep evaluate_promotion unchanged as the uniform heuristic safety check.
If enforced promotion fails, retain the existing restart from the analytical
context, heuristic discard refinement and heuristic measurement. Report the
safety result and the distinct joint-policy measurement rather than treating
the safety average as E(delta P).

The existing enforced measured_policy value trained can describe any
candidate Mapping at the technical level, but its release description says
trained pegging policies and does not identify the retrievable exact book.
A deliberate future provenance change should use an explicit frozen-book
label, its action/fallback fingerprint, the actual discard-policy fingerprint,
and the measured refinement source. MEASURED_DESCRIPTIONS and provenance
readers would need the corresponding approved extension. A failed enforced
run continues to say legacy-heuristic. No metadata values or readers changed
in this research phase.

| Repeat | Heuristic seconds | Stages 1+2 seconds | Ratio |
| --- | ---: | ---: | ---: |
| 1 | 8.270 | 9.169 | 1.10877 |
| 2 | 8.073 | 9.002 | 1.11511 |
| 3 | 8.597 | 9.278 | 1.07926 |

Each timing arm is a bounded real generate_play_table call on the same 200
labeled random canonical hands, two roles and 200 samples: 80000 complete
simulations. Three paired repeats alternate arm order (480000 total), use
the actual reconstructed opponent keeps and fixed seed, and exercise the
actual per-key measurement path rather than extrapolating exact-rollout speed.
The median paired ratio is 1.10877; individual ratios span 1.07926-1.11511.
At the supplied 97-minute heuristic sampling baseline, budget roughly
8-11 extra sampling minutes, about 108 minutes using the median ratio.
Loading the map is negligible. Two candidate discard-refinement tables and
the unchanged safety gate add several minutes; skipping the old failed
training path saves time, so a whole-workflow total is not derived from the
sampling ratio alone.

The latest completed production run 37706691080 is a different machine/time
baseline: its final heuristic sampling log runs from 00:50:07.146 UTC to
03:34:29.428 UTC, 164.37 minutes, not 97. On that baseline the same ratio
projects about 182.25 minutes of sampling, about 17.88 extra minutes.
These are estimates: book-refined keeps and runner performance can change
throughput. No full final generation or workflow dispatch was performed.

## Reproduce and review

From the repository root with the documented Python environment and a
bootstrapped tally shelf, run each phase in this order. Use an isolated working
directory and PYTHONPATH pointing at the repository for the population and
timing commands to keep runtime databases out of the checkout.

```sh
python -m scratch.book_product_checks posterior --workers 8 --output posterior.json
python -m scratch.book_product_checks uniform --output uniform.json
python -m scratch.book_keep_population build --population keeps.json
python -m scratch.book_keep_population compare --population keeps.json --output production.json
python -m scratch.book_product_checks sizes --output sizes.json
python -m scratch.book_keep_population timing --population keeps.json --output timing.json
python -m unittest test_pegging_research
```

The repository's root loader collects all 47 research regressions in ordinary
CI discovery, including eight new tests for posterior physical-draw oracles,
actual complete-game gains, normalization, covariance, real promotion parity,
loadable-map behavior and generator population settings/integrity. Six
isolated mutants fail the named regressions: wrong posterior normalization,
wrong observed-reply model, reversed paired seat points, unpaired errors,
wrong fallback settings and ignored keep digest. Candidate evidence is
retained in issue187_product_*.json with full integer posterior rows and the
regenerated six-hand keep mapping. No 100% scratch unit-coverage claim is made.

Required validation passed: default discovery, artifact fast and all five
slow analytical tests, 100% artifact/ratchet coverage, mypy, legacy ratchet,
legacy similarities, artifact pylint, flake8, research pylint and spelling.
The README ten-game smoke completed with plausible cribbage scores and empty
stderr. Experiments took 34.06 seconds for posterior enumeration, 117.29
seconds for uniform comparisons, 327.63 seconds for keeps, 122.74 seconds for
production compare and about 51.5 seconds for the six timing arms. Every
run stayed well below 45 minutes. CI is reported separately on the final head.
