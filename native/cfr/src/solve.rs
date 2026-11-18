//! Full-width alternating CFR+ with linear averaging, the 1,000-unit rounded
//! policy and its exact integer certificate.
//!
//! # Determinism
//!
//! Floating-point results depend on the order of additions, so the parallel
//! schedule is chosen so that every accumulator slot receives its terms in
//! exactly the serial order, whatever the thread count:
//!
//! * In Pone's pass every counterfactual value written belongs to an
//!   information set of the Pone hand `pone_hand` whose tree is being walked, so
//!   Pone hands run in parallel, each over Dealer hands in order.
//! * In Dealer's pass the slots belong to the Dealer hand `d`, and the serial
//!   order is Pone hand, then Dealer hand. Pone hands therefore stay
//!   sequential and Dealer hands run in parallel within each.
//! * Regret, strategy and average updates are per menu, and a menu's parent
//!   chain stays inside its own file, so files update in parallel.
//!
//! No reduction crosses threads. Certificate arithmetic is exact `i128`, so
//! its order does not matter. Rust never fuses `a * b + c` into a
//! multiply-add unless asked, so no fused multiply-add enters the result.

use super::menus::NIL;
use super::trees::{Menus, Node, TAG, Tree, leaf};
use rayon::prelude::*;
use std::path::Path;

/// Probability units per menu in the rounded policy.
pub const POLICY_UNITS: u32 = 1000;

/// Everything the solver reads, kept in memory.
pub struct Game<'a> {
    pub menus: &'a Menus,
    /// 1,820 x 1,820 joint deal weights, Pone hand major.
    pub chance: &'a [u64],
    pub mass: u64,
}

impl Game<'_> {
    fn weight(&self, pone_hand: usize, dealer_hand: usize) -> u64 {
        self.chance[pone_hand * 1820 + dealer_hand]
    }

    /// Action-slot range of menu file `k`.
    fn slots(&self, file_index: usize) -> std::ops::Range<usize> {
        let menus = self.menus;
        let at = |menu_index: u32| {
            let menu_index = menu_index as usize;
            usize::try_from(if menu_index < menus.len() {
                u64::from(menus.offset[menu_index])
            } else {
                menus.actions
            })
            .expect("action count")
        };
        at(menus.starts[file_index])..at(menus.starts[file_index + 1])
    }
}

/// Split `values` into the action-slot slices of files `first..first+1820`.
fn file_slices<'v, T>(game: &Game, values: &'v mut [T], first: usize) -> Vec<&'v mut [T]> {
    let base = game.slots(first).start;
    let mut rest = &mut values[base..game.slots(first + 1819).end];
    let mut out = Vec::with_capacity(1820);
    for file_index in first..first + 1820 {
        let (head, tail) = rest.split_at_mut(game.slots(file_index).len());
        out.push(head);
        rest = tail;
    }
    out
}

/// Counterfactual walk; adds `role`'s values into `out`, whose first element
/// is action slot `base`. Returns the node value for Pone.
#[allow(clippy::too_many_arguments)]
fn walk(
    menus: &Menus,
    sigma: &[f64],
    tree: &Tree,
    out: &mut [f64],
    base: usize,
    id: u32,
    pone_reach: f64,
    dealer_reach: f64,
    role: u8,
    weight: f64,
) -> f64 {
    if id & TAG != 0 {
        return f64::from(leaf(id));
    }
    let Node {
        first,
        off,
        actor,
        width,
        ..
    } = tree.node(menus, id);
    let mut total = 0.0;
    for action in 0..width {
        let prob = sigma[off + action];
        if actor != role && prob == 0.0 {
            continue;
        }
        let child = walk(
            menus,
            sigma,
            tree,
            out,
            base,
            tree.edges[first + action],
            pone_reach * if actor == 0 { prob } else { 1.0 },
            dealer_reach * if actor == 1 { prob } else { 1.0 },
            role,
            weight,
        );
        total += prob * child;
        if actor == role {
            let reach = if role == 1 { pone_reach } else { dealer_reach };
            let sign = if role == 1 { -1.0 } else { 1.0 };
            out[off + action - base] += weight * reach * child * sign;
        }
    }
    total
}

