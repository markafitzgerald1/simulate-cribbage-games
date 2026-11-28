"""Discard the way the cribbage-trainer app advises, from its published tables.

The app ranks each of the 15 keeps by E(hand) +/- E(crib) + E(deltaP):

- E(hand) is exact: the kept four scored with each of the 46 starters the
  player has not seen, averaged.
- E(crib) is the crib table's mean for the two discards, per starter rank,
  weighted by how many starters of that rank are unseen. Where the table
  splits a rank by the starter's suit (suited or Jack discards), each unseen
  starter takes the mean of its own suit relation. It is added for the
  dealer and subtracted for the pone.
- E(deltaP) is the play table's mean pegging margin for the kept ranks in
  that seat. Without a play table it is zero, as in the app before it had
  one.

The app breaks exact ties by rank and then suit. Here the seat's discard
stream picks uniformly among keeps whose values agree to 1e-9, so no suit
is favoured; a tie can only matter between keeps the tables cannot tell
apart.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import itertools
import math
import random

from artifact_pipeline.adapter import (
    cached_pairs_runs_and_fifteens_points,
    get_canonical_pairs,
    insert_sorted,
)
from artifact_pipeline.ladder_game import PhysicalCard, Split
from artifact_pipeline.pegging import (
    DEALER,
    ROLES,
    canonical_hand_key,
    get_canonical_hands,
)

RANK_LABELS = "A23456789TJQK"
JACK = 10
TIE_TOLERANCE = 1e-9
# Published means carry four decimals, so a margin and its two rounded totals
# disagree by at most 1.5e-4; the app allows 0.001. Rounding never reverses
# the order of two totals, so a margin of the other sign is refused outright.
PLAY_TOLERANCE = 2e-4
MATCHING_DISCARD = "matching_discard_suit"
NON_MATCHING = "non_matching_discard_suit"
MATCHING_RANK_1 = "matching_rank_1_suit"
MATCHING_RANK_2 = "matching_rank_2_suit"

CribCell = tuple[float, Mapping[str, float]]


def discard_key(first: PhysicalCard, second: PhysicalCard) -> str:
    """Return the crib table's key for two discards, lower rank first."""
    low, high = sorted((first, second))
    # Two cards of one suit always differ in rank, so a pair is never suited.
    group = "Suited" if low[1] == high[1] else "Unsuited"
    return f"{RANK_LABELS[low[0]]}_{RANK_LABELS[high[0]]}_{group}"


def starter_relation(
    first: PhysicalCard, second: PhysicalCard, starter_suit: int
) -> str:
    """Name how a starter's suit relates to two discards, as the app does."""
    low, high = sorted((first, second))
    if low[0] == high[0] or low[1] == high[1]:
        matches = starter_suit in (low[1], high[1])
        return MATCHING_DISCARD if matches else NON_MATCHING
    if starter_suit == low[1]:
        return MATCHING_RANK_1
    if starter_suit == high[1]:
        return MATCHING_RANK_2
    return NON_MATCHING


def _mean(entry: object, where: str) -> float:
    value = entry.get("mu") if isinstance(entry, Mapping) else None
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise ValueError(f"table has no finite mean at {where}")
    return float(value)


def _client_keeps_relations(pair: str) -> bool:
    low, high, group = pair.split("_")
    return group == "Suited" or "J" in (low, high)


def load_crib_table(
    table: Mapping[str, object],
) -> dict[tuple[str, str], tuple[CribCell, ...]]:
    """Read every discard pair, seat and starter rank of a crib table."""
    cells: dict[tuple[str, str], tuple[CribCell, ...]] = {}
    for pair in get_canonical_pairs():
        for role in ROLES:
            seat = table.get(pair, {})
            ranks = seat.get(role, {}) if isinstance(seat, Mapping) else {}
            row = []
            for label in RANK_LABELS:
                where = f"{pair} {role} {label}"
                cell = ranks.get(label) if isinstance(ranks, Mapping) else None
                relations = (
                    cell.get("starter_suit_relation", {})
                    if isinstance(cell, Mapping)
                    else {}
                )
                if relations and not _client_keeps_relations(pair):
                    # The full artifact splits every cell by suit; the app
                    # reads the client file, which keeps only these splits.
                    raise ValueError(f"not a client crib table: {where} splits")
                row.append(
                    (
                        _mean(cell, where),
                        {
                            name: _mean(value, f"{where} {name}")
                            for name, value in relations.items()
                        },
                    )
                )
            cells[(pair, role)] = tuple(row)
    return cells


