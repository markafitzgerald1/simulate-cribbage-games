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

The published policy is a `PolicyMixture` of two policies at a fixed training
weight. A split in lead or modal-response frequency reflects that blend, not
equilibrium mixing; see
[#183](https://github.com/markafitzgerald1/simulate-cribbage-games/issues/183).

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
v3 rejects older checkpoints; missing lead/response counts cannot be filled in
from whole-hand means. Seeded resumed sampling matches uninterrupted sampling,
including lead counts, modes and conditional moments.

`--lines-output` overrides the companion path; it must differ from the full
and client output paths. Write client means first, hash those exact on-disk
bytes, then write the minified companion. Report minified bytes and reproducible
gzip level-9 bytes (`mtime=0`). Publish the companion, means and uncertainty
sidecar in a single rolling-release publication call.
