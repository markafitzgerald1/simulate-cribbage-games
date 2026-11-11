//! Rank-only two-player pegging: the rules every later module walks, and the
//! legacy pegging heuristic.
//!
//! The heuristic is the rule-based policy in `artifact_pipeline/pegging.py`.
//! The generator plays it only where the move is forced (one legal rank, a go
//! or a player's last card), so its rules change no game value. Each menu
//! record also stores its choice at the decision, and because that byte is
//! part of the menu files, the order in which the heuristic breaks ties is
//! part of the generated output.
//!
//! Ranks are 0 (Ace) through 12 (King).

/// History token for a go, as stored in `State::history`.
pub const GO: i8 = -1;
/// History token for a count reset after a go pair or a 31.
pub const RESET: i8 = -2;

/// The four ranks of a hand, ascending.
pub type Cards = [u8; 4];

/// All 1,820 rank-only four-card hands, in the solver's canonical order.
pub fn canonical() -> Vec<Cards> {
    let mut hands = Vec::with_capacity(1820);
    for first in 0..13 {
        for second in first..13 {
            for third in second..13 {
                for fourth in third..13 {
                    hands.push([first, second, third, fourth]);
                }
            }
        }
    }
    hands
}

/// Pegging count value: Ace 1 through ten-cards 10.
pub fn count_value(rank: u8) -> u32 {
    u32::from(rank + 1).min(10)
}

/// Whether two rank hands can be dealt from one deck (no rank used 5 times).
pub fn feasible(pone: &Cards, dealer: &Cards) -> bool {
    let mut copies = [0u8; 13];
    for &rank in pone.iter().chain(dealer) {
        copies[usize::from(rank)] += 1;
    }
    copies.iter().all(|&count| count <= 4)
}

/// A pegging position. Player 0 is Pone, player 1 is Dealer.
#[derive(Clone)]
pub struct State {
    /// Each player's unplayed ranks, ascending, in the first `cards_left`.
    pub hands: [Cards; 2],
    pub cards_left: [usize; 2],
    pub points: [i32; 2],
    /// The player to act.
    pub next: usize,
    pub count: u32,
    /// Bit `p` is set once player `p` has said go since the last reset.
    passed: u8,
    last_player: Option<usize>,
    /// Ranks played since the last reset, oldest first.
    played: [u8; 8],
    played_length: usize,
    /// Every event this hand: ranks, `GO` and `RESET` tokens.
    history: [i8; 24],
    history_length: usize,
}

impl State {
    pub fn new(pone: Cards, dealer: Cards) -> Self {
        State {
            hands: [pone, dealer],
            cards_left: [4, 4],
            points: [0, 0],
            next: 0,
            count: 0,
            passed: 0,
            last_player: None,
            played: [0; 8],
            played_length: 0,
            history: [0; 24],
            history_length: 0,
        }
    }

    fn append(&mut self, token: i8) {
        assert!(self.history_length < 24, "History capacity");
        self.history[self.history_length] = token;
        self.history_length += 1;
    }

    /// Distinct playable ranks for the player to act, ascending.
    pub fn legal(&self) -> Vec<u8> {
        let hand = &self.hands[self.next];
        let mut ranks = Vec::with_capacity(4);
        for i in 0..self.cards_left[self.next] {
            let fits = self.count + count_value(hand[i]) <= 31;
            let duplicate = i > 0 && hand[i] == hand[i - 1];
            if fits && !duplicate {
                ranks.push(hand[i]);
            }
        }
        ranks
    }

