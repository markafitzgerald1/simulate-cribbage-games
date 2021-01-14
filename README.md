# Play Cribbage Hand

Simulate and analyze the play of cribbage hands between two opponents.

## Setup

- Install Python 3.9.1
- `pip install -r requirements.txt` _(may require local admin to install black globally... or use a [virtualenv](https://virtualenv.pypa.io/en/latest/) instead!)_

## Test

- Check for type errors - should only find one about `runstats` module not having type hints: `mypy simulateCribbageGames.py`

## Use

- Simulate one hand from deal to end of hand counting: `python simulateCribbageGames.py`
- Help on additional simulation options: `python simulateCribbageGames.py --help`

## Smoke Tests and Usage Examples

All of the following should exit with status code 0 and no raised exception:

- Simulate play of 10 reasonably well discarded and played hands of cribbage: `python simulateCribbageGames.py --game-count 10`;
- Simulate play of 10 reasonably well discarded and played games of cribbage: `python simulateCribbageGames.py --game-count 10 --unlimited-hands-per-game`;
- Simulate and summarize play of 5,000 reasonably well discarded and played hand pairs: `python simulateCribbageGames.py --game-count 5000 --hide-pone-hand --hide-dealer-hand --hide-play-actions`;
- Simulate a fixed pone hand and discard against random reasonably well discarded and played dealer hands: `python simulateCribbageGames.py --pone-dealt-cards AC,2D,3H,4S,5C,6D --pone-kept-cards 2D,3H,4S,5C --hide-pone-hand --hide-dealer-hand --hide-play-actions --game-count 5000`;
- Simulate a fixed pone hand and discard against random reasonably discarded and played dealer hands with two parallel processes: `python simulateCribbageGames.py --pone-dealt-cards AC,2D,3H,4S,5C,6D --pone-kept-cards 2D,3H,4S,5C --hide-pone-hand --hide-dealer-hand --hide-play-actions --game-count 5000 --process-count 2`;
- Simulate to the end of single hand play a fixed dealer hand and discard against random pone hands: `python simulateCribbageGames.py --dealer-dealt-cards AC,2D,3H,4S,5C,6D --dealer-kept-cards AC,2D,3H,4S --hide-pone-hand --hide-dealer-hand --hide-play-actions --game-count 5000`;
- Simulate all possible discards from a fixed pone hand against random dealer hands: `python simulateCribbageGames.py --pone-dealt-cards AC,2D,3H,4S,5C,6D --pone-select-each-possible-kept-hand --hide-pone-hand --hide-dealer-hand --hide-play-actions --games-per-update 10000 --game-count 10000`;
- Simulate all possible discards from a fixed dealer hand against random pone hands: `python simulateCribbageGames.py --dealer-dealt-cards AC,2D,3H,4S,5C,6D --dealer-select-each-possible-kept-hand --hide-pone-hand --hide-dealer-hand --hide-play-actions --games-per-update 10000 --game-count 10000`;
- Simulate all possible discards from a fixed dealer hand against random pone hands at a greater than 0-0 game score: `python simulateCribbageGames.py --dealer-dealt-cards JH,TS,6S,6C,4C,AD --dealer-select-each-possible-kept-hand --initial-pone-score 105 --initial-dealer-score 117 --hide-pone-hand --hide-dealer-hand --hide-play-actions --game-count 20000`;
- Simulate all possible leads from a fixed pone hand and discard against random dealer hands: `python simulateCribbageGames.py --pone-dealt-cards JH,TS,6S,6C,4C,AD --pone-kept-cards TS,6S,4C,AD --select-each-post-initial-play --hide-pone-hand --hide-dealer-hand --hide-play-actions --game-count 30000`;
- Simulate all possible pone plays from a mid-play position against partly known dealer hands: `python simulateCribbageGames.py --pone-dealt-cards KC,QD,TC,8S,4D,AH --pone-kept-cards QD,TC,4D,AH --dealer-dealt-cards 8H --initial-played-cards 4D,8H --select-each-post-initial-play --hide-pone-hand --hide-dealer-hand --hide-play-actions --game-count 20000`;
- Simulate all possible dealer plays from a mid-play position against partly known pone and fully known dealer hands: `python simulateCribbageGames.py --dealer-dealt-cards 8C,4D,TH,9S,KC,KD --dealer-kept-cards 8C,4D,TH,9S --pone-dealt-cards 4C --initial-played-cards 4C --select-each-post-initial-play --hide-pone-hand --hide-dealer-hand --hide-play-actions --game-count 20000`;
- Simulate from late in the third leg all possible dealer discards to end of game against reasonable opponent play: `python simulateCribbageGames.py --dealer-dealt-cards AC,2S,6C,TD,JD,KC --dealer-select-each-possible-kept-hand --hide-pone-hand --hide-dealer-hand --hide-play-actions --unlimited-hands-per-game --game-count 20000 --initial-pone-score 87 --initial-dealer-score 85`;
- Simulate one hand from deal to end of hand counting using simulation-based pone discarding: `python simulateCribbageGames.py --process-count 1 --game-count 1 --pone-discard-based-on-simulations 320`;
- Simulate one hand from deal to end of hand counting using simulation-based dealer discarding: `python simulateCribbageGames.py --process-count 1 --game-count 1 --dealer-discard-based-on-simulations 320`; and
- Simulate one hand from deal to end of hand counting using simulation-based pone and dealer discarding: `python simulateCribbageGames.py --process-count 1 --game-count 1 --pone-discard-based-on-simulations 320 --dealer-discard-based-on-simulations 320`.

## Long-term project goal

Provide efficient, user-friendly discard and play analysis factoring
in the expected game points differential (and play points differential if no game points differential) to end of hand(s) or game above opponent
for different possible discards or plays.

## Current short to medium term goals

- Add play decision analysis support by allowing the set of the initial simulation state to all post-discard, post-initial play states and then simulating all possible next plays to the end of the hand (or multiple hands);
- Add support for time-limited discard simulations and simulation-based discard strategies.
- Reconsider not ignoring suit by default and not ignoring suit in simulation-based discard strategy.
- Add simulation-based pone and dealer play strategies.
- Improve user interface via which human players can play against implemented computer discard and play strategies.
- Implement simulation-based discard and play where immediate opponent reponse is also simulation-based but based on fewer simluated games.
- Implement simulation-based discard and play where multiple subsequent opponent or self play or discard actions are also simulation-based but based on fewer simluated games.  (Keys to success: tuning of decay factor; determining whether the positional evaluation benefits of low (< 32 for discard, for example) simulation counts outweigh their higher error rate costs.)
- Automate execution and verification of above smoke tests.
- Increase confidence in implementation by adding further type hints (Python), type checking and unit tests.
- Increase performance and simulation-based play strategy strengths via performance improvements in Python or other programming language.

## Current known bugs

- First pone and first dealer win percentages do not always exactly add up to 1 and standard deviations do not equal in 10,000+ game simulations.  (They do add up to 1 and have equal standard deviations in <= 5,000 game simulations.)  Perhaps just a rounding error in runstats/Statistics, but perhaps a bug?

## Past project goals

- Stop discard/play simulation and simulation-based discard when only one non-dropped option remains.
- In single all possible discards simulations and simulation-based discard strategy drop possible discards 2 standard deviations worse beyond the current selected confidence level than the current best discard as simulation proceeds save time and get better answers faster.
- Discard based on expected hand value ignoring suit when neither flush nor nobs is possible in both maximize hand points and maximize hand +/- crib points discard strategies.  This allows suit to be factored into discard decisions more often as discard maximizing hand value was sped up 75% while discard maximizing hand +/- crib points was sped up about 33%.
- Evaluate faster way of factoring expected crib points into discard factoring in suit post-cut discard strategies.  (Approach using disk cache increased discard strategy speed from unusuable on my laptop 6 seconds per hand discard pair to 60 discard pairs per second, an approximately 375x speed improvement.  Play strength gains are small - about 0.10 +/- 0.07 points per hand (95% confidence interval) for pone and 0.043 +/- 0.041 points per hand for dealer - thus not using this as the default discard strategy at present.
- Evaluate faster way of factoring expected crib points into discard ignoring suit post-cut discard strategies.  (Approach was included as default discard strategy - about as effective as factoring in held cards but only about 20% slower than not factoring in crib value at all.)
- Incorporate expected post-cut value of held Jack into discard algorithms otherwise ignoring suit - should be a cheap to compute discard improvement. (Abandoned as benefit to pone did not show with statistical significance over more hands than anyone would play in a lifetime (about 5 million) and was if anything a slight loss for dealer.)
- Add simulation-based pone discard strategy.
- Add multiple played hands or played hands to end of game simulation support.
- Add play decision analysis support by allowing the set of the initial simulation state to a post-discard, start or middle of first play to 31 state and then simulating all possible initial plays to the end of the hand (or multiple hands).
- Provide efficient discard and play analysis factoring
  in the expected play points differential - to end of hand - above opponent
  for different possible discards or plays. (Extended to multi-hand or end of game with _game_ points differential also added as ultimate goal is winning - scored hand/play points is just a proxy for ultimately scored _game_ points.)
- Add endgame analysis support by allowing the initial simulation score to be set to non-zero and recording win percentages to end of hand (or multiple hands);
- Improve realism and usefulness/credibility of simulated discards by adding higher-scoring discard and play strategy options; and
- Select best language with which to implement this
  given the longer term goal of providing discard and play analysis factoring
  in the expected play points differential - to end of hand - above opponent
  for different possible discards or plays. (_Result:_ decided to go with Python to start then reimplement in Node.js when and/or if reimplementation cost is less than the time spent waiting for Python-based simulations to complete.)

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
