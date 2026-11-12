//! The support bits against an oracle that replays each deal from `State`
//! and finds menus by public history, never through trees.

mod common;

use cfr_inputs::game::State;
use cfr_inputs::support::{Pair, support};
use common::{Small, SmallTrees, decides, info_of, matched, small, solve};

/// Mark every menu reached from `state` with `bit` when the seat not deciding
/// there can still be following `policy`. `ok[seat]` says whether every
/// action that seat has taken so far has positive probability under it.
fn reach(
    small_game: &Small,
    policy: &[u16],
    mut state: State,
    (pone_hand, dealer_hand): (usize, usize),
    ok: [bool; 2],
    bit: u8,
    flags: &mut [u8],
) {
    loop {
        if state.cards_left[0] <= 1 && state.cards_left[1] <= 1 {
            return;
        }
        if decides(&state) {
            break;
        }
        let action = state.forced();
        state.play(action);
    }
    let actor = state.next;
    let info = info_of(small_game, &state, pone_hand, dealer_hand);
    if ok[1 - actor] {
        flags[info] |= bit;
    }
    let off = small_game.menus.offset[info] as usize;
    for (action_index, &rank) in state.legal().iter().enumerate() {
        let mut next_ok = ok;
        next_ok[actor] &= policy[off + action_index] != 0;
        if next_ok[0] || next_ok[1] {
            let mut next = state.clone();
            next.play(Some(rank));
            reach(
                small_game,
                policy,
                next,
                (pone_hand, dealer_hand),
                next_ok,
                bit,
                flags,
            );
        }
    }
}

#[test]
fn support_bits_match_a_replay_of_each_policy() {
    // Two pairs that differ in both policy and prior, so each bit is tested
    // on its own and a swap of the two would show.
    let small_game = small();
    let game = small_game.game();
    let early = solve(&small_game, 2, 1).rounded(&game);
    let later = solve(&small_game, 2, 64).rounded(&game);
    let sparse = matched().chance;
    let pairs = [
        Pair {
            policy: &early,
            prior: &small_game.chance,
        },
        Pair {
            policy: &later,
            prior: &sparse,
        },
    ];
    let flags = support(&small_game.menus, &SmallTrees(&small_game.trees), &pairs);
    let mut expected = vec![0u8; small_game.menus.len()];
    for (pair_index, pair) in pairs.iter().enumerate() {
        for pone_hand in 0..1820 {
            for dealer_hand in 0..1820 {
                if pair.prior[pone_hand * 1820 + dealer_hand] != 0 {
                    let state =
                        State::new(small_game.hands[pone_hand], small_game.hands[dealer_hand]);
                    reach(
                        &small_game,
                        pair.policy,
                        state,
                        (pone_hand, dealer_hand),
                        [true; 2],
                        1 << pair_index,
                        &mut expected,
                    );
                }
            }
        }
    }
    assert_eq!(flags, expected);
    let count = |bit: u8| flags.iter().filter(|&&flag| flag & bit != 0).count();
    // The sparse prior reaches fewer menus, and some menus get neither bit.
    assert!(count(2) > 0 && count(2) < count(1));
    assert!(flags.contains(&0));
}
