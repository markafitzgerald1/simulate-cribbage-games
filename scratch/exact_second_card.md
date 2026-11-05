# Exact second card and measured depth cost: issue 187

This phase follows the exact stages 1-4 checkpoint posted as issue comment
6053493823. It freezes the exact Pone opening book and Dealer first replies.
The Pone opening choices were not re-optimized against the Dealer book.
Research code and evidence remain outside published artifacts and workflows.

## Stage 3a model and results

For each original Pone kept hand, enumerate every feasible Dealer rank keep
with the physical multiplicity after removing Pone's four cards. The frozen
Pone book chooses the lead; the frozen Dealer book chooses the actual reply.
Partition Dealer keeps by the resulting complete `PeggingState.view()` for
Pone's second card. Every conditional cell shares the same hidden population
across all distinct legal alternatives. Force each alternative, then use the
heuristic in both seats for the continuation. Prefix points cancel in paired
differences. No go/reset can occur before the third public card: two card
counts total at most twenty. Later goes and resets are handled by the simulator.

Only states with more than one distinct legal rank are rolled out. Integer
weighted gain sums choose overrides above the unchanged epsilon of 0.000001;
true positive ties choose the lowest rank, and zero gain retains the heuristic.
Install those full-view entries alongside the unchanged Pone lead entries in
one `TabularPeggingPolicy`, with heuristic fallback. Dealer remains frozen.

| Stage 3a result | Value |
| --- | ---: |
| Observed second-card keys | 23584 |
| Optional second-card keys | 23117 |
| New positive overrides | 9868 |
| Epsilon-zero different overrides | 0 |
| Exact marginal gain against frozen Dealer | 0.325780811 |
| Continuation simulations | 8923666 |
| Training seconds, eight workers | 117.03 |
| Total seconds including gate and marginal comparison | 208.83 |

Every original hand's observed-reply partition sums to 194580 physical draws.
A twenty-hand one-worker pilot took 5.37 seconds for 68833 continuations,
establishing the runtime budget before the complete calculation. Nothing
approached 45 minutes, and no samples were reduced: enumeration is exact.

All gate results below use the unmodified `evaluate_promotion` defaults:
200000 uniform physical deals, seed 42, independent gate streams, and one SE.
The marginal comparison replays candidate and reference Pone policies on the
same `gate_deals` and play seeds against heuristic Dealer. Dealer's candidate
policy is unchanged, so its marginal is zero; the both-seat difference is half
the per-deal Pone difference. SEs come from those paired differences, never from
subtracting marginal SEs.

| Policy vs heuristic | Pone gain +/- SE | Dealer gain +/- SE | Both-seat gain +/- SE |
| --- | ---: | ---: | ---: |
| Frozen stages 1+2 | 0.206630 +/- 0.004755 | 0.164830 +/- 0.004929 | 0.185730 +/- 0.003061 |
| Stages 1+2+3a | 0.214760 +/- 0.005507 | 0.164830 +/- 0.004929 | 0.189795 +/- 0.003228 |
| Paired marginal 3a over 1+2 | 0.008130 +/- 0.003919 | 0 +/- 0 | 0.004065 +/- 0.001959 |

The combined policy passes. The marginal change has z = 2.07 and fails the
three-SE promotion criterion on its own. The much larger exact gain against
the frozen Dealer does not transfer to heuristic Dealer: the same observed
reply can imply a different hidden population under a different policy. This
is a model/opponent distinction, not remaining sampling selection bias.
The second-card entries are retained as approved research, without a claim
that they independently qualify for production promotion. There is still no
retrievable production discard-keep population for an additional arm.

## Measured full-depth cost

The cost counter enumerates all 3274375 feasible ordered rank-hand pairs for
each seat's original-hand partition. It traces the frozen stages 1+2+3a and
collects every full public view with more than one distinct legal rank.
A decision layer is `5 - len(own_remaining)`, not an alternating turn number.
Passes/go decisions have no alternative, and fourth cards are forced, so none
are counted. Public history includes every go and sequence reset. Reconstructing
the original own hand from the public actors proves original-hand jobs have
disjoint full keys; that invariant is asserted for every counted decision.

