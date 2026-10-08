"""Rebuild the generator's heuristic-enforce discard population for reports."""

import argparse
from collections import defaultdict
import hashlib
import importlib
import json
from pathlib import Path
import random
import time
from types import SimpleNamespace

from artifact_pipeline import generate_play_table as generator
from artifact_pipeline.pegging import DEALER, PONE, get_canonical_hands, _stable_seed

product = importlib.import_module("scratch.book_product_checks")


def build_population(output):
    """Use exactly the production analytical initialization and enforce fallback."""
    started = time.monotonic()
    context = generator.solve_initial_discard_policy(40, 2)
    initialization_seconds = time.monotonic() - started
    args = SimpleNamespace(outer_iterations=2, policy_table_samples=200, seed=42)
    gate = {"passed": False}
    _, context, converged = generator.heuristic_fallback(
        gate, context, args, get_canonical_hands()
    )
    discard = generator.selected_discards_to_policy(context.selected_discards)
    rows = [
        [role, list(hand), list(keep)]
        for (role, hand), keep in sorted(discard.kept_by_role_and_hand.items())
    ]
    populations = {r: defaultdict(int) for r in (PONE, DEALER)}
    for role, hand, keep in rows:
        populations[role][
            generator.canonical_hand_key(keep)
        ] += product.exact.physical_weight(hand)
    report = {
        "configuration": {
            "analytical_max_iterations": 40,
            "full_hand_policy_max_iterations": 2,
            "outer_iterations": 2,
            "policy_table_samples": 200,
            "seed": 42,
        },
        "initialization_seconds": initialization_seconds,
        "elapsed_seconds": time.monotonic() - started,
        "converged": converged,
        "refinement": gate["discard_refinement"],
        "discard_policy_fingerprint": generator.discard_keeps_fingerprint(discard),
        "six_hand_physical_weight_per_role": {
            r: sum(v.values()) for r, v in populations.items()
        },
        "keep_populations": {
            r: dict(sorted(v.items())) for r, v in populations.items()
        },
        "keeps": rows,
    }
    report["keeps_sha256"] = hashlib.sha256(
        json.dumps(rows, separators=(",", ":")).encode()
    ).hexdigest()
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def read_population(path):
    """Validate the regenerated keep mapping, preserving all six known cards."""
    report = json.loads(Path(path).read_bytes())
    if (
        report["keeps_sha256"]
        != hashlib.sha256(
            json.dumps(report["keeps"], separators=(",", ":")).encode()
        ).hexdigest()
    ):
        raise ValueError("Keep population digest mismatch")
    discard = generator.DiscardPolicy(
        {(r, tuple(h)): tuple(k) for r, h, k in report["keeps"]}
    )
    if (
        generator.discard_keeps_fingerprint(discard)
        != report["discard_policy_fingerprint"]
    ):
        raise ValueError("Keep policy fingerprint mismatch")
    return report, discard


def production_deals(discard, count, seed):
    """Draw actual twelve-card deals and use the regenerated role-specific keeps."""
    rng = random.Random(repr((seed, "issue-187-production-report-v1", "deals")))
    for index in range(count):
        pone, dealer = generator.sample_policy_deal(rng, discard)
        yield pone, dealer, _stable_seed(
            seed, "issue-187-production-report-v1", "play", index
        )


def timing(discard, policies, hands, samples, seed):
    """Time bounded real generator measurements, without full final generation."""
    started = time.monotonic()
    generator.generate_play_table(discard, policies, samples, seed, hands=hands)
    return time.monotonic() - started


def main():
    """Build keeps first, then use one common population for all report arms."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("build", "compare", "timing"))
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--deals", type=int, default=200000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.stage != "build" and args.output is None:
        parser.error("Measurement requires --output")
    if args.deals < 1000:
        parser.error("Need at least 1000 deals")
    if args.stage == "build":
        report = build_population(args.population)
    else:
        source, discard = read_population(args.population)
        paths = tuple(
            str(Path(__file__).with_name(n).resolve())
            for n in (
                "issue187_exact_pone.json",
                "issue187_exact_dealer.json",
                "issue187_exact_second_card.json",
            )
        )
        _, parents, combined = product.load_books(paths)
        if args.stage == "compare":
            started = time.monotonic()
            report = product.evaluate_policy_comparisons(
                product.matchup_games(parents, combined),
                production_deals(discard, args.deals, args.seed),
                "generator heuristic-refined six-card keeps",
            )
            report["elapsed_seconds"] = time.monotonic() - started
        else:
            hands = random.Random(42).sample(get_canonical_hands(), 200)
            games = product.matchup_games(parents, combined)
            report = {
                "hands": len(hands),
                "samples_per_role": 200,
                "seed": args.seed,
                "timings": {},
            }
            for repeat in range(3):
                order = (
                    ("heuristic-both", "books12-both")
                    if repeat % 2 == 0
                    else ("books12-both", "heuristic-both")
                )
                for name in order:
                    report["timings"].setdefault(name, []).append(
                        timing(discard, games[name], hands, 200, args.seed)
                    )
        report["seed"] = args.seed
        report["policy_fingerprints"] = {
            name: {r: product.policy_fingerprint(p) for r, p in policies.items()}
            for name, policies in product.matchup_games(parents, combined).items()
        }
        report["discard_policy_fingerprint"] = source["discard_policy_fingerprint"]
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in ("keeps", "keep_populations")},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
