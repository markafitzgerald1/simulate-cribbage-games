"""Survey partition, orchestration and provenance regressions without sampling."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_crib_v4_diagnostic as diagnostic
from scripts import run_crib_v4_survey as survey


class TestSurvey(unittest.TestCase):
    """Pin the approved experiment independently of dispatch inputs."""

    def test_partition_covers_every_distinct_pair_once(self):
        ranks = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K")
        expected = {f"{a}_{b}" for i, a in enumerate(ranks) for b in ranks[i + 1 :]}
        groups = [group for shard in survey.SHARDS.values() for group in shard]
        self.assertEqual(len(groups), 78)
        self.assertEqual(set(groups), expected)
        self.assertEqual(sorted(map(len, survey.SHARDS.values())), [19, 19, 20, 20])
        self.assertEqual(
            [sum("J" in g for g in s) for s in survey.SHARDS.values()], [3, 3, 3, 3]
        )

    def test_all_shards_use_fixed_target_and_manifest_rejects_other_shards(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, client, output = root / "source", root / "client", root / "out"
            source.write_text("source")
            client.write_text("client")
            with patch.object(diagnostic, "verified_inputs"), patch.object(
                diagnostic.measure_crib_v4, "main", return_value=True
            ) as measure, patch.object(
                diagnostic.time, "time", return_value=0
            ), contextlib.redirect_stdout(
                io.StringIO()
            ):
                for shard, groups in survey.SHARDS.items():
                    destination = output / shard
                    summary = survey.run(source, client, destination, 100, shard)
                    self.assertTrue(summary["complete"])
                    self.assertEqual(list(summary["groups"]), list(groups))
                    identity = json.loads((destination / "manifest.json").read_text())
                    self.assertEqual(identity["samples"], 22000)
                    self.assertEqual(identity["shard"], shard)
                    self.assertTrue(
                        "scripts/run_crib_v4_survey.py" in identity["files"]
                    )
                    self.assertTrue(
                        ".github/workflows/survey-crib-v4.yml" in identity["files"]
                    )
                    self.assertEqual(measure.call_count, len(groups))
                    for group, call in zip(groups, measure.call_args_list, strict=True):
                        args = call.args[0]
                        self.assertEqual(args[args.index("--rank-group") + 1], group)
                        self.assertEqual(
                            args[args.index("--output") + 1],
                            str(destination / f"group-{group}.json"),
                        )
                        self.assertEqual(args[args.index("--source") + 1], str(source))
                        self.assertEqual(args[args.index("--samples") + 1], "22000")
                        self.assertEqual(
                            args[args.index("--checkpoint-frequency") + 1], "1000"
                        )
                        self.assertEqual(args[args.index("--stop-at") + 1], "100")
                    measure.reset_mock()
                    with self.assertRaisesRegex(ValueError, "manifest differs"):
                        survey.run(
                            source,
                            client,
                            destination,
                            100,
                            "2" if shard == "1" else "1",
                        )
                    measure.assert_not_called()

    def test_resume_origin_is_survey_only(self):
        valid = {
            "event": "workflow_dispatch",
            "status": "completed",
            "path": ".github/workflows/survey-crib-v4.yml",
            "repository": {"full_name": "owner/repo"},
            "head_repository": {"full_name": "owner/repo"},
        }
        survey.validate_resume_run(valid, "owner/repo")
        for field, value in (
            ("path", ".github/workflows/diagnose-crib-v4.yml"),
            ("event", "pull_request"),
            ("status", "in_progress"),
            ("repository", {"full_name": "fork/repo"}),
            ("head_repository", None),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                survey.validate_resume_run({**valid, field: value}, "owner/repo")
