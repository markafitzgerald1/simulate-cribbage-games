# Reported marginal uncertainty sidecars

Issue #137 exports statistics already saved in the full artifacts. Export does
not import either generator or the legacy simulator, invoke training or
dampening, resume, or sample. Publication and trainer integration are separate
decisions. Existing release workflows and client means remain unchanged.

## Export and inspect

Download a full artifact and its matching `.client.json` from each rolling
release. Keep those inputs separate from the output directory. For example,
with downloaded inputs in `inputs/` and an existing `dist/uncertainty/` directory:

```sh
python -m artifact_pipeline.export_uncertainty --table crib \
  --full inputs/expected_crib_points.json \
  --means inputs/expected_crib_points.client.json \
  --output dist/uncertainty/expected_crib_points.uncertainty.json
python -m artifact_pipeline.export_uncertainty --table play \
  --full inputs/expected_play_points.json \
  --means inputs/expected_play_points.client.json \
  --output dist/uncertainty/expected_play_points.uncertainty.json
python -m scripts.measure_uncertainty \
  dist/uncertainty/expected_crib_points.uncertainty.json \
  dist/uncertainty/expected_play_points.uncertainty.json
```

The exporter checks every client mean against the corresponding full mean
rounded to four decimal places, including category means, without rebuilding
the client files. It hashes the exact input bytes and rejects an output path
that aliases either input. All writes go to the requested sidecar path. Tests
assert that both client JSON files retain their exact bytes, including unusual
whitespace, and prohibit generator/simulator imports during the CLI test.

`decode_sidecar(sidecar_bytes, means_bytes)` is the reference Python reader.
It validates the schema, means digest, identities, counts and statistics.
Malformed JSON, duplicate object names, unsupported versions, invalid numeric
values, unexpected keys/roles/ranks/slots and mismatched means are errors.
Consumers should turn a missing or rejected sidecar into an unavailable
capability, not a measured zero. A rolling-release race must not combine a new
means file with an old sidecar.

## Version 1 JSON contract

The UTF-8 document has `schema: "expected-points-uncertainty.v1"`, `table`
(`crib` or `play`), `source_full_sha256`, `means_sha256`, and `provenance`.
Provenance retains every scalar item from the full artifact's metadata;
snapshots, policy tables and training histories are excluded. In particular,
play retains its policy fingerprint and `joint_policy_converged: false`.

`statistic` is `reported_marginal_se`. Crib `n_semantics` is `sum_weights`;
play uses `simulation_count`. `cross_bucket_covariance`, `policy_uncertainty`
and `calibrated_comparison_uncertainty` are explicitly `null`, meaning
unavailable, never zero or independent. Textual `qualifications` preserve the
estimator and policy limitations alongside the numbers.

`keys` lists the client keys in lexicographic order. `roles` is
`["Dealer", "Pone"]`. Crib `ranks` is
`["A", "2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K"]`;
play uses an empty list. Crib `slots` lists `total`, `matching_discard_suit`,
`non_matching_discard_suit`, `matching_rank_1_suit`, `matching_rank_2_suit`;
play uses `delta`. A record identity is `key/role/rank/slot` for crib or
`key/role/delta` for play. These named identities are independent of object
iteration order; readers must not invent another hand enumeration.

`record_groups.totals` contains `record_count` and a `records` object mapping
identities to named numeric fields. Each record contains
`reported_marginal_se`, `n`, and, for crib only, `sum_w2`. For example:

```json
{
  "A_A_Unsuited/Dealer/A/total": {
    "reported_marginal_se": 0.023563883578079117,
    "n": 11461.568181821294,
    "sum_w2": 6360.283574380505
  }
}
```

No rounding, integer conversion of crib weights, or fitted dispersion model is
used. A missing crib `sum_w2` in the full schema defaults to `n`. Missing
statistics, `n < 2`, and an unsupported weighted variance denominator omit the
record. Supported measured `se=0` remains an available zero. A missing relation
record does not authorize root uncertainty for a relation-based mean.

Version-1 readers must ignore unknown header/record fields and unknown named
record groups. Future category records belong in a separate group, such as
`record_groups.categories`, with its own count and records. They must not be
appended to `totals`, change its identities, or change its count. This is the
additive extension boundary: an unchanged version-1 reader still reads the
original totals even when category records arrive. A test exercises that
extension with the existing reader. Incompatible changes to existing fields
require a new schema.

## Meaning and consumer boundaries

Crib exports 4,394 root rank totals and the 4,682 relation totals retained by
the client means lookup. The six known cards change starter-rank weights and
suit availability, so #627 needs these inputs even for collapsed total rows;
338 pair/role scalars cannot represent that lookup. Relations remain limited
to suited discards and discarded Jacks. Root and relation records overlap and
are alternative lookup representations, not independent observations to add.

Play exports 3,640 keyed-player delta records for #725. The delta's own SE
preserves the own-minus-opponent pairing in each simulation. Do not reconstruct
it by summing the two player-total variances. There are no category, player-total
or per-action uncertainty records. #774 and #11 can reuse these inputs but do
not gain a calibrated combined mistake threshold from publication alone.

