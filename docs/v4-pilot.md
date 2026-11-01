# Bounded v4 pilot

OpenAI Codex, measured October 31, 2026 (America/Toronto), starting from main
`32e520e`. This is a cost/precision pilot, not the table-wide sign survey or a
production regeneration. No policy training, workflow dispatch, publication,
consumer change, or per-cut sign gate is included.

The [machine-readable timings](v4-pilot-measurements.json) retain chunk counts,
write times and source/policy manifests; they contain no sampled table moments.

## Review and acceptance

Allow 5-10 minutes for human review after the independent review loop is clean.
Read the risk table and terminal 3-8 result, then decide whether the proposed
16-hour future survey is worth its cost. Merging this pilot does not approve
that survey or production activation. Most added lines are timing JSON, marked
as generated in GitHub; expand them only to audit records. The shared runtime
change is the short `_exact_psd` function; the separate helper is diagnostic.
There is no app screen or deployed preview to test for this change.

| Risk and worst outcome | Exposure now | Evidence and later checks |
| --- | --- | --- |
| PSD false rejection prevents resuming a valid checkpoint | Opt-in v4 operator loses time | Independent old/new exact comparisons and principal-minor oracle test acceptance. A later resume makes rejection visible. |
| PSD false acceptance admits inconsistent covariance | Opt-in v4 can report misleading uncertainty | Independent oracle and corrupted-state tests are the primary protection. Per-bucket variance checks catch only some directions. The survey and an exporter reusing this validator do not independently prove PSD. |
| Diagnostic output aliases its source and destroys it | Local input file, before any publication | Real CLI tests reject direct, symlink and hard link temporary-path aliases with unchanged source bytes. Later math or release checks cannot restore that file. |
| Pilot understates full-survey time or overstates precision | Future budget/research decisions | Independent integer-moment projection verifies the terminal figures. Monitoring and a stop budget limit future cost; the survey does not itself establish calibration. |
| A future v4 artifact reaches users with an unnoticed defect | Future activation and adoption, not this merge | Weekly v3 routing and assets are unchanged. Separate survey, export, production and trainer decisions offer opportunities to catch defects, but need independent checks rather than reusing the same arithmetic. |

For a quick check without reading implementation, run from a configured PR
checkout:

```sh
python -m unittest artifact_pipeline.test_crib_v4_psd \
  artifact_pipeline.test_crib_v4_state test_measure_crib_v4
```

Expected: all tests pass in seconds, including source preservation, exact
classification and a hand-calculated covariance result. The maintainer does
not need to rerun expensive measurements or the full CI suite. A second,
optional acceptance check exercises real CLI fresh/resume behavior:

```sh
trial="$(mktemp -d)"
v4_trial() {
  python -c 'from artifact_pipeline.generate_table import main; main(["3_8_Suited", "3_8_Unsuited"])' \
    --estimator-v4 --seed 42 "$@"
}
v4_trial --samples 2 --output "$trial/resumed.json"
v4_trial --samples 4 --output "$trial/resumed.json"
v4_trial --samples 4 --output "$trial/fresh.json"
cmp "$trial/resumed.json" "$trial/fresh.json"
cmp "$trial/resumed.client.json" "$trial/fresh.client.json"
```

Expected: all commands succeed; both `cmp` calls print nothing, confirming exact
fresh/resumed full and client bytes. Only temporary trial files are written.
If either check fails, stop review and retain the output. This establishes the
small acceptance case, not performance at N=22,000 or statistical calibration.

## Inputs and reproduction

Apple M2, 16 GiB RAM, macOS 26.6.2, CPython 3.14.4, seed 42, generation zero.
The existing full artifact's saved `generation_accumulators`, including its
`policy_mu`, supplies the frozen suit-sensitive policy. Passing the entire
artifact to the ordinary `--bootstrap` option would instead read its displayed
root means and would change the experiment.

- Source full SHA-256:
  `a0464f8c805f782c27040bb366e0775455cd2fa02eb5e458d70bb0e6b9c69666`.
- Matching client SHA-256, verified against the existing local bytes:
  `4cd8a9258d32973710361b9c2a764aea3b8c9a1178ab53e1c2aa38a53e030cc1`.
- Canonical saved-policy SHA-256:
  `2a2a584f1f31fc28f3aa42988f0be8659eafde5e1776cac27c09f1d2e6f114d0`.
