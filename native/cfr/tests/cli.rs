//! The command-line binary: argument errors, and every subcommand run end to
//! end on output folders small enough for a test. The commands' results are
//! compared with the library functions they wrap, so these tests check the
//! wiring (paths, parsing, exit codes), not the arithmetic.

mod common;

use cfr_inputs::driver::{self, Outcome};
use cfr_inputs::game::canonical;
use cfr_inputs::menus::{self, FILES, NIL};
use cfr_inputs::trees::{Menus, Tree, offsets_bytes};
use common::{Small, SmallTrees, small};
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

fn cli(args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_cfr-inputs"))
        .args(args)
        .output()
        .unwrap()
}

fn scratch(name: &str) -> PathBuf {
    let dir = PathBuf::from(env!("CARGO_TARGET_TMPDIR")).join(format!("cli-{name}"));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn text(bytes: &[u8]) -> String {
    String::from_utf8_lossy(bytes).into_owned()
}

/// A tree file for a Pone hand with no deals: every root absent.
fn no_trees() -> Tree {
    Tree {
        roots: vec![NIL; 1820],
        nodes: Vec::new(),
        edges: Vec::new(),
    }
}

/// `digests` prints the menu and tree folder digests and those of the named
/// single-file outputs, in the binary's order.
fn assert_digests(dir: &Path, files: &[&str]) {
    let (stdout, _) = expect(&["digests", "--output", dir.to_str().unwrap()], 0);
    let menus = driver::folder_sha256(&dir.join("menus"), FILES).unwrap();
    let trees = driver::folder_sha256(&dir.join("trees"), 1820).unwrap();
    let mut fields = vec![
        format!("\"menus\":\"{menus}\""),
        format!("\"trees\":\"{trees}\""),
    ];
    for name in files {
        let bytes = std::fs::read(dir.join(format!("{name}.bin"))).unwrap();
        fields.push(format!("\"{name}\":\"{}\"", driver::sha256(&bytes)));
    }
    let expected = format!("{{{}}}", fields.join(","));
    assert_eq!(stdout.lines().next().unwrap(), expected);
}

/// Run the binary and check its exit code; returns stdout and stderr.
fn expect(args: &[&str], code: i32) -> (String, String) {
    let out = cli(args);
    let (stdout, stderr) = (text(&out.stdout), text(&out.stderr));
    assert_eq!(out.status.code(), Some(code), "{args:?}: {stdout}{stderr}");
    (stdout, stderr)
}

#[test]
fn bad_arguments_exit_with_usage_errors() {
    for (args, message) in [
        (&[][..], "usage"),
        (&["menus"][..], "usage"),
        (&["menus", "--output"][..], "--output needs a value"),
        (&["menus", "--colour", "x"][..], "unknown option --colour"),
        (
            &["menus", "--threads", "x"][..],
            "--threads must be a number",
        ),
        (
            &["solve", "--pause-after-seconds", "x"][..],
            "--pause-after-seconds",
        ),
        (&["solve", "--max-iterations", "x"][..], "--max-iterations"),
        (&["menus", "--range", "5"][..], "--range must be START..END"),
        (
            &["menus", "--range", "a..5"][..],
            "--range must be START..END",
        ),
        (
            &["offsets", "--output", "x", "--range", "0..1"][..],
            "--range applies only to menus and trees",
        ),
    ] {
        let (_, stderr) = expect(args, 2);
        assert!(stderr.contains(message), "{args:?}: {stderr}");
    }
}

#[test]
fn failing_commands_exit_with_one() {
    let dir = scratch("failing");
    let out = dir.to_str().unwrap();
    let small_prior = dir.join("small-prior.bin");
    std::fs::write(&small_prior, [0u8; 8]).unwrap();
    let full_prior = dir.join("full-prior.bin");
    std::fs::write(&full_prior, vec![u8::MAX; 1820 * 1820 * 8]).unwrap();
    let (small_prior, full_prior) = (small_prior.to_str().unwrap(), full_prior.to_str().unwrap());
    for (args, message) in [
        (vec!["unknown", "--output", out], "unknown command unknown"),
        (
            vec!["menus", "--output", out, "--range", "3..2"],
            "--range must lie within 0..3640",
        ),
        (
            vec!["trees", "--output", out, "--range", "0..1821"],
            "--range must lie within 0..1820",
        ),
        (vec!["trees", "--output", out], "No such file"),
        (
            vec!["solve", "--output", out],
            "solve needs exactly one --prior",
        ),
        (
            vec!["solve", "--output", out, "--prior", small_prior],
            "prior must be 1820 x 1820",
        ),
        (
            vec!["solve", "--output", out, "--prior", full_prior],
            "prior mass overflows",
        ),
    ] {
        let (_, stderr) = expect(&args, 1);
        assert!(stderr.contains(message), "{args:?}: {stderr}");
    }
}

/// Write the small game's menus and trees as the binary lays them out: every
/// menu file (empty outside the small game) and every tree file (no roots
/// outside its two Pone hands). Returns the prior's path.
fn small_output(s: &Small, dir: &Path) -> PathBuf {
    let hands = canonical();
    std::fs::create_dir_all(dir.join("menus")).unwrap();
    std::fs::create_dir_all(dir.join("trees")).unwrap();
    let pones: Vec<usize> = s.trees.keys().copied().collect();
    let mut dealers = Vec::new();
    for p in &pones {
        dealers.extend((0..1820).filter(|&d| s.chance[p * 1820 + d] != 0));
    }
    for k in 0..FILES {
        let wanted = pones.contains(&k) || (k >= 1820 && dealers.contains(&(k - 1820)));
        let bytes = if wanted {
            menus::build(k, &hands)
        } else {
            Vec::new()
        };
        std::fs::write(dir.join("menus").join(format!("{k}.bin")), bytes).unwrap();
    }
    let none = no_trees();
    for p in 0..1820 {
        let bytes = s.trees.get(&p).unwrap_or(&none).to_bytes();
        std::fs::write(dir.join("trees").join(format!("{p}.bin")), bytes).unwrap();
    }
    let prior = dir.join("prior.bin");
    let bytes: Vec<u8> = s.chance.iter().flat_map(|w| w.to_le_bytes()).collect();
    std::fs::write(&prior, bytes).unwrap();
    prior
}

/// The small game written to a fresh folder: the game, the folder and the
/// prior's path.
fn small_folder(name: &str) -> (Small, PathBuf, String) {
    let s = small();
    let dir = scratch(name);
    let prior = small_output(&s, &dir).to_str().unwrap().to_owned();
    (s, dir, prior)
}

#[test]
fn solve_and_digests_run_on_a_small_output() {
    let (s, dir, prior) = small_folder("small");
    let (out, prior) = (dir.to_str().unwrap(), prior.as_str());

    let (stdout, _) = expect(
        &["solve", "--output", out, "--prior", prior, "--threads", "2"],
        0,
    );
    assert_eq!(stdout.trim(), "Converged(128)");
    // The same solve run in process, from the same prior, writes the same policy.
    let reference = scratch("small-reference");
    let game = s.game();
    let outcome = driver::run(&reference, &game, &SmallTrees(&s.trees), "x", None, 4096).unwrap();
    assert_eq!(outcome, Outcome::Converged(128));
    let policy = std::fs::read(dir.join("policy.bin")).unwrap();
    assert_eq!(policy, std::fs::read(reference.join("policy.bin")).unwrap());
    // A zero budget pauses after one iteration, and a cap stops at it.
    let (_, held, held_prior) = small_folder("paused");
    let (out_held, prior_held) = (held.to_str().unwrap(), held_prior.as_str());
    let (stdout, _) = expect(
        &[
            "solve",
            "--output",
            out_held,
            "--prior",
            prior_held,
            "--pause-after-seconds",
            "0",
        ],
        3,
    );
    assert_eq!(stdout.trim(), "Paused(1)");
    let (stdout, _) = expect(
        &[
            "solve",
            "--output",
            out_held,
            "--prior",
            prior_held,
            "--max-iterations",
            "2",
        ],
        4,
    );
    assert_eq!(stdout.trim(), "Capped(2)");
    // Running the converged solve again returns the recorded result.
    let (stdout, _) = expect(&["solve", "--output", out, "--prior", prior], 0);
    assert_eq!(stdout.trim(), "Converged(128)");

    assert_digests(&dir, &["policy"]);
}

#[test]
fn digests_of_an_empty_output_are_empty() {
    let dir = scratch("empty");
    let (stdout, _) = expect(&["digests", "--output", dir.to_str().unwrap()], 0);
    assert_eq!(stdout.lines().next().unwrap(), "{}");
}

#[test]
fn menus_and_trees_write_the_files_in_their_range() {
    // Every Dealer menu, since a Pone hand's trees reach almost every Dealer
    // hand, plus one Pone menu and its trees.
    let dir = scratch("range");
    let out = dir.to_str().unwrap();
    let hands = canonical();
    let pone_hand = 77;
    expect(&["menus", "--output", out, "--range", "1820..3640"], 0);
    let one = format!("{pone_hand}..{}", pone_hand + 1);
    expect(
        &["menus", "--output", out, "--range", &one, "--threads", "2"],
        0,
    );
    for file_index in 0..1820 {
        let path = dir.join("menus").join(format!("{file_index}.bin"));
        if file_index == pone_hand {
            assert_eq!(
                std::fs::read(&path).unwrap(),
                menus::build(file_index, &hands)
            );
        } else {
            assert!(!path.exists());
            std::fs::write(path, []).unwrap();
        }
    }
    let dealer = dir.join("menus").join("3000.bin");
    assert_eq!(std::fs::read(dealer).unwrap(), menus::build(3000, &hands));
    expect(&["trees", "--output", out, "--range", &one], 0);
    let menus = Menus::load(&dir).unwrap();
    let built = std::fs::read(dir.join("trees").join(format!("{pone_hand}.bin"))).unwrap();
    let tree = Tree::build(&menus, &hands, pone_hand);
    assert_eq!(built, tree.to_bytes());
    assert_eq!(Tree::read(&dir, pone_hand).unwrap().to_bytes(), built);
    assert!(
        !dir.join("trees")
            .join(format!("{}.bin", pone_hand + 1))
            .exists()
    );

    expect(&["offsets", "--output", out], 0);
    let offsets = std::fs::read(dir.join("offsets.bin")).unwrap();
    assert_eq!(offsets, offsets_bytes(&menus));
    // With every tree file present, `digests` covers all three outputs.
    let none = no_trees();
    for other_hand in (0..1820).filter(|&other_hand| other_hand != pone_hand) {
        std::fs::write(
            dir.join("trees").join(format!("{other_hand}.bin")),
            none.to_bytes(),
        )
        .unwrap();
    }
    assert_digests(&dir, &["offsets"]);
}
