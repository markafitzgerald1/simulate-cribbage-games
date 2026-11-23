//! Command-line entry point. Every subcommand writes into `--output DIR`,
//! flushing each file under a temporary name before renaming it, so an
//! interrupted run never leaves a partial file under a final name.

use cfr_inputs::driver::{self, Outcome};
use cfr_inputs::game::{canonical, feasible};
use cfr_inputs::menus::{self, FILES};
use cfr_inputs::solve::{Game, MASS_LIMIT, POLICY_UNITS, TreeFiles};
use cfr_inputs::support::Pair;
use cfr_inputs::trees::{Menus, Tree, offsets_bytes};
use rayon::prelude::*;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::Instant;

const USAGE: &str = "usage: cfr-inputs <menus|trees> --output DIR [--range START..END] [--threads N]
       cfr-inputs <offsets|digests> --output DIR [--threads N]
       cfr-inputs solve --output DIR --prior FILE [--pause-after-seconds S] [--max-iterations N] [--threads N]
       cfr-inputs support --output DIR (--policy FILE --prior FILE)... [--threads N]";

/// The parsed command line.
struct Options {
    command: String,
    output: PathBuf,
    threads: usize,
    priors: Vec<PathBuf>,
    policies: Vec<PathBuf>,
    pause_after: Option<f64>,
    max_iterations: u32,
    range: Option<std::ops::Range<usize>>,
}

/// Parse `START..END`, the files `menus` or `trees` should write.
fn parse_range(value: &str) -> Option<std::ops::Range<usize>> {
    let (start, end) = value.split_once("..")?;
    Some(start.parse().ok()?..end.parse().ok()?)
}

/// Parse the arguments after the program name: the subcommand, then
/// `--flag value` pairs in any order. An error is the message to print; `main`
/// exits with status 2 for it, the usual code for a usage error.
fn parse(args: &[String]) -> Result<Options, String> {
    let command = args.first().ok_or(USAGE)?.clone();
    let (mut output, mut threads, mut pause_after, mut max_iterations) = (None, 0, None, 4096);
    let (mut priors, mut policies, mut range) = (Vec::new(), Vec::new(), None);
    let mut rest = args[1..].iter();
    while let Some(flag) = rest.next() {
        let value = rest.next().ok_or(format!("{flag} needs a value"))?;
        match flag.as_str() {
            "--output" => output = Some(PathBuf::from(value)),
            "--threads" => threads = value.parse().map_err(|_| "--threads must be a number")?,
            "--prior" => priors.push(PathBuf::from(value)),
            "--policy" => policies.push(PathBuf::from(value)),
            "--range" => range = Some(parse_range(value).ok_or("--range must be START..END")?),
            "--pause-after-seconds" => {
                pause_after = Some(
                    value
                        .parse()
                        .map_err(|_| "--pause-after-seconds must be a number")?,
                );
            }
            "--max-iterations" => {
                max_iterations = value
                    .parse()
                    .map_err(|_| "--max-iterations must be a number")?;
            }
            _ => return Err(format!("unknown option {flag}\n{USAGE}")),
        }
    }
    if range.is_some() && command != "menus" && command != "trees" {
        return Err(format!("--range applies only to menus and trees\n{USAGE}"));
    }
    Ok(Options {
        command,
        output: output.ok_or(USAGE)?,
        threads,
        priors,
        policies,
        pause_after,
        max_iterations,
        range,
    })
}

/// SHA-256 of each single-file output, and for the menu and tree folders the
/// SHA-256 of their per-file hex digests, one per line in file order.
fn digests(dir: &Path) -> std::io::Result<String> {
    let folder = |name: &str, count: usize| -> std::io::Result<Option<String>> {
        if !dir.join(name).exists() {
            return Ok(None);
        }
        driver::folder_sha256(&dir.join(name), count).map(Some)
    };
    let file = |name: &str| -> std::io::Result<Option<String>> {
        let path = dir.join(name);
        Ok(if path.exists() {
            Some(driver::sha256(&std::fs::read(path)?))
        } else {
            None
        })
    };
    let entries = [
        ("menus", folder("menus", FILES)?),
        ("trees", folder("trees", 1820)?),
        ("offsets", file("offsets.bin")?),
        ("policy", file("policy.bin")?),
        ("support", file("support.bin")?),
    ];
    let body: Vec<String> = entries
        .iter()
        .filter_map(|(name, folder_digest)| {
            folder_digest
                .as_ref()
                .map(|digest| format!("\"{name}\":\"{digest}\""))
        })
        .collect();
    Ok(format!("{{{}}}", body.join(",")))
}

