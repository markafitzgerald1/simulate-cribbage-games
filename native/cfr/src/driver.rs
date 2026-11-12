//! SHA-256 digests of the generated files, and atomic file writes. The
//! resumable solve driver joins this module with the CFR+ solve.

use sha2::{Digest, Sha256};
use std::io;
use std::path::Path;

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

/// Write to a temporary name, flush it to disk, then rename over `path`, so a
/// crash leaves either the old file or the complete new one.
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
