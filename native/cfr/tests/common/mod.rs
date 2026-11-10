//! The small game shared by the integration tests: two Pone hands against
//! three Dealer hands, with menus and trees built by the library itself.

#![allow(dead_code)] // Each test binary uses a different part of this module.

use cfr_inputs::game::{Cards, State, canonical, feasible};
use cfr_inputs::menus::{self, FILES};
use cfr_inputs::solve::{Game, Solver, Trees};
use cfr_inputs::trees::{Menus, Tree};
use std::collections::HashMap;

/// Two Pone hands against three Dealer hands each.
pub const PONES: [[u8; 4]; 2] = [[0, 4, 9, 12], [2, 3, 6, 10]];
pub const DEALERS: [[u8; 4]; 3] = [[1, 4, 7, 11], [3, 5, 5, 9], [0, 8, 10, 12]];

/// Each Pone hand meets exactly one Dealer hand and vice versa, so every
/// information set has a single deal behind it and a best response is a plain
/// expectimax over the game.
pub const MATCHED: [(usize, usize); 2] = [(0, 0), (1, 2)];

pub struct Small {
    pub hands: Vec<Cards>,
    pub menus: Menus,
    pub trees: HashMap<usize, Tree>,
    pub chance: Vec<u64>,
}

impl Small {
    pub fn game(&self) -> Game<'_> {
        Game {
            menus: &self.menus,
            chance: &self.chance,
            mass: self.chance.iter().sum(),
        }
    }

    /// Sum `f(state, p, d)` times the deal's weight over every deal.
    pub fn over_deals(&self, f: impl Fn(State, usize, usize) -> i128) -> i128 {
        let mut total = 0i128;
        for p in 0..1820 {
            for d in 0..1820 {
                let w = self.chance[p * 1820 + d];
                if w != 0 {
                    total += i128::from(w) * f(State::new(self.hands[p], self.hands[d]), p, d);
                }
            }
        }
        total
    }
}

pub struct SmallTrees<'a>(pub &'a HashMap<usize, Tree>);

impl Trees for SmallTrees<'_> {
    fn tree(&self, p: usize) -> Tree {
        match self.0.get(&p) {
            Some(t) => Tree {
                roots: t.roots.clone(),
                nodes: t.nodes.clone(),
                edges: t.edges.clone(),
            },
            None => Tree {
                roots: vec![u32::MAX; 1820],
                nodes: Vec::new(),
                edges: Vec::new(),
            },
        }
    }
}

pub fn index(hands: &[Cards], h: Cards) -> usize {
    hands.iter().position(|x| *x == h).unwrap()
}

pub fn small() -> Small {
    build_small(|i, j| (3 + i + 2 * j) as u64)
}

pub fn matched() -> Small {
    build_small(|i, j| {
        if MATCHED.contains(&(i, j)) {
            5 + i as u64
        } else {
            0
        }
    })
}

pub fn build_small(weight: impl Fn(usize, usize) -> u64) -> Small {
    let hands = canonical();
    let ps: Vec<usize> = PONES.iter().map(|&h| index(&hands, h)).collect();
    let ds: Vec<usize> = DEALERS.iter().map(|&h| index(&hands, h)).collect();
    let files: Vec<Vec<u8>> = (0..FILES)
        .map(|k| {
            if ps.contains(&k) || (k >= 1820 && ds.contains(&(k - 1820))) {
                // Restrict collection to the small game's opponents by
                // building full files: the extra records are never reached.
                menus::build(k, &hands)
            } else {
                Vec::new()
            }
        })
        .collect();
    let menus = Menus::from_files(&files);
    let mut trees = HashMap::new();
    let mut chance = vec![0u64; 1820 * 1820];
    for (i, &p) in ps.iter().enumerate() {
        trees.insert(p, Tree::build_some(&menus, &hands, p, |d| ds.contains(&d)));
        for (j, &d) in ds.iter().enumerate() {
            if feasible(&hands[p], &hands[d]) {
                chance[p * 1820 + d] = weight(i, j);
            }
        }
    }
    Small {
        hands,
        menus,
        trees,
        chance,
    }
}

pub fn solve(s: &Small, threads: usize, iterations: u32) -> Solver {
    let game = s.game();
    let n = usize::try_from(s.menus.actions).unwrap();
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(threads)
        .build()
        .unwrap();
    pool.install(|| {
        let mut solver = Solver::new(&game, vec![0.0; n], vec![0.0; n]);
        for it in 1..=iterations {
            solver.update(&game, &SmallTrees(&s.trees), 0, it);
            solver.update(&game, &SmallTrees(&s.trees), 1, it);
        }
        solver
    })
}

pub fn bits(v: &[f64]) -> Vec<u64> {
    v.iter().map(|x| x.to_bits()).collect()
}

/// The global menu index of the decision `state` is at, found by its public
/// history in the deciding seat's menu file, never through trees.
pub fn info_of(s: &Small, state: &State, p: usize, d: usize) -> usize {
    let k = state.next * 1820 + if state.next == 1 { d } else { p };
    let range = s.menus.starts[k] as usize..s.menus.starts[k + 1] as usize;
    let key = state.history_key();
    range
        .clone()
        .find(|&i| s.menus.history[i] == key)
        .expect("info")
}

/// Whether `state` is at a real decision: an optional choice among the
/// seat's first three cards.
pub fn decides(state: &State) -> bool {
    state.legal().len() >= 2 && 4 - state.n[state.next] < 3
}
