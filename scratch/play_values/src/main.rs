//! Spike for simulate-cribbage-games#260: per-play values for the first two
//! pegging plays of each seat, under the pinned CFR policy and its prior.
//!
//! `exact BUNDLE OUT` walks every deal's game tree once, in exact `i128`
//! arithmetic, and writes for every decision at stages 0..4 (each seat's
//! first and second card) the expected pegging margin, from the acting
//! seat's side, of each legal card when both seats follow the policy
//! afterwards. The value at a decision is conditioned on reaching it: deals
//! are weighted by the prior times the opponent's policy probabilities along
//! the way (the acting seat's own earlier choices are fixed by the history,
//! so they cancel). It is the counterfactual value the solver itself uses,
//! divided by the counterfactual reach.
//!
//! `mc BUNDLE TARGETS SAMPLES SEED OUT` estimates the same numbers by
//! playing deals forward with `State` and a menu lookup, never reading a
//! tree or the exact accumulators, as an independent check.

use cfr_inputs::driver::sha256;
use cfr_inputs::game::{Cards, State, canonical};
use cfr_inputs::menus::{FILES, NIL, build};
use cfr_inputs::trees::{Menus, Node, TAG, Tree, leaf, offsets_bytes};
use rayon::prelude::*;
use std::io::Write;
use std::path::Path;
use std::sync::Mutex;

const UNITS: i128 = 1000;
/// Stages tracked: Pone card 1 (0), Dealer card 1 (1), Pone card 2 (2),
/// Dealer card 2 (3).
const STAGES: u8 = 4;
const MENUS_DIGEST: &str = "a7c50ae009bffd159d242cfb7f38e0e838a38eda1efb2cec05b60b19bd368f3f";
const TREES_DIGEST: &str = "d06cacaa6df7f3e75fc305cc7b21942a2ea574bd1030e77338d29271c0caabbc";
const OFFSETS_DIGEST: &str = "8077f44a2f3ed48d48e42a0e80940d52e9f7f62cf3466a7ebb0120704457cf2e";
const POLICY_DIGEST: &str = "647b38309d1e43109274250fe2b8b8a8acedd905d8eb56717999df83f487395d";
const PRIOR_DIGEST: &str = "9e0a76fc3b64f5609781bed320f48f8bbb23bb481c2872ecdcd1ed25a404c595";

struct Inputs {
    hands: Vec<Cards>,
    menus: Menus,
    policy: Vec<u16>,
    prior: Vec<u64>,
    mass: u64,
}

fn load(bundle: &Path) -> Inputs {
    let hands = canonical();
    let files: Vec<Vec<u8>> = (0..FILES)
        .into_par_iter()
        .map(|file_index| {
            let path = bundle.join("menus").join(format!("{file_index}.bin"));
            if path.exists() {
                std::fs::read(path).expect("menu read")
            } else {
                let built = build(file_index, &hands);
                assert!(built.is_empty(), "missing non-empty menu {file_index}");
                built
            }
        })
        .collect();
    let lines: String = files.iter().map(|bytes| sha256(bytes) + "\n").collect();
    assert_eq!(sha256(lines.as_bytes()), MENUS_DIGEST, "menus digest");
    let menus = Menus::from_files(&files);
    drop(files);
    assert_eq!(sha256(&offsets_bytes(&menus)), OFFSETS_DIGEST, "offsets digest");
    let policy_bytes = std::fs::read(bundle.join("policy.bin")).expect("policy read");
    assert_eq!(sha256(&policy_bytes), POLICY_DIGEST, "policy digest");
    let policy: Vec<u16> = policy_bytes
        .as_chunks::<2>()
        .0
        .iter()
        .map(|&chunk| u16::from_le_bytes(chunk))
        .collect();
    assert_eq!(policy.len() as u64, menus.actions, "policy size");
    let prior_bytes = std::fs::read(bundle.join("prior.bin")).expect("prior read");
    assert_eq!(sha256(&prior_bytes), PRIOR_DIGEST, "prior digest");
    let prior: Vec<u64> = prior_bytes
        .as_chunks::<8>()
        .0
        .iter()
        .map(|&chunk| u64::from_le_bytes(chunk))
        .collect();
    let mass = prior.iter().sum();
    eprintln!(
        "loaded: {} menus, {} actions, prior mass {mass}",
        menus.len(),
        menus.actions
    );
    Inputs {
        hands,
        menus,
        policy,
        prior,
        mass,
    }
}

