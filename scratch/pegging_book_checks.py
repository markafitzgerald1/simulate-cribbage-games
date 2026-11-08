"""Independent confirmation and one fixed pair-rule experiment for issue #187.

Run `selection` first, then `patterns`, with separate output paths. Both are
research checks outside production; neither calculates Dealer replies.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction
import hashlib
import importlib
import json
import math
import multiprocessing
from pathlib import Path
import random
from statistics import mean
import sys
import time
from typing import Any

from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    LegacyHeuristicPolicy,
    PeggingPolicy,
    PolicyView,
    RunningStatistics,
    _stable_seed,
    policy_fingerprint,
    rank_count,
    simulate_pegging,
)
from artifact_pipeline.promotion_gate import (
    BOTH_SEATS,
    DEFAULT_GATE_DEALS,
    GATE_POPULATION,
    MINIMUM_GATE_DEALS,
    evaluate_promotion,
    gate_deals,
)

# Research modules remain outside the installed Python packages.
opening_book = importlib.import_module("scratch.pegging_opening_book")
FRESH_LABEL = "issue-187-pone-confirmation-v1"
CONTROL_LABEL = "issue-187-rejected-controls-v1"
VALIDATION_Z = 2.0
PAIR_RULE = (
    "initial-Pone: lowest repeated rank (multiplicity >= 2), otherwise heuristic"
)


@dataclass(frozen=True)
class SelectionSettings:
    """Fixed sampling budget, with separate confirmation and gate streams."""

    samples: int = 2500
    controls: int = 200
    seed: int = 42
    workers: int = 8
    deals: int = DEFAULT_GATE_DEALS


def read_book(path: Path) -> dict[str, Any]:
    """Require the original evidence and reconstructed policy to match their hashes."""
    report = json.loads(path.read_bytes())
    if report["evidence_sha256"] != opening_book.evidence_digest(report["hands"]):
        raise ValueError("Opening book evidence digest mismatch")
    if report["policy_fingerprint"] != policy_fingerprint(
        opening_book.build_policy(report["hands"])
    ):
        raise ValueError("Opening book policy fingerprint mismatch")
    return report


def confirmation_jobs(
    rows: list[dict[str, Any]], controls: int, samples: int, seed: int
) -> list[tuple[dict[str, Any], int, int, int, str]]:
    """Freeze original choices and sample eligible rejected keys without replacement."""
    if samples < 2 or controls < 0:
        raise ValueError("Need at least two samples and a nonnegative control count")
    accepted = [row for row in rows if row["override"] is not None]
    rejected = [
        row for row in rows if row["override"] is None and len(row["candidates"]) > 1
    ]
    if controls > len(rejected):
        raise ValueError("Control count exceeds eligible rejected keys")
    chosen = random.Random(_stable_seed(seed, CONTROL_LABEL)).sample(rejected, controls)
    jobs = [(row, row["override"], samples, seed, "accepted") for row in accepted]
    for row in chosen:
        alternatives = [
            value
            for value in row["candidates"]
            if value["lead"] != row["heuristic_lead"]
        ]
        best = max(
            alternatives,
            key=lambda value: (
                Fraction(
                    value.get("gain_sum", round(value["mu"] * value["n"])), value["n"]
                ),
                -value["lead"],
            ),
        )
        jobs.append((row, best["lead"], samples, seed, "rejected-control"))
    return jobs


def confirm_lead(job: tuple[dict[str, Any], int, int, int, str]) -> dict[str, Any]:
    """Re-estimate one previously fixed alternative on a fresh shared-deal stream."""
    row, selected, samples, seed, group = job
    if samples < 2 or selected == row["heuristic_lead"]:
        raise ValueError("Need two samples and a genuine alternative lead")
    hand = tuple(row["hand"])
    baseline = row["heuristic_lead"]
    original = next(value for value in row["candidates"] if value["lead"] == selected)
    pool = opening_book.remaining_deck(hand)
    rng = random.Random(_stable_seed(seed, FRESH_LABEL, "deals", hand))
    values = RunningStatistics()
    for index in range(samples):
        opponent = tuple(card // 4 for card in rng.sample(pool, 4))
        deltas = opening_book.rollout_leads(
            hand,
            opponent,
            (baseline, selected),
            _stable_seed(seed, FRESH_LABEL, "play", hand, index),
        )
        values.add(deltas[selected] - deltas[baseline])
    return {
        "key": row["key"],
        "hand": row["hand"],
        "group": group,
        "heuristic_lead": baseline,
        "tested_lead": selected,
        "original": original,
        "fresh": {
            **values.to_dict(),
            "z": values.mean / values.standard_error if values.standard_error else None,
        },
        "fresh_minus_original": values.mean - original["mu"],
        "passes_validation": values.mean > 0
        and values.mean >= VALIDATION_Z * values.standard_error,
    }


def confirm_jobs(jobs, workers: int) -> list[dict[str, Any]]:
    """Keep result order fixed across serial and spawned-pool execution."""
    if workers < 1:
        raise ValueError("Worker count must be positive")
    if workers == 1:
        return list(map(confirm_lead, jobs))
    rows = []
    started = time.monotonic()
    with multiprocessing.get_context("spawn").Pool(workers) as pool:
        for row in pool.imap(confirm_lead, jobs):
            rows.append(row)
            if len(rows) % 100 == 0:
                print(
                    f"[confirmation] {len(rows)}/{len(jobs)} keys, {time.monotonic() - started:.1f}s",
                    file=sys.stderr,
                    flush=True,
                )
    return rows


def quantiles(values: list[float]) -> dict[str, float]:
    """Return linearly interpolated empirical quantiles, without extra dependencies."""
    ordered = sorted(values)
    result = {}
    for fraction in (0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0):
        index = fraction * (len(ordered) - 1)
        lower = math.floor(index)
        upper = math.ceil(index)
        result[str(fraction)] = ordered[lower] + (index - lower) * (
            ordered[upper] - ordered[lower]
        )
    return result


def confirmation_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe key-level replication; these are equal-key descriptive summaries."""
    original = [row["original"]["mu"] for row in rows]
    fresh = [row["fresh"]["mu"] for row in rows]
    differences = [new - old for new, old in zip(fresh, original)]
    if not rows:
        return {"keys": 0}
    return {
        "keys": len(rows),
        "fresh_positive": sum(value > 0 for value in fresh),
        "fresh_negative": sum(value < 0 for value in fresh),
        "fresh_zero": sum(value == 0 for value in fresh),
        "passes_validation": sum(row["passes_validation"] for row in rows),
        "original_mean": mean(original),
        "fresh_mean": mean(fresh),
        "fresh_minus_original_mean": mean(differences),
        "original_quantiles": quantiles(original),
        "fresh_quantiles": quantiles(fresh),
        "fresh_minus_original_quantiles": quantiles(differences),
    }


