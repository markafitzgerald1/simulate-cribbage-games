"""Exercise one CFR solve job against a fake `cfr-inputs` binary."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from scripts import run_cfr_inputs

PINNED = json.loads(run_cfr_inputs.PINNED_DIGESTS.read_text(encoding="utf-8"))[
    "reproducible"
]

# Stands in for the Rust binary: writes the files each subcommand would and
# prints what `digests` prints. SOLVE_EXIT picks the solve's outcome.
FAKE_BINARY = r"""
import json, os, sys
from pathlib import Path
command, output = sys.argv[1], Path(sys.argv[3])
pinned = json.loads(os.environ["PINNED"])
if command in ("menus", "trees"):
    (output / command).mkdir(exist_ok=True)
elif command == "offsets":
    (output / "offsets.bin").write_bytes(b"offsets")
elif command == "digests":
    # Like the binary, report only the outputs present.
    present = {"menus": output / "menus", "trees": output / "trees",
               "offsets": output / "offsets.bin"}
    built = {name: pinned[name] for name, path in present.items() if path.exists()}
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


class JobFixture(unittest.TestCase):
    """A fake binary, its files, and a job built over them."""

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
        self.environment = {"PINNED": json.dumps(PINNED), "SOLVE_EXIT": "0"}

    def arguments(self, stop_at: float) -> list[str]:
        return [
            "solve-job",
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

    def build_arguments(self) -> list[str]:
        return [
            "build-inputs",
            "--binary",
            str(self.binary),
            "--output",
            str(self.output),
        ]


class SolveJobTest(JobFixture):
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

    def test_inputs_that_differ_from_their_pinned_digests_stop_the_job(self) -> None:
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
        for index in range(1, len(complete), 2):
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

    def test_build_inputs_builds_and_checks_menus_and_offsets_only(self) -> None:
        # Catches building the 7.7 GB trees, or skipping the digest check,
        # in the step the measurement bundle uses.
        printed = io.StringIO()
        with mock.patch.dict("os.environ", self.environment), mock.patch(
            "sys.stdout", printed
        ):
            self.assertEqual(run_cfr_inputs.main(self.build_arguments()), 0)
        self.assertTrue((self.output / "menus").is_dir())
        self.assertTrue((self.output / "offsets.bin").exists())
        self.assertFalse((self.output / "trees").exists())
        self.assertEqual(json.loads(printed.getvalue())["menus"], PINNED["menus"])
        self.environment["DIGEST_OVERRIDE"] = json.dumps({"offsets": "0" * 64})
        with mock.patch.dict("os.environ", self.environment), mock.patch("sys.stdout"):
            with self.assertRaisesRegex(RuntimeError, "offsets digest"):
                run_cfr_inputs.main(self.build_arguments())

    def test_build_inputs_needs_less_disk_than_a_solve(self) -> None:
        usage = mock.Mock(free=run_cfr_inputs.INPUTS_FREE_BYTES - 1)
        with mock.patch.object(run_cfr_inputs.shutil, "disk_usage", return_value=usage):
            with self.assertRaisesRegex(RuntimeError, "bytes free"):
                run_cfr_inputs.main(self.build_arguments())
        usage = mock.Mock(free=run_cfr_inputs.INPUTS_FREE_BYTES)
        with mock.patch.dict("os.environ", self.environment), mock.patch(
            "sys.stdout"
        ), mock.patch.object(run_cfr_inputs.shutil, "disk_usage", return_value=usage):
            self.assertEqual(run_cfr_inputs.main(self.build_arguments()), 0)

    def test_a_command_is_required(self) -> None:
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            run_cfr_inputs.parse_args(["--binary", "x", "--output", "y"])


def wait_until(condition, seconds: float = 10.0) -> bool:
    """Poll `condition` until it holds or `seconds` pass; return whether it held."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


class BrokenStream:
    """A stderr whose writes fail, as a closed pipe's would."""

    def write(self, _: str) -> int:
        raise OSError("broken pipe")

    def flush(self) -> None:
        raise OSError("broken pipe")


class ProgressTest(JobFixture):
    """What a running job writes to the Actions log."""

    def test_a_running_step_logs_its_start_progress_and_end(self) -> None:
        # Catches a heartbeat that never starts, a solve line that drops the
        # newest certificate, and a missing start or end line: each leaves
        # a silent Actions log for a step that can run for hours.
        logged = io.StringIO()

        def slow_solve(command):
            (self.output / "curve.jsonl").write_text(
                '{"iteration":6,"seconds":9.5}\n{"iteration":7,"seconds":9.8}\n'
            )
            for iteration, exposure in ((128, 0.01), (1024, 0.0042)):
                (self.output / f"certificate-{iteration}.json").write_text(
                    json.dumps({"iteration": iteration, "exposure": exposure})
                )
            wait_until(lambda: logged.getvalue().count("iteration 7 took") >= 2)
            return subprocess.CompletedProcess(command, 3, stdout="")

        job = self.job(stop_at=time.time() + 3700)
        job.arguments.heartbeat_seconds = 0.05
        job.runner = slow_solve
        with mock.patch("sys.stderr", logged):
            job.step("solve", "--prior", str(self.prior))
        lines = logged.getvalue().splitlines()
        self.assertRegex(lines[0], "solve: started$")
        ends = [line for line in lines if "solve: exit 3 after " in line]
        self.assertEqual(len(ends), 1)
        beats = [line for line in lines if "solve: still running" in line]
        self.assertGreaterEqual(len(beats), 2)
        self.assertRegex(beats[-1], re.escape("iteration 7 took 9.8 s"))
        self.assertRegex(
            beats[-1], re.escape("certificate at iteration 1024: exposure 0.0042")
        )
        self.assertRegex(beats[-1], "1h0[01]m until the pause deadline")

    def test_a_passed_deadline_says_so(self) -> None:
        # Catches a countdown stuck at zero while the solve finishes its
        # last iteration and certificate after the deadline.
        self.output.mkdir(parents=True, exist_ok=True)
        job = self.job(stop_at=875.0)
        with mock.patch.object(run_cfr_inputs.time, "time", return_value=1000.0):
            line = job.describe("solve")
        self.assertRegex(line, "pause deadline passed 2m05s ago")
        self.assertRegex(line, "the solve stops after its current iteration")

    def test_progress_reads_partial_files_without_failing(self) -> None:
        # Catches treating a line the solver is still appending, or an empty
        # certificate it is still writing, as an error.
        self.output.mkdir(parents=True, exist_ok=True)
        self.assertEqual(
            run_cfr_inputs.solve_progress(self.output), "no iteration finished yet"
        )
        (self.output / "curve.jsonl").write_text(
            '{"iteration":3,"seconds":1.5}\n[]\n{"seconds'
        )
        (self.output / "certificate-1.json").write_text("")
        self.assertEqual(
            run_cfr_inputs.solve_progress(self.output), "iteration 3 took 1.5 s"
        )

    def test_a_failed_progress_read_never_stops_the_step(self) -> None:
        # Catches letting a heartbeat's error end the thread silently or
        # propagate: the step must still finish and say why progress is gone.
        def unreadable() -> str:
            raise OSError("gone")

        logged = io.StringIO()
        with mock.patch("sys.stderr", logged):
            with run_cfr_inputs.Heartbeat(unreadable, 0.02):
                self.assertTrue(
                    wait_until(
                        lambda: logged.getvalue().count("progress unavailable") >= 2
                    )
                )

    def test_a_stuck_progress_read_cannot_hold_the_job(self) -> None:
        # Catches waiting for the heartbeat without a bound, which would
        # hold the job's evidence and status behind a slow disk read, and a
        # beat logged after its step has ended.
        entered, release = threading.Event(), threading.Event()

        def stuck() -> str:
            entered.set()
            release.wait(10)
            return "late beat"

        logged = io.StringIO()
        heartbeat = run_cfr_inputs.Heartbeat(stuck, 0.01)

        def run_block() -> None:
            with heartbeat:
                entered.wait(10)

        worker = threading.Thread(target=run_block, daemon=True)
        with mock.patch("sys.stderr", logged):
            worker.start()
            worker.join(1)
            finished = not worker.is_alive()
            release.set()
            heartbeat.thread.join(5)
        self.assertTrue(finished)
        self.assertNotRegex(logged.getvalue(), "late beat")

    def test_a_broken_stderr_never_fails_a_step(self) -> None:
        # Catches letting a failed log write end the job, which would turn
        # a finished solve into a failure over a line nobody can read.
        job = self.job()
        job.arguments.heartbeat_seconds = 0.01
        job.runner = lambda command: subprocess.CompletedProcess(command, 3, stdout="")
        with mock.patch("sys.stderr", BrokenStream()):
            result = job.step("solve", "--prior", str(self.prior))
        self.assertEqual(result.returncode, 3)
        self.assertEqual(job.steps[-1]["exit_code"], 3)

    def test_a_heartbeat_that_cannot_start_still_runs_the_step(self) -> None:
        # Catches letting a failed thread start stop the step from running.
        ran = []
        logged = io.StringIO()
        with mock.patch("sys.stderr", logged), mock.patch.object(
            threading.Thread, "start", side_effect=RuntimeError("no threads")
        ):
            with run_cfr_inputs.Heartbeat(lambda: "beat", 0.01):
                ran.append(True)
        self.assertEqual(ran, [True])
        self.assertRegex(logged.getvalue(), "no progress lines for this step")

    def test_other_steps_report_disk_but_no_solve_progress(self) -> None:
        job = self.job()
        self.assertNotRegex(job.describe("trees"), "pause deadline")
        self.assertRegex(job.describe("trees"), "^trees: still running; ")

    def test_the_heartbeat_interval_is_bounded(self) -> None:
        # Catches accepting an interval that floods the log (zero, or under
        # a second), never compares (NaN), or overflows a thread's wait.
        for bad in ("0", "0.5", "-5", "nan", "inf", "1e100"):
            with self.subTest(value=bad), mock.patch("sys.stderr"):
                with self.assertRaises(SystemExit):
                    run_cfr_inputs.parse_args(
                        self.build_arguments() + ["--heartbeat-seconds", bad]
                    )
        parsed = run_cfr_inputs.parse_args(self.build_arguments())
        self.assertEqual(parsed.heartbeat_seconds, run_cfr_inputs.HEARTBEAT_SECONDS)
        for good, expected in (("1", 1.0), ("30", 30.0)):
            parsed = run_cfr_inputs.parse_args(
                self.build_arguments() + ["--heartbeat-seconds", good]
            )
            self.assertEqual(parsed.heartbeat_seconds, expected)

    def test_durations_read_as_hours_or_minutes(self) -> None:
        self.assertEqual(run_cfr_inputs.duration(3725.0), "1h02m")
        self.assertEqual(run_cfr_inputs.duration(65.0), "1m05s")
        self.assertEqual(run_cfr_inputs.duration(-3.0), "0m00s")


if __name__ == "__main__":
    unittest.main()
