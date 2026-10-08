"""Exact Pone second-card decisions after frozen exact opening books."""

import argparse
from fractions import Fraction
from functools import lru_cache
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
dealer_book = importlib.import_module("scratch.exact_dealer_book")


@lru_cache(maxsize=4)
def frozen_books(pone_path, dealer_path):
    """Load and verify each immutable parent once per spawned worker."""
    pone = dealer_book.read_pone(pone_path)
    dealer = json.loads(Path(dealer_path).read_bytes())
    if dealer["evidence_sha256"] != exact.book.evidence_digest(dealer["hands"]):
        raise ValueError("Exact Dealer evidence digest mismatch")
    policy = dealer_book.build_dealer(dealer["hands"])
    if dealer["policy_fingerprint"] != policy_fingerprint(policy):
        raise ValueError("Exact Dealer policy fingerprint mismatch")
    if dealer["pone_policy_fingerprint"] != pone["policy_fingerprint"]:
        raise ValueError("Dealer book uses a different frozen Pone book")
    return pone, dealer, {PONE: exact.build_pone(pone["hands"]), DEALER: policy}


def second_state(pone, dealer, lead, reply):
    """Construct the real third public decision, before any possible go/reset."""
    own_remaining, other_remaining = list(pone), list(dealer)
    own_remaining.remove(lead)
    other_remaining.remove(reply)
    return PeggingState(
        {PONE: own_remaining, DEALER: other_remaining},
        next_role=PONE,
        count=rank_count(lead) + rank_count(reply),
        sequence=[lead, reply],
        public_history=[lead, reply],
        last_player=DEALER,
    )


def finish_cell(cell):
    """Convert shared conditional integer sums to an exact override."""
    totals = cell.pop("totals")
    cell["candidates"] = (
        exact.candidates_from_totals(totals, cell["heuristic_second"]) if totals else []
    )
    cell["override"] = (
        exact.choose_override(
            cell["candidates"], cell["heuristic_second"], cell["weight"]
        )
        if totals
        else None
    )
    cell["override_epsilon_zero"] = (
        exact.choose_override(
            cell["candidates"], cell["heuristic_second"], cell["weight"], Fraction(0)
        )
        if totals
        else None
    )
    return cell


def add_opponent(cells, own, opponent, weight, prefix):
    """Add one hidden keep to its observed-reply cell with shared alternatives."""
    lead, parents, rng = prefix
    continuation = {PONE: LegacyHeuristicPolicy(), DEALER: LegacyHeuristicPolicy()}
    reply = parents[DEALER].select_rank(
        dealer_book.after_lead_state(opponent, own, lead).view(), rng
    )
    state = second_state(own, opponent, lead, reply)
    view = state.view()
    key = view.key()
    if key not in cells:
        cells[key] = {
            "view_key": key,
            "reply": reply,
            "weight": 0,
            "opponent_multisets": 0,
            "heuristic_second": continuation[PONE].select_rank(view, rng),
            "totals": (
                {r: 0 for r in view.legal_ranks} if len(view.legal_ranks) > 1 else {}
            ),
        }
    cell = cells[key]
    cell["weight"] += weight
    cell["opponent_multisets"] += 1
    for rank in cell["totals"]:
        cell["totals"][rank] += weight * exact.integer_delta(
            simulate_from_state(state, continuation, rng, forced_rank=rank), PONE
        )


def exact_second_hand(job):
    """Partition Dealer hands by their frozen reply, forcing each Pone option."""
    own, pone_path, dealer_path, ranks = job
    _, _, parents = frozen_books(pone_path, dealer_path)
    rng = random.Random(0)
    lead = parents[PONE].select_rank(exact.book.opening_view(own), rng)
    cells = {}
    for opponent, weight in exact.opponent_hands(own, ranks):
        add_opponent(cells, own, opponent, weight, (lead, parents, rng))
    if sum(c["weight"] for c in cells.values()) != math.comb(4 * ranks - 4, 4):
        raise ValueError("Second-card cells do not partition the physical population")
    if rng.getstate() != random.Random(0).getstate():
        raise ValueError("Exact second cards require deterministic policies")
    return {
        "hand": list(own),
        "key": canonical_hand_key(own),
        "own_weight": exact.physical_weight(own),
        "lead": lead,
        "weight": sum(c["weight"] for c in cells.values()),
        "simulations": sum(
            c["opponent_multisets"] * len(c["totals"]) for c in cells.values()
        ),
        "replies": [finish_cell(cells[k]) for k in sorted(cells)],
    }


def build_second(rows, pone):
    """Install second-card entries beside the frozen lead entries, retaining fallback."""
    actions = dict(pone.actions)
    actions.update(
        {
            c["view_key"]: c["override"]
            for row in rows
            for c in row["replies"]
            if c["override"] is not None
        }
    )
    return TabularPeggingPolicy(actions, fallback=LegacyHeuristicPolicy())


def second_summary(rows):
    """Report exact marginal gain in the frozen-Dealer training population."""
    cells = [c for r in rows for c in r["replies"]]
    numerator = sum(
        r["own_weight"]
        * next(v["gain_sum"] for v in c["candidates"] if v["rank"] == c["override"])
        for r in rows
        for c in r["replies"]
        if c["override"] is not None
    )
    return {
        "observed_keys": len(cells),
        "optional_keys": sum(bool(c["candidates"]) for c in cells),
        "overrides": sum(c["override"] is not None for c in cells),
        "epsilon_zero_different_keys": sum(
            c["override"] != c["override_epsilon_zero"] for c in cells
        ),
        "exact_marginal_vs_frozen_dealer": exact.fraction_record(
            Fraction(numerator, exact.POPULATION_WEIGHT)
        ),
    }


def main():
    """Train only the approved second card, then gate and pair the marginal change."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pone", required=True, type=Path)
    parser.add_argument("--dealer", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--gate-deals", type=int, default=DEFAULT_GATE_DEALS)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.workers < 1 or args.gate_deals < 1000:
        parser.error("Need positive workers and at least 1000 gate deals")
    pone, dealer, parents = frozen_books(str(args.pone), str(args.dealer))
    started = time.monotonic()
    rows = exact.enumerate_jobs(
        [(h, str(args.pone), str(args.dealer), 13) for h in exact.HANDS],
        "pone-second",
        args.workers,
        exact_second_hand,
    )
    candidate = build_second(rows, parents[PONE])
    report = {
        "experiment": "issue-187-exact-pone-second-v1",
        "epsilon": exact.fraction_record(exact.EPSILON),
        "workers": args.workers,
        "pone_policy_fingerprint": pone["policy_fingerprint"],
        "dealer_policy_fingerprint": dealer["policy_fingerprint"],
        "summary": second_summary(rows),
        "simulations": sum(r["simulations"] for r in rows),
        "training_seconds": time.monotonic() - started,
        "evidence_sha256": exact.book.evidence_digest(rows),
        "policy_fingerprint": policy_fingerprint(candidate),
    }
    exact.write_report(args.output, report, rows)
    report["combined_gate"] = evaluate_promotion(
        {PONE: candidate, DEALER: parents[DEALER]},
        args.gate_deals,
        args.seed,
    )
    report["paired_marginal_gate"] = exact.checks.compare_pone(
        candidate,
        parents[PONE],
        args.gate_deals,
        args.seed,
    )
    report["elapsed_seconds"] = time.monotonic() - started
    exact.write_report(args.output, report, rows)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
