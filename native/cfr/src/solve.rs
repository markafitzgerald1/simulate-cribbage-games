//! Full-width alternating CFR+ with linear averaging, the 1,000-unit rounded
//! policy and its exact integer certificate, mirroring `walk`, `update`,
//! `rounded`, `joint_value`, `response`, `br` and `certificate` in the
//! research `stream.cpp`.
//!
//! # Determinism
//!
//! Floating-point results depend on the order of additions, so the parallel
//! schedule is chosen so that every accumulator slot receives its terms in
//! exactly the serial C++ order, whatever the thread count:
//!
//! * In Pone's pass every counterfactual value written belongs to an
//!   information set of the Pone hand `p` whose tree is being walked, so
//!   Pone hands run in parallel, each over Dealer hands in order.
//! * In Dealer's pass the slots belong to the Dealer hand `d`, and the serial
//!   order is Pone hand, then Dealer hand. Pone hands therefore stay
//!   sequential and Dealer hands run in parallel within each.
//! * Regret, strategy and average updates are per menu, and a menu's parent
//!   chain stays inside its own file, so files update in parallel.
//!
//! No reduction crosses threads. Certificate arithmetic is exact `i128`, so
//! its order does not matter. Rust never fuses `a * b + c` into a
//! multiply-add unless asked, matching the research build's
//! `-ffp-contract=off`.

use super::menus::NIL;
use super::trees::{Menus, Node, TAG, Tree, leaf};
use rayon::prelude::*;
use std::path::Path;

/// Probability units per menu in the rounded policy.
pub const Q: u32 = 1000;

/// Everything the solver reads, kept in memory.
pub struct Game<'a> {
    pub menus: &'a Menus,
    /// 1,820 x 1,820 joint deal weights, Pone hand major.
    pub chance: &'a [u64],
    pub mass: u64,
}

impl Game<'_> {
    fn weight(&self, p: usize, d: usize) -> u64 {
        self.chance[p * 1820 + d]
    }

    /// Action-slot range of menu file `k`.
    fn slots(&self, k: usize) -> std::ops::Range<usize> {
        let m = self.menus;
        let at = |i: u32| {
            let i = i as usize;
            usize::try_from(if i < m.len() {
                u64::from(m.offset[i])
            } else {
                m.actions
            })
            .expect("action count")
        };
        at(m.starts[k])..at(m.starts[k + 1])
    }
}

/// Split `values` into the action-slot slices of files `first..first+1820`.
fn file_slices<'v, T>(game: &Game, values: &'v mut [T], first: usize) -> Vec<&'v mut [T]> {
    let base = game.slots(first).start;
    let mut rest = &mut values[base..game.slots(first + 1819).end];
    let mut out = Vec::with_capacity(1820);
    for k in first..first + 1820 {
        let (head, tail) = rest.split_at_mut(game.slots(k).len());
        out.push(head);
        rest = tail;
    }
    out
}

/// Counterfactual walk; adds `role`'s values into `out`, whose first element
/// is action slot `base`. Returns the node value for Pone.
#[allow(clippy::too_many_arguments)]
fn walk(
    m: &Menus,
    sigma: &[f64],
    t: &Tree,
    out: &mut [f64],
    base: usize,
    id: u32,
    p: f64,
    d: f64,
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
    } = t.node(m, id);
    let mut total = 0.0;
    for a in 0..width {
        let prob = sigma[off + a];
        if actor != role && prob == 0.0 {
            continue;
        }
        let child = walk(
            m,
            sigma,
            t,
            out,
            base,
            t.edges[first + a],
            p * if actor == 0 { prob } else { 1.0 },
            d * if actor == 1 { prob } else { 1.0 },
            role,
            weight,
        );
        total += prob * child;
        if actor == role {
            let reach = if role == 1 { p } else { d };
            let sign = if role == 1 { -1.0 } else { 1.0 };
            out[off + a - base] += weight * reach * child * sign;
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
    fn tree(&self, p: usize) -> Tree;
}

/// Trees read from `dir/trees/{p}.bin` on demand.
pub struct TreeFiles<'a>(pub &'a Path);