/// The tracked menus (stages 0..4), in global order.
struct Compact {
    of_menu: Vec<u32>,
    global: Vec<u32>,
    /// Compact action-slot start per compact menu, one extra at the end.
    slot: Vec<u32>,
    /// Compact menu start per file, one extra at the end.
    file_start: Vec<u32>,
}

impl Compact {
    fn new(menus: &Menus) -> Compact {
        let mut compact = Compact {
            of_menu: vec![NIL; menus.len()],
            global: Vec::new(),
            slot: vec![0],
            file_start: Vec::with_capacity(FILES + 1),
        };
        for file_index in 0..FILES {
            compact
                .file_start
                .push(u32::try_from(compact.global.len()).unwrap());
            for menu in menus.starts[file_index] as usize..menus.starts[file_index + 1] as usize {
                if menus.stage[menu] < STAGES {
                    compact.of_menu[menu] = u32::try_from(compact.global.len()).unwrap();
                    compact.global.push(u32::try_from(menu).unwrap());
                    let last = *compact.slot.last().unwrap();
                    compact.slot.push(last + u32::from(menus.width[menu]));
                }
            }
        }
        compact
            .file_start
            .push(u32::try_from(compact.global.len()).unwrap());
        compact
    }

    fn menu_range(&self, file_index: usize) -> (usize, usize) {
        (
            self.file_start[file_index] as usize,
            self.file_start[file_index + 1] as usize,
        )
    }

    fn slot_range(&self, file_index: usize) -> (usize, usize) {
        let (begin, end) = self.menu_range(file_index);
        (self.slot[begin] as usize, self.slot[end] as usize)
    }
}

/// Value and reach accumulators for one file's tracked menus.
struct Accumulator {
    menu_base: usize,
    slot_base: usize,
    value: Vec<i128>,
    reach: Vec<i128>,
}

impl Accumulator {
    fn new(compact: &Compact, file_index: usize) -> Accumulator {
        let (menu_begin, menu_end) = compact.menu_range(file_index);
        let (slot_begin, slot_end) = compact.slot_range(file_index);
        Accumulator {
            menu_base: menu_begin,
            slot_base: slot_begin,
            value: vec![0; slot_end - slot_begin],
            reach: vec![0; menu_end - menu_begin],
        }
    }

    fn add(&mut self, other: &Accumulator) {
        for (mine, theirs) in self.value.iter_mut().zip(&other.value) {
            *mine += theirs;
        }
        for (mine, theirs) in self.reach.iter_mut().zip(&other.reach) {
            *mine += theirs;
        }
    }
}

struct Walker<'a> {
    menus: &'a Menus,
    policy: &'a [u16],
    compact: &'a Compact,
    tree: &'a Tree,
    /// Index 0: the Pone hand's file; index 1: the Dealer hand's file.
    accumulators: [&'a mut Accumulator; 2],
}

fn units_power(exponent: u32) -> i128 {
    UNITS.pow(exponent)
}

impl Walker<'_> {
    /// Returns the subtree's Pone-minus-Dealer value scaled by
    /// `UNITS^(6 - depth)`, as `solve::joint_value` does. `weight[s]` is the
    /// prior times every policy probability on the path except seat `s`'s,
    /// which count as one (`UNITS`), scaled by `UNITS^depth`.
    fn walk(&mut self, id: u32, weight: [i128; 2], depth: u32) -> i128 {
        if id & TAG != 0 {
            return i128::from(leaf(id)) * units_power(6 - depth);
        }
        if weight == [0, 0] {
            return 0;
        }
        let Node {
            info,
            first,
            off,
            actor,
            width,
        } = self.tree.node(self.menus, id);
        let seat = usize::from(actor);
        let compact_menu = self.compact.of_menu[info];
        let tracked = compact_menu != NIL && weight[seat] != 0;
        let mut total = 0;
        for action in 0..width {
            let prob = i128::from(self.policy[off + action]);
            let mut child_weight = weight;
            child_weight[seat] *= UNITS;
            child_weight[1 - seat] *= prob;
            if prob == 0 && child_weight[seat] == 0 {
                continue;
            }
            let child = self.walk(self.tree.edges[first + action], child_weight, depth + 1);
            total += prob * child;
            if tracked {
                let accumulator = &mut self.accumulators[seat];
                let slot = self.compact.slot[compact_menu as usize] as usize + action
                    - accumulator.slot_base;
                accumulator.value[slot] += weight[seat] * child;
            }
        }
        if tracked {
            let accumulator = &mut self.accumulators[seat];
            accumulator.reach[compact_menu as usize - accumulator.menu_base] +=
                weight[seat] * units_power(6 - depth);
        }
        total
    }
}

