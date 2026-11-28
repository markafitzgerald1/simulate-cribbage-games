"""Run the issue #263 strength ladder from the command line.

Rungs differ only in pegging: random, the legacy heuristic, and a CFR+
six-layer policy loaded from a verified bundle. Every rung shares one
discard rule, either the frozen rank-only discard population bound into
that bundle's manifest or uniformly random keeps, so a rung's edge over the
one below it measures pegging alone. A --table-player instead discards as
the cribbage-trainer app advises from a crib and a play table, with any of
the three pegging policies; the report records each table's SHA-256. The
table counts the CFR policy's
calls by what it did: heuristic fallbacks (no stored menu), off-support
calls (zero opponent reach under its saved policy and prior; it still
samples its stored row), and all calls including forced ones. Results go to
stdout as a Markdown table and, optionally, to a JSON file holding every
match in both orientations.

Parallel workers are forked, so --workers above 1 needs a platform with the
fork start method.

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
import multiprocessing
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
from artifact_pipeline.six_layer_policy import SixLayerPolicy, read_manifest
from artifact_pipeline.table_discards import (
    TableDiscardRule,
    load_crib_table,
    load_play_table,
)

SCHEMA = "cribbage-strength-ladder.v1"
RUNGS = ("random", "heuristic", "cfr")


@dataclass(frozen=True)
class RankDiscardRule:  # pylint: disable=too-few-public-methods
    """Keep the ranks a complete rank-only discard policy names.

    Ranks fix the keep. Among cards of a kept rank, the seat's discard
    stream picks which to keep, so no suit is favoured.
    """

    policy: DiscardPolicy

    def select_discard(
        self, role: str, dealt: Sequence[PhysicalCard], rng: random.Random
    ) -> Split:
        """Return the policy's keep and the two remaining cards."""
        shuffled = sorted(dealt)
        rng.shuffle(shuffled)
        kept = self.policy.keep_physical_cards(role, shuffled)
        for card in kept:
            shuffled.remove(card)
        return tuple(sorted(kept)), tuple(sorted(shuffled))


