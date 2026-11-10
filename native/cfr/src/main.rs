//! Command-line entry point. Every subcommand writes into `--output DIR`,
//! flushing each file under a temporary name before renaming it, so an
//! interrupted run never leaves a partial file under a final name.

use cfr_inputs::driver;
use cfr_inputs::game::canonical;
use cfr_inputs::menus::{self, FILES};
use cfr_inputs::trees::{Menus, Tree, offsets_bytes};
use rayon::prelude::*;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::Instant;

const USAGE: &str =
    "usage: cfr-inputs <menus|trees> --output DIR [--range START..END] [--threads N]
       cfr-inputs <offsets|digests> --output DIR [--threads N]";

struct Options {
    command: String,
    output: PathBuf,
    threads: usize,
    range: Option<std::ops::Range<usize>>,
}

/// Parse `START..END`, the files `menus` or `trees` should write.
fn parse_range(value: &str) -> Option<std::ops::Range<usize>> {
    let (start, end) = value.split_once("..")?;
    Some(start.parse().ok()?..end.parse().ok()?)
}

fn parse(args: &[String]) -> Result<Options, String> {
    let command = args.first().ok_or(USAGE)?.clone();
    let (mut output, mut threads, mut range) = (None, 0, None);
    let mut rest = args[1..].iter();
    while let Some(flag) = rest.next() {
        let value = rest.next().ok_or(format!("{flag} needs a value"))?;
        match flag.as_str() {
            "--output" => output = Some(PathBuf::from(value)),
            "--threads" => threads = value.parse().map_err(|_| "--threads must be a number")?,
            "--range" => range = Some(parse_range(value).ok_or("--range must be START..END")?),
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
    ];
    let body: Vec<String> = entries
        .iter()
        .filter_map(|(k, v)| v.as_ref().map(|v| format!("\"{k}\":\"{v}\"")))
        .collect();
    Ok(format!("{{{}}}", body.join(",")))
}

/// The files to write, which must lie within `0..count`.
fn files(o: &Options, count: usize) -> std::io::Result<std::ops::Range<usize>> {
    let range = o.range.clone().unwrap_or(0..count);
    if range.start >= range.end || range.end > count {
        return Err(std::io::Error::other(format!(
            "--range must lie within 0..{count}"
        )));
    }
    Ok(range)
}

fn run(o: &Options) -> std::io::Result<()> {
    let hands = canonical();
    match o.command.as_str() {
        "menus" => {
            let range = files(o, FILES)?;
            let dir = o.output.join("menus");
            std::fs::create_dir_all(&dir)?;
            range.into_par_iter().try_for_each(|k| {
                driver::write_atomic(&dir.join(format!("{k}.bin")), &menus::build(k, &hands))
            })
        }
        "trees" => {
            let range = files(o, 1820)?;
            let m = Menus::load(&o.output)?;
            let dir = o.output.join("trees");
            std::fs::create_dir_all(&dir)?;
            range.into_par_iter().try_for_each(|p| {
                let bytes = Tree::build(&m, &hands, p).to_bytes();
                driver::write_atomic(&dir.join(format!("{p}.bin")), &bytes)
            })
        }
        "digests" => {
            println!("{}", digests(&o.output)?);
            Ok(())
        }
        "offsets" => {
            let m = Menus::load(&o.output)?;
            driver::write_atomic(&o.output.join("offsets.bin"), &offsets_bytes(&m))
        }
        other => Err(std::io::Error::other(format!(
            "unknown command {other}\n{USAGE}"
        ))),
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let o = match parse(&args) {
        Ok(o) => o,
        Err(e) => {
            eprintln!("{e}");
            return ExitCode::from(2);
        }
    };
    if o.threads > 0 {
        rayon::ThreadPoolBuilder::new()
            .num_threads(o.threads)
            .build_global()
            .expect("thread pool");
    }
    let start = Instant::now();
    match run(&o) {
        Ok(()) => {
            println!(
                "{{\"command\":\"{}\",\"seconds\":{:.3}}}",
                o.command,
                start.elapsed().as_secs_f64()
            );
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("{e}");
            ExitCode::FAILURE
        }
    }
}