- Estimator `shared-rank-relation-v1`; centering
  `uniform-two-card-rank-completion-v1`; allocation base:residual:suit = 1:1:1
  for twins, base:suit = 1:1 for pairs. All inputs remain unchanged.

Run each measurement as a tracked background job, retaining stdout/stderr and
its exit status. The helper emits flushed JSON progress after each group chunk
and checkpoint, and rejects a resumed checkpoint from another source/policy.
For example, with the matching historical full artifact saved as `inputs.json`:

```sh
python -m scripts.measure_crib_v4 --source inputs.json \
  --rank-group 3_8 --samples 22000 --checkpoint-frequency 400 \
  --output /tmp/pilot-3-8.json > /tmp/pilot-3-8.log 2> /tmp/pilot-3-8.err
```

Use separate output files for `2_3` and `7_8` at N=4,000/cadence 1,000, and
`4_J` and `A_A` at N=1,600/cadence 800. Same-rank groups have no twin gap.
Reusing an output at its saved target measures resume without new sampling.
The helper suppresses client writes for these diagnostics. The README's
separate N=2 example also exercises actual full/client generation.

## Generation and precision

A sample step is one complete row in **each active stream for one role**.
It is not one physical starter, policy evaluation, or weighted bucket count.
Each distinct-rank round draws three hands and evaluates the actual selector
five times: once for base and twice each for residual and suit. Thus 3-8 at
N=22,000 in both roles commits 132,000 vector rows and 220,000 selector calls.

Timings below exclude each chunk's checkpoint callback (projection, encoding,
JSON write and atomic replacement). They include row construction and moment
updates. Ranges describe observed chunk timings, not confidence intervals on
hardware speed. Concurrent local validation/diagnostics slowed some chunks;
these are wall times, not isolated single-core speed estimates.

| Group | N/stream/role | Chunks/role | Dealer ms/step, median [range] | Pone ms/step, median [range] | Final bytes, both roles |
| --- | ---: | ---: | ---: | ---: | ---: |
| 3-8 | 22,000 | 55 | 6.275 [5.396, 36.902] | 6.261 [5.413, 35.541] | 10,773,069 |
| 2-3 | 4,000 | 4 | 12.547 [12.007, 23.454] | 11.629 [8.463, 29.295] | 10,668,303 |
| 7-8 | 4,000 | 4 | 10.771 [9.634, 21.534] | 11.778 [8.851, 30.350] | 10,667,160 |
| 4-J | 1,600 | 2 | 10.678 [9.484, 11.873] | 9.362 [8.970, 9.753] | 10,808,528 |
| A-A | 1,600 | 2 | 10.108 [6.028, 14.187] | 8.368 [4.877, 11.860] | 2,816,909 |

The fresh 3-8 N=400 baseline took 7.350 s including checkpoints; N=22,000 took
450.616 s, including 112 checkpoint callbacks. The latter timing includes
contention. Its first and last snapshots have different target metadata from
N=400, so raw-byte size differences are not exclusively moment growth. A
separate timing-only continuation from N=22,000 to 23,000 took 11.969 ms/step
Dealer and 14.651 ms/step Pone after subtracting writes, under concurrent
validation. Its 34.718-second load and extra rows are not used for the terminal
N=22,000 precision claim; the diagnostic files remain separate.

Pre-cut roots are weighted by `(4 - own_rank_multiplicity)/50`. The shared
baseline cancels before computing the twin variance. Cross-cut and within-suit
flush/nobs covariance are retained, not reconstructed from marginal SEs.