impl Trees for TreeFiles<'_> {
    fn tree(&self, p: usize) -> Tree {
        Tree::read(self.0, p).expect("Tree read")
    }
}

fn strategy(regret: &[f64], sigma: &mut [f64]) {
    let total = regret.iter().fold(0.0, |s, &r| s + r);
    for (s, &r) in sigma.iter_mut().zip(regret) {
        *s = if total == 0.0 {
            1.0 / regret.len() as f64
        } else {
            r / total
        };
    }
}

impl Solver {
    /// Start from saved regrets and averages (zeros for a fresh solve).
    pub fn new(game: &Game, regret: Vec<f64>, average: Vec<f64>) -> Solver {
        let n = usize::try_from(game.menus.actions).expect("action count");
        assert!(regret.len() == n && average.len() == n, "Checkpoint size");
        let mut sigma = vec![0.0; n];
        let m = game.menus;
        for i in 0..m.len() {
            let r = m.offset[i] as usize..m.offset[i] as usize + usize::from(m.width[i]);
            strategy(&regret[r.clone()], &mut sigma[r]);
        }
        Solver {
            regret,
            average,
            sigma,
            values: vec![0.0; n],
        }
    }

    fn values_for(&mut self, game: &Game, trees: &dyn Trees, role: u8) {
        self.values.fill(0.0);
        let (m, sigma) = (game.menus, &self.sigma);
        let visit = |t: &Tree, p: usize, d: usize, out: &mut [f64], base: usize| {
            let w = game.weight(p, d);
            if w != 0 {
                assert!(t.roots[d] != NIL, "Chance mismatch");
                let weight = w as f64 / game.mass as f64;
                walk(m, sigma, t, out, base, t.roots[d], 1.0, 1.0, role, weight);
            }
        };
        if role == 0 {
            let slices = file_slices(game, &mut self.values, 0);
            slices.into_par_iter().enumerate().for_each(|(p, out)| {
                let t = trees.tree(p);
                let base = game.slots(p).start;
                for d in 0..1820 {
                    visit(&t, p, d, out, base);
                }
            });
        } else {
            let mut slices = file_slices(game, &mut self.values, 1820);
            let mut next = Some(trees.tree(0));
            for p in 0..1820 {
                let t = next.take().expect("tree");
                let mut work = || {
                    slices.par_iter_mut().enumerate().for_each(|(d, out)| {
                        visit(&t, p, d, out, game.slots(1820 + d).start);
                    });
                };
                if p + 1 < 1820 {
                    let ((), loaded) = rayon::join(work, || trees.tree(p + 1));
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
        let m = game.menus;
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
                let k = first + i;
                let lo = game.slots(k).start;
                let menus = m.starts[k] as usize..m.starts[k + 1] as usize;
                for j in menus.clone() {
                    let r = m.offset[j] as usize - lo
                        ..m.offset[j] as usize - lo + usize::from(m.width[j]);
                    let vals = &values[r.start + lo - base..r.end + lo - base];
                    let mut v = 0.0;
                    for (s, x) in sigma[r.clone()].iter().zip(vals) {
                        v += s * x;
                    }
                    for (g, x) in regret[r.clone()].iter_mut().zip(vals) {
                        let next = *g + x - v;
                        *g = if 0.0 < next { next } else { 0.0 };
                    }
                    strategy(&regret[r.clone()], &mut sigma[r]);
                }
                for j in menus {
                    let mut reach = 1.0;
                    let (mut parent, mut a) = (m.parent[j], m.parent_action[j]);
                    while parent != NIL {
                        let q = parent as usize;
                        reach *= sigma[m.offset[q] as usize - lo + usize::from(a)];
                        a = m.parent_action[q];
                        parent = m.parent[q];
                    }
                    let o = m.offset[j] as usize - lo;
                    for x in o..o + usize::from(m.width[j]) {
                        average[x] += it * reach * sigma[x];
                    }
                }
            });
    }

    /// The average strategy rounded to `Q` units per menu: floor, then hand
    /// the remaining units to the largest remainders, ties to the lower index.
    pub fn rounded(&self, game: &Game) -> Vec<u16> {
        let m = game.menus;
        let mut s = vec![0u16; usize::try_from(m.actions).expect("action count")];
        for i in 0..m.len() {
            let (off, w) = (m.offset[i] as usize, usize::from(m.width[i]));
            let avg = &self.average[off..off + w];
            let total = avg.iter().fold(0.0, |t, &x| t + x);
            let mut used = 0u32;
            let mut rem = [(0.0f64, 0usize); 4];
            for a in 0..w {
                let x = if total == 0.0 {
                    f64::from(Q) / w as f64
                } else {
                    f64::from(Q) * avg[a] / total
                };
                #[expect(
                    clippy::cast_possible_truncation,
                    clippy::cast_sign_loss,
                    reason = "x lies in [0, Q], so its floor fits a u16"
                )]
                let floor = x.floor() as u16;
                s[off + a] = floor;
                used += u32::from(floor);
                rem[a] = (-(x - f64::from(floor)), a);
            }
            rem[..w].sort_by(|x, y| x.0.partial_cmp(&y.0).expect("NaN").then(x.1.cmp(&y.1)));
            assert!(
                used <= Q && Q - used <= u32::try_from(w).expect("width"),
                "Rounding"
            );
            for &(_, a) in &rem[..(Q - used) as usize] {
                s[off + a] += 1;
            }
        }
        s
    }
}

