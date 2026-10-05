# Typical first-exchange pegging lines

`expected_play_points.lines.json` accompanies the play means and uncertainty
sidecar. It describes the same frozen policy's first exchange: Pone's opening
card and Dealer's first response.

## Version 1 compact JSON contract

The UTF-8 file is minified onto one line with a trailing newline. Header fields:

- `schema`: `expected-play-lines.v1`.
- `means_sha256`: SHA-256 of the exact accompanying client means file bytes.
- `ranks`: `A23456789TJQK`; rank indexes are zero-based into this string.
- `roles`: `["Pone", "Dealer"]`, in this order.
- `columns`: `[["lead", "n", "mu", "se"],
  ["lead", "n", "mu", "se", "response", "response_n"]]`.
- `precision`: `{"mu_decimals": 3, "se_significant_figures": 2}`.
- `provenance`: `generation_method`, `seed`, `policy_fingerprint` and
  `joint_policy_converged` from the final frozen-policy measurement. `seed` is
  required and must be a non-boolean JSON integer. The play generator always
  uses an integer seed (default 42); unseeded, null and nonce forms are not
  supported.
- `qualifications`: non-empty `policy`, `statistics` and `missing` statements
  that consumers can quote. They describe observed frozen-policy behavior,
  exclude optimality and alternative-action claims, exclude policy-learning
  uncertainty from SE, and explain unavailable statistics.
- `keys`: canonical kept four-rank keys, each sorted internally, with the list
  in rank order. For example, `A_A_A_A` precedes `A_A_A_2`; order uses the rank
  string, not ASCII sorting.
- `entries`: array parallel to `keys`. Each entry is `[pone_rows, dealer_rows]`.

A complete run has 1,820 keys and two roles. Bounded runs may contain a subset.
Each role's rows ascend strictly by observed opening rank. Only ranks actually
observed are present. `lead` and `response` are integer rank indexes; `n` is
the lead's sample count, and `response_n` is its modal response's count.
Counts are exact positive integers. `mu` and `se` are the conditional delta
mean and its sample standard error, respectively. An example entry:

```json
[
  [[0,3,2.0,2.3],[1,1,null,null],[2,1,null,null]],
  [[8,3,-1.333,3.5,0,2],[9,2,0.0,0.0,2,1]]
]
```

V1 excludes later exchanges, traces, hidden hands, suits, board positions, per-response means/distributions, action comparisons, optimality claims, confidence thresholds, browser simulation and trainer loading/display.

One bounded all-key run measured 497,557 minified bytes and 123,409 gzip level-9
bytes; production size can vary.

## Meaning for consumers

For Pone, the rows describe the keyed hand's own opening leads. For Dealer,
lead ranks describe the sampled opponent's opening leads. In both cases `mu`
is the **whole-hand** keyed player's pegging points minus the opponent's,
conditional on that opening lead. Dealer's mean includes **every** simulation
with the lead, including responses other than the mode. It is not a mean
conditional on the mode too, nor the points scored in just the first exchange.

