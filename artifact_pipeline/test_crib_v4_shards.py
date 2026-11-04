"""Split/assembly acceptance and rejection tests using small seeded vectors."""

import copy
import contextlib
import io
import hashlib
import os
import runpy
import sys
import time
import json
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from artifact_pipeline import crib_v4, crib_v4_shards as shards, generate_table
from artifact_pipeline.crib_v4 import (
    _policy_hash,
    _digest,
    _score_deal,
    _centers,
    _V4Run,
    _project_output,
)
from artifact_pipeline.crib_v4_state import empty_moments, add_row, encode_moments
from artifact_pipeline.crib_v4_shards import (
    _protect_directory,
    _save_snapshot,
    _snapshot_path,
    _snapshot_bytes,
    _write_manifest,
    _load_shard,
    _decode_full,
    _comparison,
)
from artifact_pipeline.test_crib_v4 import (
    PAIRS,
    fixture_centers,
    fixture_score_deal,
    run_args,
)


class ShardedV4Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        for name, replacement in (
            ("_centers", fixture_centers),
            ("_score_deal", fixture_score_deal),
        ):
            mocked = patch.object(crib_v4, name, replacement)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.args = run_args(
            str(self.root / "mono.json"),
            2,
            max_generations=2,
            convergence_threshold=1000,
            fail_on_non_convergence=True,
            no_client_output=True,
        )
        self.plan = shards.initial_plan(self.args, PAIRS)

    def _wave(self, plan, name):
        paths = []
        for number in range(8):
            path = self.root / f"{name}-{number}"
            self.assertTrue(shards.measure_shard(plan, number, path))
            paths.append(path)
        return paths

    def _checkpoint(self, directory, group):
        name = f"group-{group}.json"
        if not (directory / "snapshots").exists():
            return directory / name
        digest = json.loads((directory / "manifest.json").read_bytes())["files"][name]
        return directory / "snapshots" / f"group-{group}-{digest}.json"

    def _record_checkpoint(self, directory, group, raw):
        name = f"group-{group}.json"
        digest = hashlib.sha256(raw).hexdigest()
        path = directory / "snapshots" / f"group-{group}-{digest}.json"
        path.write_bytes(raw)
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["files"][name] = digest
        manifest_path.write_text(json.dumps(manifest))
        return path

    def _reference(self):
        output = crib_v4.run(self.args, PAIRS, generate_table)
        output["__metadata__"] = {
            "generation_method": "artifact_pipeline.generate_table.v3"
        }
        directory = self.root / "reference"
        directory.mkdir()
        (directory / "expected_crib_points.json").write_bytes(shards.json_bytes(output))
        (directory / "expected_crib_points.client.json").write_bytes(
            shards.client_bytes(output)
        )
        (directory / "release.json").write_bytes(
            shards.json_bytes(
                {
                    "tag_name": "expected-crib-points",
                    "assets": [
                        {
                            "id": number + 1,
                            "name": name,
                            "size": (directory / name).stat().st_size,
                            "digest": "sha256:" + shards.file_digest(directory / name),
                        }
                        for number, name in enumerate(
                            (
                                "expected_crib_points.json",
                                "expected_crib_points.client.json",
                            )
                        )
                    ],
                }
            )
        )
        return directory

    def _cli_pipeline(self):
        reference = self._reference()
        plan = shards.initial_plan(self.args, PAIRS, shards.reference_files(reference))
        initial = self.root / "initial"
        bootstrap = self.root / "bootstrap.json"
        bootstrap.write_bytes(b"{}")
        with patch.object(
            shards, "initial_plan", return_value=plan
        ) as initialize, patch.object(
            generate_table, "get_canonical_pairs", return_value=PAIRS
        ):
            shards.main(
                [
                    "plan",
                    "--bootstrap",
                    str(bootstrap),
                    "--reference",
                    str(reference),
                    "--output",
                    str(initial),
                ]
            )
        args = initialize.call_args.args[0]
        self.assertEqual(
            (
                args.samples,
                args.max_generations,
                args.convergence_threshold,
                args.fail_on_non_convergence,
                args.seed,
            ),
            (22000, 2, 0.10, True, 42),
        )
        current_path = initial / "plan.json"
        with self.assertRaises(SystemExit):
            shards.main(
                [
                    "measure",
                    "--plan",
                    str(current_path),
                    "--shard",
                    "0",
                    "--stop-at",
                    "0",
                    "--output",
                    str(self.root / "expired"),
                ]
            )
        for generation in range(2):
            workers = [self.root / f"cli-{generation}-{i}" for i in range(8)]
            for number, path in enumerate(workers):
                shards.main(
                    [
                        "measure",
                        "--plan",
                        str(current_path),
                        "--shard",
                        str(number),
                        "--stop-at",
                        str(time.time() + 60),
                        "--output",
                        str(path),
                    ]
                )
            assembled = self.root / f"assembled-{generation}"
            shards.main(
                [
                    "assemble",
                    "--plan",
                    str(current_path),
                    "--shards",
                    *map(str, workers),
                    "--output",
                    str(assembled),
                ]
            )
            if generation == 0:
                current_path = assembled / "next-plan.json"
        final = self.root / "final"
        shards.main(
            [
                "finalize",
                "--plan",
                str(current_path),
                "--assembled",
                str(assembled),
                "--reference",
                str(reference),
                "--output",
                str(final),
            ]
        )
        return reference, current_path, assembled, final

    def _record_reference(self, directory):
        record = {
            "tag_name": "expected-crib-points",
            "assets": [
                {
                    "id": number + 1,
                    "name": name,
                    "size": (directory / name).stat().st_size,
                    "digest": "sha256:" + shards.file_digest(directory / name),
                }
                for number, name in enumerate(
                    ("expected_crib_points.json", "expected_crib_points.client.json")
                )
            ],
        }
        (directory / "release.json").write_bytes(shards.json_bytes(record))