fn exact(bundle: &Path, out: &Path) {
    let inputs = load(bundle);
    let menus = &inputs.menus;
    let compact = Compact::new(menus);
    eprintln!(
        "tracked: {} menus, {} action slots",
        compact.global.len(),
        compact.slot.last().unwrap()
    );
    let dealer: Vec<Mutex<Accumulator>> = (0..1820)
        .map(|dealer_hand| Mutex::new(Accumulator::new(&compact, 1820 + dealer_hand)))
        .collect();
    let started = std::time::Instant::now();
    let done = std::sync::atomic::AtomicUsize::new(0);
    let pone: Vec<(String, Accumulator)> = (0..1820)
        .into_par_iter()
        .map(|pone_hand| {
            let tree = Tree::build(menus, &inputs.hands, pone_hand);
            let digest = sha256(&tree.to_bytes());
            let mut pone_accumulator = Accumulator::new(&compact, pone_hand);
            for dealer_hand in 0..1820 {
                let deal_weight = inputs.prior[pone_hand * 1820 + dealer_hand];
                if deal_weight == 0 {
                    continue;
                }
                let mut dealer_accumulator = Accumulator::new(&compact, 1820 + dealer_hand);
                let root = tree.roots[dealer_hand];
                assert!(root != NIL, "Chance mismatch");
                let mut walker = Walker {
                    menus,
                    policy: &inputs.policy,
                    compact: &compact,
                    tree: &tree,
                    accumulators: [&mut pone_accumulator, &mut dealer_accumulator],
                };
                let weight = i128::from(deal_weight);
                walker.walk(root, [weight, weight], 0);
                dealer[dealer_hand].lock().unwrap().add(&dealer_accumulator);
            }
            let finished = done.fetch_add(1, std::sync::atomic::Ordering::Relaxed) + 1;
            if finished % 100 == 0 {
                eprintln!(
                    "{finished}/1820 Pone hands, {:.0} s",
                    started.elapsed().as_secs_f64()
                );
            }
            (digest, pone_accumulator)
        })
        .collect();
    let lines: String = pone.iter().map(|(digest, _)| digest.clone() + "\n").collect();
    let trees_digest = sha256(lines.as_bytes());
    assert_eq!(trees_digest, TREES_DIGEST, "trees digest");
    eprintln!(
        "trees digest matches; walk took {:.0} s",
        started.elapsed().as_secs_f64()
    );
    let mut accumulators: Vec<Accumulator> = pone.into_iter().map(|(_, acc)| acc).collect();
    accumulators.extend(dealer.into_iter().map(|cell| cell.into_inner().unwrap()));
    let denominator = inputs.mass as f64 * (UNITS as f64).powi(6);
    let mut file = std::io::BufWriter::new(std::fs::File::create(out).expect("create"));
    for (file_index, accumulator) in accumulators.iter().enumerate() {
        write_rows(&inputs, &compact, file_index, accumulator, denominator, None, &mut file);
    }
    file.flush().unwrap();
    eprintln!("wrote {}", out.display());
}

/// The product of the policy probabilities of the seat's own earlier
/// choices that lead to `menu`.
fn own_reach(inputs: &Inputs, menu: usize) -> f64 {
    let menus = &inputs.menus;
    let mut reach = 1.0f64;
    let (mut parent, mut parent_action) = (menus.parent[menu], menus.parent_action[menu]);
    while parent != NIL {
        let parent_index = parent as usize;
        reach *= f64::from(
            inputs.policy[menus.offset[parent_index] as usize + usize::from(parent_action)],
        ) / 1000.0;
        parent_action = menus.parent_action[parent_index];
        parent = menus.parent[parent_index];
    }
    reach
}

