"""Check the source checks the CFR bundle workflow runs before bundling."""

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import check_cfr_bundle_sources as sources
from scripts.run_cfr_inputs import PINNED_DIGESTS

PINNED = json.loads(PINNED_DIGESTS.read_text(encoding="utf-8"))["reproducible"]
REPOSITORY = "markafitzgerald1/simulate-cribbage-games"


def good_run() -> dict:
    return {
        "id": 45322543914,
        "head_sha": "dc060a8",
        "path": ".github/workflows/generate-cfr-inputs.yml",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
        "repository": {"full_name": REPOSITORY},
    }


class SourceRunTest(unittest.TestCase):
    def test_a_successful_manual_run_on_main_is_accepted(self) -> None:
        sources.check_source_run(good_run(), REPOSITORY)

    def test_each_other_kind_of_run_is_refused(self) -> None:
        # Catches dropping any one condition: another workflow's run, a
        # scheduled or pushed run, a branch, an unfinished, failed or
        # cancelled run, a re-run (whose jobs all skip, yet which can report
        # success), or one from a fork, each alone must be refused.
        changes = {
            "path": ".github/workflows/generate-play-artifact.yml",
            "event": "push",
            "head_branch": "feature",
            "status": "in_progress",
            "conclusion": "failure",
            "run_attempt": 2,
            "repository": {"full_name": "someone/simulate-cribbage-games"},
        }
        for key, value in changes.items():
            with self.subTest(key=key):
                run = {**good_run(), key: value}
                with self.assertRaisesRegex(ValueError, "source run"):
                    sources.check_source_run(run, REPOSITORY)
        for missing in ("repository", "conclusion"):
            with self.subTest(missing=missing):
                run = good_run()
                del run[missing]
                with self.assertRaisesRegex(ValueError, "source run"):
                    sources.check_source_run(run, REPOSITORY)

    def test_the_cli_reads_the_api_record(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            record = Path(folder) / "run.json"
            record.write_text(json.dumps(good_run()))
            printed = io.StringIO()
            with mock.patch("sys.stdout", printed):
                code = sources.main(
                    [
                        "source-run",
                        "--run-json",
                        str(record),
                        "--repository",
                        REPOSITORY,
                    ]
                )
            self.assertEqual(code, 0)
            self.assertRegex(printed.getvalue(), "source run 45322543914 at dc060a8")
            record.write_text(json.dumps({**good_run(), "conclusion": "cancelled"}))
            with self.assertRaisesRegex(ValueError, "conclusion"):
                sources.main(
                    [
                        "source-run",
                        "--run-json",
                        str(record),
                        "--repository",
                        REPOSITORY,
                    ]
                )


class SourcesTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        self.work, self.prior_dir, self.evidence = (
            root / "work",
            root / "prior",
            root / "evidence",
        )
        for path in (self.work, self.prior_dir, self.evidence):
            path.mkdir()
        contents = {
            self.work / "policy.bin": b"policy",
            self.work / "support.bin": b"support",
            self.prior_dir / "prior.bin": b"prior",
        }
        for path, data in contents.items():
            path.write_bytes(data)
        self.recorded = {
            path.name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for path, data in contents.items()
        }

    def write_summary(self, job: str, status: str, **changes) -> None:
        summary = {
            "status": status,
            "prior_independent_digests": dict(PINNED),
            "files": dict(self.recorded),
            **changes,
        }
        (self.evidence / f"summary-{job}.json").write_text(json.dumps(summary))

    def check(self) -> dict:
        return sources.check_sources(self.work, self.prior_dir, self.evidence)

    def test_matching_files_from_a_resumed_run_are_accepted(self) -> None:
        # A paused first job and a converged second one: only the second
        # recorded the solved files.
        self.write_summary(
            "first", "paused", files={"prior.bin": self.recorded["prior.bin"]}
        )
        self.write_summary("continue", "converged")
        found = self.check()
        self.assertEqual(found["policy.bin"], self.recorded["policy.bin"]["sha256"])
        self.assertEqual(set(found), {"policy.bin", "support.bin", "prior.bin"})

    def test_each_file_must_match_what_the_run_recorded(self) -> None:
        # Catches skipping any one comparison: a policy, support or prior
        # from another run would otherwise be bundled silently.
        self.write_summary("first", "converged")
        for path in (
            self.work / "policy.bin",
            self.work / "support.bin",
            self.prior_dir / "prior.bin",
        ):
            with self.subTest(file=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b"!")
                with self.assertRaisesRegex(ValueError, path.name):
                    self.check()
                path.write_bytes(original)

    def test_the_run_must_have_built_the_pinned_inputs(self) -> None:
        # Catches skipping the comparison for any of menus, offsets, trees:
        # the policy is only valid over the inputs it was solved on.
        for name in ("menus", "offsets", "trees"):
            with self.subTest(name=name):
                digests = {**PINNED, name: "0" * 64}
                self.write_summary(
                    "first", "converged", prior_independent_digests=digests
                )
                with self.assertRaisesRegex(ValueError, name):
                    self.check()

    def test_exactly_one_job_must_have_converged(self) -> None:
        # Catches bundling a paused run, or picking one of two converged
        # summaries arbitrarily.
        self.write_summary("first", "paused")
        with self.assertRaisesRegex(ValueError, "found 0 among 1"):
            self.check()
        self.write_summary("first", "converged")
        self.write_summary("continue", "converged")
        with self.assertRaisesRegex(ValueError, "found 2 among 2"):
            self.check()

    def test_the_cli_prints_each_checked_digest(self) -> None:
        self.write_summary("first", "converged")
        printed = io.StringIO()
        arguments = ["sources", "--work", str(self.work), "--prior-dir"]
        arguments += [str(self.prior_dir), "--evidence", str(self.evidence)]
        with mock.patch("sys.stdout", printed):
            self.assertEqual(sources.main(arguments), 0)
        lines = printed.getvalue().splitlines()
        self.assertEqual(
            lines,
            [
                f"{name} sha256={self.recorded[name]['sha256']}"
                for name in sorted(self.recorded)
            ],
        )


class PriorLogTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        self.prior_dir = Path(folder.name)
        self.digests = {}
        for name, data in (("population.json", b"population"), ("prior.bin", b"prior")):
            (self.prior_dir / name).write_bytes(data)
            self.digests[name] = hashlib.sha256(data).hexdigest()

    def log(self, digests: dict) -> str:
        # As Actions writes it: the echoed command, then timestamped lines.
        lines = ['2026-11-24T04:03:59.57Z sha256sum cfr-prior/* | tee -a "$X"']
        lines += [
            f"2026-11-24T04:04:11.85Z {digest}  cfr-prior/{name}"
            for name, digest in digests.items()
        ]
        lines.append("2026-11-24T04:04:11.90Z   path: cfr-prior/")
        return "\n".join(lines) + "\n"

    def test_the_logged_population_and_prior_are_accepted(self) -> None:
        found = sources.check_prior_log(self.log(self.digests), self.prior_dir)
        self.assertEqual(found, self.digests)

    def test_a_population_or_prior_unlike_the_log_is_refused(self) -> None:
        # Catches skipping either comparison: a population that gives the
        # same prior bytes yet deals other keeps passes every other check.
        for name in self.digests:
            with self.subTest(name=name):
                logged = {**self.digests, name: "0" * 64}
                with self.assertRaisesRegex(ValueError, name):
                    sources.check_prior_log(self.log(logged), self.prior_dir)

    def test_a_missing_or_repeated_log_line_is_refused(self) -> None:
        # Catches trusting a log that does not name the file exactly once.
        for name in self.digests:
            with self.subTest(name=name, case="missing"):
                logged = {
                    key: value for key, value in self.digests.items() if key != name
                }
                with self.assertRaisesRegex(ValueError, f"0 digests for {name}"):
                    sources.check_prior_log(self.log(logged), self.prior_dir)
        doubled = self.log(self.digests) + self.log(self.digests)
        with self.assertRaisesRegex(ValueError, "2 digests"):
            sources.check_prior_log(doubled, self.prior_dir)

    def test_the_cli_reads_the_log_file(self) -> None:
        record = self.prior_dir / "prior-job.log"
        record.write_text(self.log(self.digests))
        printed = io.StringIO()
        arguments = [
            "prior-log",
            "--log",
            str(record),
            "--prior-dir",
            str(self.prior_dir),
        ]
        with mock.patch("sys.stdout", printed):
            self.assertEqual(sources.main(arguments), 0)
        self.assertEqual(
            printed.getvalue().splitlines(),
            [f"{name} sha256={self.digests[name]}" for name in sorted(self.digests)],
        )


if __name__ == "__main__":
    unittest.main()
