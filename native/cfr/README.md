# cfr-inputs

Regenerates the inputs of the six-layer CFR pegging policy. A later pull
request (from branch `feat/187-cfr-fixed-policy-measurement`) measures the
play tables with that fixed policy and pins these inputs by digest:

- **menus:** for each of the 3,640 pairs of four-card hand and seat, every
  point in pegging where that player has a real choice of card, as the player
  sees it (own hand plus the cards played so far). These are the decisions
  the policy has to make.
- **trees:** for each of the 1,820 Pone hands, every way the pegging can go
  against every possible Dealer hand, with the final pegging margin at each
  leaf.
- **offsets:** where each menu's probabilities start in the one flat policy
  array.
- **the CFR+ mixture policy and its exact certificate.**
- **the counterfactual support bits.**

The policy makes every real choice in the hand: each seat's first three
cards wherever more than one rank is legal. Two seats times three cards are
the six layers; the fourth card is always forced. Here the legacy pegging
heuristic (the rule-based policy in `artifact_pipeline/pegging.py`) only
fills in forced moves, where any rule plays the same card. Its real job is
the choice it would make at each decision, which every menu record stores.
The measurement reads that choice: it plays the heuristic wherever the stored
policy has no row, and counts the decisions where the policy agrees with it.

It is a port of the unpublished research C++ (`stream.cpp`, `offsets.cpp`,
`support.cpp` and the header `cfr_joint_native.hpp`). What has to match is
the output, not the code's shape: the menus, trees, offsets, policy and
support reproduce the research files byte for byte. (Certificate files match
in their integers. Their display-only `exposure` float and their measured
`seconds` can differ.) Two things therefore stay fixed. The heuristic's
tie-break order is part of the output. The solver also adds its
floating-point terms in the research order, with no fused multiply-add,
because a different order changes the low bits of the policy. Names and
structure are otherwise free to be idiomatic Rust.

## What each module mirrors

| Module | Research source | Output |
|---|---|---|
| `game.rs` | `joint::State` in `cfr_joint_native.hpp` | rank-only pegging rules and the legacy heuristic |
| `menus.rs` | `collect`, `make_menu` in `stream.cpp` | `menus/{k}.bin`, 3,640 files |
| `trees.rs` | `load`, `lookup`, `Tree`, `make_tree` in `stream.cpp`; `offsets.cpp` | `trees/{p}.bin`, 1,820 files; `offsets.bin` |
| `solve.rs` | `walk`, `update`, `rounded`, `joint_value`, `response`, `br`, `certificate` in `stream.cpp` | the CFR+ iteration, the rounded policy, the exact `i128` certificate |
| `driver.rs` | the `solve` mode of `stream.cpp` | checkpoints, `policy-N.bin`, `certificate-N.json`, `policy.bin` |
| `support.rs` | `support.cpp` | `support.bin` |

Deliberate differences from the research driver:

- **Pausing never certifies.** The research driver certified, and could stop
  for good, whenever its time budget ran out. Certificates here come only at
  iterations 1, 8, 32 and every multiple of 128. The research schedule was
  1, 8, 32 and 128 only; it never needed more, because the pinned solve met
  its target at 128. A resumed solve therefore ends on the same policy as an
  uninterrupted one.
- **A crash during certification is repaired.** A resume first certifies a
  scheduled checkpoint that has no certificate yet.
- **A finished solve is never continued.** Running `solve` again returns the
  recorded result.
- **Resume checks the saved state.** It verifies the checkpoint's SHA-256
  digests and the inputs' identity: the prior plus the menu and tree
  digests. Files are flushed to disk before each rename.

## Parallelism without changing bytes

Every floating-point accumulator receives its terms in the serial C++ order,
whatever the thread count.

- **Pone's pass** runs Pone hands in parallel.
- **Dealer's pass** keeps Pone hands sequential and runs Dealer hands in
  parallel.
- **Per-menu updates** run per file.

`solve.rs` explains why each choice preserves the order. The test
`bytes_do_not_depend_on_thread_count` checks it on a small game.

## Usage

```sh
cargo build --release
B=target/release/cfr-inputs
$B menus   --output OUT [--range START..END]
$B offsets --output OUT
$B trees   --output OUT [--range START..END]
$B solve   --output OUT --prior PRIOR.bin [--pause-after-seconds S]
$B support --output OUT --policy OUT/policy.bin --prior PRIOR.bin
$B digests --output OUT
```

`--range` writes only those menu files (0..3640) or tree files (0..1820),
so the work can be split across jobs. `trees` needs every menu file.

