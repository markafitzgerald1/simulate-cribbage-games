# Draft crib v4 activation and v3 restore

Preparation, publication and restore each require a fresh, separately
approved dispatch on main. The publish dispatch names the successful
preparation run on the same commit. The first activation also requires the compatible trainer
reader and the verified D9 prerelease. The old v3 workflow keeps manual
artifact generation and bounded PR coverage. It has no rolling release job.
The v3 restore operation uses the exact archived v3 bytes.

Before publication, confirm no historical writer run is queued or in flight
across any ref: both Generate Crib Artifact (`generate-crib-artifact.yml`)
and Export Uncertainty Sidecars (`export-uncertainty.yml`), including its
historical crib backfill. Keep historical scheduled and manual runs from both
workflows out of the retry path. GitHub reruns use the original workflow
definition and ref, so this change cannot retroactively disable those writers.

The activation path calls the read-only eight-shard shadow workflow. It pins
the archived v3 reference and approved runtime inputs, preserves the 0.10
gate, then requires the approved SHA-256 of the rebuilt client bytes. Its
final job exports the marginal v2 sidecar, attaches the verified assembly
shift, and compresses the full JSON. The sidecar's source digest identifies
the uncompressed full file.

The reusable sampler checks manual dispatch, main, attempt 1 and explicit
`prepare` confirmation before bootstrap and each measurement wave. A standalone
shadow dispatch requires its own `shadow` confirmation on main, attempt 1.
Sampling has a separate concurrency group with cancellation disabled. Only
publish and restore hold the shared release writer lock, so preparation does
not delay a separately approved restore.

Before its first write, the publish job requires exactly the three pinned
v3 assets in uploaded state, with the archived digests. It uploads the gzip
without overwriting an asset and verifies the staged gzip and all three v3
assets before replacing the client pair. It verifies the resulting digests
and removes the superseded v3 full asset.

GitHub replaces rolling assets individually. Readers check means pairing by
digest. A failed gzip upload leaves the v3 client pair in place. If an upload
or cleanup leaves an incomplete asset set, inspect the release and use a
separately approved fresh restore dispatch before trying publication again.
Reruns of activation preparation cannot start sampling, and reruns cannot
publish.

The restore job validates the v3 full, client and sidecar hashes before
the write job runs. It attaches all three, verifies their
uploaded digests, and removes any v4 full asset. Preparing the rollback
locally reproduced the original v1 sidecar byte for byte. The D9 prerelease
stores that sidecar separately because the reference ZIP contains only the
v3 full and client files.