/// Solver state: cumulative positive regrets, current strategy and linear
/// average, one entry per action slot.
pub struct Solver {
    pub regret: Vec<f64>,
    pub average: Vec<f64>,
    pub sigma: Vec<f64>,
    values: Vec<f64>,
}

/// Source of trees for Pone hand `p`.
pub trait Trees: Sync {
    fn tree(&self, pone_hand: usize) -> Tree;
}

/// Trees read from `dir/trees/{p}.bin` on demand.
pub struct TreeFiles<'a>(pub &'a Path);

impl Trees for TreeFiles<'_> {
    fn tree(&self, pone_hand: usize) -> Tree {
        Tree::read(self.0, pone_hand).expect("Tree read")
    }
}

fn strategy(regret: &[f64], sigma: &mut [f64]) {
    let total = regret
        .iter()
        .fold(0.0, |sum, &positive_regret| sum + positive_regret);
    for (probability, &positive_regret) in sigma.iter_mut().zip(regret) {
        *probability = if total == 0.0 {
            1.0 / regret.len() as f64
        } else {
            positive_regret / total
        };
    }
}

impl Solver {
    /// Start from saved regrets and averages (zeros for a fresh solve).
    pub fn new(game: &Game, regret: Vec<f64>, average: Vec<f64>) -> Solver {
        let action_count = usize::try_from(game.menus.actions).expect("action count");
        assert!(
            regret.len() == action_count && average.len() == action_count,
            "Checkpoint size"
        );
        let mut sigma = vec![0.0; action_count];
        let menus = game.menus;
        for i in 0..menus.len() {
            let slot_range =
                menus.offset[i] as usize..menus.offset[i] as usize + usize::from(menus.width[i]);
            strategy(&regret[slot_range.clone()], &mut sigma[slot_range]);
        }
        Solver {
            regret,
            average,
            sigma,
            values: vec![0.0; action_count],
        }
    }

    fn values_for(&mut self, game: &Game, trees: &dyn Trees, role: u8) {
        self.values.fill(0.0);
        let (menus, sigma) = (game.menus, &self.sigma);
        let visit =
            |tree: &Tree, pone_hand: usize, dealer_hand: usize, out: &mut [f64], base: usize| {
                let deal_weight = game.weight(pone_hand, dealer_hand);
                if deal_weight != 0 {
                    assert!(tree.roots[dealer_hand] != NIL, "Chance mismatch");
                    let weight = deal_weight as f64 / game.mass as f64;
                    walk(
                        menus,
                        sigma,
                        tree,
                        out,
                        base,
                        tree.roots[dealer_hand],
                        1.0,
                        1.0,
                        role,
                        weight,
                    );
                }
            };
        if role == 0 {
            let slices = file_slices(game, &mut self.values, 0);
            slices
                .into_par_iter()
                .enumerate()
                .for_each(|(pone_hand, out)| {
                    let tree = trees.tree(pone_hand);
                    let base = game.slots(pone_hand).start;
                    for dealer_hand in 0..1820 {
                        visit(&tree, pone_hand, dealer_hand, out, base);
                    }
                });
        } else {
            let mut slices = file_slices(game, &mut self.values, 1820);
            let mut next = Some(trees.tree(0));
            for pone_hand in 0..1820 {
                let tree = next.take().expect("tree");
                let mut work = || {
                    slices
                        .par_iter_mut()
                        .enumerate()
                        .for_each(|(dealer_hand, out)| {
                            visit(
                                &tree,
                                pone_hand,
                                dealer_hand,
                                out,
                                game.slots(1820 + dealer_hand).start,
                            );
                        });
                };
                if pone_hand + 1 < 1820 {
                    let ((), loaded) = rayon::join(work, || trees.tree(pone_hand + 1));
                    next = Some(loaded);
                } else {
                    work();
                }
            }
        }
    }