    /// Length of the run completed by playing `rank`, or 0.
    ///
    /// Tries the longest tail of the played cards first: a tail of length
    /// `run_length` is a run when its ranks are distinct and span exactly
    /// `run_length` consecutive values.
    pub fn run(&self, rank: u8) -> usize {
        let mut cards = [0u8; 9];
        cards[..self.played_length].copy_from_slice(&self.played[..self.played_length]);
        cards[self.played_length] = rank;
        let total = self.played_length + 1;
        for run_length in (3..=total).rev() {
            let tail = &cards[total - run_length..total];
            let mut seen = 0u32;
            let mut distinct = true;
            for &card in tail {
                distinct &= seen & (1 << card) == 0;
                seen |= 1 << card;
            }
            let low = tail.iter().min().expect("non-empty tail");
            let high = tail.iter().max().expect("non-empty tail");
            if distinct && usize::from(high - low) == run_length - 1 {
                return run_length;
            }
        }
        0
    }

    /// The legacy pegging heuristic; `None` means go.
    ///
    /// It takes the first rule that applies, and within a rule the lowest
    /// legal rank, unless the rule says otherwise:
    /// 1. leading: the highest card worth less than five;
    /// 2. after a pair: three of a kind;
    /// 3. the longest run;
    /// 4. fifteen;
    /// 5. a pair with the last card;
    /// 6. thirty-one;
    /// 7. a count of 16 to 20;
    /// 8. otherwise the highest count value.
    pub fn heuristic(&self) -> Option<u8> {
        let ranks = self.legal();
        if ranks.is_empty() {
            return None;
        }
        if self.count == 0
            && let Some(&lead) = ranks.iter().rev().find(|&&rank| count_value(rank) < 5)
        {
            return Some(lead);
        }
        let last_card = self.played_length.checked_sub(1).map(|i| self.played[i]);
        let after_pair = self.played_length >= 2
            && self.played[self.played_length - 1] == self.played[self.played_length - 2];
        if after_pair && let Some(&trips) = ranks.iter().find(|&&rank| Some(rank) == last_card) {
            return Some(trips);
        }
        // The first rank reaching the strictly longest run wins.
        let mut longest: Option<(u8, usize)> = None;
        for &rank in &ranks {
            let run_length = self.run(rank);
            if run_length > longest.map_or(0, |(_, best)| best) {
                longest = Some((rank, run_length));
            }
        }
        if let Some((rank, _)) = longest {
            return Some(rank);
        }
        let count_after = |rank: u8| self.count + count_value(rank);
        let first_where =
            |rule: &dyn Fn(u8) -> bool| ranks.iter().copied().find(|&rank| rule(rank));
        first_where(&|rank| count_after(rank) == 15)
            .or_else(|| first_where(&|rank| Some(rank) == last_card))
            .or_else(|| first_where(&|rank| count_after(rank) == 31))
            .or_else(|| first_where(&|rank| (16..=20).contains(&count_after(rank))))
            .or_else(|| {
                // The first rank with the strictly highest count value.
                let mut highest = ranks[0];
                for &rank in &ranks {
                    if count_value(rank) > count_value(highest) {
                        highest = rank;
                    }
                }
                Some(highest)
            })
    }

    fn reset(&mut self, to_act: usize) {
        self.count = 0;
        self.played_length = 0;
        self.passed = 0;
        self.append(RESET);
        self.next = to_act;
        self.last_player = None;
    }

