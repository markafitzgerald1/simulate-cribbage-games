# Table-wide pre-cut v4 survey

OpenAI Codex, November 1, 2026. Mark approved this budget in the handoff:
one workflow PR, then one manual dispatch on `main` after Mark merges it.
A failed or incomplete shard requires approval before retry or resume.
Production regeneration, version-4 activation, publication, larger N and
sampling until a positive sign are outside this authorization.

## Fixed experiment and budget

The separate `survey-crib-v4.yml` workflow runs four parallel shards. Their
literal group lists are committed in `scripts/run_crib_v4_survey.py`: 20, 20,
19 and 19 groups, each with three Jack groups to balance their slightly higher
cost. Together they cover the 78 distinct-rank groups exactly once, both roles
and complete twins (156 comparisons). Same-rank groups have no suited twin.

Each active stream targets N=22,000 complete rows with seed 42, generation
zero, CPython 3.14.4 and the original source/client/saved-policy hashes from
[the pilot](v4-pilot.md). The [first diagnostic's](v4-diagnostic.md) input
verification, exact moments, contracts and per-group checkpoint handling are
reused. Group allocation never changes row seeds. No policy is trained.

Measured generation costs are about 21 seconds per 1,000 rows per group,
including both roles (about 22 seconds for Jack groups). Expect about ten
runner-hours total and 2.5-3 hours elapsed; the conservative 1.56 multiplier
puts each shard near four hours. These are projections from the diagnostic,
not full-survey measurements. Each job has a 330-minute ceiling and a graceful
deadline recorded by its first step, 300 minutes later, reserving 30 minutes
for final checkpoint and upload. Finish at N even when time remains.

Checkpoint cadence is 1,000 complete rounds per group/role. Expect about
210 MB of checkpoints per shard. Each shard has its own concurrency group
and artifact `crib-v4-survey-shard-<k>` with 30-day retention. A failed shard
does not cancel the others. There is no automatic retry or continuation.
The workflow is manual-only, read-only and separate from release workflows.

## Resume and evidence

After separate approval, `resume_run_id` restores each shard's own named
artifact from a completed manual survey in the same repository. The manifest
pins the shard, groups, N, source/client/policy hashes, runtime, producer and
helper source files, and this workflow's bytes. Another shard or changed
experiment fails closed. The shared runner validates checkpoint provenance
and retains logs, actual counts and individual group files. Restored results
are not newly validated when this attempt fails or skips measurement.

Read summary and terminal status events even when Actions reports success:
a graceful deadline can leave groups incomplete or unstarted. Upload logs
record transferred bytes, digest and duration; the step summary records local
bytes and measurement outcome. Reserve time is not a guarantee against runner
loss or exceptionally long operations.

Download all four artifacts into separate fresh directories. Read them as data
with `python -I`; do not concatenate their JSON into a full checkpoint. Report
all 156 pre-cut twin gaps with covariance-aware comparison SEs, actual counts,
and residual/flush/nobs splits, retaining unresolved signs and negative
residuals. Describe any exceptions by mechanism, including possible suppression
of flush contributions by the suit-sensitive policy. Include per-shard wall
time, throughput, checkpoint sizes and upload costs. Individual normal intervals
are diagnostics, not simultaneous sign guarantees or empirical calibration.
Twin SEs are not a crib-wide noise floor. No per-cut sign gate is justified.
Post the results on #135 attributed to OpenAI Codex, then ask about follow-up.

## Review guide

Allow one short sitting. Read this budget, the workflow's matrix/deadline/restore
and upload steps, and the survey wrapper's fixed lists and manifest. The shared
coordinator changes only to accept explicit groups, target and identity; its
original five-group N=4,000 entry point keeps those defaults. Skip the unchanged
estimator, production workflows and historical pilot data unless auditing them.
Run this practical check without dispatching or sampling:

```sh
python -m unittest test_crib_v4_survey test_crib_v4_diagnostic test_workflow_gates
```

Expected: all pass, covering the exact partition, fixed N/cadence/deadline,
wrong-shard rejection, workflow origin, budget and parallelism, failure upload,
and the existing real interruption/resume checks. The pilot's optional tiny
fresh/resume CLI example exercises the unchanged engine end to end.

## Durable timing corrections

V4 crib generation on the GitHub runner was about M2 speed: about 20 seconds
per 1,000 samples for 3-8 versus 20.5 seconds locally (450.6 seconds at
N=22,000). The play pipeline's 1.6 multiplier must not be reused for v4 crib.
Resume at N=22,000 was measured in #205 at 25.0 seconds for 3-8 on the M2;
the later 45-75 second extrapolation overstated it. About 0.5 runner-hours
for all distinct groups is a planning estimate, not a measured survey resume.
The exact PSD optimization already landed in #205 (311.9 down to 25.0 seconds).
No further optimization is required for this approved budget.

## Independent adversarial review

Two separate OpenAI Codex reviewers, neither the implementer, reviewed executable
commit `4e0848e8b4185a2fae249df7ce5f491468a92577` on November 1, 2026.
No executable defects were found. Both also checked the new independent-review
readiness gate in `AGENTS.md`, `README.md` and `skills/SKILLS.md`.

The operations review examined authorization, workflow isolation, concurrency,
resume origin and manifests, deadlines and failure uploads. It ran the 28
focused checks and actionlint, then independently exercised two small groups
through the real coordinator, scorer, engine and checkpoint machinery at N=2
using fixture input digests and partition/target overrides. Both roles and all
streams reached the target; same-target resume preserved checkpoint bytes.
Wrong-shard manifests, changed workflow hashes and swapped group checkpoints
were rejected. An expired deadline started no group or checkpoint.

The contract review independently checked the exact 78-group partition and
experiment identity. Its separate tiny deterministic-scoring experiment used
the real engine/checkpoint path with correctly hashed synthetic input: both
roles and all streams retained count and next index 2, generation zero and
seed 42; fresh and resumed checkpoint bytes matched. Revisiting a completed
checkpoint succeeded with sampling replaced by a function that would fail if
called. All 28 focused checks passed in that review too.

These reviews do not establish physical-policy mathematics, calibration,
N=22,000 performance, production input availability or actual GitHub runner
cancellation/upload behavior. The operations experiment used a real scorer;
the contract experiment used the existing deterministic test scorer. Neither
review dispatched a workflow. A future approved resume schedules all four
matrix jobs, including validation of completed shards; account for that cost.

The contract reviewer also found a test gap: routing every measurement to 3-8
still passed the new survey tests. The follow-up asserts the exact measurement
call count, each rank group, its output path and the source path. In scratch
copies the strengthened test rejects constant-rank, constant-output and extra
measurement mutations; the unmodified coordinator passes.

The follow-up changes tests and documentation, leaving executable behavior
unchanged. The readiness gate now
explicitly requires independent adversarial review before a ready handoff,
review of fixes, and recorded commit/scope/findings/limits. CI and self-review
alone cannot satisfy it. Human review and execution authorization still apply.
