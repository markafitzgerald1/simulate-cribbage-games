"""Tests for discards chosen from the app's crib and play tables (#263)."""

from __future__ import annotations

from collections import Counter, namedtuple
import itertools
import random
import unittest
from unittest.mock import patch

from artifact_pipeline.adapter import get_canonical_pairs
from artifact_pipeline.generate_play_table import PHYSICAL_DECK
from artifact_pipeline.generate_table import starter_suit_relation
from artifact_pipeline.ladder_game import score_cards
from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    ROLES,
    canonical_hand_key,
    get_canonical_hands,
)
from artifact_pipeline.table_discards import (
    HandScoring,
    RANK_LABELS,
    TableDiscardRule,
    load_crib_table,
    load_play_table,
)

Starter = namedtuple("Starter", "suit")
RELATIONS = {
    "Suited": ("matching_discard_suit", "non_matching_discard_suit"),
    "Pair": ("matching_discard_suit", "non_matching_discard_suit"),
    "Unsuited": (
        "matching_rank_1_suit",
        "matching_rank_2_suit",
        "non_matching_discard_suit",
    ),
}


def pair_kind(pair):
    low, high, group = pair.split("_")
    return "Pair" if low == high else group


def crib_json(seed=1):
    """A complete crib table; suited and Jack cells split by suit relation."""
    rng = random.Random(seed)
    table = {}
    for pair in get_canonical_pairs():
        table[pair] = {}
        for role in ROLES:
            cells = {}
            for label in RANK_LABELS:
                cell = {"mu": rng.uniform(3, 9)}
                if pair_kind(pair) == "Suited" or "J" in pair.split("_")[:2]:
                    cell["starter_suit_relation"] = {
                        name: {"mu": rng.uniform(3, 9)}
                        for name in RELATIONS[pair_kind(pair)]
                    }
                cells[label] = cell
            table[pair][role] = cells
    return table


def play_json(seed=2):
    rng = random.Random(seed)
    table = {}
    for hand in get_canonical_hands():
        totals = {role: rng.uniform(1, 4) for role in ROLES}
        table[canonical_hand_key(hand)] = {
            role: {
                "mu": totals[role] - totals[ROLES[1 - ROLES.index(role)]],
                "players": {name: {"mu": value} for name, value in totals.items()},
            }
            for role in ROLES
        }
    return table


def unseen(dealt):
    return [card for card in PHYSICAL_DECK if card not in dealt]


def oracle_hand(kept, dealt):
    starters = unseen(dealt)
    return sum(score_cards(kept, starter, False) for starter in starters) / len(
        starters
    )


def oracle_crib(table, role, discards, dealt):
    """Look up each physical starter through the producer's suit relation."""
    low, high = sorted(discards)
    pair = (
        f"{RANK_LABELS[low[0]]}_{RANK_LABELS[high[0]]}_"
        f"{'Suited' if low[0] != high[0] and low[1] == high[1] else 'Unsuited'}"
    )
    canonical = {low[1]: 0}
    canonical.setdefault(high[1], 1)
    total = 0.0
    for rank, suit in unseen(dealt):
        cell = table[pair][role][RANK_LABELS[rank]]
        relations = cell.get("starter_suit_relation")
        if relations:
            relation = starter_suit_relation(pair, Starter(canonical.get(suit, 2)))
            total += relations[relation]["mu"]
        else:
            total += cell["mu"]
    return total / 46


def deals(count, seed):
    rng = random.Random(seed)
    crafted = [
        [(4, 2), (5, 2), (6, 2), (10, 2), (10, 0), (0, 1)],  # flush and nobs
        [(10, 1), (10, 3), (4, 0), (4, 1), (9, 2), (12, 3)],  # Jack pair
        [(0, 0), (1, 0), (2, 1), (3, 1), (10, 0), (11, 2)],  # suited, Jack
    ]
    return crafted + [sorted(rng.sample(PHYSICAL_DECK, 6)) for _ in range(count)]


