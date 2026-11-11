//! Resumable solve driver: iterate, checkpoint after every iteration, and
//! certify on a fixed schedule.
//!
//! The research driver certified whenever its time budget ran out, and stopped
//! for good if that certificate met the 0.001 exposure target. A run paused
//! and resumed could then end on a different iteration, and so a different
//! policy, from an uninterrupted run. Here pausing never certifies: the
//! certificate schedule depends only on the iteration number (1, 8, 32 and
//! every multiple of 128, which includes the research schedule's 1, 8, 32 and
//! 128), so a resumed solve ends on exactly the policy an uninterrupted one
//! would.
//!
//! Layout under the output directory:
//! * `checkpoint-N/regret.bin`, `checkpoint-N/average.bin`: little-endian
//!   `f64` arrays after iteration `N`; only the newest generation is kept.
//! * `checkpoint.json`: the committed generation, the SHA-256 of both arrays
//!   and the input identity, checked before any resume.
//! * `policy-N.bin`, `certificate-N.json`: rounded policy (`u16` per action)
//!   and its exact certificate at each scheduled iteration. After a crash
//!   either may exist without the other; the resume certifies again and
//!   rewrites both identically.
//! * `policy.bin`, `solve.json`: the final policy once the target is met;
//!   `solve.json` is written last and marks the solve finished.
//!
//! The research driver certified only at 1, 8, 32 and 128; it never needed
//! more, because the pinned solve met its target at 128.

use super::solve::{Certificate, Game, Q, Solver, Trees};
use sha2::{Digest, Sha256};
use std::io;
use std::path::Path;
use std::time::Instant;

/// Whether iteration `it` is certified.
pub fn scheduled(it: u32) -> bool {
    it == 1 || it == 8 || it == 32 || it.is_multiple_of(128)
}

pub fn sha256(bytes: &[u8]) -> String {
    use std::fmt::Write;
    Sha256::digest(bytes)
        .iter()
        .fold(String::new(), |mut hex, byte| {
            write!(hex, "{byte:02x}").expect("writing to a String");
            hex
        })
}

/// SHA-256 of the per-file SHA-256 hex digests of `dir/{0..count}.bin`, one
/// per line in file order.
pub fn folder_sha256(dir: &Path, count: usize) -> io::Result<String> {
    use rayon::prelude::*;
    let lines = (0..count)
        .into_par_iter()
        .map(|file_index| Ok(sha256(&std::fs::read(dir.join(format!("{file_index}.bin")))?) + "\n"))
        .collect::<io::Result<Vec<String>>>()?;
    Ok(sha256(lines.concat().as_bytes()))
}

fn f64_bytes(v: &[f64]) -> Vec<u8> {
    v.iter().flat_map(|x| x.to_le_bytes()).collect()
}

fn f64s(bytes: &[u8]) -> Vec<f64> {
    let (chunks, rest) = bytes.as_chunks::<8>();
    assert!(rest.is_empty(), "f64 array length");
    chunks.iter().map(|&c| f64::from_le_bytes(c)).collect()
}

/// Write to a temporary name, flush it to disk, then rename over `path`, so a
/// crash leaves either the old file or the complete new one. The rename itself
/// is durable only once the parent directory is synced, which the solve loop
/// does before deleting the previous checkpoint generation.
pub fn write_atomic(path: &Path, bytes: &[u8]) -> io::Result<()> {
    use std::io::Write;
    let mut tmp = path.as_os_str().to_owned();
    tmp.push(".tmp");
    let mut file = std::fs::File::create(&tmp)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    drop(file);
    std::fs::rename(&tmp, path)
}

/// Read one field of the flat JSON objects this module writes. A quoted value
/// runs to the next quote (values never contain quotes or escapes); a bare
/// value runs to the next comma or closing brace.
fn field<'a>(json: &'a str, name: &str) -> Option<&'a str> {
    let key = format!("\"{name}\":");
    let rest = json[json.find(&key)? + key.len()..].trim_start();
    if let Some(quoted) = rest.strip_prefix('"') {
        return Some(&quoted[..quoted.find('"')?]);
    }
    Some(rest[..rest.find([',', '}'])?].trim())
}

