# Fixed six-layer pegging measurement

`python -m artifact_pipeline.measure_fixed_play_table` measures a supplied
rank-only mixed policy in **both** seats through the existing Python v3
physical-card sampler, paired accumulators and opening-line observations.
It does not train, refine discards, load measured research statistics or call
native code. This is an internal producer input contract, not a published
browser policy format or an authorization to replace release assets.

```sh
python -m artifact_pipeline.measure_fixed_play_table \
  --policy-manifest inputs/policy.json \
  --policy-manifest-sha256 <approved-manifest-sha256> \
  --samples 13000 --seed 42 --workers 4 --hand-limit 4 \
  --generated-at 2026-10-12T16:00:00Z --checkpoint-dir dist/fixed-cells \
  --promotion-gate report
```

The command writes full, client means, opening lines and uncertainty
using their existing schemas. The exporter hashes the exact written means.
An enforced failed gate aborts; it cannot refine replacement discards while
claiming to measure the supplied fixed model. Report mode records the unchanged
safety gate without changing observations. Gate selections are excluded from
measurement counters. The CLI requires the approved manifest digest, which
transitively pins the policy, support, prior, menus and discard document.
The Python serial reference function remains available for comparisons.

## Input manifest

The UTF-8 JSON object has schema `six-layer-pegging-policy.v1` and integer
`probability_denominator: 1000`. Duplicate names are rejected. Components
`probabilities`, `offsets`, `support`, `prior` and `discard_population` carry
`file`, `bytes` and lowercase hexadecimal `sha256`. Files are relative to the
manifest; parent traversal and absolute names are rejected. Local symlinks can
refer to existing large research inputs. Inputs must remain immutable during
measurement. The reader maps files read-only and verifies the same opened bytes.

The probability file is little-endian unsigned 16-bit action counts. Offsets
are little-endian unsigned 32-bit action indices, one per optional row. Rows
are ordered by role (Pone then Dealer), canonical original own four ranks,
and ascending packed public history. Each row's counts sum to 1,000 and its
stored action menu must equal the actual legal ranks when used. Zero-mass
choices are never selected; pure distributions consume no random draw.

`menus` is an array of component descriptors with `role` and `own_hand` (sorted
zero-based ranks, Ace=0 through King=12). Each file contains 24-byte records:
`<QII8B`: packed history, unused training parent/offset fields, four action
bytes, layer (0 through 5), width (2 through 4), heuristic action index and
unused parent-action byte. History uses low-to-high nibbles: rank+1, go=14,
reset=15. Forced menus need no row. Missing shards/histories use the immutable
heuristic; a declared missing/corrupt file is an error, never a silent fallback.
The loader reconstructs the original own keep and validates count, sequence,
opponent card count, passed roles and actor from the complete public history.
It has no opponent cards or private discard information.

`prior` is a shaped 1,820 by 1,820 little-endian unsigned 64-bit training chance
matrix, bound by digest. It is provenance, not the measurement distribution;
the loader does not solve or certify its numerical weights. `support` has one
byte per optional row and integer `mask` 1 or 2. Its bits attest positive
opponent counterfactual reach under the saved rounded policy and that prior,
ignoring earlier own-action reach. The reader validates its shape/byte range
but does not recompute support. The input producer and its support/prior
relationship still require review.

`fallback` contains identity `legacy-heuristic-v1`, its existing policy
fingerprint and `source_sha256` of the immutable legacy Python file. The
behavioral fingerprint hashes probability/offset/menu/support/prior digests,
the support mask, fallback identity/source and encoding version; paths and
observer counters do not change it. The generic policy fingerprint function
recognizes this validated 64-hex behavioral identity.

`discard_population` additionally has `keep_fingerprint`, `converged: false`
and a nonempty `description` of its limits. Its JSON contains `keeps` rows
`[role, dealt_six_ranks, kept_four_ranks]`. There must be exactly every physically
possible six-rank hand in each role (18,395 each), no duplicates, invalid ranks
or unavailable kept cards. This frozen distribution can differ from the
training prior and the crib table's opponent. For the research candidate it
is the two-by-200 heuristic refinement that has not converged, fingerprint
`326f6541973eeb44d763f3efc4182f0884f77e6473013e3bef739c4c6856c720`;
that is a chosen input, not a claim that the discard/pegging loop settled.

## Provenance and counters

The actual Python generator records its v3 method, Python measurement backend,
`measured_policy: trained`, behavioral fingerprints for both roles, the frozen
keep fingerprint, input/prior digests and explicit limits. Both
`joint_policy_converged` and `discard_refinement_converged` are false. The
existing exporter retains these scalar fields. Paired delta SE excludes model,
prior and policy-learning uncertainty; more samples do not repair those limits.

