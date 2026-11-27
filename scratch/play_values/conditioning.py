"""How much do first- and second-play values move when the opponent's hand
is conditioned on the cards the player can see (own six and the starter)?

Usage:
  python conditioning.py build BUNDLE DEALS SEED SCENARIOS.bin
  python conditioning.py compare BUNDLE SCENARIOS.bin ROWS.bin VALUES.bin OUT.json

`build` deals DEALS physical hands and, for each seat of each deal, writes
three opponent distributions over the 1,820 kept hands. The player's own
kept hand comes from the pinned discard population.

- baseline: the prior row of the kept hand, exactly what the spike's values
  use;
- mixture: `artifact_pipeline/cfr_prior.py`'s two components (uniform
  four-card hands, and six-card hands mapped through the population's keeps)
  with the opponent's cards drawn from the 45 unseen cards, each component
  keeping the share it has in the prior row. This is a card-removal
  sensitivity test with the mixture shares held fixed, not a posterior: once
  the six and the starter are seen, those shares are a modelling choice;
- population: the production component alone, conditioned the same way,
  i.e. the opponent discards by the pinned population.

`compare` values each scenario's decisions with `play-values rows` output
and measures how far the conditioned values move from the baseline.
Standard library only.
"""

import bisect
import json
import math
import os
import random
import struct
import sys
from itertools import combinations_with_replacement

PONE, DEALER = 0, 1
ROLES = {"Pone": PONE, "Dealer": DEALER}
SCALE = 1 << 50
VARIANTS = {"mixture": 0, "population": 1 << 20, "baseline": 2 << 20}
SCENARIO_MASK = (1 << 20) - 1
RECORD = struct.Struct("<IBxH")
ROW = struct.Struct("<IIBBxxdd4d")
VALUE_ROW = struct.Struct("<IBBxxdd4d")
TIE = 0.005
BANDS = [0.005, 0.05, 0.1, 0.25]


def rank_hands(size):
    return [
        hand
        for hand in combinations_with_replacement(range(13), size)
        if max(hand.count(rank) for rank in set(hand)) <= 4
    ]


def counts(hand):
    out = [0] * 13
    for rank in hand:
        out[rank] += 1
    return out


def ways(hand_counts, available):
    product = 1
    for rank, count in enumerate(hand_counts):
        if count:
            if count > available[rank]:
                return 0
            product *= math.comb(available[rank], count)
    return product


def integer_weights(shares):
    # Rounded to integers with a total near 2^50; `rows` divides by the
    # actual total, so the rounding changes no normalization.
    norm = sum(shares)
    return [round(SCALE * share / norm) for share in shares]


