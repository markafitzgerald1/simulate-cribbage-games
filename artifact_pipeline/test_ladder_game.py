"""Tests for one full strength-ladder game (issue #263)."""

from __future__ import annotations

from collections import Counter
import hashlib
import random
import unittest
from unittest.mock import patch

from artifact_pipeline.generate_play_table import PHYSICAL_DECK
from artifact_pipeline.ladder_game import (
    HEELS_POINTS,
    JACK_RANK,
    LadderPlayer,
    RandomDiscardRule,
    RandomPeggingPolicy,
    _pegging_streams,
    checked_split,
    deal_hand,
    play_game,
    play_pegging_to_target,
    score_cards,
)
from artifact_pipeline.pegging import (
    DEALER,
    PONE,
    ROLES,
    LegacyHeuristicPolicy,
    PolicyView,
    simulate_pegging,
)

ZERO = {PONE: 0, DEALER: 0}


class LowestRank:  # pylint: disable=too-few-public-methods
    """Play the lowest legal rank, so a test can trace every play by hand."""

    def __init__(self) -> None:
        self.calls = 0

    def select_rank(self, view: PolicyView, rng: random.Random) -> int:
        del rng
        self.calls += 1
        return view.legal_ranks[0]


class Scripted:  # pylint: disable=too-few-public-methods
    """Play a fixed sequence of ranks."""

    def __init__(self, ranks) -> None:
        self.ranks = list(ranks)

    def select_rank(self, view: PolicyView, rng: random.Random) -> int:
        del view, rng
        return self.ranks.pop(0)


class NoPegging:  # pylint: disable=too-few-public-methods
    """Fail if asked to play: the game should already be over."""

    def select_rank(self, view: PolicyView, rng: random.Random) -> int:
        raise AssertionError(f"pegging after the game ended: {view}")


class ViewHashPolicy:  # pylint: disable=too-few-public-methods
    """Pick a legal rank from a hash of the view and record every view seen.

    The choice depends on the view alone, so two engines with identical
    rules make identical choices whatever random streams they pass in.
    """

    def __init__(self) -> None:
        self.views: list[PolicyView] = []

    def select_rank(self, view: PolicyView, rng: random.Random) -> int:
        del rng
        self.views.append(view)
        digest = hashlib.sha256(view.key().encode("utf-8")).digest()
        return view.legal_ranks[digest[0] % len(view.legal_ranks)]


class FirstFour:  # pylint: disable=too-few-public-methods
    """Keep the first four dealt cards."""

    def select_discard(self, role, dealt, rng):
        del role, rng
        return tuple(dealt[:4]), tuple(dealt[4:])