    /// Play `action` (`None` is a go) for the player to act. Returns true
    /// when the last card has been played.
    pub fn play(&mut self, action: Option<u8>) -> bool {
        let player = self.next;
        let other = 1 - player;
        let Some(rank) = action else {
            assert!(self.legal().is_empty(), "Illegal go");
            self.append(GO);
            if self.passed & (1 << other) != 0 {
                // Both have said go: the last player to lay a card pegs one.
                let last_player = self.last_player.expect("No last player");
                self.points[last_player] += 1;
                self.reset(1 - last_player);
            } else {
                self.passed |= 1 << player;
                self.next = other;
            }
            return false;
        };
        assert!(self.legal().contains(&rank), "Illegal rank");
        let matching = self.played[..self.played_length]
            .iter()
            .rev()
            .take_while(|&&earlier| earlier == rank)
            .count();
        let pairs = match matching {
            1 => 2,
            2 => 6,
            3 => 12,
            _ => 0,
        };
        let mut score = i32::try_from(self.run(rank)).expect("run length") + pairs;
        let held = self.cards_left[player];
        let hand = &mut self.hands[player];
        let position = hand[..held]
            .iter()
            .position(|&card| card == rank)
            .expect("Rank in hand");
        hand.copy_within(position + 1..held, position);
        self.cards_left[player] -= 1;
        self.count += count_value(rank);
        self.played[self.played_length] = rank;
        self.played_length += 1;
        self.append(rank.cast_signed());
        self.last_player = Some(player);
        if self.count == 15 || self.count == 31 {
            score += 2;
        }
        self.points[player] += score;
        if self.cards_left == [0, 0] {
            if self.count != 31 {
                self.points[player] += 1;
            }
            return true;
        }
        if self.count == 31 {
            self.reset(other);
        } else {
            self.next = other;
        }
        false
    }

    /// Play the heuristic for both players until the hand ends.
    pub fn finish(&mut self) {
        while self.cards_left != [0, 0] {
            let action = self.heuristic();
            if self.play(action) {
                break;
            }
        }
    }

    /// Packed public history: one 4-bit token per event, oldest lowest.
    /// Ranks are 1-13, a go 14 and a reset 15. Menus only need histories of
    /// up to 13 events (16 would fit), so one integer identifies the history
    /// for hashing and comparison.
    pub fn history_key(&self) -> u64 {
        assert!(self.history_length <= 13, "History key bound");
        let mut key = 0u64;
        for (i, &event) in self.history[..self.history_length].iter().enumerate() {
            let token: u64 = match event {
                GO => 14,
                RESET => 15,
                rank => u64::from(rank.cast_unsigned()) + 1,
            };
            key |= token << (4 * i);
        }
        key
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_hands_are_ordered_and_complete() {
        let hands = canonical();
        assert_eq!(hands.len(), 1820);
        assert_eq!(hands[0], [0, 0, 0, 0]);
        assert_eq!(hands[1], [0, 0, 0, 1]);
        assert_eq!(hands[1819], [12, 12, 12, 12]);
        assert!(hands.windows(2).all(|pair| pair[0] < pair[1]));
    }

    #[test]
    fn feasibility_limits_each_rank_to_four() {
        assert!(feasible(&[0, 0, 1, 1], &[0, 0, 1, 1]));
        assert!(!feasible(&[0, 0, 0, 1], &[0, 0, 2, 3]));
    }

    #[test]
    fn count_values_cap_at_ten() {
        let values: Vec<u32> = (0..13).map(count_value).collect();
        assert_eq!(values, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10]);
    }

    #[test]
    fn fifteen_two_and_pair_score_for_the_player() {
        // Pone leads a 7 (rank 6); Dealer makes 15 with an 8 (rank 7).
        let mut state = State::new([6, 9, 10, 11], [7, 8, 12, 12]);
        assert!(!state.play(Some(6)));
        assert!(!state.play(Some(7)));
        assert_eq!(state.points, [0, 2]);
        assert_eq!(state.count, 15);
    }

    /// Both players hold 10-J-Q-K; 10, J, Q makes 30 and both then go.
    fn thirty_then_two_goes() -> State {
        let mut state = State::new([9, 10, 11, 12], [9, 10, 11, 12]);
        state.play(Some(9));
        state.play(Some(10));
        state.play(Some(11));
        assert_eq!(state.count, 30);
        state.play(None); // Dealer goes.
        state.play(None); // Pone goes: Pone (last to play) pegs one.
        state
    }

    #[test]
    fn go_pair_awards_the_last_player_and_resets() {
        let state = thirty_then_two_goes();
        // Pone's Q completed the run 10-J-Q (3), then pegs the go (1).
        assert_eq!(state.points, [4, 0]);
        assert_eq!(state.count, 0);
        assert_eq!(state.next, 1);
    }

