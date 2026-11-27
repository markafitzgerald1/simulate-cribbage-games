"""Paired, seat-swapped matches between strength-ladder players (#263).

A match plays deal pairs. Each pair is two games on one seed with the seats
swapped, so both players hold the same cards in the same seat over the hands
both games reach. Pairs are independent, so the standard error comes from the
spread of the per-pair results: treating the two games of a pair as
independent would misstate it, because they share the cards.

Every match in a ladder uses the same pair seeds, so cells of the cross table
are measured on common deals.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
import math
import multiprocessing
from typing import Any, Sequence

from artifact_pipeline.ladder_game import (
    TARGET_SCORE,
    GameOutcome,
    LadderPlayer,
    play_game,
)
from artifact_pipeline.pegging import _stable_seed

# Players can hold memory-mapped policy files that cannot be pickled, so
# workers are forked and read the match from here.
_FORKED_MATCH: dict[str, Any] = {}


@dataclass(frozen=True)
class IntegerMoments:
    """Exact sums of integer observations equal to `scale` times the value."""

    scale: int
    n: int = 0
    total: int = 0
    total_sq: int = 0

    def add(self, scaled_value: int) -> "IntegerMoments":
        """Return these moments with one more observation."""
        return replace(
            self,
            n=self.n + 1,
            total=self.total + scaled_value,
            total_sq=self.total_sq + scaled_value * scaled_value,
        )

    def merge(self, other: "IntegerMoments") -> "IntegerMoments":
        """Return the moments of both samples together."""
        if self.scale != other.scale:
            raise ValueError("Cannot merge moments with different scales")
        return replace(
            self,
            n=self.n + other.n,
            total=self.total + other.total,
            total_sq=self.total_sq + other.total_sq,
        )

    def affine(self, offset: int, sign: int) -> "IntegerMoments":
        """Return the moments of offset + sign * x for every scaled value x."""
        return replace(
            self,
            total=self.n * offset + sign * self.total,
            total_sq=self.n * offset * offset
            + 2 * offset * sign * self.total
            + self.total_sq,
        )

    def summary(self) -> dict[str, int | float | None]:
        """Return n, the mean and its standard error; None where undefined."""
        if self.n == 0:
            return {"n": 0, "mu": None, "se": None}
        mean = self.total / (self.n * self.scale)
        if self.n == 1:
            return {"n": 1, "mu": mean, "se": None}
        spread = self.n * self.total_sq - self.total * self.total
        variance = spread / (self.n * (self.n - 1) * self.scale * self.scale)
        return {"n": self.n, "mu": mean, "se": math.sqrt(variance / self.n)}


def elo_difference(
    win_rate: float | None, standard_error: float | None
) -> tuple[float | None, float | None]:
    """Convert a win rate and its standard error to Elo, by the delta method."""
    if win_rate is None or standard_error is None or not 0.0 < win_rate < 1.0:
        return None, None
    elo = 400.0 * math.log10(win_rate / (1.0 - win_rate))
    elo_se = 400.0 / math.log(10.0) * standard_error / (win_rate * (1.0 - win_rate))
    return elo, elo_se


def _empty_moments() -> dict[str, IntegerMoments]:
    # Scale 2 keeps each pair's average of its two games an integer.
    return {
        "win_rate": IntegerMoments(2),
        "won_as_first_pone": IntegerMoments(1),
        "won_as_first_dealer": IntegerMoments(1),
        "point_margin": IntegerMoments(2),
        "pegging_margin": IntegerMoments(2),
        "hands_per_game": IntegerMoments(2),
    }


@dataclass
class MatchAccumulator:
    """Per-pair results for player A against player B."""

    both_won: int = 0
    split: int = 0
    both_lost: int = 0
    moments: dict[str, IntegerMoments] = field(default_factory=_empty_moments)
    # Decision categories from policies that count their own calls (the CFR
    # policy counts heuristic fallbacks), keyed by the players using them.
    policy_decisions: dict[str, Counter[str]] = field(default_factory=dict)

    def add_pair(self, a_first_pone: GameOutcome, a_first_dealer: GameOutcome) -> None:
        """Record the two games of one deal pair, from A's side."""
        won_as_pone = int(a_first_pone.first_pone_won)
        won_as_dealer = int(not a_first_dealer.first_pone_won)
        wins = won_as_pone + won_as_dealer
        if wins == 2:
            self.both_won += 1
        elif wins == 1:
            self.split += 1
        else:
            self.both_lost += 1
        observations = {
            "win_rate": wins,
            "won_as_first_pone": won_as_pone,
            "won_as_first_dealer": won_as_dealer,
            "point_margin": a_first_pone.first_pone_score
            - a_first_pone.first_dealer_score
            + a_first_dealer.first_dealer_score
            - a_first_dealer.first_pone_score,
            "pegging_margin": a_first_pone.first_pone_pegging
            - a_first_pone.first_dealer_pegging
            + a_first_dealer.first_dealer_pegging
            - a_first_dealer.first_pone_pegging,
            "hands_per_game": a_first_pone.hands_played + a_first_dealer.hands_played,
        }
        for key, value in observations.items():
            self.moments[key] = self.moments[key].add(value)

    def merge(self, other: "MatchAccumulator") -> None:
        """Add another accumulator's pairs to this one."""
        self.both_won += other.both_won
        self.split += other.split
        self.both_lost += other.both_lost
        for key, moments in other.moments.items():
            self.moments[key] = self.moments[key].merge(moments)
        for label, counts in other.policy_decisions.items():
            self.policy_decisions.setdefault(label, Counter()).update(counts)

    def inverted(self) -> "MatchAccumulator":
        """Return the same pairs from B's side, exactly."""
        moments = self.moments
        return MatchAccumulator(
            both_won=self.both_lost,
            split=self.split,
            both_lost=self.both_won,
            moments={
                "win_rate": moments["win_rate"].affine(2, -1),
                "won_as_first_pone": moments["won_as_first_dealer"].affine(1, -1),
                "won_as_first_dealer": moments["won_as_first_pone"].affine(1, -1),
                "point_margin": moments["point_margin"].affine(0, -1),
                "pegging_margin": moments["pegging_margin"].affine(0, -1),
                "hands_per_game": moments["hands_per_game"],
            },
            policy_decisions={
                label: Counter(counts)
                for label, counts in self.policy_decisions.items()
            },
        )

    def summary(self) -> dict[str, Any]:
        """Return counts, each statistic's n, mean and SE, and the Elo gap."""
        pairs = self.both_won + self.split + self.both_lost
        win = self.moments["win_rate"].summary()
        elo, elo_se = elo_difference(win["mu"], win["se"])
        independent_se = (
            None
            if win["mu"] is None
            else math.sqrt(win["mu"] * (1.0 - win["mu"]) / (2 * pairs))
        )
        return {
            "pairs": pairs,
            "games": 2 * pairs,
            "pair_outcomes": {
                "both_won": self.both_won,
                "split": self.split,
                "both_lost": self.both_lost,
            },
            **{key: moments.summary() for key, moments in self.moments.items()},
            "elo": elo,
            "elo_se": elo_se,
            "win_rate_se_if_games_were_independent": independent_se,
            "policy_decisions": {
                label: dict(sorted(counts.items()))
                for label, counts in sorted(self.policy_decisions.items())
            },
        }


