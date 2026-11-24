//! Small-game checks of the solver: thread-count determinism, resume
//! equivalence, and the exact joint value against an oracle that replays the
//! game from `State` and looks policies up by history, never touching trees.

mod common;

use cfr_inputs::driver::{self, Outcome};
use cfr_inputs::game::State;
use cfr_inputs::solve::{Certificate, Game, MASS_LIMIT, POLICY_UNITS, Solver, certificate};
use common::{
    DEALERS, PONES, Small, SmallTrees, bits, build_game, decides, info_of, matched, small, solve,
};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

#[test]
fn bytes_do_not_depend_on_thread_count() {
    let small_game = small();
    let one = solve(&small_game, 1, 6);
    let many = solve(&small_game, 4, 6);
    assert_eq!(bits(&one.regret), bits(&many.regret));
    assert_eq!(bits(&one.average), bits(&many.average));
    assert!(one.average.iter().any(|&weight| weight > 0.0));
}

/// Pone's value times `POLICY_UNITS^(6 - depth)`, by replaying the game from
/// `State` and looking policies up by history, never touching trees. Both
/// seats play `policy`, except that the seat `responder` names best-responds.
fn replay(
    small_game: &Small,
    policy: &[u16],
    state: State,
    pone_hand: usize,
    dealer_hand: usize,
    depth: u32,
    responder: Option<usize>,
) -> i128 {
    let mut state = state;
    loop {
        if state.cards_left[0] <= 1 && state.cards_left[1] <= 1 {
            state.finish();
            return i128::from(state.points[0] - state.points[1])
                * i128::from(POLICY_UNITS).pow(6 - depth);
        }
        if !decides(&state) {
            let action = state.forced();
            state.play(action);
            continue;
        }
        let legal = state.legal();
        let actor = state.next;
        let off =
            small_game.menus.offset[info_of(small_game, &state, pone_hand, dealer_hand)] as usize;
        let children = legal.iter().map(|&rank| {
            let mut next = state.clone();
            next.play(Some(rank));
            replay(
                small_game,
                policy,
                next,
                pone_hand,
                dealer_hand,
                depth + 1,
                responder,
            )
        });
        if responder != Some(actor) {
            return children
                .zip(&policy[off..])
                .map(|(value, &units)| i128::from(units) * value)
                .sum();
        }
        let values = children.map(|value| value * i128::from(POLICY_UNITS));
        return if actor == 0 {
            values.max()
        } else {
            values.min()
        }
        .unwrap();
    }
}

/// The joint value of `policy` in both seats, by replaying every deal.
fn replayed_joint(small_game: &Small, policy: &[u16]) -> i128 {
    small_game.over_deals(|state, pone_hand, dealer_hand| {
        replay(small_game, policy, state, pone_hand, dealer_hand, 0, None)
    })
}

#[test]
fn certificate_joint_value_matches_a_direct_replay() {
    let small_game = small();
    let game = small_game.game();
    let policy = solve(&small_game, 2, 4).rounded(&game);
    let exact = certificate(&game, &SmallTrees(&small_game.trees), &policy);
    assert_eq!(exact.joint, replayed_joint(&small_game, &policy));
    // Each player's best response does at least as well as the policy itself.
    assert!(exact.upper * i128::from(POLICY_UNITS).pow(3) >= exact.joint);
    assert!(exact.lower * i128::from(POLICY_UNITS).pow(3) <= exact.joint);
}

#[test]
fn rounded_policy_has_1000_units_per_menu() {
    let small_game = small();
    let policy = solve(&small_game, 2, 3).rounded(&small_game.game());
    for i in 0..small_game.menus.len() {
        let off = small_game.menus.offset[i] as usize;
        let sum: u32 = policy[off..off + usize::from(small_game.menus.width[i])]
            .iter()
            .map(|&units| u32::from(units))
            .sum();
        assert_eq!(sum, POLICY_UNITS);
    }
}

