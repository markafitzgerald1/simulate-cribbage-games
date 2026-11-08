"""Count reachable optional information sets and benchmark continuations, not train."""

import argparse
from collections import Counter
from functools import lru_cache
import gzip
import importlib
import json
from pathlib import Path
import random
import sys
import time

from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    GO_ACTION,
    SEQUENCE_RESET,
    other_role,
    policy_fingerprint,
    simulate_from_state,
    simulate_pegging,
)

second = importlib.import_module("scratch.exact_second_card")
exact = second.exact
LAYERS = tuple(f"{role}-{number}" for role in (PONE, DEALER) for number in (1, 2, 3))


@lru_cache(maxsize=4)
def frozen_policies(paths):
    """Verify and cache all three frozen stages before tracing their reachability."""
    _, _, parents = second.frozen_books(*paths[:2])
    source = json.loads(Path(paths[2]).read_bytes())
    if source["evidence_sha256"] != exact.book.evidence_digest(source["hands"]):
        raise ValueError("Second-card evidence digest mismatch")
    candidate = second.build_second(source["hands"], parents[PONE])
    if source["policy_fingerprint"] != policy_fingerprint(candidate):
        raise ValueError("Second-card policy fingerprint mismatch")
    if source["dealer_policy_fingerprint"] != policy_fingerprint(parents[DEALER]):
        raise ValueError("Second-card source Dealer mismatch")
    if source["pone_policy_fingerprint"] != policy_fingerprint(parents[PONE]):
        raise ValueError("Second-card source Pone mismatch")
    return {PONE: candidate, DEALER: parents[DEALER]}


def initial_hand(view):
    """Recover own original cards from public actors, including goes and resets."""
    actor, last = PONE, None
    played = []
    for action in view.public_history:
        if action == GO_ACTION:
            actor = other_role(actor)
        elif action == SEQUENCE_RESET:
            if last is None:
                raise ValueError("Reset without a previous public play")
            actor, last = other_role(last), None
        else:
            if actor == view.role:
                played.append(action)
            last, actor = actor, other_role(actor)
    if actor != view.role:
        raise ValueError("Public history does not identify the acting seat")
    return tuple(sorted((*played, *view.own_remaining)))


def layer_name(view):
    """Card number counts actual own cards played, never passes or turn alternations."""
    return f"{view.role}-{5-len(view.own_remaining)}"


def serialized_layer(values, policy, rng):
    """Measure actual full-key action JSON and dictionary storage for one shard."""
    actions = {k: policy.select_rank(v[0], rng) for k, v in values}
    encoded = json.dumps(actions, separators=(",", ":")).encode("ascii")
    return {
        "sets": len(values),
        "alternatives": sum(len(v[0].legal_ranks) for _, v in values),
        "consistent_hands": sum(v[1] for _, v in values),
        "simulations": sum(v[1] * len(v[0].legal_ranks) for _, v in values),
        "support_histogram": dict(Counter(v[1] for _, v in values)),
        "json_entry_bytes": len(encoded) - 2,
        "gzip_shard_bytes": len(gzip.compress(encoded, mtime=0)),
        "python_key_bytes": sum(sys.getsizeof(k) for k in actions),
        "python_shard_dict_bytes": sys.getsizeof(actions),
        "with_go_history": sum(GO_ACTION in v[0].public_history for _, v in values),
        "with_reset_history": sum(
            SEQUENCE_RESET in v[0].public_history for _, v in values
        ),
    }


def collect_support(sets, result, own, role):
    """Count one consistent rank hand once per reachable optional full view."""
    for decision in result.decisions:
        view = decision.view
        if view.role != role:
            continue
        if initial_hand(view) != own:
            raise ValueError("Original hand partition is not disjoint")
        key = view.key()
        if key not in sets:
            sets[key] = [view, 0]
        sets[key][1] += 1


def trace_hand(own, opponent, role, policies, rng):
    """Trace one ordered pair under the frozen policies."""
    hands = {role: own, other_role(role): opponent}
    return simulate_pegging(
        hands[PONE], hands[DEALER], policies, rng, collect_decisions=True
    )


def count_hand(job):
    """Aggregate one original own hand; full history makes different jobs disjoint."""
    own, role, paths, ranks = job
    policies = frozen_policies(paths)
    rng = random.Random(0)
    sets, pairs, physical_mass = {}, 0, 0
    for opponent, weight in exact.opponent_hands(own, ranks):
        pairs += 1
        physical_mass += weight
        collect_support(sets, trace_hand(own, opponent, role, policies, rng), own, role)
    layers = {}
    for name in LAYERS:
        values = [(k, v) for k, v in sets.items() if layer_name(v[0]) == name]
        if not values:
            continue
        layers[name] = serialized_layer(values, policies[role], rng)
    if rng.getstate() != random.Random(0).getstate():
        raise ValueError("Counting requires deterministic frozen policies")
    return {
        "hand": list(own),
        "role": role,
        "rank_deals": pairs,
        "physical_mass": physical_mass,
        "layers": layers,
    }


