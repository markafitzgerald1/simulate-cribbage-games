"""How much do first- and second-play values move when the opponent's hand
is conditioned on the cards the player can see (own six and the starter)?

Usage:
  python conditioning.py build BUNDLE DEALS SEED SCENARIOS.bin
  python conditioning.py compare SCENARIOS.bin ROWS.bin VALUES.bin OUT.json

`build` deals DEALS physical hands, and for each deal makes four scenarios:
the Pone and the Dealer seat, each once with the prior row of its kept hand
(the baseline the spike's values use) and once conditioned. Kept hands come
from the pinned discard population. The conditioned weights mirror
`artifact_pipeline/cfr_prior.py`: the same two components (uniform four-card
hands, and six-card hands mapped through the population's keeps) with the
same component weights as the prior row, but the opponent's cards are drawn
from the 45 cards the player cannot see. Only card removal changes.
Standard library only.
"""

import json
import math
import random
import struct
import sys
from itertools import combinations_with_replacement

PONE, DEALER = 0, 1
ROLES = {"Pone": PONE, "Dealer": DEALER}
SCALE = 1 << 50
BASE_OFFSET = 1 << 20
RECORD = struct.Struct("<IBxH")
ROW = struct.Struct("<IIBBxxdd4d")
VALUE_ROW = struct.Struct("<IBBxxdd4d")


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
            opponent_role = 1 - seat
            available = [4 - c for c in counts(own_six)]
            available[starter] -= 1
            uniform = [ways(counts(hand), available) for hand in fours]
            production = [0] * len(fours)
            for hand, hand_counts in sixes:
                count = ways(hand_counts, available)
                if count:
                    production[four_index[keep[(opponent_role, hand)]]] += count
            uniform_share = ways(counts(kept), full) / math.comb(52, 4)
            production_share = kept_mass[seat][own] / math.comb(52, 6)
            total_uniform, total_production = sum(uniform), sum(production)
            mixed = [
                uniform_share * u / total_uniform
                + production_share * p / total_production
                for u, p in zip(uniform, production)
            ]
            norm = sum(mixed)
            conditioned = [round(SCALE * w / norm) for w in mixed]
            if seat == PONE:
                baseline = list(prior[own * 1820 : (own + 1) * 1820])
            else:
                baseline = [prior[p * 1820 + own] for p in range(1820)]
            scenario = 2 * deal + seat
            records.append((scenario, seat, own, conditioned))
            records.append((scenario + BASE_OFFSET, seat, own, baseline))
    with open(out, "wb") as handle:
        for scenario, seat, own, weights in records:
            handle.write(RECORD.pack(scenario, seat, own))
            handle.write(struct.pack("<1820Q", *weights))
    print(f"wrote {len(records)} scenarios")


def compare(rows_path, values_path, out):
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
    # The baseline run must reproduce the spike's own values.
    baseline_error = 0.0
    for scenario, decisions in by_scenario.items():
        if scenario >= BASE_OFFSET:
            for menu, (_, width, _, _, values) in decisions.items():
                reference = published[menu][5 : 5 + width]
                baseline_error = max(
                    baseline_error, max(abs(a - b) for a, b in zip(values, reference))
                )
    stats = {
        stage: {
            "scenarios": 0,
            "changed": 0.0,
            "cost": 0.0,
            "loss_shift": 0.0,
            "value_shift": 0.0,
            "costs": [],
            "tie_broken": 0.0,
            "missing": 0.0,
        }
        for stage in range(4)
    }
    for scenario, conditioned in by_scenario.items():
        if scenario >= BASE_OFFSET:
            continue
        baseline = by_scenario.get(scenario + BASE_OFFSET, {})
        per_stage = {stage: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0] for stage in range(4)}
        for menu, (stage, width, reach, own_reach, values) in conditioned.items():
            weight = reach * own_reach
            if weight <= 0:
                continue
            totals = per_stage[stage]
            totals[0] += weight
            if menu not in baseline:
                totals[6] += weight
                continue
            base_values = baseline[menu][4]
            base_best = max(range(width), key=lambda a: base_values[a])
            best = max(values)
            cost = best - values[base_best]
            base_losses = [max(base_values) - v for v in base_values]
            losses = [best - v for v in values]
            totals[1] += weight * (cost >= 0.005)
            totals[2] += weight * cost
            totals[3] += (
                weight * sum(abs(a - b) for a, b in zip(losses, base_losses)) / width
            )
            totals[4] += (
                weight * sum(abs(a - b) for a, b in zip(values, base_values)) / width
            )
            # A card the baseline shows as tied with the best (encoded loss
            # 0) that conditioning makes at least 0.05 points worse.
            totals[5] += weight * any(
                b < 0.005 and c >= 0.05 for b, c in zip(base_losses, losses)
            )
        for stage, totals in per_stage.items():
            mass = totals[0]
            if mass <= 0:
                continue
            entry = stats[stage]
            entry["scenarios"] += 1
            entry["changed"] += totals[1] / mass
            entry["cost"] += totals[2] / mass
            entry["loss_shift"] += totals[3] / mass
            entry["value_shift"] += totals[4] / mass
            entry["tie_broken"] += totals[5] / mass
            entry["missing"] += totals[6] / mass
            entry["costs"].append(totals[2] / mass)
    for entry in stats.values():
        n = entry["scenarios"]
        costs = sorted(entry.pop("costs"))
        for key in (
            "changed",
            "cost",
            "loss_shift",
            "value_shift",
            "tie_broken",
            "missing",
        ):
            entry[key] /= n
        mean = entry["cost"]
        entry["cost_se"] = (sum((c - mean) ** 2 for c in costs) / (n - 1) / n) ** 0.5
        entry["cost_p95"] = costs[int(0.95 * (n - 1))]
        entry["cost_max"] = costs[-1]
    stats["baseline_max_abs_error"] = baseline_error
    with open(out, "w") as handle:
        json.dump(stats, handle, indent=1)
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5])
    else:
        compare(sys.argv[2], sys.argv[3], sys.argv[4])
