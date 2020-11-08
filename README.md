# Play Cribbage Hand

Simulate and analyze the play of cribbage hands between two opponents.

## Setup

- Install Python 3.9.0
- `pip install -r requirements.txt` _(may require local admin to install black globally... or use a [virtualenv](https://virtualenv.pypa.io/en/latest/) instead!)_

## Test

- Check for type errors - should only fine one about `runstats` module not having type hints: `mypy playCribbageHand.py`

## Use

- Simulate one hand from deal to end of hand counting: `python playCribbageHand.py`
- Help on additional simulation options: `python playCribbageHand.py --help`

## Smoke Tests

All of the following should exit with status code 0 and no raised exception:

- Simulate a single random hand: `python playCribbageHand.py`;
- Simulate a fixed dealer hand and discard against random pone hands: `python playCribbageHand.py --dealer-dealt-cards AC,2D,3H,4S,5C,6D --dealer-kept-cards 3H,4S,5C,6D --pone-keep-first-four --pone-play-first --dealer-play-first --hide-pone-hand --hide-dealer-hand --hide-play-actions --hand-count 1000`;
- Simulate a fixed pone hand and discard against random dealer hands: `python playCribbageHand.py --pone-dealt-cards AC,2D,3H,4S,5C,6D --pone-kept-cards 3H,4S,5C,6D --dealer-keep-first-four --pone-play-first --dealer-play-first --hide-pone-hand --hide-dealer-hand --hide-play-actions --hand-count 1000`;
- Simulate all possible discards from a fixed dealer hand against random pone hands: `python playCribbageHand.py --dealer-dealt-cards AC,2D,3H,4S,5C,6D --dealer-keep-each-possibility --pone-keep-first-four --pone-play-first --dealer-play-first --hide-pone-hand --hide-dealer-hand --hide-play-actions --hand-count 1500`; and
- Simulate all possible discards from a fixed pone hand against random dealer hands: `python playCribbageHand.py --pone-dealt-cards AC,2D,3H,4S,5C,6D --pone-keep-each-possibility --dealer-keep-first-four --hide-pone-hand --hide-dealer-hand --hide-play-actions --hand-count 1500`.

## Long-term project goal

Provide efficient discard and play analysis factoring
in the expected play points differential - to end of hand - above opponent
for different possible discards or plays.

## Current short to medium term goals

- Improve realism and usefulness/credibility of simulated discards by adding higher-scoring discard and play strategy options;
- Add endgame analysis support by allowing the initial simulation score to be set to non-zero and recording win percentages to end of hand (or multiple hands);
- Add play decision analysis support by allowing the set of the initial simulation state to a post-discard, start or middle of play state and then simulating all possible initial plays to the end of the hand (or multiple hands); and
- Increase confidence in implementation by adding type hints (Python), type checking and unit tests.

## Past project goal

Select best language with which to implement this
given the longer term goal of providing discard and play analysis factoring
in the expected play points differential - to end of hand - above opponent
for different possible discards or plays.

_Result:_ decided to go with Python to start then reimplement in Node.js when and/or if reimplementation cost is less than the time spent waiting for Python-based simulations to complete.

## Technology stack

### Currently tested project toolchain versions

#### Main implementation

- Python 3.9.0

#### Backup, partial implementation

- Node.js 14.5.0

#### Prototype benchmarking implementations

- Java OpenJDK 14.0.1,
- GCC 8.1.0 (non-parallel),
- GCC 10.2.0 (parallel),
- C#.NET Core 3.1.302.