    /// One CFR+ half-iteration for `role` (0 Pone, 1 Dealer).
    pub fn update(&mut self, game: &Game, trees: &dyn Trees, role: u8, iteration: u32) {
        self.values_for(game, trees, role);
        let menus = game.menus;
        let first = usize::from(role) * 1820;
        let base = game.slots(first).start;
        let end = game.slots(first + 1819).end;
        let mut regret = file_slices(game, &mut self.regret, first);
        let mut sigma = file_slices(game, &mut self.sigma, first);
        let mut average = file_slices(game, &mut self.average, first);
        let values = &self.values[base..end];
        let it = f64::from(iteration);
        regret
            .par_iter_mut()
            .zip(sigma.par_iter_mut())
            .zip(average.par_iter_mut())
            .enumerate()
            .for_each(|(i, ((regret, sigma), average))| {
                let file_index = first + i;
                let lo = game.slots(file_index).start;
                let menu_range =
                    menus.starts[file_index] as usize..menus.starts[file_index + 1] as usize;
                for j in menu_range.clone() {
                    let action_slots = menus.offset[j] as usize - lo
                        ..menus.offset[j] as usize - lo + usize::from(menus.width[j]);
                    let vals =
                        &values[action_slots.start + lo - base..action_slots.end + lo - base];
                    let mut value = 0.0;
                    for (probability, action_value) in sigma[action_slots.clone()].iter().zip(vals)
                    {
                        value += probability * action_value;
                    }
                    for (regret_entry, action_value) in
                        regret[action_slots.clone()].iter_mut().zip(vals)
                    {
                        let next = *regret_entry + action_value - value;
                        *regret_entry = if 0.0 < next { next } else { 0.0 };
                    }
                    strategy(&regret[action_slots.clone()], &mut sigma[action_slots]);
                }
                for j in menu_range {
                    let mut reach = 1.0;
                    let (mut parent, mut parent_action) = (menus.parent[j], menus.parent_action[j]);
                    while parent != NIL {
                        let parent_index = parent as usize;
                        reach *= sigma
                            [menus.offset[parent_index] as usize - lo + usize::from(parent_action)];
                        parent_action = menus.parent_action[parent_index];
                        parent = menus.parent[parent_index];
                    }
                    let action_start = menus.offset[j] as usize - lo;
                    for slot in action_start..action_start + usize::from(menus.width[j]) {
                        average[slot] += it * reach * sigma[slot];
                    }
                }
            });
    }

    /// The average strategy rounded to `POLICY_UNITS` units per menu: floor, then hand
    /// the remaining units to the largest remainders, ties to the lower index.
    pub fn rounded(&self, game: &Game) -> Vec<u16> {
        let menus = game.menus;
        let mut rounded = vec![0u16; usize::try_from(menus.actions).expect("action count")];
        for i in 0..menus.len() {
            let (off, width) = (menus.offset[i] as usize, usize::from(menus.width[i]));
            let avg = &self.average[off..off + width];
            let total = avg
                .iter()
                .fold(0.0, |sum, &average_weight| sum + average_weight);
            let mut used = 0u32;
            let mut rem = [(0.0f64, 0usize); 4];
            for action in 0..width {
                let scaled = if total == 0.0 {
                    f64::from(POLICY_UNITS) / width as f64
                } else {
                    f64::from(POLICY_UNITS) * avg[action] / total
                };
                #[expect(
                    clippy::cast_possible_truncation,
                    clippy::cast_sign_loss,
                    reason = "scaled lies in [0, POLICY_UNITS], so its floor fits a u16"
                )]
                let floor = scaled.floor() as u16;
                rounded[off + action] = floor;
                used += u32::from(floor);
                rem[action] = (-(scaled - f64::from(floor)), action);
            }
            rem[..width].sort_by(|left, right| {
                left.0
                    .partial_cmp(&right.0)
                    .expect("NaN")
                    .then(left.1.cmp(&right.1))
            });
            assert!(
                used <= POLICY_UNITS && POLICY_UNITS - used <= u32::try_from(width).expect("width"),
                "Rounding"
            );
            for &(_, action) in &rem[..(POLICY_UNITS - used) as usize] {
                rounded[off + action] += 1;
            }
        }
        rounded
    }
}