Unlike `generate_play_table`, which writes `measured_policy` and
`discard_policy_fingerprint` only on enforced promotion-gate runs, this tool
writes both in every gate mode. It has no fallback model to substitute, and a
failed enforced gate aborts, so their presence says nothing about the gate
mode. Read `promotion_gate` for that; it is absent when the gate is off.

Counters are disjoint, in this order: forced, missing-menu fallback, off-support,
heuristic-equivalent, trained. "Trained" means positive saved opponent support
and a stored distribution differing from the heuristic; it does **not** mean
historical training reach was retained. Off-support likewise does not imply
never trained. Heuristic-equivalent means all probability is on the heuristic
card, not an actual missing lookup. The denominator is final-measurement
`select_rank` calls in both seats, including forced cards; automatic goes are
not policy calls and are excluded. Counts and shares are emitted as scalar
metadata. Use a context manager or `close()`; global mappings and the bounded
64-own-hand menu cache are released, and a closed policy rejects selection.

## Parallel completion and resume

`--workers` defaults to one. Spawned processes initialize their own validated
read-only mappings once and share filesystem pages through the operating system.
One worker owns every ordered observation in a key/role cell; worker identity
never enters the v3 entry/sample seed. The parent reduces in canonical rank and
role order, sums integer decision counters and writes the four artifacts once.
The caller supplies one timezone-qualified `--generated-at` value. With the same
inputs and timestamp, one, two, four and six workers emit identical full, client,
sidecar and opening-lines bytes. Worker counts and completion order are not
artifact metadata.

`--checkpoint-dir` requires that original timestamp. Its `run.json` binds the
manifest digest, behavioral and discard fingerprints, generation method, seed,
fixed sample count, sorted cell set, gate result, interpreter and producer code.
A changed input, timestamp, schedule or code rejects resume. This first version
cannot extend completed cells to a larger sample target; use a new directory.
It is an entry-owner coordinator, not a cross-job shard/merge interface.

Workers atomically replace complete `<keep>.<role>.json` files, each containing
its task identity, exact output statistics, raw opening moments, decision counts
and payload checksum. The parent validates every expected cell; unexpected,
duplicate, corrupt or incomplete final JSON files are errors. Unfinished
`.tmp-*` writes are ignored. A worker failure aborts and terminates its peers;
independently complete files survive. On the next run, only cells without a
completion file start again at sample zero on their original seed. No completed
row passes through `RunningStatistics.from_dict`, and no unordered floating
partials are combined. The OS file lock prevents concurrent directory owners and
is released when the parent exits, including crashes. This coordinator targets
Linux and macOS, which provide `flock`.

The JSON normalization step precedes checksum computation and reduction: integer
opening-response keys become strings and then sort in the same order as resumed
JSON. It changes no mean, standard error or raw moment. This distinction matters
for ten through king responses, where numeric and string order disagree.

## Bounded validation and release draft

Run `python -m scripts.run_fixed_play_smoke` locally to exercise the real
multiprocess CLI, writers and companion decoders with portable synthetic inputs.
The bounded play workflow runs the same command on pull requests. The fixture
covers 21 keeps and both roles at 25 samples, including live mixed-policy calls;
it is not an approved production input bundle or a promotion-gate result.

`examples/fixed-play-inputs.json` pins the current research candidate's manifest,
discard document, keep fingerprint and prior. These digests attest bytes, not
scientific correctness. Mark must review the input derivation and model limits,
approve an input-distribution workflow and materialize its files without local
research symlinks. The CLI itself never downloads inputs.

`examples/generate-fixed-play-artifact.yml` is an inert job definition outside
GitHub's workflow directory. It has no schedule. Before activation, Mark must
approve the pins and inputs, provide `FIXED_PLAY_INPUT_RUN_ID` for an approved
`fixed-play-policy-inputs` artifact, and configure required human reviewers on
`approved-fixed-play-release`. Its 330-minute generation job measures 13,000
samples per cell with four workers and an enforced promotion gate. Publication
also requires the explicit `authorize_release` input and the main branch.

The example repeats the existing same-job export and unchanged-means digest
check. It retains the offline Cribbage Pro gross-regression gate and records
that report before exporting the sidecar from the final full bytes. It uploads
the full/means/sidecar/lines bundle and uses the existing
`expected-play-points` tag, concurrency group and single `action-gh-release`
attachment boundary. `python -m scripts.verify_fixed_play_bundle` verifies the
exact means pairing and recomputes both companions from that full table. With
`--release-samples 13000` it additionally requires every canonical cell, its
approved sample count, a passed enforced gate and truthful model limits.
The release job repeats that check after download and before attachment.

The example's local complete-cell checkpoints are not retained across hosted
workflow jobs. Cross-job checkpoint transport, a larger precision schedule and
real runner throughput are subsequent work. Activating, dispatching, publishing
or vendoring the resulting bundle requires separate authorization. Local
measurement and YAML linting do not authorize those actions.
