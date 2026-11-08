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
  --samples 13000 --seed 42 --hand-limit 4 --promotion-gate report
```

The serial command writes full, client means, opening lines and uncertainty
using their existing schemas. The exporter hashes the exact written means.
An enforced failed gate aborts; it cannot refine replacement discards while
claiming to measure the supplied fixed model. Report mode records the unchanged
safety gate without changing observations. Gate selections are excluded from
measurement counters. Multiprocessing, resumable generation, fetching inputs
and release-workflow activation are separate work. Do not treat this command
as a byte-identical resume implementation.

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
but does not rederive support. The input producer and its support/prior
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
is the nonconverged two-by-200 heuristic refinement, fingerprint
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
