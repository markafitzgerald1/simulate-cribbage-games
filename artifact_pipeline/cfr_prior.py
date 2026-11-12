"""Build the CFR solver's discard population and its 50/50 chance prior.

Issue #203 publishes the inputs to the Rust CFR+ solve in `native/cfr`
(PR #229, not yet on main). This module makes the two that the Rust code
does not:

1. The discard population: the production generator's seeded
   heuristic-refined discards (the `--promotion-gate=enforce` fallback in
   `generate_play_table`), one kept hand per role and six-card rank
   multiset. It is written without timing fields, so equal inputs on the
   same interpreter give equal bytes. (Its refinement report carries the
   generator's float shift statistics, which assume IEEE doubles.)
2. The prior: a 1,820 x 1,820 matrix of little-endian u64 chance weights
   indexed `[pone_keep * 1820 + dealer_keep]` in `get_canonical_hands`
   order, which is the layout the Rust `solve --prior` reads. It is the
   exact 50/50 probability mixture of two physical weightings of kept-hand
   pairs: uniform four-card deals, and twelve-card deals mapped through the
   population's keeps (the production matrix).

Every weight is an exact count of physical deals, so the output depends on
no floating-point order.
"""

from __future__ import annotations

import argparse
from array import array
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from itertools import combinations, combinations_with_replacement, product
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

if __package__ in (None, ""):  # pragma: no cover
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# pylint: disable=wrong-import-position
from artifact_pipeline import generate_play_table as generator  # noqa: E402
from artifact_pipeline.analytical_solver import (  # noqa: E402
    get_card_removal_weight,
)
from artifact_pipeline.pegging import DEALER, PONE, ROLES  # noqa: E402

SUITS = 4
RANKS = 13
DEALT = 6
KEPT = 4
POPULATION_METHOD = "artifact_pipeline.cfr_prior.population.v1"
PRIOR_METHOD = "artifact_pipeline.cfr_prior.mixture.v1"
# The production play-table workflow's settings for these stages: analytical
# initialization (40 and 2 iterations), then two outer heuristic refinements
# of 200 samples per hand, seed 42.
DEFAULT_CONFIGURATION = {
    "analytical_max_iterations": 40,
    "full_hand_policy_max_iterations": 2,
    "outer_iterations": 2,
    "policy_table_samples": 200,
    "seed": 42,
}
# The Rust solver's MASS_LIMIT (native/cfr/src/solve.rs): the largest prior
# mass its exact i128 certificate can carry, (2^125 - 1) // (128 * 1000^6).
SOLVER_MASS_LIMIT = 332_306_998_946_228_968
REQUIRED_POPULATION_KEYS = frozenset(
    ("keeps", "keeps_sha256", "discard_policy_fingerprint")
)

Row = tuple[str, tuple[int, ...], tuple[int, ...]]
Weighted = Iterable[tuple[tuple[int, ...], int]]


def rank_hands(size: int, ranks: int = RANKS) -> list[tuple[int, ...]]:
    """Every rank multiset of `size` cards that four suits can deal, sorted.

    For four cards and 13 ranks this is `get_canonical_hands()`, the
    solver's key order.
    """
    return [
        hand
        for hand in combinations_with_replacement(range(ranks), size)
        if max(Counter(hand).values()) <= SUITS
    ]


def physical_weight(hand: Sequence[int]) -> int:
    """Count the physical card sets a rank multiset stands for."""
    return get_card_removal_weight((), list(hand))


def keeps_digest(rows: Sequence[Sequence[Any]]) -> str:
    """Digest the keep rows as compact JSON, in their sorted order."""
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def keep_populations(rows: Iterable[Row]) -> dict[str, dict[str, int]]:
    """Physical six-card weight that each role's policy sends to each keep."""
    populations: dict[str, Counter[str]] = {role: Counter() for role in (PONE, DEALER)}
    for role, hand, keep in rows:
        populations[role][generator.canonical_hand_key(keep)] += physical_weight(hand)
    return {role: dict(sorted(value.items())) for role, value in populations.items()}


