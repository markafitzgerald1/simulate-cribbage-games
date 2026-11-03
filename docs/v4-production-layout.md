# Version-4 sharded generation and assembly

OpenAI Codex, November 2, 2026. Design implementing Mark's
[D6 decision](https://github.com/markafitzgerald1/simulate-cribbage-games/issues/135#issuecomment-6591347660).
The [implementation guide](v4-shadow.md) documents the resulting boundaries.
This design authorizes no execution,
activation or production release. The existing v3 weekly workflow stays intact.

## Scope and fixed settings

The new layout measures all 91 rank groups (169 discard keys), both roles,
at 22,000 complete rows per active stream per generation, seed 42, at most
2 generations, convergence threshold 0.10 and failure on non-convergence.
Checkpoint cadence is 1,000 rounds per group/role. Neither shard membership
nor checkpoint cadence enters the row seed. No sample reduction buys time.

Eight workers measure one frozen policy generation. Assembly validates the
complete table before considering convergence or performing one policy
transition. A second eight-worker wave measures the new policy. The final
assembly must pass convergence and the pre-cut guard before its results can
be used. The generation-zero comparison cannot establish convergence against
a preceding measured generation; preserve the current engine's behavior.

The initial policy is the analytical bootstrap, using the existing production
solver settings. Later policies come exclusively from the engine's full-table
measured accumulators and existing dampening. Do not bootstrap from displayed
means, train independent policies within shards, or pool moments across policies.

## Generation plan

A versioned plan contains the canonical global requested keys, ordered rank
groups and eight-way partition; runtime, RNG, deck, selector, estimator,
centering and scale contracts; seed/randomness identity; full run controls;
generation; bootstrap digest; frozen policy payload and hash; and exact
producer/helper/workflow/dependency-file digests. Its identity is the SHA-256
of a canonical JSON payload, excluding the identity field itself. The workflow
also records its source commit and run identity in diagnostic provenance.

Use canonical rank order and a deterministic round-robin partition across eight
shards. This gives 11 or 12 groups per shard and spreads the cheaper same-rank
groups. The plan records the exact lists; no worker infers its own membership.
A test-only small selection may leave empty shards, which still require their
own manifests. The production command exposes no smaller group selection or
sample-budget override.

A group checkpoint has only that group's requested keys and both roles, under
the plan's exact policy, generation, seed and controls. The explicit local key
selection is the sole permitted identity difference from the global plan.
Because the row seed contains no requested-key list or shard number, splitting
work preserves the monolithic seeded observations exactly. There is no new RNG,
allocation, scoring or selection algorithm.

## Worker boundary and resume

Workers initialize from the plan's policy and empty group moments, or resume a
checkpoint proven to belong to that same plan and shard. They use the existing
complete-round engine and checkpoint writer. They sample one generation only:
never call the engine's automatic policy-transition loop on a partial table.
A completed group is revalidated without sampling additional rows.

Each shard manifest records its plan identity, shard ID, exact groups, completed
status and exact SHA-256 for every group checkpoint. Counts, labels, scale,
centers and stream allocation remain in the authoritative checkpoint. A saved
summary or displayed mean cannot substitute for those moments. The manifest
is a consistency record, not an authentication signature.

SIGINT and the declared deadline request a stop after a complete round and
retain the last valid checkpoint. Deadline checks occur between bounded chunks;
reserve time for final serialization and upload. Each worker gets a three-hour
job limit and a 150-minute sampling deadline, leaving 30 minutes for shutdown.
Upload diagnostics on failure as well as success. No automatic retry, extra
sampling wave or cross-run continuation is enabled. A later approved resume
must verify the same plan and artifact origin before restoring files.

## Assembly contract

Assembly consumes one immutable plan and exactly eight shard manifests. It
requires all 91 groups exactly once, both roles and every expected active
stream at count = next index = 22,000. Complete twins stay in one group;
same-rank groups have only the unsuited variant. It derives expected membership
from the plan, never from the first shard or the files that happen to exist.

Before writing any usable result, reject:

- Missing, duplicate or foreign shard IDs, groups, keys, roles or streams;
  altered membership, missing manifests and incomplete groups.
- Wrong plan identity, source-file digest, runtime, contract, scale, seed or
  nonce, bootstrap digest, generation, target or iterative controls.
- A foreign policy, even if its own payload and recomputed hash agree; the
  payload and hash must equal the plan's expected policy.
- Wrong labels, centering constants, malformed integer encodings, duplicate
  JSON keys, unequal stream counts, non-complete phases and impossible joint
  moments, including covariance with a negative quadratic form.
- A checkpoint whose bytes do not match its manifest, paths escaping the input
  directory, or output/temporary paths aliasing an input, including existing
  symbolic or hard links.

Use the existing v4 moment decoder and exact feasibility checks. Reconstruct
one canonical global state from validated group moments. Do not concatenate
arbitrary JSON, average shard means, reconstruct moments from displayed SEs,
reseed, resample or infer missing groups as zeros. Rebuild the table/client
using the existing projections. The producer pre-cut guard applies to every
completed generation and before any transition, including resumed pending
transitions. Unresolved rows do not fail; resolved-negative rows do.

Only this global state can call the existing convergence/transition functions.
Measured means and SEs stay separate from dampened policy values. A transition
constructs the next frozen policy once and resets every group's moments. A
rerun of assembly over identical inputs computes the identical result rather
than applying another transition to its own prior output.

Stage outputs in a fresh sibling directory, then atomically install a completed
bundle at a previously absent destination with a decision manifest and exact
output digests. Never replace a nonempty directory. An exclusive destination
lock serializes installers; acquire it without replacing an existing lock and
recheck the destination before installation. An already successful bundle with
identical plan, decision and every file digest is a no-op; any other existing
output fails closed without replacement. Interrupted staging is not a result;
readers ignore it. A stale lock requires explicit recovery, not automatic
removal of another writer's lock.

The bundle identifies success, generation and either a next plan or terminal
convergence. Rejected input must preserve existing output and every input file.
Diagnostic failure reports may be retained separately, but never carry a
successful completion marker. Readers validate that marker and digests before
consuming a bundle.

## Final job and publication boundary

The implementation PR adds a separate manual-only, non-publishing shadow
workflow. It has read-only repository permissions, no schedule, no release step
and no production tag mutation. Its final job rebuilds full/client/report from
the terminal assembled state, checks the client digest and retains diagnostics.
It pins the existing v3 table's exact bytes and release provenance for the
approved shadow comparison. Report numerical differences and convergence,
without treating legacy marginal SEs as calibrated comparison uncertainty.

Mark must separately authorize the single shadow dispatch. It measures actual
cost and convergence against that week's v3 table. Failure or incomplete work
does not authorize a retry. No dispatch is part of implementing this design.

D5 requires the v2 crib sidecar and a compatible trainer reader before
activation. Implementing that exporter/reader is outside this handoff's list
of authorized changes. The shadow workflow therefore publishes no sidecar,
and never substitutes a v1 crib sidecar. Eventual activated publication must
rebuild the final table, export v2 and publish full/client/sidecar together in
one final job, preserving exact-byte digest pairing. Do not move export into
a later job reading an already-published rolling release. Activation, adding
that publishing path, the release and trainer re-vendoring each remain separate
maintainer decisions.

## Budget and observability

The survey measured about 8.3 runner-hours for 78 distinct groups. Adding the
13 cheaper same-rank groups gives about 9 runner-hours per generation, about
18 for two generations. Eight shards imply about 1.2 sampling hours per wave.
The expected weekly wall time is roughly 3-4 hours, subject to the shadow run.
These are estimates, not a production timing measurement.

Assembly is not free: the measured N=22,000 resume validation is about
25 seconds per distinct group on the M2. A serial full-table validation can
therefore cost tens of minutes, before projection, serialization and upload.
Allow for two assemblies, final verification, analytical bootstrap and artifact
transfers in addition to sampling. The 18-hour figure describes the generation
estimate; these added costs must be reported separately. Give assembly/final
jobs explicit two-hour ceilings rather than assuming instantaneous assembly.
No individual job approaches the six-hour cap by design.

Record start/end times, planned and completed rows, policy evaluations where
available, phase/generation/plan identity, checkpoint and validation durations,
bytes and digests, convergence shift and guard outcome. A successful Actions
job alone does not establish complete counts. Keep durable artifacts and a
machine-readable completion record; no long silent foreground process.

## Implementation acceptance and falsification

Write tests before the implementation. The primary acceptance test runs a tiny
seeded selection through both a monolithic engine and split workers/assembly,
then compares parsed full state, all moments and projected statistics, exact
client bytes, next policy identity and the following generation. Exercise
same-rank and twin groups, both roles, different checkpoint cadences and resume.
The small test uses the covered deterministic scoring fixture; also run a tiny
real-scorer group through the boundary. This is test-only sampling, not a survey.

Independently test the complete 91-group/169-key partition and every rejection
listed above. Check no worker can transition and no transition occurs before
all groups arrive. Check completed and pending-transition guard failures,
non-convergence, measured/policy separation, missing/zero moments, exact-rerun
no-ops, conflicting existing bundles, competing installers, interrupted staging
and failure preservation. Name and kill mutations that omit group coverage, count
or generation/policy checks, substitute displayed values, or transition a
partial table. Equality on one happy path is insufficient.

Run the full required Python validation, README smoke and spelling checks,
plus workflow validation without dispatch. Preserve 100% artifact coverage.
Obtain independent adversarial review with practical split/resume and rejection
attempts, then re-review fixes before claiming readiness. Human review and
separate merge approval remain required. The design does not reopen the survey,
residual ruling, per-cut no-gate decision or established resume optimization.
