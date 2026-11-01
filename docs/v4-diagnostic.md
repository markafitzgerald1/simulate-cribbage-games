# First v4 runner diagnostic

This manual workflow implements the November 1 amendment to issue #135. It is
separate from both production workflows and has no release permission or
publication step. Merging it authorizes no execution. Mark must separately
approve dispatch; no N=4,000 job was run to validate this PR.

The predeclared first shard is **3_8, 2_3, 7_8, 4_J, A_A**, serially in that
order. These retain the reported example, two residual contrasts, a Jack twin
and a same-rank control from the local pilot. Both roles and complete legal
twins are retained. The fixed target is 4,000 complete rows per active stream,
seed 42, one frozen policy, no transitions. There is no matrix, automatic next
shard, sampling-until-positive rule or new precision threshold.

## Inputs and recovery

The workflow retrieves existing full/client release assets by IDs 697897856
and 697897857, respectively. Before measurement it verifies the three digests
in [the pilot report](v4-pilot.md), including the canonical saved generating
policy, then loads `generation_accumulators` with `policy_mu`. It never passes
the full artifact through ordinary `--bootstrap`. Retrieval of these exact
assets and all three hashes was verified during implementation. If a rolling
release deletes an asset ID, retrieval fails: an operator must locate the same
bytes in an approved archive, or request an explicit replacement experiment.
Do not substitute the latest policy or create a release to bypass this failure.

CPython 3.14.4, estimator and centering contracts are checked explicitly. The
manifest pins source hashes for producer modules, diagnostic scripts, legacy
simulator and requirements. Every checkpoint retains the engine's runtime,
selector/RNG/deck contracts, source and frozen policy hashes, raw integer joint
moments and cumulative row indices. Shard selection never enters row seeds.

The `crib-v4-diagnostic-checkpoints` Actions artifact contains separate
`group-*.json` checkpoints, append-only progress logs, manifest and summary.
Retention is 30 days; preserve an approved archive before expiry if needed.
Never concatenate these files into a purported full checkpoint. To resume,
provide the prior diagnostic run ID through `resume_run_id`. A later dispatch
still requires its own authorization. The runner verifies the manifest and
each encountered checkpoint before reuse, skips sampling completed groups,
and resumes incomplete groups at their saved row indices. A changed producer,
input, seed, policy, target or runtime is incompatible. A deadline can leave
later groups unstarted or unvalidated; their prior files remain evidence, not
newly validated results.

## Time and evidence

The first step records a deadline 210 minutes after job start. The job has a
240-minute hard ceiling, including setup and upload, so the intended reserve
is 30 minutes. Sampling checks that deadline before a chunk and after each
complete row is constructed, before the engine commits its streams together.
The existing graceful-stop machinery writes the completed round atomically;
it does not depend on GitHub's hard termination to preserve local files.
An already expired deadline starts no sampling. Finish immediately when the
fixed target is reached. Setup/retrieval failure, runner loss, cancellation or
an exceptionally long operation can still prevent upload; the hard ceiling
cannot guarantee salvage after forced termination.

Cadence is 1,000 rounds per group and role, with additional final/interrupt
writes. Flushed JSON events record sampling rows and elapsed time including
writes, separate checkpoint projection/encoding/write time and byte size,
resume-validation time, total time and actual stream counts. Divide rows by
sampling time minus writes for throughput; selector calls are five per twin
round and two per same-rank round. Logs report per-role pre-cut means and twin
residual/flush/nobs/gap means and covariance-aware SEs, retaining cross-cut
covariance. Zero/one-row estimates may be unavailable. Checkpoints also retain
the per-cut measured views. These are fixed-policy diagnostics, not calibrated
comparison intervals or a crib-wide uncertainty floor.

