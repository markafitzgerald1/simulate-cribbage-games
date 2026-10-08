"""Report-only posterior transfer and joint-policy measurement for issue 187."""

import argparse
from collections import defaultdict
from functools import lru_cache
from fractions import Fraction
import gzip
import hashlib
import importlib
import json
import math
from pathlib import Path
import random
import sys
import time

from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    LegacyHeuristicPolicy,
    RunningStatistics,
    policy_fingerprint,
    simulate_from_state,
    simulate_pegging,
)
from artifact_pipeline.promotion_gate import gate_deals

second = importlib.import_module("scratch.exact_second_card")
exact = second.exact


@lru_cache(maxsize=4)
def load_books(paths):
    """Verify all frozen policy evidence before deriving a report."""
    pone, dealer, parents = second.frozen_books(*paths[:2])
    report = json.loads(Path(paths[2]).read_bytes())
    if report["evidence_sha256"] != exact.book.evidence_digest(report["hands"]):
        raise ValueError("Second-card evidence digest mismatch")
    candidate = second.build_second(report["hands"], parents[PONE])
    if report["policy_fingerprint"] != policy_fingerprint(candidate):
        raise ValueError("Second-card policy fingerprint mismatch")
    if (
        report["dealer_policy_fingerprint"] != dealer["policy_fingerprint"]
        or report["pone_policy_fingerprint"] != pone["policy_fingerprint"]
    ):
        raise ValueError("Second-card frozen parent mismatch")
    return report, parents, {PONE: candidate, DEALER: parents[DEALER]}


def add_heuristic_keep(cells, own, opponent, weight, prefix):
    """Measure the selected actions on one heuristic-consistent hidden keep."""
    lead, parents, rng = prefix
    heuristic = LegacyHeuristicPolicy()
    policies = {PONE: heuristic, DEALER: heuristic}
    first = second.dealer_book.after_lead_state(opponent, own, lead).view()
    book_reply = parents[DEALER].select_rank(first, rng)
    reply = heuristic.select_rank(first, rng)
    if reply not in cells:
        return
    cell = cells[reply]
    cell["heuristic_weight"] += weight
    cell["intersection_weight"] += weight * (book_reply == reply)
    state = second.second_state(own, opponent, lead, reply)
    cell["heuristic_gain_sum"] += weight * continuation_gain(
        state, policies, rng, cell["override"], cell["heuristic_second"]
    )


def continuation_gain(state, policies, rng, override, baseline_rank):
    """Compare two forced actions with identical deterministic continuations."""
    candidate = exact.integer_delta(
        simulate_from_state(state, policies, rng, forced_rank=override),
        PONE,
    )
    baseline = exact.integer_delta(
        simulate_from_state(state, policies, rng, forced_rank=baseline_rank),
        PONE,
    )
    return candidate - baseline


def transfer_hand(job):
    """Compare weighted reply posteriors and selected-action payoffs exactly."""
    row, paths, ranks = job
    _, parents, _ = load_books(paths)
    own, lead = tuple(row["hand"]), row["lead"]
    cells = {
        c["reply"]: dict(
            c, heuristic_weight=0, intersection_weight=0, heuristic_gain_sum=0
        )
        for c in row["replies"]
        if c["override"] is not None
    }
    rng = random.Random(0)
    for opponent, weight in exact.opponent_hands(own, ranks):
        add_heuristic_keep(cells, own, opponent, weight, (lead, parents, rng))
    return {
        "hand": row["hand"],
        "own_weight": row["own_weight"],
        "cells": list(cells.values()),
    }


def posterior_totals(cells):
    """Aggregate overlap and an algebraic posterior/frequency decomposition."""
    weighted = defaultdict(list)
    groups = defaultdict(
        lambda: {"keys": 0, "book_numerator": 0, "heuristic_numerator": 0}
    )
    for own_weight, cell in cells:
        b, h, i = cell["weight"], cell["heuristic_weight"], cell["intersection_weight"]
        gain = exact.gain_sum(cell, cell["override"]) / b
        tv = 1 - i / max(b, h)
        cell["total_variation"] = tv if h else None
        weighted["book_tv"].append(own_weight * b * tv)
        weighted["heuristic_tv"].append(own_weight * h * tv)
        weighted["frequency"].append(own_weight * (b - h) * gain)
        weighted["posterior"].append(
            own_weight * (h * gain - cell["heuristic_gain_sum"])
        )
        group = (
            "absent-under-heuristic"
            if not h
            else ("same-posterior" if not tv else f"tv-bin-{min(3, int(tv * 4))}")
        )
        groups[group]["keys"] += 1
        groups[group]["book_numerator"] += own_weight * exact.gain_sum(
            cell, cell["override"]
        )
        groups[group]["heuristic_numerator"] += own_weight * cell["heuristic_gain_sum"]
    return weighted, groups


