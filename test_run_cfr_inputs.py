"""Exercise one CFR solve job against a fake `cfr-inputs` binary."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from scripts import run_cfr_inputs

RESEARCH = json.loads(run_cfr_inputs.RESEARCH_DIGESTS.read_text(encoding="utf-8"))

# Stands in for the Rust binary: writes the files each subcommand would and
# prints what `digests` prints. SOLVE_EXIT picks the solve's outcome.
FAKE_BINARY = r"""
import json, os, sys
from pathlib import Path
command, output = sys.argv[1], Path(sys.argv[3])
research = json.loads(os.environ["RESEARCH"])
if command in ("menus", "trees"):
    (output / command).mkdir(exist_ok=True)
elif command == "offsets":
    (output / "offsets.bin").write_bytes(b"offsets")
elif command == "digests":
    built = {name: research[name] for name in ("menus", "trees", "offsets")}
    built.update(json.loads(os.environ.get("DIGEST_OVERRIDE", "{}")))
    print(json.dumps(built))
    print(json.dumps({"command": "digests", "seconds": 0.5}))
elif command == "solve":
    with open(output / "arguments.txt", "w") as record:
        record.write(" ".join(sys.argv[4:]))
    code = int(os.environ["SOLVE_EXIT"])
    (output / "certificate-1.json").write_text("{}")
    (output / "curve.jsonl").write_text("{}\n")
    (output / "checkpoint.json").write_text("{}")
    if code == 0:
        (output / "policy.bin").write_bytes(b"policy")
        (output / "solve.json").write_text("{}")
    sys.exit(code)
elif command == "support":
    (output / "support.bin").write_bytes(b"support")
else:
    sys.exit(2)
