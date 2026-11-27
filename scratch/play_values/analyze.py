"""Summarize `play-values exact` output for the #260 spike.

Usage: python analyze.py BUNDLE VALUES.bin OUT_DIR [TARGETS_PER_STAGE]

Writes summary.json, targets.txt (Monte Carlo targets sampled by how often
play reaches them) and examples.json into OUT_DIR. Standard library only.
"""

import gzip
import json
import lzma
import os
import random
import struct
import sys
from array import array

RECORD = 19
FILES = 3640
ROW = struct.Struct("<IBBxxdd4d")
RANKS = "A23456789TJQK"
STAGE_NAMES = ["Pone card 1", "Dealer card 1", "Pone card 2", "Dealer card 2"]
POLICY_UNITS = 1000
TIE_EDGES = [0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1.0]


def canonical():
    return [
        (a, b, c, d)
        for a in range(13)
        for b in range(a, 13)
        for c in range(b, 13)
        for d in range(c, 13)
    ]


def history_text(key):
    tokens = []
    while key:
        token = key & 15
        key >>= 4
        tokens.append(
            "go" if token == 14 else "reset" if token == 15 else RANKS[token - 1]
        )
    return " ".join(tokens) or "(none)"


def main():
    bundle, values_path, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    per_stage = int(sys.argv[4]) if len(sys.argv) > 4 else 15
    starts = [0]
    for k in range(FILES):
        path = os.path.join(bundle, "menus", f"{k}.bin")
        size = os.path.getsize(path) if os.path.exists(path) else 0
        starts.append(starts[-1] + size // RECORD)
    offsets = array("I")
    with open(os.path.join(bundle, "offsets.bin"), "rb") as handle:
        offsets.frombytes(handle.read())
    policy = array("H")
    with open(os.path.join(bundle, "policy.bin"), "rb") as handle:
        policy.frombytes(handle.read())
    with open(values_path, "rb") as handle:
        data = handle.read()
    rows = list(ROW.iter_unpack(data))

    stats = {
        stage: {
            "rows": 0,
            "chance_reached": 0,
            "policy_reached": 0,
            "actions_reached": 0,
            "occurrence": 0.0,
            "mixed_rows": 0,
            "mixed_spread_max": 0.0,
            "mixed_spread_weighted": 0.0,
            "mixed_occurrence": 0.0,
            "top_is_best": 0.0,
            "policy_loss_weighted": 0.0,
            "gap_counts": [0] * (len(TIE_EDGES) + 1),
            "gap_occurrence": [0.0] * (len(TIE_EDGES) + 1),
            "worst_loss_weighted": 0.0,
            "worst_loss_max": 0.0,
            "value_abs_max": 0.0,
        }
        for stage in range(4)
    }
    candidates = {stage: [] for stage in range(4)}
    quantized = {stage: bytearray() for stage in range(4)}
    for menu, stage, width, reach, own_reach, *values in rows:
        entry = stats[stage]
        entry["rows"] += 1
        if reach <= 0:
            continue
        entry["chance_reached"] += 1
        if own_reach <= 0:
            continue
        entry["policy_reached"] += 1
        entry["actions_reached"] += width
        occurrence = reach * own_reach
        entry["occurrence"] += occurrence
        values = values[:width]
        probs = [policy[offsets[menu] + action] for action in range(width)]
        best = max(values)
        ordered = sorted(values, reverse=True)
        gap = ordered[0] - ordered[1]
        bucket = next(
            (i for i, edge in enumerate(TIE_EDGES) if gap < edge), len(TIE_EDGES)
        )
        entry["gap_counts"][bucket] += 1
        entry["gap_occurrence"][bucket] += occurrence
        supported = [values[a] for a in range(width) if probs[a] > 0]
        if len(supported) > 1:
            spread = max(supported) - min(supported)
            entry["mixed_rows"] += 1
            entry["mixed_spread_max"] = max(entry["mixed_spread_max"], spread)
            entry["mixed_spread_weighted"] += spread * occurrence
            entry["mixed_occurrence"] += occurrence
        top = max(range(width), key=lambda a: (probs[a], -a))
        if values[top] == best:
            entry["top_is_best"] += occurrence
        policy_value = sum(p * v for p, v in zip(probs, values)) / POLICY_UNITS
        entry["policy_loss_weighted"] += (best - policy_value) * occurrence
        worst = best - min(values)
        entry["worst_loss_weighted"] += worst * occurrence
        entry["worst_loss_max"] = max(entry["worst_loss_max"], worst)
        entry["value_abs_max"] = max(
            entry["value_abs_max"], max(abs(v) for v in values)
        )
        candidates[stage].append((occurrence, menu))
        # Size probe: each card's loss against the best, in hundredths of a
        # point, capped at 255, one byte per legal card.
        quantized[stage].extend(min(255, round((best - v) * 100)) for v in values)

    for stage in range(4):
        entry = stats[stage]
        mass = entry["occurrence"]
        for key in ("top_is_best", "policy_loss_weighted", "worst_loss_weighted"):
            entry[key] = entry[key] / mass if mass else None
        if entry["mixed_occurrence"]:
            entry["mixed_spread_weighted"] /= entry["mixed_occurrence"]
        entry["gap_share"] = (
            [x / mass for x in entry["gap_occurrence"]] if mass else None
        )
        blob = bytes(quantized[stage])
        entry["probe_bytes_raw"] = len(blob)
        entry["probe_bytes_gzip"] = len(gzip.compress(blob, 9))
        entry["probe_bytes_xz"] = len(lzma.compress(blob, preset=9))
    stats["tie_edges"] = TIE_EDGES
    stats["stage_names"] = STAGE_NAMES

    rng = random.Random(260)
    targets = []
    for stage in range(4):
        pool = candidates[stage]
        total = sum(weight for weight, _ in pool)
        chosen = set()
        while len(chosen) < min(per_stage, len(pool)):
            draw = rng.random() * total
            for weight, menu in pool:
                draw -= weight
                if draw <= 0:
                    chosen.add(menu)
                    break
        targets.extend(sorted(chosen))
    with open(os.path.join(out_dir, "targets.txt"), "w") as handle:
        handle.write("\n".join(map(str, targets)) + "\n")

    hands = canonical()
    by_menu = {row[0]: row for row in rows}
    examples = []
    for menu in targets:
        file_index = next(k for k in range(FILES) if starts[k] <= menu < starts[k + 1])
        with open(os.path.join(bundle, "menus", f"{file_index}.bin"), "rb") as handle:
            handle.seek((menu - starts[file_index]) * RECORD)
            record = handle.read(RECORD)
        key = struct.unpack_from("<Q", record)[0]
        width = record[17]
        ranks = record[12 : 12 + width]
        _, stage, _, reach, own_reach, *values = by_menu[menu]
        examples.append(
            {
                "menu": menu,
                "stage": STAGE_NAMES[stage],
                "hand": "".join(RANKS[r] for r in hands[file_index % 1820]),
                "history": history_text(key),
                "cards": [RANKS[r] for r in ranks],
                "policy": [
                    policy[offsets[menu] + a] / POLICY_UNITS for a in range(width)
                ],
                "values": values[:width],
                "occurrence": reach * own_reach,
            }
        )
    with open(os.path.join(out_dir, "examples.json"), "w") as handle:
        json.dump(examples, handle, indent=1)
    with open(os.path.join(out_dir, "summary.json"), "w") as handle:
        json.dump(stats, handle, indent=1)
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