| Group/role | N/stream | Rank residual (SE) | Flush gap (SE) | Nobs gap (SE) | Total twin gap (SE) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 3-8 Dealer | 22,000 | -0.001010 (0.000524) | 0.040573 (0.001298) | 0.000062 (0.000082) | 0.039625 (0.001399) |
| 3-8 Pone | 22,000 | -0.001027 (0.000594) | 0.037459 (0.001253) | -0.000048 (0.000091) | 0.036384 (0.001386) |
| 2-3 Dealer | 4,000 | 0.002573 (0.001644) | 0.038494 (0.002965) | -0.000216 (0.000186) | 0.040852 (0.003385) |
| 2-3 Pone | 4,000 | -0.001749 (0.001952) | 0.039858 (0.003028) | -0.000114 (0.000151) | 0.037995 (0.003595) |
| 7-8 Dealer | 4,000 | -0.000430 (0.002262) | 0.034773 (0.002836) | 0.000102 (0.000181) | 0.034445 (0.003624) |
| 7-8 Pone | 4,000 | -0.011552 (0.003042) | 0.035682 (0.002858) | 0.000244 (0.000159) | 0.024374 (0.004168) |
| 4-J Dealer | 1,600 | -0.000431 (0.002030) | 0.046733 (0.005146) | -0.019645 (0.000970) | 0.026657 (0.005411) |
| 4-J Pone | 1,600 | -0.000009 (0.002304) | 0.038920 (0.004745) | -0.018352 (0.001009) | 0.020560 (0.005187) |

3-8 Pone's achieved 0.001386 SE is 5.0% above the old 0.00132 projection,
which assumed separate flush/nobs streams. Its individual normal diagnostic
95% interval is [0.033667, 0.039101]. This is conditional on the frozen policy;
it is not empirical calibration, a simultaneous survey interval, or a
crib-wide noise floor. No independent-twin speed/variance improvement factor
is claimed: the repeated-seed comparator/calibration experiment in the wider
#135 plan remains future work.

The 7-8 Pone residual is larger in magnitude than the earlier N=6,000 estimate
(-0.003513, SE 0.002437). It is retained and reported, not clamped or discarded.
These different seeded samples do not establish a changed expectation. Its
flush contribution still exceeds the measured negative residual here. Five
chosen groups cannot establish the sign distribution across all 156 twins.

## Resume and checkpoint cost

| Rows/stream, 3-8 both roles | Original Fraction load, seconds | Primitive integer load, seconds |
| --- | ---: | ---: |
| 400 | 92.158 | 5.960 |
| 1,600 | 157.743 | 8.349 |
| 22,000 | 311.902 | 25.042 |

The suit stream has 357 contract coordinates, of which 279 have nonzero
empirical variance in these larger checkpoints. Base and residual each have
39 active coordinates. Original N=1,600 load consumed 119.566 CPU s; primitive
load consumed 8.319 CPU s. At N=22,000 the original load consumed 254.218 CPU s
and primitive load consumed 21.447 CPU s: 12.5x less wall time and 11.9x less CPU time.
This confirms growth with sample target even at fixed dimension, but does not
fit a dimension exponent from three real observations. The earlier d^5 claim
was a small synthetic extrapolation, not a measured production law.

Exploration at N=1,600: plain Bareiss took 108.496 wall/106.185 CPU seconds;
initial diagonal-unit normalization reduced that to 41.487/41.227 seconds.
The committed implementation instead removes common integer content at every
Schur step, which performed substantially better on the actual matrices.

The real N=22,000 two-role checkpoint is 10.77 MB. A serializer-only stress
fixture replicated that group's state 91 times with one policy snapshot,
producing 853,450,713 bytes. Three indented JSON writes plus atomic replacement
took 20.292, 21.028 and 32.158 wall seconds (17.358, 18.678 and 22.386 CPU s).
This is a synthetic storage load, **not sampled full-table data**. It overstates
same-rank moment size and omits the other groups' derived views; it supports an
approximately 0.8-1.0 GB planning allowance, not an exact artifact-size claim.
Writes are buffered, matching the existing writer; no durability/fsync timing
is claimed. Full-table projection and client-writing cost remain additional.

At cadence 100, N=22,000 means 220 passes x 182 group-role callbacks, or 40,040
whole-file rewrites, plus initial/final writes. At a representative mature
21-second rewrite this is about 234 hours of serialization alone; early files
are smaller. At cadence 1,000 it is still 4,004 rewrites (about 23.4 mature-file
hours). At cadence 22,000 it is 182 callbacks, with a growing file during the
first pass: at most about 1.1 mature-file hours, plus initial/final writes.
These are extrapolations, not executed surveys. No indentation, wire format,
stream allocation, or production sample target was changed.

## Proposed budget, awaiting Mark's approval

Approve **16 local wall hours for one fixed-policy N=22,000 survey**, with the
source/policy/seed above and all 91 groups/both roles. This is a ceiling for
planning, not permission granted by this pilot. A central sampling range of
roughly 7-14 hours follows from the measured 6-12 ms group-role steps; a
conservative allowance of 14 ms for distinct-rank and 10 ms for same-rank
steps gives 14.9 sampling hours. Reserve the balance for checkpoints, startup,
reporting, and a bounded retry. Unresolved signs stay unresolved at terminal N.

