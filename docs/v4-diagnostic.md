# First v4 runner diagnostic

This manual workflow implements the November 1 amendment to issue #135.
It has no production or publication step. Merging the workflow does not
approve dispatch; no N=4,000 diagnostic run was used to validate this PR.

The first shard is **3_8, 2_3, 7_8, 4_J, A_A**, serially in that order:
the reported pair, two residual contrasts, a Jack twin and a same-rank control.
Use both roles, complete legal twins, seed 42, one frozen policy and a fixed
target of 4,000 complete rows per active stream. There is no automatic next
shard, policy transition, sampling-until-positive rule or new SE threshold.

## Inputs and resume

The workflow first retrieves full/client release asset IDs 697897856 and
697897857. Weekly publication replaces IDs, so unavailable IDs fall back to
the same filenames on the rolling tag. **Every route must match the original
full, client and saved-policy hashes** in [the pilot report](v4-pilot.md).
Different bytes fail closed. Locate the original bytes in an approved archive
or request a replacement experiment; do not substitute a policy or create a
release to bypass the check. ID-route downloads and all three hashes were
verified; fallback retrieval was tested with network-free fixtures.

Measurement loads saved `generation_accumulators`, preserving `policy_mu`.
Ordinary `--bootstrap` would read displayed means and change the experiment.
The runner pins CPython 3.14.4, generation zero and estimator/centering
contracts. Its manifest also hashes producer modules, diagnostic scripts,
legacy source and requirements. Checkpoints retain the engine's complete
runtime/selector/RNG/deck contracts, source/policy hashes, raw integer joint
moments and row indices. Group selection never enters the row seed.

The Actions artifact `crib-v4-diagnostic-checkpoints` retains separate
`group-*.json` checkpoints, append-only progress logs, manifest and summary
for 30 days. Archive approved evidence before expiry if needed. Never
concatenate group files into a purported full checkpoint.

To resume, supply the prior diagnostic run ID through `resume_run_id` after
separate execution approval. Before download, the workflow requires a completed
manual run of this diagnostic in this repository, with the same head repository;
PR/fork/other-workflow runs are rejected. The runner checks its manifest without
rewriting it, validates encountered checkpoints, samples no completed groups,
and continues incomplete groups at saved indices. Changed producer/input,
seed, policy or runtime is incompatible. Groups beyond the deadline can remain
unstarted or unvalidated; restored files alone are not newly verified results.

## Deadline and evidence

The first step records a deadline 210 minutes after job start. The job ceiling
is 240 minutes including setup/upload, reserving 30 minutes for final evidence.
Finish at the sample target, even if the deadline coincides with its final row.
An expired deadline starts no sampling.

The helper checks before a chunk and after constructing a complete row. The
engine commits all active streams together, writes an atomic checkpoint, then
stops. SIGINT follows the same complete-round path and restores the previous
handler. Measurement uses `exec` so Python receives the step's signals.
This does not rely on hard termination to save runner-local files. Runner loss,
cancellation, setup failure or an exceptionally long operation can still
prevent upload; the four-hour ceiling cannot guarantee salvage.

Cadence is 1,000 rounds per group/role, with additional final/interrupt writes.
Flushed JSON events retain actual stream counts, rows/time including writes,
separate checkpoint projection/encoding/write time and bytes, resume-validation
time and total time. Throughput is rows divided by sampling time minus writes;
selector calls are five per twin round and two per same-rank round.

Logs report individual pre-cut means and twin residual/flush/nobs/gap means
and SEs with cross-cut covariance. Zero/one-row estimates can be unavailable.
Per-cut measured views remain in checkpoints. These are fixed-policy sampling
results, not calibrated intervals or a crib-wide uncertainty floor.

Read `summary.json` and terminal `status` events: a successful job can be
incomplete. Exceptions propagate as failures while `always()` attempts upload.
The step summary labels this attempt's outcome, so failed/skipped validation
cannot endorse an older restored summary. Earlier log entries describe earlier
attempts. Upload logs contain compressed bytes, digest and duration; the archive
contains upload start time, while the step summary records local bytes. An
upload cannot include its own completed duration inside the file being sent.

## Acceptance and review

Your code read is optional after clean adversarial review and practical checks.
If inspecting code, focus on workflow deadline/upload handling and the runner's
input/resume boundary; the estimator and production workflows are unchanged.
Run this from a configured checkout (seconds, no dispatch):

```sh
python -m unittest test_crib_v4_diagnostic test_measure_crib_v4
```

Expected: every test passes. Fixtures cover interrupted stream counts, final-row
completion, SIGINT, exact fresh/resume bytes, input/seed/policy/generation
rejection, source/output/temp aliases, manifest preservation and resume origin.
Workflow tests additionally exercise replaced asset IDs without network access.
The [pilot's optional CLI acceptance](v4-pilot.md#review-and-acceptance) should
also finish in seconds, with both full/client `cmp` calls printing nothing.

Fresh/resume equality proves reproducibility. The hand-calculated covariance
fixture and existing decomposition oracle provide independent arithmetic
checks; another exporter using the same validator is not independent proof.
Detailed validation, mutation evidence and named reviewer results are collapsed
in the PR description. Actual GHA throughput/upload cost awaits the separately
authorized first execution. No aggregate survey budget or merge is implied.
