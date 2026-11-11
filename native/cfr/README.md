# cfr-inputs

Generates the inputs of the six-layer CFR pegging policy (issue #203): a
fixed pegging policy, solved with CFR+, that the play-table measurement uses
for every real choice either player makes during the play.

## What it generates

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

**Why 1,820 and 3,640.** Hands are rank-only: nothing in the play scores by
suit, so suits are dropped. A four-card hand is then a multiset of ranks,
because ranks can repeat (5-5-J-K). The number of multisets of size k drawn
from n kinds is C(n + k - 1, k), so there are C(13 + 4 - 1, 4) = C(16, 4) =
1,820 hands. (C(13, 4) = 715 would count only hands with four different
ranks.) No rank can appear more than four times in four cards, so every one
of them can be dealt. Each hand can be held by Pone or by Dealer, which gives
3,640 hand-and-seat pairs.

**The six layers.** The policy makes every real choice in the hand: each
seat's first three cards, wherever more than one rank is legal. Two seats
times three cards are the six layers; a seat's fourth card is always forced.

**Forced moves.** Where only one move is possible (one legal rank, a go, or a
player's last card), the generator plays it. Menu records keep one reserved
byte, always 0.

## Why the output is correct

Each part of the evidence lives in this repository:

- **The pegging rules** (`game.rs`): unit tests whose expected values are
  worked out by hand from the cribbage rules, one per scoring case, and a
  check against the published Python engine, an independent implementation.
  `artifact_pipeline/pegging_golden.py` plays about 8,000 deals with
  `simulate_pegging` under a fixed choice rule and writes each deal's final
  points to `tests/pegging_golden.txt`; `tests/rules.rs` replays them with
  `State` and must match every line, and a Python test checks the file is
  current.

The generator arrives in stacked pull requests. This first one holds the
pegging rules every later module walks. Menus, trees and offsets come next,
then the solve, then the support bits; each adds its own evidence above.

## Why Rust

- **Memory safety at C++-class speed:** a compiled systems language with the
  speed and control of C++ and no garbage collector, whose compiler checks
  memory safety; `unsafe` is forbidden here.
- **Safe parallelism:** the compiler rules out data races, and the rayon
  thread-pool library spreads the work across cores. Tests check that the
  solver's numerical outputs are identical for 1 to 4 threads on a small game;
  the full-size run used 8.

## Port history

This package began as a port of unpublished research code in C++. Nothing here
depends on that code: every input the project ships is generated from this
repository's source.

## Floating-point order

The solver adds its floating-point terms in a fixed order, with no fused
multiply-add, so its output bytes are reproducible. That order may change, but
a change can alter the low bits of the policy, so it needs the full-size check,
and a re-pin and fresh certificates if the bytes change.

## What each module does

| Module | Output |
|---|---|
| `game.rs` | rank-only pegging rules and the forced move |

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
  each exemption, and `min_ident_chars` rejects one-letter names outside
  clippy's default short list (i, j, n, w, x, y, z).
- **Coverage:** 100% of lines.
- **Copy/paste:** PMD 7 CPD at the TypeScript threshold of 40 tokens.
- **Dependencies:** `deny.toml` fails on RustSec advisories, yanked crates,
  licenses other than MIT, Apache-2.0 or MPL-2.0, duplicate versions and
  unknown sources. Dependabot watches `Cargo.lock`.