    #[test]
    fn run_detection_handles_out_of_order_runs() {
        let mut state = State::new([2, 6, 9, 9], [3, 7, 9, 9]);
        state.play(Some(2)); // 3
        state.play(Some(3)); // 4
        assert_eq!(state.run(1), 3); // a 2 completes 2-3-4
        assert_eq!(state.run(4), 3); // a 5 completes 3-4-5
        assert_eq!(state.run(5), 0);
    }

    #[test]
    fn a_repeated_rank_breaks_a_run() {
        // 2, 3, 3 then a 5: 2-3-3-5 and 3-3-5 span the right width but
        // repeat the 3, so neither is a run.
        let state = after([1, 2, 9, 9], [2, 4, 9, 9], &[1, 2, 2]);
        assert_eq!(state.run(4), 0);
    }

    #[test]
    fn the_longest_run_wins() {
        // A-2-3 then a 4: a run of four, not of three.
        let state = after([0, 2, 9, 9], [1, 10, 11, 12], &[0, 1, 2]);
        assert_eq!(state.run(3), 4);
    }

    #[test]
    fn a_shorter_tail_can_still_be_a_run() {
        // 3, A, 2 then a 3: the four-card tail repeats the 3, but A-2-3 is a
        // run of three.
        let state = after([1, 2, 9, 9], [0, 10, 11, 12], &[2, 0, 1]);
        assert_eq!(state.run(2), 3);
    }

    /// The state after Pone and Dealer play `ranks` alternately from the start.
    fn after(pone: Cards, dealer: Cards, ranks: &[u8]) -> State {
        let mut state = State::new(pone, dealer);
        for &rank in ranks {
            state.play(Some(rank));
        }
        state
    }

    // One test per heuristic rule, in priority order. Ranks are 0 (ace) to
    // 12 (king); 9-12 count ten.

    #[test]
    fn heuristic_goes_when_nothing_fits() {
        // Nothing fits under 31 after 10-J-Q.
        let state = after([9, 10, 11, 12], [9, 10, 11, 12], &[9, 10, 11]);
        assert_eq!(state.heuristic(), None);
    }

    #[test]
    fn heuristic_leads_highest_card_under_five() {
        let state = State::new([0, 3, 4, 12], [1, 2, 3, 4]);
        assert_eq!(state.heuristic(), Some(3));
    }

    #[test]
    fn heuristic_prefers_three_of_a_kind_to_fifteen() {
        // A pair of 3s on the table: the 3 beats the 9 that makes fifteen.
        let state = after([2, 2, 8, 12], [2, 5, 6, 7], &[2, 2]);
        assert_eq!(state.heuristic(), Some(2));
    }

    #[test]
    fn heuristic_completes_a_run() {
        // 3 then 4: the 5 completes a run.
        let state = after([2, 4, 9, 12], [3, 5, 6, 7], &[2, 3]);
        assert_eq!(state.heuristic(), Some(4));
    }

    #[test]
    fn heuristic_prefers_the_longer_run() {
        // 2, A, 3 played: a 4 makes a run of four, a 2 only of three.
        let state = after([1, 2, 9, 9], [0, 1, 3, 12], &[1, 0, 2]);
        assert_eq!(state.heuristic(), Some(3));
    }

    #[test]
    fn heuristic_takes_the_lowest_of_equal_runs() {
        // 3 then 4: a 2 and a 5 both make a run of three; the 2 is lower.
        let state = after([1, 2, 4, 9], [3, 9, 9, 9], &[2, 3]);
        assert_eq!(state.heuristic(), Some(1));
    }

    #[test]
    fn heuristic_prefers_fifteen_to_a_pair() {
        // After a 10: the 5 makes fifteen, ahead of pairing the 10.
        let state = after([0, 2, 3, 9], [1, 4, 9, 11], &[9]);
        assert_eq!(state.heuristic(), Some(4));
    }

