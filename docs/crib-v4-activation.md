# Draft crib v4 activation and v3 restore

Preparation, publication and restore each require a fresh, separately
approved dispatch on main. The publish dispatch names the successful
preparation run on the same commit. The first activation also requires the compatible trainer
reader and the verified D9 prerelease. The old v3 workflow keeps manual
artifact generation and bounded PR coverage. It has no rolling release job.
The v3 restore operation uses the exact archived v3 bytes.

Before publication, confirm no historical writer run is queued or in flight
across any ref: both the v3 crib artifact workflow
(`generate-crib-artifact.yml`, formerly named Generate Crib Artifact)
and Export Uncertainty Sidecars (`export-uncertainty.yml`), including its
historical crib backfill. Keep historical scheduled and manual runs from both
workflows out of the retry path. GitHub reruns use the original workflow
definition and ref, so this change cannot retroactively disable those writers.

The activation path calls the read-only eight-shard shadow workflow. It pins the
archived v3 reference and approved runtime inputs, preserves the 0.10 gate, then
requires the approved SHA-256 of the rebuilt client bytes. Its final job exports
the marginal v2 sidecar, attaches the verified assembly shift, and compresses
the full JSON. The sidecar's source digest identifies the uncompressed full
file. The runtime inputs are the SHA-256 digests of `.python-version` and
`requirements.txt`. They were re-approved for CPython 3.14.10 in #231. A test
keeps the `.python-version` digest current, so a Python bump re-pins it in
review. Dependency bumps are left to merge without a re-pin: a stale
`requirements.txt` digest stops preparation at this first check, before any
sampling, and the operator re-approves the current dependencies then.

The reusable sampler checks manual dispatch, main, attempt 1 and explicit
`prepare` confirmation before bootstrap and each measurement wave. A standalone
shadow dispatch requires its own `shadow` confirmation on main, attempt 1.
Sampling has a separate concurrency group. Cancellation of a run in progress
is disabled, but a pending dispatch in a group is still replaced by a newer
one. Only
publish and restore hold the shared release writer lock, so preparation does
not delay a separately approved restore.

Before its first write, the publish job requires exactly the three pinned
v3 assets in uploaded state, with the archived digests. It uploads the gzip
without overwriting an asset and verifies the staged gzip and all three v3
assets before replacing the client pair. It verifies the resulting digests
and removes the superseded v3 full asset.

The release action deletes an existing asset and then uploads its
replacement, so each replaced asset briefly does not exist. It also updates
the release body before any upload, so a failed run can leave a body that
disagrees with the assets. Readers check means pairing by
digest. A failed gzip upload leaves the v3 client pair in place. If an upload
or cleanup leaves an incomplete asset set, inspect the release and use a
separately approved fresh restore dispatch before trying publication again.
Reruns of activation preparation cannot start sampling, and reruns cannot
publish.

The rollback preparation job validates the v3 full, client and sidecar hashes
before the restore job runs. It attaches all three, verifies their
uploaded digests, and removes any v4 full asset. Preparing the rollback
locally reproduced the original v1 sidecar byte for byte. The D9 prerelease
stores that sidecar separately because the reference ZIP contains only the
v3 full and client files.

Never delete the D9 prerelease `crib-v4-shadow-41771033920`: restore reads the
archived sidecar and reference from it, and deleting it makes restore
impossible. Keep a local copy of the three archived v3 files as well. Digests
are pinned, so tampering fails closed.

The weekly v3 schedule stays live on main until this change merges. Re-check
the live v3 digests immediately before publishing; the publish preflight check fails
closed if they changed, and a restore would then return to the pinned 2026-11-01
bytes, not to newer ones.

Publish and restore run in the `crib-release` GitHub environment, limited to
`main` and requiring a reviewer's approval for each run. The environment gates
only jobs that name it, so a branch copy of the workflow that drops the
`environment:` line would still receive `GITHUB_TOKEN` write access. Closing
that needs the release-writing credential stored as a secret in the
environment, which is not done while the repository has one maintainer;
revisit it when anyone else gets write access or an agent gets push rights
without review.

A publish job that is waiting for environment approval can hold the release
lock, so a restore dispatched meanwhile queues behind it. Reject or cancel the
waiting publish, confirm it has ended, then approve the restore. Never approve
the obsolete publish only to unblock the restore. A rejected or expired
approval makes no release write, and a rerun is a new attempt that the guards
refuse, so recovery always needs a fresh dispatch.
