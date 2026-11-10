//! Small-game checks of the solver: thread-count determinism, resume
//! equivalence, and the exact joint value against an oracle that replays the
//! game from `State` and looks policies up by history, never touching trees.

mod common;

use cfr_inputs::driver::{self, Outcome};
use cfr_inputs::game::State;
use cfr_inputs::solve::{Q, certificate};
use common::{Small, SmallTrees, bits, decides, info_of, matched, small, solve};
use std::path::{Path, PathBuf};

#[test]
fn bytes_do_not_depend_on_thread_count() {
    let s = small();
    let one = solve(&s, 1, 6);
    let many = solve(&s, 4, 6);
    assert_eq!(bits(&one.regret), bits(&many.regret));
    assert_eq!(bits(&one.average), bits(&many.average));
    assert!(one.average.iter().any(|&x| x > 0.0));
}

/// Pone's value times Q^(6 - depth), by replaying the game from `State` and
/// looking policies up by history, never touching trees. Both seats play
/// `policy`, except that the seat `responder` names best-responds.
fn replay(
    s: &Small,
    policy: &[u16],
    state: State,
    p: usize,
    d: usize,
    depth: u32,
    responder: Option<usize>,
) -> i128 {
    let mut state = state;
    loop {
        if state.n[0] <= 1 && state.n[1] <= 1 {
            state.finish();
            return i128::from(state.points[0] - state.points[1]) * i128::from(Q).pow(6 - depth);
        }
        if !decides(&state) {
            let a = state.heuristic();
            state.play(a);
            continue;
        }
        let legal = state.legal();
        let actor = state.next;
        let off = s.menus.offset[info_of(s, &state, p, d)] as usize;
        let children = legal.iter().map(|&r| {
            let mut next = state.clone();
            next.play(Some(r));
            replay(s, policy, next, p, d, depth + 1, responder)
        });
        if responder != Some(actor) {
            return children
                .zip(&policy[off..])
                .map(|(v, &q)| i128::from(q) * v)
                .sum();
        }
        let values = children.map(|v| v * i128::from(Q));
        return if actor == 0 {
            values.max()
        } else {
            values.min()
        }
        .unwrap();
    }
}

#[test]
fn certificate_joint_value_matches_a_direct_replay() {
    let s = small();
    let game = s.game();
    let policy = solve(&s, 2, 4).rounded(&game);
    let c = certificate(&game, &SmallTrees(&s.trees), &policy);
    let expected = s.over_deals(|state, p, d| replay(&s, &policy, state, p, d, 0, None));
    assert_eq!(c.joint, expected);
    // Each player's best response does at least as well as the policy itself.
    assert!(c.upper * i128::from(Q).pow(3) >= c.joint);
    assert!(c.lower * i128::from(Q).pow(3) <= c.joint);
}

#[test]
fn rounded_policy_has_q_units_per_menu() {
    let s = small();
    let policy = solve(&s, 2, 3).rounded(&s.game());
    for i in 0..s.menus.len() {
        let off = s.menus.offset[i] as usize;
        let sum: u32 = policy[off..off + usize::from(s.menus.width[i])]
            .iter()
            .map(|&x| u32::from(x))
            .sum();
        assert_eq!(sum, Q);
    }
}

