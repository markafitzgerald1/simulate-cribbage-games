# Reported marginal uncertainty sidecars

Issue #137 exports statistics already saved in the full artifacts. Export does
not import either generator or the legacy simulator, invoke training or
dampening, resume, or sample. Issue #139 publishes the exported sidecars from
CI; trainer integration remains a separate decision, and the client means
assets remain byte-for-byte unchanged.

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

## Publication

Each generation workflow exports its sidecar in the same job that writes the
table, immediately after generation, and its `release-artifact` job attaches
the full table, the client means, and the sidecar to the rolling release in a
single call. Publication is therefore atomic: the release cannot hold a sidecar
derived from a table other than the means beside it. A downstream job that
re-derived the sidecar from already-published assets would have the opposite
property — it would ship a sidecar built from the previous tables at exactly
the moment the tables changed, which is when the mismatch matters.

The export step carries no event condition, so it also runs on `pull_request`
against that run's own bounded artifacts. The bounded crib run
(`--samples=300 --max-generations=1`) writes the same `se`, `n` and `sum_w2`
accumulators the production run does, and exports the same 9,076 records; the
bounded play run (`--hand-limit=4`) exports its 8. Each export takes well under
a second, so the production publication step runs on every pull request rather
than first on a weekly cron. Each step also records the client means digest
before and after the export and fails if those bytes moved, and fails if the
sidecar carries no measured records.

`.github/workflows/export-uncertainty.yml` is a `workflow_dispatch`-only
backfill, not a second production path and not a test of one. It downloads the
assets currently attached to the rolling releases, re-exports, and attaches the
sidecars to the same tags without regenerating a table. Use it to land sidecars
for tables generated before this publication path existed, and to re-export
after a fix to the exporter. It shares the generation workflows' per-tag
concurrency groups so it cannot interleave with a scheduled run replacing the
same assets, and by default it checks each downloaded client means file against
the digest pinned in its matrix. A dispatch after a regeneration has
legitimately replaced those bytes must turn that check off.

## Version 2 crib JSON contract

This section specifies the wire format for the follow-up exporter and readers.
This contract and its fixtures land before the v2 exporter and Python reference
reader; those implementations follow in separate changes. The export commands
and publication behavior above remain version 1.

Version 2 is the marginal sidecar for the version 4 crib estimator. Select the
decoder by `schema`. Version 1 remains the format for version 3 crib and for
play. The v2 schema is `expected-points-uncertainty.v2` and its table is `crib`.

V2 retains the v1 crib identity lists and ordering and the
`record_groups.totals` envelope. Production shadow data has 9,076 identities.
A bounded table may contain fewer. Each measured identity has these fields.

| Field | Meaning |
| --- | --- |
| `mu` | Finite, unrounded measured mean. The producer’s Python `round(mu, 4)` must match the corresponding client mean. |
| `reported_marginal_se` | Finite, nonnegative standard error of the measured estimator conditional on the frozen opponent policy. |
| `n` | Integer count of independent vector rows per active stream, at least two. |

The estimator projects joint integer moments within each active stream and
combines the stream contributions to obtain the marginal variance. The count
is neither a weight sum nor the sum across streams. V2 omits `sum_w2`.
The standalone exporter uses completed measured state and checks the displayed
means against the exact matching client file. Publication additionally requires
a verified terminal bundle.

The exact byte digests are lowercase SHA-256 hex. `means_sha256` binds the
sidecar to its client JSON, and `source_full_sha256` identifies the uncompressed
full JSON even when distributed as gzip. The following fields are required in
`provenance`.

| Field | Value |
| --- | --- |
| `generation_method` | `artifact_pipeline.generate_table.v4` |
| `estimator_contract` | `shared-rank-relation-v1` |
| `relation_centering_contract` | `uniform-two-card-rank-completion-v1` |
| `selector_contract` | `legacy-suit-sensitive-first-max-v1` |
| `rng_contract` | `python-random-sample-v1` |
| `sample_unit` | `independent-vector-rows-per-active-stream` |
| `policy_sha256` | Lowercase SHA-256 hex of the frozen opponent policy |
| `bootstrap_sha256` | Lowercase SHA-256 hex of the bootstrap input, or null when no external bootstrap file was supplied |
| `generation` | Nonnegative integer generation index |
| `seed` | Integer seed, or null for a run initialized with a nonce |

The standalone exporter omits `convergence_shift` when the full JSON lacks
it. A publication workflow with verified assembly diagnostics can include
the measured shift as a finite nonnegative number. When the full source has
a pre-cut report, include the nonnegative integer counts
`precut_resolved_positive`, `precut_resolved_negative` and `precut_unresolved`
derived from its row statuses. Additional scalar provenance fields are allowed.
Exclude checkpoint moments, policy snapshots and their null placeholders.

Every integer field (`n`, `record_count`, `generation`, `seed` and the
pre-cut counts) is a JSON integer that is also a JavaScript safe integer,
meaning its magnitude is at most 9007199254740991, so the Python and
browser readers describe one wire format. `seed` may be negative; `n` is
at least two and the other counts are nonnegative. A producer must refuse
to emit, and a reader must reject, an integer outside that range.
A sidecar with zero records is well formed but offers no capability, and
the trainer updater refuses to install one.

