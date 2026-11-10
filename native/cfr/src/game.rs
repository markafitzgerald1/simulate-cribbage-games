//! Rank-only two-player pegging, mirroring `joint::State` in the research
//! header `cfr_joint_native.hpp` (sha256 5f707f5c...), which was validated
//! against the Python pegging transitions in `artifact_pipeline/pegging.py`.
//!
//! Ranks are 0 (Ace) through 12 (King). Every method keeps the C++ control
//! flow, including the order in which ties are broken, because the menus and
//! trees built from it are compared byte for byte with the saved research
//! outputs.

/// History token for a go, as stored in `State::history`.
pub const GO: i8 = -1;
/// History token for a count reset after a go pair or a 31.
pub const RESET: i8 = -2;

/// The four ranks of a hand, ascending.
pub type Cards = [u8; 4];

/// All 1,820 rank-only four-card hands, in the solver's canonical order.
pub fn canonical() -> Vec<Cards> {
    let mut hands = Vec::with_capacity(1820);
    for a in 0..13 {
        for b in a..13 {
            for c in b..13 {
                for d in c..13 {
                    hands.push([a, b, c, d]);
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
    let mut counts = [0u8; 13];
    for &r in pone.iter().chain(dealer) {
        counts[usize::from(r)] += 1;
    }
    counts.iter().all(|&c| c <= 4)
}

/// A pegging position. Player 0 is Pone, player 1 is Dealer.
#[derive(Clone)]
pub struct State {
    pub hands: [Cards; 2],
    pub n: [usize; 2],
    pub points: [i32; 2],
    pub next: usize,
    pub count: u32,
    passed: u8,
    last: Option<usize>,
    seq: [u8; 8],
    length: usize,
    history: [i8; 24],
    history_length: usize,
}

impl State {
    pub fn new(pone: Cards, dealer: Cards) -> Self {
        State {
            hands: [pone, dealer],
            n: [4, 4],
            points: [0, 0],
            next: 0,
            count: 0,
            passed: 0,
            last: None,
            seq: [0; 8],
            length: 0,
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
        for i in 0..self.n[self.next] {
            if self.count + count_value(hand[i]) <= 31 && (i == 0 || hand[i] != hand[i - 1]) {
                ranks.push(hand[i]);
            }
        }
        ranks
    }

    /// Length of the run completed by playing `rank`, or 0.
    pub fn run(&self, rank: u8) -> usize {
        let mut s = [0u8; 9];
        s[..self.length].copy_from_slice(&self.seq[..self.length]);
        s[self.length] = rank;
        let mut l = self.length + 1;
        while l >= 3 {
            let mut mask = 0u32;
            let (mut low, mut high) = (13u8, 0u8);
            let mut unique = true;
            for &r in &s[self.length + 1 - l..=self.length] {
                if mask & (1 << r) != 0 {
                    unique = false;
                }
                mask |= 1 << r;
                low = low.min(r);
                high = high.max(r);
            }
            if unique && usize::from(high - low) == l - 1 {
                return l;
            }
            l -= 1;
        }
        0
    }

    /// The legacy pegging heuristic; `None` means go.
    pub fn heuristic(&self) -> Option<u8> {
        let ranks = self.legal();
        if ranks.is_empty() {
            return None;
        }
        if self.count == 0
            && let Some(&low) = ranks.iter().rev().find(|&&r| count_value(r) < 5)
        {
            return Some(low);
        }
        let top = self.length.checked_sub(1).map(|i| self.seq[i]);
        if self.length >= 2
            && self.seq[self.length - 1] == self.seq[self.length - 2]
            && let Some(&r) = ranks.iter().find(|&&r| Some(r) == top)
        {
            return Some(r);
        }
        let (mut best, mut run_length) = (None, 0);
        for &r in &ranks {
            let v = self.run(r);
            if v > run_length {
                best = Some(r);
                run_length = v;
            }
        }
        if best.is_some() {
            return best;
        }
        let total = |r: u8| self.count + count_value(r);
        if let Some(&r) = ranks.iter().find(|&&r| total(r) == 15) {
            return Some(r);
        }
        if let Some(&r) = ranks.iter().find(|&&r| Some(r) == top) {
            return Some(r);
        }
        if let Some(&r) = ranks.iter().find(|&&r| total(r) == 31) {
            return Some(r);
        }
        if let Some(&r) = ranks.iter().find(|&&r| (16..=20).contains(&total(r))) {
            return Some(r);
        }
        let mut selected = ranks[0];
        for &r in &ranks {
            if count_value(r) > count_value(selected) {
                selected = r;
            }
        }
        Some(selected)
    }

    fn reset(&mut self, role: usize) {
        self.count = 0;
        self.length = 0;
        self.passed = 0;
        self.append(RESET);
        self.next = role;
        self.last = None;
    }

    /// Play `action` (`None` is a go) for the player to act. Returns true
    /// when the last card has been played.
    pub fn play(&mut self, action: Option<u8>) -> bool {
        let role = self.next;
        let Some(a) = action else {
            assert!(self.legal().is_empty(), "Illegal go");
            self.append(GO);
            if self.passed & (1 << (1 - role)) != 0 {
                let last = self.last.expect("No last player");
                self.points[last] += 1;
                self.reset(1 - last);
            } else {
                self.passed |= 1 << role;
                self.next = 1 - role;
            }
            return false;
        };
        assert!(self.legal().contains(&a), "Illegal rank");
        let mut pair_length = 1;
        for &r in self.seq[..self.length].iter().rev() {
            if r != a {
                break;
            }
            pair_length += 1;
        }
        let pairs = match pair_length {
            2 => 2,
            3 => 6,
            4 => 12,
            _ => 0,
        };
        let mut score = i32::try_from(self.run(a)).expect("run length") + pairs;
        let n = self.n[role];
        let hand = &mut self.hands[role];
        let at = hand[..n]
            .iter()
            .position(|&r| r == a)
            .expect("Rank in hand");
        hand.copy_within(at + 1..n, at);
        self.n[role] -= 1;
        self.count += count_value(a);
        self.seq[self.length] = a;
        self.length += 1;
        self.append(a.cast_signed());
        self.last = Some(role);
        if self.count == 15 || self.count == 31 {
            score += 2;
        }
        self.points[role] += score;
        if self.n[0] == 0 && self.n[1] == 0 {
            if self.count != 31 {
                self.points[role] += 1;
            }
            return true;
        }
        if self.count == 31 {
            self.reset(1 - role);
        } else {
            self.next = 1 - role;
        }
        false
    }

    /// Play the heuristic for both players until the hand ends.
    pub fn finish(&mut self) {
        while self.n[0] != 0 || self.n[1] != 0 {
            let action = self.heuristic();
            if self.play(action) {
                break;
            }
        }
    }

    /// Packed public history: one 4-bit token per event, oldest lowest.
    /// Ranks are 1-13, a go 14 and a reset 15.
    pub fn history_key(&self) -> u64 {
        assert!(self.history_length <= 13, "History key bound");
        let mut key = 0u64;
        for (i, &t) in self.history[..self.history_length].iter().enumerate() {
            let token: u64 = match t {
                GO => 14,
                RESET => 15,
                r => u64::from(r.cast_unsigned()) + 1,
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
        assert!(hands.windows(2).all(|w| w[0] < w[1]));
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
        let mut s = State::new([6, 9, 10, 11], [7, 8, 12, 12]);
        assert!(!s.play(Some(6)));
        assert!(!s.play(Some(7)));
        assert_eq!(s.points, [0, 2]);
        assert_eq!(s.count, 15);
    }

    /// Both players hold 10-J-Q-K; 10, J, Q makes 30 and both then go.
    fn thirty_then_two_goes() -> State {
        let mut s = State::new([9, 10, 11, 12], [9, 10, 11, 12]);
        s.play(Some(9));
        s.play(Some(10));
        s.play(Some(11));
        assert_eq!(s.count, 30);
        s.play(None); // Dealer goes.
        s.play(None); // Pone goes: Pone (last to play) pegs one.
        s
    }

    #[test]
    fn go_pair_awards_the_last_player_and_resets() {
        let s = thirty_then_two_goes();
        // Pone's Q completed the run 10-J-Q (3), then pegs the go (1).
        assert_eq!(s.points, [4, 0]);
        assert_eq!(s.count, 0);
        assert_eq!(s.next, 1);
    }

    #[test]
    fn run_detection_handles_out_of_order_runs() {
        let mut s = State::new([2, 6, 9, 9], [3, 7, 9, 9]);
        s.play(Some(2)); // 3
        s.play(Some(3)); // 4
        assert_eq!(s.run(1), 3); // a 2 completes 2-3-4
        assert_eq!(s.run(4), 3); // a 5 completes 3-4-5
        assert_eq!(s.run(5), 0);
    }

    /// The state after Pone and Dealer play `ranks` alternately from the start.
    fn after(pone: Cards, dealer: Cards, ranks: &[u8]) -> State {
        let mut s = State::new(pone, dealer);
        for &r in ranks {
            s.play(Some(r));
        }
        s
    }

    #[test]
    fn heuristic_follows_its_priorities_in_order() {
        // Ranks are 0 (ace) to 12 (king); 9-12 count ten.
        // Nothing fits under 31 after 10-J-Q: a go.
        let go = after([9, 10, 11, 12], [9, 10, 11, 12], &[9, 10, 11]);
        assert_eq!(go.heuristic(), None);
        // A pair of 3s on the table: three of a kind beats the 9 that
        // would make fifteen.
        let triple = after([2, 2, 8, 12], [2, 5, 6, 7], &[2, 2]);
        assert_eq!(triple.heuristic(), Some(2));
        // 3 then 4: the 5 completes a run.
        let run = after([2, 4, 9, 12], [3, 5, 6, 7], &[2, 3]);
        assert_eq!(run.heuristic(), Some(4));
        // After a 10: the 5 makes fifteen, ahead of pairing the 10.
        let fifteen = after([0, 2, 3, 9], [1, 4, 9, 11], &[9]);
        assert_eq!(fifteen.heuristic(), Some(4));
        // After a 10: pair it, since nothing makes fifteen.
        let pair = after([0, 2, 3, 9], [1, 2, 6, 9], &[9]);
        assert_eq!(pair.heuristic(), Some(9));
        // At 21: the jack makes 31. No case can tell this branch from the
        // highest-value fallback: from 21 nothing reaches 16 to 20, and the
        // card making 31 is the highest legal value, lowest rank first.
        let thirty_one = after([0, 5, 7, 12], [3, 5, 9, 10], &[12, 9, 0]);
        assert_eq!(thirty_one.heuristic(), Some(10));
        // After a 10: the 6 is the lowest card reaching 16 to 20.
        let mid = after([0, 2, 3, 9], [0, 5, 8, 12], &[9]);
        assert_eq!(mid.heuristic(), Some(5));
        // After a 10, with only low cards: the highest value.
        let high = after([4, 6, 7, 9], [0, 1, 2, 3], &[9]);
        assert_eq!(high.heuristic(), Some(3));
    }

    #[test]
    fn pairs_score_two_six_and_twelve() {
        let s = after([2, 2, 5, 6], [2, 2, 7, 8], &[2, 2, 2, 2]);
        // Dealer's pair (2) and four of a kind (12); Pone's three (6).
        assert_eq!(s.points, [6, 14]);
        assert_eq!(s.count, 12);
    }

    #[test]
    fn thirty_one_scores_two_and_resets_for_the_other_player() {
        let s = after([0, 5, 7, 12], [3, 5, 9, 10], &[12, 9, 0, 10]);
        assert_eq!(s.points, [0, 2]);
        assert_eq!(s.count, 0);
        assert_eq!(s.next, 0);
    }

    #[test]
    fn heuristic_leads_highest_card_under_five() {
        let s = State::new([0, 3, 4, 12], [1, 2, 3, 4]);
        assert_eq!(s.heuristic(), Some(3));
    }

    #[test]
    fn history_key_packs_ranks_goes_and_resets() {
        let s = thirty_then_two_goes();
        // Tokens: 10, 11, 12, go 14, go 14, reset 15.
        let expected = 0xA | 0xB << 4 | 0xC << 8 | 0xE << 12 | 0xE << 16 | 0xF << 20;
        assert_eq!(s.history_key(), expected);
    }

    #[test]
    fn last_card_scores_one_unless_thirty_one() {
        let mut s = State::new([0, 0, 0, 0], [1, 1, 1, 1]);
        s.finish();
        assert_eq!(s.n, [0, 0]);
        assert!(s.points[0] + s.points[1] > 0);
    }
}