"""


class SolveJobTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.binary = self.root / "cfr-inputs"
        self.binary.write_text(f"#!{sys.executable}\n{FAKE_BINARY}")
        self.binary.chmod(0o700)
        self.prior = self.root / "prior.bin"
        self.prior.write_bytes(b"prior")
        self.output = self.root / "work"
        self.evidence = self.root / "evidence"
        self.status = self.root / "github-output"
        self.environment = {"RESEARCH": json.dumps(RESEARCH), "SOLVE_EXIT": "0"}

    def arguments(self, stop_at: float) -> list[str]:
        return [
            "--binary",
            str(self.binary),
            "--output",
            str(self.output),
            "--prior",
            str(self.prior),
            "--evidence",
            str(self.evidence),
            "--status-file",
            str(self.status),
            "--job",
            "first",
            "--stop-at",
            str(stop_at),
        ]

    def job(self, clock_values=(1000.0,) * 20, stop_at=1600.0):
        namespace = run_cfr_inputs.parse_args(self.arguments(stop_at))
        namespace.output.mkdir(parents=True, exist_ok=True)
        clock = iter(clock_values)
        return run_cfr_inputs.SolveJob(namespace, clock=lambda: next(clock))

    def summary(self) -> dict:
        path = self.evidence / "summary-first.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_converged_job_writes_support_and_digests_every_output(self) -> None:
        with mock.patch.dict("os.environ", self.environment), mock.patch("sys.stdout"):
            self.assertEqual(run_cfr_inputs.main(self.arguments(time.time() + 900)), 0)
        self.assertEqual(self.status.read_text(), "status=converged\n")
        summary = self.summary()
        steps = [entry["step"] for entry in summary["steps"]]
        self.assertEqual(
            steps, ["menus", "offsets", "trees", "digests", "solve", "support"]
        )
        self.assertEqual(
            summary["files"]["policy.bin"]["sha256"],
            hashlib.sha256(b"policy").hexdigest(),
        )
        self.assertEqual(
            set(summary["files"]),
            {
                "prior.bin",
                "policy.bin",
                "support.bin",
                "solve.json",
                "curve.jsonl",
                "certificate-1.json",
            },
        )
        self.assertTrue((self.evidence / "certificate-1.json").exists())

    def test_solve_gets_the_time_left_before_the_deadline(self) -> None:
        # Catches passing the deadline itself, or the elapsed time, as the
        # budget: either lets the solve run past the job's time limit.
        with mock.patch.dict("os.environ", self.environment):
            self.job(clock_values=(1000.0,) * 8 + (1200.0,) * 12).run()
        recorded = (self.output / "arguments.txt").read_text().split()
        self.assertEqual(
            recorded, ["--prior", str(self.prior), "--pause-after-seconds", "400"]
        )

    def test_paused_job_keeps_the_checkpoint_and_skips_support(self) -> None:
        # Catches running support, or reporting convergence, on a pause.
        self.environment["SOLVE_EXIT"] = "3"
        with mock.patch.dict("os.environ", self.environment):
            self.assertEqual(self.job().run(), "paused")
        self.assertEqual(self.status.read_text(), "status=paused\n")
        steps = [entry["step"] for entry in self.summary()["steps"]]
        self.assertEqual(steps[-1], "solve")
        self.assertNotIn("policy.bin", self.summary()["files"])
        self.assertTrue((self.evidence / "checkpoint.json").exists())

    def test_iteration_cap_fails_the_job(self) -> None:
        # Catches treating any non-pause exit as convergence.
        self.environment["SOLVE_EXIT"] = "4"
        with mock.patch.dict("os.environ", self.environment):
            with self.assertRaisesRegex(RuntimeError, "exit code 4"):
                self.job().run()
        self.assertEqual(self.summary()["status"], "failed")
        self.assertFalse(self.status.exists())

    def test_inputs_that_differ_from_the_research_stop_the_job(self) -> None:
        # Catches dropping the comparison, or comparing only some inputs:
        # each prior-independent digest is changed in turn.
        for name in ("menus", "trees", "offsets"):
            with self.subTest(name=name):
                self.environment["DIGEST_OVERRIDE"] = json.dumps({name: "0" * 64})
                with mock.patch.dict("os.environ", self.environment):
                    with self.assertRaisesRegex(RuntimeError, name):
                        self.job().run()
                steps = [entry["step"] for entry in self.summary()["steps"]]
                self.assertNotIn("solve", steps)

    def test_a_failed_build_step_stops_the_job(self) -> None:
        self.binary.write_text(f"#!{sys.executable}\nimport sys; sys.exit(1)\n")
        with self.assertRaisesRegex(RuntimeError, "menus failed"):
            self.job().run()

    def test_too_little_disk_stops_the_job_before_any_step(self) -> None:
        usage = mock.Mock(free=run_cfr_inputs.MINIMUM_FREE_BYTES - 1)
        with mock.patch.object(run_cfr_inputs.shutil, "disk_usage", return_value=usage):
            with self.assertRaisesRegex(RuntimeError, "bytes free"):
                self.job().run()
        self.assertEqual(self.summary()["steps"], [])

    def test_no_time_left_stops_the_job_before_the_solve(self) -> None:
        with mock.patch.dict("os.environ", self.environment):
            with self.assertRaisesRegex(RuntimeError, "no time"):
                self.job(stop_at=1000.0).run()
        steps = [entry["step"] for entry in self.summary()["steps"]]
        self.assertNotIn("solve", steps)

    def test_run_command_captures_stdout(self) -> None:
        result = run_cfr_inputs.run_command([sys.executable, "-c", "print('out')"])
        self.assertIsInstance(result, subprocess.CompletedProcess)
        self.assertEqual(result.stdout, "out\n")

    def test_arguments_are_all_required(self) -> None:
        # Catches any one argument made optional.
        complete = self.arguments(1.0)
        self.assertIsInstance(run_cfr_inputs.parse_args(complete), argparse.Namespace)
        for index in range(0, len(complete), 2):
            with self.subTest(argument=complete[index]):
                partial = complete[:index] + complete[index + 2 :]
                with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
                    run_cfr_inputs.parse_args(partial)

    def test_a_missing_or_doubled_digest_record_stops_the_job(self) -> None:
        for printed in ("", '{"menus": "a"}\n{"trees": "b"}\n'):
            with self.subTest(printed=printed):
                result = subprocess.CompletedProcess([], 0, stdout=printed)
                job = self.job()
                job.runner = lambda command, result=result: result
                with self.assertRaisesRegex(RuntimeError, "digest record"):
                    job.digests()


if __name__ == "__main__":
    unittest.main()
