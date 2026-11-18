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

    /// Sum `per_deal(state, pone_hand, dealer_hand)` times the deal's weight over every deal.
    pub fn over_deals(&self, per_deal: impl Fn(State, usize, usize) -> i128) -> i128 {
        let mut total = 0i128;
        for pone_hand in 0..1820 {
            for dealer_hand in 0..1820 {
                let deal_weight = self.chance[pone_hand * 1820 + dealer_hand];
                if deal_weight != 0 {
                    total += i128::from(deal_weight)
                        * per_deal(
                            State::new(self.hands[pone_hand], self.hands[dealer_hand]),
                            pone_hand,
                            dealer_hand,
                        );
                }
            }
        }
        total
    }
}

pub struct SmallTrees<'a>(pub &'a HashMap<usize, Tree>);

impl Trees for SmallTrees<'_> {
    fn tree(&self, pone_hand: usize) -> Tree {
        match self.0.get(&pone_hand) {
            Some(tree) => Tree {
                roots: tree.roots.clone(),
                nodes: tree.nodes.clone(),
                edges: tree.edges.clone(),
            },
            None => Tree {
                roots: vec![u32::MAX; 1820],
                nodes: Vec::new(),
                edges: Vec::new(),
            },
        }
    }
}

pub fn index(hands: &[Cards], hand: Cards) -> usize {
    hands
        .iter()
        .position(|candidate| *candidate == hand)
        .unwrap()
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
    let pone_hands: Vec<usize> = PONES.iter().map(|&hand| index(&hands, hand)).collect();
    let dealer_hands: Vec<usize> = DEALERS.iter().map(|&hand| index(&hands, hand)).collect();
    let files: Vec<Vec<u8>> = (0..FILES)
        .map(|file_index| {
            if pone_hands.contains(&file_index)
                || (file_index >= 1820 && dealer_hands.contains(&(file_index - 1820)))
            {
                // Restrict collection to the small game's opponents by
                // building full files: the extra records are never reached.
                menus::build(file_index, &hands)
            } else {
                Vec::new()
            }
        })
        .collect();
    let menus = Menus::from_files(&files);
    let mut trees = HashMap::new();
    let mut chance = vec![0u64; 1820 * 1820];
    for (i, &pone_hand) in pone_hands.iter().enumerate() {
        trees.insert(
            pone_hand,
            Tree::build_some(&menus, &hands, pone_hand, |dealer_hand| {
                dealer_hands.contains(&dealer_hand)
            }),
        );
        for (j, &dealer_hand) in dealer_hands.iter().enumerate() {
            if feasible(&hands[pone_hand], &hands[dealer_hand]) {
                chance[pone_hand * 1820 + dealer_hand] = weight(i, j);
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

pub fn solve(small_game: &Small, threads: usize, iterations: u32) -> Solver {
    let game = small_game.game();
    let action_count = usize::try_from(small_game.menus.actions).unwrap();
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(threads)
        .build()
        .unwrap();
    pool.install(|| {
        let mut solver = Solver::new(&game, vec![0.0; action_count], vec![0.0; action_count]);
        for it in 1..=iterations {
            solver.update(&game, &SmallTrees(&small_game.trees), 0, it);
            solver.update(&game, &SmallTrees(&small_game.trees), 1, it);
        }
        solver
    })
}

pub fn bits(values: &[f64]) -> Vec<u64> {
    values.iter().map(|value| value.to_bits()).collect()
}

/// The global menu index of the decision `state` is at, found by its public
/// history in the deciding seat's menu file, never through trees.
pub fn info_of(small_game: &Small, state: &State, pone_hand: usize, dealer_hand: usize) -> usize {
    let file_index = state.next * 1820
        + if state.next == 1 {
            dealer_hand
        } else {
            pone_hand
        };
    let range = small_game.menus.starts[file_index] as usize
        ..small_game.menus.starts[file_index + 1] as usize;
    let key = state.history_key();
    range
        .clone()
        .find(|&menu_index| small_game.menus.history[menu_index] == key)
        .expect("info")
}

/// Whether `state` is at a real decision: an optional choice among the
/// seat's first three cards.
pub fn decides(state: &State) -> bool {
    state.legal().len() >= 2 && 4 - state.cards_left[state.next] < 3
}