/// The average follows Tammelin's alternating schedule: after one iteration
/// Pone's average holds its strategy after its update and Dealer's holds its
/// strategy before its update, which is uniform at every first decision.
#[test]
fn each_seat_averages_the_strategy_its_opponent_played_against() {
    let small_game = small();
    let solver = solve(&small_game, 2, 1);
    let menus = &small_game.menus;
    let dealer_menus = menus.starts[1820] as usize..menus.len();
    let mut dealer_moved = false;
    for i in 0..menus.len() {
        if menus.parent[i] != u32::MAX {
            continue;
        }
        let slots =
            menus.offset[i] as usize..menus.offset[i] as usize + usize::from(menus.width[i]);
        if dealer_menus.contains(&i) {
            let uniform = 1.0 / f64::from(menus.width[i]);
            assert!(
                solver.average[slots.clone()]
                    .iter()
                    .all(|&weight| weight.to_bits() == uniform.to_bits())
            );
            dealer_moved |= solver.sigma[slots]
                .iter()
                .any(|&probability| probability.to_bits() != uniform.to_bits());
        } else {
            assert_eq!(
                bits(&solver.average[slots.clone()]),
                bits(&solver.sigma[slots])
            );
        }
    }
    assert!(
        dealer_moved,
        "Dealer's first update must change some first decision"
    );
}

/// Own reach is conserved down each seat's choices: a menu's average weights
/// sum to the average weight of the parent action that leads to it, because
/// every term carries the same iteration weight and the same strategy, with
/// the menu's own reach equal to its parent's reach times that action. At a
/// first decision own reach is one, so after three iterations the linear
/// weights sum to 1 + 2 + 3 = 6.
#[test]
fn average_weights_sum_to_their_parent_action() {
    let small_game = small();
    let solver = solve(&small_game, 2, 3);
    let menus = &small_game.menus;
    let mut children = 0;
    for i in 0..menus.len() {
        let off = menus.offset[i] as usize;
        let total: f64 = solver.average[off..off + usize::from(menus.width[i])]
            .iter()
            .sum();
        if menus.parent[i] == u32::MAX {
            assert!((total - 6.0).abs() <= 1e-12, "first decision {i}");
            continue;
        }
        let parent = menus.parent[i] as usize;
        let expected =
            solver.average[menus.offset[parent] as usize + usize::from(menus.parent_action[i])];
        if expected == 0.0 {
            assert!(total == 0.0, "menu {i}");
        } else {
            assert!((total - expected).abs() <= 1e-12 * expected, "menu {i}");
        }
        children += 1;
    }
    assert!(children > 0, "the game must have later decisions");
}

/// The stopping rule at its exact boundary: exposure 0.001 points converges,
/// and one more unit of best-response gap does not.
#[test]
fn convergence_flips_one_unit_past_exposure_one_thousandth() {
    let denominator = 7 * i128::from(POLICY_UNITS).pow(3);
    // Both bounds sit off zero, so a rule that ignored either one would show.
    let at = |gap: i128| Certificate {
        joint: 0,
        upper: gap - 11,
        lower: -11,
        denominator,
    };
    let boundary = 2 * denominator / 1000;
    assert_eq!(at(boundary).exposure(), 0.001);
    assert!(at(boundary).converged());
    assert!(!at(boundary + 1).converged());
}

/// Rounding hands each menu's spare units to the largest remainders, ties to
/// the lower action, and splits a menu with no average weight evenly.
#[test]
fn rounding_gives_spare_units_to_the_largest_remainders() {
    let small_game = small();
    let game = small_game.game();
    let menus = &small_game.menus;
    let action_count = usize::try_from(menus.actions).unwrap();
    let width_of = |width| (0..menus.len()).find(|&i| menus.width[i] == width).unwrap();
    let (two, three) = (width_of(2), width_of(3));
    let mut average = vec![0.0; action_count];
    // 1/3 and 2/3 of 1,000: floors 333 and 666, the spare unit to the larger remainder.
    average[menus.offset[two] as usize] = 1.0;
    average[menus.offset[two] as usize + 1] = 2.0;
    // Equal thirds tie, so the spare unit goes to the first action.
    for slot in 0..3 {
        average[menus.offset[three] as usize + slot] = 1.0;
    }
    let solver = Solver::new(&game, vec![0.0; action_count], average);
    let rounded = solver.rounded(&game);
    let units = |menu: usize| {
        let off = menus.offset[menu] as usize;
        rounded[off..off + usize::from(menus.width[menu])].to_vec()
    };
    assert_eq!(units(two), [333, 667]);
    assert_eq!(units(three), [334, 333, 333]);
    let untouched = (0..menus.len())
        .find(|&i| menus.width[i] == 3 && i != three)
        .unwrap();
    assert_eq!(units(untouched), [334, 333, 333]);
}

