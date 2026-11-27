"""Check `play-values mc` output against the exact values and reaches.

Usage: python check_mc.py BUNDLE VALUES.bin MC.csv [MC.csv ...]

Per card: z of the Monte Carlo mean against the exact value. Per target:
z of the acceptance rate against the exact chance of reaching the decision
given the seat's own hand and history, `reach * mass / row_mass`, which
catches errors that scale every reach alike and so leave the means alone.
The sum of squared card z-scores is descriptive only: cards of one decision
share their sampled deals. Standard library only.
"""

import bisect
import csv
import os
import struct
import sys

ROW = struct.Struct("<IBBxxdd4d")


def main():
    bundle, values_path, *csv_paths = sys.argv[1:]
    starts = [0]
    for k in range(3640):
        path = os.path.join(bundle, "menus", f"{k}.bin")
        starts.append(
            starts[-1] + (os.path.getsize(path) // 19 if os.path.exists(path) else 0)
        )
    with open(os.path.join(bundle, "prior.bin"), "rb") as handle:
        prior = struct.unpack(f"<{1820 * 1820}Q", handle.read())
    mass = sum(prior)
    pone_mass = [sum(prior[p * 1820 : (p + 1) * 1820]) for p in range(1820)]
    dealer_mass = [sum(prior[d::1820]) for d in range(1820)]
    with open(values_path, "rb") as handle:
        exact = {row[0]: row for row in ROW.iter_unpack(handle.read())}
    card_z, accept_z, zero_spread, zero_own, endpoint_failures = [], [], [], 0, 0
    seen = set()
    for path in csv_paths:
        with open(path) as handle:
            for row in csv.DictReader(handle):
                menu = int(row["menu"])
                _, stage, _, reach, own_reach, *values = exact[menu]
                value = values[int(row["action"])]
                error = float(row["mean"]) - value
                standard_error = float(row["standard_error"])
                # No observed spread (for example every later play forced):
                # a z-score is undefined, so record agreement separately.
                if standard_error == 0:
                    zero_spread.append(abs(error) < 1e-9)
                else:
                    card_z.append(error / standard_error)
                if menu in seen:
                    continue
                seen.add(menu)
                zero_own += own_reach == 0
                file_index = bisect.bisect_right(starts, menu) - 1
                own = file_index % 1820
                row_mass = pone_mass[own] if file_index < 1820 else dealer_mass[own]
                expected = reach * mass / row_mass
                attempts = int(row["attempts"])
                accepted = int(row["accepted"])
                # At an endpoint every attempt must agree; otherwise the
                # residual is approximate, since sampling stops at a fixed
                # number of accepted deals.
                if expected >= 1 - 1e-12 or expected <= 1e-12:
                    endpoint_failures += accepted != round(expected) * attempts
                    continue
                spread = (expected * (1 - expected) / attempts) ** 0.5
                accept_z.append((accepted / attempts - expected) / spread)
    count = len(card_z)
    print(
        f"zero-spread cards: {len(zero_spread)}, disagreeing {zero_spread.count(False)}; "
        f"endpoint acceptance failures: {endpoint_failures}"
    )
    print(f"targets {len(seen)} (zero own reach {zero_own}), cards {count}")
    print(
        f"card z: sum of squares {sum(z * z for z in card_z):.1f}, mean {sum(card_z) / count:+.3f}, "
        f"beyond 2: {sum(abs(z) > 2 for z in card_z)}, beyond 3: {sum(abs(z) > 3 for z in card_z)}"
    )
    print(
        f"acceptance z: max abs {max(abs(z) for z in accept_z):.2f}, "
        f"beyond 3: {sum(abs(z) > 3 for z in accept_z)}"
    )
    if zero_spread.count(False) or endpoint_failures:
        sys.exit("Monte Carlo disagrees with an exact value or reach")


if __name__ == "__main__":
    main()