/// The input identity a checkpoint is bound to: the prior's SHA-256 and the
/// menu and tree folder digests.
pub fn identity(prior_sha256: &str, menus: &str, trees: &str) -> String {
    format!("prior:{prior_sha256},menus:{menus},trees:{trees}")
}

/// Flush a directory's entries (new names, renames, removals) to disk.
fn sync_dir(dir: &Path) -> io::Result<()> {
    std::fs::File::open(dir)?.sync_all()
}

/// How a call to [`run`] ended.
#[derive(Debug, PartialEq, Eq)]
pub enum Outcome {
    /// The exposure target was met at this iteration.
    Converged(u32),
    /// The time budget ran out after this committed iteration.
    Paused(u32),
    /// The iteration cap was reached without meeting the target.
    Capped(u32),
}

fn certificate_json(it: u32, c: &Certificate, seconds: f64) -> String {
    let q3 = i128::from(Q).pow(3);
    format!(
        "{{\"iteration\":{it},\"joint_num\":\"{}\",\"joint_den\":\"{}\",\"upper_num\":\"{}\",\"lower_num\":\"{}\",\"br_den\":\"{}\",\"exposure\":{},\"seconds\":{seconds:.3}}}\n",
        c.joint,
        c.denominator * q3,
        c.upper,
        c.lower,
        c.denominator,
        c.exposure()
    )
}

/// Certify iteration `it`: write its rounded policy and certificate, and on
/// meeting the target also `policy.bin` and `solve.json`, the latter last.
fn certify(
    dir: &Path,
    game: &Game,
    trees: &dyn Trees,
    solver: &Solver,
    it: u32,
    identity: &str,
) -> io::Result<bool> {
    let began = Instant::now();
    let policy = solver.rounded(game);
    let bytes: Vec<u8> = policy.iter().flat_map(|x| x.to_le_bytes()).collect();
    write_atomic(&dir.join(format!("policy-{it}.bin")), &bytes)?;
    let c = super::solve::certificate(game, trees, &policy);
    let json = certificate_json(it, &c, began.elapsed().as_secs_f64());
    write_atomic(&dir.join(format!("certificate-{it}.json")), json.as_bytes())?;
    if !c.converged(game.mass) {
        return Ok(false);
    }
    write_atomic(&dir.join("policy.bin"), &bytes)?;
    // `policy.bin` is on disk before `solve.json`, which vouches for it.
    sync_dir(dir)?;
    let finished = format!(
        "{{\"iteration\":{it},\"policy_sha256\":\"{}\",\"identity\":\"{identity}\",\"exposure\":{}}}\n",
        sha256(&bytes),
        c.exposure()
    );
    write_atomic(&dir.join("solve.json"), finished.as_bytes())?;
    Ok(true)
}

/// The recorded result of a finished solve, after checking it was made from
/// these inputs and that `policy.bin` is the policy it recorded.
fn finished(dir: &Path, identity: &str) -> io::Result<Option<u32>> {
    let path = dir.join("solve.json");
    if !path.exists() {
        return Ok(None);
    }
    let json = std::fs::read_to_string(&path)?;
    let get = |k: &str| {
        field(&json, k)
            .map(str::to_owned)
            .ok_or_else(|| io::Error::other(format!("solve.json lacks {k}")))
    };
    if get("identity")? != identity {
        return Err(io::Error::other(
            "solve.json was made from different inputs",
        ));
    }
    if sha256(&std::fs::read(dir.join("policy.bin"))?) != get("policy_sha256")? {
        return Err(io::Error::other("policy.bin does not match solve.json"));
    }
    Ok(Some(get("iteration")?.parse().map_err(io::Error::other)?))
}