/// Exact integer values of a rounded policy.
pub struct Certificate {
    pub joint: i128,
    pub upper: i128,
    pub lower: i128,
    /// `mass * POLICY_UNITS^3`; the joint value's denominator is this times that cube.
    pub denominator: i128,
}

impl Certificate {
    /// Exposure in points: half the gap between the two best responses.
    pub fn exposure(&self) -> f64 {
        (self.upper - self.lower) as f64 / (2.0 * self.denominator as f64)
    }

    /// The stopping rule: exposure at most 0.001 points, so neither player
    /// can gain more than 0.002 points by deviating.
    pub fn converged(&self, mass: u64) -> bool {
        let units_cubed = i128::from(POLICY_UNITS).pow(3);
        (self.upper - self.lower) * 1000 <= 2 * i128::from(mass) * units_cubed
    }
}

fn joint_value(menus: &Menus, tree: &Tree, id: u32, policy: &[u16], depth: u32) -> i128 {
    if id & TAG != 0 {
        let mut value = i128::from(leaf(id));
        for _ in depth..6 {
            value *= i128::from(POLICY_UNITS);
        }
        return value;
    }
    let Node {
        first, off, width, ..
    } = tree.node(menus, id);
    let mut value = 0i128;
    for action in 0..width {
        let prob = policy[off + action];
        if prob != 0 {
            value += i128::from(prob)
                * joint_value(menus, tree, tree.edges[first + action], policy, depth + 1);
        }
    }
    value
}

struct Response<'a> {
    menus: &'a Menus,
    policy: &'a [u16],
    choice: &'a [u8],
    role: u8,
    stage: i32,
}

impl Response<'_> {
    /// Adds `role`'s payoffs into `vals` (slots from `base`) at the action
    /// chosen at depth `stage`, or into the returned total when `stage` is -1.
    #[allow(clippy::too_many_arguments)]
    fn walk(
        &self,
        tree: &Tree,
        id: u32,
        weight: i128,
        current: u32,
        action: usize,
        vals: &mut [i128],
        base: usize,
    ) -> i128 {
        let menus = self.menus;
        if id & TAG != 0 {
            let payoff = weight * i128::from(leaf(id)) * if self.role == 1 { -1 } else { 1 };
            if current != NIL {
                vals[menus.offset[current as usize] as usize + action - base] += payoff;
                return 0;
            }
            return payoff;
        }
        let Node {
            info,
            first,
            off,
            actor,
            width,
        } = tree.node(menus, id);
        let card = i32::from(menus.stage[info] / 2);
        let mut out = 0;
        for action_index in 0..width {
            if actor == self.role
                && card > self.stage
                && action_index != usize::from(self.choice[info])
            {
                continue;
            }
            let (mut scaled_weight, mut selected, mut selected_action) = (weight, current, action);
            if actor != self.role {
                let prob = self.policy[off + action_index];
                if prob == 0 {
                    continue;
                }
                if u32::from(prob) != POLICY_UNITS {
                    assert!(
                        scaled_weight % i128::from(POLICY_UNITS) == 0,
                        "Denominator exhausted"
                    );
                    scaled_weight = scaled_weight / i128::from(POLICY_UNITS) * i128::from(prob);
                }
            } else if card == self.stage {
                selected = u32::try_from(info).expect("menu index");
                selected_action = action_index;
            }
            out += self.walk(
                tree,
                tree.edges[first + action_index],
                scaled_weight,
                selected,
                selected_action,
                vals,
                base,
            );
        }
        out
    }
}