This measures all reachable optional information sets under the frozen
policies. It does not enumerate every counterfactual history produced by
changing previous actions. Policy changes require recounting their support.
A complete frozen sweep here means force each distinct legal action once for
every consistent opponent rank keep, including the heuristic baseline. Physical
multiplicities weight expectations; suits do not require separate simulations.

| Layer | Information sets | Mean alternatives | Mean consistent rank keeps | Simulations per sweep |
| --- | ---: | ---: | ---: | ---: |
| Pone first | 1807 | 3.2662 | 1802.2302 | 10658830 |
| Pone second | 23117 | 2.7725 | 139.0820 | 8923666 |
| Pone third | 229561 | 2.0000 | 9.9232 | 4555964 |
| Dealer first | 23479 | 3.2668 | 138.7039 | 10658830 |
| Dealer second | 260569 | 2.5247 | 9.8812 | 6588142 |
| Dealer third | 976317 | 2.0000 | 2.1520 | 4202128 |
| Total | 1514850 | | | 45587560 |

The count took 155.67 seconds on eight workers. It includes 156092 Pone-third,
79066 Dealer-second and 660161 Dealer-third keys with go history; the respective
reset-history counts are 163229, 79066 and 847768. These overlap and are not
extra keys. Pone first excludes thirteen quads; Dealer first excludes forced
quad replies. Pone-second sweep simulations match stage 3a exactly.

The first timing pilot was deliberately extended to reduce startup noise.
The retained final benchmark uses 200 labeled random original hands per seat,
all their opponent keeps, and all optional legal continuations: 5020498
simulations in 88.08 seconds, or 57000.49 simulations/second across eight
workers including trace/startup overhead. Per-layer worker timing projects
640.58 seconds of pure continuations; aggregate throughput projects a full
sweep of 799.77 seconds, about 13.3 minutes, including trace overhead. Integer
value accumulation, table assembly and gates add work not measured by this benchmark; budget
15-20 minutes per initial full sweep rather than promising an exact runtime.

The prior of 100 million simulations in six minutes is corrected in both
directions: fewer simulations, slower measured rate. For one deterministic
on-policy rank-only sweep, a loose population-independent bound is eighteen
alternatives per ordered pair, or 58938750 continuations here. Counterfactual
history trees and stochastic mixtures are different experiments with larger
support. Split any future run exceeding 45 minutes by seat and original-hand
ranges; deterministic physical sums combine exactly across those shards.

A fixed-point sweep count was not measured and cannot be guaranteed; alternating
best responses can cycle, and reachable supports change. At the current frozen
rate, five/ten/twenty sweeps are 66.6/133.3/266.6 minutes before extra assembly,
gates and support changes. Those are planning scenarios, not convergence
predictions. No policy iteration or later-layer optimization was run.

## Table sizes and depth cutoff

The following are measured serialization sizes for one action at every current
optional key, an upper bound on selected overrides until deeper layers are
trained. Full view strings are preserved. Across the two role dictionaries,
compact JSON is 102223489 bytes (about 102.2 MB); the sum of independently
compressed original-hand shards is 9378938 bytes (9.38 MB). The latter is an
actual sharded size, not a measured single-file compressed size.

| Layer | Entries | Compact action-map JSON bytes |
| --- | ---: | ---: |
| Pone first | 1807 | 83348 |
| Pone second | 23117 | 1215772 |
| Pone third | 229561 | 14954118 |
| Dealer first | 23479 | 1242733 |
| Dealer second | 260569 | 16657700 |
| Dealer third | 976317 | 68069822 |

Merging layer dictionaries removes one byte per join; the sum of layer bytes
is consequently four bytes above the two complete role dictionaries. The
independent JSON-size regression checks that boundary. Dealer second and third
contain 81.0% of all keys, confirming that part of the prior.

