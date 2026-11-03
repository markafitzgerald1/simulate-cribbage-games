# Eight-shard v4 shadow implementation

The [production-layout design](v4-production-layout.md) defines the model,
assembly contract and budget. `shadow-crib-v4.yml` implements its manual,
non-publishing stage. Merging it does not start sampling. Dispatch, retry,
activation, production publication and trainer changes need separate approval.
The existing v3 weekly workflow is unchanged.

## Data flow

`artifact_pipeline.crib_v4_shards` exposes four stages: `plan`, `measure`,
`assemble` and `finalize`. The production plan fixes all 91 groups, 169 keys,
both roles, seed 42, N=22,000, at most two generations, threshold 0.10 and
failure on non-convergence. Workers checkpoint every 1,000 complete rounds.
The plan pins code, workflow, dependencies, runtime, contracts and policy.

The initial job captures the v3 release record, downloads its recorded asset
IDs and verifies names, IDs, sizes and SHA-256 digests before solving the
analytical bootstrap. Full/client means must match and cover every canonical
key. A changed rolling tag cannot silently relabel different downloaded bytes.
Reference bytes and the captured release record remain diagnostic artifacts.

Two waves of eight workers each measure exactly one frozen generation. Only
assembly may transition the global policy. Every worker manifest is required,
including empty shards in tiny tests. The assembler checks group ownership,
counts, generation, seed, exact policy identity, contracts and moment validity
before producing a result. It reads moments, not displayed means or reports.
The final job validates terminal completion again and rebuilds full/client
output from the authoritative moments.

## Checkpoint commits and interruption

The worker's `manifest.json` is the atomic commit pointer. Its `files` maps
logical names such as `group-3_8.json` to exact content digests. Committed bytes
live at `snapshots/group-3_8-<digest>.json`. Resume verifies every referenced
snapshot's digest, contract, policy and moments before writing any data.
Never replace a saved digest with a freshly calculated hash of changed input.

The sampler writes in a fresh private working directory. It then creates an
immutable snapshot exclusively and atomically updates the manifest through a
unique temporary file. Only after the pointer commits may it remove obsolete
snapshots. A failed pointer update preserves the preceding committed snapshot;
an unreferenced new snapshot is ignored and can be reused on the next attempt.
Working files never supply resume state. Existing temporary aliases cannot
truncate checkpoint input because the writer uses fresh temporary paths.

Garbage collection retains only manifest-referenced snapshots after a commit.
This bounds ordinary retention to one checkpoint per group, with temporary
space for the current write, rather than retaining 44 copies per group.
Interrupted scratch directories are ignored and excluded from artifact upload.
Worker and bundle destination locks reject competing installers. A stale lock
requires explicit recovery after establishing the prior writer has stopped.

## Results and limits

A successful assembly bundle has `bundle.json`, exact file digests, the full
table, client means and `diagnostics.json`. An intermediate bundle also contains
`next-plan.json`. Identical reruns are no-ops; different existing bundles are
preserved and rejected. Failed validation, a resolved-negative pre-cut row or
non-convergence cannot create a successful terminal bundle.

Diagnostics retain actual counts, guard outcomes and the measured convergence
shift. The diagnostic event is emitted before the convergence decision, so a
failed run still retains its shift in the always-uploaded JSONL. Volatile
validation, checkpoint and stage timings are separate from deterministic bundle
identity. The final comparison includes all root key/role/cut means, named
maximum differences and empirical quantiles, plus the pre-cut twin gaps.
Same-rank groups and a common offset to both twins remain visible. Different
iterated policies may contribute to these descriptive differences; they are
not paired uncertainty, a bias proof or calibrated comparison uncertainty.

Each worker has a three-hour ceiling and a 150-minute graceful deadline.
Assembly and final jobs have two-hour ceilings. The approximate 18 runner-hours
of generation excludes validation, bootstrap, transfer and snapshot overhead;
the separately approved shadow run must measure those costs and convergence.
No production runtime or precision claim is established by the tiny tests.

No sidecar or release is published. D5 still requires v2 crib export and a
compatible trainer reader before activation. The eventual production final
job must build, export and publish the matching full/client/v2 files together.

## Review and practical checks

The risk is an incorrectly assembled table or lost resumable state. The focused
checks exercise both outcomes without dispatching or production sampling:

```sh
python -m unittest artifact_pipeline.test_crib_v4_shards test_v4_shard_workflow
```

Allow about 30 seconds locally. Expected: tiny seeded split runs equal a
monolithic two-generation run, including all joint moments and exact client
bytes; a real two-row group also matches; completed resumes add no samples;
foreign identities and incomplete counts fail; changed bytes and temporary
hard links preserve the saved inputs on rejection; interrupted pointer updates
resume without duplicate rows; conflicting bundles and locks fail closed.
Tests also expose shared-base offsets in absolute comparisons and retain the
measured shift on convergence failure. These are separate from calibration.

Review the six-job workflow's dependencies, matrices, limits, captured asset
IDs, failure uploads and read-only permissions. `actionlint` validates it
without dispatch. Runtime comparisons, GitHub cancellation/upload behavior and
production convergence remain for the separately approved shadow execution.