class RecordingRandomDiscard(
    RandomDiscardRule
):  # pylint: disable=too-few-public-methods
    """Random discards that record each (role, dealt, split) they produce."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def select_discard(self, role, dealt, rng):
        split = super().select_discard(role, dealt, rng)
        self.calls.append((role, tuple(dealt), split))
        return split


class Recorder:
    """A player that logs the role and first random draw of each call."""

    def __init__(self) -> None:
        self.log: list[tuple[str, str, float]] = []

    def select_discard(self, role, dealt, rng):
        self.log.append(("discard", role, rng.random()))
        return tuple(dealt[:4]), tuple(dealt[4:])

    def select_rank(self, view, rng):
        self.log.append(("peg", view.role, rng.random()))
        return view.legal_ranks[0]

    def by_hand(self):
        """Return [role, discard draw, [(pegging role, draw), ...]] per hand."""
        hands: list[list] = []
        for kind, role, draw in self.log:
            if kind == "discard":
                hands.append([role, draw, []])
            else:
                hands[-1][2].append((role, draw))
        return hands


class DrawsExtra(Recorder):
    """Plays like Recorder but consumes extra draws from its own streams."""

    def select_rank(self, view, rng):
        rng.random()
        rng.random()
        return super().select_rank(view, rng)


def recorded(name: str, recorder: Recorder) -> LadderPlayer:
    return LadderPlayer(name, recorder, recorder)


def peg(pone, dealer, scores_before, policies=None, target=121):
    """Peg with both seats playing their lowest legal rank by default."""
    return play_pegging_to_target(
        {PONE: pone, DEALER: dealer},
        policies or {PONE: LowestRank(), DEALER: LowestRank()},
        {PONE: random.Random(0), DEALER: random.Random(0)},
        scores_before,
        target,
    )


class TestScoreCards(unittest.TestCase):
    def test_known_hands_and_crib_flush_rule(self):
        # 5-5-5-J with the fourth 5 cut and the Jack in the starter's suit.
        self.assertEqual(
            score_cards(((4, 0), (4, 1), (4, 2), (10, 3)), (4, 3), False), 29
        )
        self.assertEqual(
            score_cards(((0, 0), (2, 1), (6, 2), (8, 3)), (11, 0), False), 0
        )
        four_flush = ((0, 1), (2, 1), (6, 1), (8, 1))
        self.assertEqual(score_cards(four_flush, (11, 0), is_crib=False), 4)
        self.assertEqual(score_cards(four_flush, (11, 0), is_crib=True), 0)
        self.assertEqual(score_cards(four_flush, (11, 1), is_crib=True), 5)
        # His nobs counts in the crib as well as in a hand.
        self.assertEqual(
            score_cards(((10, 2), (0, 0), (2, 1), (6, 3)), (8, 2), True), 1
        )


class TestPeggingToTarget(unittest.TestCase):
    def test_matches_published_pegging_view_for_view(self):
        deal_rng = random.Random(2026)
        for _ in range(1500):
            cards = deal_rng.sample(PHYSICAL_DECK, 8)
            pone = [card[0] for card in cards[:4]]
            dealer = [card[0] for card in cards[4:]]
            published = ViewHashPolicy()
            expected = simulate_pegging(
                pone, dealer, {PONE: published, DEALER: published}, random.Random(0)
            )
            ladder = ViewHashPolicy()
            winner, pegged = play_pegging_to_target(
                {PONE: pone, DEALER: dealer},
                {PONE: ladder, DEALER: ladder},
                {PONE: random.Random(1), DEALER: random.Random(2)},
                ZERO,
                1000,
            )
            self.assertIsNone(winner)
            self.assertEqual(ladder.views, published.views)
            for role in ROLES:
                self.assertEqual(pegged[role], expected.total(role))

    def test_stops_at_the_point_that_reaches_the_target(self):
        # Both hold 5-T-T-T and play their lowest rank. Pone 5 (5), Dealer 5
        # (10, pair 2), Pone T (20), Dealer T (30, pair 2), both go (Dealer
        # 1), Pone T (10), Dealer T (20, pair 2), Pone T (30, pair royal 6),
        # Dealer go and Pone out (Pone 1), Dealer T (10, last card 1).
        hand = (4, 9, 9, 9)
        self.assertEqual(peg(hand, hand, ZERO), (None, {PONE: 7, DEALER: 8}))
        policies = {PONE: LowestRank(), DEALER: LowestRank()}
        self.assertEqual(
            peg(hand, hand, {PONE: 0, DEALER: 119}, policies),
            (DEALER, {PONE: 0, DEALER: 2}),
        )
        # Pone's lead and Dealer's pair; nobody is asked to play after it.
        self.assertEqual((policies[PONE].calls, policies[DEALER].calls), (1, 1))
        self.assertEqual(  # the go point reaches 121
            peg(hand, hand, {PONE: 0, DEALER: 116}),
            (DEALER, {PONE: 0, DEALER: 5}),
        )
        policies = {PONE: LowestRank(), DEALER: LowestRank()}
        self.assertEqual(  # Pone's go point wins before Dealer's last card
            peg(hand, hand, {PONE: 114, DEALER: 113}, policies),
            (PONE, {PONE: 7, DEALER: 7}),
        )
        self.assertEqual((policies[PONE].calls, policies[DEALER].calls), (4, 3))
        self.assertEqual(  # Pone's pair royal reaches 121 one play before Dealer
            peg(hand, hand, {PONE: 115, DEALER: 113}),
            (PONE, {PONE: 6, DEALER: 7}),
        )
        self.assertEqual(  # the last-card point reaches 121
            peg(hand, hand, {PONE: 0, DEALER: 113}),
            (DEALER, {PONE: 7, DEALER: 8}),
        )

    def test_a_play_scores_all_its_points_together(self):
        # A-2-3-4 each: Dealer pairs every Pone card, and the fourth pair is
        # also the last card, so that play scores 3.
        hand = (0, 1, 2, 3)
        self.assertEqual(peg(hand, hand, ZERO), (None, {PONE: 0, DEALER: 9}))
        for before in (112, 113):
            self.assertEqual(
                peg(hand, hand, {PONE: 0, DEALER: before}),
                (DEALER, {PONE: 0, DEALER: 9}),
            )
        # Pone K-7-2-A, Dealer K-2-A-A: K (10), K (20, pair 2), 7 (27),
        # 2 (29), then Pone's 2 makes 31 and a pair for 4 at once.
        for before in (117, 119):
            scripted = {PONE: Scripted([12, 6, 1]), DEALER: Scripted([12, 1])}
            self.assertEqual(
                peg((12, 6, 1, 0), (12, 1, 0, 0), {PONE: before, DEALER: 0}, scripted),
                (PONE, {PONE: 4, DEALER: 2}),
            )

    def test_calls_no_policy_when_the_game_is_already_over(self):
        policies = {PONE: NoPegging(), DEALER: NoPegging()}
        self.assertEqual(
            peg((0, 1, 2, 3), (0, 1, 2, 3), {PONE: 0, DEALER: 121}, policies),
            (DEALER, ZERO),
        )

    def test_rejects_an_illegal_play(self):
        class PlaysKing:  # pylint: disable=too-few-public-methods
            def select_rank(self, view, rng):
                del view, rng
                return 12

        with self.assertRaisesRegex(ValueError, "Illegal rank"):
            play_pegging_to_target(
                {PONE: (0, 1, 2, 3), DEALER: (0, 1, 2, 3)},
                {PONE: PlaysKing(), DEALER: LowestRank()},
                {PONE: random.Random(0), DEALER: random.Random(0)},
                ZERO,
                121,
            )


class TestRandomRules(unittest.TestCase):
    def test_random_pegging_weighs_duplicate_cards(self):
        # Two Aces and a King: a uniformly chosen card is an Ace 2/3 of the
        # time (600 of 900, sd 14); choosing among distinct ranks gives 450.
        view = PolicyView(PONE, (0, 0, 12), 0, (), 3, (), ())
        rng = random.Random(7)
        aces = sum(
            RandomPeggingPolicy().select_rank(view, rng) == 0 for _ in range(900)
        )
        self.assertTrue(540 < aces < 660, aces)
        blocked = PolicyView(PONE, (0, 12), 25, (12, 12, 4), 1, (), (12, 12, 4))
        self.assertEqual(RandomPeggingPolicy().select_rank(blocked, rng), 0)

    def test_random_discard_covers_all_fifteen_splits_evenly(self):
        dealt = PHYSICAL_DECK[:6]
        rng = random.Random(11)
        seen = Counter(
            RandomDiscardRule().select_discard(PONE, dealt, rng) for _ in range(3000)
        )
        self.assertEqual(len(seen), 15)
        # 200 expected each, sd about 13.7.
        self.assertTrue(all(140 < count < 260 for count in seen.values()), seen)
        for kept, discarded in seen:
            self.assertEqual(sorted(kept + discarded), sorted(dealt))

    def test_checked_split_rejects_a_bad_discard(self):
        dealt = PHYSICAL_DECK[:6]
        good = (dealt[:4], dealt[4:])
        self.assertEqual(checked_split(PONE, dealt, good), good)
        as_lists = (list(dealt[:4]), list(dealt[4:]))
        self.assertEqual(checked_split(PONE, dealt, as_lists), good)
        for bad in (
            (dealt[:3], dealt[3:]),
            (dealt[:4], (dealt[4], PHYSICAL_DECK[40])),
            (dealt[:4], (dealt[4], dealt[4])),
        ):
            with self.assertRaisesRegex(ValueError, "Invalid Pone discard"):
                checked_split(PONE, dealt, bad)


SIX_LOW = ((0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0))
# The crib (two from each) is a four-card flush, which scores only as a hand.
SIX_HIGH = ((6, 1), (7, 1), (8, 1), (11, 1), (12, 0), (11, 0))


def fixed_player(name: str) -> LadderPlayer:
    return LadderPlayer(name, FirstFour(), LowestRank())


class TestPlayGame(unittest.TestCase):
    def play_fixed(self, deals, target):
        with patch("artifact_pipeline.ladder_game.deal_hand", side_effect=deals):
            return play_game(fixed_player("a"), fixed_player("b"), 1, target)

    def test_heels_is_scored_before_pegging(self):
        with patch(
            "artifact_pipeline.ladder_game.deal_hand",
            return_value=(SIX_LOW, SIX_HIGH, (JACK_RANK, 3)),
        ):
            outcome = play_game(
                LadderPlayer("a", FirstFour(), NoPegging()),
                LadderPlayer("b", FirstFour(), NoPegging()),
                1,
                HEELS_POINTS,
            )
        self.assertEqual(
            (outcome.first_pone_score, outcome.first_dealer_score), (0, HEELS_POINTS)
        )
        self.assertEqual(outcome.first_dealer_pegging, 0)
        self.assertEqual(outcome.hands_played, 1)
        self.assertFalse(outcome.first_pone_won)

    def test_counting_order_pone_hand_dealer_hand_then_crib(self):
        starter = (4, 3)
        pone_kept, dealer_kept = SIX_LOW[:4], SIX_HIGH[:4]
        crib = SIX_LOW[4:] + SIX_HIGH[4:]
        _, pegged = peg(
            [c[0] for c in pone_kept], [c[0] for c in dealer_kept], ZERO, target=1000
        )
        pone_hand = score_cards(pone_kept, starter, False)
        dealer_hand = score_cards(dealer_kept, starter, False)
        crib_points = score_cards(crib, starter, True)
        pone_total = pegged[PONE] + pone_hand
        dealer_after_hand = pegged[DEALER] + dealer_hand
        # These cards make each count decide a different target.
        self.assertTrue(
            dealer_after_hand + crib_points > dealer_after_hand > pone_total
        )
        self.assertGreater(pone_total, max(pegged.values()))

        def one_hand(target):
            return self.play_fixed([(SIX_LOW, SIX_HIGH, starter)], target)

        pone_wins = one_hand(pone_total)
        self.assertTrue(pone_wins.first_pone_won)
        self.assertEqual(pone_wins.first_dealer_score, pegged[DEALER])
        dealer_hand_wins = one_hand(dealer_after_hand)
        self.assertEqual(dealer_hand_wins.first_pone_score, pone_total)
        self.assertEqual(dealer_hand_wins.first_dealer_score, dealer_after_hand)
        crib_wins = one_hand(dealer_after_hand + crib_points)
        self.assertEqual(crib_wins.first_dealer_score, dealer_after_hand + crib_points)
        self.assertEqual(
            (crib_wins.first_pone_pegging, crib_wins.first_dealer_pegging),
            (pegged[PONE], pegged[DEALER]),
        )

    def test_the_deal_alternates_each_hand(self):
        strong = ((4, 0), (4, 1), (4, 2), (10, 3), (12, 0), (12, 1))
        quiet = ((0, 0), (2, 1), (6, 2), (8, 3), (11, 0), (11, 1))
        starter = (4, 3)
        _, pegged = peg([4, 4, 4, 10], [0, 2, 6, 8], ZERO, target=1000)
        first_pone = pegged[PONE] + score_cards(strong[:4], starter, False)
        first_dealer = (
            pegged[DEALER]
            + score_cards(quiet[:4], starter, False)
            + score_cards(strong[4:] + quiet[4:], starter, True)
        )
        self.assertGreater(first_pone, first_dealer)
        # Hand 2 cuts a Jack. The player who was Pone first now deals, so he
        # scores his heels and then pairs the Ace that Pone leads.
        deals = [(strong, quiet, starter), (quiet, quiet, (JACK_RANK, 0))]
        target = first_pone + HEELS_POINTS + 2
        outcome = self.play_fixed(deals, target)
        self.assertEqual(outcome.hands_played, 2)
        self.assertTrue(outcome.first_pone_won)
        self.assertEqual(
            (outcome.first_pone_score, outcome.first_dealer_score),
            (target, first_dealer),
        )
        self.assertEqual(
            (outcome.first_pone_pegging, outcome.first_dealer_pegging),
            (pegged[PONE] + 2, pegged[DEALER]),
        )

    def test_swapped_seats_see_the_same_deals_and_streams(self):
        first, second = RecordingRandomDiscard(), RecordingRandomDiscard()
        players = [
            LadderPlayer(name, rule, RandomPeggingPolicy())
            for name, rule in (("a", first), ("b", second))
        ]
        forward = play_game(players[0], players[1], 5)
        mirrored = [
            LadderPlayer(p.name, p.discard_rule, p.pegging_policy) for p in players
        ]
        forward_calls = first.calls + second.calls
        first.calls, second.calls = [], []
        backward = play_game(mirrored[1], mirrored[0], 5)
        backward_calls = first.calls + second.calls
        # Identical rules in both seats: the swapped game is the same game.
        self.assertEqual(forward, backward)
        self.assertEqual(sorted(forward_calls), sorted(backward_calls))
        self.assertGreater(forward.hands_played, 3)
        hands = [dealt for _role, dealt, _split in forward_calls]
        self.assertEqual(len(set(hands)), len(hands))
        self.assertNotEqual(play_game(players[0], players[1], 6), forward)

    def test_each_player_gets_its_own_role_and_that_seat_streams(self):
        first, second = Recorder(), Recorder()
        outcome = play_game(recorded("a", first), recorded("b", second), 5)
        hands = list(zip(first.by_hand(), second.by_hand()))
        self.assertEqual(len(hands), outcome.hands_played)
        self.assertGreater(outcome.hands_played, 3)
        for index, (mine, theirs) in enumerate(hands):
            self.assertEqual(mine[0], (PONE, DEALER)[index % 2])
            self.assertEqual(theirs[0], (DEALER, PONE)[index % 2])
            self.assertNotEqual(mine[1], theirs[1])
            self.assertTrue(mine[2] and theirs[2])
            self.assertEqual({role for role, _ in mine[2]}, {mine[0]})
            self.assertEqual({role for role, _ in theirs[2]}, {theirs[0]})
            self.assertNotEqual(mine[2][0][1], theirs[2][0][1])
        # Each hand draws fresh streams, and so does another game seed.
        for player in (first, second):
            discard_draws = [hand[1] for hand in player.by_hand()]
            pegging_draws = [hand[2][0][1] for hand in player.by_hand()]
            self.assertEqual(len(set(discard_draws)), len(hands))
            self.assertEqual(len(set(pegging_draws)), len(hands))
        other_seed = Recorder()
        play_game(recorded("a", other_seed), recorded("b", Recorder()), 6)
        self.assertNotEqual(other_seed.by_hand()[0][1], first.by_hand()[0][1])
        self.assertNotEqual(
            other_seed.by_hand()[0][2][0][1], first.by_hand()[0][2][0][1]
        )
        # With the seats swapped, whoever holds a seat gets that seat's streams.
        swapped_first, swapped_second = Recorder(), Recorder()
        play_game(recorded("b", swapped_second), recorded("a", swapped_first), 5)
        self.assertEqual(swapped_second.by_hand(), first.by_hand())
        self.assertEqual(swapped_first.by_hand(), second.by_hand())
        # An opponent that draws more from its streams does not shift mine.
        alone = Recorder()
        play_game(recorded("a", alone), recorded("b", DrawsExtra()), 5)
        self.assertEqual(alone.by_hand(), first.by_hand())

    def test_each_deal_uses_thirteen_distinct_cards(self):
        for seed in range(300):
            pone, dealer, starter = deal_hand(random.Random(seed))
            self.assertEqual(len(pone), 6)
            self.assertEqual(len(dealer), 6)
            self.assertEqual(len({*pone, *dealer, starter}), 13)

    def test_each_seat_draws_its_own_pegging_stream(self):
        streams = _pegging_streams(3, 0)
        self.assertNotEqual(streams[PONE].random(), streams[DEALER].random())
        self.assertEqual(
            _pegging_streams(3, 0)[PONE].random(), _pegging_streams(3, 0)[PONE].random()
        )
        self.assertNotEqual(
            _pegging_streams(3, 0)[PONE].random(), _pegging_streams(3, 1)[PONE].random()
        )

    def test_rejects_a_target_below_one(self):
        with self.assertRaisesRegex(ValueError, "must be positive"):
            play_game(fixed_player("a"), fixed_player("b"), 1, 0)

    def test_full_game_is_reproducible_and_reaches_121(self):
        heuristic = LadderPlayer("h", RandomDiscardRule(), LegacyHeuristicPolicy())
        randomly = LadderPlayer("r", RandomDiscardRule(), RandomPeggingPolicy())
        outcome = play_game(heuristic, randomly, 9)
        self.assertEqual(outcome, play_game(heuristic, randomly, 9))
        self.assertGreaterEqual(
            max(outcome.first_pone_score, outcome.first_dealer_score), 121
        )
        self.assertLess(min(outcome.first_pone_score, outcome.first_dealer_score), 121)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
