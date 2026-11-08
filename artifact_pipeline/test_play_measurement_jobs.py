"""Deterministic complete-cell ownership, resume, corruption and process failures."""

from concurrent.futures import (
    ProcessPoolExecutor as RealExecutor,
    as_completed as real_completed,
)
from concurrent.futures.process import BrokenProcessPool
import hashlib
import json
import os
from pathlib import Path
import signal
import unittest
from unittest.mock import Mock, patch

from artifact_pipeline.export_uncertainty import build_sidecar, encode_json
from artifact_pipeline.generate_play_table import build_client_table
from artifact_pipeline.measure_fixed_play_table import (
    GateSettings,
    MeasurementRequest,
    measure_fixed_table,
    measure_fixed_parallel,
)
from artifact_pipeline.play_lines import build_lines
from artifact_pipeline.play_measurement_jobs import (
    CellWorker,
    MeasurementJobs,
    _encode,
    _initialize,
    _locked,
    _measure,
    _prepare,
    _read,
    _tasks,
    _validate_cell,
    measure_cells,
)
from artifact_pipeline.test_fixed_policy_fixtures import make_bundle
from artifact_pipeline.test_six_layer_policy import temporary_directory

STAMP = "2026-10-12T16:00:00+00:00"
HANDS = [(0, 0, 1, 8), (0, 4, 4, 4), (3, 5, 7, 9), (12, 12, 12, 12)]


def artifact_bytes(table):
    full = encode_json(table)
    means = encode_json(build_client_table(table))
    return (
        full,
        means,
        encode_json(build_sidecar("play", full, means)),
        encode_json(build_lines(table, means)),
    )