class TestShardedV4(ShardedV4Fixture):
    def test_resume_rejects_altered_checkpoint_without_accepting_changed_bytes(self):
        directory = self.root / "altered"
        shards.measure_shard(self.plan, 0, directory)
        checkpoint = self._checkpoint(directory, "A_A")
        checkpoint.write_bytes(checkpoint.read_bytes() + b" ")
        original = checkpoint.read_bytes()
        manifest = (directory / "manifest.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "digest"):
            shards.measure_shard(self.plan, 0, directory)
        self.assertEqual(checkpoint.read_bytes(), original)
        self.assertEqual((directory / "manifest.json").read_bytes(), manifest)

    def test_resume_temporary_hard_link_cannot_clobber_checkpoint(self):
        directory = self.root / "temp-alias"
        shards.measure_shard(self.plan, 0, directory)
        checkpoint = self._checkpoint(directory, "A_A")
        original = checkpoint.read_bytes()
        manifest = (directory / "manifest.json").read_bytes()
        os.link(checkpoint, directory / "manifest.json.tmp")
        with self.assertRaises(ValueError):
            shards.measure_shard(self.plan, 0, directory)
        self.assertEqual(checkpoint.read_bytes(), original)
        self.assertEqual((directory / "manifest.json").read_bytes(), manifest)

    def test_reference_requires_recorded_asset_digests(self):
        reference = self._reference()
        (reference / "release.json").write_bytes(
            b'{"tag_name":"expected-crib-points","assets":[]}'
        )
        with self.assertRaisesRegex(ValueError, "asset"):
            shards.reference_files(reference)

    def test_split_and_assembled_matches_monolithic_across_generations(self):
        paths = self._wave(self.plan, "first")
        first, following = shards.assemble(self.plan, paths)
        self.assertEqual(first["__metadata__"]["generation"], 0)
        self.assertIsNotNone(following)
        with patch.object(
            crib_v4, "_sample_round", side_effect=AssertionError("resampled")
        ):
            for number, path in enumerate(paths):
                self.assertTrue(shards.measure_shard(self.plan, number, path))
        second, terminal = shards.assemble(following, self._wave(following, "second"))
        self.assertIsNone(terminal)
        mono = crib_v4.run(self.args, PAIRS, generate_table)
        self.assertEqual(second, mono)
        self.assertEqual(shards.client_bytes(second), shards.client_bytes(mono))
        self.assertEqual(second["__metadata__"]["generation"], 1)

    def test_partition_has_all_groups_and_keys_exactly_once(self):
        pairs = generate_table.get_canonical_pairs()
        groups = list(dict.fromkeys(pair.rsplit("_", 1)[0] for pair in pairs))
        parts = shards.partition(groups)
        self.assertEqual(
            [len(part) for part in parts], [12, 12, 12, 11, 11, 11, 11, 11]
        )
        self.assertEqual(len(groups), 91)
        self.assertEqual(len(pairs), 169)
        self.assertEqual(set(sum(parts, [])), set(groups))
        self.assertEqual(len(sum(parts, [])), 91)

    def test_identity_and_manifest_rejections_preserve_inputs(self):
        paths = self._wave(self.plan, "identity")
        manifest_path = paths[0] / "manifest.json"
        original = manifest_path.read_bytes()
        manifest = json.loads(original)
        for field, value in (
            ("plan_sha256", "bad"),
            ("shard", 7),
            ("groups", []),
            ("complete", False),
            ("complete", 1),
        ):
            bad = copy.deepcopy(manifest)
            bad[field] = value
            manifest_path.write_text(json.dumps(bad))
            with self.subTest(field=field), self.assertRaises(ValueError):
                shards.assemble(self.plan, paths)
        manifest_path.write_bytes(original)
        for bad_paths in (paths[:-1], paths[:-1] + [paths[0]]):
            with self.assertRaises(ValueError):
                shards.assemble(self.plan, bad_paths)
        bad_plan = copy.deepcopy(self.plan)
        bad_plan["metadata"]["seed"] = 99
        with self.assertRaises(ValueError):
            shards.assemble(bad_plan, paths)
        self.assertEqual(manifest_path.read_bytes(), original)

    def test_checkpoint_rejections_even_with_updated_manifest_digest(self):
        paths = self._wave(self.plan, "checkpoint")
        checkpoint = self._checkpoint(paths[0], "A_A")
        original = checkpoint.read_bytes()
        manifest_path = paths[0] / "manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        for mutate in (
            lambda m: m.update(generation=7),
            lambda m: m.update(seed=7),
            lambda m: m.update(policy_sha256="bad"),
            lambda m: m.update(
                generation_accumulators={}, policy_sha256=_policy_hash({})
            ),
            lambda m: m["estimator_state"]["A_A"].pop("Pone"),
            lambda m: m["estimator_state"]["A_A"]["Dealer"]["streams"]["base"].update(
                count=1, next_index=1
            ),
            lambda m: m.update(phase="sampling"),
        ):
            document = json.loads(original)
            mutate(document["__metadata__"])
            self._record_checkpoint(paths[0], "A_A", json.dumps(document).encode())
            with self.assertRaises(ValueError):
                shards.assemble(self.plan, paths)
        checkpoint.write_bytes(original)
        manifest_path.write_bytes(manifest_bytes)
        checkpoint.write_bytes(original + b" ")
        with self.assertRaisesRegex(ValueError, "digest"):
            shards.assemble(self.plan, paths)

    def test_worker_never_transitions_and_deadline_resumes(self):
        path = self.root / "deadline"
        with patch.object(
            crib_v4, "_transition", side_effect=AssertionError("worker transition")
        ), patch.object(
            shards, "_transition", side_effect=AssertionError("worker transition")
        ):
            self.assertFalse(shards.measure_shard(self.plan, 0, path, stop_at=0))
            self.assertTrue(shards.measure_shard(self.plan, 0, path))
        changed = copy.deepcopy(self.plan)
        changed["source_files"] = {}
        with self.assertRaises(ValueError):
            shards.measure_shard(changed, 0, path)

    def test_atomic_install_noop_collision_and_lock(self):
        output = self.root / "bundle"
        files = {"table.json": b"measured table\n"}
        shards.install_bundle(output, files, {"kind": "test"})
        before = {p.name: p.read_bytes() for p in output.iterdir()}
        shards.install_bundle(output, files, {"kind": "test"})
        with self.assertRaises(ValueError):
            shards.install_bundle(
                output, {"table.json": b"different"}, {"kind": "test"}
            )
        self.assertEqual(before, {p.name: p.read_bytes() for p in output.iterdir()})
        locked = self.root / "locked"
        Path(str(locked) + ".lock").mkdir()
        with self.assertRaises(ValueError):
            shards.install_bundle(locked, files, {"kind": "test"})
        self.assertFalse(locked.exists())

    def test_tiny_real_scorer_group_matches_monolithic(self):
        pairs = ["3_8_Suited", "3_8_Unsuited"]
        args = copy.copy(self.args)
        args.output = str(self.root / "real-mono.json")
        with patch.object(crib_v4, "_score_deal", _score_deal), patch.object(
            crib_v4, "_centers", _centers
        ):
            plan = shards.initial_plan(args, pairs)
            output, _next = shards.assemble(plan, self._wave(plan, "real"))
            mono = _V4Run(args, pairs, generate_table)
            mono.sample_pass()
            self.assertEqual(output, _project_output(mono.state, generate_table))

    def test_plan_contract_shape_partition_and_target(self):
        with self.assertRaises(ValueError):
            shards.validate_plan({})
        for change in (
            lambda p: p.update(source_files={}),
            lambda p: p.update(shards=[[]] * 8),
            lambda p: p["metadata"].update(phase="complete"),
            lambda p: p["metadata"]["run_control"].update(target_samples=True),
            lambda p: p["metadata"]["run_control"].update(target_samples=1),
        ):
            plan = copy.deepcopy(self.plan)
            change(plan)
            plan["sha256"] = _digest({k: v for k, v in plan.items() if k != "sha256"})
            with self.assertRaises(ValueError):
                shards.validate_plan(plan)
        with self.assertRaises(ValueError):
            shards.measure_shard(self.plan, True, self.root / "bad-number")
        directory = self.root / "wrong-manifest"
        shards.measure_shard(self.plan, 0, directory, stop_at=0)
        manifest = json.loads((directory / "manifest.json").read_bytes())
        manifest["plan_sha256"] = "foreign"
        (directory / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            shards.measure_shard(self.plan, 0, directory)

    def test_paths_foreign_files_and_duplicate_json(self):
        source = self.root / "source"
        source.write_bytes(b"preserve")
        hard = self.root / "hard"
        os.link(source, hard)
        for path in (source, hard):
            with self.assertRaisesRegex(ValueError, "alias"):
                shards.protect_paths([source], [path])
        shards.protect_paths([source], [self.root / "absent"])
        worker = self.root / "worker"
        worker.mkdir()
        (worker / "foreign.json").write_bytes(b"{}")
        with self.assertRaises(ValueError):
            shards.measure_shard(self.plan, 0, worker)
        (worker / "foreign.json").unlink()
        (worker / "group-A_A.json").write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "no manifest"):
            shards.measure_shard(self.plan, 0, worker)
        linked = self.root / "linked"
        linked.symlink_to(worker, target_is_directory=True)
        with self.assertRaises(ValueError):
            shards.measure_shard(self.plan, 0, linked)
        paths = self._wave(self.plan, "duplicate-json")
        self._record_checkpoint(
            paths[0], "A_A", b'{"__metadata__":{},"__metadata__":{}}'
        )
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            shards.assemble(self.plan, paths)
        (paths[0] / "foreign.json").write_bytes(b"{}")
        with self.assertRaises(ValueError):
            shards.assemble(self.plan, paths)

    def test_worker_deadline_after_a_partial_pass_and_pending_rejection(self):
        path = self.root / "partial"
        real_pass = shards.ShardRun.sample_pass

        def partial(current):
            current.args.checkpoint_frequency = 1
            real_pass(current)

        clock = {"expired": False}

        def one_pass(current):
            partial(current)
            clock["expired"] = True

        with patch.object(shards.ShardRun, "sample_pass", one_pass), patch.object(
            shards.time, "time", side_effect=lambda: 11 if clock["expired"] else 0
        ):
            self.assertFalse(shards.measure_shard(self.plan, 0, path, stop_at=10))
        self.assertTrue(shards.measure_shard(self.plan, 0, path))
        saved = json.loads(self._checkpoint(path, "A_A").read_bytes())
        saved["__metadata__"]["phase"] = "transition_pending"
        self._record_checkpoint(path, "A_A", json.dumps(saved).encode())
        with self.assertRaises(ValueError):
            shards.measure_shard(self.plan, 0, path)

    def test_bundle_failure_cleanup_and_completion_reader(self):
        for files in ({"../escape": b"{}"}, {"bundle.json": b"{}"}):
            with self.assertRaises(ValueError):
                shards.install_bundle(self.root / "invalid", files, {})
        output = self.root / "interrupted"
        with patch.object(Path, "rename", side_effect=OSError("interruption")):
            with self.assertRaises(OSError):
                shards.install_bundle(output, {"table.json": b"{}"}, {"success": True})
        self.assertFalse(output.exists())
        self.assertFalse(Path(str(output) + ".lock").exists())
        self.assertEqual(list(self.root.glob(".v4-assembly-*")), [])
        shards.install_bundle(output, {"table.json": b"{}"}, {"success": True})
        self.assertEqual(
            shards.read_bundle(output)["files"],
            {"table.json": shards.file_digest(output / "table.json")},
        )
        manifest_path = output / "bundle.json"
        original = manifest_path.read_bytes()
        for change in (
            lambda m: m.update(success=False),
            lambda m: m.update(files=[]),
            lambda m: m.update(files={"../escape": "digest"}),
        ):
            manifest = json.loads(original)
            change(manifest)
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                shards.read_bundle(output)
        manifest_path.write_bytes(original)
        (output / "table.json").write_bytes(b"{ }")
        with self.assertRaisesRegex(ValueError, "digest"):
            shards.read_bundle(output)
        (output / "extra.json").write_bytes(b"{}")
        with self.assertRaises(ValueError):
            shards.read_bundle(output)
        manifest_path.unlink()
        manifest_path.symlink_to(self.root / "missing")
        with self.assertRaises(ValueError):
            shards.read_bundle(output)

    def test_finalize_rejects_rebuilt_client_digest_mismatch(self):
        reference, plan_path, assembled, _final = self._cli_pipeline()
        plan = json.loads(plan_path.read_bytes())
        client = assembled / "expected_crib_points.client.json"
        with patch.object(
            shards, "client_bytes", return_value=client.read_bytes() + b" "
        ), self.assertRaisesRegex(ValueError, "Rebuilt client digest"):
            shards.final_output(plan, assembled, reference)

    def test_real_cli_pipeline_and_reference_pinning(self):
        reference, current_path, assembled, final = self._cli_pipeline()
        self.assertEqual(shards.read_bundle(final)["kind"], "shadow")
        final_plan = json.loads(current_path.read_bytes())
        wrong = copy.deepcopy(final_plan)
        wrong["reference"] = {}
        wrong["sha256"] = _digest({k: v for k, v in wrong.items() if k != "sha256"})
        with self.assertRaises(ValueError):
            shards.final_output(wrong, assembled, reference)
        with patch.object(
            shards, "reference_files", return_value={}
        ), self.assertRaisesRegex(ValueError, "reference digest"):
            shards.final_output(final_plan, assembled, reference)
        with patch.object(
            shards, "_should_stop_after_complete", return_value=False
        ), self.assertRaisesRegex(ValueError, "not converged"):
            shards.final_output(final_plan, assembled, reference)
        client = reference / "expected_crib_points.client.json"
        client.write_bytes(b"{}")
        self._record_reference(reference)
        with self.assertRaisesRegex(ValueError, "means differ"):
            shards.reference_files(reference)
        full_path = reference / "expected_crib_points.json"
        full = json.loads(full_path.read_bytes())
        full["__metadata__"]["generation_method"] = "unknown"
        full_path.write_bytes(shards.json_bytes(full))
        self._record_reference(reference)
        with self.assertRaisesRegex(ValueError, "v3 table"):
            shards.reference_files(reference)

    def test_cli_rejects_output_containing_inputs_and_help(self):
        with patch.object(
            sys, "argv", ["crib_v4_shards", "--help"]
        ), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            runpy.run_path(str(Path(shards.__file__)), run_name="__main__")
        with self.assertRaises(ValueError):
            _protect_directory([self.root / "input"], self.root)
        with self.assertRaises(ValueError):
            shards.protect_paths([self.root], [self.root])
        source_directory = self.root / "source-directory"
        source_directory.mkdir()
        with self.assertRaises(ValueError):
            _protect_directory([source_directory], source_directory / "nested-output")
        reference = self._reference()
        bootstrap = self.root / "bootstrap.json"
        bootstrap.write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "all canonical keys"):
            shards.main(
                [
                    "plan",
                    "--bootstrap",
                    str(bootstrap),
                    "--reference",
                    str(reference),
                    "--output",
                    str(self.root / "bad-plan"),
                ]
            )
        self.assertFalse((self.root / "bad-plan").exists())


