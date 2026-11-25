Expected pegging points for every four-card keep and both seats, measured by self-play of the solved CFR pegging policy.

**Promotion gate (enforce):** passed. E(deltaP) was measured with the trained pegging policies.

Trained minus legacy heuristic, points per hand (mean +/- standard error) over 200000 duplicate deals: both seats +0.2218 +/- 0.0032; Pone +0.2326 +/- 0.0057; Dealer +0.2110 +/- 0.0050.

- Measured by [run 45535004794](https://github.com/markafitzgerald1/simulate-cribbage-games/actions/runs/45535004794) at commit e85fea370413c5eed890f9562b91408e12acf648, with 13,000 samples per cell.
- The keeps that each seat faces come from a fixed discard population. It has not converged and was not refined with this pegging policy; the table records both limits.
- The policy and the table use card ranks only.

## Scorecard

Bots played duplicate deals, 500,000 pairs of games per row with the seats swapped. Every bot picks its discards by hand, plus or minus crib, plus one play table, with the same crib table (v4). 50% is parity. Each figure is the first bot's win rate, plus or minus one standard error in percentage points; the rows are not adjusted for multiple comparisons.

| First bot | Second bot | First bot wins |
|---|---|---|
| This table, CFR pegging | App's table, CFR pegging | 50.287% +/- 0.027 |
| This table, heuristic pegging | App's table, heuristic pegging | 49.724% +/- 0.023 |
| This table, CFR pegging | Previous release, CFR pegging | 50.885% +/- 0.029 |
| This table, heuristic pegging | Previous release, heuristic pegging | 48.912% +/- 0.026 |
| App's table, CFR pegging | App's table, heuristic pegging | 55.638% +/- 0.029 |

Against one fixed bot that uses neither table and pegs with the heuristic, this table's discards change the win rate by +0.032 +/- 0.025 points when paired with CFR pegging, and by -0.167 +/- 0.025 points when paired with heuristic pegging, compared with the app's table's discards on the same deals.

So a table does better in the pegging style it was measured in. This table's advantage is established for players who peg like the CFR policy, not for the heuristic and not for people: these are matches between bots. The last row of the table is the value of pegging itself, which a discard table does not teach. The matches were run on one laptop with an unpublished match program; the tables and policy they read are the released bytes and the measurement's pinned inputs.

## Table history

| Table | Client means SHA-256 | Measured with | Status |
|---|---|---|---|
| June 2026 | `7420b180` | The trained pegging policy of the time, both seats | In the app until it vendors a newer one |
| Version 3, 2026-11-22 | `6ed3a051` | The legacy heuristic, both seats | The previous release, replaced by this one |
| October 2026 research | `41ddcbd6` | An earlier CFR pegging policy, both seats | Never released |
| This release | `4ef452e2` | The solved CFR pegging policy (`647b3830`), both seats | Current |

## Files

- `expected_play_points.json`: paired sampling statistics and point-type details.
- `expected_play_points.client.json`: the lean table the browser reads.
- `expected_play_points.uncertainty.json`: marginal uncertainty for the client means (see `docs/uncertainty-sidecars.md`).
- `expected_play_points.lines.json`: observed first-exchange lines (see `docs/pegging-lines.md`).