/// One record per tracked menu of `file_index`: menu, stage, width, reach
/// as a share of `denominator`, own reach, and the value of each card from
/// the acting seat's side (`NaN` when the opponent never reaches it). With
/// `scenario`, the record starts with the scenario id and skips unreached
/// menus.
fn write_rows(
    inputs: &Inputs,
    compact: &Compact,
    file_index: usize,
    accumulator: &Accumulator,
    denominator: f64,
    scenario: Option<u32>,
    file: &mut impl Write,
) {
    let menus = &inputs.menus;
    let seat_sign = if file_index < 1820 { 1.0 } else { -1.0 };
    for (local, &reach) in accumulator.reach.iter().enumerate() {
        if scenario.is_some() && reach == 0 {
            continue;
        }
        let compact_menu = accumulator.menu_base + local;
        let menu = compact.global[compact_menu] as usize;
        let width = usize::from(menus.width[menu]);
        let mut values = [f64::NAN; 4];
        if reach != 0 {
            for (action, value) in values.iter_mut().enumerate().take(width) {
                let slot = compact.slot[compact_menu] as usize + action - accumulator.slot_base;
                let numerator = accumulator.value[slot] * UNITS;
                *value = seat_sign * numerator as f64 / reach as f64;
            }
        }
        if let Some(id) = scenario {
            file.write_all(&id.to_le_bytes()).unwrap();
        }
        file.write_all(&u32::try_from(menu).unwrap().to_le_bytes()).unwrap();
        file.write_all(&[menus.stage[menu], menus.width[menu], 0, 0]).unwrap();
        file.write_all(&(reach as f64 / denominator).to_le_bytes()).unwrap();
        file.write_all(&own_reach(inputs, menu).to_le_bytes()).unwrap();
        for value in values {
            file.write_all(&value.to_le_bytes()).unwrap();
        }
    }
}

/// One valuation scenario: a seat, its kept hand, and integer weights over
/// the opponent's 1,820 kept hands.
struct Scenario {
    id: u32,
    seat: usize,
    own: usize,
    weights: Vec<u64>,
}

fn read_scenarios(path: &Path) -> Vec<Scenario> {
    let bytes = std::fs::read(path).expect("scenarios");
    let record = 8 + 1820 * 8;
    assert_eq!(bytes.len() % record, 0, "scenario file size");
    bytes
        .chunks(record)
        .map(|chunk| {
            let weights: Vec<u64> = chunk[8..]
                .as_chunks::<8>()
                .0
                .iter()
                .map(|&word| u64::from_le_bytes(word))
                .collect();
            let total: u128 = weights.iter().map(|&weight| u128::from(weight)).sum();
            assert!(total > 0 && total < 1 << 60, "scenario mass");
            Scenario {
                id: u32::from_le_bytes(chunk[0..4].try_into().unwrap()),
                seat: usize::from(chunk[4]),
                own: usize::from(u16::from_le_bytes(chunk[6..8].try_into().unwrap())),
                weights,
            }
        })
        .collect()
}

/// `rows BUNDLE SCENARIOS OUT`: values of every first- and second-play
/// decision of each scenario's own hand, with the opponent's hand weighted
/// by the scenario's weights instead of the prior row.
fn rows(bundle: &Path, scenarios_path: &Path, out: &Path) {
    let inputs = load(bundle);
    let menus = &inputs.menus;
    let compact = Compact::new(menus);
    let scenarios = read_scenarios(scenarios_path);
    let own_file = |scenario: &Scenario| scenario.seat * 1820 + scenario.own;
    let results: Vec<Mutex<Accumulator>> = scenarios
        .iter()
        .map(|scenario| Mutex::new(Accumulator::new(&compact, own_file(scenario))))
        .collect();
    let started = std::time::Instant::now();
    (0..1820).into_par_iter().for_each(|pone_hand| {
        let wanted: Vec<usize> = (0..scenarios.len())
            .filter(|&i| {
                let scenario = &scenarios[i];
                if scenario.seat == 0 {
                    scenario.own == pone_hand
                } else {
                    scenario.weights[pone_hand] != 0
                }
            })
            .collect();
        if wanted.is_empty() {
            return;
        }
        let tree = Tree::build(menus, &inputs.hands, pone_hand);
        for i in wanted {
            let scenario = &scenarios[i];
            let dealers: Vec<usize> = if scenario.seat == 0 {
                (0..1820).filter(|&d| scenario.weights[d] != 0).collect()
            } else {
                vec![scenario.own]
            };
            let mut own_accumulator = Accumulator::new(&compact, own_file(scenario));
            for dealer_hand in dealers {
                let weight = if scenario.seat == 0 {
                    scenario.weights[dealer_hand]
                } else {
                    scenario.weights[pone_hand]
                };
                let root = tree.roots[dealer_hand];
                assert!(root != NIL, "scenario weights an impossible deal");
                let mut pone_accumulator;
                let mut dealer_accumulator;
                let accumulators = if scenario.seat == 0 {
                    dealer_accumulator = Accumulator::new(&compact, 1820 + dealer_hand);
                    [&mut own_accumulator, &mut dealer_accumulator]
                } else {
                    pone_accumulator = Accumulator::new(&compact, pone_hand);
                    [&mut pone_accumulator, &mut own_accumulator]
                };
                let mut walker = Walker {
                    menus,
                    policy: &inputs.policy,
                    compact: &compact,
                    tree: &tree,
                    accumulators,
                };
                let weight = i128::from(weight);
                walker.walk(root, [weight, weight], 0);
            }
            results[i].lock().unwrap().add(&own_accumulator);
        }
    });
    eprintln!("walks took {:.0} s", started.elapsed().as_secs_f64());
    let mut file = std::io::BufWriter::new(std::fs::File::create(out).expect("create"));
    for (scenario, cell) in scenarios.iter().zip(results) {
        let accumulator = cell.into_inner().unwrap();
        let mass: u64 = scenario.weights.iter().sum();
        let denominator = mass as f64 * (UNITS as f64).powi(6);
        write_rows(
            &inputs,
            &compact,
            own_file(scenario),
            &accumulator,
            denominator,
            Some(scenario.id),
            &mut file,
        );
    }
    file.flush().unwrap();
    eprintln!("wrote {}", out.display());
}

struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut mixed = self.0;
        mixed = (mixed ^ (mixed >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        mixed = (mixed ^ (mixed >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        mixed ^ (mixed >> 31)
    }

    fn below(&mut self, bound: u64) -> u64 {
        // Rejection keeps the draw exactly uniform.
        let zone = u64::MAX - u64::MAX % bound;
        loop {
            let draw = self.next();
            if draw < zone {
                return draw % bound;
            }
        }
    }
}

fn lookup(menus: &Menus, file_index: usize, key: u64) -> usize {
    let (begin, end) = (
        menus.starts[file_index] as usize,
        menus.starts[file_index + 1] as usize,
    );
    let at = menus.history[begin..end].partition_point(|&candidate| candidate < key);
    assert!(
        begin + at < end && menus.history[begin + at] == key,
        "Missing info"
    );
    begin + at
}

fn token_count(key: u64) -> u32 {
    u32::try_from((0..16).take_while(|i| (key >> (4 * i)) & 15 != 0).count()).unwrap()
}

fn sample_policy(inputs: &Inputs, menu: usize, rng: &mut Rng) -> usize {
    let off = inputs.menus.offset[menu] as usize;
    let mut draw = rng.below(1000);
    for action in 0..usize::from(inputs.menus.width[menu]) {
        let prob = u64::from(inputs.policy[off + action]);
        if draw < prob {
            return action;
        }
        draw -= prob;
    }
    unreachable!("policy row sums to 1000")
}

/// The menu file for the player to act.
fn file_of(state: &State, pone_hand: usize, dealer_hand: usize) -> usize {
    state.next * 1820
        + if state.next == 1 {
            dealer_hand
        } else {
            pone_hand
        }
}

/// Play to the end with the policy for both seats; Pone-minus-Dealer margin.
fn playout(inputs: &Inputs, mut state: State, hands: (usize, usize), rng: &mut Rng) -> i32 {
    loop {
        if state.cards_left[0] <= 1 && state.cards_left[1] <= 1 {
            state.finish();
            return state.points[0] - state.points[1];
        }
        let legal = state.legal();
        if legal.len() < 2 || 4 - state.cards_left[state.next] >= 3 {
            let action = state.forced();
            state.play(action);
            continue;
        }
        let menu = lookup(
            &inputs.menus,
            file_of(&state, hands.0, hands.1),
            state.history_key(),
        );
        let action = sample_policy(inputs, menu, rng);
        state.play(Some(legal[action]));
    }
}

/// Play forward to `target`, or `None` if the deal leaves its history.
fn reach_target(
    inputs: &Inputs,
    target: usize,
    target_key: u64,
    seat: usize,
    hands: (usize, usize),
    rng: &mut Rng,
) -> Option<State> {
    let mut state = State::new(inputs.hands[hands.0], inputs.hands[hands.1]);
    loop {
        let key = state.history_key();
        let length = token_count(key);
        let mask = if length == 0 { 0 } else { (1u64 << (4 * length)) - 1 };
        if target_key & mask != key {
            return None;
        }
        if state.cards_left[0] <= 1 && state.cards_left[1] <= 1 {
            return None;
        }
        let legal = state.legal();
        if legal.len() < 2 || 4 - state.cards_left[state.next] >= 3 {
            let action = state.forced();
            state.play(action);
            continue;
        }
        let menu = lookup(&inputs.menus, file_of(&state, hands.0, hands.1), key);
        if state.next == seat {
            if menu == target {
                return Some(state);
            }
            // An earlier own decision: follow the target's history.
            let token = (target_key >> (4 * length)) & 15;
            if !(1..=13).contains(&token) {
                return None;
            }
            let rank = u8::try_from(token - 1).unwrap();
            if !legal.contains(&rank) {
                return None;
            }
            state.play(Some(rank));
        } else {
            let action = sample_policy(inputs, menu, rng);
            state.play(Some(legal[action]));
        }
    }
}

fn monte_carlo(bundle: &Path, targets_path: &Path, samples: usize, seed: u64, out: &Path) {
    assert!(samples >= 2, "a standard error needs at least two samples");
    let inputs = load(bundle);
    let targets: Vec<usize> = std::fs::read_to_string(targets_path)
        .expect("targets")
        .split_whitespace()
        .map(|word| word.parse().expect("menu index"))
        .collect();
    let rows: Vec<String> = targets
        .par_iter()
        .enumerate()
        .map(|(target_number, &target)| {
            let menus = &inputs.menus;
            let file_index = menus.starts.partition_point(|&start| start as usize <= target) - 1;
            let seat = file_index / 1820;
            let own = file_index % 1820;
            let target_key = menus.history[target];
            let weights: Vec<u64> = (0..1820)
                .map(|other| {
                    if seat == 0 {
                        inputs.prior[own * 1820 + other]
                    } else {
                        inputs.prior[other * 1820 + own]
                    }
                })
                .collect();
            let row_mass: u64 = weights.iter().sum();
            let mut rng = Rng(seed ^ (target_number as u64).wrapping_mul(0xA24B_AED4_963E_E407));
            let width = usize::from(menus.width[target]);
            let mut sums = [0f64; 4];
            let mut squares = [0f64; 4];
            let (mut accepted, mut attempts) = (0usize, 0usize);
            let sign = if seat == 0 { 1.0 } else { -1.0 };
            while accepted < samples && attempts < samples * 2000 {
                attempts += 1;
                let mut draw = rng.below(row_mass);
                let mut other = 0;
                while draw >= weights[other] {
                    draw -= weights[other];
                    other += 1;
                }
                let hands = if seat == 0 { (own, other) } else { (other, own) };
                let Some(state) = reach_target(&inputs, target, target_key, seat, hands, &mut rng)
                else {
                    continue;
                };
                accepted += 1;
                let legal = state.legal();
                for action in 0..width {
                    let mut next = state.clone();
                    next.play(Some(legal[action]));
                    let margin = sign * f64::from(playout(&inputs, next, hands, &mut rng));
                    sums[action] += margin;
                    squares[action] += margin * margin;
                }
            }
            assert!(
                accepted == samples,
                "target {target} reached {accepted} of {samples} deals in {attempts} attempts"
            );
            let count = accepted as f64;
            (0..width)
                .map(|action| {
                    let mean = sums[action] / count;
                    let variance = (squares[action] / count - mean * mean) * count / (count - 1.0);
                    format!(
                        "{target},{action},{accepted},{attempts},{mean},{}\n",
                        (variance / count).sqrt()
                    )
                })
                .collect::<String>()
        })
        .collect();
    let mut text = String::from("menu,action,accepted,attempts,mean,standard_error\n");
    text.extend(rows);
    std::fs::write(out, text).expect("write");
    eprintln!("wrote {}", out.display());
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("exact") => exact(Path::new(&args[2]), Path::new(&args[3])),
        Some("rows") => rows(Path::new(&args[2]), Path::new(&args[3]), Path::new(&args[4])),
        Some("mc") => monte_carlo(
            Path::new(&args[2]),
            Path::new(&args[3]),
            args[4].parse().expect("samples"),
            args[5].parse().expect("seed"),
            Path::new(&args[6]),
        ),
        _ => {
            eprintln!("usage: play-values exact BUNDLE OUT | mc BUNDLE TARGETS SAMPLES SEED OUT");
            std::process::exit(2);
        }
    }
}