/// Exact integer values of a rounded policy.
pub struct Certificate {
    pub joint: i128,
    pub upper: i128,
    pub lower: i128,
    /// `mass * Q^3`; the joint value's denominator is this times `Q^3`.
    pub denominator: i128,
}

impl Certificate {
    /// Exposure in points: half the gap between the two best responses.
    pub fn exposure(&self) -> f64 {
        (self.upper - self.lower) as f64 / (2.0 * self.denominator as f64)
    }

    /// The research stopping rule: exposure at most 0.001 points.
    pub fn converged(&self, mass: u64) -> bool {
        let q3 = i128::from(Q).pow(3);
        (self.upper - self.lower) * 1000 <= 2 * i128::from(mass) * q3
    }
}

fn joint_value(m: &Menus, t: &Tree, id: u32, s: &[u16], depth: u32) -> i128 {
    if id & TAG != 0 {
        let mut v = i128::from(leaf(id));
        for _ in depth..6 {
            v *= i128::from(Q);
        }
        return v;
    }
    let Node {
        first, off, width, ..
    } = t.node(m, id);
    let mut v = 0i128;
    for a in 0..width {
        let prob = s[off + a];
        if prob != 0 {
            v += i128::from(prob) * joint_value(m, t, t.edges[first + a], s, depth + 1);
        }
    }
    v
}

struct Response<'a> {
    m: &'a Menus,
    s: &'a [u16],
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
        t: &Tree,
        id: u32,
        weight: i128,
        current: u32,
        action: usize,
        vals: &mut [i128],
        base: usize,
    ) -> i128 {
        let m = self.m;
        if id & TAG != 0 {
            let v = weight * i128::from(leaf(id)) * if self.role == 1 { -1 } else { 1 };
            if current != NIL {
                vals[m.offset[current as usize] as usize + action - base] += v;
                return 0;
            }
            return v;
        }
        let Node {
            info,
            first,
            off,
            actor,
            width,
        } = t.node(m, id);
        let card = i32::from(m.stage[info] / 2);
        let mut out = 0;
        for a in 0..width {
            if actor == self.role && card > self.stage && a != usize::from(self.choice[info]) {
                continue;
            }
            let (mut w, mut selected, mut act) = (weight, current, action);
            if actor != self.role {
                let prob = self.s[off + a];
                if prob == 0 {
                    continue;
                }
                if u32::from(prob) != Q {
                    assert!(w % i128::from(Q) == 0, "Denominator exhausted");
                    w = w / i128::from(Q) * i128::from(prob);
                }
            } else if card == self.stage {
                selected = u32::try_from(info).expect("menu index");
                act = a;
            }
            out += self.walk(t, t.edges[first + a], w, selected, act, vals, base);
        }
        out
    }
}