def pair_seed(seed: int, pair_index: int) -> int:
    """Return the game seed both games of one deal pair are played on."""
    return _stable_seed(seed, "ladder-pair", pair_index)


def _counting_policies(players: Sequence[LadderPlayer]) -> dict[str, Any]:
    """Return each policy that counts its decisions, labelled by its players."""
    users: dict[int, tuple[Any, list[str]]] = {}
    for player in players:
        policy = player.pegging_policy
        if hasattr(policy, "decision_counts"):
            users.setdefault(id(policy), (policy, []))[1].append(player.name)
    return {"+".join(sorted(set(names))): policy for policy, names in users.values()}


def play_pairs(
    player_a: LadderPlayer,
    player_b: LadderPlayer,
    pair_range: range,
    seed: int,
    target_score: int = TARGET_SCORE,
) -> MatchAccumulator:
    """Play the given deal pairs serially.

    Resets the decision counters of counting policies first, so the
    counts cover these pairs only, in a worker or in the calling process.
    """
    counting = _counting_policies((player_a, player_b))
    for policy in counting.values():
        policy.reset_counts()
    accumulator = MatchAccumulator()
    for pair_index in pair_range:
        game_seed = pair_seed(seed, pair_index)
        accumulator.add_pair(
            play_game(player_a, player_b, game_seed, target_score),
            play_game(player_b, player_a, game_seed, target_score),
        )
    accumulator.policy_decisions = {
        label: Counter(policy.decision_counts()) for label, policy in counting.items()
    }
    return accumulator