def population_document(
    configuration: Mapping[str, int],
    converged: bool,
    refinement: Mapping[str, Any],
    discard: generator.DiscardPolicy,
) -> dict[str, Any]:
    """Describe a discard policy as a timing-free population document."""
    keeps = sorted(discard.kept_by_role_and_hand.items())
    rows = [[role, list(hand), list(keep)] for (role, hand), keep in keeps]
    populations = keep_populations((role, hand, keep) for (role, hand), keep in keeps)
    return {
        "population_method": POPULATION_METHOD,
        "configuration": dict(configuration),
        "converged": converged,
        "refinement": refinement,
        "discard_policy_fingerprint": generator.discard_keeps_fingerprint(discard),
        "six_hand_physical_weight_per_role": {
            role: sum(value.values()) for role, value in populations.items()
        },
        "keep_populations": populations,
        "keeps": rows,
        "keeps_sha256": keeps_digest(rows),
    }


def build_population(configuration: Mapping[str, int] | None = None) -> dict[str, Any]:
    """Run the generator's analytical start and heuristic discard refinement.

    This is the path `generate_play_table` takes when an enforced promotion
    gate fails: refinement restarts from the analytical policy and plays the
    legacy heuristic in both seats.
    """
    if configuration is None:
        configuration = DEFAULT_CONFIGURATION
    context = generator.solve_initial_discard_policy(
        configuration["analytical_max_iterations"],
        configuration["full_hand_policy_max_iterations"],
    )
    args = argparse.Namespace(
        outer_iterations=configuration["outer_iterations"],
        policy_table_samples=configuration["policy_table_samples"],
        seed=configuration["seed"],
    )
    gate: dict[str, Any] = {"passed": False}
    fallback = generator.heuristic_fallback(
        gate, context, args, generator.get_canonical_hands()
    )
    assert fallback is not None
    _, refined, converged = fallback
    discard = generator.selected_discards_to_policy(refined.selected_discards)
    return population_document(
        configuration, converged, gate["discard_refinement"], discard
    )


def encode_population(document: Mapping[str, Any]) -> bytes:
    """Serialize a population document compactly and deterministically."""
    return (json.dumps(document, separators=(",", ":"), allow_nan=False) + "\n").encode(
        "utf-8"
    )


def validate_rows(rows: Sequence[Sequence[Any]], ranks: int = RANKS) -> list[Row]:
    """Require one valid keep for each role and each six-card hand that can be dealt."""
    parsed: list[Row] = []
    for role, hand, keep in rows:
        hand, keep = tuple(hand), tuple(keep)
        if role not in ROLES:
            raise ValueError(f"Unknown role {role!r}")
        if len(keep) != KEPT or list(keep) != sorted(keep):
            raise ValueError(f"Keep {keep} is not four sorted ranks")
        if Counter(keep) - Counter(hand):
            raise ValueError(f"Keep {keep} is not drawn from {hand}")
        parsed.append((role, hand, keep))
    expected = sorted(
        (role, hand) for role in ROLES for hand in rank_hands(DEALT, ranks)
    )
    if sorted((role, hand) for role, hand, _ in parsed) != expected:
        raise ValueError("Keeps must cover every six-card hand once per role")
    return parsed


