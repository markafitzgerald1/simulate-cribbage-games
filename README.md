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
- Simulate and summarize play of 5,000 reasonably well discarded and played hand pairs: `python simulateCribbageGames.py --game-count 5000 --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions`;
- Simulate and summarize play of 2,500 reasonably well discarded and played games: `python simulateCribbageGames.py --game-count 2500 --games-per-update 500 --unlimited-hands-per-game --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions`;
- Simulate and summarize play of 1,000 games with random first pone play against reasonably good first dealer play: `python simulateCribbageGames.py --game-count 1000 --games-per-update 500 --unlimited-hands-per-game --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions --first-pone-keep-random --first-pone-play-random`;
- Simulate and summarize play of 1,000 games with reasonably good first pone play against random first dealer play: `python simulateCribbageGames.py --game-count 1000 --games-per-update 500 --unlimited-hands-per-game --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions --first-dealer-keep-random --first-dealer-play-random`;
- Simulate a fixed pone hand and discard against random reasonably well discarded and played dealer hands: `python simulateCribbageGames.py --first-pone-dealt-cards AC,2D,3H,4S,5C,6D --first-pone-kept-cards 2D,3H,4S,5C --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions --game-count 5000`;
- Simulate a fixed pone hand and discard against random reasonably discarded and played dealer hands with two parallel processes: `python simulateCribbageGames.py --first-pone-dealt-cards AC,2D,3H,4S,5C,6D --first-pone-kept-cards 2D,3H,4S,5C --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions --game-count 5000 --process-count 2`;
- Simulate to the end of single hand play a fixed dealer hand and discard against random pone hands: `python simulateCribbageGames.py --first-dealer-dealt-cards AC,2D,3H,4S,5C,6D --first-dealer-kept-cards AC,2D,3H,4S --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions --game-count 5000`;
- Simulate all possible discards from a fixed pone hand against random dealer hands: `python simulateCribbageGames.py --first-pone-dealt-cards AC,2D,3H,4S,5C,6D --first-pone-select-each-possible-kept-hand --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions --games-per-update 1000 --game-count 10000`;
- Simulate all possible discards from a fixed dealer hand against random pone hands: `python simulateCribbageGames.py --first-dealer-dealt-cards AC,2D,3H,4S,5C,6D --first-dealer-select-each-possible-kept-hand --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions --games-per-update 1000 --game-count 10000`;
- Simulate all possible discards from a fixed dealer hand against random pone hands at a greater than 0-0 game score: `python simulateCribbageGames.py --first-dealer-dealt-cards JH,TS,6S,6C,4C,AD --first-dealer-select-each-possible-kept-hand --initial-pone-score 105 --initial-dealer-score 117 --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions --game-count 20000 --games-per-update 2000`;
- Simulate all possible leads from a fixed pone hand and discard against random dealer hands: `python simulateCribbageGames.py --first-pone-dealt-cards JH,TS,6S,6C,4C,AD --first-pone-kept-cards TS,6S,4C,AD --select-each-post-initial-play --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions --game-count 30000 --games-per-update 3000`;
- Simulate all possible leads from a fixed pone kept hand against random dealer hands: `python simulateCribbageGames.py --first-pone-kept-cards TS,6S,4C,AD --select-each-post-initial-play --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions --game-count 30000 --games-per-update 3000`;
- Simulate all possible leads from a partially known pone kept hand against random dealer hands: `python simulateCribbageGames.py --first-pone-kept-cards 4C,AD --select-each-post-initial-play --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions --game-count 30000 --games-per-update 3000`;
- Simulate all possible pone plays with known pone discard from a mid-play position (dealer hand now partially known): `python simulateCribbageGames.py --first-pone-dealt-cards KC,QD,TC,8S,4D,AH --first-pone-kept-cards QD,TC,4D,AH --initial-play-actions 4D,8H --select-each-post-initial-play --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions --game-count 20000 --games-per-update 2000`;
- Simulate all possible pone plays with an unknown discard from a mid-play position (pone hand now partially known): `python simulateCribbageGames.py --first-pone-kept-cards QD,TC,4D,AH --initial-play-actions 4D,8H --select-each-post-initial-play --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions --game-count 20000 --games-per-update 2000`;
- Simulate all possible pone plays from a mid-play position late in the game to end of game: `python simulateCribbageGames.py --first-pone-kept-cards 6s,6h,7c,ks --select-each-post-initial-play --infinite-game-count --games-per-update 1000 --unlimited-hands-per-game --initial-pone-score 106 --initial-dealer-score 106 --initial-play-actions 6s,ts --hide-play-actions --hide-first-pone-hand --hide-first-dealer-hand`;
- Simulate all possible dealer plays from a mid-play position against partly known pone kept and fully known dealer dealt and kept hands: `python simulateCribbageGames.py --first-dealer-dealt-cards 8C,4D,TH,9S,KC,KD --first-dealer-kept-cards 8C,4D,TH,9S --initial-play-actions 4C --select-each-post-initial-play --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions --game-count 20000 --games-per-update 2000`;
- Simulate all possible dealer plays from a mid-play position with unknown discard against partly known pone and fully known dealer kept hands: `python simulateCribbageGames.py --first-dealer-kept-cards 8C,4D,TH,9S --initial-play-actions 4C --select-each-post-initial-play --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions --game-count 20000 --games-per-update 2000`;
- Simulate all possible pone plays from a mid-play position against partly known dealer hands where the already executed pone play is not what the play strategy in use would have selected: `python simulateCribbageGames.py --first-pone-dealt-cards 2s,4h,9s,9c,7c,qh --first-pone-kept-cards 2s,4h,9s,9c --initial-play-actions 9c,qs --select-each-post-initial-play --infinite-game-count --hide-play-actions --hide-first-pone-hand --hide-first-dealer-hand --process-count 2`;
- Simulate all possible dealer plays from a mid-play position where the already executed dealer discard is not what the dealer discard strategy would have discarded: `python simulateCribbageGames.py --first-dealer-dealt-cards 2d,3h,6h,8d,9d,qc --first-dealer-kept-cards 2d,3h,8d,qc --initial-play-actions 4c,8d,kd --select-each-post-initial-play --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions --game-count 20000 --games-per-update 1000`;
- Simulate all possible dealer plays from start of the second play where dealer has two more cards than pone: `python simulateCribbageGames.py --first-dealer-kept-cards tc,3s,8c,9h --initial-play-actions th,tc,td,go,ac,go,go --select-each-post-initial-play --game-count 20000 --games-per-update 2000 --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions`;
- Simulate from late in the third leg all possible dealer discards to end of game against reasonable opponent play: `python simulateCribbageGames.py --first-dealer-dealt-cards AC,2S,6C,TD,JD,KC --first-dealer-select-each-possible-kept-hand --hide-first-pone-hand --hide-first-dealer-hand --hide-play-actions --unlimited-hands-per-game --game-count 20000 --initial-pone-score 87 --initial-dealer-score 85 --games-per-update 1000`; and
- Simulate one hand from deal to end of hand counting using simulation-based pone and dealer discarding: `python simulateCribbageGames.py --process-count 1 --game-count 1 --first-pone-discard-based-on-simulations 320 --first-dealer-discard-based-on-simulations 320`.