class TestMeasurementJobs(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(temporary_directory()))
        self.path = make_bundle(self.root)
        self.digest = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def run_table(self, workers=1, checkpoint=None, **options):
        return measure_fixed_parallel(
            self.path,
            MeasurementRequest(
                options.get("samples", 41),
                options.get("seed", 42),
                options.get("hands", HANDS),
            ),
            GateSettings("off"),
            MeasurementJobs(
                options.get("stamp", STAMP), workers, checkpoint, self.digest
            ),
        )

    def test_real_1_2_4_6_worker_full_means_sidecar_lines_bytes(self):
        serial = self.run_table()
        expected = artifact_bytes(serial)
        for workers in (2, 4, 6):
            self.assertEqual(artifact_bytes(self.run_table(workers)), expected)
        # Independent original serial entry point uses exactly the same streams.
        original = measure_fixed_table(self.path, 41, 42, HANDS, GateSettings("off"))
        self.assertEqual(encode_json(build_client_table(original)), expected[1])
        self.assertEqual(
            json.loads(
                encode_json(
                    {
                        key: value
                        for key, value in original.items()
                        if key != "__metadata__"
                    }
                )
            ),
            {key: value for key, value in serial.items() if key != "__metadata__"},
        )
        self.assertEqual(serial["__metadata__"]["decision_count_total"], 8 * 41 * 8)
        self.assertGreater(serial["A_A_2_9"]["Pone"]["se"], 0)
        self.assertGreater(serial["__metadata__"]["decision_count_trained"], 0)
        self.assertEqual(artifact_bytes(self.run_table(hands=HANDS[::-1])), expected)

    def test_resume_keeps_complete_rows_and_restarts_only_missing_cell(self):
        checkpoint = self.root / "cells"
        initial = self.run_table(2, checkpoint)
        before = {p.name: p.read_bytes() for p in checkpoint.glob("*.json")}
        victim = checkpoint / "A_A_2_9.Dealer.json"
        victim.unlink()
        (checkpoint / "A_A_2_9.Dealer.json.tmp-dead").write_text('{"partial":')
        with patch.object(
            CellWorker, "measure", autospec=True, wraps=None
        ) as measurement:
            measurement.side_effect = TestMeasurementJobs.saved_measure
            resumed = self.run_table(1, checkpoint)
            self.assertEqual(measurement.call_count, 1)
            task = measurement.call_args.args[1]
            self.assertEqual(task["hand"], [0, 0, 1, 8])
            self.assertEqual(task["role"], "Dealer")
        self.assertEqual(artifact_bytes(resumed), artifact_bytes(initial))
        self.assertEqual(
            before, {p.name: p.read_bytes() for p in checkpoint.glob("*.json")}
        )
        with patch.object(
            CellWorker,
            "measure",
            side_effect=AssertionError("Complete cells must not sample"),
        ):
            self.assertEqual(
                artifact_bytes(self.run_table(6, checkpoint)), artifact_bytes(initial)
            )

    saved_measure = CellWorker.measure

    def test_resume_rejects_changed_inputs_seed_count_timestamp_code_and_schedule(self):
        checkpoint = self.root / "cells"
        self.run_table(checkpoint=checkpoint, samples=2)
        for changes in [
            {"seed": 43},
            {"samples": 3},
            {"stamp": "2026-10-12T17:00:00Z"},
            {"hands": HANDS[:1]},
        ]:
            with self.assertRaisesRegex(ValueError, "Checkpoint run"):
                self.run_table(checkpoint=checkpoint, **changes)
        with patch(
            "artifact_pipeline.measure_fixed_play_table.sampler_digest",
            return_value="f" * 64,
        ):
            with self.assertRaisesRegex(ValueError, "Checkpoint run"):
                self.run_table(checkpoint=checkpoint, samples=2)
        with self.assertRaisesRegex(ValueError, "Pinned"):
            measure_fixed_parallel(
                self.path,
                MeasurementRequest(2, 42, []),
                GateSettings("off"),
                MeasurementJobs(STAMP, manifest_sha256="f" * 64),
            )
        manifest = json.loads(self.path.read_bytes())
        manifest["discard_population"]["description"] += "; changed"
        self.path.write_text(json.dumps(manifest))
        self.digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "Checkpoint run"):
            self.run_table(checkpoint=checkpoint, samples=2)

    def test_corrupt_or_unexpected_completed_cell_aborts(self):
        checkpoint = self.root / "cells"
        self.run_table(checkpoint=checkpoint, samples=2)
        path = checkpoint / "A_A_2_9.Pone.json"
        original = path.read_bytes()
        document = json.loads(original)
        document["payload"]["entry"]["mu"] += 1
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "Cell digest"):
            self.run_table(checkpoint=checkpoint, samples=2)
        path.write_bytes(original)
        (checkpoint / "duplicate.json").write_bytes(original)
        with self.assertRaisesRegex(ValueError, "Unexpected or duplicate"):
            self.run_table(checkpoint=checkpoint, samples=2)
        (checkpoint / "duplicate.json").unlink()
        document = json.loads(original)
        task = document["payload"]["task"]
        for change in ("counts", "statistics", "opening"):
            malformed = json.loads(original)
            if change == "counts":
                malformed["payload"]["counts"]["forced"] = -1
            elif change == "statistics":
                malformed["payload"]["entry"]["players"]["Dealer"]["n"] = 1
            else:
                malformed["payload"]["entry"]["opening"] = {}
            malformed["sha256"] = hashlib.sha256(
                _encode(malformed["payload"])
            ).hexdigest()
            with self.assertRaises(ValueError):
                _validate_cell(malformed, task)

    def test_invalid_settings_and_missing_run_manifest(self):
        for stamp, workers in [
            ("2026-10-12", 1),
            (STAMP, 0),
            (STAMP, True),
            (STAMP, 1.5),
        ]:
            with self.assertRaises(ValueError):
                MeasurementJobs(stamp, workers).validate()
        for samples in [0, True, 1.5]:
            with self.assertRaisesRegex(ValueError, "Samples"):
                self.run_table(samples=samples)
        for hands in [[HANDS[0]] * 2, [(0, 0, 0, 0, 0)]]:
            with self.assertRaisesRegex(ValueError, "unique canonical"):
                self.run_table(hands=hands)
        checkpoint = self.root / "cells"
        checkpoint.mkdir()
        (checkpoint / "orphan.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "without a run"):
            self.run_table(checkpoint=checkpoint)
        (checkpoint / "orphan.json").write_text("[]")
        with self.assertRaisesRegex(ValueError, "JSON object"):
            _read(checkpoint / "orphan.json")
        with _locked(checkpoint):
            with self.assertRaisesRegex(ValueError, "already has an owner"):
                with _locked(checkpoint):
                    self.fail("Double ownership")
        self.assertEqual(_prepare(None, {}, []), {})

    def test_worker_input_failures_close_mappings(self):
        with self.assertRaisesRegex(ValueError, "Worker policy"):
            CellWorker.load(self.path, "f" * 64)
        with patch(
            "artifact_pipeline.play_measurement_jobs.load_fixed_discards",
            side_effect=ValueError("bad"),
        ), patch("artifact_pipeline.play_measurement_jobs.SixLayerPolicy") as loader:
            with self.assertRaisesRegex(ValueError, "bad"):
                CellWorker.load(self.path, self.digest)
            loader.return_value.close.assert_called_once()
        worker = CellWorker.load(self.path, self.digest)
        worker.close()
        with patch("artifact_pipeline.play_measurement_jobs._WORKER", []), patch(
            "artifact_pipeline.play_measurement_jobs.atexit.register"
        ) as register:
            _initialize(self.path, self.digest)
            register.assert_called_once()
            binding = {"hands": [[0, 0, 1, 8]], "samples": 2, "seed": 42}
            document = _measure(_tasks(binding)[0], None)
            self.assertEqual(document["payload"]["entry"]["n"], 2)
            completed_dir = self.root / "worker-complete"
            completed_dir.mkdir()
            _measure(_tasks(binding)[0], completed_dir)
            self.assertTrue((completed_dir / "A_A_2_9.Pone.json").is_file())
            register.call_args.args[0]()

    def test_worker_exception_and_duplicate_missing_reduction_fail_closed(self):
        worker = Mock(spec=CellWorker)
        task_binding = {"hands": [[0, 0, 1, 8]], "samples": 2, "seed": 42}
        with patch(
            "artifact_pipeline.play_measurement_jobs.ProcessPoolExecutor"
        ) as executor:
            executor.return_value.submit.side_effect = RuntimeError("worker failed")
            with self.assertRaisesRegex(RuntimeError, "worker failed"):
                measure_cells(
                    self.path,
                    {**task_binding, "policy_manifest_sha256": self.digest},
                    MeasurementJobs(STAMP, 2),
                    worker,
                )
            executor.return_value.terminate_workers.assert_called_once()
            executor.return_value.shutdown.assert_called_once()
        with patch(
            "artifact_pipeline.play_measurement_jobs._prepare",
            return_value={"spurious": {}},
        ):
            worker.measure.return_value = {"payload": {}}
            with self.assertRaisesRegex(ValueError, "Cell digest"):
                measure_cells(self.path, task_binding, MeasurementJobs(STAMP), worker)

    def test_duplicate_and_missing_cell_guard(self):
        binding = {
            "hands": [[0, 0, 1, 8]],
            "samples": 2,
            "seed": 42,
            "policy_manifest_sha256": self.digest,
        }
        task = _tasks(binding)[0]
        worker = CellWorker.load(self.path, self.digest)
        self.addCleanup(worker.close)
        with patch(
            "artifact_pipeline.play_measurement_jobs._tasks", return_value=[task, task]
        ):
            with self.assertRaisesRegex(ValueError, "Duplicate completed"):
                measure_cells(self.path, binding, MeasurementJobs(STAMP), worker)
        with patch(
            "artifact_pipeline.play_measurement_jobs.ProcessPoolExecutor"
        ), patch(
            "artifact_pipeline.play_measurement_jobs.as_completed", return_value=[]
        ):
            with self.assertRaisesRegex(ValueError, "Missing complete"):
                measure_cells(self.path, binding, MeasurementJobs(STAMP, 2), worker)

    def test_manifest_modified_during_measurement_aborts(self):
        original = self.path.read_bytes()

        def change_manifest(*_args):
            self.path.write_bytes(original + b" ")
            return {}, {}

        with patch(
            "artifact_pipeline.measure_fixed_play_table.measure_cells",
            side_effect=change_manifest,
        ):
            with self.assertRaisesRegex(ValueError, "changed during"):
                self.run_table(hands=[])

    def test_killed_real_worker_resume_preserves_completed_files(self):
        checkpoint = self.root / "killed"
        executors = []

        def factory(**kwargs):
            executor = RealExecutor(**kwargs)
            executors.append(executor)
            return executor

        def kill_after_first(futures):
            for index, future in enumerate(real_completed(futures)):
                if index == 1:
                    # The pool has no public child-PID API for SIGKILL injection.
                    pool = executors[0]
                    processes = pool._processes  # pylint: disable=protected-access
                    process = list(processes.values())[0]
                    os.kill(process.pid, signal.SIGKILL)
                yield future

        with patch(
            "artifact_pipeline.play_measurement_jobs.ProcessPoolExecutor",
            side_effect=factory,
        ), patch(
            "artifact_pipeline.play_measurement_jobs.as_completed",
            side_effect=kill_after_first,
        ):
            with self.assertRaises(BrokenProcessPool):
                self.run_table(2, checkpoint, samples=2000)
        complete = {p.name: p.read_bytes() for p in checkpoint.glob("*.json")}
        self.assertGreater(len(complete), 1)
        self.assertLess(len(complete), 9)
        resumed = self.run_table(2, checkpoint, samples=2000)
        self.assertEqual(
            artifact_bytes(resumed), artifact_bytes(self.run_table(samples=2000))
        )
        for name, data in complete.items():
            self.assertEqual((checkpoint / name).read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