def restricted_policy(original_rows, confirmations):
    """Delete failed original entries; controls can never add an action."""
    retained = {
        row["key"]
        for row in confirmations
        if row["group"] == "accepted" and row["passes_validation"]
    }
    rows = [
        {**row, "override": row["override"] if row["key"] in retained else None}
        for row in original_rows
    ]
    return opening_book.build_policy(rows)


def compare_pone(
    candidate: PeggingPolicy, reference: PeggingPolicy, deals: int, seed: int
) -> dict[str, Any]:
    """Compare Pone policies on duplicate gate deals with the same heuristic Dealer.

    Two games suffice because Dealer is unchanged. Both-seat gain is half each
    per-deal Pone gain, not a difference of separately estimated means.
    """
    if deals < MINIMUM_GATE_DEALS:
        raise ValueError("At least 1,000 gate deals are required")
    heuristic = LegacyHeuristicPolicy()
    estimates = {seat: RunningStatistics() for seat in (PONE, DEALER, BOTH_SEATS)}
    for pone, dealer, play_seed in gate_deals(deals, seed):
        reference_result = simulate_pegging(
            pone, dealer, {PONE: reference, DEALER: heuristic}, random.Random(play_seed)
        )
        candidate_result = simulate_pegging(
            pone, dealer, {PONE: candidate, DEALER: heuristic}, random.Random(play_seed)
        )
        gain = candidate_result.delta(PONE) - reference_result.delta(PONE)
        estimates[PONE].add(gain)
        estimates[DEALER].add(0.0)
        estimates[BOTH_SEATS].add(gain / 2)
    both = estimates[BOTH_SEATS]
    return {
        "population": GATE_POPULATION,
        "deals": deals,
        "seed": seed,
        **{seat: value.to_dict() for seat, value in estimates.items()},
        "passed": both.mean > 0 and both.mean >= 3 * both.standard_error,
    }


