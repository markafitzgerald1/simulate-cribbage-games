//! Optional-decision menus: the decisions the policy has to make.
//!
//! There is one menu file per (seat, own hand): file `k` covers seat `k / 1820`
//! and own hand `k % 1820`. It lists every information set at which that seat
//! has a real choice among its first three cards (the fourth card and single
//! legal plays are forced), sorted by packed public history. Each record is
//! 19 little-endian bytes:
//!
//! | bytes | field |
//! |---|---|
//! | 0..8 | packed history key |
//! | 8..12 | index of the seat's previous decision in this file, or `u32::MAX` |
//! | 12..16 | legal ranks, ascending, zero padded |
//! | 16 | stage: `seat + 2 * cards already played by the seat` |
//! | 17 | width (number of legal ranks) |
//! | 18 | action taken at the previous decision |
//!
//! Global action offsets are not stored: the solver assigns them when it
//! loads the menus, in file order.

use super::game::{Cards, State, feasible};
use std::collections::HashMap;

/// Marks "no previous decision" in the parent field.
pub const NIL: u32 = u32::MAX;
/// Bytes per menu record.
pub const RECORD: usize = 19;
/// Number of menu files: two seats times 1,820 own hands.
pub const FILES: usize = 3640;

#[derive(Clone, PartialEq, Eq)]
struct Temp {
    parent: u64,
    actions: [u8; 4],
    stage: u8,
    width: u8,
    parent_action: u8,
    has_parent: bool,
}

fn collect(
    mut state: State,
    role: usize,
    parent: u64,
    parent_action: u8,
    has_parent: bool,
    map: &mut HashMap<u64, Temp>,
) {
    loop {
        if state.cards_left[0] <= 1 && state.cards_left[1] <= 1 {
            return;
        }
        let legal = state.legal();
        let card = 4 - state.cards_left[state.next];
        let optional = legal.len() > 1 && card < 3;
        if optional && state.next == role {
            let mut candidate = Temp {
                parent,
                actions: [0; 4],
                stage: u8::try_from(role + 2 * card).expect("stage"),
                width: u8::try_from(legal.len()).expect("width"),
                parent_action,
                has_parent,
            };
            candidate.actions[..legal.len()].copy_from_slice(&legal);
            let key = state.history_key();
            match map.get(&key) {
                None => {
                    map.insert(key, candidate);
                }
                Some(existing) => {
                    // Perfect recall: the same public history must imply the
                    // same previous own decision and the same legal ranks.
                    assert!(
                        existing.has_parent == has_parent
                            && existing.parent == parent
                            && existing.parent_action == parent_action
                            && existing.actions == candidate.actions
                            && existing.stage == candidate.stage,
                        "Recall"
                    );
                }
            }
        }
        if !optional {
            let action = state.forced();
            state.play(action);
            continue;
        }
        let own = state.next == role;
        let key = if own { state.history_key() } else { parent };
        for (i, &rank) in legal.iter().enumerate() {
            let mut next = state.clone();
            next.play(Some(rank));
            collect(
                next,
                role,
                key,
                if own {
                    u8::try_from(i).expect("width")
                } else {
                    parent_action
                },
                own || has_parent,
                map,
            );
        }
        return;
    }
}

/// Build menu file `k` (seat `k / 1820`, own hand `k % 1820`) as bytes.
pub fn build(file_index: usize, hands: &[Cards]) -> Vec<u8> {
    let role = file_index / 1820;
    let own = file_index % 1820;
    let mut map = HashMap::new();
    for other in 0..1820 {
        let (pone, dealer) = if role == 1 {
            (hands[other], hands[own])
        } else {
            (hands[own], hands[other])
        };
        if feasible(&pone, &dealer) {
            collect(State::new(pone, dealer), role, 0, 0, false, &mut map);
        }
    }
    let mut keys: Vec<u64> = map.keys().copied().collect();
    keys.sort_unstable();
    let mut out = Vec::with_capacity(keys.len() * RECORD);
    for key in &keys {
        let record = &map[key];
        let parent = if record.has_parent {
            u32::try_from(keys.partition_point(|&earlier_key| earlier_key < record.parent))
                .expect("menu size")
        } else {
            NIL
        };
        out.extend_from_slice(&key.to_le_bytes());
        out.extend_from_slice(&parent.to_le_bytes());
        out.extend_from_slice(&record.actions);
        out.extend_from_slice(&[record.stage, record.width, record.parent_action]);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::super::game::canonical;
    use super::*;

    #[test]
    fn records_are_sorted_and_parents_point_backwards() {
        let hands = canonical();
        // Dealer holding 5-5-J-K: a small file, so the test is fast, in which
        // some lines give the Dealer a choice at both its first and second
        // card, so some records link back to an earlier choice (a parent).
        let file_index = 1820
            + hands
                .iter()
                .position(|hand| hand == &[4, 4, 10, 12])
                .unwrap();
        let bytes = build(file_index, &hands);
        assert_eq!(bytes.len() % RECORD, 0);
        let rows: Vec<&[u8]> = bytes
            .as_chunks::<RECORD>()
            .0
            .iter()
            .map(|row| &row[..])
            .collect();
        assert_ne!(rows.len(), 0);
        let key = |row: &[u8]| u64::from_le_bytes(row[0..8].try_into().unwrap());
        assert!(rows.windows(2).all(|pair| key(pair[0]) < key(pair[1])));
        let mut parents = 0;
        for (i, row) in rows.iter().enumerate() {
            let parent = u32::from_le_bytes(row[8..12].try_into().unwrap());
            assert_eq!(row[16] % 2, 1, "Dealer stages are odd");
            assert!((2..=4).contains(&row[17]));
            assert!(row[18] < 4);
            let width = usize::from(row[17]);
            let ranks = &row[12..16];
            assert!(ranks[..width].windows(2).all(|pair| pair[0] < pair[1]));
            assert!(ranks[width..].iter().all(|&rank| rank == 0));
            assert!(ranks[..width].iter().all(|&rank| rank < 13));
            if parent != NIL {
                parents += 1;
                assert!((parent as usize) < i, "a parent is a shorter history");
                assert!(rows[parent as usize][16] < row[16]);
            }
        }
        assert!(parents > 0);
    }

    #[test]
    fn hand_of_four_identical_ranks_has_no_choices() {
        let hands = canonical();
        assert_eq!(build(0, &hands).len(), 0);
    }
}
