# Parallel play-table generation

`generate_play_table.py --workers N` uses spawned processes. The CLI defaults to
`os.process_cpu_count()` (or one if unavailable); library calls default to one
for compatibility with existing serial callers. `--workers=1` uses no pool.
Use an explicit count on a shared machine. The `geometric`, `uniform-hand`, and
`geometric-hand` averaging modes use the same process boundary.

## Independent work and exact reduction

Each measurement task owns one complete (canonical hand, role) entry. Its RNG
seeds remain functions of the run seed, hand, role, and cumulative sample index.
The worker updates the entry's online moments in the original sample order.
It returns the entry, including all absolute-seat categories and opening lines.
The parent consumes entries in input order and checkpoints only after both
roles of a hand are complete. Adaptive stopping happens inside each entry.
Workers never write checkpoints or artifacts.

A rollout best-response pass freezes its policies before launching workers.
The parent draws deals from the original sequential RNG, in fixed batches of
32 samples independent of worker count. Each deal carries its global sample
index. Trace and rollout seeds retain their original derivation, and rollouts
keep the trace's resolved policies, including whole-hand component/fallback
draws. Workers return raw (information-state key, rank, delta) observations in
sample, decision, rank, and rollout order. The parent replays them in that order
through the original online accumulator. Combining floating-point shard
moments would change rounding and potentially tie-breaking; it is deliberately
avoided. Counts, means, second moments, actions, and policy fingerprints remain
identical.

Pone and Dealer response updates alternate sequentially. Outer iterations,
analytical solving, discard refinement, action selection from reduced moments,
and file writing also remain sequential. Policy-table measurement passes use
the same entry distribution as final measurement. The process pool is recreated
for each frozen pass, so later responses cannot observe stale snapshots.

## Checkpoints and byte comparisons

Play generation method v4 saves unrounded `moment_2` beside `n`, `mu`, and `se`
for each delta, absolute-seat total, and point category. Opening lines already
save their raw moments. Resume restores these values directly; worker count may
change between partial and resumed runs. Already satisfied adaptive entries
receive no additional sample. v3 and earlier checkpoints are rejected because
reconstructing a second moment from a displayed SE is not bit-exact. Start the
first v4 run with `--no-resume`. This method version changes checkpoint
provenance, without changing the means schema or lines schema.

Client and lines files compare byte for byte for the same seed and settings.
All measured full-artifact fields, training reports, and fingerprints do too.
The existing `generated_at` field records wall-clock time and naturally differs
between independent invocations. Full-byte tests hold that field fixed; a
comparison of ordinary CLI runs must normalize that field alone. Execution
worker counts, PIDs, timings, and memory reports never enter table metadata.
The experiment runner records the resolved worker count in its separate report.

## Memory and performance measurements

Each worker receives one frozen policy/discard snapshot per pass. At most twice
the worker count of tasks are pending in the ordered map. Fixed training batch
size bounds the raw-observation lists in flight; final measurement returns one
entry rather than every simulated hand. After a pass, stderr reports peak RSS
for every process that completed work. This is whole-process resident memory,
including Python, imports, policy snapshots, and working data; Linux KiB and
macOS bytes are normalized to MiB. It is not an incremental policy-size estimate.

Spawn startup, snapshot serialization, IPC, ordered observation replay, and the
sequential analytical/refinement stages limit speedup, especially on tiny runs.
Use a bounded but substantive workload at 1, 2, 4, and 8 workers, preserve all
training/sample settings, record end-to-end and stage wall times, and compare
the actual written files. The usage-counter runner
`scripts/run_pegging_experiment.py` defaults to one worker and accepts explicit
parallel counts. Worker-local observations are returned and reduced in the
parent; `experiment.json` records the resolved worker count.

Parallelism preserves policy quality at fixed settings. Use freed time first
for matched, held-out training experiments measured by issue #187's quality
gauge and coverage diagnostics. The current evidence identifies substantial
legacy fallback usage; deeper training requires measurement, and faster
generation does not itself justify a new production policy or sample count.

The Unix-only `resource` module is optional. On platforms without it, worker
results and ordering are preserved, peak RSS is unavailable, and memory
reporting is omitted. This does not restrict serial execution or library imports.