def run_selection(source, settings: SelectionSettings):
    """Execute A with choices and thresholds fixed before fresh observations."""
    started = time.monotonic()
    original_rows = source["hands"]
    jobs = confirmation_jobs(
        original_rows, settings.controls, settings.samples, settings.seed
    )
    confirmations = confirm_jobs(jobs, settings.workers)
    resampling_seconds = time.monotonic() - started
    original = opening_book.build_policy(original_rows)
    restricted = restricted_policy(original_rows, confirmations)
    original_gate = evaluate_promotion(
        {PONE: original, DEALER: LegacyHeuristicPolicy()}, settings.deals, 43
    )
    restricted_gate = evaluate_promotion(
        {PONE: restricted, DEALER: LegacyHeuristicPolicy()}, settings.deals, 43
    )
    difference = compare_pone(restricted, original, settings.deals, 43)
    tests = sum(len(row["candidates"]) - 1 for row in original_rows)
    alpha = 0.5 * math.erfc(3 / math.sqrt(2))
    return {
        "experiment": FRESH_LABEL,
        "seed": settings.seed,
        "samples": settings.samples,
        "workers": settings.workers,
        "validation_z": VALIDATION_Z,
        "control_label": CONTROL_LABEL,
        "controls": settings.controls,
        "eligible_rejected_keys": sum(
            row["override"] is None and len(row["candidates"]) > 1
            for row in original_rows
        ),
        "original_policy_fingerprint": source["policy_fingerprint"],
        "restricted_policy_fingerprint": policy_fingerprint(restricted),
        "evidence_sha256": opening_book.evidence_digest(confirmations),
        "accepted": confirmation_summary(
            [row for row in confirmations if row["group"] == "accepted"]
        ),
        "rejected_controls": confirmation_summary(
            [row for row in confirmations if row["group"] == "rejected-control"]
        ),
        "null_benchmark": {
            "alternative_tests": tests,
            "one_sided_alpha": alpha,
            "expected_if_all_null": tests * alpha,
        },
        "original_gate": original_gate,
        "restricted_gate": restricted_gate,
        "restricted_minus_original": difference,
        "resampling_seconds": resampling_seconds,
        "elapsed_seconds": time.monotonic() - started,
        "confirmations": confirmations,
    }


@dataclass
class PairLeadPolicy:
    """One fixed Pone-only pair rule with the exact legacy continuation fallback."""

    fallback: PeggingPolicy = field(default_factory=LegacyHeuristicPolicy)

    def select_rank(self, view: PolicyView, rng: random.Random) -> int:
        if len(view.own_remaining) == 4 and view == opening_book.opening_view(
            view.own_remaining
        ):
            pairs = sorted(
                rank
                for rank, count in Counter(view.own_remaining).items()
                if count >= 2
            )
            if pairs:
                return pairs[0]
        return self.fallback.select_rank(view, rng)