Always use the top-level measured crib bucket corresponding to the client mean.
`generation_accumulators` is a frozen policy snapshot and also lacks nested
relations. For `A_A_Unsuited/Dealer/A`, the full measurement mean is
7.749001108447055; snapshot `policy_mu` is 7.740845299442242. Neither the snapshot
nor dampened values describe the published measurement.

Crib `n` is a sum of weights, not hands simulated. With `W=n` and `Q=sum_w2`,
the stored marginal moments reconstruct as:

```text
sum = W * mu
sum_squares = reported_marginal_se^2 * W * (W - Q / W) + W * mu^2
```

The saved data lack cross-bucket products and squared-weight residual moments.
The stored weighted SE formula has not been established as calibrated sampling
uncertainty. Publishing `Q` does not fix that limitation. No replay, additional
accumulation or new sampling design is authorized here.

Comparisons must combine coefficients by artifact identity and record identity
before subtracting candidates. Reusing the same play entry cancels exactly.
Distinct play entries have independent final samples conditional on the frozen
policies; their delta variances can then be added. This excludes policy-learning
uncertainty and model error, and is not a paired alternative-action experiment.

For crib, the actual comparison variance needs the missing covariance matrix.
`sum(abs(coefficient) * reported_marginal_se)` is only a dependence bound within
the reported marginal-error model, not a demonstrated calibrated bound for the
weighted estimator. Summing squared marginal errors assumes missing covariance
away. Neither establishes calibrated #774 suppression. #135's projected 0.00132
twin-difference SE is specific to its shared-baseline design; it is not a global
crib noise floor.

Trainer loaders/updater changes remain separately scoped. They must preserve
means-only recommendations while uncertainty is absent, use explicit `null`
checks that retain numeric zero, and defer fetching sidecars until after the
first recommendation renders. Publication here does not implement classification,
queue/chart/tally changes, confidence thresholds, historical decision rewrites,
or the trainer's absence/loading/network tests.

## Measured format choice

On the September 13, 2026 release inputs, exported on September 20:

| Payload | Raw bytes | Gzip level 9 bytes |
| --- | ---: | ---: |
| Crib means, unchanged | 1,433,106 | 165,572 |
| Play means, unchanged | 1,378,134 | 190,091 |
| Combined means before first recommendation | 2,811,240 | 355,663 |
| Crib JSON uncertainty | 1,707,943 | 263,592 |
| Play JSON uncertainty | 467,975 | 53,952 |
| Combined JSON uncertainty, deferred | 2,175,918 | 317,544 |
| Crib packed binary candidate | 225,961 | 153,357 |
| Play packed binary candidate | 81,552 | 34,911 |
| Combined binary candidate, deferred | 307,513 | 188,268 |

Choose JSON. Binary saves 129,276 compressed bytes (126.2 KiB, 40.7% of the
JSON sidecars), but that deferred saving does not justify opaque git blobs and
a binary decoder for every consumer. JSON retains named, readable records,
full numeric precision and ordinary textual diffs. No binary assets are shipped.
The measurement script constructs the design's packed header, masks and
binary64 records only in memory, including the same provenance/qualifications
for a fair comparison. It is an experiment, not a second supported format.

The added JSON is 77.4% of the current raw means payload; after both sidecars
arrive the total is 4,987,158 raw bytes or 673,207 gzip bytes. The amount needed
before the first recommendation remains the existing 2.7 MB of means, exactly
2,811,240 raw bytes. These are reproducible compression measurements with
`mtime=0`, not production Content-Encoding or measured browser traffic. Actual
trainer loading order and loader/descriptor bundle cost still need validation
in that repository's separate implementation.

Full source SHA-256 digests:

- Crib: `a0464f8c805f782c27040bb366e0775455cd2fa02eb5e458d70bb0e6b9c69666`.
- Play: `3e3f59a7267551e771663f73fff87e1fb2515fa733ac0b441c00de092620b120`.

Matching client means SHA-256 digests:

- Crib: `4cd8a9258d32973710361b9c2a764aea3b8c9a1178ab53e1c2aa38a53e030cc1`.
- Play: `7420b1804f64a32a73edb2fcc7fe9f53fe427510755c8b2b3723142e503cca5c`.

Generated outputs follow the existing repository convention of local build
artifacts under `dist/`, rather than committed production tables. The commands
above reproduce them from the matching release inputs; exporting does not
upload or publish them.

## Regression checker limits

For this export-only change, the requested `scratch/verify_upgrade.py` runs
with the same pinned Python 3.14.4 environment in both interpreter positions.
No Python or dependency upgrade is part of this change. The checker compares
ten existing cases in isolated workspaces: exit status, normalized stdout and
stderr, and the tiny generated crib JSON. It runs small test simulations and a
tiny test generation independently of the exporter and production artifacts.

A pass establishes repeatability of those cases in that environment. Both
sides use the current source; it is not a before/after source regression proof,
does not compare all generated files, and does not exercise the new exporter.
It proves neither estimator calibration nor production convergence. Dedicated
export tests provide the input-preservation and sidecar-contract evidence.
