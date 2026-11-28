# Pegging policy shards

`python -m artifact_pipeline.export_policy_shards` splits the fixed six-layer
pegging policy described in [its input contract](fixed-pegging-policy.md) into
one small file per seat and original four-card keep, for a browser that plays
or reviews one hand at a time and so needs only two of them. It refuses a
manifest whose SHA-256 is not the approved one, or that the loader parsed
differently from the bytes hashed, and reads the bundle through
`SixLayerPolicy`, which checks the digests of the policy, offsets, support,
prior and menus. It does not read the discard population, which the shards do
not carry. The shards carry the stored policy only: no values, no fallback
and no opponent cards.

```sh
python -m artifact_pipeline.export_policy_shards \
  --policy-manifest inputs/policy.json \
  --policy-manifest-sha256 <approved-manifest-sha256> \
  --output shards
```

The manual workflow `export-policy-shards.yml` runs exactly that on the bundle
named by `examples/fixed-play-inputs.json`, the pins the measured table used,
and uploads the folder as the artifact `pegging-policy-shards`. It publishes
nothing. Dispatching it, publishing its output and vendoring it into the app
each need separate authorization.

## Files

The output folder holds `shards.json` and one file per own-hand menu, named
`<role>/<hand key>.bin.gz`, where the role is `pone` or `dealer` and the hand
key spells the four ranks ascending with `A23456789TJQK` joined by `_`, as
the app's play tables do (`dealer/6_9_T_K.bin.gz`). A keep whose every
decision is forced, the four of a kind, has no menu and no file.

`shards.json` is UTF-8 JSON with sorted keys and no spaces, ending in one
newline. It holds `schema` (`pegging-policy-shards.v1`), a `description` of
the policy's limits, `probability_denominator` (1000), the source
`policy_manifest_sha256` and `behavioral_fingerprint`, and `shards`: one
object per file in canonical seat (Pone then Dealer) and hand order, with
`role`, `own_hand` (zero-based ranks), `file`, `rows`, `bytes`, `sha256` of
the gzip file and `payload_sha256` of its decompressed bytes. The gzip
header's time is zero, so one zlib build gives identical files; another build
may compress differently, which `payload_sha256` lets a reader tell apart from
a content change.

## Payload

A decompressed shard is little-endian, column by column so that gzip sees
runs of similar bytes. With `n` rows:

| Bytes | Content |
| --- | --- |
| 4 | `CPS1` |
| 4 | `n`, unsigned 32-bit |
| 8n | each packed history minus the previous row's (the first minus 0) |
| 4n | each row's legal ranks, ascending, zero padded |
| n | each row's width, the number of legal ranks (2 to 4) |
| n | 1 when the row's support byte shares a bit with the manifest's mask |
| 2 per action | each row's counts, unsigned 16-bit, summing to 1000 |

Rows are the menu's rows in ascending packed history, so every delta after
the first is positive; histories use the menu's nibble packing (rank + 1, go
14, reset 15, oldest lowest). The counts section has no padding and the
payload has no trailing bytes. A reader looks up a decision by its history,
must check that the stored legal ranks equal the real ones, and draws a rank
with probability count / 1000. A history with a choice but no row is not in
the policy; the measurement played such a decision with the legacy heuristic,
and a reader must say so rather than invent a play.

Support means positive opponent counterfactual reach under the saved policy
and training prior, ignoring the seat's own earlier actions, as
[the input contract](fixed-pegging-policy.md) defines it; it does not mean
the row was trained or untrained. Under the solver's event rules, every
history at which the seat has two or more legal ranks among its first three
cards has a row, because a menu enumerates every feasible opponent hand. A
decision with one legal rank, or the fourth card, has no row and needs none. Measured on the bundle pinned by
`examples/fixed-play-inputs.json` (bundle run 45528665715), exported locally
in about four minutes: 3,614 shards holding 45,366,803 rows, 32,980,231 bytes
compressed in all; median 5,550 bytes, 95th percentile 27,588 and largest
64,022 (`dealer/9_J_Q_K.bin.gz`, 102,326 rows). A hand needs two shards. A
trial that pruned the rows a seat's own zero-count actions cannot reach saved
about 40%, but it drops the rows a review needs once a player leaves the
policy, so the export keeps every row.