With the default `--policy-averaging=geometric`, each update nests a
`PolicyMixture` of the prior policy and the
new tabular response, with weights 0.5 and 0.5. These nests persist across outer
iterations and the final training pass. With six updates per role (the current
production settings), explicit component weights are newest response 1/2,
then 1/4, 1/8, 1/16, 1/32, 1/64, and the initial legacy heuristic 1/64.
Each decision draws afresh, including within nested mixtures; it does not pick
one policy for the whole hand. A tabular response also falls back to its prior
policy at an unsupported information state, so effective action probabilities
depend on table coverage. A split in lead or modal-response frequency reflects
this behavior, not established equilibrium mixing; see
[#183](https://github.com/markafitzgerald1/simulate-cribbage-games/issues/183).

The opt-in `--policy-averaging=uniform-hand` instead averages complete response
strategies: each role independently samples one of its stored components at
the start of the hand and retains it throughout. History contains the legacy
heuristic plus every response across outer iterations and the final pass, with
equal mass per **top-level** component (seven per role at current production
training settings). This is not equal effective mass at each decision: table
misses route through prior averages toward earlier components and the legacy
heuristic. No burn-in is applied. A response's unsupported states use
its frozen prior average: fallback components are also sampled once before the
hand, retained for that hand, and never reselected at each decision. The trace
keeps these latent draws for continuation rollouts, preserving the component
distribution conditional on the observed history instead of drawing afresh
from the unconditional average mid-hand. Training forces one rollout per action
in this mode, even when a larger count is requested. Once the trace components
are frozen, the complete-state continuation is deterministic; repeating it
adds cost and duplicates observations without adding information. Each sampled
decision/action contributes once to its statistics, rather than inflating `n`.

The opt-in `--policy-averaging=geometric-hand` uses the same complete-component
sampling and frozen fallback rules, with geometric top-level weights instead
of uniform weights. At the default update weight, the newest response has mass
1/2, the preceding response 1/4, and so on; with six updates the oldest response
and legacy each have mass 1/64. This isolates hand-level correlation from the
weighting change. Both hand modes force one rollout per action. Top-level
weights still do not describe effective action mass after table misses.

Per-decision equal weights would not implement this strategy average: at later
information states, behavioral averaging requires each component's own reach
probability. Sampling a complete strategy avoids that calculation; see
[Heinrich, Lanctot and Silver (2015)](https://proceedings.mlr.press/v37/heinrich15.html).
Our rollout responses remain approximate and sparse, so this sampling rule
does not establish fictitious-play convergence or optimality in this model.

Dealer publishes one modal response rank and its observed count per lead.
Resolve count ties by canonical rank order. That tie-break is presentation,
not evidence that one tied response is better. A response with count one still
appears. Do not derive response-conditional means from these records.
Every card has count at most ten, so a Dealer response always exists; there is
no opening "go" category.

Derive frequencies from the counts instead of shipping redundant fields:

- Lead frequency: `n / sum(n over all rows for that role)`.
- Modal response frequency: `response_n / n` for that Dealer lead.
- Plug-in frequency SE: `sqrt(p * (1 - p) / denominator)`, using the role total
  for a lead and that lead's `n` for a response. With denominator below two,
  the frequency SE is unavailable. This is not a confidence interval or
  calibrated small-sample accuracy claim.

Every observed lead is published, including thin cells. With `n < 2`, `mu`
and `se` are both explicitly `null`; the count remains available. A missing
rank is unobserved and unavailable, not measured zero. An empty role array,
missing key/file, or rejected pairing is also unavailable. Measured zeros with
`n >= 2` remain numeric zero. Always test null explicitly rather than truthiness.

Means are rounded to three decimal places (nearest, ties to even), with at
most 0.0005 points of rounding error. Rounded mean zeros have a positive sign,
including negative means that round to zero. SEs are rounded to two significant
figures, which preserves positive tiny SEs instead of rounding them to zero
with a fixed number of decimals. JSON need not retain trailing zeros. Precision
applies only to this companion; client means and checkpoint statistics retain
their existing precision. Counts and frequency denominators are never rounded.

`decode_lines(lines_bytes, means_bytes)` in
[`artifact_pipeline/play_lines.py`](../artifact_pipeline/play_lines.py) is the
reference reader. It checks the schema, exact-byte pairing, declared
columns/precision, required qualifications,
frozen-policy provenance, hand/role identities, row widths, legal ranks,
counts, finite moments and thin-cell nulls. Keys must follow canonical rank
order, and each role's rows must ascend strictly by lead. Non-object documents
and malformed containers are rejected with `ValueError`, like all other
parse/validation failures; the capability is unavailable. This verifies the
digest pairing, not numerical agreement with the means. Hash file bytes before
parsing or serializing again: a whitespace-only means change still rejects the
pairing. Readers must use `keys`, `roles` and `columns`, rather than inventing
an independent enumeration.

## Generation invariants (for simulator maintainers)

`simulate_pegging` records only the first two actual selected ranks in its
result. It does not replay, force, reselect, or consume extra randomness. The
same returned complete-hand delta feeds both the play mean and its observed
opening-lead cell. Publication uses only the final measurement pass and final
policy fingerprint.

Full-table entries retain unrounded online conditional moments and response
counts under `opening`. Checkpoints store the second central moment directly,
so resuming never reconstructs it from rounded published SEs. Generation method
v4 also saves raw moments for every absolute-seat scalar and rejects older
checkpoints. Missing lead/response counts cannot be filled in from whole-hand
means. Seeded resumed sampling matches uninterrupted sampling,
including lead counts, modes and conditional moments.

`--lines-output` overrides the companion path; it must differ from the full
and client output paths. Write client means first, hash those exact on-disk
bytes, then write the minified companion. Report minified bytes and reproducible
gzip level-9 bytes (`mtime=0`). Publish the companion, means and uncertainty
sidecar in a single rolling-release publication call.

## Pone lead quality gauge

Every written companion is validated against the exact client bytes and measured
by `measure_quality` in `artifact_pipeline/play_quality.py`. The generation log
prints its JSON report, and the workflow carries that report into release notes.
This diagnostic does not change the lines schema or qualifications.

Defaults are a minimum of 100 samples per lead and z >= 3. An eligible key has
at least two Pone leads meeting that count. Its most frequent lead uses count
first, then canonical rank order for ties. A key is flagged if any qualifying
alternative has a positive mean gap and
`gap >= 3 * sqrt(se_mode**2 + se_alternative**2)`. Both SEs come from the
published conditional cells; a positive gap with both SEs zero is flagged,
whereas equal means are not. Dealer rows do not enter the gauge.

`flagged_share` uses eligible keys as its denominator. `keys_total`,
`keys_eligible`, and `keys_flagged` expose coverage; with no eligible keys the
share and gain summaries are null, not zero. `observed_samples` counts all Pone
samples, while `eligible_samples` counts qualifying leads in eligible keys.
Thin, rare, absent and single-lead cases cannot demonstrate policy quality.

For each eligible key, gain is the largest qualifying lead mean minus the
count-weighted mean of qualifying leads. It describes the observed mixture
**restricted to those leads**, not the complete mixture when rare leads are
excluded. The report gives the equal-key mean, population standard deviation
and maximum of these gains in points. Keys are not weighted by deal frequency.
The spread describes variation across keys, not uncertainty in the mean gain.

Pone's initial per-decision draw is independent of the hidden opponent deal
given its kept ranks. This supports within-policy opening-lead diagnostics;
Dealer's observed opponent lead does not randomize its own response. The z rule
is an approximate screening criterion, with rounded published moments and no
multiple-comparison correction. Selecting the best observed mean biases gain
upward. Neither statistic proves optimality, exploitability, head-to-head
strength, policy-learning accuracy, or the effect on the full discard decision.
Compare matched settings and report eligibility alongside any apparent gain.

For the opt-in whole-hand average, the opening draw is still independent of the
hidden deal, but the continuation is correlated with the component that chose
the lead. For a given keep, a component's lead is usually deterministic, so
lead groups are largely component groups; several components can share a lead,
and unsupported lead states can route through the frozen fallback. Its gauge
compares **whole observed lines**, not alternative leads
followed by a common continuation. The formula and thresholds stay unchanged;
cross-method differences are descriptive policy/line diagnostics, not a causal
estimate of replacing only the opening card. Qualifications text is unchanged.


## Paired promotion gate

After the final training pass and before final artifact measurement,
`--promotion-gate=report` (the default) evaluates the trained policies against
`LegacyHeuristicPolicy`. It logs the result and adds `promotion_gate` to the
full artifact metadata, without changing the policies measured. `off` skips
the evaluation. `enforce` measures both seats with the legacy heuristic when
the trained policy's both-seat advantage is not positive at z >= 3. Metadata
records both trained and measured fingerprints and the policy selected; the
ordinary artifact and lines fingerprint identifies the policy actually measured.
Enforced legacy checkpoints also retain a `training_context_fingerprint` of
the trained policies and the opponent-discard mapping. Resuming rejects a
different or missing context: identical legacy policies do not imply identical
conditional sampling populations.
Failed enforcement rebuilds discard refinement with the selected heuristic
before final measurement, as described below. Lines qualifications are unchanged.

Scheduled and dispatched production generation explicitly uses
`--promotion-gate=enforce --workers=4`, shipping heuristic-generated deltas when
promotion fails. This overrides the CLI's `report` default only in the production
step; the other production settings and bounded PR command are unchanged.

The default is 200,000 independent physical eight-card deals, sampled without
replacement from four copies of each rank, then split into two four-card keeps.
This is a uniform keep population, rather than the artifact's discard-policy
conditional population. `--promotion-gate-deals` overrides the count for bounded
checks; at least two deals are required when enabled. The default count targets
SE near 0.01 points or smaller, but the actual SE is always reported.

Each deal is played three times with the same play RNG seed: legacy versus
legacy, trained Pone versus legacy Dealer, and legacy Pone versus trained
Dealer. The Pone advantage is its trained delta minus the reference Pone delta;
the Dealer advantage is its trained delta minus the reference Dealer delta.
The both-seat advantage **per hand** is their average, not their sum. Estimate
its SE from these per-deal averages to retain paired covariance. Processes
return raw pairs in deal order so estimates are reproducible across worker
counts. Gate randomness is separate from training and artifact measurement.
A positive mean with zero SE passes; a zero mean does not. These SEs condition
on the frozen policies and exclude learning uncertainty. Passing on uniform
keeps does not prove superiority in the artifact population or optimality.

The experiment runner observes table hits and terminal legacy selections inside
measurement workers and reduces the returned counts in the parent. Observation
preserves scores, openings and RNG state. Terminal-legacy share divides terminal
legacy selections by all card selections (table hits plus terminal legacy).
Coverage counts unique stored states separately from actual decision usage.
When resuming, usage counts cover newly measured samples only.

For paired gauge comparisons, request `include_key_statistics=True` from
`measure_quality`. Compare the intersection of eligible **keys**, retaining each
policy's own qualifying leads. This matches the seed-43 comparison in issue
#187; it does not impose common lead support. McNemar's signed screening z is
`(baseline_only - variant_only) / sqrt(baseline_only + variant_only)` without a
continuity correction. Estimate the SE of the mean gain difference from paired
per-key differences, rather than combining marginal spreads. Whole-hand lead
groups remain largely component groups, so these comparisons describe complete
lines rather than isolated opening-card changes.

The experiment runner defaults to one worker unless `--workers` is supplied;
`experiment.json` records `resolved_workers` and effective arguments. This is
separate from the generator CLI's process CPU default. Enabled promotion gates
reject fewer than two deals during parsing, before analytical solving or
training.

For direct response fitting with hand strategies, inspect the resolved trace's
continuations, including sparse fallbacks and either asymmetric seat arrangement.
Built-in legacy/tabular continuations that are deterministic in both seats use
one rollout per action. Stochastic mixtures and unrecognized custom components
retain requested repeats; sampling a component does not prove its internal
selector is deterministic. The production geometric observation stream is
retained. Both hand-mode warm starts reject per-decision mixture fallbacks.

When enforcement selects legacy, discard refinement restarts from the saved
analytical solution with heuristic play fixed in both seats. It uses the same
policy-table samples, seed, workers, outer-iteration cap, and two-consecutive-step
convergence test as the trained outer loop. Final measurement uses those refined
keeps and the same heuristic. `joint_policy_converged` then describes this
fallback refinement, which may remain false at the configured cap.

Enforce-only `promotion_gate.discard_refinement` records the method, pegging
policy/fingerprint, actual discard fingerprint, analytical initialization,
convergence, and refinement iterations. Top-level `outer_iterations` retains the
original training history. Passing enforcement records the existing trained
refinement history; the final trained IBR still follows that refinement. Failed
enforcement rejects resumes without matching training and actual refinement
identities, including pre-fix fallback checkpoints. Report/off artifacts retain
their previous bytes. The gate's paired evaluation and qualifications are
unchanged.