def lead_features(hand: list[int], lead: int) -> dict[str, bool]:
    """Classify rank facts; overlapping groups are not policy recommendations."""
    counts = Counter(hand)
    distinct = set(hand)
    return {
        "lead_from_repeated_rank": counts[lead] >= 2,
        "lead_from_exact_pair": counts[lead] == 2,
        "lead_is_lowest": lead == min(hand),
        "lead_is_highest": lead == max(hand),
        "lead_is_middle": min(hand) < lead < max(hand),
        "lead_count_above_ten": rank_count(lead) > 10,
        "lead_has_ten_value": rank_count(lead) == 10,
        "lead_is_face_rank": lead >= 10,
        "hand_has_repeated_rank": any(count >= 2 for count in counts.values()),
        "hand_has_two_pairs": list(counts.values()).count(2) == 2,
        "hand_has_triple": 3 in counts.values(),
        "hand_has_run_of_three": any(
            {rank, rank + 1, rank + 2} <= distinct for rank in range(11)
        ),
        "hand_has_run_of_four": len(distinct) == 4 and max(hand) - min(hand) == 3,
    }


def pattern_summary(original_rows, confirmations):
    """Report equal-key means for overlapping feature groups declared in advance."""
    fresh = {
        row["key"]: row["fresh"]["mu"]
        for row in confirmations
        if row["group"] == "accepted"
    }
    selected = [row for row in original_rows if row["override"] is not None]
    features = {
        row["key"]: lead_features(row["hand"], row["override"]) for row in selected
    }
    output = {}
    for feature in next(iter(features.values())):
        group = [row for row in selected if features[row["key"]][feature]]
        output[feature] = {
            "keys": len(group),
            "original_mean": (
                mean(
                    next(
                        v["mu"]
                        for v in row["candidates"]
                        if v["lead"] == row["override"]
                    )
                    for row in group
                )
                if group
                else None
            ),
            "fresh_mean": mean(fresh[row["key"]] for row in group) if group else None,
        }
    return output


def run_patterns(source, confirmation, deals: int):
    """Execute B only after A; gate one pair rule against two fixed references."""
    started = time.monotonic()
    original = opening_book.build_policy(source["hands"])
    rule = PairLeadPolicy()
    vs_heuristic = evaluate_promotion(
        {PONE: rule, DEALER: LegacyHeuristicPolicy()}, deals, 44
    )
    vs_book = compare_pone(rule, original, deals, 44)
    selected = [row for row in source["hands"] if row["override"] is not None]
    agreements = sum(
        rule.select_rank(
            opening_book.opening_view(tuple(row["hand"])), random.Random(0)
        )
        == row["override"]
        for row in selected
    )
    return {
        "experiment": "issue-187-pair-lead-rule-v1",
        "rule": PAIR_RULE,
        "features": pattern_summary(source["hands"], confirmation["confirmations"]),
        "rule_agrees_with_original_overrides": agreements,
        "rule_vs_heuristic": vs_heuristic,
        "rule_vs_original_book": vs_book,
        "elapsed_seconds": time.monotonic() - started,
    }


def main() -> None:
    """Run A or B explicitly, retaining the independent streams and full evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("selection", "patterns"))
    parser.add_argument(
        "--book",
        type=Path,
        default=Path(__file__).with_name("issue187_pone_opening_book.json"),
    )
    parser.add_argument("--confirmation", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=2500)
    parser.add_argument("--controls", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--gate-deals", type=int, default=DEFAULT_GATE_DEALS)
    args = parser.parse_args()
    if args.gate_deals < MINIMUM_GATE_DEALS or args.samples < 2 or args.workers < 1:
        parser.error("Need gate-deals >= 1000, samples >= 2 and workers >= 1")
    source = read_book(args.book)
    if args.stage == "selection":
        report = run_selection(
            source,
            SelectionSettings(
                args.samples, args.controls, args.seed, args.workers, args.gate_deals
            ),
        )
    else:
        if args.confirmation is None:
            parser.error("patterns requires the completed --confirmation report")
        confirmation = json.loads(args.confirmation.read_bytes())
        if confirmation["evidence_sha256"] != opening_book.evidence_digest(
            confirmation["confirmations"]
        ):
            raise ValueError("Confirmation evidence digest mismatch")
        if confirmation["original_policy_fingerprint"] != source["policy_fingerprint"]:
            raise ValueError("Confirmation belongs to a different opening book")
        report = run_patterns(source, confirmation, args.gate_deals)
    report["input_file_sha256"] = hashlib.sha256(args.book.read_bytes()).hexdigest()
    args.output.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "confirmations"},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