/// The committed checkpoint's iteration and arrays, after checking its input
/// identity and array digests, or iteration zero with zeroed arrays.
fn resume(dir: &Path, identity: &str, n: usize) -> io::Result<(u32, Vec<f64>, Vec<f64>)> {
    let manifest = dir.join("checkpoint.json");
    if !manifest.exists() {
        return Ok((0, vec![0.0; n], vec![0.0; n]));
    }
    let json = std::fs::read_to_string(&manifest)?;
    let get = |k: &str| -> io::Result<String> {
        field(&json, k)
            .map(str::to_owned)
            .ok_or_else(|| io::Error::other(format!("checkpoint.json lacks {k}")))
    };
    if get("identity")? != identity {
        return Err(io::Error::other(
            "checkpoint was made from different inputs",
        ));
    }
    let it: u32 = get("iteration")?.parse().map_err(io::Error::other)?;
    let folder = dir.join(format!("checkpoint-{it}"));
    let mut arrays = Vec::new();
    for name in ["regret", "average"] {
        let bytes = std::fs::read(folder.join(format!("{name}.bin")))?;
        let key = format!("{name}_sha256");
        if bytes.len() != n * 8 || sha256(&bytes) != get(&key)? {
            return Err(io::Error::other(format!(
                "checkpoint {name} does not match its digest"
            )));
        }
        arrays.push(f64s(&bytes));
    }
    let average = arrays.pop().unwrap();
    Ok((it, arrays.pop().unwrap(), average))
}

/// Run or resume the solve in `dir` until convergence, the iteration cap, or
/// (checked after each committed iteration) the time budget.
///
/// `identity` names the inputs (the caller hashes the prior, menus and
/// trees); a checkpoint or finished solve made from other inputs is refused.
/// A finished solve is not continued: its `policy.bin` is checked against
/// `solve.json` and returned as is. A checkpoint at a scheduled iteration
/// whose certificate was never written (a crash during certification) is
/// certified before iterating further, so it ends where an uninterrupted
/// run would.
pub fn run(
    dir: &Path,
    game: &Game,
    trees: &dyn Trees,
    identity: &str,
    budget_seconds: Option<f64>,
    max_iterations: u32,
) -> io::Result<Outcome> {
    use std::io::Write;
    let start = Instant::now();
    let n = usize::try_from(game.menus.actions).expect("action count");
    if let Some(it) = finished(dir, identity)? {
        return Ok(Outcome::Converged(it));
    }
    let manifest = dir.join("checkpoint.json");
    let (previous, regret, average) = resume(dir, identity, n)?;
    let mut solver = Solver::new(game, regret, average);
    // `solve.json` is absent here, so a scheduled checkpoint may have crashed
    // anywhere inside certification; certifying again is deterministic and
    // rewrites the same files.
    if previous > 0
        && scheduled(previous)
        && certify(dir, game, trees, &solver, previous, identity)?
    {
        return Ok(Outcome::Converged(previous));
    }
    for it in previous + 1..=max_iterations {
        let began = Instant::now();
        solver.update(game, trees, 0, it);
        solver.update(game, trees, 1, it);
        let folder = dir.join(format!("checkpoint-{it}"));
        std::fs::create_dir_all(&folder)?;
        let regret = f64_bytes(&solver.regret);
        let average = f64_bytes(&solver.average);
        write_atomic(&folder.join("regret.bin"), &regret)?;
        write_atomic(&folder.join("average.bin"), &average)?;
        // The arrays and the folder's own entry reach disk before the
        // manifest names them, and the manifest before the old generation
        // goes.
        sync_dir(&folder)?;
        sync_dir(dir)?;
        let committed = format!(
            "{{\"iteration\":{it},\"regret_sha256\":\"{}\",\"average_sha256\":\"{}\",\"identity\":\"{identity}\",\"actions\":{n}}}\n",
            sha256(&regret),
            sha256(&average)
        );
        write_atomic(&manifest, committed.as_bytes())?;
        sync_dir(dir)?;
        // The previous generation always exists here: it is either the
        // checkpoint this run resumed from, verified above, or the one the
        // previous iteration committed.
        if it > 1 {
            std::fs::remove_dir_all(dir.join(format!("checkpoint-{}", it - 1)))?;
            sync_dir(dir)?;
        }
        let mut curve = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(dir.join("curve.jsonl"))?;
        let seconds = began.elapsed().as_secs_f64();
        writeln!(curve, "{{\"iteration\":{it},\"seconds\":{seconds:.3}}}")?;
        if scheduled(it) && certify(dir, game, trees, &solver, it, identity)? {
            return Ok(Outcome::Converged(it));
        }
        if budget_seconds.is_some_and(|b| start.elapsed().as_secs_f64() >= b) {
            return Ok(Outcome::Paused(it));
        }
    }
    Ok(Outcome::Capped(max_iterations))
}
