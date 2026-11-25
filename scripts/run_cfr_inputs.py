"""Run one job of the manual CFR input workflow (issue #203).

`solve-job`: the workflow `.github/workflows/generate-cfr-inputs.yml` calls
this once per solve job. Each call rebuilds the prior-independent inputs
(menus, offsets and trees) with the Rust `cfr-inputs` binary, checks them
against the digests any build must reproduce, then runs or resumes the CFR+
solve until it converges or its time budget runs out. On convergence it also
writes the one-bit counterfactual support. Every call leaves a summary of its
steps (time, peak memory, free disk) and of each output's size and SHA-256.
While a step runs, a progress line goes to stderr every five minutes, so the
Actions log shows a multi-hour solve advancing: its latest iteration, newest
certificate and time left before it pauses.
The job's status (`converged` or `paused`) goes to the file named by
`--status-file`, which the workflow points at `$GITHUB_OUTPUT`, so a paused
first job can hand its checkpoint to a second.

`build-inputs`: rebuild only the menus and offsets and check their digests,
for a job that needs them without a solve (the measurement's input bundle).

Nothing here publishes."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import threading
import time

PINNED_DIGESTS = Path(__file__).resolve().parents[1] / "native/cfr/digests.json"
# Peak disk on one runner is about 13.9 GB: menus, trees, two checkpoint
# generations while one replaces the other, and the certified policies.
MINIMUM_FREE_BYTES = 16 * 1000**3
# Menus and offsets alone, for `build-inputs`, are about 1.3 GB.
INPUTS_FREE_BYTES = 2 * 1000**3
BUILD_ORDER = ("menus", "offsets", "trees")
CONVERGED, PAUSED = 0, 3
CONVERGED_OUTPUTS = ("policy.bin", "support.bin", "solve.json", "curve.jsonl")
STATE_FILES = ("curve.jsonl", "solve.json", "checkpoint.json")
HEARTBEAT_SECONDS = 300.0
# Shorter would flood the log; longer than this overflows a thread wait.
MINIMUM_HEARTBEAT_SECONDS = 1.0

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run one binary command, passing stderr through and capturing stdout."""
    return subprocess.run(command, stdout=subprocess.PIPE, text=True, check=False)


def sha256_file(path: Path) -> str:
    """Return a file's SHA-256 without holding all of it in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def log(message: str) -> None:
    """Write one progress line to stderr, which the Actions log shows live.

    Best effort: the line is only for people watching, so a closed or
    broken stderr must never fail the job. With stderr closed at launch
    Python sets it to None, and print would then write to stdout, which
    carries the command's result. A stream with a file descriptor gets the
    line in one unbuffered write: a failed buffered write leaves bytes that
    Python flushes again at exit, and that second failure sets exit code 120.
    """
    stream = sys.stderr
    if stream is None:
        return
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[cfr-inputs {stamp}Z] {message}\n"
    try:
        try:
            descriptor = stream.fileno()
        except (AttributeError, OSError, ValueError):
            stream.write(line)
            stream.flush()
        else:
            encoding = getattr(stream, "encoding", None) or "utf-8"
            os.write(descriptor, line.encode(encoding, "replace"))
    except (OSError, ValueError):
        pass


def duration(seconds: float) -> str:
    """Format a span as hours and minutes, or minutes and seconds."""
    whole = max(0, int(seconds))
    hours, rest = divmod(whole, 3600)
    if hours:
        return f"{hours}h{rest // 60:02d}m"
    return f"{rest // 60}m{rest % 60:02d}s"


def last_record(path: Path) -> dict[str, object] | None:
    """Return a JSON-lines file's last complete record, if it has one.

    The solver may be appending a line or replacing the file as it is read,
    so a partial last line is skipped rather than treated as an error.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            return record
    return None


def certificate_iteration(path: Path) -> int:
    """Return the iteration a `certificate-N.json` name records."""
    return int(path.stem.rsplit("-", 1)[1])


def solve_progress(output: Path) -> str:
    """Describe a running solve from the files it writes as it goes."""
    parts = []
    curve = last_record(output / "curve.jsonl")
    if curve is not None:
        parts.append(
            f"iteration {curve.get('iteration')} took {curve.get('seconds')} s"
        )
    certificates = sorted(output.glob("certificate-*.json"), key=certificate_iteration)
    newest = last_record(certificates[-1]) if certificates else None
    if newest is not None:
        parts.append(
            f"certificate at iteration {newest.get('iteration')}: "
            f"exposure {newest.get('exposure')} (target 0.001)"
        )
    return "; ".join(parts) or "no iteration finished yet"