## Long-term project goal

Provide efficient, user-friendly discard and play analysis factoring
in the expected game points differential (and play points differential if no game points differential) to end of hand(s) or game above opponent
for different possible discards or plays.

## Definite pre-first version or release goals
- Further improve current best play strategy:
  - add simulation-based pone and dealer play strategies;
- Add support for time-limited discard simulations and simulation-based discard strategies.

## Maybe pre-first version or release goals
- UI/UX improvements:
  - add a 'coach mode': show the user computer recommended action after user has taken a play (including discard) action.
- Improve both discard and play strategies:
  - Implement simulation-based discard and play where immediate opponent reponse is also simulation-based but based on fewer simluated games.

## Probably not pre-first version or release goals
- Improve simulation-based discard strategy:
  - Implement simulation-based discard and play where multiple subsequent opponent or self play or discard actions are also simulation-based but based on fewer simluated games. (Keys to success: tuning of decay factor; determining whether the positional evaluation benefits of low (< 32 for discard, for example) simulation counts outweigh their higher error rate costs.)
- Improve play simulation and play simulation based play accuracy:
  - Factor the minimum possible count value of all remaining opponent cards implied by saying Go into play simulations and play simulation based play.
- Improve current best non-simulation-based play strategy:
  - consider dealer respond with higher card of pair adding to 11 in response to pone 10 count lead to set up more 31-2's for self - e.g. dealer play 7 from 7-4 or 8 from 8-3 in response to pone 10 count lead;
  - reconsider adding run setup avoidance to default play strategy; and
  - consider improving default play algorithm to lead from high (> 5) pair (e.g. 9 from T-9-9-6) when low lead not possible (1.2 points better than T lead based on simulations).
- Improve development speed and quality:
  - Automate execution and verification of above smoke tests.

## Post-first version or release short to medium term goals
- Further improve current best discard strategy:
  - reconsider not ignoring suit by default and not ignoring suit in simulation-based discard strategy.
- UI/UX improvements:
  - improve user interface via which human players can play against implemented computer discard and play strategies;
  - add support for --(pone|dealer)-(dealt|kept)-cards and --initial-play-actions lacking suit information; and