def build(bundle, deals, seed, out):
    with open(f"{bundle}/population.json") as handle:
        population = json.load(handle)
    keep = {
        (ROLES[role], tuple(hand)): tuple(kept)
        for role, hand, kept in population["keeps"]
    }
    fours = rank_hands(4)
    four_index = {hand: i for i, hand in enumerate(fours)}
    sixes = [(hand, counts(hand)) for hand in rank_hands(6)]
    full = [4] * 13
    # Each role's physical six-card weight per kept hand: the production
    # matrix's marginal divided by C(46, 6).
    kept_mass = [[0] * len(fours) for _ in range(2)]
    for (role, hand), kept in keep.items():
        kept_mass[role][four_index[kept]] += ways(counts(hand), full)
    with open(f"{bundle}/prior.bin", "rb") as handle:
        prior = struct.unpack(f"<{1820 * 1820}Q", handle.read())
    rng = random.Random(seed)
    records = []
    for deal in range(deals):
        deck = list(range(52))
        rng.shuffle(deck)
        hands = [
            sorted(card // 4 for card in deck[0:6]),
            sorted(card // 4 for card in deck[6:12]),
        ]
        starter = deck[12] // 4
        for seat in (PONE, DEALER):
            own_six = tuple(hands[seat])
            kept = keep[(seat, own_six)]
            own = four_index[kept]
            available = [4 - c for c in counts(own_six)]
            available[starter] -= 1
            # The starter is cut after the deal, so given it the opponent's
            # six are uniform over the 45 cards the player cannot see.
            uniform = [ways(counts(hand), available) for hand in fours]
            production = [0] * len(fours)
            for hand, hand_counts in sixes:
                count = ways(hand_counts, available)
                if count:
                    production[four_index[keep[(1 - seat, hand)]]] += count
            uniform_share = ways(counts(kept), full) / math.comb(52, 4)
            production_share = kept_mass[seat][own] / math.comb(52, 6)
            total_uniform, total_production = sum(uniform), sum(production)
            mixture = [
                uniform_share * u / total_uniform
                + production_share * p / total_production
                for u, p in zip(uniform, production)
            ]
            if seat == PONE:
                baseline = list(prior[own * 1820 : (own + 1) * 1820])
            else:
                baseline = [prior[p * 1820 + own] for p in range(1820)]
            scenario = 2 * deal + seat
            records.append(
                (scenario + VARIANTS["mixture"], seat, own, integer_weights(mixture))
            )
            records.append(
                (
                    scenario + VARIANTS["population"],
                    seat,
                    own,
                    integer_weights(production),
                )
            )
            records.append((scenario + VARIANTS["baseline"], seat, own, baseline))
    with open(out, "wb") as handle:
        for scenario, seat, own, weights in records:
            handle.write(RECORD.pack(scenario, seat, own))
            handle.write(struct.pack("<1820Q", *weights))
    print(f"wrote {len(records)} scenarios")


def weighted_quantile(pairs, fraction):
    pairs = sorted(pairs)
    total = sum(weight for _, weight in pairs)
    running = 0.0
    for value, weight in pairs:
        running += weight
        if running >= fraction * total:
            return value
    return pairs[-1][0]


def band_of(loss):
    return next((i for i, edge in enumerate(BANDS) if loss < edge), len(BANDS))


def compare_variant(by_scenario, offset):
    """Statistics of one conditioned variant against the baseline.

    A decision counts with weight conditioned reach times the player's own
    policy reach, normalized per hand and stage, so each hand counts once
    per stage; decisions that need an earlier off-policy own card get no
    weight. Per-card statistics give each legal card of a decision an equal
    share of the decision's weight.
    """
    stages = {
        stage: {
            "hands": 0,
            "changed": 0.0,
            "cost": 0.0,
            "costs": [],
            "decision_cost_max": 0.0,
            "tie_broken": 0.0,
        }
        for stage in range(4)
    }
    loss_shift = {stage: [] for stage in range(4)}
    bands = [[0.0, 0.0, 0.0, 0.0] for _ in range(len(BANDS) + 1)]
    for scenario, conditioned in by_scenario.items():
        if scenario & ~SCENARIO_MASK != offset:
            continue
        baseline = by_scenario[(scenario & SCENARIO_MASK) + VARIANTS["baseline"]]
        totals = {stage: [0.0, 0.0, 0.0, 0.0] for stage in range(4)}
        cards = []
        for menu, (stage, width, reach, own_reach, values) in conditioned.items():
            weight = reach * own_reach
            if weight <= 0:
                continue
            if menu not in baseline:
                raise ValueError(
                    f"scenario {scenario}: menu {menu} has no baseline row"
                )
            base_values = baseline[menu][4]
            base_best = max(range(width), key=lambda a: base_values[a])
            best = max(values)
            cost = best - values[base_best]
            base_losses = [max(base_values) - v for v in base_values]
            losses = [best - v for v in values]
            stage_totals = totals[stage]
            stage_totals[0] += weight
            stage_totals[1] += weight * (cost >= TIE)
            stage_totals[2] += weight * cost
            stage_totals[3] += weight * any(
                b < TIE and c >= 0.05 for b, c in zip(base_losses, losses)
            )
            stages[stage]["decision_cost_max"] = max(
                stages[stage]["decision_cost_max"], cost
            )
            cards.extend(
                (stage, weight / width, b, c) for b, c in zip(base_losses, losses)
            )
        for stage, (mass, changed, cost, tie_broken) in totals.items():
            if mass <= 0:
                continue
            entry = stages[stage]
            entry["hands"] += 1
            entry["changed"] += changed / mass
            entry["cost"] += cost / mass
            entry["tie_broken"] += tie_broken / mass
            entry["costs"].append(cost / mass)
        for stage, share, base_loss, loss in cards:
            share /= totals[stage][0]
            loss_shift[stage].append((abs(base_loss - loss), share))
            band = bands[band_of(base_loss)]
            band[0] += share
            if base_loss < TIE:
                band[1] += share * (loss >= 0.05)
            else:
                band[1] += share * (loss < TIE)
                band[2] += share * (loss == 0)
            band[3] += share * (abs(base_loss - loss) >= 0.1)
    for stage, entry in stages.items():
        hands = entry["hands"]
        costs = sorted(entry.pop("costs"))
        for key in ("changed", "cost", "tie_broken"):
            entry[key] /= hands
        mean = entry["cost"]
        entry["cost_se"] = (
            sum((c - mean) ** 2 for c in costs) / (hands - 1) / hands
        ) ** 0.5
        entry["hand_cost_p95"] = costs[int(0.95 * (hands - 1))]
        entry["hand_cost_max"] = costs[-1]
        entry["loss_shift_p50"] = weighted_quantile(loss_shift[stage], 0.5)
        entry["loss_shift_p90"] = weighted_quantile(loss_shift[stage], 0.9)
        entry["loss_shift_p99"] = weighted_quantile(loss_shift[stage], 0.99)
    band_rows = []
    edges = [0.0] + BANDS + [None]
    for i, (mass, event, exactly_best, moved) in enumerate(bands):
        band_rows.append(
            {
                "baseline_loss_from": edges[i],
                "baseline_loss_to": edges[i + 1],
                "event": (
                    "loss >= 0.05 after conditioning"
                    if i == 0
                    else "within 0.005 of best after conditioning"
                ),
                "event_share": event / mass,
                "exactly_best_share": None if i == 0 else exactly_best / mass,
                "moved_0_1_share": moved / mass,
            }
        )
    return {"stages": stages, "bands": band_rows}


def read_scenarios(path):
    record = RECORD.size + 1820 * 8
    with open(path, "rb") as handle:
        data = handle.read()
    scenarios = {}
    for start in range(0, len(data), record):
        scenario, seat, own = RECORD.unpack_from(data, start)
        weights = struct.unpack_from("<1820Q", data, start + RECORD.size)
        if scenario in scenarios:
            raise ValueError(f"scenario {scenario} appears twice")
        scenarios[scenario] = (seat, own, sum(weights))
    return scenarios


def check_coverage(bundle, scenarios, by_scenario, published):
    """Require every scenario's rows, and baselines equal to the spike's.

    A baseline must hold exactly the menus of its own file that the spike's
    values reach, with the same values, own reach and (renormalized from the
    prior row to the whole prior) opponent reach. A conditioned variant must
    be present whenever its hand has a choice, and may reach only menus its
    baseline reaches. Returns the number of baseline rows checked and the
    largest value or own-reach difference.
    """
    starts = [0]
    for k in range(3640):
        path = os.path.join(bundle, "menus", f"{k}.bin")
        size = os.path.getsize(path) if os.path.exists(path) else 0
        starts.append(starts[-1] + size // 19)
    with open(os.path.join(bundle, "prior.bin"), "rb") as handle:
        mass = sum(struct.unpack(f"<{1820 * 1820}Q", handle.read()))
    reached_by_file = {}
    for menu, row in published.items():
        if row[3] > 0:
            file_index = bisect.bisect_right(starts, menu) - 1
            reached_by_file.setdefault(file_index, set()).add(menu)
    # Each dealt hand must carry exactly one record of each variant, all
    # for the same seat and kept hand, even when its hand has no choice.
    hands = {}
    for scenario, (seat, own, _) in scenarios.items():
        hands.setdefault(scenario & SCENARIO_MASK, {})[scenario & ~SCENARIO_MASK] = (
            seat,
            own,
        )
    for key, variants in hands.items():
        if set(variants) != set(VARIANTS.values()) or len(set(variants.values())) != 1:
            raise ValueError(f"hand {key} lacks a full, consistent set of variants")
    checked, error = 0, 0.0
    for scenario, (seat, own, weight_total) in scenarios.items():
        expected = reached_by_file.get(seat * 1820 + own, set())
        rows = by_scenario.get(scenario, {})
        if scenario & ~SCENARIO_MASK == VARIANTS["baseline"]:
            if set(rows) != expected:
                raise ValueError(
                    f"baseline {scenario} does not cover its reached menus"
                )
            for menu, (_, width, reach, own_reach, values) in rows.items():
                reference = published[menu]
                if not math.isclose(
                    reach * weight_total / mass, reference[3], rel_tol=1e-12, abs_tol=0
                ):
                    raise ValueError(f"baseline {scenario} menu {menu}: reach differs")
                checked += 1
                error = max(
                    error,
                    abs(own_reach - reference[4]),
                    max(abs(a - b) for a, b in zip(values, reference[5 : 5 + width])),
                )
        else:
            if expected and not rows:
                raise ValueError(f"scenario {scenario} has no rows")
            if not set(rows) <= expected:
                raise ValueError(
                    f"scenario {scenario} reaches menus its baseline does not"
                )
    return checked, error


def compare(bundle, scenarios_path, rows_path, values_path, out):
    with open(rows_path, "rb") as handle:
        rows = list(ROW.iter_unpack(handle.read()))
    with open(values_path, "rb") as handle:
        published = {row[0]: row for row in VALUE_ROW.iter_unpack(handle.read())}
    by_scenario = {}
    for scenario, menu, stage, width, reach, own_reach, *values in rows:
        by_scenario.setdefault(scenario, {})[menu] = (
            stage,
            width,
            reach,
            own_reach,
            values[:width],
        )
    scenarios = read_scenarios(scenarios_path)
    if set(by_scenario) - set(scenarios):
        raise ValueError("rows name scenarios the scenario file does not")
    checked, baseline_error = check_coverage(bundle, scenarios, by_scenario, published)
    result = {
        "baseline_rows_checked": checked,
        "baseline_max_abs_error": baseline_error,
        "mixture": compare_variant(by_scenario, VARIANTS["mixture"]),
        "population": compare_variant(by_scenario, VARIANTS["population"]),
    }
    with open(out, "w") as handle:
        json.dump(result, handle, indent=1)
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5])
    else:
        compare(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6])