/// Read a prior: the integer weight of every (Pone hand, Dealer hand) deal,
/// 1,820 x 1,820 little-endian `u64` in Pone-major order.
fn read_prior(bytes: &[u8]) -> std::io::Result<Vec<u64>> {
    if bytes.len() != 1820 * 1820 * 8 {
        return Err(std::io::Error::other(
            "prior must be 1820 x 1820 little-endian u64",
        ));
    }
    Ok(bytes
        .as_chunks::<8>()
        .0
        .iter()
        .map(|&chunk| u64::from_le_bytes(chunk))
        .collect())
}

/// The prior's total weight, after refusing a prior whose total overflows
/// and one with no weight.
fn prior_mass(chance: &[u64]) -> std::io::Result<u64> {
    let mass = chance
        .iter()
        .try_fold(0u64, |total, &weight| total.checked_add(weight))
        .ok_or_else(|| std::io::Error::other("prior mass overflows"))?;
    if mass == 0 {
        return Err(std::io::Error::other("prior has no weight"));
    }
    Ok(mass)
}

/// Refuse a prior that weights a deal no pair of hands can make: no tree
/// covers it, so its missing root would read as a leaf.
fn check_feasible(chance: &[u64]) -> std::io::Result<()> {
    let hands = canonical();
    if let Some(pair) = (0..chance.len())
        .find(|&pair| chance[pair] != 0 && !feasible(&hands[pair / 1820], &hands[pair % 1820]))
    {
        return Err(std::io::Error::other(format!(
            "prior weights an impossible deal: Pone hand {}, Dealer hand {}",
            pair / 1820,
            pair % 1820
        )));
    }
    Ok(())
}

/// Refuse a policy that is not a rounded policy for `menus`: one value per
/// action, and exactly `POLICY_UNITS` units in every menu.
fn check_policy(menus: &Menus, policy: &[u16]) -> std::io::Result<()> {
    if policy.len() as u64 != menus.actions {
        return Err(std::io::Error::other(format!(
            "policy has {} actions, the menus have {}",
            policy.len(),
            menus.actions
        )));
    }
    for menu in 0..menus.len() {
        let off = menus.offset[menu] as usize;
        let units: u32 = policy[off..off + usize::from(menus.width[menu])]
            .iter()
            .map(|&units| u32::from(units))
            .sum();
        if units != POLICY_UNITS {
            return Err(std::io::Error::other(format!(
                "policy menu {menu} holds {units} units, not {POLICY_UNITS}"
            )));
        }
    }
    Ok(())
}

/// Compute the support bits for the `--policy`/`--prior` pairs, matched in
/// the order given, and write `support.bin`: one byte per menu, with bit `k`
/// set when the menu is reached with positive weight under prior `k` while
/// the opponent follows policy `k`.
fn support(options: &Options) -> std::io::Result<()> {
    if options.policies.is_empty() || options.policies.len() != options.priors.len() {
        return Err(std::io::Error::other(
            "support needs matching --policy and --prior pairs",
        ));
    }
    if options.policies.len() > 8 {
        return Err(std::io::Error::other(
            "support takes at most eight --policy and --prior pairs",
        ));
    }
    let policies = options
        .policies
        .iter()
        .map(|path| {
            let bytes = std::fs::read(path)?;
            let (words, rest) = bytes.as_chunks::<2>();
            if !rest.is_empty() {
                return Err(std::io::Error::other("policy must be little-endian u16"));
            }
            Ok(words
                .iter()
                .map(|&chunk| u16::from_le_bytes(chunk))
                .collect())
        })
        .collect::<std::io::Result<Vec<Vec<u16>>>>()?;
    let priors = options
        .priors
        .iter()
        .map(|path| {
            let prior = read_prior(&std::fs::read(path)?)?;
            prior_mass(&prior)?;
            check_feasible(&prior)?;
            Ok(prior)
        })
        .collect::<std::io::Result<Vec<_>>>()?;
    let menus = Menus::load(&options.output)?;
    for policy in &policies {
        check_policy(&menus, policy)?;
    }
    let pairs: Vec<Pair> = policies
        .iter()
        .zip(&priors)
        .map(|(policy, prior)| Pair { policy, prior })
        .collect();
    // A missing tree file is an I/O error, reported as one, not a panic.
    for pone_hand in 0..1820 {
        std::fs::metadata(
            options
                .output
                .join("trees")
                .join(format!("{pone_hand}.bin")),
        )?;
    }
    let flags = cfr_inputs::support::support(&menus, &TreeFiles(&options.output), &pairs);
    driver::write_atomic(&options.output.join("support.bin"), &flags)
}

