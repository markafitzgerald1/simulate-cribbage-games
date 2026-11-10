//! The command-line binary: argument errors, and every subcommand run end to
//! end on output folders small enough for a test. The commands' results are
//! compared with the library functions they wrap, so these tests check the
//! wiring (paths, parsing, exit codes), not the arithmetic.

use cfr_inputs::driver;
use cfr_inputs::game::canonical;
use cfr_inputs::menus::{self, FILES, NIL};
use cfr_inputs::trees::{Menus, Tree, offsets_bytes};
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
    ] {
        let (_, stderr) = expect(&args, 1);
        assert!(stderr.contains(message), "{args:?}: {stderr}");
    }
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
    let p = 77;
    expect(&["menus", "--output", out, "--range", "1820..3640"], 0);
    let one = format!("{p}..{}", p + 1);
    expect(
        &["menus", "--output", out, "--range", &one, "--threads", "2"],
        0,
    );
    for k in 0..1820 {
        let path = dir.join("menus").join(format!("{k}.bin"));
        if k == p {
            assert_eq!(std::fs::read(&path).unwrap(), menus::build(k, &hands));
        } else {
            assert!(!path.exists());
            std::fs::write(path, []).unwrap();
        }
    }
    let dealer = dir.join("menus").join("3000.bin");
    assert_eq!(std::fs::read(dealer).unwrap(), menus::build(3000, &hands));
    expect(&["trees", "--output", out, "--range", &one], 0);
    let menus = Menus::load(&dir).unwrap();
    let built = std::fs::read(dir.join("trees").join(format!("{p}.bin"))).unwrap();
    let tree = Tree::build(&menus, &hands, p);
    assert_eq!(built, tree.to_bytes());
    assert_eq!(Tree::read(&dir, p).unwrap().to_bytes(), built);
    assert!(!dir.join("trees").join(format!("{}.bin", p + 1)).exists());

    expect(&["offsets", "--output", out], 0);
    let offsets = std::fs::read(dir.join("offsets.bin")).unwrap();
    assert_eq!(offsets, offsets_bytes(&menus));
    // With every tree file present, `digests` covers all three outputs.
    let none = no_trees();
    for q in (0..1820).filter(|&q| q != p) {
        std::fs::write(dir.join("trees").join(format!("{q}.bin")), none.to_bytes()).unwrap();
    }
    assert_digests(&dir, &["offsets"]);
}
