"""Tests for the strength-ladder command line (issue #263)."""

from __future__ import annotations

from collections import Counter
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import random
import shutil
import tempfile
import unittest
from unittest.mock import patch

from artifact_pipeline.generate_play_table import DiscardPolicy
from artifact_pipeline.ladder_match import run_ladder
from artifact_pipeline.pegging import DEALER, PONE
from artifact_pipeline.six_layer_policy import SixLayerPolicy
from artifact_pipeline.strength_ladder import (
    SCHEMA,
    RankDiscardRule,
    _plus_minus,
    build_players,
    format_summary,
    main,
    parse_args,
)
from artifact_pipeline.table_discards import TableDiscardRule
from artifact_pipeline.test_fixed_policy_fixtures import make_bundle
from artifact_pipeline.test_table_discards import crib_json, play_json

RANDOM_ARGS = ["--discards", "random", "--rungs", "random,heuristic"]


def bundle_in(directory: Path) -> Path:
    directory.mkdir()
    return make_bundle(directory)


def run_cli(argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(argv)
    return code, out.getvalue()


def rejected(test, argv):
    with redirect_stderr(io.StringIO()) as err, test.assertRaises(SystemExit):
        parse_args(argv)
    return err.getvalue()


class TestRankDiscardRule(unittest.TestCase):
    def test_keeps_the_named_ranks(self):
        keeps = {
            (PONE, (0, 0, 5, 7, 9, 12)): (0, 0, 5, 7),
            (DEALER, (0, 1, 2, 3, 3, 4)): (1, 2, 3, 4),
        }
        rule = RankDiscardRule(DiscardPolicy(keeps))
        dealt = [(12, 0), (0, 3), (9, 1), (5, 2), (0, 1), (7, 0)]
        self.assertEqual(
            rule.select_discard(PONE, dealt, random.Random(0)),
            (((0, 1), (0, 3), (5, 2), (7, 0)), ((9, 1), (12, 0))),
        )
        dealt = [(3, 2), (0, 0), (4, 1), (3, 0), (2, 3), (1, 1)]
        kept, discarded = rule.select_discard(DEALER, dealt, random.Random(0))
        self.assertEqual([card[0] for card in kept], [1, 2, 3, 4])
        self.assertEqual(sorted(kept + discarded), sorted(dealt))

    def test_the_stream_picks_which_card_of_a_kept_rank(self):
        rule = RankDiscardRule(
            DiscardPolicy({(DEALER, (0, 1, 2, 3, 3, 4)): (1, 2, 3, 4)})
        )
        dealt = [(3, 2), (0, 0), (4, 1), (3, 0), (2, 3), (1, 1)]
        kept_three = Counter(
            next(
                card
                for card in rule.select_discard(DEALER, dealt, random.Random(seed))[0]
                if card[0] == 3
            )
            for seed in range(400)
        )
        # Either Four is kept about half the time (200 expected, sd 10).
        self.assertEqual(set(kept_three), {(3, 0), (3, 2)})
        self.assertTrue(
            all(150 < count < 250 for count in kept_three.values()), kept_three
        )
        self.assertEqual(
            rule.select_discard(DEALER, dealt, random.Random(9)),
            rule.select_discard(DEALER, dealt, random.Random(9)),
        )


class TestArguments(unittest.TestCase):
    def test_rejects_bad_rungs_counts_and_manifest_use(self):
        for argv in (
            ["--discards", "random", "--rungs", "random"],
            ["--discards", "random", "--rungs", "random,random"],
            ["--discards", "random", "--rungs", "random,expert"],
            ["--rungs", "random,heuristic"],
            ["--discards", "random", "--rungs", "random,cfr"],
            [*RANDOM_ARGS, "--policy-manifest", "policy.json"],
            [*RANDOM_ARGS, "--pairs", "0"],
            [*RANDOM_ARGS, "--workers", "0"],
            [*RANDOM_ARGS, "--cache-limit", "0"],
            [*RANDOM_ARGS, "--output", "no/such/directory/ladder.json"],
        ):
            rejected(self, argv)
        args = parse_args(["--discards", "random", "--rungs", " heuristic , random"])
        self.assertEqual(args.rungs, ["heuristic", "random"])

    def test_workers_need_the_fork_start_method(self):
        with patch("multiprocessing.get_all_start_methods", return_value=["spawn"]):
            self.assertTrue("fork" in rejected(self, [*RANDOM_ARGS, "--workers", "2"]))
            self.assertEqual(parse_args([*RANDOM_ARGS, "--workers", "1"]).workers, 1)

    def test_output_must_not_touch_the_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = bundle_in(root / "bundle")
            before = manifest.read_bytes()
            outside = root / "report.json"
            os.link(manifest, outside)
            base = ["--policy-manifest", str(manifest), "--rungs", "random,heuristic"]
            for output in (manifest, root / "bundle" / "new.json", outside):
                message = rejected(self, [*base, "--output", str(output)])
                self.assertTrue("bundle" in message, message)
            self.assertEqual(manifest.read_bytes(), before)
            parse_args([*base, "--output", str(root / "fresh.json")])
            # Through a symbolic link, the guard and the loader use the target.
            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            (elsewhere / "policy.json").symlink_to(manifest)
            linked = ["--policy-manifest", str(elsewhere / "policy.json")]
            args = parse_args([*linked, "--output", str(elsewhere / "discards.json")])
            self.assertEqual(args.policy_manifest, manifest.resolve())
            rejected(
                self, [*linked, "--output", str(root / "bundle" / "discards.json")]
            )

    def test_plus_minus_shows_what_is_known(self):
        self.assertEqual(_plus_minus(None, None), "n/a")
        self.assertEqual(_plus_minus(0.5, None, 100), "50.00")
        self.assertEqual(_plus_minus(0.5612, 0.0011, 100), "56.12 +/- 0.11")


def stat(mu, se):
    return {"n": 10, "mu": mu, "se": se}


def match_summary(player, opponent, win, outcomes, decisions):
    return {
        "player": player,
        "opponent": opponent,
        "win_rate": stat(win, 0.01),
        "elo": 190.8 if win > 0.5 else -190.8,
        "elo_se": 3.0,
        "pair_outcomes": dict(zip(("both_won", "split", "both_lost"), outcomes)),
        "point_margin": stat(4.0 if win > 0.5 else -4.0, 0.5),
        "policy_decisions": decisions,
    }


class TestFormatSummary(unittest.TestCase):
    def test_rows_are_higher_rungs_against_lower_ones(self):
        counts = {
            "forced": 4000,
            "heuristic_equivalent": 300,
            "missing_menu_fallback": 2,
            "off_support": 17,
            "trained": 5000,
        }
        report = {
            "pairs_per_match": 10,
            "seed": 1,
            "provenance": {"discards": "random"},
            "rungs": [{"name": "low"}, {"name": "mid"}, {"name": "high"}],
            "matches": [
                match_summary("mid", "low", 0.75, (6, 3, 1), {}),
                match_summary("low", "mid", 0.25, (1, 3, 6), {}),
                match_summary("high", "low", 0.75, (6, 3, 1), {"high": counts}),
            ],
        }
        lines = format_summary(report).splitlines()
        self.assertEqual(
            lines[4:],
            [
                "| mid vs low | 75.00 +/- 1.00 | 190.80 +/- 3.00 | 6 / 3 / 1 "
                "| 4.00 +/- 0.50 | n/a |",
                "| high vs low | 75.00 +/- 1.00 | 190.80 +/- 3.00 | 6 / 3 / 1 "
                "| 4.00 +/- 0.50 | 2 / 17 / 9,319 |",
            ],
        )


class TestMain(unittest.TestCase):
    @staticmethod
    def bundle_ladder():
        """Run the CLI twice on a fixture bundle, with and without workers."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = bundle_in(root / "bundle")
            manifest_bytes = manifest.read_bytes()
            argv = [
                "--policy-manifest",
                str(manifest),
                "--policy-manifest-sha256",
                hashlib.sha256(manifest_bytes).hexdigest(),
                "--pairs",
                "6",
                "--cross-table",
            ]
            reports = []
            for extra in (["--workers", "2"], []):
                output = root / "ladder.json"
                code, printed = run_cli([*argv, *extra, "--output", str(output)])
                assert code == 0
                reports.append(json.loads(output.read_text(encoding="utf-8")))
            with SixLayerPolicy(manifest) as policy:
                fingerprint = policy.behavioral_fingerprint
            return reports, printed, manifest_bytes, fingerprint

    def test_bundle_ladder_cross_table_report(self):
        (report, again), printed, manifest_bytes, fingerprint = self.bundle_ladder()
        self.assertEqual(again, report)
        population = json.loads(manifest_bytes)["discard_population"]
        self.assertEqual(report["schema"], SCHEMA)
        self.assertEqual(
            report["provenance"],
            {
                "discards": "bundle",
                "policy_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "policy_fingerprint": fingerprint,
                "discard_population_sha256": population["sha256"],
            },
        )
        self.assertEqual(
            [r["name"] for r in report["rungs"]], ["random", "heuristic", "cfr"]
        )
        pairs = {(m["player"], m["opponent"]) for m in report["matches"]}
        self.assertEqual(len(pairs), 6)
        for match in report["matches"]:
            self.assertEqual(match["pairs"], 6)
            uses_cfr = "cfr" in (match["player"], match["opponent"])
            self.assertEqual(
                list(match["policy_decisions"]), ["cfr"] if uses_cfr else []
            )
            if uses_cfr:
                self.assertGreater(sum(match["policy_decisions"]["cfr"].values()), 0)
        lines = printed.splitlines()
        self.assertTrue(
            "6 deal pairs per match, seed 42, bundle discards" in lines[0], lines[0]
        )
        rows = [line.split(" | ")[0] for line in lines[4:]]
        self.assertEqual(
            rows, ["| heuristic vs random", "| cfr vs random", "| cfr vs heuristic"]
        )

    def test_every_rung_shares_the_bundle_discard_rule(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            manifest = make_bundle(Path(directory))
            args = parse_args(["--policy-manifest", str(manifest)])
            players, _ = build_players(args, stack)
            rules = {id(player.discard_rule) for player in players}
            self.assertEqual(len(rules), 1)
            self.assertIsInstance(players[0].discard_rule, RankDiscardRule)
            self.assertIsInstance(players[2].pegging_policy, SixLayerPolicy)

    def test_bundle_discards_without_the_cfr_rung_skip_the_policy(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            manifest = make_bundle(Path(directory))
            args = parse_args(
                ["--policy-manifest", str(manifest), "--rungs", "random,heuristic"]
            )
            with patch(
                "artifact_pipeline.strength_ladder.SixLayerPolicy"
            ) as policy_class:
                players, provenance = build_players(args, stack)
            policy_class.assert_not_called()
            self.assertIsInstance(players[0].discard_rule, RankDiscardRule)
            self.assertNotIn("policy_fingerprint", provenance)

    def test_refuses_unverified_or_changed_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = make_bundle(Path(directory))
            base = ["--policy-manifest", str(manifest), "--pairs", "1"]
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                main([*base, "--policy-manifest-sha256", "0" * 64])
            replaced = json.loads(manifest.read_bytes())
            replaced["discard_population"]["description"] = "replaced while loading"
            with patch.object(
                SixLayerPolicy, "manifest", replaced
            ), self.assertRaisesRegex(ValueError, "changed while"):
                main(base)
            (Path(directory) / "discards.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                main([*base, "--rungs", "random,heuristic"])

    def test_random_discards_need_no_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "ladder.json"
            code, printed = run_cli(
                [*RANDOM_ARGS, "--pairs", "4", "--output", str(output)]
            )
            report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(report["provenance"], {"discards": "random"})
        self.assertEqual(len(report["matches"]), 2)
        with patch(
            "artifact_pipeline.strength_ladder.run_ladder", wraps=run_ladder
        ) as spy:
            self.assertEqual(
                run_cli([*RANDOM_ARGS, "--pairs", "4", "--workers", "2"]), (0, printed)
            )
        self.assertEqual(spy.call_args.kwargs["workers"], 2)


class TestTablePlayers(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.crib = self.root / "crib.json"
        self.play = self.root / "play.json"
        self.crib.write_text(json.dumps(crib_json()), encoding="utf-8")
        self.play.write_text(json.dumps(play_json()), encoding="utf-8")

    def table_args(self, name, pegging, crib="none", play="none"):
        return ["--table-player", name, pegging, str(crib), str(play)]

    def test_rejects_bad_table_players(self):
        app = self.table_args("app", "heuristic", self.crib)
        for argv in (
            [*app, *app, "--rungs", "app,heuristic", "--discards", "random"],
            [*self.table_args("cfr", "heuristic"), "--discards", "random"],
            [*self.table_args("app", "expert"), "--discards", "random"],
            [*app, "--rungs", "app,other"],
            [*self.table_args("app", "cfr"), "--rungs", "app,heuristic"],
            [*app, "--rungs", "app,heuristic"],
            [
                *app,
                *self.table_args("hand", "random"),
                "--rungs",
                "app,hand",
                "--policy-manifest",
                "policy.json",
            ],
            [
                *app,
                "--rungs",
                "app,heuristic",
                "--discards",
                "random",
                "--output",
                str(self.crib),
            ],
        ):
            rejected(self, argv)
        args = parse_args(
            [*app, *self.table_args("hand", "random"), "--rungs", "hand,app"]
        )
        self.assertEqual(args.rungs, ["hand", "app"])
        with patch.object(Path, "exists", return_value=False):
            parse_args(
                [
                    *app,
                    "--rungs",
                    "app,heuristic",
                    "--discards",
                    "random",
                    "--output",
                    str(self.crib),
                ]
            )

    def test_default_rungs_put_table_players_last(self):
        manifest = bundle_in(self.root / "bundle")
        args = parse_args(
            [
                "--policy-manifest",
                str(manifest),
                *self.table_args("app", "cfr", self.crib, self.play),
            ]
        )
        self.assertEqual(args.rungs, ["random", "heuristic", "cfr", "app"])

    def test_table_players_record_their_tables_and_pegging(self):
        manifest = bundle_in(self.root / "bundle")
        argv = [
            "--policy-manifest",
            str(manifest),
            "--rungs",
            "hand,heuristic,app",
            *self.table_args("hand", "random"),
            *self.table_args("app", "cfr", self.crib, self.play),
        ]
        with ExitStack() as stack:
            players, provenance = build_players(parse_args(argv), stack)
            self.assertEqual([p.name for p in players], ["hand", "heuristic", "app"])
            hand, heuristic, app = players[0], players[1], players[2]
            self.assertIsInstance(hand.discard_rule, TableDiscardRule)
            self.assertIsInstance(app.discard_rule, TableDiscardRule)
            self.assertIsInstance(heuristic.discard_rule, RankDiscardRule)
            self.assertIsInstance(app.pegging_policy, SixLayerPolicy)
            self.assertEqual(
                hand.pegging_policy.__class__.__name__, "RandomPeggingPolicy"
            )
            self.assertTrue(app.description.startswith("app-table discards, CFR+"))
        digest = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (self.crib, self.play)
        }
        self.assertEqual(
            provenance["table_players"],
            {
                "hand": {"pegging": "random"},
                "app": {
                    "pegging": "cfr",
                    "crib_sha256": digest[self.crib],
                    "play_sha256": digest[self.play],
                },
            },
        )
        dealt = [(0, 2), (0, 3), (3, 2), (6, 1), (9, 0), (9, 1)]
        crib_only = TableDiscardRule()
        self.assertEqual(
            hand.discard_rule.keep_value(PONE, dealt[:4], dealt),
            crib_only.keep_value(PONE, dealt[:4], dealt),
        )
        self.assertNotEqual(
            app.discard_rule.keep_value(PONE, dealt[:4], dealt),
            crib_only.keep_value(PONE, dealt[:4], dealt),
        )

    def test_a_table_only_ladder_runs_without_a_bundle(self):
        output = self.root / "ladder.json"
        code, printed = run_cli(
            [
                *self.table_args("hand", "heuristic"),
                *self.table_args("app", "heuristic", self.crib, self.play),
                "--rungs",
                "hand,app",
                "--pairs",
                "3",
                "--output",
                str(output),
            ]
        )
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(
            [r["description"] for r in report["rungs"]],
            ["app-table discards, legacy simulator's default play"] * 2,
        )
        self.assertTrue(
            "seed 42, app-table discards for hand, app. Win" in printed, printed
        )
        _, mixed = run_cli(
            [
                *self.table_args("app", "heuristic", self.crib),
                "--discards",
                "random",
                "--rungs",
                "random,app",
                "--pairs",
                "2",
            ]
        )
        self.assertTrue("random discards; app-table discards for app." in mixed, mixed)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
