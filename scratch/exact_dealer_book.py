"""Exact Dealer first replies conditional on the frozen exact Pone lead book."""

import argparse
from fractions import Fraction
import importlib
import json
import math
from pathlib import Path
import random
import time

from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    LegacyHeuristicPolicy,
    PeggingState,
    TabularPeggingPolicy,
    canonical_hand_key,
    policy_fingerprint,
    rank_count,
    simulate_from_state,
)
from artifact_pipeline.promotion_gate import DEFAULT_GATE_DEALS, evaluate_promotion

exact = importlib.import_module("scratch.exact_pegging_book")


def after_lead_state(dealer, pone, lead):
    """Construct the actual first Dealer decision after a zero-point opening."""
    remaining = list(pone)
    remaining.remove(lead)
    return PeggingState(
        {PONE: remaining, DEALER: list(dealer)},
        next_role=DEALER,
        count=rank_count(lead),
        sequence=[lead],
        public_history=[lead],
        last_player=PONE,
    )


def exact_dealer_hand(job):
    """Partition each hidden Pone hand once, then force every distinct reply."""
    own, choices, ranks = job
    heuristic = LegacyHeuristicPolicy()
    policies = {PONE: heuristic, DEALER: heuristic}
    rng = random.Random(0)
    cells = {}
    for pone, weight in exact.opponent_hands(own, ranks):
        lead = choices[pone]
        state = after_lead_state(own, pone, lead)
        view = state.view()
        if lead not in cells:
            cells[lead] = {
                "lead": lead,
                "weight": 0,
                "opponent_multisets": 0,
                "view_key": view.key(),
                "heuristic_reply": heuristic.select_rank(view, rng),
                "totals": {r: 0 for r in view.legal_ranks},
            }
        cell = cells[lead]
        if cell["view_key"] != view.key():
            raise ValueError("Hidden Pone cards changed the Dealer information key")
        cell["weight"] += weight
        cell["opponent_multisets"] += 1
        for reply in cell["totals"]:
            cell["totals"][reply] += weight * exact.integer_delta(
                simulate_from_state(state, policies, rng, forced_rank=reply), DEALER
            )
    if sum(c["weight"] for c in cells.values()) != math.comb(4 * ranks - 4, 4):
        raise ValueError(
            "Dealer conditional cells do not partition the physical population"
        )
    if rng.getstate() != random.Random(0).getstate():
        raise ValueError("Exact replies require deterministic continuations")
    for cell in cells.values():
        cell["candidates"] = exact.candidates_from_totals(
            cell.pop("totals"), cell["heuristic_reply"]
        )
        cell["override"] = exact.choose_override(
            cell["candidates"], cell["heuristic_reply"], cell["weight"]
        )
        cell["override_epsilon_zero"] = exact.choose_override(
            cell["candidates"], cell["heuristic_reply"], cell["weight"], Fraction(0)
        )
    return {
        "hand": list(own),
        "key": canonical_hand_key(own),
        "own_weight": exact.physical_weight(own),
        "weight": sum(c["weight"] for c in cells.values()),
        "simulations": sum(
            c["opponent_multisets"] * len(c["candidates"]) for c in cells.values()
        ),
        "leads": [cells[lead] for lead in sorted(cells)],
    }


def build_dealer(rows):
    """Install only observed first-Dealer overrides, with heuristic fallback."""
    return TabularPeggingPolicy(
        {
            c["view_key"]: c["override"]
            for r in rows
            for c in r["leads"]
            if c["override"] is not None
        },
        fallback=LegacyHeuristicPolicy(),
    )


def read_pone(path):
    """Validate frozen exact evidence and its installed policy before use."""
    report = json.loads(Path(path).read_bytes())
    if report["evidence_sha256"] != exact.book.evidence_digest(report["hands"]):
        raise ValueError("Exact Pone evidence digest mismatch")
    if report["policy_fingerprint"] != policy_fingerprint(
        exact.build_pone(report["hands"])
    ):
        raise ValueError("Exact Pone policy fingerprint mismatch")
    return report


def opening_choices(rows):
    """Resolve the frozen book's actual lead for every kept hand."""
    return {
        tuple(r["hand"]): (
            r["override"] if r["override"] is not None else r["heuristic_lead"]
        )
        for r in rows
    }


def dealer_summary(rows):
    """Report conditional support and exact matched-Pone training-population gain."""
    cells = [c for r in rows for c in r["leads"]]
    numerator = sum(
        r["own_weight"]
        * next(v["gain_sum"] for v in c["candidates"] if v["rank"] == c["override"])
        for r in rows
        for c in r["leads"]
        if c["override"] is not None
    )
    return {
        "observed_keys": len(cells),
        "unobserved_keys": 13 * len(rows) - len(cells),
        "optional_keys": sum(len(c["candidates"]) > 1 for c in cells),
        "overrides": sum(c["override"] is not None for c in cells),
        "epsilon_zero_different_keys": sum(
            c["override"] != c["override_epsilon_zero"] for c in cells
        ),
        "minimum_positive_cell_weight": min(c["weight"] for c in cells),
        "exact_gain_against_frozen_pone": exact.fraction_record(
            Fraction(numerator, exact.POPULATION_WEIGHT)
        ),
    }


def main():
    """Enumerate the approved stage-2 reply book and run the unmodified gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pone", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--gate-deals", type=int, default=DEFAULT_GATE_DEALS)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.workers < 1 or args.gate_deals < 1000:
        parser.error("Need positive workers and at least 1000 gate deals")
    source = read_pone(args.pone)
    choices = opening_choices(source["hands"])
    started = time.monotonic()
    rows = exact.enumerate_jobs(
        [(h, choices, 13) for h in exact.HANDS],
        "dealer",
        args.workers,
        exact_dealer_hand,
    )
    training_seconds = time.monotonic() - started
    dealer = build_dealer(rows)
    report = {
        "experiment": "issue-187-exact-dealer-v1",
        "epsilon": exact.fraction_record(exact.EPSILON),
        "workers": args.workers,
        "pone_policy_fingerprint": source["policy_fingerprint"],
        "pone_evidence_sha256": source["evidence_sha256"],
        "summary": dealer_summary(rows),
        "weight_min": min(r["weight"] for r in rows),
        "weight_max": max(r["weight"] for r in rows),
        "simulations": sum(r["simulations"] for r in rows),
        "training_seconds": training_seconds,
        "policy_fingerprint": policy_fingerprint(dealer),
        "evidence_sha256": exact.book.evidence_digest(rows),
    }
    exact.write_report(args.output, report, rows)
    report["combined_gate"] = evaluate_promotion(
        {PONE: exact.build_pone(source["hands"]), DEALER: dealer},
        args.gate_deals,
        args.seed,
    )
    report["elapsed_seconds"] = time.monotonic() - started
    exact.write_report(args.output, report, rows)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