def transfer_summary(rows):
    """Separate posterior changes from state-frequency changes in the gain gap."""
    cells = [(r["own_weight"], c) for r in rows for c in r["cells"]]
    book_sum = sum(w * exact.gain_sum(c, c["override"]) for w, c in cells)
    heuristic_sum = sum(w * c["heuristic_gain_sum"] for w, c in cells)
    mass_book = sum(w * c["weight"] for w, c in cells)
    mass_heuristic = sum(w * c["heuristic_weight"] for w, c in cells)
    weighted, groups = posterior_totals(cells)
    mass_absent = sum(w * c["weight"] for w, c in cells if not c["heuristic_weight"])
    return {
        "override_keys": len(cells),
        "heuristic_positive_keys": sum(c["heuristic_gain_sum"] > 0 for _, c in cells),
        "heuristic_negative_keys": sum(c["heuristic_gain_sum"] < 0 for _, c in cells),
        "heuristic_zero_supported_keys": sum(
            c["heuristic_weight"] > 0 and c["heuristic_gain_sum"] == 0 for _, c in cells
        ),
        "heuristic_unsupported_keys": sum(c["heuristic_weight"] == 0 for _, c in cells),
        "book_override_visit_probability": mass_book / exact.POPULATION_WEIGHT,
        "heuristic_override_visit_probability": mass_heuristic
        / exact.POPULATION_WEIGHT,
        "book_visit_weighted_tv_including_absent_as_one": math.fsum(weighted["book_tv"])
        / mass_book,
        "book_supported_visit_weighted_tv": (
            math.fsum(weighted["book_tv"]) - mass_absent
        )
        / (mass_book - mass_absent),
        "heuristic_negative_override_visit_probability": sum(
            w * c["heuristic_weight"] for w, c in cells if c["heuristic_gain_sum"] < 0
        )
        / exact.POPULATION_WEIGHT,
        "book_unsupported_override_visit_probability": mass_absent
        / exact.POPULATION_WEIGHT,
        "heuristic_visit_weighted_tv": math.fsum(weighted["heuristic_tv"])
        / mass_heuristic,
        "exact_gain_book_dealer": exact.fraction_record(
            Fraction(book_sum, exact.POPULATION_WEIGHT)
        ),
        "exact_gain_heuristic_dealer": exact.fraction_record(
            Fraction(heuristic_sum, exact.POPULATION_WEIGHT)
        ),
        "frequency_contribution_to_gap": math.fsum(weighted["frequency"])
        / exact.POPULATION_WEIGHT,
        "posterior_contribution_to_gap": math.fsum(weighted["posterior"])
        / exact.POPULATION_WEIGHT,
        "groups": dict(groups),
    }


def matchup_games(parents, combined):
    """Joint and unilateral arms on one common population, without changing the gate."""
    heuristic = {r: LegacyHeuristicPolicy() for r in (PONE, DEALER)}
    return {
        "heuristic-both": heuristic,
        "books12-both": parents,
        "books123-both": combined,
        "book1-v-heuristic": {PONE: parents[PONE], DEALER: heuristic[DEALER]},
        "heuristic-v-book2": {PONE: heuristic[PONE], DEALER: parents[DEALER]},
        "book13-v-heuristic": {PONE: combined[PONE], DEALER: heuristic[DEALER]},
    }


def add_matchup_results(results, stats, marginal, gates):
    """Retain same-deal covariance in every reported contrast."""
    for name, result in results.items():
        for role in (PONE, DEALER):
            cell = stats[name][role]
            cell["points"].add(result.total(role))
            cell["points_difference"].add(
                result.total(role) - results["heuristic-both"].total(role)
            )
            cell["delta"].add(result.delta(role))
            cell["delta_difference"].add(
                result.delta(role) - results["heuristic-both"].delta(role)
            )
    for role in (PONE, DEALER):
        marginal[role]["points"].add(
            results["books123-both"].total(role) - results["books12-both"].total(role)
        )
        marginal[role]["delta"].add(
            results["books123-both"].delta(role) - results["books12-both"].delta(role)
        )
    for name, pone_arm in (
        ("books12", "book1-v-heuristic"),
        ("books123", "book13-v-heuristic"),
    ):
        pg = results[pone_arm].delta(PONE) - results["heuristic-both"].delta(PONE)
        dg = results["heuristic-v-book2"].delta(DEALER) - results[
            "heuristic-both"
        ].delta(DEALER)
        for role, gain in ((PONE, pg), (DEALER, dg), ("both_seats", (pg + dg) / 2)):
            gates[name][role].add(gain)


