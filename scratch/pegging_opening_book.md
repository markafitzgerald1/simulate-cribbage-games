# Issue #187: Pone opening-lead experiment

This research harness changes only the first Pone selection. It does not enter
the generator, legacy CLI, release assets or published artifact schemas.

Each of the 1,820 canonical four-rank multisets gets 2,500 opponent keeps,
sampled uniformly from physical four-card subsets after removing the known
hand. All distinct leads share each opponent keep and play seed. After the
forced lead, both seats use `LegacyHeuristicPolicy`. The objective is Pone
pegging points minus Dealer pegging points, measured over the entire hand.

For each lead, online moments use the difference from the heuristic lead on
that same deal. Select the largest positive paired mean that reaches three
standard errors; ties favor the lower rank. This is a nominal training screen,
without a multiple-comparison correction. It is not independent validation
of individual entries. A zero-SE candidate has null `z` in the evidence;
only a positive mean can qualify in that case.

Overrides are `TabularPeggingPolicy` entries for the complete opening
`PolicyView`, with the heuristic as fallback. Later resets, Dealer decisions,
unsupported hands and every other information state keep that fallback. The
policy is frozen before calling the unchanged `evaluate_promotion` with its
200,000-deal default and the generator's default seed 42. Its streams are
independent of the labeled training streams. Dealer's candidate is the
heuristic, so its advantage is zero; the both-seat result is half Pone's.

Training rows and the policy fingerprint are deterministic given the seed and
sample count, independent of pool scheduling. The evidence digest hashes all
unrounded candidate statistics in canonical order. Elapsed times are excluded
from that digest. Evidence ranks are zero-based (`A23456789TJQK`); `mu` is the
paired gain relative to the heuristic lead, not an absolute pegging value.
There is no resumable accumulator or production reader.
The script writes its training evidence before starting the gate, so a gate
failure does not discard a completed book.

## Reproduce

Use Python 3.14.4 with the repository requirements installed. From an empty
temporary working directory, set `PYTHONPATH` to this checkout, create its
tally shelf, and run:

```sh
python -c "import shelve; shelve.open('start_of_hand_position_results_tallies_shelf', flag='c').close()"
python -m scratch.pegging_opening_book --samples 2500 --seed 42 --workers 8 --gate-deals 200000 --output book.json
```

The run stays separate from other simulator caches and shelves. The 25-sample
timing pilot projected about nine minutes for training on this machine; it
was used only for sizing, with no strength-based tuning of the final settings.
The retained result is `issue187_pone_opening_book.json` beside this note.

The optional production-style arm was omitted: the saved full/client tables
contain means and policy fingerprints, but no retrievable discard keeps.
Rebuilding those policies would add a separate discard calculation and cannot
establish that the reconstructed keeps match production from a fingerprint
alone.

## Retained result

The 2,500-sample, seed-42 run selected 656 overrides (36.0%). The default
200,000-deal gate passed at z = 46.93:

| Candidate seat | Net pegging gain per hand | Standard error |
| --- | --- | --- |
| Pone | +0.190935 | 0.004068 |
| Dealer | 0 | 0 |
| Both seats | +0.095468 | 0.002034 |

Training took 359.9 seconds with eight workers; the unchanged, single-process
gate took 61.5 seconds. Total experiment time was 421.5 seconds. This includes
14,787,500 forced-lead simulations. Four full-sample keys were replayed in a
single process and matched the pool evidence exactly. See the adjacent JSON
for every selected and rejected lead, its count, gain, paired SE and nominal z.

## Focused validation

```sh
python -m unittest scratch.test_pegging_opening_book -v
mypy scratch/pegging_opening_book.py scratch/test_pegging_opening_book.py
PYTHONPATH=. pylint --persistent=n scratch/pegging_opening_book.py scratch/test_pegging_opening_book.py
flake8 scratch/pegging_opening_book.py scratch/test_pegging_opening_book.py
npx cspell --config cspell.json scratch/pegging_opening_book.py scratch/test_pegging_opening_book.py scratch/pegging_opening_book.md
```

The tests exercise shared cards and random states, frozen heuristic
continuations, the covariance-sensitive paired standard error, inclusive
thresholds, positive means, minimum counts, deterministic tie-breaking,
physical multiplicities, exact opening keys, fallback and pool reproducibility.
The CLI test uses the real merged gate. Existing fast tests cover all reused
immutable heuristic functions at 100% including branches; focused expected
rank fixtures and complete simulations exercise those functions here too.

Scratch-copy mutation proofs target these failures:

| Mutation | Detecting test |
| --- | --- |
| Accumulate action totals instead of paired differences | Paired differences |
| Use action-dependent play seeds | Shared cards and seeds |
| Exclude equality at three standard errors | Threshold boundary |
| Maximize confidence margin rather than qualifying mean | Threshold and ties |
| Remove only one known card per rank | Physical removal |
| Key the entry with a wrong opponent count | Exact opening fallback |
| Ignore the caller's deal seed | Seed and pool reproducibility |
| Change the empty book's fallback lead | Frozen heuristic and full simulation |
| Force a zero-gain gate to pass | Real CLI and gate |
| Replace the evidence digest with a constant | Unrounded evidence digest |

Passing the gate supports average improvement over this heuristic on uniform
keeps. It does not establish optimality, an equilibrium, improved Dealer play,
per-entry out-of-sample significance or strength against other opponents.
Dealer first replies and all production integration remain later work.