#[test]
#[should_panic(expected = "prior mass 0")]
fn a_prior_with_no_weight_is_refused() {
    let small_game = small();
    let chance = vec![0u64; 1820 * 1820];
    let _ = Game::new(&small_game.menus, &chance);
}

#[test]
#[should_panic(expected = "prior mass")]
fn a_prior_over_the_mass_limit_is_refused() {
    let small_game = small();
    let mut chance = small_game.chance.clone();
    let pair = chance.iter().position(|&weight| weight != 0).unwrap();
    chance[pair] = MASS_LIMIT;
    let _ = Game::new(&small_game.menus, &chance);
}

#[test]
#[should_panic(expected = "prior weights an impossible deal")]
fn a_prior_on_an_impossible_deal_is_refused() {
    let small_game = small();
    let mut chance = small_game.chance.clone();
    // Four aces each: eight aces cannot be dealt.
    let aces = common::index(&small_game.hands, [0, 0, 0, 0]);
    chance[aces * 1820 + aces] = 1;
    let _ = Game::new(&small_game.menus, &chance);
}

#[test]
fn exposure_falls_as_the_solve_runs() {
    let small_game = small();
    let game = small_game.game();
    let exposure = |iterations| {
        let policy = solve(&small_game, 2, iterations).rounded(&game);
        certificate(&game, &SmallTrees(&small_game.trees), &policy).exposure()
    };
    let (early, later) = (exposure(1), exposure(64));
    assert!(later < early);
    assert!(later >= 0.0);
}

/// Identities in the exact format the binary uses, which contains commas.
fn id(prior: &str) -> String {
    driver::identity(
        &driver::sha256(prior.as_bytes()),
        "menus-digest",
        "trees-digest",
    )
}

