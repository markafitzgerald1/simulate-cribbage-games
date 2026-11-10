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
operation order and uses no fused multiply-add, so its outputs can match the
research files byte for byte.

The generator arrives in stacked pull requests. This first one holds the pegging
rules every later module walks. Menus, trees and offsets come next, then the
solve, then the support bits.

## What each module mirrors

| Module | Research source | Output |
|---|---|---|
| `game.rs` | `joint::State` in `cfr_joint_native.hpp` | rank-only pegging rules and the legacy heuristic |

## Validation

```sh
cargo fmt --check
cargo clippy --locked --release --all-targets -- -D warnings
cargo test --locked --release
RAYON_NUM_THREADS=1 cargo llvm-cov --locked --release --fail-under-lines 100 --show-missing-lines
pmd cpd --language rust --minimum-tokens 40 --dir src
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

The tests are small checks of the pegging rules and every branch of the
legacy heuristic.

They cannot show equivalence with the research C++. That evidence comes from
full-size runs compared with the research digests, which arrive with the
modules that write those files.