/// Run or resume the CFR+ solve on one prior. Before any work it rejects a
/// prior with no weight, one whose total weight exceeds what the certificate's
/// exact arithmetic can carry, and one that weights a deal no tree covers.
/// The input identity (digests of the prior, menus and trees) ties every
/// checkpoint to these inputs, so a resume on different inputs is refused.
fn solve(options: &Options) -> std::io::Result<ExitCode> {
    let [path] = options.priors.as_slice() else {
        return Err(std::io::Error::other("solve needs exactly one --prior"));
    };
    let bytes = std::fs::read(path)?;
    let chance = read_prior(&bytes)?;
    let mass = prior_mass(&chance)?;
    if mass > MASS_LIMIT {
        return Err(std::io::Error::other(format!(
            "prior mass {mass} exceeds the certificate's limit {MASS_LIMIT}"
        )));
    }
    check_feasible(&chance)?;
    let menus = Menus::load(&options.output)?;
    let game = Game::new(&menus, &chance);
    let menus_digest = driver::folder_sha256(&options.output.join("menus"), FILES)?;
    let trees_digest = driver::folder_sha256(&options.output.join("trees"), 1820)?;
    let id = driver::identity(&driver::sha256(&bytes), &menus_digest, &trees_digest);
    let trees = TreeFiles(&options.output);
    let (pause, cap) = (options.pause_after, options.max_iterations);
    let outcome = driver::run(&options.output, &game, &trees, &id, pause, cap)?;
    println!("{outcome:?}");
    Ok(match outcome {
        Outcome::Converged(_) => ExitCode::SUCCESS,
        Outcome::Paused(_) => ExitCode::from(3),
        Outcome::Capped(_) => ExitCode::from(4),
    })
}

/// The files to write, which must lie within `0..count`.
fn files(options: &Options, count: usize) -> std::io::Result<std::ops::Range<usize>> {
    let range = options.range.clone().unwrap_or(0..count);
    if range.start >= range.end || range.end > count {
        return Err(std::io::Error::other(format!(
            "--range must lie within 0..{count}"
        )));
    }
    Ok(range)
}

/// Run one subcommand. `menus` and `trees` spread their files across the
/// rayon threads; `trees` and `offsets` first load every menu file, so they
/// need a complete `menus` folder.
fn run(options: &Options) -> std::io::Result<()> {
    let hands = canonical();
    match options.command.as_str() {
        "menus" => {
            let range = files(options, FILES)?;
            let dir = options.output.join("menus");
            std::fs::create_dir_all(&dir)?;
            range.into_par_iter().try_for_each(|file_index| {
                driver::write_atomic(
                    &dir.join(format!("{file_index}.bin")),
                    &menus::build(file_index, &hands),
                )
            })
        }
        "trees" => {
            let range = files(options, 1820)?;
            let loaded_menus = Menus::load(&options.output)?;
            let dir = options.output.join("trees");
            std::fs::create_dir_all(&dir)?;
            range.into_par_iter().try_for_each(|pone_hand| {
                let bytes = Tree::build(&loaded_menus, &hands, pone_hand).to_bytes();
                driver::write_atomic(&dir.join(format!("{pone_hand}.bin")), &bytes)
            })
        }
        "support" => support(options),
        "digests" => {
            println!("{}", digests(&options.output)?);
            Ok(())
        }
        "offsets" => {
            let loaded_menus = Menus::load(&options.output)?;
            driver::write_atomic(
                &options.output.join("offsets.bin"),
                &offsets_bytes(&loaded_menus),
            )
        }
        other => Err(std::io::Error::other(format!(
            "unknown command {other}\n{USAGE}"
        ))),
    }
}

/// Exit status 0 on success, 2 when the options cannot be parsed, and 1 when
/// the command returns an error (an I/O error, rejected input, or an unknown
/// subcommand given valid options). Input that breaks an internal check,
/// such as a truncated menu file, panics and aborts instead. On success the
/// last line printed is JSON naming the subcommand and its elapsed seconds;
/// `digests` prints its digest object on the line before.
/// `solve` instead prints its outcome and exits 0 when converged, 3 when it
/// pauses on its time budget and 4 at the iteration cap, so a workflow can
/// resume a pause and fail a cap without mistaking either for a crash. An
/// iteration that meets the target converges even if the budget has run out;
/// otherwise the budget is checked after every iteration, so a budget that
/// runs out on the last allowed iteration gives 3, and resuming with the same
/// `--max-iterations` then gives 4.
fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let options = match parse(&args) {
        Ok(options) => options,
        Err(error) => {
            eprintln!("{error}");
            return ExitCode::from(2);
        }
    };
    if options.threads > 0 {
        rayon::ThreadPoolBuilder::new()
            .num_threads(options.threads)
            .build_global()
            .expect("thread pool");
    }
    let start = Instant::now();
    if options.command == "solve" {
        return solve(&options).unwrap_or_else(|error| {
            eprintln!("{error}");
            ExitCode::FAILURE
        });
    }
    match run(&options) {
        Ok(()) => {
            println!(
                "{{\"command\":\"{}\",\"seconds\":{:.3}}}",
                options.command,
                start.elapsed().as_secs_f64()
            );
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("{error}");
            ExitCode::FAILURE
        }
    }
}