def _validate(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    tables = {player[0]: player for player in args.table_player}
    known = set(RUNGS) | set(tables)
    if len(tables) != len(args.table_player) or set(tables) & set(RUNGS):
        parser.error(f"--table-player names must be distinct and not in {RUNGS}")
    if any(player[1] not in RUNGS for player in args.table_player):
        parser.error(f"--table-player pegging must be one of {RUNGS}")
    missing = [
        path
        for player in args.table_player
        for path in player[2:]
        if path != "none" and not Path(path).is_file()
    ]
    if missing:
        parser.error(f"--table-player files not found: {', '.join(missing)}")
    names = args.rungs
    if len(names) < 2 or len(set(names)) != len(names) or set(names) - known:
        parser.error(f"--rungs needs two or more distinct names from {sorted(known)}")
    pegging = {tables[name][1] if name in tables else name for name in names}
    uses_bundle_discards = bool(set(names) & set(RUNGS))
    needs_bundle = (
        args.discards == "bundle" and uses_bundle_discards
    ) or "cfr" in pegging
    if needs_bundle != bool(args.policy_manifest):
        parser.error(
            "--policy-manifest is needed for bundle discards or the cfr rung, "
            "and only then"
        )
    if min(args.pairs, args.workers, args.cache_limit) < 1:
        parser.error("--pairs, --workers and --cache-limit must be positive")
    if args.workers > 1 and "fork" not in multiprocessing.get_all_start_methods():
        parser.error("--workers above 1 needs the fork start method")
    if args.output:
        if not args.output.parent.is_dir():
            parser.error(f"--output directory does not exist: {args.output.parent}")
        if args.policy_manifest and _aliases_bundle(args.output, args.policy_manifest):
            parser.error("--output must not be, or link to, a file of the bundle")
        if args.output.exists() and any(
            path != "none" and args.output.samefile(path)
            for player in args.table_player
            for path in player[2:]
        ):
            parser.error("--output must not be a table file")


def _aliases_bundle(output: Path, manifest: Path) -> bool:
    """Return whether writing output could touch a file of the bundle."""
    bundle = manifest.parent
    if output.resolve().is_relative_to(bundle):
        return True
    if not output.exists():
        return False
    target = output.stat()
    return any(
        path.is_file()
        and (path.stat().st_dev, path.stat().st_ino) == (target.st_dev, target.st_ino)
        for path in bundle.rglob("*")
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse and check the ladder's command-line options."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    parser.add_argument("--policy-manifest", type=Path)
    parser.add_argument(
        "--policy-manifest-sha256", help="refuse a manifest with other bytes"
    )
    parser.add_argument("--discards", choices=("bundle", "random"), default="bundle")
    parser.add_argument("--rungs")
    parser.add_argument(
        "--table-player",
        nargs=4,
        action="append",
        default=[],
        metavar=("NAME", "PEGGING", "CRIB", "PLAY"),
        help="a player discarding by the app's tables; CRIB or PLAY may be none",
    )
    parser.add_argument("--pairs", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--cache-limit", type=int, default=4096)
    parser.add_argument("--cross-table", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    args.rungs = (
        [name.strip() for name in args.rungs.split(",")]
        if args.rungs is not None
        else [*RUNGS, *(player[0] for player in args.table_player)]
    )
    if args.policy_manifest:
        # Load components, discards and the output guard from one directory,
        # even when the manifest path is a symbolic link.
        args.policy_manifest = args.policy_manifest.resolve()
    _validate(parser, args)
    return args


def _load_bundle(
    args: argparse.Namespace, stack: ExitStack, provenance: dict[str, Any]
) -> tuple[SixLayerPolicy | None, Mapping[str, Any]]:
    manifest_bytes = args.policy_manifest.read_bytes()
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    if args.policy_manifest_sha256 not in (None, digest):
        raise ValueError(f"Policy manifest SHA-256 is {digest}, not the one given")
    provenance["policy_manifest_sha256"] = digest
    policy = None
    if needs_policy(args):
        policy = stack.enter_context(
            SixLayerPolicy(args.policy_manifest, cache_limit=args.cache_limit)
        )
        manifest = policy.manifest
        provenance["policy_fingerprint"] = policy.behavioral_fingerprint
    else:
        manifest = read_manifest(args.policy_manifest)
    # Hash and use the same manifest: refuse one replaced while loading.
    if manifest != json.loads(manifest_bytes):
        raise ValueError("Policy manifest changed while it was being loaded")
    return policy, manifest


def needs_policy(args: argparse.Namespace) -> bool:
    """Return whether any chosen rung pegs with the CFR policy."""
    tables = {player[0]: player[1] for player in args.table_player}
    return any(tables.get(name, name) == "cfr" for name in args.rungs)


def _load_table(path: str, provenance: dict[str, str], label: str) -> Any:
    if path == "none":
        return None
    data = Path(path).read_bytes()
    provenance[f"{label}_sha256"] = hashlib.sha256(data).hexdigest()
    table = json.loads(data)
    if not isinstance(table, dict):
        raise ValueError(f"{label} table is not a JSON object: {path}")
    return table


def _table_rule(player: Sequence[str], provenance: dict[str, Any]) -> DiscardRule:
    record = {"pegging": player[1]}
    provenance.setdefault("table_players", {})[player[0]] = record
    crib = _load_table(player[2], record, "crib")
    play = _load_table(player[3], record, "play")
    return TableDiscardRule(
        None if crib is None else load_crib_table(crib),
        None if play is None else load_play_table(play),
    )


def build_players(
    args: argparse.Namespace, stack: ExitStack
) -> tuple[list[LadderPlayer], dict[str, Any]]:
    """Return the ladder's players, bottom rung first, and their provenance."""
    provenance: dict[str, Any] = {"discards": args.discards}
    policy: SixLayerPolicy | None = None
    manifest: Mapping[str, Any] = {}
    if args.policy_manifest:
        policy, manifest = _load_bundle(args, stack, provenance)
    discard_rule: DiscardRule = RandomDiscardRule()
    if args.discards == "bundle" and set(args.rungs) & set(RUNGS):
        population = manifest["discard_population"]
        discard_rule = RankDiscardRule(
            load_fixed_discards(args.policy_manifest.parent, population)
        )
        provenance["discard_population_sha256"] = population["sha256"]
    pegging: dict[str, tuple[PeggingPolicy, str]] = {
        "random": (RandomPeggingPolicy(), "uniformly random playable card"),
        "heuristic": (LegacyHeuristicPolicy(), "legacy simulator's default play"),
    }
    if policy is not None:
        pegging["cfr"] = (policy, "CFR+ six-layer policy from the bundle")
    tables = {player[0]: player for player in args.table_player}
    players = []
    for name in args.rungs:
        if name in tables:
            rule = _table_rule(tables[name], provenance)
            style = tables[name][1]
            discards = "app-table"
        else:
            rule, style, discards = discard_rule, name, args.discards
        players.append(
            LadderPlayer(
                name,
                rule,
                pegging[style][0],
                f"{discards} discards, {pegging[style][1]}",
            )
        )
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


def _decisions(match: Mapping[str, Any]) -> str:
    if not match["policy_decisions"]:
        return "n/a"
    totals: Counter[str] = Counter()
    for counts in match["policy_decisions"].values():
        totals.update(counts)
    return (
        f"{totals['missing_menu_fallback']:,} / {totals['off_support']:,} "
        f"/ {sum(totals.values()):,}"
    )


def format_summary(report: Mapping[str, Any]) -> str:
    """Return a Markdown table of each higher rung against each lower one."""
    names = [rung["name"] for rung in report["rungs"]]
    by_pair = {(m["player"], m["opponent"]): m for m in report["matches"]}
    tables = list(report["provenance"].get("table_players", {}))
    discards = [f"app-table discards for {', '.join(tables)}"] if tables else []
    if set(names) - set(tables):
        discards.insert(0, f"{report['provenance']['discards']} discards")
    lines = [
        f"{report['pairs_per_match']:,} deal pairs per match, seed {report['seed']}, "
        f"{'; '.join(discards)}. Win rate and Elo are for the "
        "upper rung; +/- is one standard error over deal pairs.",
        "",
        "| Rung vs lower | Win % | Elo | Won both / split / lost both "
        "| Point margin | CFR calls: fallback / off-support / all |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for high in range(1, len(names)):
        for low in range(high):
            match = by_pair.get((names[high], names[low]))
            if match is None:
                continue
            win, outcomes = match["win_rate"], match["pair_outcomes"]
            margin = match["point_margin"]
            lines.append(
                f"| {names[high]} vs {names[low]} "
                f"| {_plus_minus(win['mu'], win['se'], 100)} "
                f"| {_plus_minus(match['elo'], match['elo_se'])} "
                f"| {outcomes['both_won']:,} / {outcomes['split']:,} "
                f"/ {outcomes['both_lost']:,} "
                f"| {_plus_minus(margin['mu'], margin['se'])} | {_decisions(match)} |"
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
