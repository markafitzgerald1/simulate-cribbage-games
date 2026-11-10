# cfr-inputs

Regenerates the inputs of the six-layer CFR pegging policy that the #203
fixed-policy play-table measurement pins:

- the optional-decision menus;
- the per-Pone-hand game trees;
- the action offsets;
- the CFR+ mixture policy and its exact certificate;
- the counterfactual support bits.

It is a port of the unpublished research C++ (`stream.cpp`, `offsets.cpp`,
`support.cpp` and the header `cfr_joint_native.hpp`). It keeps the same
operation order and uses no fused multiply-add, so its outputs match the
research files byte for byte.

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
`92f3bb24...`, built from the top of this stack of pull requests. Menus,
trees and offsets match the research files byte for byte. The checks covered
all 3,640 menus against PR A's manifest, all 1,820 trees against the research
tree digests, and the offsets.

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
  each exemption.
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