class TestShardStorageBoundaries(ShardedV4Fixture):
    def test_snapshot_atomicity_and_manifest_failure_preserve_last_commit(self):
        directory = self.root / "snapshots-test"
        directory.mkdir()
        raw = b"{}"
        digest = _save_snapshot(directory, "group-A_A.json", raw)
        self.assertEqual(_save_snapshot(directory, "group-A_A.json", raw), digest)
        path = _snapshot_path(directory, "group-A_A.json", digest)
        path.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "immutable"):
            _save_snapshot(directory, "group-A_A.json", raw)
        path.unlink()
        with self.assertRaisesRegex(ValueError, "Missing"):
            _snapshot_bytes(directory, "group-A_A.json", digest)
        path.symlink_to(self.root / "absent")
        with self.assertRaisesRegex(ValueError, "linked"):
            _snapshot_bytes(directory, "group-A_A.json", digest)
        for value in (False, "short", "x" * 64):
            with self.assertRaisesRegex(ValueError, "digest"):
                _snapshot_path(directory, "group-A_A.json", value)
        manifest = directory / "manifest.json"
        manifest.write_bytes(b"previous")
        with patch.object(shards.os, "replace", side_effect=OSError("interrupt")):
            with self.assertRaises(OSError):
                _write_manifest(manifest, {"next": True})
        self.assertEqual(manifest.read_bytes(), b"previous")
        self.assertEqual(list(directory.glob(".manifest-*")), [])

    def test_interrupted_pointer_commit_resumes_without_duplicate_rows(self):
        directory = self.root / "pointer"
        original = _write_manifest

        def fail_on_checkpoint(path, value):
            if value["files"]:
                raise OSError("interrupted before pointer commit")
            original(path, value)

        with patch(
            "artifact_pipeline.crib_v4_shards._write_manifest", fail_on_checkpoint
        ):
            with self.assertRaises(OSError):
                shards.measure_shard(self.plan, 0, directory)
        self.assertEqual(
            json.loads((directory / "manifest.json").read_bytes())["files"], {}
        )
        self.assertTrue(shards.measure_shard(self.plan, 0, directory))
        self.assertEqual(len(list((directory / "snapshots").iterdir())), 1)
        complete = json.loads(self._checkpoint(directory, "A_A").read_bytes())
        self.assertEqual(
            complete["__metadata__"]["estimator_state"]["A_A"]["Dealer"]["streams"][
                "base"
            ]["count"],
            2,
        )
        self.assertEqual(list(directory.glob(".working-*")), [])
        fresh = self.root / "fresh-pointer"
        shards.measure_shard(self.plan, 0, fresh)
        self.assertEqual(
            self._checkpoint(directory, "A_A").read_bytes(),
            self._checkpoint(fresh, "A_A").read_bytes(),
        )

    def test_worker_lock_and_foreign_snapshot_rejections(self):
        directory = self.root / "locked-worker"
        lock = Path(str(directory) + ".lock")
        lock.mkdir()
        with self.assertRaisesRegex(ValueError, "locked"):
            shards.measure_shard(self.plan, 0, directory)
        lock.rmdir()
        shards.measure_shard(self.plan, 0, directory)
        snapshots = directory / "snapshots"
        linked = snapshots / "linked"
        linked.symlink_to(self._checkpoint(directory, "A_A"))
        with self.assertRaises(ValueError):
            shards.measure_shard(self.plan, 0, directory)
        linked.unlink()
        (snapshots / "foreign.json").write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "Foreign immutable"):
            shards.measure_shard(self.plan, 0, directory)
        (snapshots / "foreign.json").unlink()
        (snapshots / "nested").mkdir()
        with self.assertRaisesRegex(ValueError, "Invalid snapshot"):
            shards.measure_shard(self.plan, 0, directory)
        (snapshots / "nested").rmdir()
        stage_link = directory / ".working-linked"
        stage_link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Linked worker"):
            shards.measure_shard(self.plan, 0, directory)
        stage_link.unlink()
        stale = directory / ".working-stale"
        stale.mkdir()
        self.assertTrue(shards.measure_shard(self.plan, 0, directory))
        document = json.loads(self._checkpoint(directory, "A_A").read_bytes())
        document["__metadata__"]["phase"] = "sampling"
        self._record_checkpoint(directory, "A_A", shards.json_bytes(document))
        with self.assertRaisesRegex(ValueError, "partial checkpoint"):
            shards.measure_shard(self.plan, 0, directory)
        with self.assertRaisesRegex(ValueError, "complete groups"):
            _load_shard(self.plan, directory, set())

    def test_foreign_self_consistent_policy_is_rejected_before_writing(self):
        directory = self._wave(self.plan, "foreign-policy")[0]
        document = json.loads(self._checkpoint(directory, "A_A").read_bytes())
        document["__metadata__"].update(
            generation_accumulators={}, policy_sha256=_policy_hash({})
        )
        checkpoint = self._record_checkpoint(
            directory, "A_A", shards.json_bytes(document)
        )
        raw = checkpoint.read_bytes()
        manifest = (directory / "manifest.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "expected generation/policy"):
            _load_shard(self.plan, directory, set())
        with self.assertRaisesRegex(ValueError, "expected generation/policy"):
            shards.measure_shard(self.plan, 0, directory)
        self.assertEqual(checkpoint.read_bytes(), raw)
        self.assertEqual((directory / "manifest.json").read_bytes(), manifest)

    def test_valid_one_row_moments_cannot_claim_completed_target(self):
        directory = self._wave(self.plan, "short-count")[0]
        document = json.loads(self._checkpoint(directory, "A_A").read_bytes())
        for entry in document["__metadata__"]["estimator_state"]["A_A"].values():
            for name, stream in list(entry["streams"].items()):
                moments = empty_moments(stream["labels"])
                add_row(moments, [0] * len(stream["labels"]))
                entry["streams"][name] = encode_moments(moments)
        self._record_checkpoint(directory, "A_A", shards.json_bytes(document))
        with self.assertRaisesRegex(ValueError, "incomplete groups"):
            _load_shard(self.plan, directory, set())

    def test_displayed_means_cannot_replace_joint_moments(self):
        directories = self._wave(self.plan, "displayed")
        expected, following = shards.assemble(self.plan, directories)
        document = json.loads(self._checkpoint(directories[1], "A_2").read_bytes())
        for key in ("A_2_Suited", "A_2_Unsuited"):
            for cuts in document[key].values():
                for bucket in cuts.values():
                    bucket.update(mu=-999, se=0, n=0)
        self._record_checkpoint(directories[1], "A_2", shards.json_bytes(document))
        actual, next_plan = shards.assemble(self.plan, directories)
        self.assertEqual(actual, expected)
        self.assertEqual(next_plan, following)

    def test_assembly_detects_missing_returned_groups(self):
        paths = self._wave(self.plan, "loader")

        def omit_group(plan, directory, seen):
            result = _load_shard(plan, directory, seen)
            result.pop("A_A", None)
            return result

        with patch(
            "artifact_pipeline.crib_v4_shards._load_shard", omit_group
        ), self.assertRaisesRegex(ValueError, "coverage"):
            shards.assemble(self.plan, paths)
        with self.assertRaises(ValueError):
            _decode_full(self.plan, {"estimator_state": {}})

    def test_reference_asset_identity_and_release_tag_checks(self):
        directory = self._reference()
        original = (directory / "release.json").read_bytes()
        for field, value in (("id", True), ("id", 0), ("digest", "wrong"), ("size", 0)):
            record = json.loads(original)
            record["assets"][0][field] = value
            (directory / "release.json").write_bytes(shards.json_bytes(record))
            with self.assertRaisesRegex(ValueError, "asset"):
                shards.reference_files(directory)
        record = json.loads(original)
        record["tag_name"] = "other-tag"
        (directory / "release.json").write_bytes(shards.json_bytes(record))
        with self.assertRaisesRegex(ValueError, "release tag"):
            shards.reference_files(directory)

    def test_final_output_rejects_partial_and_absolute_comparison_sees_shared_base(
        self,
    ):
        reference, plan_path, assembled, _final = self._cli_pipeline()
        output = json.loads((assembled / "expected_crib_points.json").read_bytes())
        baseline = json.loads((reference / "expected_crib_points.json").read_bytes())
        offset = copy.deepcopy(output)
        for key, roles in offset.items():
            if key != "__metadata__":
                for cuts in roles.values():
                    for bucket in cuts.values():
                        bucket["mu"] += 1
        comparison = _comparison(offset, baseline)
        self.assertEqual(comparison["record_count"], 78)
        self.assertTrue(
            any(
                r["identity"].startswith("A_A_Unsuited/")
                for r in comparison["absolute"]
            )
        )
        self.assertAlmostEqual(comparison["max_absolute_difference"]["difference"], 1)
        self.assertTrue(
            all(abs(r["difference"] - 1) < 1e-12 for r in comparison["absolute"])
        )
        plan = json.loads(plan_path.read_bytes())
        plan["metadata"]["run_control"]["target_samples"] = 3
        plan["sha256"] = _digest({k: v for k, v in plan.items() if k != "sha256"})
        output["__metadata__"]["run_control"]["target_samples"] = 3
        output["__metadata__"]["phase"] = "sampling"
        partial = self.root / "partial-final"
        shards.install_bundle(
            partial,
            {"expected_crib_points.json": shards.json_bytes(output)},
            {
                "kind": "generation",
                "success": True,
                "terminal": True,
                "plan_sha256": plan["sha256"],
            },
        )
        with self.assertRaisesRegex(ValueError, "complete checkpoint"):
            shards.final_output(plan, partial, reference)

    def test_infinite_diagnostics_are_unavailable_and_failed_convergence(self):
        _reference, plan_path, assembled, _final = self._cli_pipeline()
        plan = json.loads(plan_path.read_bytes())
        metadata = json.loads((assembled / "expected_crib_points.json").read_bytes())[
            "__metadata__"
        ]
        state = {**metadata, "estimator_state": _decode_full(plan, metadata)}
        with patch.object(
            generate_table, "calculate_max_ev_shift", return_value=float("inf")
        ):
            diagnostics = shards.generation_diagnostics(state, {"rows": []})
        self.assertIsNone(diagnostics["convergence_shift"])
        with patch.object(generate_table, "calculate_max_ev_shift", return_value=3.25):
            self.assertEqual(
                shards.generation_diagnostics(state, {"rows": []})["convergence_shift"],
                3.25,
            )
        args = copy.copy(self.args)
        args.max_generations = 1
        limited = shards.initial_plan(args, PAIRS)
        with self.assertRaisesRegex(RuntimeError, "before convergence"):
            shards.assemble(limited, self._wave(limited, "failed-convergence"))

    def test_failed_convergence_keeps_its_measured_shift_in_logs(self):
        args = copy.copy(self.args)
        args.convergence_threshold = 0
        plan = shards.initial_plan(args, PAIRS)
        _output, following = shards.assemble(plan, self._wave(plan, "log-first"))
        paths = self._wave(following, "log-second")
        log = io.StringIO()
        with contextlib.redirect_stdout(log), self.assertRaisesRegex(
            RuntimeError, "before convergence"
        ):
            shards.assemble(following, paths)
        facts = [
            json.loads(line)
            for line in log.getvalue().splitlines()
            if json.loads(line)["event"] == "assembly-diagnostics"
        ][0]
        self.assertGreater(facts["convergence_shift"], 0)
        self.assertEqual(facts["counts"]["A_A"]["Dealer"]["base"], 2)

    def test_failed_pointer_update_preserves_the_preceding_snapshot(self):
        directory = self.root / "previous-pointer"
        clock = {"expired": False}
        real_pass = shards.ShardRun.sample_pass

        def one_pass(current):
            current.args.checkpoint_frequency = 1
            real_pass(current)
            clock["expired"] = True

        with patch.object(shards.ShardRun, "sample_pass", one_pass), patch.object(
            shards.time, "time", side_effect=lambda: 11 if clock["expired"] else 0
        ):
            self.assertFalse(shards.measure_shard(self.plan, 0, directory, stop_at=10))
        checkpoint = self._checkpoint(directory, "A_A")
        original = checkpoint.read_bytes()
        manifest = (directory / "manifest.json").read_bytes()
        with patch(
            "artifact_pipeline.crib_v4_shards._write_manifest",
            side_effect=OSError("pointer update failed"),
        ):
            with self.assertRaises(OSError):
                shards.measure_shard(self.plan, 0, directory)
        self.assertEqual(checkpoint.read_bytes(), original)
        self.assertEqual((directory / "manifest.json").read_bytes(), manifest)
        self.assertTrue(shards.measure_shard(self.plan, 0, directory))
        self.assertEqual(len(list((directory / "snapshots").iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