- Improve development speed and quality:
  - Increase confidence in implementation by adding further type hints (Python), type checking and unit tests.
- Improve simulation-based play and discard speed and strength:
  - Increase performance and simulation-based play strategy strengths via performance improvements in Python or other programming language.

## Current known bugs

- First pone and first dealer win percentages do not always exactly add up to 1 and standard deviations do not equal in 10,000+ game simulations. (They do add up to 1 and have equal standard deviations in <= 5,000 game simulations.) Perhaps just a rounding error in runstats/Statistics, but perhaps a bug?

## Past project goals

- UI/UX improvements:
  - add `--first-(pone|dealer)-keep-user-entered` discard strategy allow for complete human play against this program (status: implemented);
  - accept card instead of hand index entry on play select (status: implemented);
  - allow user to press enter when they have only one play option or must say Go (status: implemented);
  - show score after every score change (status: implemented);
  - replace `--(pone|dealer)-play-user-entered` with `--first-(pone|dealer)-play-user-entered` and do same for all other possible play algorithm selections so that a human can play against a consistent computer opponent and so that two different computer opponents can be compared in multi-hand games - likely necessary to improve play when a small but greater than 1 number of hands remain - i.e. in a positional play position.
- Further improve current best play strategy:
  - add support for --initial-starter specification to slightly improve simulation-based play accuracy;
  - consider improving default play algorithm to lead A from A-4 (e.g. A-4-T-T), which seems to be about 0.08 points better than a 4 lead according to current simulations with two Tens (status: rejected - 4 and A about equal leads holding both; similar for lead from 2-3 - about equal leads as pone); and
  - consider improving default play algorithm to lead 3 from 3-9 (e.g. 3-4-8-9) which seems better than a 4 lead if only because a dealer 3 response can be 15-2'ed to even the play score. Similar lead 4 from 4-7 should also be considered here (status: rejected - 0.005 +/- 0.014 points worse for pone in simulations).
- Add play decision analysis support by allowing the set of the initial simulation state to all post-discard, post-initial play states and then simulating all possible next plays to the end of the hand (or multiple hands):
  - add support for play simulations without specifying player not under simulation dealt or kept cards - can be inferred from --initial-play-actions (status: implemented),
  - add support for play simulations without specifying player under simulation dealt but not kept (discarded) cards - often not known, remembered or all that relevant (status: implemented);
  - add support for --initial-play-actions containing a Go (status: implemented),
  - add support for --initial-play-actions containing two consecutive Gos - i.e. a count reset (status: implemented);
- BUG: --initial-play-actions 9-4-9 with 4,4,8 in dealer hand not simulatable because current best play algorithm would have played 8 on first played card. Same is true of simulation of --initial-play-actions 9-Q with 9-4-2 in pone hand. (Fix requires possibly not assuming that future plays would match that of the best non-simulation-based play algorithm. Separate TODO to not respond to 9 lead with 8 setting up two possible opponent run plays below.) (Status: fixed.)
- BUG: --initial-play-actions 4-8 with A,T,Q in pone hand considers T and Q to be equal plays as the current best non-simulation-based play algorithm would have played 9 on its first play as dealer if it held it thus the simulation does not consider a run off of 4-8-T to be possible for dealer. (Status: fixed.)
- BUG: simulation of all possible plays over just one game fails to complete on a ZeroDivisionError during variance calculation. (Status: fixed.)
- Stop discard/play simulation and simulation-based discard when only one non-dropped option remains.
- In single all possible discards simulations and simulation-based discard strategy drop possible discards 2 standard deviations worse beyond the current selected confidence level than the current best discard as simulation proceeds save time and get better answers faster.
- Discard based on expected hand value ignoring suit when neither flush nor nobs is possible in both maximize hand points and maximize hand +/- crib points discard strategies. This allows suit to be factored into discard decisions more often as discard maximizing hand value was sped up 75% while discard maximizing hand +/- crib points was sped up about 33%.
- Evaluate faster way of factoring expected crib points into discard factoring in suit post-cut discard strategies. (Approach using disk cache increased discard strategy speed from unusuable on my laptop 6 seconds per hand discard pair to 60 discard pairs per second, an approximately 375x speed improvement. Play strength gains are small - about 0.10 +/- 0.07 points per hand (95% confidence interval) for pone and 0.043 +/- 0.041 points per hand for dealer - thus not using this as the default discard strategy at present.
- Evaluate faster way of factoring expected crib points into discard ignoring suit post-cut discard strategies. (Approach was included as default discard strategy - about as effective as factoring in held cards but only about 20% slower than not factoring in crib value at all.)
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
