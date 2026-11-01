"""Operational checks for the bounded runner without production sampling."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from artifact_pipeline import crib_v4
from artifact_pipeline.test_crib_v4 import V4CheckpointFixture, read_json
from scripts import measure_crib_v4


class TestDiagnosticDeadline(V4CheckpointFixture):
    """Use real checkpoint machinery with a small deterministic scorer."""

    def invoke(self, output, group="3_8", extra=()):
        source = Path(self.path("source.json"))
        source.write_text(
            json.dumps({"__metadata__": {"generation_accumulators": None}})
        )
        with contextlib.redirect_stdout(io.StringIO()) as log:
            complete = measure_crib_v4.main(
                [
                    "--source",
                    str(source),
                    "--output",
                    output,
                    "--rank-group",
                    group,
                    "--samples",
                    "4",
                    "--checkpoint-frequency",
                    "3",
                    *extra,
                ]
            )
        return complete, [json.loads(line) for line in log.getvalue().splitlines()]

    def test_deadline_commits_complete_round_and_resume_equals_fresh(self):
        for group in ("3_8", "A_A"):
            with self.subTest(group=group):
                output = self.path(f"{group}.json")
                original = crib_v4._sample_round

                def expire_after_row(*args):
                    rows = original(*args)
                    clock.return_value = 11
                    return rows

                with patch(
                    "scripts.measure_crib_v4.time.time", return_value=0
                ) as clock:
                    with patch.object(crib_v4, "_sample_round", expire_after_row):
                        complete, events = self.invoke(
                            output, group, ("--stop-at", "10")
                        )
                self.assertFalse(complete)
                self.assertEqual(events[-1]["event"], "status")
                self.assertEqual(events[-1]["reason"], "deadline")
                state = read_json(output)["__metadata__"]
                self.assertEqual(state["phase"], "sampling")
                for stream in state["estimator_state"][group]["Dealer"][
                    "streams"
                ].values():
                    self.assertEqual(stream["count"], 1)
                    self.assertEqual(stream["next_index"], 1)
                self.assertTrue(self.invoke(output, group)[0])
                fresh = self.path(f"fresh-{group}.json")
                self.assertTrue(self.invoke(fresh, group)[0])
                self.assertEqual(Path(output).read_bytes(), Path(fresh).read_bytes())

    def test_expired_deadline_does_not_sample(self):
        with patch("scripts.measure_crib_v4.time.time", return_value=11):
            with patch.object(crib_v4, "_sample_round", side_effect=AssertionError):
                complete, events = self.invoke(
                    self.path("empty.json"), extra=("--stop-at", "10")
                )
        self.assertFalse(complete)
        self.assertEqual(events[-1]["counts"]["Dealer"]["base"], 0)

    def test_source_hash_rejection_preserves_existing_output(self):
        output = Path(self.path("existing.json"))
        self.invoke(str(output))
        original = output.read_bytes()
        with self.assertRaises(ValueError):
            self.invoke(str(output), extra=("--source-sha256", "0" * 64))
        self.assertEqual(output.read_bytes(), original)

    def test_resume_seed_policy_and_input_mismatches_preserve_output(self):
        output = self.path("resume.json")
        self.invoke(output)
        saved = Path(output).read_bytes()
        for field, value in (
            ("seed", 43),
            ("generation", 1),
            ("policy_sha256", "0" * 64),
            ("bootstrap_sha256", "0" * 64),
        ):
            with self.subTest(field=field):
                document = json.loads(saved)
                document["__metadata__"][field] = value
                Path(output).write_text(json.dumps(document))
                changed = Path(output).read_bytes()
                with self.assertRaises(ValueError):
                    self.invoke(output)
                self.assertEqual(Path(output).read_bytes(), changed)

    def test_all_writer_aliases_preserve_source(self):
        for suffix in ("", ".tmp"):
            for alias in ("direct", "symlink", "hard_link"):
                with self.subTest(
                    suffix=suffix, alias=alias
                ), tempfile.TemporaryDirectory() as folder:
                    output = Path(folder) / "output.json"
                    destination = Path(f"{output}{suffix}")
                    source = (
                        destination
                        if alias == "direct"
                        else Path(folder) / "source.json"
                    )
                    source.write_text("protected")
                    if alias == "symlink":
                        destination.symlink_to(source)
                    elif alias == "hard_link":
                        os.link(source, destination)
                    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(
                        SystemExit
                    ):
                        measure_crib_v4.main(
                            [
                                "--source",
                                str(source),
                                "--output",
                                str(output),
                                "--samples",
                                "2",
                            ]
                        )
                    self.assertEqual(source.read_text(), "protected")

    def test_policy_hash_is_checked_before_writing(self):
        with self.assertRaises(ValueError):
            self.invoke(
                self.path("none.json"),
                extra=("--policy-sha256", hashlib.sha256(b"wrong").hexdigest()),
            )
        self.assertFalse(Path(self.path("none.json")).exists())


class TestShardCoordinator(unittest.TestCase):
    """Prove failure preservation and strict resume at the orchestration layer."""

    def setUp(self):
        from scripts import run_crib_v4_diagnostic

        self.runner = run_crib_v4_diagnostic
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.source = self.root / "source.json"
        self.client = self.root / "client.json"
        self.source.write_text("source")
        self.client.write_text("client")
        self.output = self.root / "output"

    def execute(self, result=True, stop_at=100):
        with patch.object(self.runner, "verified_inputs"), patch.object(
            self.runner.measure_crib_v4, "main", return_value=result
        ) as measure, patch.object(self.runner.time, "time", return_value=0):
            with contextlib.redirect_stdout(io.StringIO()):
                summary = self.runner.run(
                    self.source, self.client, self.output, stop_at
                )
        return summary, measure

    def test_serial_fixed_shard_stops_on_incomplete_and_retains_summary(self):
        summary, measure = self.execute(False)
        self.assertEqual(measure.call_count, 1)
        self.assertFalse(summary["complete"])
        self.assertEqual(summary["groups"]["3_8"], "incomplete")
        self.assertEqual(summary["groups"]["2_3"], "not_started")
        self.assertEqual(
            json.loads((self.output / "summary.json").read_text()), summary
        )
        args = measure.call_args.args[0]
        self.assertEqual(args[args.index("--samples") + 1], "4000")
        self.assertEqual(args[args.index("--stop-at") + 1], "100")

    def test_complete_and_expired_reports(self):
        summary, measure = self.execute()
        self.assertTrue(summary["complete"])
        self.assertEqual(measure.call_count, 5)
        summary, measure = self.execute(stop_at=0)
        self.assertFalse(summary["complete"])
        self.assertFalse(measure.called)

    def test_failed_group_still_writes_summary(self):
        with patch.object(self.runner, "verified_inputs"), patch.object(
            self.runner.measure_crib_v4, "main", side_effect=ValueError("broken")
        ), patch.object(self.runner.time, "time", return_value=0):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(
                ValueError
            ):
                self.runner.run(self.source, self.client, self.output, 100)
        summary = json.loads((self.output / "summary.json").read_text())
        self.assertEqual(summary["groups"]["3_8"], "failed")
        self.assertFalse(summary["complete"])

    def test_resume_requires_unchanged_manifest(self):
        self.execute()
        identity = self.output / "manifest.json"
        before = identity.read_bytes()
        changed = json.loads(before)
        changed["seed"] = 43
        identity.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            self.execute()
        identity.unlink()
        (self.output / "group-3_8.json").write_text("checkpoint")
        with self.assertRaises(ValueError):
            self.execute()

    def test_runner_protects_both_inputs_from_all_writers(self):
        self.output.mkdir()
        for name in (
            "manifest.json",
            "summary.json",
            "group-3_8.json",
            "group-3_8.json.tmp",
            "group-3_8.jsonl",
        ):
            for original in (self.source, self.client):
                alias = self.output / name
                alias.symlink_to(original)
                with self.assertRaises(ValueError):
                    self.runner.run(self.source, self.client, self.output, 100)
                self.assertEqual(
                    original.read_text(),
                    "source" if original == self.source else "client",
                )
                alias.unlink()

    def test_verified_inputs_reject_hash_policy_runtime_and_contract_drift(self):
        raw = json.dumps({"__metadata__": {"generation_accumulators": None}}).encode()
        self.source.write_bytes(raw)
        with self.assertRaises(ValueError):
            self.runner.verified_inputs(self.source, self.client)
        with patch.object(
            self.runner, "SOURCE_SHA256", hashlib.sha256(raw).hexdigest()
        ):
            with self.assertRaisesRegex(ValueError, "pinned input hash"):
                self.runner.verified_inputs(self.source, self.client)
        with patch.object(
            self.runner, "SOURCE_SHA256", hashlib.sha256(raw).hexdigest()
        ), patch.object(
            self.runner,
            "CLIENT_SHA256",
            hashlib.sha256(self.client.read_bytes()).hexdigest(),
        ):
            with self.assertRaises(ValueError):
                self.runner.verified_inputs(self.source, self.client)
            with patch.object(self.runner, "POLICY_SHA256", crib_v4._policy_hash(None)):
                with patch.object(
                    self.runner.platform, "python_version", return_value="3.14.3"
                ):
                    with self.assertRaises(ValueError):
                        self.runner.verified_inputs(self.source, self.client)
                with patch.object(crib_v4, "ESTIMATOR_CONTRACT", "different"):
                    with self.assertRaises(ValueError):
                        self.runner.verified_inputs(self.source, self.client)
                self.runner.verified_inputs(self.source, self.client)