The paired means JSON must carry a `__metadata__` object with
`generation_method`, `generation` and `seed`. Each must have the same type
and value as the sidecar's provenance field, including a null seed, and the
means `generation_method` must be `artifact_pipeline.generate_table.v4`.
The reference reader and the byte-aware updater reject a missing object or
any difference, even when the means digest matches. A browser parser that
receives only parsed sidecar data relies on that upstream check.

- `statistic` is `reported_marginal_se`.
- `n_semantics` is `independent-vector-rows-per-active-stream`.
- `uncertainty_scope` is `fixed-policy-sampling`.
- `cross_bucket_covariance`, `policy_uncertainty`, `selection_adjustment` and
  `calibrated_comparison_uncertainty` are required JSON nulls.
- `qualifications` has nonempty `crib` and `scope` strings describing the
  fixed-policy sampling scope, the lack of a coverage claim and the
  comparison-specific nature of twin-difference SE.

The integer `record_count` equals the number of entries in `records`.
Each entry names a root or retained relation identity in the paired means.
The Python reference reader checks the producer rounding rule.
Reject an unsupported schema or table, a mismatched means digest where exact
bytes are available, or a malformed document or record. Keep a missing record
unavailable, including a missing relation record whose root is present. Keep
a measured zero. Unknown separate record groups may be ignored. A linear
comparison can still use the sum of absolute combined coefficients times
their marginal SEs as a dependence bound conditional on the frozen policy.

The [golden fixture directory](../artifact_pipeline/fixtures/crib-uncertainty-v2)
contains the exact client bytes and the expected marginal sidecar for a retained
seed-42 run of the 3–8 group with four rows per active stream. The fixtures
cover root and suit-relation identities without depending on the shadow run.

## Version 1 JSON contract

Crib export requires the explicit generation method
`artifact_pipeline.generate_table.v3`. Version 4 needs a v2 sidecar: its
unit-weight vector counts and joint moments cannot be labelled as legacy
weighted marginal statistics. Unknown or missing crib generation methods fail
before output is written. Play export is unchanged.

The UTF-8 document has `schema: "expected-points-uncertainty.v1"`, `table`
(`crib` or `play`), `source_full_sha256`, `means_sha256`, and `provenance`.
Provenance retains every scalar item from the full artifact's metadata;
snapshots, policy tables and training histories are excluded. In particular,
play retains its policy fingerprint and `joint_policy_converged: false`.
Play documents from enforced generation also retain `measured_policy`
(`trained` or `legacy-heuristic`) and `discard_policy_fingerprint`; readers
accept an absent `measured_policy` but reject one that disagrees with
`policy_fingerprint`: `legacy-heuristic` exactly when both seats carry the
legacy heuristic's fingerprint, `trained` otherwise. When `measured_policy` is
present, readers also require a valid non-empty `discard_policy_fingerprint`.

`statistic` is `reported_marginal_se`. Crib `n_semantics` is `sum_weights`;
play uses `simulation_count`. `cross_bucket_covariance`, `policy_uncertainty`
and `calibrated_comparison_uncertainty` are explicitly `null`, meaning
unavailable, never zero or independent. Textual `qualifications` preserve the
estimator and policy limitations alongside the numbers. Only its keys
(`crib`, `play`, `scope`) are part of the wire contract: a reader requires
every key present with a non-empty string value, but does not pin the exact
wording, so clarifying a qualification's text does not orphan previously
published sidecars or reject newly published ones from an older reader.
Adding, removing, or emptying a key is still rejected, because that would
mean a consumer received a sidecar stripped of one of these statements.

`keys` lists the client keys in rank order — the order of `RANKS`
(`"A23456789TJQK"`), not lexicographic (ASCII) order. Ten is spelled `T`, so
rank order runs ace, two, ..., nine, ten, jack, queen, king; a reader
searching the array for `"10"` will not find it, and lexicographic order
would instead sort the digit ranks before `"A"` and place ten last, after
`"K"`. The published client table's own key order is rank order and is
verifiably not `sorted()`: it begins `A_A_Unsuited, A_2_Suited,
A_2_Unsuited, A_3_Suited`, which lexicographic order would not produce. A
crib key orders its two ranks by `RANKS` position, then `Suited` before
`Unsuited` when both exist; a play key orders its four ranks the same way.
`roles` is
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

For v1, always use the top-level measured crib bucket corresponding to the
client mean.
`generation_accumulators` is a frozen policy snapshot and also lacks nested
relations. For `A_A_Unsuited/Dealer/A`, the full measurement mean is
7.749001108447055; snapshot `policy_mu` is 7.740845299442242. Neither the snapshot
nor dampened values describe the published measurement.

Version 1 crib `n` is a sum of weights, not hands simulated. With `W=n` and
`Q=sum_w2`, the stored marginal moments reconstruct as:

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