The summary distinguishes complete, incomplete, failed and not-started groups;
errors propagate as job failures while `always()` attempts evidence upload.
The upload step reports compressed bytes, artifact digest and upload duration;
its start timestamp and uncompressed local bytes are also recorded. Combine
those logs with checkpoint events to assess storage/write/upload cost.
Upload itself cannot include its own final duration in the archive being sent.
Do not infer that a green job reached N=4,000: read `summary.json` and terminal
`status` events. Earlier logs in a resumed artifact describe earlier attempts.

## Human review and acceptance

Allow about 10 minutes. Read the workflow, runner's validation/resume boundary,
and the helper's deadline wrapper; skim the test fixtures. The estimator and
production workflows have no changes. Most operational risk lies in accepting
an incompatible input or losing an incomplete checkpoint, rather than in new
mathematics.

From a configured checkout, run:

```sh
python -m unittest test_crib_v4_diagnostic test_measure_crib_v4
```

Expected: all tests pass in seconds. The tests stop a real fixture run during
a row, verify equal active-stream counts, resume twin and same-rank groups,
and compare full checkpoint bytes with fresh runs. They reject changed
seed/policy/source metadata and direct/symbolic/hard-link writer aliases while
preserving input bytes. Coordinator tests cover failure/incomplete summaries,
strict manifests and the fixed serial shard. No runner dispatch is needed.

A separate small real-CLI acceptance check is in
[the pilot report](v4-pilot.md#review-and-acceptance). It should finish in
seconds and both byte comparisons should print nothing. It exercises the
actual full/client generator; it does not independently prove the estimator.
The hand-calculated covariance fixture is independent of the helper projection
arithmetic. Fresh/resume comparisons prove reproducibility, not unbiasedness.
The existing decomposition oracle remains the independent mathematical check.

Practical review risks: a wrong deadline loses time/state; verify the incomplete
fixture and upload's unconditional condition. A wrong pin changes the
experiment; inspect explicit asset IDs/digests and mismatch fixtures. Misread
SEs distort future budgets; retain the distinction between twin cancellation
and individual crib means. A subsequent survey/export reusing the same
validator is not independent validation. No human review is replaced by CI.

## Implementation validation record

The local validation passed: 370 root tests (five analytical tests intentionally
skipped there), 318 artifact tests, all five explicit analytical tests and 28
appended ratchet tests. The combined artifact/ratchet report is 100% statement
and branch coverage. Mypy, artifact pylint, legacy ratchet/similarities,
flake8, spelling, configured file hooks and Markdown review passed. No legacy
or production workflow source changed.

Tiny real CLI N=2 -> 4 and fresh N=4 full/client bytes matched; the helper also
matched fresh/resumed bytes under the downloaded pinned historical policy.
Both stderr files were empty. The same-interpreter upgrade checker passed all
ten cases within its two-minute bound; that is repeatability, not before/after
source compatibility, estimator calibration or runner performance.

Both independent reviews reached a clean final round. Their generation-zero
resume finding was first reproduced as a failing test, then fixed at the
diagnostic boundary. Other review improvements retain interrupted-chunk timing
and independently assert individual mean uncertainty. Named scratch mutations
were all rejected:

| Mutation | Regression that rejects it |
| --- | --- |
| Omit graceful stop request | Complete-round deadline/resume equality |
| Accept changed generation | Seed/policy/input/generation rejection with preserved checkpoint |
| Omit expected source digest | Valid existing-checkpoint source rejection |
| Omit expected policy digest | Policy rejection before output exists |
| Continue after incomplete group | Single-call incomplete coordinator summary |
| Drop B from individual means | Hand-calculated U/S means and SEs |
| Ignore resume manifest | Changed manifest and missing-manifest rejection |
| Omit failed-run summary write | Failure still leaves explicit incomplete summary |
| Omit temporary-path protection | Real CLI direct/symbolic/hard-link source preservation |

The diagnostic-only workflow was not dispatched. GHA throughput and actual
upload costs therefore remain unmeasured, for the separately approved first
execution. No full survey, production regeneration, publication or merge was
performed.