Prefer separate rank-group checkpoints at cadence 1,000 for the diagnostic
survey: each two-role file is about 3-11 MB, its writes take under one second
locally, and a restart validates only that group. Group selection is absent from row
seeds, so with the same frozen policy the individual rows match a combined
run; retain each shard's own metadata and do not concatenate JSON into a
purported valid full checkpoint. Reporting over shards is separate from
production publication. Start jobs in batches with at most one hour of
estimated work, report progress, and pause if the aggregate budget is reached.

For an eventual **single-file production** run, propose cadence 22,000 rather
than the default 100, preserving complete-round SIGINT checkpoints. The measured
per-role work between checkpoints is minutes at this target. A provisional
16-hour local allowance covers one frozen-policy generation only, not training
or an unspecified number of policy transitions. A six-hour CI job cannot be
promised to fit even the central local estimate. Production needs a separately
approved resume-across-jobs plan, measured CI throughput/storage, and eventual
v2 export/consumer readiness. The existing play-pipeline runner multiplier is
not a v4 crib benchmark. Do not reduce N to fit the cap.

## Why exact acceptance is unchanged

For a symmetric integer matrix with first block `[p, v.T; v, A]`, a negative
p is a negative quadratic form. If p=0 and v is nonzero, some vector supported
on those two coordinates has negative form; if v=0, remove that zero row and
column. For p>0, completing the square makes PSD equivalent to PSD of
`A - v*v.T/p`, which is equivalent to PSD of the integer matrix
`B = p*A - v*v.T`. Dividing B by its positive gcd leaves that status unchanged.
When B is all zero, no division is needed. Induction proves the same accept/
reject result as rational Schur elimination for every symmetric integer input.
Only the upper triangle is stored during elimination; the original matrix is
copied. No floating tolerance, sign clamp or weakened feasibility check enters.

An independent all-principal-minors oracle exhausts all 729 symmetric 3x3
matrices with entries in {-1,0,1}, plus large signed/singular 4x4 congruences
and zero pivots before/after positive pivots. These tests pass the original
implementation too: this fixes cost, not an incorrect PSD verdict. Before the
change, a dense 120-coordinate integer Gram fixture failed a five-CPU-second
scratch regression budget at 8.985 CPU s. The final check passes at 0.790 s.
The timing threshold is a pilot regression experiment, not a flaky CI test.

Named scratch mutations all fail the independent oracle: omit zero-row
rejection (109 failures), reject zero pivots (24), add the cross term (137),
and divide by gcd+1 (3). The report's hand-calculated projection test also
retains negative cross-cut flush/nobs covariance and the 3/50 versus 4/50
starter weights. Its numerical expectation is independent of the projection
implementation.

The unchanged v4 sampling identity and JSON format need no contract bump.
Both original-validator and final-validator N=400 -> 1,600 seeded runs equal
fresh N=1,600 generation in every field, moment and statistic. The existing
small seeded, nonce, interruption, and policy-transition tests remain required.
A bounded v3 control-variate run at N=40, seed 42, both 3-8 variants/roles,
produced identical full and client bytes from main and the pilot sources.
The legacy file, v3 generator and weekly workflow have no source changes;
this is bounded compatibility evidence, not a regenerated weekly artifact.

The same-interpreter `scratch/verify_upgrade.py` passed all ten existing cases
in isolated directories, with local worker connections permitted. It establishes
repeatability, not before/after source compatibility or v4 calibration.


## Initial-head validation

At `7a93a13`, all required Python checks passed: 356 root tests, 318 fast artifact tests,
all five slow analytical tests, and the appended ratchet tests. The combined
artifact/ratchet gate reports 100% statement and branch coverage (3,811
statements, 1,508 branches). Mypy, artifact pylint, the legacy ratchet and
similarities check, flake8, spelling (including this report), configured file
hooks, the README full/client smoke run and the mutation experiments passed.
No browser behavior changed; no browser suite was needed. The coverage-command
clarification in all three guidance files collects existing ratchet tests after
the artifact run resets coverage; it changes no hook, CI gate or threshold.
