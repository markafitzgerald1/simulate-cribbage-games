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
  each exemption, and `min_ident_chars` rejects one-letter names.
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
