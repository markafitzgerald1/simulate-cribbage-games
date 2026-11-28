# Typical first-exchange pegging lines

`expected_play_points.lines.json` accompanies the play means and uncertainty
sidecar. It describes the same frozen policy's first exchange: Pone's opening
card and Dealer's first response.

## Version 2 compact JSON contract

The UTF-8 file is minified onto one line with a trailing newline. Header fields:

- `schema`: `expected-play-lines.v2`.
- `means_sha256`: SHA-256 of the exact accompanying client means file bytes.
- `ranks`: `A23456789TJQK`; rank indexes are zero-based into this string.
- `roles`: `["Pone", "Dealer"]`, in this order.
- `columns`: `[["lead", "n", "mu", "se"],
  ["lead", "n", "mu", "se", "responses"]]`.
- `precision`: `{"mu_decimals": 3, "se_significant_figures": 2}`.
- `provenance`: `generation_method`, `seed`, `policy_fingerprint` and
  `joint_policy_converged` from the final frozen-policy measurement. `seed` is
  required and must be a non-boolean JSON integer. The play generator always
  uses an integer seed (default 42); unseeded, null and nonce forms are not
  supported. Documents from `--promotion-gate=enforce` runs also carry
  `measured_policy`: `trained`, or `legacy-heuristic` when the trained policy
  failed the promotion gate and both seats were measured with the legacy
  heuristic, and `discard_policy_fingerprint` of the measured keeps. Readers
  accept their absence, which is how older and report-mode documents look, and
  reject a value that disagrees with `policy_fingerprint`: `legacy-heuristic`
  exactly when both seats carry the heuristic's fingerprint, or an invalid
  discard policy fingerprint when `measured_policy` is present.
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
observed are present. `lead` is an integer rank index and `n` is its sample
count. Dealer's `responses` is an array of `[rank, count]` pairs in strictly
ascending rank order. Each rank occurs at most once and belongs to the keyed
hand. Counts are positive safe JSON integers and sum to the lead's `n`. `mu` and `se` are the conditional delta
mean and its sample standard error, respectively. An example entry:

```json
[
  [[0,3,2.0,2.3],[1,1,null,null],[2,1,null,null]],
  [[8,3,-1.333,3.5,[[0,2],[1,1]]],[9,2,0.0,0.0,[[2,1],[3,1]]]]
]
```

V2 excludes later exchanges, traces, hidden hands, suits, board positions,
per-response point means and distributions, action comparisons, optimality
claims, confidence thresholds, browser simulation and trainer loading/display.

Re-exporting the pinned fixed-play release produced 885,219 minified bytes and
270,797 gzip level-9 bytes. Its v1 file was 721,119 minified bytes and 239,250
gzip bytes. Sizes vary with the observed ranks and counts.

## Migration from version 1

V1 stored `response` and `response_n` as the last two Dealer columns. The
trainer's v1 `parsePegLines` returns `null` for the entire v2 document at the
schema check, so opening lines for both roles are unavailable if it receives
v2. The v1 updater rejects the v2 schema before vendoring. Existing trainer
builds use their bundled v1 asset. Update the reader and updater in
[cribbage-trainer#1001](https://github.com/markafitzgerald1/cribbage-trainer/issues/1001)
before approving publication. The old updater validates all three play files
before writing any of them, so v2 lines would block the whole play refresh.

## Meaning for consumers

For Pone, the rows describe the keyed hand's own opening leads. For Dealer,
lead ranks describe the sampled opponent's opening leads. In both cases `mu`
is the **whole-hand** keyed player's pegging points minus the opponent's,
conditional on that opening lead. Dealer's mean includes **every** simulation
with the lead, including responses other than the mode. It is not a mean
conditional on the mode too, nor the points scored in just the first exchange.

The published policy is a `PolicyMixture` of two policies at a fixed training
weight. A split in lead or response frequency can reflect that blend, not
equilibrium mixing; see
[#183](https://github.com/markafitzgerald1/simulate-cribbage-games/issues/183).
When `measured_policy` is `legacy-heuristic`, both seats play the
deterministic legacy heuristic, which picks a lead from Pone's own cards
alone, so each Pone key shows one lead.

Dealer publishes every observed reply, including those with count one and
those in thin lead cells. Ties use rank order, like all other counts. Consumers
can sort by frequency and fold rare replies for display. These counts describe
how often the policy played each reply.
Every card has count at most ten, so a Dealer response always exists; there is
no opening "go" category.

Derive frequencies from the counts instead of shipping redundant fields:

- Lead frequency: `n / sum(n over all rows for that role)`.
- Response frequency: pair count divided by `n` for that Dealer lead.
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
counts, response order and totals, finite moments and thin-cell nulls. Keys must follow canonical rank
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
including lead and response counts and conditional moments.

`--lines-output` overrides the companion path; it must differ from the full
and client output paths. Write client means first, hash those exact on-disk
bytes, then write the minified companion. Report minified bytes and reproducible
gzip level-9 bytes (`mtime=0`). Publish the companion, means and uncertainty
sidecar in a single rolling-release publication call.

## Re-export and rollback

[Re-export play opening lines](../.github/workflows/reexport-play-lines.yml)
rebuilds v2 from the pinned rolling release using `python -S -m
artifact_pipeline.play_lines`. The exporter verifies the play sidecar by
rebuilding it from the exact full table and means bytes. The read-only job
checks the [v2 pin](../examples/reexport-play-lines.sha256), prints the digest
in its log and run summary, and keeps the v1 asset as `previous-play-lines`
for 90 days.
After approval in `play-release`, the writer checks the downloaded file
against the checked-in pin, verifies the v1 release, replaces the lines
asset, and checks the resulting four assets. The resulting release uses the
three full, means and uncertainty digests from the
[fixed measurement manifest](../examples/fixed-play-release.sha256) and the
lines digest from the v2 pin. The manifest still identifies the original
measurement bundle. A fresh re-export dispatch expects the original v1 release
and will refuse a release that already has v2 lines.

For an authorized rollback, download `previous-play-lines` from the migration
run and verify the v1 lines digest in the fixed measurement manifest. Check
that the other three released files still match that manifest, then run the
following command from the directory containing the recovered asset.

```sh
gh release upload expected-play-points expected_play_points.lines.json \
  --repo markafitzgerald1/simulate-cribbage-games --clobber
```

Verify all four release assets against the fixed measurement manifest after
upload. Restore v1 manually because the current fixed-play publisher requires
v2 lines. Keep a copy of the v1 asset if rollback may be needed after the
Actions artifact expires.