def load_play_table(
    table: Mapping[str, object],
) -> dict[tuple[str, tuple[int, ...]], float]:
    """Read every keep's pegging margin, checked against its player totals."""
    margins: dict[tuple[str, tuple[int, ...]], float] = {}
    for hand in get_canonical_hands():
        key = canonical_hand_key(hand)
        for role in ROLES:
            seat = table.get(key, {})
            entry = seat.get(role) if isinstance(seat, Mapping) else None
            margin = _mean(entry, f"{key} {role}")
            players = entry.get("players", {}) if isinstance(entry, Mapping) else {}
            own = _mean(players.get(role), f"{key} {role} players")
            other = _mean(
                players.get(ROLES[1 - ROLES.index(role)]), f"{key} {role} players"
            )
            if abs(own - other - margin) > PLAY_TOLERANCE or (own - other) * margin < 0:
                raise ValueError(f"play margin disagrees with totals at {key} {role}")
            margins[(role, hand)] = margin
    return margins


class TableDiscardRule:  # pylint: disable=too-few-public-methods
    """Keep the four cards the app's hand, crib and play values rank first."""

    def __init__(
        self,
        crib: Mapping[tuple[str, str], tuple[CribCell, ...]] | None = None,
        play: Mapping[tuple[str, tuple[int, ...]], float] | None = None,
    ) -> None:
        self._crib = crib
        self._play = play

    def keep_value(
        self, role: str, kept: Sequence[PhysicalCard], dealt: Sequence[PhysicalCard]
    ) -> float:
        """Return E(hand) +/- E(crib) + E(deltaP) for one keep."""
        discards = [card for card in dealt if card not in kept]
        held = [[suit for rank, suit in dealt if rank == r] for r in range(13)]
        ranks = tuple(sorted(rank for rank, _suit in kept))
        suits = {suit for _rank, suit in kept}
        hand = 0.0
        crib = 0.0
        for rank in range(13):
            unseen = [suit for suit in range(4) if suit not in held[rank]]
            hand += len(unseen) * cached_pairs_runs_and_fifteens_points(
                insert_sorted(ranks, rank)
            )
            for suit in unseen:
                if len(suits) == 1:
                    hand += 5 if suit in suits else 4
                hand += (JACK, suit) in kept
            if self._crib is not None:
                crib += self._crib_points(role, discards, rank, unseen)
        value = (hand + (crib if role == DEALER else -crib)) / 46
        if self._play is not None:
            value += self._play[(role, ranks)]
        return value

    def _crib_points(
        self,
        role: str,
        discards: Sequence[PhysicalCard],
        rank: int,
        unseen: Sequence[int],
    ) -> float:
        assert self._crib is not None
        mean, relations = self._crib[(discard_key(*discards), role)][rank]
        if not relations:
            return mean * len(unseen)
        points = 0.0
        for suit in unseen:
            relation = starter_relation(discards[0], discards[1], suit)
            if relation not in relations:
                raise ValueError(f"crib table has no {relation} cell")
            points += relations[relation]
        return points

    def select_discard(
        self, role: str, dealt: Sequence[PhysicalCard], rng: random.Random
    ) -> Split:
        """Return the best keep, drawing among exact ties."""
        cards = sorted(dealt)
        scored = [
            (self.keep_value(role, kept, cards), kept)
            for kept in itertools.combinations(cards, 4)
        ]
        best = max(value for value, _kept in scored)
        kept = rng.choice(
            [keep for value, keep in scored if value >= best - TIE_TOLERANCE]
        )
        return kept, tuple(card for card in cards if card not in kept)
