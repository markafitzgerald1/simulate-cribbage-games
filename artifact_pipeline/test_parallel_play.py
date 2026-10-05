"""Exact serial/process equivalence, ordered merges, and resume regressions."""

import io
import importlib.util
import json
import os
import sys
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from functools import partial
from unittest.mock import Mock, patch

from artifact_pipeline.generate_play_table import (
    build_client_table,
    generate_play_table,
    sample_policy_deal,
)
from artifact_pipeline.pegging import (
    PONE,
    ROLES,
    LegacyHeuristicPolicy,
    RolloutContext,
    RunningStatistics,
    _merge_observations,
    _rollout_batch,
    policy_fingerprint,
    train_iterative_best_response,
    train_rollout_best_response,
)
from artifact_pipeline import process_pool
from artifact_pipeline.process_pool import (
    _initialize_worker,
    _peak_rss_bytes,
    _worker_job,
)
from artifact_pipeline.play_lines import build_lines
from artifact_pipeline.test_generate_play_table import all_first_four_policy


def varied_deal(rng):
    deck = [rank for rank in range(13) for _suit in range(4)]
    cards = rng.sample(deck, 8)
    return tuple(cards[:4]), tuple(cards[4:])


def add_task(context, task):
    return context + task


def fail_task(_context, _task):
    raise ValueError("failed worker sample")


class RandomRankPolicy:  # pylint: disable=too-few-public-methods
    def select_rank(self, view, rng):
        return rng.choice(view.legal_ranks)


class TestParallelPlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.discards = all_first_four_policy()
        cls.hands = [(0, 4, 10, 10), (1, 3, 5, 7), (4, 4, 4, 4)]

    def test_training_moments_and_actions_are_exact_across_worker_counts(self):
        policies = {role: RandomRankPolicy() for role in ROLES}
        serial, expected = train_rollout_best_response(
            PONE, policies, varied_deal, 67, 2, 42, workers=1
        )
        # Nontrivial repeats and fractional means exercise online merge order.
        self.assertTrue(
            any(stats.n > 2 for cell in expected.values() for stats in cell.values())
        )
        self.assertTrue(
            any(stats.mean % 1 for cell in expected.values() for stats in cell.values())
        )
        for workers in (2, 3):
            with self.subTest(workers=workers):
                response, moments = train_rollout_best_response(
                    PONE, policies, varied_deal, 67, 2, 42, workers=workers
                )
                self.assertEqual(moments, expected)
                self.assertEqual(response.actions, serial.actions)
                self.assertEqual(
                    policy_fingerprint(response), policy_fingerprint(serial)
                )

    def test_both_averages_training_and_all_artifact_bytes_match(self):
        for averaging in ("geometric", "uniform-hand", "geometric-hand"):
            with self.subTest(averaging=averaging):
                trained = []
                sampler = partial(sample_policy_deal, discard_policy=self.discards)
                for workers in (1, 2, 3):
                    policies, reports = train_iterative_best_response(
                        sampler, 2, 35, 2, 57, averaging=averaging, workers=workers
                    )
                    # Warm passes exercise shared sparse fallback/history graphs.
                    policies, final_reports = train_iterative_best_response(
                        sampler,
                        1,
                        35,
                        2,
                        58,
                        initial_policies=policies,
                        averaging=averaging,
                        workers=workers,
                    )
                    fingerprint = ":".join(
                        policy_fingerprint(policies[role]) for role in ROLES
                    )
                    with patch("sys.stderr", io.StringIO()) as stderr, patch(
                        "artifact_pipeline.generate_play_table.datetime"
                    ) as clock:
                        clock.now.return_value = datetime(
                            2026, 10, 4, tzinfo=timezone.utc
                        )
                        table = generate_play_table(
                            self.discards,
                            policies,
                            37,
                            59,
                            hands=self.hands,
                            play_policy_fingerprint=fingerprint,
                            workers=workers,
                        )
                    self.assertEqual(
                        "[play-workers]" in stderr.getvalue(),
                        workers > 1 and process_pool.resource is not None,
                    )
                    self.assertNotIn(f"pid {os.getpid()}:", stderr.getvalue())
                    table["__metadata__"].update(
                        joint_policy_converged=False,
                        policy_averaging=averaging,
                        reports=[reports, final_reports],
                    )
                    full_bytes = json.dumps(table, sort_keys=True).encode()
                    client_bytes = json.dumps(
                        build_client_table(table), sort_keys=True
                    ).encode()
                    lines_bytes = json.dumps(
                        build_lines(table, client_bytes), sort_keys=True
                    ).encode()
                    trained.append((full_bytes, client_bytes, lines_bytes))
                self.assertEqual(trained[1:], [trained[0], trained[0]])

    def test_resume_raw_moments_exact_after_json_and_worker_count_change(self):
        policies, _ = train_iterative_best_response(
            varied_deal, 1, 17, 2, 29, averaging="uniform-hand"
        )
        first = generate_play_table(
            self.discards, policies, 7, 89, hands=self.hands, workers=2
        )
        saved = json.loads(json.dumps(first))
        untouched = deepcopy(saved)
        for workers in (1, 3):
            resumed = generate_play_table(
                self.discards,
                policies,
                43,
                89,
                hands=self.hands,
                existing_table=saved,
                workers=workers,
            )
            fresh = generate_play_table(
                self.discards, policies, 43, 89, hands=self.hands
            )
            resumed["__metadata__"]["generated_at"] = fresh["__metadata__"][
                "generated_at"
            ]
            self.assertEqual(resumed, fresh)
        self.assertEqual(saved, untouched)

    def test_adaptive_resume_and_checkpoint_prefix_match_serial(self):
        policies = {role: LegacyHeuristicPolicy() for role in ROLES}
        expected = []
        for workers in (1, 2):
            checkpoints = []
            table = generate_play_table(
                self.discards,
                policies,
                3,
                72,
                hands=self.hands,
                target_standard_error=0.01,
                max_samples=11,
                workers=workers,
                checkpoint_frequency=2,
                checkpoint=lambda output, saved=checkpoints: saved.append(
                    deepcopy(output)
                ),
            )
            self.assertEqual(
                list(checkpoints[0]), ["__metadata__", "A_5_J_J", "2_4_6_8"]
            )
            self.assertEqual(checkpoints[-1], table)
            self.assertEqual(len(checkpoints), 2)
            for saved in checkpoints:
                for key, entries in saved.items():
                    if key != "__metadata__":
                        self.assertEqual(set(entries), set(ROLES))
            for saved in checkpoints:
                saved["__metadata__"].pop("generated_at")
            expected.append(checkpoints)
        self.assertEqual(expected[0], expected[1])

    def test_already_satisfied_adaptive_resume_does_not_add_a_sample(self):
        policies = {role: LegacyHeuristicPolicy() for role in ROLES}
        first = generate_play_table(
            self.discards,
            policies,
            3,
            72,
            hands=self.hands,
            target_standard_error=100.0,
            max_samples=11,
        )
        self.assertTrue(all(first["A_5_J_J"][role]["n"] == 3 for role in ROLES))
        for workers in (1, 2):
            resumed = generate_play_table(
                self.discards,
                policies,
                3,
                72,
                hands=self.hands,
                target_standard_error=100.0,
                max_samples=11,
                existing_table=first,
                workers=workers,
            )
            for key, original in first.items():
                if key != "__metadata__":
                    self.assertEqual(resumed[key], original)

    def test_ordered_merge_retains_every_observation_and_existing_moments(self):
        moments = {"same": {2: RunningStatistics(2, 2.0, 2.0)}}
        _merge_observations(
            moments,
            iter(
                [
                    ("same", 2, 7.0),
                    ("other", 0, -3.0),
                    ("same", 2, 1.0),
                    ("same", 3, 2.0),
                    ("other", 0, 1.0),
                ]
            ),
        )
        # The initial observations were 1 and 3: [1, 3, 7, 1] => 3, 24.
        self.assertEqual(moments["same"][2], RunningStatistics(4, 3.0, 24.0))
        self.assertEqual(moments["same"][3], RunningStatistics(1, 2.0, 0.0))
        self.assertEqual(moments["other"][0], RunningStatistics(2, -1.0, 8.0))
        context = RolloutContext(
            PONE, {role: LegacyHeuristicPolicy() for role in ROLES}, 2, 18
        )
        observations = _rollout_batch(context, [(33, (0, 1, 2, 3), (4, 5, 6, 7))])
        self.assertGreater(len(observations), 0)

    def test_workers_one_never_opens_a_pool_and_invalid_counts_fail(self):
        policies = {role: LegacyHeuristicPolicy() for role in ROLES}
        for workers in (0, -1):
            with self.assertRaisesRegex(ValueError, "Workers"):
                generate_play_table(
                    self.discards, policies, 1, 2, hands=[], workers=workers
                )
            with self.assertRaisesRegex(ValueError, "Workers"):
                train_rollout_best_response(
                    PONE, policies, varied_deal, 1, 1, 2, workers=workers
                )
        with patch(
            "artifact_pipeline.process_pool.ProcessPoolExecutor",
            side_effect=AssertionError("serial pool"),
        ):
            train_rollout_best_response(PONE, policies, varied_deal, 1, 1, 2, workers=1)
            generate_play_table(
                self.discards, policies, 1, 2, hands=self.hands, workers=1
            )

    def test_worker_reports_whole_process_peak_memory_and_propagates_failure(self):
        with patch.object(process_pool, "_WORKER_STATE", None):
            with self.assertRaisesRegex(RuntimeError, "no pass snapshot"):
                _worker_job(1)
            _initialize_worker(add_task, 9)
            value, pid, peak = _worker_job(3)
            self.assertEqual(value, 12)
            self.assertEqual(pid, os.getpid())
            self.assertEqual(peak is None, process_pool.resource is None)
            self.assertTrue(peak is None or peak > 0)
        with patch.object(process_pool, "resource", Mock()) as resource:
            resource.getrusage.return_value.ru_maxrss = 123
            for platform, expected in (("darwin", 123), ("linux", 123 * 1024)):
                with patch.object(process_pool.sys, "platform", platform):
                    self.assertEqual(_peak_rss_bytes(), expected)
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            self.assertEqual(
                list(process_pool.ordered_process_map(add_task, 9, [1, 2, 3], 2)),
                [10, 11, 12],
            )
        self.assertEqual(
            "peak RSS" in stderr.getvalue(), process_pool.resource is not None
        )
        self.assertNotIn(f"pid {os.getpid()}:", stderr.getvalue())
        with self.assertRaisesRegex(ValueError, "failed worker sample"):
            list(process_pool.ordered_process_map(fail_task, None, [0], 2))

    def test_pool_bounds_pending_work_freezes_snapshot_and_reports_maximum_rss(self):
        with patch.object(process_pool, "ProcessPoolExecutor") as executor, patch(
            "sys.stderr", io.StringIO()
        ) as stderr:
            pool = executor.return_value.__enter__.return_value
            # Inputs 1..9 exceed the six-slot window. Track live futures rather
            # than relying on the result of an unbounded but equivalent map.
            live = 0
            observed = []

            def submit(function, task):
                nonlocal live
                self.assertIs(function, _worker_job)
                live += 1
                self.assertLessEqual(live, 6)
                observed.append(task)
                future = Mock()

                def result():
                    nonlocal live
                    live -= 1
                    return (
                        task,
                        7 if task < 3 else 8,
                        (2 if task == 1 else 1 if task == 2 else 3) * 1024**2,
                    )

                future.result.side_effect = result
                return future

            pool.submit.side_effect = submit
            self.assertEqual(
                list(process_pool.ordered_process_map(add_task, 9, range(1, 10), 3)),
                list(range(1, 10)),
            )
            self.assertEqual(observed, list(range(1, 10)))
            self.assertEqual(live, 0)
            kwargs = executor.call_args.kwargs
            self.assertEqual(kwargs["max_workers"], 3)
            self.assertEqual(kwargs["mp_context"].get_start_method(), "spawn")
            self.assertEqual(kwargs["initargs"], (add_task, 9))
            self.assertIs(kwargs["initializer"], _initialize_worker)
            self.assertTrue("pid 7: peak RSS 2.0 MiB" in stderr.getvalue())
            self.assertTrue("pid 8: peak RSS 3.0 MiB" in stderr.getvalue())
            self.assertEqual(
                list(process_pool.ordered_process_map(add_task, 9, [], 3)), []
            )

    def test_resource_unavailable_keeps_results_without_rss_reporting(self):
        spec = importlib.util.spec_from_file_location(
            "pool_without_resource", process_pool.__file__
        )
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"resource": None}):
            spec.loader.exec_module(module)
        getattr(module, "_initialize_worker")(add_task, 9)
        self.assertEqual(getattr(module, "_worker_job")(3), (12, os.getpid(), None))
        with patch.object(module, "ProcessPoolExecutor") as executor, patch(
            "sys.stderr", io.StringIO()
        ) as stderr:
            pool = executor.return_value.__enter__.return_value

            def submit(_function, task):
                future = Mock()
                future.result.return_value = (9 + task, 7, None)
                return future

            pool.submit.side_effect = submit
            self.assertEqual(
                list(module.ordered_process_map(add_task, 9, [1, 2, 3], 2)),
                [10, 11, 12],
            )
            self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
