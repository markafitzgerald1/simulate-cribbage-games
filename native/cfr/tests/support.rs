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
    s: &Small,
    policy: &[u16],
    mut state: State,
    (p, d): (usize, usize),
    ok: [bool; 2],
    bit: u8,
    flags: &mut [u8],
) {
    loop {
        if state.n[0] <= 1 && state.n[1] <= 1 {
            return;
        }
        if decides(&state) {
            break;
        }
        let a = state.heuristic();
        state.play(a);
    }
    let actor = state.next;
    let info = info_of(s, &state, p, d);
    if ok[1 - actor] {
        flags[info] |= bit;
    }
    let off = s.menus.offset[info] as usize;
    for (a, &rank) in state.legal().iter().enumerate() {
        let mut next_ok = ok;
        next_ok[actor] &= policy[off + a] != 0;
        if next_ok[0] || next_ok[1] {
            let mut next = state.clone();
            next.play(Some(rank));
            reach(s, policy, next, (p, d), next_ok, bit, flags);
        }
    }
}

#[test]
fn support_bits_match_a_replay_of_each_policy() {
    // Two pairs that differ in both policy and prior, so each bit is tested
    // on its own and a swap of the two would show.
    let s = small();
    let game = s.game();
    let early = solve(&s, 2, 1).rounded(&game);
    let later = solve(&s, 2, 64).rounded(&game);
    let sparse = matched().chance;
    let pairs = [
        Pair {
            policy: &early,
            prior: &s.chance,
        },
        Pair {
            policy: &later,
            prior: &sparse,
        },
    ];
    let flags = support(&s.menus, &SmallTrees(&s.trees), &pairs);
    let mut expected = vec![0u8; s.menus.len()];
    for (k, pair) in pairs.iter().enumerate() {
        for p in 0..1820 {
            for d in 0..1820 {
                if pair.prior[p * 1820 + d] != 0 {
                    let state = State::new(s.hands[p], s.hands[d]);
                    reach(
                        &s,
                        pair.policy,
                        state,
                        (p, d),
                        [true; 2],
                        1 << k,
                        &mut expected,
                    );
                }
            }
        }
    }
    assert_eq!(flags, expected);
    let count = |bit: u8| flags.iter().filter(|&&f| f & bit != 0).count();
    // The sparse prior reaches fewer menus, and some menus get neither bit.
    assert!(count(2) > 0 && count(2) < count(1));
    assert!(flags.contains(&0));
}
