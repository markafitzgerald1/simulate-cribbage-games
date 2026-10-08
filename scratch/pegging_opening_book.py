"""Issue #187 Stage 1 research: improve only the Pone's first lead.

Run from an isolated working directory with the repository on PYTHONPATH:
python -m scratch.pegging_opening_book --output book.json --workers 8

This is an experiment, not a production artifact or a legacy CLI adapter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
from pathlib import Path
import random
import sys
import time
from typing import Any

from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    LegacyHeuristicPolicy,
    PeggingState,
    PolicyView,
    RunningStatistics,
    TabularPeggingPolicy,
    _stable_seed,
    canonical_hand_key,
    get_canonical_hands,
    policy_fingerprint,
    simulate_from_state,
)
from artifact_pipeline.promotion_gate import DEFAULT_GATE_DEALS, evaluate_promotion

TRAINING_LABEL = "issue-187-pone-opening-book-v1"
Z_THRESHOLD = 3.0


def opening_view(hand: tuple[int, ...]) -> PolicyView:
    """Use the simulator's exact information state for the first Pone play."""
    return PolicyView(PONE, tuple(sorted(hand)), 0, (), 4, (), ())


def remaining_deck(hand: tuple[int, ...]) -> tuple[int, ...]:
    """Remove physical representatives of all four known cards, including pairs."""
    cards = list(range(52))
    for rank in hand:
        cards.remove(next(card for card in cards if card // 4 == rank))
    return tuple(cards)


def select_override(
    values: dict[int, RunningStatistics], heuristic_lead: int
) -> int | None:
    """Select the largest positive paired mean meeting the nominal 3-SE screen."""
    eligible = [
        rank
        for rank, value in values.items()
        if rank != heuristic_lead
        and value.n >= 2
        and value.mean > 0
        and value.mean >= Z_THRESHOLD * value.standard_error
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda rank: (values[rank].mean, -rank))


def rollout_leads(
    hand: tuple[int, ...], opponent: tuple[int, ...], ranks: tuple[int, ...], seed: int
) -> dict[int, float]:
    """Force only the first play; freeze both continuation policies and the deal."""
    heuristic = LegacyHeuristicPolicy()
    policies = {PONE: heuristic, DEALER: heuristic}
    state = PeggingState(hands={PONE: list(hand), DEALER: list(opponent)})
    return {
        rank: simulate_from_state(
            state, policies, random.Random(seed), forced_rank=rank
        ).delta(PONE)
        for rank in ranks
    }


def train_hand(job: tuple[tuple[int, ...], int, int]) -> dict[str, Any]:
    """Evaluate every distinct lead on the same uniform physical opponent keeps."""
    hand, samples, seed = job
    if samples < 2:
        raise ValueError("At least two training samples are required")
    view = opening_view(hand)
    baseline = LegacyHeuristicPolicy().select_rank(view, random.Random(0))
    values = {rank: RunningStatistics() for rank in view.legal_ranks}
    pool = remaining_deck(hand)
    deal_rng = random.Random(_stable_seed(seed, TRAINING_LABEL, "deals", hand))
    for index in range(samples):
        opponent = tuple(card // 4 for card in deal_rng.sample(pool, 4))
        deltas = rollout_leads(
            hand,
            opponent,
            view.legal_ranks,
            _stable_seed(seed, TRAINING_LABEL, "play", hand, index),
        )
        for rank, delta in deltas.items():
            values[rank].add(delta - deltas[baseline])
    selected = select_override(values, baseline)
    return {
        "hand": list(hand),
        "key": canonical_hand_key(hand),
        "heuristic_lead": baseline,
        "override": selected,
        "candidates": [
            {
                "lead": rank,
                **value.to_dict(),
                "z": (
                    value.mean / value.standard_error if value.standard_error else None
                ),
            }
            for rank, value in values.items()
        ],
    }


def build_policy(rows: list[dict[str, Any]]) -> TabularPeggingPolicy:
    """Install opening-only entries; all later decisions use the same heuristic."""
    actions = {
        opening_view(tuple(row["hand"])).key(): row["override"]
        for row in rows
        if row["override"] is not None
    }
    return TabularPeggingPolicy(actions, fallback=LegacyHeuristicPolicy())


def evidence_digest(rows: list[dict[str, Any]]) -> str:
    """Hash canonical, unrounded evidence; runtimes are deliberately excluded."""
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def train_book(samples: int, seed: int, workers: int) -> list[dict[str, Any]]:
    """Process keys in canonical order, independent of pool scheduling."""
    if workers < 1:
        raise ValueError("Worker count must be positive")
    jobs = [(hand, samples, seed) for hand in get_canonical_hands()]
    started = time.monotonic()
    rows = []
    if workers == 1:
        results = map(train_hand, jobs)
        for row in results:
            rows.append(row)
    else:
        with multiprocessing.get_context("spawn").Pool(workers) as pool:
            for row in pool.imap(train_hand, jobs):
                rows.append(row)
                if len(rows) % 100 == 0:
                    print(
                        f"[opening-book] {len(rows)}/{len(jobs)} keys, "
                        f"{time.monotonic() - started:.1f}s",
                        file=sys.stderr,
                        flush=True,
                    )
    return rows


def main() -> None:
    """Write evidence and run the unchanged merged promotion gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=2500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gate-deals", type=int, default=DEFAULT_GATE_DEALS)
    args = parser.parse_args()
    if args.samples < 2 or args.workers < 1 or args.gate_deals < 1000:
        parser.error("Need samples >= 2, workers >= 1 and gate-deals >= 1000")
    started = time.monotonic()
    rows = train_book(args.samples, args.seed, args.workers)
    training_seconds = time.monotonic() - started
    policy = build_policy(rows)
    report = {
        "experiment": TRAINING_LABEL,
        "seed": args.seed,
        "samples_per_hand": args.samples,
        "workers": args.workers,
        "training_population": "uniform-physical-four-card-opponent-keeps-after-removal",
        "continuations": "legacy-heuristic-both-seats",
        "objective": "Pone pegging points minus Dealer pegging points",
        "z_threshold": Z_THRESHOLD,
        "z_note": "Nominal training screen, no multiple-comparison correction; null z means zero SE",
        "key_count": len(rows),
        "overrides": len(policy.actions),
        "evidence_sha256": evidence_digest(rows),
        "policy_fingerprint": policy_fingerprint(policy),
        "training_seconds": training_seconds,
        "hands": rows,
    }
    args.output.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        f"[opening-book] {len(policy.actions)} overrides; starting gate",
        file=sys.stderr,
        flush=True,
    )
    gate_started = time.monotonic()
    report["promotion_gate"] = evaluate_promotion(
        {PONE: policy, DEALER: LegacyHeuristicPolicy()}, args.gate_deals, args.seed
    )
    report["gate_seconds"] = time.monotonic() - gate_started
    report["elapsed_seconds"] = time.monotonic() - started
    report["production_style_report"] = {
        "status": "not-run",
        "reason": "Saved means and policy fingerprints do not contain retrievable discard keeps",
    }
    args.output.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "hands"}, indent=2
        )
    )


if __name__ == "__main__":
    main()