def benchmark_hand(job):
    """Force all legal alternatives solely to time a frozen continuation sweep."""
    own, role, paths, ranks = job
    policies = frozen_policies(paths)
    rng = random.Random(0)
    stats = {name: {"simulations": 0, "seconds": 0.0} for name in LAYERS}
    started = time.monotonic()
    for opponent, _ in exact.opponent_hands(own, ranks):
        result = trace_hand(own, opponent, role, policies, rng)
        for decision in result.decisions:
            if decision.view.role != role:
                continue
            stat = stats[layer_name(decision.view)]
            before = time.monotonic()
            for rank in decision.view.legal_ranks:
                simulate_from_state(decision.state, policies, rng, forced_rank=rank)
                stat["simulations"] += 1
            stat["seconds"] += time.monotonic() - before
    return {"layers": stats, "seconds": time.monotonic() - started}


def combine_counts(rows):
    """Retain exact support histograms and measured serialization sizes by layer."""
    combined = {}
    for name in LAYERS:
        cells = [r["layers"][name] for r in rows if name in r["layers"]]
        total = {}
        for cell in cells:
            for key, value in cell.items():
                if key != "support_histogram":
                    total[key] = total.get(key, 0) + value
        histogram = Counter()
        for cell in cells:
            histogram.update({int(k): v for k, v in cell["support_histogram"].items()})
        total["support_histogram"] = dict(sorted(histogram.items()))
        if cells:
            total["mean_alternatives"] = total["alternatives"] / total["sets"]
            total["mean_consistent_rank_hands"] = (
                total["consistent_hands"] / total["sets"]
            )
            total["compact_json_bytes"] = total["json_entry_bytes"] + len(cells) - 1 + 2
            total["python_single_dict_bytes"] = sys.getsizeof(
                dict.fromkeys(range(total["sets"]))
            )
            total["python_keys_and_dict_bytes"] = (
                total["python_key_bytes"] + total["python_single_dict_bytes"]
            )
        combined[name] = total
    return combined


def full_table_sizes(layers):
    """Measure two role dictionaries; merging layer maps removes one byte per join."""
    sizes = {}
    for role in (PONE, DEALER):
        cells = [v for k, v in layers.items() if k.startswith(role) and v.get("sets")]
        entries = sum(v["sets"] for v in cells)
        sizes[role] = {
            "entries": entries,
            "compact_json_bytes": (
                sum(v["compact_json_bytes"] for v in cells) - len(cells) + 1
                if cells
                else 2
            ),
            "python_keys_and_dict_bytes": sum(v["python_key_bytes"] for v in cells)
            + sys.getsizeof(dict.fromkeys(range(entries))),
        }
    return sizes


def main():
    """Measure frozen support or a labeled timing sample without choosing new actions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("counts", "benchmark"))
    parser.add_argument("--pone", required=True, type=Path)
    parser.add_argument("--dealer", required=True, type=Path)
    parser.add_argument("--second", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", default=8, type=int)
    parser.add_argument("--keys", default=20, type=int)
    parser.add_argument("--seed", default=42, type=int)
    args = parser.parse_args()
    if args.workers < 1 or not 1 <= args.keys <= len(exact.HANDS):
        parser.error("Need positive workers and a valid timing sample size")
    paths = tuple(str(p.resolve()) for p in (args.pone, args.dealer, args.second))
    policies = frozen_policies(paths)
    hands = (
        exact.HANDS
        if args.mode == "counts"
        else random.Random(repr((args.seed, "issue-187-depth-timing-v1"))).sample(
            exact.HANDS, args.keys
        )
    )
    started = time.monotonic()
    rows = exact.enumerate_jobs(
        [(h, role, paths, 13) for role in (PONE, DEALER) for h in hands],
        "depth-" + args.mode,
        args.workers,
        count_hand if args.mode == "counts" else benchmark_hand,
    )
    elapsed = time.monotonic() - started
    report = {
        "experiment": "issue-187-depth-" + args.mode + "-v1",
        "scope": "reachable optional full public views under frozen stages 1+2+3a, not off-policy histories",
        "workers": args.workers,
        "seed": args.seed,
        "timing_stream": "issue-187-depth-timing-v1",
        "elapsed_seconds": elapsed,
        "fingerprints": {r: policy_fingerprint(p) for r, p in policies.items()},
        "own_keys_per_seat": len(hands),
    }
    if args.mode == "counts":
        report["layers"] = combine_counts(rows)
        report["full_table_sizes"] = full_table_sizes(report["layers"])
        report["rank_deals_per_seat"] = sum(
            r["rank_deals"] for r in rows if r["role"] == PONE
        )
    else:
        report["layers"] = {
            name: {
                "simulations": sum(r["layers"][name]["simulations"] for r in rows),
                "worker_seconds": sum(r["layers"][name]["seconds"] for r in rows),
            }
            for name in LAYERS
        }
        report["simulations"] = sum(v["simulations"] for v in report["layers"].values())
        report["aggregate_simulations_per_second_including_traces"] = (
            report["simulations"] / elapsed
        )
    report["rows"] = rows
    exact.write_report(args.output, report)
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