`solve` exits with:
- 0 when the 0.001-point exposure target is met;
- 3 when it pauses on its time budget (run the same command again to
  resume);
- 4 at the iteration cap.

`support` sets one bit per `--policy`/`--prior` pair, in the order given. The
research `support.bin` has two bits: the mixture policy with the mixture
prior, then the production policy with the iteration-4 prior.

`digests` prints the SHA-256 of each output. For the menu and tree folders it
prints the SHA-256 of the per-file digests, one per line in file order. The
printed values can be compared with `research-digests.json`.

## Hosted run

`.github/workflows/generate-cfr-inputs.yml` runs the whole shipped chain on
GitHub's runners: the Python prior, then `menus`, `offsets`, `trees`,
`solve` and a one-bit `support`. It is manual only and publishes nothing.
Each solve job first checks its menus, trees and offsets against
`research-digests.json`, since no prior changes them. The first solve job's
budget ends 45 minutes before its time limit, and it pauses at the next
iteration end; a second job resumes from the
uploaded checkpoint and must converge. The converged policy, support,
certificates and per-step timings, peak memory and free disk are kept as
30-day Actions artifacts. Dispatching it needs the maintainer's approval
and the input `generate`.

## Evidence

Measured on an Apple M2 with 8 threads, 2026-11-10, with binary sha256
`42160cc1...`, built from this source. The run built menus, offsets and
trees, then ran `solve --pause-after-seconds 600`, which paused at iteration
31 with exit 3. The same command then resumed and converged at 128. Support
and digests followed. Earlier builds of the same arithmetic produced the same
digests, three paused (at 37, 27 and 27) and three uninterrupted.

**Byte-for-byte reproduction:**
- **Menus, trees and offsets:** they match the research files byte for byte.
  The checks covered all 3,640 menus against the measurement PR's manifest
  (`inputs/policy.json` on `feat/187-cfr-fixed-policy-measurement`), all
  1,820 trees against the research tree digests, and the offsets.
- **Support:** fed the saved mixture and production policies and their two
  priors, it reproduces `7e788918...`.
- **Solve:** on the pinned prior `6685f548...` it converges at iteration 128
  and writes `policy.bin` with sha256 `ec93951f...`, the pinned research
  policy. The integers in certificates 1, 8, 32 and 128 equal the research
  certificates. The certificate files themselves differ in the display-only
  `exposure` float, which prints in shortest round-trip form, and in
  `seconds`.

**Runtime:**

| Step | Rust (M2, 8 threads) | Research C++ |
|---|---|---|
| menus | 60 s | 160 s on 4 threads |
| trees | 73 s | 141 s on 4 threads |
| solve | 32 to 34 min wall uninterrupted, 3.7 to 4.1 GB peak RSS | 71 min single-threaded |
| support | 14 s | 22 s |

The wall-clock gain comes from using more threads, not from faster code: the
Rust solve spends about 260 thread-minutes against the C++'s 71
single-threaded minutes. The point of the parallelism is throughput without
changing a single output byte.

## Validation

```sh
cargo fmt --check
cargo clippy --locked --release --all-targets -- -D warnings
cargo test --locked --release
RAYON_NUM_THREADS=1 cargo llvm-cov --locked --release --fail-under-lines 100 --show-missing-lines
pmd cpd --language rust --minimum-tokens 40 --dir src --dir tests
cargo deny --locked check
```

The `rust-cfr-inputs` CI job runs the same gates, mirroring the Python and
TypeScript ones:
- **Lint:** clippy's pedantic group is on in `Cargo.toml`, which explains
  each exemption, and `min_ident_chars` rejects one-letter names.
- **Coverage:** 100% of lines.
- **Copy/paste:** PMD 7 CPD at the TypeScript threshold of 40 tokens.
- **Dependencies:** `deny.toml` fails on RustSec advisories, yanked crates,
  licenses other than MIT, Apache-2.0 or MPL-2.0, duplicate versions and
  unknown sources. Dependabot watches `Cargo.lock`.

The tests are small-game checks:
- determinism across thread counts;
- pause, crash, cap and resume behavior, and damaged or mismatched saved
  state;
- the joint value, both best responses and the support bits against oracles
  that replay each deal from the game rules and find menus by history,
  never through the trees;
- a pinned digest of the small game's arithmetic;
- every subcommand of the binary, its exit codes and its argument errors,
  on output folders small enough for a test.

They cannot show equivalence with the research C++. That evidence comes from
the full-size runs above. A later manual workflow is planned to repeat them
on Actions.
