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

The generator arrives in stacked pull requests. This one adds the menus, trees
and offsets. The solve and the support bits follow.

## What each module mirrors

| Module | Research source | Output |
|---|---|---|
| `game.rs` | `joint::State` in `cfr_joint_native.hpp` | rank-only pegging rules and the legacy heuristic |
| `menus.rs` | `collect`, `make_menu` in `stream.cpp` | `menus/{k}.bin`, 3,640 files |
| `trees.rs` | `load`, `lookup`, `Tree`, `make_tree` in `stream.cpp`; `offsets.cpp` | `trees/{p}.bin`, 1,820 files; `offsets.bin` |

## Usage

```sh
cargo build --release
B=target/release/cfr-inputs
$B menus   --output OUT [--range START..END]
$B offsets --output OUT
$B trees   --output OUT [--range START..END]
$B digests --output OUT
```

`--range` writes only those menu files (0..3640) or tree files (0..1820),
so the work can be split across jobs. `trees` needs every menu file.

`digests` prints the SHA-256 of each output. For the menu and tree folders it
prints the SHA-256 of the per-file digests, one per line in file order. The
printed values can be compared with `research-digests.json`.

## Evidence

Measured on an Apple M2 with 8 threads, 2026-11-10, with binary sha256
`42160cc1...`, built from the top of this stack of pull requests. Menus,
trees and offsets match the research files byte for byte. The checks covered
all 3,640 menus against the measurement PR's manifest (`inputs/policy.json`
on `feat/187-cfr-fixed-policy-measurement`), all 1,820 trees against the
research tree digests, and the offsets.

| Step | Rust (M2, 8 threads) | Research C++ |
|---|---|---|
| menus | 60 s | 160 s on 4 threads |
| trees | 73 s | 141 s on 4 threads |

The wall-clock gain comes from using more threads, not from faster code.

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

The tests are small checks:
- the pegging rules and every branch of the legacy heuristic;
- the menu records, and trees that round-trip and end in the heuristic's
  own margins;
- every subcommand of the binary, its exit codes and its argument errors,
  on output folders small enough for a test.

They cannot show equivalence with the research C++. That evidence comes from
the full-size runs above. A later manual workflow is planned to repeat them
on Actions.
