"""Check what a CFR input bundle is built from (issue #203).

The manual `bundle-cfr-inputs.yml` workflow bundles the outputs of one
earlier `generate-cfr-inputs.yml` run for the fixed-policy measurement. It
downloads that run's artifacts rather than solving again, so before bundling
it checks two things:

`source-run`: the run, as the Actions API describes it, is a successful
manual run of the CFR input workflow on this repository's main branch, on its
first attempt. A re-run skips every job of that workflow yet can still report
success, while its artifacts are those of the attempt before it.

`sources`: the downloaded files are the ones that run produced. The converged
job's evidence summary records the SHA-256 of `policy.bin`, `support.bin` and
`prior.bin`, and the digests of the menus, offsets and trees it built; the
first three must match the downloaded files, and the last three must match
the pins this checkout rebuilds the menus and offsets against.

`prior-log`: the solve's evidence does not record the discard population, but
the run's prior job logged the SHA-256 of every file it uploaded. The
downloaded population and prior must match those lines, which must be
adjacent, as one `sha256sum cfr-prior/*` prints them. A prior rebuilt from
the population is not enough: two populations can yield the same prior bytes
while changing which opponent keeps the measurement deals.

Nothing here publishes."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
import re
import sys
from typing import Any

from scripts.run_cfr_inputs import PINNED_DIGESTS, sha256_file

SOURCE_WORKFLOW = ".github/workflows/generate-cfr-inputs.yml"
SOLVED_FILES = ("policy.bin", "support.bin")
PRIOR_INDEPENDENT = ("menus", "offsets", "trees")
PRIOR_FILES = ("population.json", "prior.bin")
# A `sha256sum cfr-prior/*` line in an Actions log: timestamp, digest, path.
LOGGED_DIGEST = re.compile(r"^\S+ ([0-9a-f]{64})  cfr-prior/(\S+)$")


def check_source_run(run: Mapping[str, Any], repository: str) -> None:
    """Refuse a run that is not a successful manual CFR input run on main."""
    expected = {
        "path": SOURCE_WORKFLOW,
        "event": "workflow_dispatch",
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
    }
    for key, value in expected.items():
        if run.get(key) != value:
            raise ValueError(f"source run {key} is {run.get(key)!r}, not {value!r}")
    owner = run.get("repository")
    name = owner.get("full_name") if isinstance(owner, Mapping) else None
    if name != repository:
        raise ValueError(f"source run is from {name!r}, not {repository!r}")


def converged_summary(evidence: Path) -> dict[str, Any]:
    """Return the evidence summary of the one job whose solve converged."""
    summaries = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(evidence.glob("summary-*.json"))
    ]
    converged = [
        summary for summary in summaries if summary.get("status") == "converged"
    ]
    if len(converged) != 1:
        raise ValueError(
            f"expected one converged job summary, found {len(converged)}"
            f" among {len(summaries)}"
        )
    return converged[0]


def check_sources(work: Path, prior_dir: Path, evidence: Path) -> dict[str, str]:
    """Match the downloaded files and the inputs' digests to the source run.

    Returns the SHA-256 of each checked file, for the job summary.
    """
    summary = converged_summary(evidence)
    recorded = summary.get("files", {})
    local = {name: work / name for name in SOLVED_FILES}
    local["prior.bin"] = prior_dir / "prior.bin"
    found = {}
    for name, path in local.items():
        found[name] = sha256_file(path)
        expected = recorded.get(name, {}).get("sha256")
        if found[name] != expected:
            raise ValueError(
                f"{name} is {found[name]}, but the run recorded {expected}"
            )
    pinned = json.loads(PINNED_DIGESTS.read_text(encoding="utf-8"))["reproducible"]
    built = summary.get("prior_independent_digests", {})
    for name in PRIOR_INDEPENDENT:
        if built.get(name) != pinned[name]:
            raise ValueError(
                f"the run built {name} as {built.get(name)}, not the pinned {pinned[name]}"
            )
    return found


def check_prior_log(log: str, prior_dir: Path) -> dict[str, str]:
    """Match the population and prior to the digests the prior job logged.

    Returns the SHA-256 of each checked file, for the job summary.
    """
    logged: dict[str, list[tuple[int, str]]] = {}
    for number, line in enumerate(log.splitlines()):
        match = LOGGED_DIGEST.match(line.strip())
        if match:
            logged.setdefault(match[2], []).append((number, match[1]))
    found = {}
    numbers = []
    for name in PRIOR_FILES:
        entries = logged.get(name, [])
        if len(entries) != 1:
            raise ValueError(f"the prior job logged {len(entries)} digests for {name}")
        number, digest = entries[0]
        numbers.append(number)
        found[name] = sha256_file(prior_dir / name)
        if found[name] != digest:
            raise ValueError(
                f"{name} is {found[name]}, but the prior job logged {digest}"
            )
    if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        raise ValueError("the logged digests are not one sha256sum listing")
    return found


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse a source-run check or a downloaded-files check."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    source_run = commands.add_parser(
        "source-run", help="Check the Actions API record of the source run"
    )
    source_run.add_argument("--run-json", type=Path, required=True)
    source_run.add_argument("--repository", required=True)
    sources = commands.add_parser(
        "sources", help="Check the downloaded files against the run's evidence"
    )
    sources.add_argument("--work", type=Path, required=True)
    sources.add_argument("--prior-dir", type=Path, required=True)
    sources.add_argument("--evidence", type=Path, required=True)
    prior_log = commands.add_parser(
        "prior-log", help="Check the population and prior against the prior job's log"
    )
    prior_log.add_argument("--log", type=Path, required=True)
    prior_log.add_argument("--prior-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the chosen check; a failed check raises and exits non-zero."""
    arguments = parse_args(argv)
    if arguments.command == "source-run":
        run = json.loads(arguments.run_json.read_text(encoding="utf-8"))
        check_source_run(run, arguments.repository)
        print(f"source run {run.get('id')} at {run.get('head_sha')}: accepted")
    else:
        if arguments.command == "prior-log":
            log = arguments.log.read_text(encoding="utf-8", errors="replace")
            found = check_prior_log(log, arguments.prior_dir)
        else:
            found = check_sources(
                arguments.work, arguments.prior_dir, arguments.evidence
            )
        for name, digest in sorted(found.items()):
            print(f"{name} sha256={digest}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