    #[test]
    fn heuristic_pairs_the_last_card() {
        // After a 10, with nothing making fifteen: pair it.
        let state = after([0, 2, 3, 9], [1, 2, 6, 9], &[9]);
        assert_eq!(state.heuristic(), Some(9));
    }

    #[test]
    fn heuristic_makes_thirty_one() {
        // At 21: the jack makes 31. No case can tell this rule from the
        // highest-value fallback: from 21 nothing reaches 16 to 20, and the
        // card making 31 is the highest legal value, lowest rank first.
        let state = after([0, 5, 7, 12], [3, 5, 9, 10], &[12, 9, 0]);
        assert_eq!(state.heuristic(), Some(10));
    }

    #[test]
    fn heuristic_reaches_sixteen_to_twenty_with_the_lowest_card() {
        // After a 10: the 6 is the lowest card reaching 16 to 20.
        let state = after([0, 2, 3, 9], [0, 5, 8, 12], &[9]);
        assert_eq!(state.heuristic(), Some(5));
    }

    #[test]
    fn heuristic_falls_back_to_the_highest_value() {
        // After a 10, with only low cards: the highest value.
        let state = after([4, 6, 7, 9], [0, 1, 2, 3], &[9]);
        assert_eq!(state.heuristic(), Some(3));
    }

    #[test]
    fn heuristic_takes_the_lowest_of_equal_values() {
        // Leading with only ten-cards: the 10, the lowest of four equal values.
        let state = State::new([9, 10, 11, 12], [0, 1, 2, 3]);
        assert_eq!(state.heuristic(), Some(9));
    }

    #[test]
    fn pairs_score_two_six_and_twelve() {
        let state = after([2, 2, 5, 6], [2, 2, 7, 8], &[2, 2, 2, 2]);
        // Dealer's pair (2) and four of a kind (12); Pone's three (6).
        assert_eq!(state.points, [6, 14]);
        assert_eq!(state.count, 12);
    }

    #[test]
    fn thirty_one_scores_two_and_resets_for_the_other_player() {
        let state = after([0, 5, 7, 12], [3, 5, 9, 10], &[12, 9, 0, 10]);
        assert_eq!(state.points, [0, 2]);
        assert_eq!(state.count, 0);
        assert_eq!(state.next, 0);
    }

    #[test]
    fn history_key_packs_ranks_goes_and_resets() {
        let state = thirty_then_two_goes();
        // Tokens: 10, 11, 12, go 14, go 14, reset 15, 4 bits each.
        let expected = 0xA | 0xB << 4 | 0xC << 8 | 0xE << 12 | 0xE << 16 | 0xF << 20;
        assert_eq!(state.history_key(), expected);
    }

    #[test]
    fn the_last_card_scores_one() {
        // A A A A 2 3 2 K: `finish` plays each player's only remaining card.
        // Pone's 2 makes 11 with no pair, run or fifteen, and the Dealer's
        // King is the last card, at 21 with no pair, run, fifteen or 31.
        let mut state = after([0, 0, 1, 1], [0, 0, 2, 12], &[0, 0, 0, 0, 1, 2]);
        let before = state.points;
        state.finish();
        assert_eq!(state.cards_left, [0, 0]);
        assert_eq!(state.points, [before[0], before[1] + 1]);
    }

    #[test]
    fn a_last_card_making_thirty_one_scores_two_not_three() {
        // K A K 2 A 2 4 A: the Dealer's last Ace makes 31, with no pair or
        // run, so it scores the 31's two points and no extra last-card point.
        let mut state = after([0, 3, 12, 12], [0, 0, 1, 1], &[12, 0, 12, 1, 0, 1, 3]);
        let before = state.points;
        state.play(Some(0));
        assert_eq!(state.cards_left, [0, 0]);
        assert_eq!(state.points, [before[0], before[1] + 2]);
    }
}