Measured Python string sizes plus actual dictionary-capacity allocations
estimate 35818322 bytes for Pone and 172868876 for Dealer: 208687198 bytes
(199.0 MiB) together. Shared small integer values are not counted repeatedly.
This is action-structure memory, not measured peak RSS. JSON parsing, sorting
and representation during `policy_fingerprint`, full research evidence and
training accumulators require extra memory; spawned processes multiply it.
The generic tabular policy can represent these keys, and
`generate_play_table(..., policies=...)` accepts those policies. A backend
process could plausibly load this size with an explicit memory budget, but no
existing CLI book loader or published artifact integration was added. Retaining
all previous response tables as fallback/mixture snapshots would multiply the
memory requirement across sweeps.

A deep book is not a drop-in browser artifact: current client means are keyed
by kept ranks and role, not full public decision states. Shipping roughly
102 MB of full-key JSON and parsing it into mobile memory would be a substantial
new product and format decision. No such format or release change is proposed.
Actual selected deep override counts and sizes remain unknown; fallback makes
sparse storage possible, but a smaller result must be measured after training.

For comparison, current selected stages 1+2 need 11373 actions, 596094 compact
JSON bytes and 37820 gzip bytes across their two maps. Adding approved stage
3a makes 21241 actions, 1116864 JSON bytes and 79547 gzip bytes, with about
2.29 MB of Python key/dictionary structure. Complete candidate evidence is
larger than these action-only maps.

A sensible present cutoff is the first exchange. It has strong default-gate
evidence in both seats and a compact sparse policy. Pone's second card nearly
doubles installed actions for only +0.004065 both-seat marginal points, below
the three-SE criterion. The third-card/Dealer-second layers were not optimized,
so monotone marginal-gain decay beyond 3a is not established. Further depth
would need separate measured marginal gains before choosing a larger cutoff.

## Reproduction and validation

Run with Python 3.14.4 and README dependencies/shelf setup. Paths may point to
retained branch evidence or freshly regenerated exact parent reports.

```sh
python -m scratch.exact_second_card --pone scratch/issue187_exact_pone.json --dealer scratch/issue187_exact_dealer.json --output /tmp/exact-second.json --workers 8 --seed 42
python -m scratch.pegging_depth_cost counts --pone scratch/issue187_exact_pone.json --dealer scratch/issue187_exact_dealer.json --second /tmp/exact-second.json --output /tmp/depth-counts.json --workers 8
python -m scratch.pegging_depth_cost benchmark --pone scratch/issue187_exact_pone.json --dealer scratch/issue187_exact_dealer.json --second /tmp/exact-second.json --output /tmp/depth-timing.json --workers 8 --keys 200 --seed 42
python -m unittest test_pegging_research
```

The root unittest loader collects all 39 research tests in ordinary CI.
Independent small physical-draw oracles compare conditional gains with full
real games and compare information-set support with explicit opponent sets.
A non-empty installed second-card book is measured inside complete real games.
Serial/spawned results agree. Real go/reset games establish reconstruction and
forced-action exclusion. Frozen report hashes and parent fingerprints are
validated before use. Seven isolated mutations fail by assertion: ignored frozen
reply, ignored second-card weights, dead second-card key, one consistent hand,
ignored go actors, wrong card number and an incorrect JSON join. The independent
serialization check verifies the byte estimate. The spelling dictionary adds Python's real
`sys.getsizeof` function name used for memory measurement.

Full required repository validation, explicit research lint/spelling, focused
regressions and the README smoke run are recorded under `/tmp/issue187-exact/`.
Complete integer second-card evidence, per-hand cost counters, timing rows and
mutation replacements are retained in `scratch/`. No later decision book,
workflow dispatch, immutable legacy edit, published format, qualifications,
release changes or Pone opening re-optimization occurred.
