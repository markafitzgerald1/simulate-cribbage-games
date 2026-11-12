//! Rank-only two-player pegging: the rules every later module walks.
//!
//! The policy makes every real choice. Where the move is forced (one legal
//! rank, a go, or a player's last card), `State::forced` plays it.
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

    /// The forced move: the only legal rank, or `None` for a go.
    ///
    /// # Panics
    ///
    /// If more than one rank is legal, because the policy, not this
    /// function, makes real choices.
    pub fn forced(&self) -> Option<u8> {
        let ranks = self.legal();
        assert!(ranks.len() <= 1, "Forced move with a choice");
        ranks.first().copied()
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

    /// Play out the hand once every remaining move is forced: each player
    /// holds at most one card.
    pub fn finish(&mut self) {
        while self.cards_left != [0, 0] {
            let action = self.forced();
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
        // 3, 4 then a 2: the low card arrives last and completes 2-3-4.
        let state = after([2, 6, 9, 9], [3, 7, 9, 9], &[2, 3]);
        assert_eq!(state.run(1), 3);
        // 5, 3 then a 4: the middle card arrives last and completes 3-4-5.
        let state = after([4, 6, 9, 9], [2, 7, 9, 9], &[4, 2]);
        assert_eq!(state.run(3), 3);
        // 5, 3 then a 6 leaves a gap at 4.
        assert_eq!(state.run(5), 0);
    }

    #[test]
    fn a_repeated_rank_breaks_a_run() {
        // 2, 3, 3 then a 5: 2-3-3-5 spans four values and 3-3-5 spans three,
        // the width of a run of their length, but each repeats the 3. Only
        // the repeat rule rejects them; 2-3-3-4 would not test it, because a
        // repeated rank already narrows its span below a run's width.
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

    #[test]
    fn the_forced_move_is_the_only_legal_rank_or_a_go() {
        // K A K 9 makes 30; Pone's 10 and Jack cannot be played, so Pone goes.
        let state = after([9, 10, 12, 12], [0, 8, 10, 11], &[12, 0, 12, 8]);
        assert_eq!(state.next, 0);
        assert_eq!(state.legal(), Vec::<u8>::new());
        assert_eq!(state.forced(), None);
        // 10 A 10 2 makes 23 and Pone holds two 5s: one legal rank.
        let state = after([4, 4, 9, 9], [0, 1, 2, 3], &[9, 0, 9, 1]);
        assert_eq!(state.legal(), vec![4]);
        assert_eq!(state.forced(), Some(4));
    }

    #[test]
    #[should_panic(expected = "Forced move with a choice")]
    fn a_real_choice_is_not_forced() {
        let _ = State::new([0, 1, 2, 3], [4, 5, 6, 7]).forced();
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
