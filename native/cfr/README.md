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
- **Menus and trees** (`menus.rs`, `trees.rs`): menu records are checked for
  order and parent links, and the builder asserts perfect recall (the same
  public history always implies the same earlier own decision and the same
  legal ranks). A tree survives a round trip through its file format, and a
  walk of every edge alongside a replay of the rules checks each node's menu
  and each leaf's margin. The binary's subcommands, exit codes and argument
  errors are tested on output folders small enough for a test.
- **Determinism:** menus, trees and offsets depend on no prior: they are
  fixed by the pegging rules, the canonical hand order and the file format.
  Their digests are in `digests.json` under `reproducible`, and every build
  of this source must reproduce them. The generation workflow (#235) checks
  them before every solve; that check has not yet run on Actions.

The generator arrives in stacked pull requests. This one adds the menus,
trees and offsets. The solve and the support bits follow, each adding its
own evidence above.

## Why Rust

- **Throughput:** native code with no runtime or garbage collector, so more
  simulation fits in the same time, which tightens error bounds.
- **Safe parallelism:** the compiler rules out data races, `unsafe` is
  forbidden here, and rayon spreads the work across cores while the numerical
  outputs stay byte-identical for any thread count.
- **Memory safety at C++-class speed:** a systems language with the speed
  and control of C++, whose compiler checks memory safety as well as ruling
  out data races, so the parallel work this generator needs is safer to
  write.

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
| `menus.rs` | `menus/{k}.bin`, 3,640 files |
| `trees.rs` | `trees/{p}.bin`, 1,820 files; `offsets.bin` |

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
printed values can be compared with `digests.json`.

## Evidence

Measured on an Apple M2 with 8 threads, 2026-11-11: menus took 74 s, offsets
3 s and trees 64 s, and all three outputs matched the `reproducible` digests in
`digests.json`.

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