#[test]
fn exposure_falls_as_the_solve_runs() {
    let s = small();
    let game = s.game();
    let exposure = |iterations| {
        let policy = solve(&s, 2, iterations).rounded(&game);
        certificate(&game, &SmallTrees(&s.trees), &policy).exposure()
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
fn drive(s: &Small, dir: &Path, prior: &str, budget: Option<f64>) -> std::io::Result<Outcome> {
    driver::run(
        dir,
        &s.game(),
        &SmallTrees(&s.trees),
        &id(prior),
        budget,
        4096,
    )
}

fn run_to_end(s: &Small, dir: &Path, prior: &str) -> std::io::Result<Outcome> {
    drive(s, dir, prior, None)
}

fn run_one(s: &Small, dir: &Path, prior: &str) -> std::io::Result<Outcome> {
    drive(s, dir, prior, Some(0.0))
}

fn assert_same_files(a: &Path, b: &Path, names: &[&str]) {
    for name in names {
        assert_eq!(
            std::fs::read(a.join(name)).unwrap(),
            std::fs::read(b.join(name)).unwrap(),
            "{name}"
        );
    }
}

#[test]
fn a_paused_and_resumed_solve_matches_an_uninterrupted_one() {
    // This game first meets the 0.001 target between iterations 64 and 128,
    // so an uninterrupted run converges at the scheduled 128. A driver that
    // certified whenever it paused would stop at an earlier, unscheduled
    // iteration with a different policy.
    let s = small();
    let straight = scratch("straight");
    let first = run_to_end(&s, &straight, "prior").unwrap();
    assert_eq!(first, Outcome::Converged(128));
    let paused = scratch("paused");
    let mut last = run_one(&s, &paused, "prior").unwrap();
    assert_eq!(last, Outcome::Paused(1));
    while let Outcome::Paused(_) = last {
        last = run_one(&s, &paused, "prior").unwrap();
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
    let strip = |t: String| t.split(",\"seconds\"").next().unwrap().to_owned();
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
    let s = small();
    let dir = scratch("other-prior");
    assert_eq!(run_one(&s, &dir, "prior").unwrap(), Outcome::Paused(1));
    let err = run_one(&s, &dir, "other").unwrap_err();
    assert!(err.to_string().contains("different inputs"), "{err}");
}

#[test]
fn resume_rejects_a_damaged_checkpoint() {
    let s = small();
    let dir = scratch("damaged");
    assert_eq!(run_one(&s, &dir, "prior").unwrap(), Outcome::Paused(1));
    let regret = dir.join("checkpoint-1/regret.bin");
    let mut bytes = std::fs::read(&regret).unwrap();
    bytes[0] ^= 1;
    std::fs::write(&regret, bytes).unwrap();
    let err = run_one(&s, &dir, "prior").unwrap_err();
    assert!(
        err.to_string().contains("does not match its digest"),
        "{err}"
    );
    // A manifest that lost a field is refused by name.
    let manifest = dir.join("checkpoint.json");
    let json = std::fs::read_to_string(&manifest).unwrap();
    std::fs::write(&manifest, json.replace("\"regret_sha256\"", "\"gone\"")).unwrap();
    let err = run_one(&s, &dir, "prior").unwrap_err();
    assert!(err.to_string().contains("lacks regret_sha256"), "{err}");
}

#[test]
fn a_solve_stops_at_its_iteration_cap() {
    let s = small();
    let dir = scratch("capped");
    let trees = SmallTrees(&s.trees);
    let outcome = driver::run(&dir, &s.game(), &trees, &id("prior"), None, 2).unwrap();
    assert_eq!(outcome, Outcome::Capped(2));
    assert!(dir.join("checkpoint-2").exists());
}

#[test]
fn certificates_follow_the_fixed_schedule() {
    let certified: Vec<u32> = (1..=300).filter(|&i| driver::scheduled(i)).collect();
    assert_eq!(certified, [1, 8, 32, 128, 256]);
}

#[test]
fn best_responses_match_an_expectimax_replay() {
    let s = matched();
    let game = s.game();
    for iterations in [1, 3] {
        let policy = solve(&s, 2, iterations).rounded(&game);
        let c = certificate(&game, &SmallTrees(&s.trees), &policy);
        let best = |responder| {
            s.over_deals(|state, p, d| replay(&s, &policy, state, p, d, 0, Some(responder)))
        };
        // Best-response values carry Q^3 less scale than joint values.
        let q3 = i128::from(Q).pow(3);
        assert_eq!(c.upper * q3, best(0), "Pone best response");
        assert_eq!(c.lower * q3, best(1), "Dealer best response");
        assert!(c.upper > c.lower);
    }
}

/// Regression pin for floating-point operation order. Its authority is the
/// full-size check in README.md: the code that produced these digests also
/// reproduced the research policy ec93951f byte for byte, so any change here
/// is a change in arithmetic order and needs that check re-run.
#[test]
fn small_game_arithmetic_matches_the_reproducing_build() {
    let s = small();
    let solver = solve(&s, 3, 6);
    let digest =
        |v: &[f64]| driver::sha256(&v.iter().flat_map(|x| x.to_le_bytes()).collect::<Vec<u8>>());
    assert_eq!(
        digest(&solver.regret),
        "2631fcb0bf9854636d4098f9c70aa0bfb8f8ae42debed5d7b77763be5415c066"
    );
    assert_eq!(
        digest(&solver.average),
        "4ca385fa5d67e1b17c49e1ec9bcd7a1d2208ec8897b51021fae934166c4d4d28"
    );
}

#[test]
fn a_crash_during_certification_is_certified_on_resume() {
    let s = small();
    let straight = scratch("crash-straight");
    assert_eq!(
        run_to_end(&s, &straight, "inputs").unwrap(),
        Outcome::Converged(128)
    );
    let crashed = scratch("crash");
    assert_eq!(
        run_to_end(&s, &crashed, "inputs").unwrap(),
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
            run_to_end(&s, &crashed, "inputs").unwrap(),
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
fn a_finished_solve_is_not_continued() {
    let s = small();
    let dir = scratch("finished");
    let converged = || run_to_end(&s, &dir, "inputs").unwrap();
    assert_eq!(converged(), Outcome::Converged(128));
    let policy = std::fs::read(dir.join("policy.bin")).unwrap();
    assert_eq!(converged(), Outcome::Converged(128));
    assert_eq!(std::fs::read(dir.join("policy.bin")).unwrap(), policy);
    assert!(!dir.join("checkpoint-129").exists());
    // The finished result stands on its own: no checkpoint is read again.
    std::fs::remove_dir_all(dir.join("checkpoint-128")).unwrap();
    assert_eq!(converged(), Outcome::Converged(128));
    let err = run_to_end(&s, &dir, "other").unwrap_err();
    assert!(err.to_string().contains("different inputs"), "{err}");
    // A policy changed after the solve finished is refused, not returned.
    let mut changed = policy;
    changed[0] ^= 1;
    std::fs::write(dir.join("policy.bin"), changed).unwrap();
    let err = run_to_end(&s, &dir, "inputs").unwrap_err();
    assert!(
        err.to_string().contains("does not match solve.json"),
        "{err}"
    );
    let finished = dir.join("solve.json");
    let json = std::fs::read_to_string(&finished).unwrap();
    std::fs::write(&finished, json.replace("\"identity\"", "\"gone\"")).unwrap();
    let err = run_to_end(&s, &dir, "inputs").unwrap_err();
    assert!(err.to_string().contains("lacks identity"), "{err}");
}