def read_population(path: Path, ranks: int = RANKS) -> tuple[dict[str, Any], list[Row]]:
    """Load a population and check it is internally consistent and complete.

    These checks catch corruption and incomplete or inconsistent keeps; they
    cannot catch a deliberate edit that recomputes every digest.
    """
    document = json.loads(Path(path).read_bytes())
    missing = REQUIRED_POPULATION_KEYS - set(document)
    if missing:
        raise ValueError(f"Population lacks {sorted(missing)}")
    method = document.get("population_method", POPULATION_METHOD)
    if method != POPULATION_METHOD:
        raise ValueError(f"Unknown population method {method!r}")
    if keeps_digest(document["keeps"]) != document["keeps_sha256"]:
        raise ValueError("Keep population digest mismatch")
    rows = validate_rows(document["keeps"], ranks)
    discard = generator.DiscardPolicy({(role, hand): keep for role, hand, keep in rows})
    if (
        generator.discard_keeps_fingerprint(discard)
        != document["discard_policy_fingerprint"]
    ):
        raise ValueError("Keep policy fingerprint mismatch")
    if "keep_populations" in document and document[
        "keep_populations"
    ] != keep_populations(rows):
        raise ValueError("Keep populations do not match the keeps")
    dealt = math.comb(SUITS * ranks, DEALT)
    if "six_hand_physical_weight_per_role" in document and document[
        "six_hand_physical_weight_per_role"
    ] != {PONE: dealt, DEALER: dealt}:
        raise ValueError("Six-card physical weight totals are wrong")
    return document, rows


def _sub_multisets(hand: Sequence[int]):
    """Yield each sub-multiset t of `hand` as a key and (count, t_r) pairs.

    The key lists (rank, t_r) for the ranks t uses, so equal sub-multisets
    of two hands share a key. The pairs cover every rank in `hand`,
    including those t does not use (t_r = 0), whose factors still count.
    """
    counts = sorted(Counter(hand).items())
    for taken in product(*(range(count + 1) for _, count in counts)):
        key = tuple((rank, take) for (rank, _), take in zip(counts, taken) if take)
        yield key, [(count, take) for (_, count), take in zip(counts, taken)]


def joint_keep_matrix(pone: Weighted, dealer: Weighted, keep_count: int) -> bytes:
    """Sum physical deal pairs into a dense little-endian u64 keep matrix.

    `pone` and `dealer` list each role's dealt rank hands with the index of
    the hand it keeps. Cell `[i * keep_count + j]` counts the physical ways
    to deal Pone a hand that keeps key `i` and then Dealer, from the
    remaining cards, a hand that keeps key `j`. This is the same quantity
    the quantity a direct count over every pair of dealt hands would sum
    one pair at a time:

        weight(p) * prod_r C(4 - p_r, d_r)

    over all rank hands p (Pone) and d (Dealer), where `p_r` and `d_r` count
    rank r. Visiting all 18,395 x 18,395 pairs is too slow in Python, so
    each factor is expanded with the per-rank identity

        C(4 - p, d) = sum_t (-1)^t C(p, t) C(4 - t, d - t),  0 <= t <= min(p, d)

    (inclusion-exclusion over the `t` dealt Pone cards Dealer's selection
    would have shared). The product over ranks then becomes a sum over
    common sub-multisets t of p and d, which factors into a Pone part,
    depending only on p and t, and a Dealer part, depending only on t and
    d. Each Dealer part is packed into one integer with a 64-bit lane per
    keep, and Pone rows are integer combinations of those packed rows. All
    arithmetic is exact; the final lanes are the true non-negative counts,
    and the callers' mass checks would catch a lane that carried.
    """
    pone_parts = _expand(pone, _pone_coefficient)
    rows = [0] * keep_count
    for shared, columns in _expand(dealer, _dealer_coefficient).items():
        lanes = array("Q", bytes(8 * keep_count))
        for column, value in columns.items():
            lanes[column] = value
        packed = int.from_bytes(_little_endian(lanes), "little")
        for row, coefficient in pone_parts.get(shared, Counter()).items():
            rows[row] += coefficient * packed
    return b"".join(row.to_bytes(8 * keep_count, "little") for row in rows)


def _pone_coefficient(hand: Sequence[int], pairs: Sequence[tuple[int, int]]) -> int:
    """weight(p) * prod_r (-1)^t_r C(p_r, t_r) for one shared sub-multiset t."""
    sign = -1 if sum(t for _, t in pairs) % 2 else 1
    return sign * physical_weight(hand) * math.prod(math.comb(c, t) for c, t in pairs)


