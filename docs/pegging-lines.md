# Typical first-exchange pegging lines

Issue #176 publishes `expected_play_points.lines.json` alongside the play
means and uncertainty sidecar. It describes what the same frozen policy does
in the first exchange: Pone's opening card and Dealer's first response.
Every card has count at most ten, so a Dealer response always exists; there is
no opening "go" category. No code or action in this PR regenerates the published
release. Future scheduled generation publishes the new companion.

## Version 1 compact JSON contract

The UTF-8 file is minified onto one line with a trailing newline. Header fields:

- `schema`: `expected-play-lines.v1`.
- `means_sha256`: SHA-256 of the exact accompanying client means file bytes.
- `ranks`: `A23456789TJQK`; rank indexes are zero-based into this string.
- `roles`: `["Pone", "Dealer"]`, in this order.
- `columns`: `[["lead", "n", "mu", "se"],
  ["lead", "n", "mu", "se", "response", "response_n"]]`.
- `precision`: `{"mu_decimals": 3, "se_significant_figures": 2}`.
- `provenance`: generation method, seed, final policy fingerprint and
  `joint_policy_converged`. The capped production policy is non-converged.
- `qualifications`: non-empty `policy`, `statistics` and `missing` statements
  that consumers can quote. They describe observed frozen-policy behavior,
  exclude optimality and alternative-action claims, exclude policy-learning
  uncertainty from SE, and explain unavailable statistics.
- `keys`: canonical kept four-rank keys, stated once in rank order. For example,
  `A_A_A_A` precedes `A_A_A_2`; order uses the rank string, not ASCII sorting.
- `entries`: array parallel to `keys`. Each entry is `[pone_rows, dealer_rows]`.

A complete run has 1,820 keys and two roles. Bounded runs may contain a subset.
Each role's rows are sorted by observed opening rank. Only ranks actually
observed are present. Counts are exact integers. An example entry:

```json
[
  [[0,3,2.0,2.3],[1,1,null,null],[2,1,null,null]],
  [[8,3,-1.333,3.5,0,2],[9,2,0.0,0.0,2,1]]
]
```

For Pone, the rows describe the keyed hand's own opening leads. For Dealer,
lead ranks describe the sampled opponent's opening leads. In both cases `mu`
is the **whole-hand** keyed player's pegging points minus the opponent's,
conditional on that opening lead. Dealer's mean includes **every** simulation
with the lead, including responses other than the mode. It is not a mean
conditional on the mode too, nor the points scored in just the first exchange.

Dealer publishes one modal response rank and its observed count per lead.
Resolve count ties by canonical rank order. That tie-break is presentation,
not evidence that one tied response is better. A response with count one still
appears. Do not derive response-conditional means from these records.

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
most 0.0005 points of rounding error. SEs are rounded to two significant figures,
which preserves positive tiny SEs instead of rounding them to zero with a fixed
number of decimals. JSON need not retain trailing zeros. Precision applies only
to this companion; client means and checkpoint statistics retain their existing
precision. Counts and frequency denominators are never rounded.

`decode_lines(lines_bytes, means_bytes)` is the reference reader. It checks the
schema, exact-byte pairing, declared columns/precision, required qualifications,
frozen-policy provenance, hand/role identities, row widths, legal ranks,
counts, finite moments and thin-cell nulls. Parse/validation failure means the
capability is unavailable. Hash downloaded file bytes before parsing or
serializing again: a whitespace-only means change still rejects the pairing.
Readers must use `keys`, `roles` and `columns`, rather than inventing an
independent enumeration. Browser loading and display belong to the trainer.

## Generation, checkpoints and publication

`simulate_pegging` records only the first two actual selected ranks in its
result. It does not replay, force, reselect, or consume extra randomness. The
same returned complete-hand delta feeds both the play mean and its observed
opening-lead cell. Mixture, fallback and single-legal-rank selections all pass
through the existing hidden-information policy interface.

Full-table entries retain unrounded online conditional moments and response
counts under `opening`. Checkpoints store the second central moment directly,
so resuming never reconstructs it from rounded published SEs. Generation method
v3 rejects older checkpoints; missing lead/response counts cannot be filled in
from whole-hand means. Seeded resumed sampling matches uninterrupted sampling,
including lead counts, modes and conditional moments. The extra observations
also appear in intermediate policy tables but publication uses only the final
measurement pass and final policy fingerprint.

`--lines-output` overrides the companion path; it must differ from the full
and client output paths. The generator writes client means first, hashes those
exact on-disk bytes, then
writes the minified companion. It prints minified bytes and reproducible gzip
level-9 bytes (`mtime=0`). These are compression measurements, not browser
traffic measurements. The workflow validates the companion against its own
means on bounded PR generation, uploads it, and attaches it in the same existing
rolling-release publication call. No workflow dispatch is needed for this PR.
The uncertainty sidecar and its exporter contract are unchanged.

## Size and scope

The compact shape drops repeated object names, total counts, frequencies and
frequency SEs. It has at most 5,915 Pone lead rows and 23,660 Dealer lead rows
across all 1,820 keys. Each Dealer row carries only one response. Fixed numeric
precision keeps this shape near the requested 1 MB minified budget. Measure
actual generated output rather than assuming synthetic compression describes
sampled policies. A generated bounded run on October 3, 2026 used all 1,820 keys and both roles,
100 samples per role, seed 42, analytical iteration limits 2/1, one outer and
one IBR iteration, 25 training samples, one rollout per action and ten policy
samples. Its frozen policy was non-converged. Measured output:

| Payload | Minified bytes | Gzip level 9 bytes |
| --- | ---: | ---: |
| Generated first-exchange lines | 497,656 | 123,435 |

That output contains 1,854 Pone lead rows, 20,516 Dealer lead rows, and 2,623
thin rows. This measures the actual generated JSON; it is not a production
policy estimate. Larger samples may observe more leads and lengthen counts.
The complete shape remains bounded by the row counts above.

The trainer's source gate warns above 250 changed lines and fails above 400.
JSON artifacts count in full; a new minified one-line asset contributes one
addition, replacement contributes one addition plus one deletion. That is a
line budget, not a byte or parsed-memory budget. No production artifact is
vendored in this simulator PR. No sharding is introduced for v1.

Exclude later exchanges, full traces, hidden opponent hands, suits,
board-position strategy, per-response means or distributions, alternative-action
comparisons, optimality claims, confidence thresholds, browser simulation,
trainer loader/display changes, changes to existing client means, and changes
to the uncertainty contract. A modal-response-only summary cannot explain
whether the modal response is better than another response.

Tests use unequal counts and independently calculated positive/negative
whole-hand deltas. They exercise generator attribution, lead and response
frequency denominators, null versus measured zero, precision, policy calls and
random state, exact checkpoint moments, seeded resume, unchanged client bytes,
and digest rejection. Scratch mutation proofs target lead-count attribution,
conditional-mean attribution and digest verification. Per-response mean
mutation proofs are outside v1 scope.
