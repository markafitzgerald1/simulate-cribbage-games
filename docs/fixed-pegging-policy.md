# Fixed six-layer pegging measurement

`python -m artifact_pipeline.measure_fixed_play_table` measures a supplied
rank-only mixed policy in **both** seats through the existing Python v3
physical-card sampler, paired accumulators and opening-line observations.
It does not train, refine discards, load previously measured statistics or
call native code. This is an internal producer input contract, not a published
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
manifest; parent traversal and absolute names are rejected. Inputs must remain
immutable during measurement. The reader maps files read-only and verifies the
same opened bytes.

The probability file is little-endian unsigned 16-bit action counts. Offsets
are little-endian unsigned 32-bit action indices, one per optional row. Rows
are ordered by role (Pone then Dealer), canonical original own four ranks,
and ascending packed public history. Each row's counts sum to 1,000 and its
stored action menu must equal the actual legal ranks when used. Zero-mass
choices are never selected; pure distributions consume no random draw.

`menus` is an array of component descriptors with `role` and `own_hand` (sorted
zero-based ranks, Ace=0 through King=12). Each file contains 19-byte records,
`<QI4B3B`: packed history, the parent record's index in the file (unused here),
four action bytes (the legal ranks ascending, zero padded), layer (0 through
5), width (2 through 4) and the action index taken at the seat's previous
decision (0 when there is none). The loader checks only that the last byte is
below 4.
History uses low-to-high nibbles: rank+1, go=14, reset=15. Forced menus need
no row. Missing shards/histories use the immutable
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
training prior and the crib table's opponent. The population comes from the
CFR prior generator's refinement (#234), which has not converged; that is a
chosen input, not a claim that the discard/pegging loop settled. Its
fingerprint is pinned from the generation run that produces it, never from
local files.

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

## Bounded validation and release

Run `python -m scripts.run_fixed_play_smoke` locally to exercise the real
multiprocess CLI, writers and companion decoders with portable synthetic inputs.
The bounded play workflow runs the same command on pull requests. The fixture
covers 21 keeps and both roles at 25 samples, including live mixed-policy calls;
it is not an approved production input bundle or a promotion-gate result.

`examples/fixed-play-inputs.json` holds the input pins. Its two values are
set together from one `bundle-cfr-inputs.yml` run: that run's id, and the
`policy_manifest_sha256` it printed in its job summary. That workflow bundles
the outputs of one finished `generate-cfr-inputs.yml` run, named by its id,
after checking the run and matching the downloads to its recorded digests.
The manifest binds the
policy, offsets, menus, support, prior and discard population, so no other
digest is committed. Every pin must come from such a run, never from local
files. Pins attest bytes, not scientific correctness. The CLI itself never
downloads inputs.

`python -m artifact_pipeline.bundle_fixed_play_inputs --work DIR --prior-dir DIR
--output DIR` builds that bundle. It reads the CFR input generator's work folder
(`menus/<k>.bin`, `offsets.bin`, `policy.bin`, `support.bin`) and the prior
folder (`prior.bin`, `population.json`), copies every component into the empty
output folder, and writes `policy.json` with sorted keys and fixed separators,
so the manifest digest depends only on the component bytes. It refuses a
population that does not report `converged: false`, then loads the bundle once
at full size and prints the manifest digest.

The manual workflow `measure-fixed-play.yml` measures the table from those
pins and publishes nothing. It runs only from main, on the first attempt, with
the approval input `measure`, and its token can only read. It uploads the
table, its companions and the gate summary as `expected-play-points-fixed`.
If it fails or runs out of time it tries to upload its complete cells instead,
as `fixed-play-unfinished`; nothing resumes them automatically. Dispatching it
needs Mark's approval.

`publish-fixed-play.yml` publishes one finished `measure-fixed-play.yml` run to
the rolling `expected-play-points` release. It never measures. It is manual,
main-only and first-attempt-only, with the approval input `publish`, and it has
no schedule. The run is the `MEASUREMENT_RUN` named in the workflow.
`examples/fixed-play-release.sha256` pins the four files from that run and
`examples/fixed-play-release.md` holds the release notes. Change all three
together, only from one such run, and never pin a table measured locally.
The [lines-only migration](pegging-lines.md#re-export-and-rollback) records its
replacement lines digest separately. The fixed-play publisher requires a v2
bundle under the current verifier.

Its first job has a read-only token. It requires a reviewer on `play-release`
whom an administrator cannot bypass, because Actions gives a job that names a
missing environment an unprotected one. It checks that the named run is a
successful first attempt of the measurement workflow on main, downloads that
run's artifact, and matches it to the committed digests. `python -m
scripts.verify_fixed_play_bundle` then recomputes both companions from the full
table; with `--release-samples 13000` it also requires every canonical cell, its
approved sample count, a passed enforced gate, truthful model limits, and zero
missing-menu and off-support decisions. The release notes must quote the
measured gate result. Last, it keeps the assets and notes the release held
before as the artifact `expected-play-points-previous`, for 90 days.

Its second job waits for the environment's approval. It downloads the artifact
again, matches the digests again, attaches the four files in one
`action-gh-release` call, and checks that the release holds exactly those files
with those digests. Replacing four files is not atomic: if that call fails part
way, dispatch the workflow again. To go back instead, download
`expected-play-points-previous`, upload its four tables with `gh release upload
expected-play-points --clobber` and restore its notes with `gh release edit
expected-play-points --notes-file release-notes.md`. The app vendors its table,
so nothing reads the release until someone updates that copy.

The run shares the `expected-play-points-release` concurrency group with
`generate-play-artifact.yml` and the sidecar backfill, from its first check
until the end of its publication. `generate-play-artifact.yml` has no schedule,
so it cannot replace the fixed-policy table with a rollout-trained or heuristic
one by itself; a manual run on main replaces it only with `replace_release`.
Every job that can write the release waits for the `play-release` environment. A
re-run keeps its original workflow file and a dispatch uses the one on its
branch, so never re-run or dispatch either of them from before this change.

Resuming a measurement across jobs and a larger precision schedule are
subsequent work. Merging, dispatching, publishing and vendoring each need
separate authorization; local measurement and YAML linting authorize none of
them.