def evaluate_policy_comparisons(games, deals, population):
    """Report absolute points and paired joint-policy differences on identical cards."""
    stats = {
        name: {
            role: {
                k: RunningStatistics()
                for k in ("points", "points_difference", "delta", "delta_difference")
            }
            for role in (PONE, DEALER)
        }
        for name in games
    }
    marginal = {
        role: {k: RunningStatistics() for k in ("points", "delta")}
        for role in (PONE, DEALER)
    }
    gates = {
        name: {role: RunningStatistics() for role in (PONE, DEALER, "both_seats")}
        for name in ("books12", "books123")
    }
    for pone, dealer, seed in deals:
        results = {
            name: simulate_pegging(pone, dealer, policies, random.Random(seed))
            for name, policies in games.items()
        }
        add_matchup_results(results, stats, marginal, gates)
    return {
        "population": population,
        "games": {
            n: {r: {k: v.to_dict() for k, v in c.items()} for r, c in seats.items()}
            for n, seats in stats.items()
        },
        "joint_3a_marginal": {
            r: {k: v.to_dict() for k, v in c.items()} for r, c in marginal.items()
        },
        "report_only_gate": {
            n: {r: v.to_dict() for r, v in seats.items()} for n, seats in gates.items()
        },
    }


def policy_sizes(parents, combined):
    """Measure a research-only loadable map; no published schema is implemented."""
    maps = {
        "pone-lead": parents[PONE].actions,
        "dealer-reply": parents[DEALER].actions,
        "books12": {**parents[PONE].actions, **parents[DEALER].actions},
        "books123": {**combined[PONE].actions, **combined[DEALER].actions},
        "pone-second": {
            k: v
            for k, v in combined[PONE].actions.items()
            if k not in parents[PONE].actions
        },
    }
    sizes = {}
    for name, actions in maps.items():
        raw = json.dumps(dict(sorted(actions.items())), separators=(",", ":")).encode(
            "ascii"
        )
        started = time.monotonic()
        loaded = json.loads(raw)
        parse_seconds = time.monotonic() - started
        assert loaded == actions
        objects = {id(v): v for pair in loaded.items() for v in pair}
        sizes[name] = {
            "entries": len(actions),
            "raw_bytes": len(raw),
            "gzip_bytes": len(gzip.compress(raw, mtime=0)),
            "actions_sha256": hashlib.sha256(raw).hexdigest(),
            "parse_seconds": parse_seconds,
            "python_actions_bytes_shallow_plus_unique_keys_and_values": sys.getsizeof(
                loaded
            )
            + sum(sys.getsizeof(v) for v in objects.values()),
        }
    return sizes


def main():
    """Run one ordered research phase using immutable existing evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("posterior", "uniform", "sizes"))
    parser.add_argument(
        "--pone",
        type=Path,
        default=Path(__file__).with_name("issue187_exact_pone.json"),
    )
    parser.add_argument(
        "--dealer",
        type=Path,
        default=Path(__file__).with_name("issue187_exact_dealer.json"),
    )
    parser.add_argument(
        "--second",
        type=Path,
        default=Path(__file__).with_name("issue187_exact_second_card.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--deals", type=int, default=200000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    paths = tuple(str(p.resolve()) for p in (args.pone, args.dealer, args.second))
    source, parents, combined = load_books(paths)
    if args.workers < 1 or args.deals < 1000:
        parser.error("Need positive workers and at least 1000 deals")
    started = time.monotonic()
    if args.stage == "posterior":
        rows = exact.enumerate_jobs(
            [(r, paths, 13) for r in source["hands"]],
            "posterior",
            args.workers,
            transfer_hand,
        )
        report = {"summary": transfer_summary(rows), "rows": rows}
    elif args.stage == "uniform":
        report = evaluate_policy_comparisons(
            matchup_games(parents, combined),
            gate_deals(args.deals, args.seed),
            "uniform gate deals",
        )
    else:
        report = {"maps": policy_sizes(parents, combined)}
    report.update(
        seed=args.seed,
        elapsed_seconds=time.monotonic() - started,
        policy_fingerprints={r: policy_fingerprint(p) for r, p in combined.items()},
    )
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