fn scratch(name: &str) -> PathBuf {
    let dir = PathBuf::from(env!("CARGO_TARGET_TMPDIR")).join(name);
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

/// Run the small solve in `dir`. With no budget it runs to the end, which is
/// convergence at 128; a zero budget pauses after each committed iteration.
fn drive(
    small_game: &Small,
    dir: &Path,
    prior: &str,
    budget: Option<f64>,
) -> std::io::Result<Outcome> {
    driver::run(
        dir,
        &small_game.game(),
        &SmallTrees(&small_game.trees),
        &id(prior),
        budget,
        4096,
    )
}

fn run_to_end(small_game: &Small, dir: &Path, prior: &str) -> std::io::Result<Outcome> {
    drive(small_game, dir, prior, None)
}

fn run_one(small_game: &Small, dir: &Path, prior: &str) -> std::io::Result<Outcome> {
    drive(small_game, dir, prior, Some(0.0))
}

fn assert_same_files(first_dir: &Path, second_dir: &Path, names: &[&str]) {
    for name in names {
        assert_eq!(
            std::fs::read(first_dir.join(name)).unwrap(),
            std::fs::read(second_dir.join(name)).unwrap(),
            "{name}"
        );
    }
}

#[test]
#[ignore = "slow (13-45 s), not broken: CI always runs it; locally run cargo test --release -- --include-ignored"]
fn a_paused_and_resumed_solve_matches_an_uninterrupted_one() {
    // This game first meets the 0.001 target between iterations 64 and 128,
    // so an uninterrupted run converges at the scheduled 128. A driver that
    // certified whenever it paused would stop at an earlier, unscheduled
    // iteration with a different policy.
    let small_game = small();
    let straight = scratch("straight");
    let first = run_to_end(&small_game, &straight, "prior").unwrap();
    assert_eq!(first, Outcome::Converged(128));
    let paused = scratch("paused");
    let mut last = run_one(&small_game, &paused, "prior").unwrap();
    assert_eq!(last, Outcome::Paused(1));
    while let Outcome::Paused(_) = last {
        last = run_one(&small_game, &paused, "prior").unwrap();
    }
    assert_eq!(first, last);
    assert_same_files(
        &straight,
        &paused,
        &[
            "checkpoint.json",
            "solve.json",
            "policy.bin",
            "policy-32.bin",
        ],
    );
    let strip = |text: String| text.split(",\"seconds\"").next().unwrap().to_owned();
    for it in [1, 8, 32, 128] {
        let name = format!("certificate-{it}.json");
        assert_eq!(
            strip(std::fs::read_to_string(straight.join(&name)).unwrap()),
            strip(std::fs::read_to_string(paused.join(&name)).unwrap()),
            "{name}"
        );
    }
}

#[test]
fn resume_rejects_a_checkpoint_made_from_different_inputs() {
    let small_game = small();
    let dir = scratch("other-prior");
    assert_eq!(
        run_one(&small_game, &dir, "prior").unwrap(),
        Outcome::Paused(1)
    );
    let err = run_one(&small_game, &dir, "other").unwrap_err();
    assert!(err.to_string().contains("different inputs"), "{err}");
}

/// A checkpoint saved by an older solver version is refused, since its
/// averages were accumulated by different arithmetic.
#[test]
fn resume_rejects_a_checkpoint_from_an_older_solver() {
    let small_game = small();
    let dir = scratch("older-solver");
    assert_eq!(
        run_one(&small_game, &dir, "prior").unwrap(),
        Outcome::Paused(1)
    );
    let manifest = dir.join("checkpoint.json");
    let json = std::fs::read_to_string(&manifest).unwrap();
    let current = format!("solver:{}", driver::SOLVER_VERSION);
    let older = format!("solver:{}", driver::SOLVER_VERSION - 1);
    assert!(json.contains(&current), "{json}");
    std::fs::write(&manifest, json.replace(&current, &older)).unwrap();
    let err = run_one(&small_game, &dir, "prior").unwrap_err();
    assert!(err.to_string().contains("different inputs"), "{err}");
}

#[test]
#[should_panic(expected = "Chance mismatch")]
fn a_weighted_deal_without_a_tree_is_refused() {
    let small_game = build_game(&PONES[..1], &DEALERS[..1], |_, _| 1);
    let mut chance = small_game.chance.clone();
    // A feasible deal whose Pone hand has no tree in this game.
    let other = common::index(&small_game.hands, PONES[1]);
    let dealer = common::index(&small_game.hands, DEALERS[0]);
    chance[other * 1820 + dealer] = 1;
    let game = Game::new(&small_game.menus, &chance);
    let policy = vec![0u16; usize::try_from(small_game.menus.actions).unwrap()];
    let _ = certificate(&game, &SmallTrees(&small_game.trees), &policy);
}

#[test]
fn resume_rejects_a_damaged_checkpoint() {
    let small_game = small();
    let dir = scratch("damaged");
    assert_eq!(
        run_one(&small_game, &dir, "prior").unwrap(),
        Outcome::Paused(1)
    );
    let regret = dir.join("checkpoint-1/regret.bin");
    let mut bytes = std::fs::read(&regret).unwrap();
    bytes[0] ^= 1;
    std::fs::write(&regret, bytes).unwrap();
    let err = run_one(&small_game, &dir, "prior").unwrap_err();
    assert!(
        err.to_string().contains("does not match its digest"),
        "{err}"
    );
    // A manifest that lost a field is refused by name.
    let manifest = dir.join("checkpoint.json");
    let json = std::fs::read_to_string(&manifest).unwrap();
    std::fs::write(&manifest, json.replace("\"regret_sha256\"", "\"gone\"")).unwrap();
    let err = run_one(&small_game, &dir, "prior").unwrap_err();
    assert!(err.to_string().contains("lacks regret_sha256"), "{err}");
}

#[test]
fn a_solve_stops_at_its_iteration_cap() {
    let small_game = small();
    let dir = scratch("capped");
    let trees = SmallTrees(&small_game.trees);
    let outcome = driver::run(&dir, &small_game.game(), &trees, &id("prior"), None, 2).unwrap();
    assert_eq!(outcome, Outcome::Capped(2));
    assert!(dir.join("checkpoint-2").exists());
}

#[test]
fn certificates_follow_the_fixed_schedule() {
    let certified: Vec<u32> = (1..=300)
        .filter(|&iteration| driver::scheduled(iteration))
        .collect();
    assert_eq!(certified, [1, 8, 32, 128, 256]);
}

/// The rounded policy after `iterations` of a two-thread solve, and its
/// exact certificate.
fn certified(small_game: &Small, iterations: u32) -> (Vec<u16>, Certificate) {
    let game = small_game.game();
    let policy = solve(small_game, 2, iterations).rounded(&game);
    let exact = certificate(&game, &SmallTrees(&small_game.trees), &policy);
    (policy, exact)
}

#[test]
fn best_responses_match_an_expectimax_replay() {
    let small_game = matched();
    for iterations in [1, 3] {
        let (policy, exact) = certified(&small_game, iterations);
        let best = |responder| {
            small_game.over_deals(|state, pone_hand, dealer_hand| {
                replay(
                    &small_game,
                    &policy,
                    state,
                    pone_hand,
                    dealer_hand,
                    0,
                    Some(responder),
                )
            })
        };
        // Best-response values carry Q^3 less scale than joint values.
        let units_cubed = i128::from(POLICY_UNITS).pow(3);
        assert_eq!(exact.upper * units_cubed, best(0), "Pone best response");
        assert_eq!(exact.lower * units_cubed, best(1), "Dealer best response");
        assert!(exact.upper > exact.lower);
    }
}

/// Regression pin for floating-point operation order. A change to the order
/// of additions that alters this small game's results changes these digests;
/// a change that does not may still alter the full-size policy, so any such
/// change needs the full-size check.
#[test]
fn small_game_arithmetic_is_pinned() {
    let small_game = small();
    let solver = solve(&small_game, 3, 6);
    let digest = |values: &[f64]| {
        driver::sha256(
            &values
                .iter()
                .flat_map(|value| value.to_le_bytes())
                .collect::<Vec<u8>>(),
        )
    };
    assert_eq!(
        digest(&solver.regret),
        "2631fcb0bf9854636d4098f9c70aa0bfb8f8ae42debed5d7b77763be5415c066"
    );
    assert_eq!(
        digest(&solver.average),
        "78c5a2e1ef7f015324e217a398028515f3ce277924f6d88de44de1f5e00636b3"
    );
}

#[test]
#[ignore = "slow (13-45 s), not broken: CI always runs it; locally run cargo test --release -- --include-ignored"]
fn a_crash_during_certification_is_certified_on_resume() {
    let small_game = small();
    let straight = scratch("crash-straight");
    assert_eq!(
        run_to_end(&small_game, &straight, "inputs").unwrap(),
        Outcome::Converged(128)
    );
    let crashed = scratch("crash");
    assert_eq!(
        run_to_end(&small_game, &crashed, "inputs").unwrap(),
        Outcome::Converged(128)
    );
    // Checkpoint 128 was committed, then a crash came somewhere inside its
    // certification: before the certificate, or after it but before
    // `solve.json`.
    let lost: [&[&str]; 2] = [
        &[
            "solve.json",
            "policy.bin",
            "certificate-128.json",
            "policy-128.bin",
        ],
        &["solve.json", "policy.bin"],
    ];
    for names in lost {
        for name in names {
            std::fs::remove_file(crashed.join(name)).unwrap();
        }
        assert_eq!(
            run_to_end(&small_game, &crashed, "inputs").unwrap(),
            Outcome::Converged(128),
            "after losing {names:?}"
        );
        assert_same_files(
            &straight,
            &crashed,
            &[
                "policy.bin",
                "solve.json",
                "checkpoint.json",
                "policy-128.bin",
            ],
        );
    }
}

#[test]
#[ignore = "slow (13-45 s), not broken: CI always runs it; locally run cargo test --release -- --include-ignored"]
fn a_finished_solve_is_not_continued() {
    let small_game = small();
    let dir = scratch("finished");
    let converged = || run_to_end(&small_game, &dir, "inputs").unwrap();
    assert_eq!(converged(), Outcome::Converged(128));
    let policy = std::fs::read(dir.join("policy.bin")).unwrap();
    assert_eq!(converged(), Outcome::Converged(128));
    assert_eq!(std::fs::read(dir.join("policy.bin")).unwrap(), policy);
    assert!(!dir.join("checkpoint-129").exists());
    // The finished result stands on its own: no checkpoint is read again.
    std::fs::remove_dir_all(dir.join("checkpoint-128")).unwrap();
    assert_eq!(converged(), Outcome::Converged(128));
    let err = run_to_end(&small_game, &dir, "other").unwrap_err();
    assert!(err.to_string().contains("different inputs"), "{err}");
    // A policy changed after the solve finished is refused, not returned.
    let mut changed = policy;
    changed[0] ^= 1;
    std::fs::write(dir.join("policy.bin"), changed).unwrap();
    let err = run_to_end(&small_game, &dir, "inputs").unwrap_err();
    assert!(
        err.to_string().contains("does not match solve.json"),
        "{err}"
    );
    let finished = dir.join("solve.json");
    let json = std::fs::read_to_string(&finished).unwrap();
    std::fs::write(&finished, json.replace("\"identity\"", "\"gone\"")).unwrap();
    let err = run_to_end(&small_game, &dir, "inputs").unwrap_err();
    assert!(err.to_string().contains("lacks identity"), "{err}");
}

/// One deal in the bag behind a responder's public state: the replayed
/// position, the deal's hands, its weight so far, and how many opponent
/// policy factors that weight already includes.
struct Branch {
    state: State,
    pone_hand: usize,
    dealer_hand: usize,
    weight: i128,
    factors: u32,
}

/// Exact best-response value for `responder` against `policy`, computed by
/// recursion over public states from the rules, without the trees. The bag
/// holds every deal consistent with the responder's information, so a
/// responder decision maximizes the sum over all of them at once.
fn public_value(small_game: &Small, policy: &[u16], responder: usize, bag: Vec<Branch>) -> i128 {
    let mut total = 0i128;
    let mut live = Vec::new();
    for mut branch in bag {
        if branch.state.cards_left[0] <= 1 && branch.state.cards_left[1] <= 1 {
            branch.state.finish();
            let margin = i128::from(branch.state.points[0] - branch.state.points[1]);
            let sign = if responder == 1 { -1 } else { 1 };
            total +=
                sign * margin * branch.weight * i128::from(POLICY_UNITS).pow(3 - branch.factors);
        } else {
            live.push(branch);
        }
    }
    if live.is_empty() {
        return total;
    }
    let actor = live[0].state.next;
    assert!(live.iter().all(|branch| branch.state.next == actor));
    if actor == responder {
        let legal = live[0].state.legal();
        assert!(live.iter().all(|branch| branch.state.legal() == legal));
        let follow = |rank: Option<u8>| -> Vec<Branch> {
            live.iter()
                .map(|branch| {
                    let mut state = branch.state.clone();
                    state.play(rank);
                    Branch { state, ..*branch }
                })
                .collect()
        };
        let best = if decides(&live[0].state) {
            legal
                .iter()
                .map(|&rank| public_value(small_game, policy, responder, follow(Some(rank))))
                .max()
                .expect("a decision has legal ranks")
        } else {
            public_value(
                small_game,
                policy,
                responder,
                follow(live[0].state.forced()),
            )
        };
        return total + best;
    }
    let mut groups: BTreeMap<Option<u8>, Vec<Branch>> = BTreeMap::new();
    for branch in live {
        if decides(&branch.state) {
            let info = info_of(
                small_game,
                &branch.state,
                branch.pone_hand,
                branch.dealer_hand,
            );
            let offset = small_game.menus.offset[info] as usize;
            for (action_index, &rank) in branch.state.legal().iter().enumerate() {
                let units = policy[offset + action_index];
                if units == 0 {
                    continue;
                }
                let mut state = branch.state.clone();
                state.play(Some(rank));
                groups.entry(Some(rank)).or_default().push(Branch {
                    state,
                    weight: branch.weight * i128::from(units),
                    factors: branch.factors + 1,
                    ..branch
                });
            }
        } else {
            let action = branch.state.forced();
            let mut state = branch.state.clone();
            state.play(action);
            groups
                .entry(action)
                .or_default()
                .push(Branch { state, ..branch });
        }
    }
    total
        + groups
            .into_values()
            .map(|bag| public_value(small_game, policy, responder, bag))
            .sum::<i128>()
}

/// The certificate's best responses against an oracle that sums each
/// responder decision over every deal behind it. Catches a best response
/// that ignores the deal weights when combining a decision's deals (mutant
/// M1 in the #229 review), which `best_responses_match_an_expectimax_replay`
/// misses because its game puts one deal behind every decision.
#[test]
fn best_responses_match_a_public_state_recursion() {
    let small_game = small();
    let mut shared_decisions = 0;
    for iterations in [1, 3, 8, 64] {
        let (policy, exact) = certified(&small_game, iterations);
        shared_decisions += check_against_recursion(&small_game, &policy, &exact, iterations);
    }
    assert!(
        shared_decisions > 0,
        "the game must put several deals behind a decision"
    );
}

/// Asserts both best responses in `exact` equal the public-state recursion's,
/// and returns how many responder hands had several deals behind them.
fn check_against_recursion(
    small_game: &Small,
    policy: &[u16],
    exact: &Certificate,
    iterations: u32,
) -> usize {
    let mut shared_decisions = 0;
    for responder in 0..2 {
        let mut bags: BTreeMap<usize, Vec<Branch>> = BTreeMap::new();
        for pone_hand in 0..1820 {
            for dealer_hand in 0..1820 {
                let weight = small_game.chance[pone_hand * 1820 + dealer_hand];
                if weight == 0 {
                    continue;
                }
                let own = if responder == 0 {
                    pone_hand
                } else {
                    dealer_hand
                };
                bags.entry(own).or_default().push(Branch {
                    state: State::new(small_game.hands[pone_hand], small_game.hands[dealer_hand]),
                    pone_hand,
                    dealer_hand,
                    weight: i128::from(weight),
                    factors: 0,
                });
            }
        }
        shared_decisions += bags.values().filter(|bag| bag.len() > 1).count();
        let value: i128 = bags
            .into_values()
            .map(|bag| public_value(small_game, policy, responder, bag))
            .sum();
        let expected = if responder == 0 {
            exact.upper
        } else {
            -exact.lower
        };
        assert_eq!(
            value, expected,
            "responder {responder} after {iterations} iterations"
        );
    }
    shared_decisions
}

/// A deal weighted near `MASS_LIMIT` keeps exact values. This weight times
/// `POLICY_UNITS^3` overflows `u64` (to zero), so the certificate must form
/// those products in `i128`. A light second deal shares Pone's decisions, so
/// a heavy weight lost at any stage would change Pone's best response.
#[test]
fn a_deal_weight_near_the_mass_limit_keeps_exact_values() {
    let heavy: u64 = 9 << 55;
    assert!(heavy < MASS_LIMIT && heavy.wrapping_mul(1_000_000_000) == 0);
    let small_game = build_game(&PONES[..1], &DEALERS[..2], |_, dealer| {
        if dealer == 0 { heavy } else { 1 }
    });
    let (policy, exact) = certified(&small_game, 3);
    assert_eq!(exact.joint, replayed_joint(&small_game, &policy));
    assert!(check_against_recursion(&small_game, &policy, &exact, 3) > 0);
    let units = i128::from(POLICY_UNITS);
    assert_eq!(exact.denominator, i128::from(heavy + 1) * units.pow(3));
}

#[test]
fn mass_limit_is_the_certificate_bound() {
    let units = i128::from(POLICY_UNITS);
    assert_eq!(
        i128::from(MASS_LIMIT),
        ((1i128 << 125) - 1) / (128 * units.pow(6))
    );
}