class TestKeepValue(unittest.TestCase):
    def test_pre_cut_scores_four_cards_with_optional_flush(self):
        # 5-6-7-8 scores a four-card run and one fifteen (7+8).
        flush = [(4, 2), (5, 2), (6, 2), (7, 2)]
        mixed = [*flush[:3], (7, 0)]
        for kept, rank_points, suit_points in (
            (flush, 6, 10),
            (mixed, 6, 6),
            ([(4, 0), (4, 1), (4, 2), (10, 2)], 14, 14),
        ):
            dealt = [*kept, (0, 0), (12, 0)]
            for mode, expected in (
                (HandScoring.PRE_CUT_RANK, rank_points),
                (HandScoring.PRE_CUT_SUIT, suit_points),
            ):
                rule = TableDiscardRule(hand_scoring=mode)
                for role in ROLES:
                    self.assertEqual(rule.keep_value(role, kept, dealt), expected)

    def test_post_cut_48_scores_each_physical_card_outside_the_keep(self):
        rule = TableDiscardRule(hand_scoring=HandScoring.POST_CUT_48)
        for dealt in deals(8, 48):
            for kept in itertools.combinations(sorted(dealt), 4):
                self.assertAlmostEqual(
                    rule.keep_value(PONE, kept, dealt),
                    oracle_hand(kept, kept),
                    places=12,
                )

    def test_alternate_hand_models_require_hand_only_discards(self):
        for mode in (HandScoring.PRE_CUT_RANK, HandScoring.POST_CUT_48):
            for tables in ({"crib": {}}, {"play": {}}):
                with self.assertRaisesRegex(ValueError, "hand-only"):
                    TableDiscardRule(hand_scoring=mode, **tables)

    def test_hand_value_is_the_mean_over_the_46_unseen_starters(self):
        rule = TableDiscardRule()
        for dealt in deals(60, 3):
            for kept in itertools.combinations(sorted(dealt), 4):
                for role in ROLES:
                    self.assertAlmostEqual(
                        rule.keep_value(role, kept, dealt),
                        oracle_hand(kept, dealt),
                        places=12,
                    )

    def test_crib_value_follows_each_starters_suit_relation(self):
        table = crib_json()
        rule = TableDiscardRule(crib=load_crib_table(table))
        hand_only = TableDiscardRule()
        for dealt in deals(60, 4):
            for kept in itertools.combinations(sorted(dealt), 4):
                discards = [card for card in dealt if card not in kept]
                for role, sign in ((DEALER, 1), (PONE, -1)):
                    crib = rule.keep_value(role, kept, dealt) - hand_only.keep_value(
                        role, kept, dealt
                    )
                    self.assertAlmostEqual(
                        crib,
                        sign * oracle_crib(table, role, discards, dealt),
                        places=12,
                    )

    def test_play_value_is_the_seats_margin_for_the_kept_ranks(self):
        table = play_json()
        rule = TableDiscardRule(play=load_play_table(table))
        hand_only = TableDiscardRule()
        for dealt in deals(20, 5):
            for kept in itertools.combinations(sorted(dealt), 4):
                key = canonical_hand_key(tuple(sorted(rank for rank, _ in kept)))
                for role in ROLES:
                    self.assertAlmostEqual(
                        rule.keep_value(role, kept, dealt)
                        - hand_only.keep_value(role, kept, dealt),
                        table[key][role]["mu"],
                        places=12,
                    )


class TestSelectDiscard(unittest.TestCase):
    def test_keeps_the_best_of_the_fifteen(self):
        crib = crib_json()
        rule = TableDiscardRule(load_crib_table(crib), load_play_table(play_json()))
        for dealt in deals(40, 6):
            for role in ROLES:
                values = {
                    kept: rule.keep_value(role, kept, dealt)
                    for kept in itertools.combinations(sorted(dealt), 4)
                }
                kept, discarded = rule.select_discard(
                    role, list(reversed(dealt)), random.Random(0)
                )
                self.assertEqual(values[kept], max(values.values()))
                self.assertEqual(sorted(kept + discarded), sorted(dealt))

    def test_draws_uniformly_among_exact_ties(self):
        rule = TableDiscardRule()
        # Hand value alone cannot tell the Ten of clubs from the Ten of
        # diamonds: A-A-4-T keeps either, and no other keep comes close.
        dealt = [(0, 2), (0, 3), (3, 2), (6, 1), (9, 0), (9, 1)]
        values = sorted(
            rule.keep_value(DEALER, kept, dealt)
            for kept in itertools.combinations(sorted(dealt), 4)
        )
        self.assertEqual(values[-1], values[-2])
        self.assertLess(values[-3], values[-1] - 0.5)
        tens = Counter(
            next(
                card
                for card in rule.select_discard(DEALER, dealt, random.Random(seed))[0]
                if card[0] == 9
            )
            for seed in range(400)
        )
        # Each Ten is kept about half the time (200 expected, sd 10).
        self.assertEqual(set(tens), {(9, 0), (9, 1)})
        self.assertTrue(all(150 < count < 250 for count in tens.values()), tens)


