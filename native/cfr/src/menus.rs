//! Optional-decision menus, mirroring `collect` and `make_menu` in the research
//! `stream.cpp` (sha256 4e95ce60... before its include paths were relocated).
//!
//! There is one menu file per (seat, own hand): file `k` covers seat `k / 1820`
//! and own hand `k % 1820`. It lists every information set at which that seat
//! has a real choice among its first three cards (the fourth card and single
//! legal plays are forced), sorted by packed public history. Each record is
//! 24 little-endian bytes:
//!
//! | bytes | field |
//! |---|---|
//! | 0..8 | packed history key |
//! | 8..12 | index of the seat's previous decision in this file, or `u32::MAX` |
//! | 12..16 | zero (the solver assigns global action offsets when loading) |
//! | 16..20 | legal ranks, ascending, zero padded |
//! | 20 | stage: `seat + 2 * cards already played by the seat` |
//! | 21 | width (number of legal ranks) |
//! | 22 | index of the heuristic's rank |
//! | 23 | action taken at the previous decision |

use super::game::{Cards, State, feasible};
use std::collections::HashMap;

/// Marks "no previous decision" in the parent field.
pub const NIL: u32 = u32::MAX;
/// Bytes per menu record.
pub const RECORD: usize = 24;
/// Number of menu files: two seats times 1,820 own hands.
pub const FILES: usize = 3640;

#[derive(Clone, PartialEq, Eq)]
struct Temp {
    parent: u64,
    actions: [u8; 4],
    stage: u8,
    width: u8,
    heuristic: u8,
    parent_action: u8,
    has_parent: bool,
}

fn collect(
    mut s: State,
    role: usize,
    parent: u64,
    parent_action: u8,
    has_parent: bool,
    map: &mut HashMap<u64, Temp>,
) {
    loop {
        if s.n[0] <= 1 && s.n[1] <= 1 {
            return;
        }
        let legal = s.legal();
        let card = 4 - s.n[s.next];
        let optional = legal.len() > 1 && card < 3;
        if optional && s.next == role {
            let heuristic = s.heuristic();
            let mut t = Temp {
                parent,
                actions: [0; 4],
                stage: u8::try_from(role + 2 * card).expect("stage"),
                width: u8::try_from(legal.len()).expect("width"),
                heuristic: 0,
                parent_action,
                has_parent,
            };
            for (i, &r) in legal.iter().enumerate() {
                t.actions[i] = r;
                if Some(r) == heuristic {
                    t.heuristic = u8::try_from(i).expect("width");
                }
            }
            let key = s.history_key();
            match map.get(&key) {
                None => {
                    map.insert(key, t);
                }
                Some(v) => {
                    // Perfect recall: the same public history must imply the
                    // same previous own decision and the same legal ranks.
                    assert!(
                        v.has_parent == has_parent
                            && v.parent == parent
                            && v.parent_action == parent_action
                            && v.actions == t.actions
                            && v.stage == t.stage,
                        "Recall"
                    );
                }
            }
        }
        if !optional {
            let action = s.heuristic();
            s.play(action);
            continue;
        }
        let own = s.next == role;
        let key = if own { s.history_key() } else { parent };
        for (i, &r) in legal.iter().enumerate() {
            let mut next = s.clone();
            next.play(Some(r));
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
pub fn build(k: usize, hands: &[Cards]) -> Vec<u8> {
    let role = k / 1820;
    let own = k % 1820;
    let mut map = HashMap::new();
    for other in 0..1820 {
        let (p, d) = if role == 1 {
            (hands[other], hands[own])
        } else {
            (hands[own], hands[other])
        };
        if feasible(&p, &d) {
            collect(State::new(p, d), role, 0, 0, false, &mut map);
        }
    }
    let mut keys: Vec<u64> = map.keys().copied().collect();
    keys.sort_unstable();
    let mut out = Vec::with_capacity(keys.len() * RECORD);
    for key in &keys {
        let t = &map[key];
        let parent = if t.has_parent {
            u32::try_from(keys.partition_point(|&k| k < t.parent)).expect("menu size")
        } else {
            NIL
        };
        out.extend_from_slice(&key.to_le_bytes());
        out.extend_from_slice(&parent.to_le_bytes());
        out.extend_from_slice(&0u32.to_le_bytes());
        out.extend_from_slice(&t.actions);
        out.extend_from_slice(&[t.stage, t.width, t.heuristic, t.parent_action]);
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
        // Dealer holding 5-5-J-K: a modest file that still has parents.
        let k = 1820 + hands.iter().position(|h| h == &[4, 4, 10, 12]).unwrap();
        let bytes = build(k, &hands);
        assert_eq!(bytes.len() % RECORD, 0);
        let rows: Vec<&[u8]> = bytes
            .as_chunks::<RECORD>()
            .0
            .iter()
            .map(|r| &r[..])
            .collect();
        assert_ne!(rows.len(), 0);
        let key = |r: &[u8]| u64::from_le_bytes(r[0..8].try_into().unwrap());
        assert!(rows.windows(2).all(|w| key(w[0]) < key(w[1])));
        let mut parents = 0;
        for (i, r) in rows.iter().enumerate() {
            let parent = u32::from_le_bytes(r[8..12].try_into().unwrap());
            assert_eq!(&r[12..16], &[0, 0, 0, 0]);
            assert_eq!(r[20] % 2, 1, "Dealer stages are odd");
            assert!((2..=4).contains(&r[21]));
            assert!(r[22] < r[21] && r[23] < 4);
            if parent != NIL {
                parents += 1;
                assert!((parent as usize) < i, "a parent is a shorter history");
                assert!(rows[parent as usize][20] < r[20]);
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
