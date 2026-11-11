//! Counterfactual opponent support, mirroring the research `support.cpp`.
//!
//! For each (policy, prior) pair `k`, bit `k` of an information set's flag is
//! set when the set is reached with positive prior weight while the
//! *opponent* follows policy `k`: at a Pone decision the Dealer's reach bits
//! are recorded and at a Dealer decision Pone's. The deciding player's own
//! actions are all explored, so the flag says whether the opponent's policy
//! can lead there, not whether the decider would choose to. The output is one
//! byte per menu, in global menu order.
//!
//! Bits are combined with OR, which is order independent, so Pone hands run
//! in parallel with atomic updates and the bytes match any serial order.

use super::menus::NIL;
use super::solve::Trees;
use super::trees::{Menus, Node, TAG, Tree};
use rayon::prelude::*;
use std::sync::atomic::{AtomicU8, Ordering};

/// One support bit: a rounded policy and the prior it is paired with.
pub struct Pair<'a> {
    pub policy: &'a [u16],
    pub prior: &'a [u64],
}

fn walk(
    menus: &Menus,
    pairs: &[Pair],
    tree: &Tree,
    flags: &[AtomicU8],
    id: u32,
    pone: u8,
    dealer: u8,
) {
    if id & TAG != 0 {
        return;
    }
    let Node {
        info,
        first,
        off,
        actor,
        width,
    } = tree.node(menus, id);
    let dealer_decides = actor == 1;
    flags[info].fetch_or(
        if dealer_decides { pone } else { dealer },
        Ordering::Relaxed,
    );
    for action in 0..width {
        let mut reach = 0u8;
        for (pair_index, pair) in pairs.iter().enumerate() {
            if pair.policy[off + action] != 0 {
                reach |= 1 << pair_index;
            }
        }
        let (mut next_pone, mut next_dealer) = (pone, dealer);
        if dealer_decides {
            next_dealer &= reach;
        } else {
            next_pone &= reach;
        }
        if next_pone != 0 || next_dealer != 0 {
            walk(
                menus,
                pairs,
                tree,
                flags,
                tree.edges[first + action],
                next_pone,
                next_dealer,
            );
        }
    }
}

/// Support flags for every menu.
pub fn support(menus: &Menus, trees: &dyn Trees, pairs: &[Pair]) -> Vec<u8> {
    assert!(
        !pairs.is_empty() && pairs.len() <= 8,
        "between one and eight pairs"
    );
    for pair in pairs {
        assert_eq!(pair.policy.len() as u64, menus.actions, "policy size");
        assert_eq!(pair.prior.len(), 1820 * 1820, "prior size");
    }
    let flags: Vec<AtomicU8> = (0..menus.len()).map(|_| AtomicU8::new(0)).collect();
    (0..1820).into_par_iter().for_each(|pone_hand| {
        let tree = trees.tree(pone_hand);
        for dealer_hand in 0..1820 {
            let mut reached_pairs = 0u8;
            for (pair_index, pair) in pairs.iter().enumerate() {
                if pair.prior[pone_hand * 1820 + dealer_hand] != 0 {
                    reached_pairs |= 1 << pair_index;
                }
            }
            if reached_pairs != 0 {
                assert!(tree.roots[dealer_hand] != NIL, "prior");
                walk(
                    menus,
                    pairs,
                    &tree,
                    &flags,
                    tree.roots[dealer_hand],
                    reached_pairs,
                    reached_pairs,
                );
            }
        }
    });
    flags.into_iter().map(AtomicU8::into_inner).collect()
}