class TestNearTies(unittest.TestCase):
    def test_values_within_the_tolerance_tie_and_beyond_it_do_not(self):
        dealt = [(0, 2), (0, 3), (3, 2), (6, 1), (9, 0), (9, 1)]

        def favoured(kept):
            return (9, 1) in kept and (9, 0) not in kept

        for gap, only_favoured in ((5e-10, False), (2e-9, True)):

            def value(_self, _role, kept, _dealt, gap=gap):
                return gap if favoured(kept) else 0.0

            with patch.object(TableDiscardRule, "keep_value", value):
                chosen = [
                    favoured(
                        TableDiscardRule().select_discard(
                            PONE, dealt, random.Random(seed)
                        )[0]
                    )
                    for seed in range(60)
                ]
            # Four of the 15 keeps are favoured, so a 15-way tie picks one of
            # the other eleven in all but about 0.27**60 of seed sets.
            self.assertEqual(all(chosen), only_favoured, gap)


class TestLoading(unittest.TestCase):
    def test_rejects_missing_or_non_numeric_means(self):
        table = crib_json()
        del table["A_2_Suited"][PONE]["7"]
        with self.assertRaisesRegex(ValueError, "A_2_Suited Pone 7"):
            load_crib_table(table)
        table = crib_json()
        table["5_J_Unsuited"][DEALER]["K"]["starter_suit_relation"][
            "matching_rank_2_suit"
        ] = {"mu": "high"}
        with self.assertRaisesRegex(ValueError, "matching_rank_2_suit"):
            load_crib_table(table)
        table = play_json()
        table["A_2_3_4"][DEALER]["players"].pop(PONE)
        with self.assertRaisesRegex(ValueError, "A_2_3_4 Dealer players"):
            load_play_table(table)

    def test_rejects_a_play_margin_that_disagrees_with_its_totals(self):
        table = play_json()
        table["5_5_T_J"][PONE]["mu"] += 0.0003
        with self.assertRaisesRegex(ValueError, "5_5_T_J Pone"):
            load_play_table(table)
        table["5_5_T_J"][PONE]["mu"] -= 0.00015
        self.assertEqual(len(load_play_table(table)), 2 * 1820)
        # A margin of the wrong sign is refused however small it is.
        players = table["2_3_4_Q"][DEALER]["players"]
        players[DEALER]["mu"], players[PONE]["mu"] = 1.0001, 1.0
        for margin, accepted in ((0.0001, True), (0.0, True), (-0.0001, False)):
            table["2_3_4_Q"][DEALER]["mu"] = margin
            if accepted:
                self.assertEqual(len(load_play_table(table)), 2 * 1820)
            else:
                with self.assertRaisesRegex(ValueError, "2_3_4_Q Dealer"):
                    load_play_table(table)

    def test_rejects_non_finite_or_boolean_means(self):
        for bad in (float("nan"), float("inf"), True):
            table = play_json()
            table["A_2_3_4"][PONE]["mu"] = bad
            with self.assertRaisesRegex(ValueError, "finite mean at A_2_3_4 Pone"):
                load_play_table(table)

    def test_rejects_the_full_crib_artifact(self):
        table = crib_json()
        table["A_2_Unsuited"][DEALER]["K"]["starter_suit_relation"] = {
            name: {"mu": 5.0} for name in RELATIONS["Unsuited"]
        }
        with self.assertRaisesRegex(ValueError, "A_2_Unsuited Dealer K splits"):
            load_crib_table(table)

    def test_refuses_a_crib_cell_without_the_starters_relation(self):
        table = crib_json()
        del table["5_J_Unsuited"][DEALER]["K"]["starter_suit_relation"][
            "matching_rank_1_suit"
        ]
        rule = TableDiscardRule(crib=load_crib_table(table))
        dealt = [(4, 0), (10, 1), (0, 2), (1, 2), (2, 3), (3, 3)]
        kept = [(0, 2), (1, 2), (2, 3), (3, 3)]
        with self.assertRaisesRegex(ValueError, "matching_rank_1_suit"):
            rule.keep_value(DEALER, kept, dealt)


if __name__ == "__main__":
    unittest.main()
