"""Run the issue #263 strength ladder from the command line.

Rungs differ only in pegging: random, the legacy heuristic, and the pinned
CFR+ six-layer policy. Every rung shares one discard rule, either the
frozen rank-only discard population bound into the CFR policy manifest or
uniformly random keeps, so a rung's edge over the one below it measures
pegging alone. The table counts the CFR policy's calls that fell back to the
heuristic (no stored menu) and those outside its certified support, where it
still plays its stored row. Results go to stdout as a Markdown table and, optionally, to
a JSON file holding every match in both orientations.

Usage:
    python -m artifact_pipeline.strength_ladder \\
        --policy-manifest <bundle>/policy.json --pairs 50000 --workers 8
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import platform
import random
from typing import Any, Mapping, Sequence

from artifact_pipeline.fixed_play_inputs import load_fixed_discards
from artifact_pipeline.generate_play_table import DiscardPolicy
from artifact_pipeline.ladder_game import (
    TARGET_SCORE,
    DiscardRule,
    LadderPlayer,
    PhysicalCard,
    RandomDiscardRule,
    RandomPeggingPolicy,
    Split,
)
from artifact_pipeline.ladder_match import MatchAccumulator, run_ladder
from artifact_pipeline.pegging import LegacyHeuristicPolicy, PeggingPolicy
from artifact_pipeline.six_layer_policy import SixLayerPolicy

SCHEMA = "cribbage-strength-ladder.v1"
RUNGS = ("random", "heuristic", "cfr")


@dataclass(frozen=True)
class RankDiscardRule:  # pylint: disable=too-few-public-methods
    """Keep the ranks a complete rank-only discard policy names.

    Ranks fix the keep; among cards of a kept rank, the lowest suit index is
    kept, so the rule is blind to flushes and nobs.
    """

    policy: DiscardPolicy

    def select_discard(
        self, role: str, dealt: Sequence[PhysicalCard], rng: random.Random
    ) -> Split:
        """Return the policy's keep and the two remaining cards."""
        del rng
        ordered = sorted(dealt)
        kept = self.policy.keep_physical_cards(role, ordered)
        for card in kept:
            ordered.remove(card)
        return kept, tuple(ordered)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the ladder's command-line options."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    parser.add_argument("--policy-manifest", type=Path)
    parser.add_argument("--discards", choices=("bundle", "random"), default="bundle")
    parser.add_argument("--rungs", default=",".join(RUNGS))
    parser.add_argument("--pairs", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--cache-limit", type=int, default=4096)
    parser.add_argument("--cross-table", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    names = [name.strip() for name in args.rungs.split(",")]
    if len(names) < 2 or len(set(names)) != len(names) or set(names) - set(RUNGS):
        parser.error(f"--rungs needs two or more distinct names from {RUNGS}")
    if (args.discards == "bundle" or "cfr" in names) and not args.policy_manifest:
        parser.error("--policy-manifest is needed for bundle discards or the cfr rung")
    if min(args.pairs, args.workers, args.cache_limit) < 1:
        parser.error("--pairs, --workers and --cache-limit must be positive")
    args.rungs = names
    return args


def build_players(
    args: argparse.Namespace, stack: ExitStack
) -> tuple[list[LadderPlayer], dict[str, Any]]:
    """Return the ladder's players, bottom rung first, and their provenance."""
    provenance: dict[str, Any] = {"discards": args.discards}
    policy: SixLayerPolicy | None = None
    if args.policy_manifest:
        policy = stack.enter_context(
            SixLayerPolicy(args.policy_manifest, cache_limit=args.cache_limit)
        )
        provenance["policy_manifest_sha256"] = hashlib.sha256(
            args.policy_manifest.read_bytes()
        ).hexdigest()
        provenance["policy_fingerprint"] = policy.behavioral_fingerprint
    discard_rule: DiscardRule = RandomDiscardRule()
    if args.discards == "bundle":
        assert policy is not None
        population = policy.manifest["discard_population"]
        discard_rule = RankDiscardRule(
            load_fixed_discards(args.policy_manifest.parent, population)
        )
        provenance["discard_population_sha256"] = population["sha256"]
    pegging: dict[str, tuple[PeggingPolicy, str]] = {
        "random": (RandomPeggingPolicy(), "uniformly random playable card"),
        "heuristic": (LegacyHeuristicPolicy(), "legacy simulator's default play"),
    }
    if policy is not None:
        pegging["cfr"] = (policy, "pinned CFR+ six-layer policy")
    players = [
        LadderPlayer(
            name,
            discard_rule,
            pegging[name][0],
            f"{args.discards} discards, {pegging[name][1]}",
        )
        for name in args.rungs
    ]
    return players, provenance


def build_report(
    args: argparse.Namespace,
    players: Sequence[LadderPlayer],
    provenance: Mapping[str, Any],
    results: Mapping[tuple[str, str], MatchAccumulator],
) -> dict[str, Any]:
    """Return the JSON report: inputs, rungs and every match both ways."""
    return {
        "schema": SCHEMA,
        "seed": args.seed,
        "pairs_per_match": args.pairs,
        "target_score": TARGET_SCORE,
        "cross_table": args.cross_table,
        "python": platform.python_version(),
        "provenance": dict(provenance),
        "rungs": [{"name": p.name, "description": p.description} for p in players],
        "matches": [
            {"player": player, "opponent": opponent, **match.summary()}
            for (player, opponent), match in sorted(results.items())
        ],
    }


def _plus_minus(value: float | None, error: float | None, scale: float = 1) -> str:
    if value is None:
        return "n/a"
    if error is None:
        return f"{scale * value:.2f}"
    return f"{scale * value:.2f} +/- {scale * error:.2f}"


def format_summary(report: Mapping[str, Any]) -> str:
    """Return a Markdown table of each rung against the one below it."""
    names = [rung["name"] for rung in report["rungs"]]
    by_pair = {(m["player"], m["opponent"]): m for m in report["matches"]}
    lines = [
        f"{report['pairs_per_match']:,} deal pairs per match, seed {report['seed']}, "
        f"{report['provenance']['discards']} discards. Win rate and Elo are for the "
        "upper rung; +/- is one standard error over deal pairs.",
        "",
        "| Rung vs below | Win % | Elo | Won both / split / lost both "
        "| Point margin | CFR calls: fallback / off-support / all |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for below, above in zip(names, names[1:]):
        match = by_pair[(above, below)]
        win, outcomes = match["win_rate"], match["pair_outcomes"]
        totals: Counter[str] = Counter()
        for counts in match["policy_decisions"].values():
            totals.update(counts)
        decisions = (
            f"{totals['missing_menu_fallback']:,} / {totals['off_support']:,} "
            f"/ {sum(totals.values()):,}"
            if match["policy_decisions"]
            else "n/a"
        )
        lines.append(
            f"| {above} vs {below} | {_plus_minus(win['mu'], win['se'], 100)} "
            f"| {_plus_minus(match['elo'], match['elo_se'])} "
            f"| {outcomes['both_won']:,} / {outcomes['split']:,} "
            f"/ {outcomes['both_lost']:,} "
            f"| {_plus_minus(match['point_margin']['mu'], match['point_margin']['se'])} "
            f"| {decisions} |"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Play the ladder, print its summary and optionally write the report."""
    args = parse_args(argv)
    with ExitStack() as stack:
        players, provenance = build_players(args, stack)
        results = run_ladder(
            players,
            args.pairs,
            args.seed,
            cross_table=args.cross_table,
            workers=args.workers,
        )
    report = build_report(args, players, provenance, results)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(format_summary(report))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
