"""Report-only pair refinements scored from exact opening-book integer evidence."""

import argparse
from collections import Counter
from fractions import Fraction
import importlib
import json
from pathlib import Path

from artifact_pipeline.pegging import rank_count

exact = importlib.import_module("scratch.exact_pegging_book")


def pair_choice(row, counts, condition=("any", 0)):
    """Describe a candidate rule's lead for analysis, without creating a policy."""
    hand = row["hand"]
    pairs = [r for r, n in Counter(hand).items() if n >= 2 and rank_count(r) in counts]
    baseline = row["heuristic_lead"]
    if not pairs:
        return baseline
    chosen = min(pairs)
    other_low = min((rank_count(r) for r in hand if r != chosen), default=11)
    sense, threshold = condition
    if (sense == "le" and other_low > threshold) or (
        sense == "gt" and other_low <= threshold
    ):
        return baseline
    return chosen


def rule_score(rows, counts, condition=("any", 0)):
    """Sum the exact physical-population contribution of one fixed rule."""
    numerator = sum(
        row["own_weight"] * exact.gain_sum(row, pair_choice(row, counts, condition))
        for row in rows
    )
    return Fraction(numerator, exact.POPULATION_WEIGHT)


def pair_analysis(rows):
    """Score a finite simple-rule menu exhaustively inside this fixed model."""
    pairs = [r for r in rows if any(n >= 2 for n in Counter(r["hand"]).values())]
    winners = [
        r
        for r in pairs
        if any(
            Counter(r["hand"])[v["rank"]] >= 2
            and v["gain_sum"] == max(c["gain_sum"] for c in r["candidates"])
            for v in r["candidates"]
        )
    ]
    exact_gain = Fraction(
        sum(
            r["own_weight"] * max(v["gain_sum"] for v in r["candidates"]) for r in rows
        ),
        exact.POPULATION_WEIGHT,
    )
    always = rule_score(rows, range(1, 11))
    menus = [
        ("interval", tuple(range(lo, hi + 1)))
        for lo in range(1, 11)
        for hi in range(lo, 11)
    ]
    menus += [
        ("exclude-one-count", tuple(v for v in range(1, 11) if v != excluded))
        for excluded in range(1, 11)
    ]
    conditions = [("any", 0)] + [
        (sense, threshold) for sense in ("le", "gt") for threshold in range(1, 11)
    ]
    results = []
    for family, counts in menus:
        for condition in conditions:
            gain = rule_score(rows, counts, condition)
            results.append(
                {
                    "family": family,
                    "allowed_pair_counts": list(counts),
                    "other_card_condition": list(condition),
                    "gain_vs_heuristic": exact.fraction_record(gain),
                    "gain_vs_exact_book": exact.fraction_record(gain - exact_gain),
                }
            )
    results.sort(
        key=lambda r: (
            -Fraction(
                r["gain_vs_heuristic"]["numerator"],
                r["gain_vs_heuristic"]["denominator"],
            ),
            r["family"],
            r["allowed_pair_counts"],
            r["other_card_condition"],
        )
    )
    return {
        "paired_keys": len(pairs),
        "pair_is_one_exact_best_keys": len(winners),
        "paired_physical_own_weight": sum(r["own_weight"] for r in pairs),
        "pair_is_one_exact_best_physical_weight": sum(r["own_weight"] for r in winners),
        "always_pair_vs_heuristic": exact.fraction_record(always),
        "always_pair_vs_exact_book": exact.fraction_record(always - exact_gain),
        "exact_book_population_gain": exact.fraction_record(exact_gain),
        "candidate_rules": len(results),
        "best_rules": results[:2],
        "best_interval": next(r for r in results if r["family"] == "interval"),
        "best_exclude_one": next(
            r for r in results if r["family"] == "exclude-one-count"
        ),
        "rules": results,
    }


def main():
    """Read exact evidence and emit descriptive rule comparisons only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.book.read_bytes())
    if source["evidence_sha256"] != exact.book.evidence_digest(source["hands"]):
        raise ValueError("Exact evidence digest mismatch")
    report = pair_analysis(source["hands"])
    report["input_evidence_sha256"] = source["evidence_sha256"]
    exact.write_report(args.output, report)
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "rules"}, indent=2
        )
    )


if __name__ == "__main__":
    main()