/// Exact value of `role`'s best response to policy `s`, chosen card by card
/// from the last decision back to the first.
fn best_response(game: &Game, trees: &dyn Trees, policy: &[u16], role: u8) -> i128 {
    let menus = game.menus;
    let mut choice = vec![0u8; menus.len()];
    let mut vals = vec![0i128; usize::try_from(menus.actions).expect("action count")];
    let units_cubed = i128::from(POLICY_UNITS).pow(3);
    let first = usize::from(role) * 1820;
    for stage in (0..=2).rev() {
        vals.fill(0);
        {
            let response = Response {
                menus,
                policy,
                choice: &choice,
                role,
                stage,
            };
            let mut slices = file_slices(game, &mut vals, first);
            let root = |tree: &Tree, pone: usize, dealer: usize, out: &mut [i128], base: usize| {
                let weight = game.weight(pone, dealer);
                if weight != 0 {
                    response.walk(
                        tree,
                        tree.roots[dealer],
                        i128::from(weight) * units_cubed,
                        NIL,
                        0,
                        out,
                        base,
                    );
                }
            };
            if role == 0 {
                slices.into_par_iter().enumerate().for_each(|(pone, out)| {
                    let tree = trees.tree(pone);
                    for dealer in 0..1820 {
                        root(&tree, pone, dealer, out, game.slots(pone).start);
                    }
                });
            } else {
                for pone in 0..1820 {
                    let tree = trees.tree(pone);
                    slices.par_iter_mut().enumerate().for_each(|(dealer, out)| {
                        root(&tree, pone, dealer, out, game.slots(1820 + dealer).start);
                    });
                }
            }
        }
        let own = menus.starts[first] as usize..menus.starts[first + 1820] as usize;
        for (i, slot) in own.clone().zip(&mut choice[own]) {
            if i32::from(menus.stage[i] / 2) == stage {
                let off = menus.offset[i] as usize;
                let mut best = 0;
                for action in 1..usize::from(menus.width[i]) {
                    if vals[off + action] > vals[off + best] {
                        best = action;
                    }
                }
                *slot = u8::try_from(best).expect("width");
            }
        }
    }
    drop(vals);
    let response = Response {
        menus,
        policy,
        choice: &choice,
        role,
        stage: -1,
    };
    let out: i128 = (0..1820)
        .into_par_iter()
        .map(|pone| {
            let tree = trees.tree(pone);
            let mut total = 0;
            for dealer in 0..1820 {
                let weight = game.weight(pone, dealer);
                if weight != 0 {
                    total += response.walk(
                        &tree,
                        tree.roots[dealer],
                        i128::from(weight) * units_cubed,
                        NIL,
                        0,
                        &mut [],
                        0,
                    );
                }
            }
            total
        })
        .sum();
    if role == 1 { -out } else { out }
}

/// The largest prior mass the certificate's exact `i128` arithmetic can
/// carry: products of a deal weight, a leaf margin and up to six policy unit
/// factors must stay below 2^125, so the limit is
/// `(2^125 - 1) / (128 * POLICY_UNITS^6)`, about 2^58.3. A unit test checks
/// this literal against that formula.
pub const MASS_LIMIT: u64 = 332_306_998_946_228_968;

/// Exact joint value and both best-response values of the rounded policy.
pub fn certificate(game: &Game, trees: &dyn Trees, policy: &[u16]) -> Certificate {
    assert!(game.mass <= MASS_LIMIT, "Bound");
    let units = i128::from(POLICY_UNITS);
    let joint: i128 = (0..1820)
        .into_par_iter()
        .map(|pone_hand| {
            let tree = trees.tree(pone_hand);
            let mut pone_total = 0;
            for dealer_hand in 0..1820 {
                let deal_weight = game.weight(pone_hand, dealer_hand);
                if deal_weight != 0 {
                    pone_total += i128::from(deal_weight)
                        * joint_value(game.menus, &tree, tree.roots[dealer_hand], policy, 0);
                }
            }
            pone_total
        })
        .sum();
    let upper = best_response(game, trees, policy, 0);
    let lower = best_response(game, trees, policy, 1);
    Certificate {
        joint,
        upper,
        lower,
        denominator: i128::from(game.mass) * units * units * units,
    }
}