def _dealer_coefficient(_: Sequence[int], pairs: Sequence[tuple[int, int]]) -> int:
    """prod_r C(4 - t_r, d_r - t_r) for one shared sub-multiset t."""
    return math.prod(math.comb(SUITS - t, c - t) for c, t in pairs)


def _expand(hands: Weighted, coefficient) -> dict[tuple, Counter[int]]:
    """Sum each hand's coefficients by shared sub-multiset, then by keep."""
    parts: dict[tuple, Counter[int]] = {}
    for hand, keep in hands:
        for key, pairs in _sub_multisets(hand):
            parts.setdefault(key, Counter())[keep] += coefficient(hand, pairs)
    return parts


def _little_endian(values: array) -> bytes:
    """Return u64 lanes as little-endian bytes on any host."""
    if sys.byteorder != "little":  # pragma: no cover - CI and the M2 are little-endian
        values = array("Q", values)
        values.byteswap()
    return values.tobytes()


def read_matrix(data: bytes, keep_count: int) -> array:
    """Decode a dense little-endian u64 matrix, checking its size."""
    if len(data) != 8 * keep_count * keep_count:
        raise ValueError(f"Expected a {keep_count} x {keep_count} u64 matrix")
    values = array("Q", data)
    if sys.byteorder != "little":  # pragma: no cover - see _little_endian
        values.byteswap()
    return values


def uniform_matrix(ranks: int = RANKS) -> array:
    """Physical weights of uniformly dealt Pone and Dealer four-card hands."""
    hands = rank_hands(KEPT, ranks)
    keyed = [(hand, index) for index, hand in enumerate(hands)]
    values = read_matrix(joint_keep_matrix(keyed, keyed, len(hands)), len(hands))
    cards = SUITS * ranks
    if sum(values) != math.comb(cards, KEPT) * math.comb(cards - KEPT, KEPT):
        raise ValueError("Uniform prior does not exhaust physical four-card deals")
    return values


def production_matrix(rows: Sequence[Row], ranks: int = RANKS) -> array:
    """Physical twelve-card deal weights mapped through the frozen keeps.

    Checks the total against every physical deal and each role's marginal
    against that role's keep populations.
    """
    hands = rank_hands(KEPT, ranks)
    index = {hand: i for i, hand in enumerate(hands)}
    by_role = {
        role: [(hand, index[keep]) for row_role, hand, keep in rows if row_role == role]
        for role in ROLES
    }
    values = read_matrix(
        joint_keep_matrix(by_role[PONE], by_role[DEALER], len(hands)), len(hands)
    )
    cards = SUITS * ranks
    remaining = math.comb(cards - DEALT, DEALT)
    if sum(values) != math.comb(cards, DEALT) * remaining:
        raise ValueError("Production prior does not exhaust physical deals")
    count = len(hands)
    marginals = {
        PONE: [sum(values[i * count : (i + 1) * count]) for i in range(count)],
        DEALER: [sum(values[i::count]) for i in range(count)],
    }
    populations = keep_populations(rows)
    for role in ROLES:
        expected = [
            populations[role].get(generator.canonical_hand_key(hand), 0) * remaining
            for hand in hands
        ]
        if marginals[role] != expected:
            raise ValueError(f"{role} marginal does not match its keep population")
    return values