class Heartbeat:
    """Log a description every `interval` seconds until the block ends.

    Leaving the block only signals the thread and never waits for it: a
    progress read stuck on a slow disk must not delay the job's evidence or
    status, or eat into the solve's time budget. The thread is a daemon, so
    one still reading dies with the process, and it logs nothing once its
    block has ended.
    """

    def __init__(self, describe: Callable[[], str], interval: float) -> None:
        self.describe = describe
        self.interval = interval
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.beat, daemon=True)

    def __enter__(self) -> "Heartbeat":
        try:
            self.thread.start()
        except RuntimeError as error:
            log(f"no progress lines for this step: {error!r}")
        return self

    def __exit__(self, *_: object) -> None:
        self.stopped.set()

    def beat(self) -> None:
        """Log until stopped; a progress read that fails never stops a step."""
        while not self.stopped.wait(self.interval):
            try:
                message = self.describe()
            except (OSError, ValueError, KeyError, TypeError) as error:
                message = f"progress unavailable: {error!r}"
            if not self.stopped.is_set():
                log(message)


def peak_child_rss() -> int:
    """Return the largest resident set of any finished child so far.

    Linux reports kibibytes. The value is a running maximum, so a step's
    entry bounds that step and every step before it.
    """
    return resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss


class SolveJob:
    """One solve job's steps, with the evidence each step leaves."""

    def __init__(
        self,
        arguments: argparse.Namespace,
        runner: Runner = run_command,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.arguments = arguments
        self.runner = runner
        self.clock = clock
        self.steps: list[dict[str, object]] = []

    def step(self, name: str, *options: str) -> subprocess.CompletedProcess[str]:
        """Run a binary subcommand on the output folder and record it."""
        command = [str(self.arguments.binary), name, "--output"]
        command += [str(self.arguments.output), *options]
        log(f"{name}: started")
        began = self.clock()
        with Heartbeat(lambda: self.describe(name), self.arguments.heartbeat_seconds):
            result = self.runner(command)
            # Timed here, so a slow heartbeat shutdown is not counted.
            seconds = round(self.clock() - began, 3)
        peak = peak_child_rss()
        free = shutil.disk_usage(self.arguments.output).free
        self.steps.append(
            {
                "step": name,
                "exit_code": result.returncode,
                "seconds": seconds,
                "peak_child_rss_kib": peak,
                "free_bytes": free,
            }
        )
        log(
            f"{name}: exit {result.returncode} after {seconds} s; "
            f"peak child memory {peak} KiB; {free / 1000**3:.1f} GB free"
        )
        return result

    def describe(self, name: str) -> str:
        """One heartbeat line for a running step: elapsed, disk, progress."""
        output = self.arguments.output
        free = shutil.disk_usage(output).free / 1000**3
        text = f"{name}: still running; {free:.1f} GB free"
        if name == "solve":
            left = self.arguments.stop_at - time.time()
            if left > 0:
                deadline = f"{duration(left)} until the pause deadline"
            else:
                deadline = (
                    f"pause deadline passed {duration(-left)} ago; "
                    "the solve stops after its current iteration"
                )
            text += f"; {deadline}; {solve_progress(output)}"
        return text

    def require(self, name: str, *options: str) -> str:
        """Run a step that must succeed and return its stdout."""
        result = self.step(name, *options)
        if result.returncode != 0:
            raise RuntimeError(f"{name} failed with exit code {result.returncode}")
        return result.stdout

    def digests(self) -> dict[str, str]:
        """Return the binary's digests of the outputs present so far.

        The binary prints the digest object, then a timing record naming
        the command; only the first is wanted.
        """
        records = [json.loads(line) for line in self.require("digests").splitlines()]
        found = [record for record in records if "command" not in record]
        if len(found) != 1:
            raise RuntimeError(f"expected one digest record, got {len(found)}")
        return dict(found[0])

    def build_inputs(self, names: Sequence[str] = BUILD_ORDER) -> dict[str, str]:
        """Build the named prior-independent inputs and match their pins."""
        needed = MINIMUM_FREE_BYTES if "trees" in names else INPUTS_FREE_BYTES
        free = shutil.disk_usage(self.arguments.output).free
        if free < needed:
            raise RuntimeError(f"only {free} bytes free; this step needs {needed}")
        for name in names:
            self.require(name)
        built = self.digests()
        pinned = json.loads(PINNED_DIGESTS.read_text(encoding="utf-8"))["reproducible"]
        for name in names:
            if built.get(name) != pinned[name]:
                raise RuntimeError(
                    f"{name} digest {built.get(name)} differs from the pinned one"
                )
        return built

    def solve(self) -> str:
        """Run or resume the solve within the job's time budget."""
        budget = int(self.arguments.stop_at - self.clock())
        if budget <= 0:
            raise RuntimeError("no time is left for the solve")
        prior = str(self.arguments.prior)
        result = self.step(
            "solve", "--prior", prior, "--pause-after-seconds", str(budget)
        )
        if result.returncode == PAUSED:
            return "paused"
        if result.returncode != CONVERGED:
            raise RuntimeError(f"solve ended with exit code {result.returncode}")
        policy = str(self.arguments.output / "policy.bin")
        self.require("support", "--policy", policy, "--prior", prior)
        return "converged"

    def summary(self, status: str, built: dict[str, str]) -> dict[str, object]:
        """Describe the job: steps, digests and the files it produced."""
        output = self.arguments.output
        files = [self.arguments.prior]
        if status == "converged":
            files += [output / name for name in CONVERGED_OUTPUTS]
        files += sorted(output.glob("certificate-*.json"))
        return {
            "status": status,
            "prior_independent_digests": built,
            "steps": self.steps,
            "files": {
                path.name: {
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in files
            },
        }

    def run(self) -> str:
        """Build, solve and record; write the evidence even on failure."""
        evidence = self.arguments.evidence
        evidence.mkdir(parents=True, exist_ok=True)
        status, built = "failed", {}
        try:
            built = self.build_inputs()
            status = self.solve()
        finally:
            output = self.arguments.output
            for path in output.glob("certificate-*.json"):
                shutil.copyfile(path, evidence / path.name)
            for name in STATE_FILES:
                if (output / name).exists():
                    shutil.copyfile(output / name, evidence / name)
            text = json.dumps(self.summary(status, built), indent=2, sort_keys=True)
            name = f"summary-{self.arguments.job}.json"
            (evidence / name).write_text(text + "\n", encoding="utf-8")
        with self.arguments.status_file.open("a", encoding="utf-8") as status_file:
            status_file.write(f"status={status}\n")
        return status


def positive_seconds(text: str) -> float:
    """Parse a heartbeat interval a thread can wait for without flooding."""
    value = float(text)
    if not MINIMUM_HEARTBEAT_SECONDS <= value <= threading.TIMEOUT_MAX:
        raise argparse.ArgumentTypeError(
            f"must be from {MINIMUM_HEARTBEAT_SECONDS:g} seconds"
            f" to {threading.TIMEOUT_MAX:g}"
        )
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse a solve job, or a build of the menus and offsets alone."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    solve_job = commands.add_parser(
        "solve-job", help="Build the inputs, then run or resume the solve"
    )
    build = commands.add_parser(
        "build-inputs",
        help="Build menus and offsets only and check them against their pins",
    )
    for command in (solve_job, build):
        command.add_argument("--binary", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument(
            "--heartbeat-seconds",
            type=positive_seconds,
            default=HEARTBEAT_SECONDS,
            help="Seconds between progress lines while a step runs",
        )
    solve_job.add_argument("--prior", type=Path, required=True)
    solve_job.add_argument("--evidence", type=Path, required=True)
    solve_job.add_argument("--status-file", type=Path, required=True)
    solve_job.add_argument("--job", required=True)
    solve_job.add_argument(
        "--stop-at",
        type=float,
        required=True,
        help="Unix time after which the solve pauses at its next iteration",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the chosen command and print its result."""
    arguments = parse_args(argv)
    arguments.output.mkdir(parents=True, exist_ok=True)
    job = SolveJob(arguments)
    if arguments.command == "build-inputs":
        built = job.build_inputs(("menus", "offsets"))
        print(json.dumps(built, sort_keys=True))
    else:
        print(job.run())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