def _play_forked_chunk(pair_range: range) -> MatchAccumulator:
    return play_pairs(pair_range=pair_range, **_FORKED_MATCH)


def chunk_ranges(pairs: int, chunks: int) -> list[range]:
    """Split range(pairs) into at most `chunks` contiguous, near-equal ranges."""
    count = min(pairs, chunks)
    base, extra = divmod(pairs, count)
    ranges, start = [], 0
    for index in range(count):
        stop = start + base + (1 if index < extra else 0)
        ranges.append(range(start, stop))
        start = stop
    return ranges


def run_match(  # pylint: disable=too-many-arguments
    player_a: LadderPlayer,
    player_b: LadderPlayer,
    pairs: int,
    seed: int,
    *,
    workers: int = 1,
    target_score: int = TARGET_SCORE,
) -> MatchAccumulator:
    """Play `pairs` deal pairs, optionally split across forked workers.

    The result does not depend on the number of workers: every pair is
    seeded by its index, and integer sums merge exactly in any grouping.
    """
    if pairs < 1 or workers < 1:
        raise ValueError("A match needs at least one deal pair and one worker")
    if workers == 1:
        return play_pairs(player_a, player_b, range(pairs), seed, target_score)
    _FORKED_MATCH.update(
        player_a=player_a, player_b=player_b, seed=seed, target_score=target_score
    )
    try:
        context = multiprocessing.get_context("fork")
        with context.Pool(processes=workers) as pool:
            partials = pool.map(_play_forked_chunk, chunk_ranges(pairs, workers * 4))
    finally:
        _FORKED_MATCH.clear()
    total = MatchAccumulator()
    for partial in partials:
        total.merge(partial)
    return total


def run_ladder(  # pylint: disable=too-many-arguments
    players: Sequence[LadderPlayer],
    pairs: int,
    seed: int,
    *,
    cross_table: bool = False,
    workers: int = 1,
    target_score: int = TARGET_SCORE,
) -> dict[tuple[str, str], MatchAccumulator]:
    """Play each rung against the one below it, or every pair of rungs.

    Players are ordered from the bottom rung up. The result holds both
    orientations of every match played, keyed (player, opponent).
    """
    names = [player.name for player in players]
    if len(players) < 2 or len(set(names)) != len(names):
        raise ValueError("A ladder needs at least two players with unique names")
    results: dict[tuple[str, str], MatchAccumulator] = {}
    for low, below in enumerate(players):
        for above in players[low + 1 :] if cross_table else players[low + 1 : low + 2]:
            match = run_match(
                above, below, pairs, seed, workers=workers, target_score=target_score
            )
            results[(above.name, below.name)] = match
            results[(below.name, above.name)] = match.inverted()
    return results