def mixture_weights(uniform: Sequence[int], production: Sequence[int]) -> array:
    """Combine two weightings as an exact equal-probability mixture.

    Each input is first normalized to probabilities, so the result is
    proportional to `uniform / sum(uniform) + production / sum(production)`.
    Scaling by the masses' greatest common divisor keeps the integers as
    small as exactness allows.
    """
    if len(uniform) != len(production) or min(uniform) < 0 or min(production) < 0:
        raise ValueError("Incompatible chance vectors")
    mass, total = sum(uniform), sum(production)
    if not mass or not total:
        raise ValueError("Empty chance prior")
    divisor = math.gcd(mass, total)
    return array(
        "Q",
        (
            u * (total // divisor) + p * (mass // divisor)
            for u, p in zip(uniform, production)
        ),
    )


def build_prior(
    rows: Sequence[Row], ranks: int = RANKS
) -> tuple[bytes, bytes, dict[str, Any]]:
    """Return the production matrix bytes, the prior bytes and a report."""
    uniform = uniform_matrix(ranks)
    production = production_matrix(rows, ranks)
    prior = mixture_weights(uniform, production)
    mixture_mass = sum(prior)
    if mixture_mass > SOLVER_MASS_LIMIT:
        raise ValueError(
            f"Prior mass {mixture_mass} exceeds the solver's limit {SOLVER_MASS_LIMIT}"
        )
    production_bytes, prior_bytes = _little_endian(production), _little_endian(prior)
    report = {
        "prior_method": PRIOR_METHOD,
        "uniform_mass": sum(uniform),
        "production_mass": sum(production),
        "mixture_mass": mixture_mass,
        "production_sha256": hashlib.sha256(production_bytes).hexdigest(),
        "prior_sha256": hashlib.sha256(prior_bytes).hexdigest(),
    }
    return production_bytes, prior_bytes, report


def write_bytes(path: Path, data: bytes) -> None:
    """Write a file whole, replacing any earlier one only once it is complete."""
    path = Path(path)
    partial = path.with_name(path.name + ".partial")
    partial.write_bytes(data)
    os.replace(partial, path)


def require_distinct(inputs: Sequence[Path], outputs: Sequence[Path]) -> None:
    """Refuse paths that would let one write replace another file in use.

    Covers each output's temporary `.partial` name, symbolic links and
    `..` (via the real path), names differing only in case, and hard links
    between files that already exist.
    """
    paths = [
        *map(Path, inputs),
        *map(Path, outputs),
        *(Path(o).with_name(Path(o).name + ".partial") for o in outputs),
    ]
    # Compare case-folded real paths, so names differing only in case clash
    # even where the volume is case-insensitive (the macOS default).
    real = [os.path.realpath(path).casefold() for path in paths]
    clash = len(set(real)) != len(real) or any(
        os.path.samefile(a, b)
        for a, b in combinations([p for p in paths if p.exists()], 2)
    )
    if clash:
        raise ValueError("Input and output paths must all be different files")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the population and prior subcommands."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    stages = parser.add_subparsers(dest="stage", required=True)
    population = stages.add_parser(
        "population", help="Refine discards and write the timing-free population"
    )
    population.add_argument("--output", type=Path, required=True)
    for name, default in DEFAULT_CONFIGURATION.items():
        population.add_argument(
            "--" + name.replace("_", "-"),
            type=int if name == "seed" else generator.positive_int,
            default=default,
        )
    prior = stages.add_parser("prior", help="Write the 50/50 mixture prior")
    prior.add_argument("--population", type=Path, required=True)
    prior.add_argument("--output", type=Path, required=True)
    prior.add_argument("--production-output", type=Path)
    prior.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Run one stage; neither samples beyond the seeded refinement nor publishes."""
    args = parse_args(argv)
    if args.stage == "population":
        configuration = {name: getattr(args, name) for name in DEFAULT_CONFIGURATION}
        document = build_population(configuration)
        write_bytes(args.output, encode_population(document))
        summary = {
            key: document[key]
            for key in ("discard_policy_fingerprint", "keeps_sha256", "converged")
        }
    else:
        outputs = [args.output, args.production_output, args.report]
        require_distinct(
            [args.population], [path for path in outputs if path is not None]
        )
        document, rows = read_population(args.population)
        production, prior, summary = build_prior(rows)
        summary["discard_policy_fingerprint"] = document["discard_policy_fingerprint"]
        summary["keeps_sha256"] = document["keeps_sha256"]
        write_bytes(args.output, prior)
        if args.production_output is not None:
            write_bytes(args.production_output, production)
        if args.report is not None:
            write_bytes(args.report, (json.dumps(summary, indent=2) + "\n").encode())
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