/// Exact value of `role`'s best response to policy `s`, chosen card by card
/// from the last decision back to the first.
fn best_response(game: &Game, trees: &dyn Trees, s: &[u16], role: u8) -> i128 {
    let m = game.menus;
    let mut choice = vec![0u8; m.len()];
    let mut vals = vec![0i128; usize::try_from(m.actions).expect("action count")];
    let q3 = i128::from(Q).pow(3);
    let first = usize::from(role) * 1820;
    for stage in (0..=2).rev() {
        vals.fill(0);
        {
            let r = Response {
                m,
                s,
                choice: &choice,
                role,
                stage,
            };
            let mut slices = file_slices(game, &mut vals, first);
            let root = |t: &Tree, p: usize, d: usize, out: &mut [i128], base: usize| {
                let w = game.weight(p, d);
                if w != 0 {
                    r.walk(t, t.roots[d], i128::from(w) * q3, NIL, 0, out, base);
                }
            };
            if role == 0 {
                slices.into_par_iter().enumerate().for_each(|(p, out)| {
                    let t = trees.tree(p);
                    for d in 0..1820 {
                        root(&t, p, d, out, game.slots(p).start);
                    }
                });
            } else {
                for p in 0..1820 {
                    let t = trees.tree(p);
                    slices.par_iter_mut().enumerate().for_each(|(d, out)| {
                        root(&t, p, d, out, game.slots(1820 + d).start);
                    });
                }
            }
        }
        let own = m.starts[first] as usize..m.starts[first + 1820] as usize;
        for (i, slot) in own.clone().zip(&mut choice[own]) {
            if i32::from(m.stage[i] / 2) == stage {
                let off = m.offset[i] as usize;
                let mut best = 0;
                for a in 1..usize::from(m.width[i]) {
                    if vals[off + a] > vals[off + best] {
                        best = a;
                    }
                }
                *slot = u8::try_from(best).expect("width");
            }
        }
    }
    drop(vals);
    let r = Response {
        m,
        s,
        choice: &choice,
        role,
        stage: -1,
    };
    let out: i128 = (0..1820)
        .into_par_iter()
        .map(|p| {
            let t = trees.tree(p);
            let mut total = 0;
            for d in 0..1820 {
                let w = game.weight(p, d);
                if w != 0 {
                    total += r.walk(&t, t.roots[d], i128::from(w) * q3, NIL, 0, &mut [], 0);
                }
            }
            total
        })
        .sum();
    if role == 1 { -out } else { out }
}

/// Exact joint value and both best-response values of the rounded policy.
pub fn certificate(game: &Game, trees: &dyn Trees, s: &[u16]) -> Certificate {
    let q = i128::from(Q);
    assert!(
        i128::from(game.mass) <= ((1i128 << 125) - 1) / (128 * q * q * q * q * q * q),
        "Bound"
    );
    let joint: i128 = (0..1820)
        .into_par_iter()
        .map(|p| {
            let t = trees.tree(p);
            let mut j = 0;
            for d in 0..1820 {
                let w = game.weight(p, d);
                if w != 0 {
                    j += i128::from(w) * joint_value(game.menus, &t, t.roots[d], s, 0);
                }
            }
            j
        })
        .sum();
    let upper = best_response(game, trees, s, 0);
    let lower = best_response(game, trees, s, 1);
    Certificate {
        joint,
        upper,
        lower,
        denominator: i128::from(game.mass) * q * q * q,
    }
}
