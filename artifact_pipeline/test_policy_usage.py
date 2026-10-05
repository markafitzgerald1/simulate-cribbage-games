"""Worker diagnostics must preserve decisions, random state, and artifact bytes."""

from copy import deepcopy
import random
import unittest

from artifact_pipeline.generate_play_table import (
    generate_play_table,
    build_client_table,
)
from artifact_pipeline.pegging import (
    PONE,
    DEALER,
    LegacyHeuristicPolicy,
    UniformHandPolicy,
    GeometricHandPolicy,
    PolicyMixture,
    TabularPeggingPolicy,
    PolicyView,
    simulate_pegging,
)
from artifact_pipeline.policy_usage import PolicyUsage, ObservedActions
from artifact_pipeline.test_generate_play_table import all_first_four_policy
from artifact_pipeline.test_hand_policy_average import EndPolicy


class LastRankLegacy(LegacyHeuristicPolicy):  # pylint: disable=too-few-public-methods
    def __init__(self):
        self.calls = 0

    def select_rank(self, view, rng):
        del rng
        self.calls += 1
        return view.legal_ranks[-1] if view.legal_ranks else -1


class FirstComponentMixture(PolicyMixture):  # pylint: disable=too-few-public-methods
    def select_rank(self, view, rng):
        return self.policies[0].select_rank(view, rng)


class TestPolicyUsage(unittest.TestCase):
    def test_custom_subclasses_keep_their_own_behavior_when_observed(self):
        legacy = LastRankLegacy()
        for root in (
            legacy,
            FirstComponentMixture((legacy, LegacyHeuristicPolicy()), (0.5, 0.5)),
            TabularPeggingPolicy({}, legacy),
        ):
            policies = {PONE: root, DEALER: LegacyHeuristicPolicy()}
            usage = PolicyUsage(policies)
            for seed in range(10):
                rng, observed_rng = random.Random(seed), random.Random(seed)
                legacy.calls = 0
                plain = simulate_pegging((0, 1, 2, 3), (4, 5, 6, 7), policies, rng)
                direct_calls = legacy.calls
                legacy.calls = 0
                observed = simulate_pegging(
                    (0, 1, 2, 3), (4, 5, 6, 7), usage.policies, observed_rng
                )
                with self.subTest(root=type(root).__name__, seed=seed):
                    self.assertEqual(
                        (plain.players, plain.opening, rng.getstate()),
                        (observed.players, observed.opening, observed_rng.getstate()),
                    )
                    self.assertEqual(legacy.calls, direct_calls)
            self.assertGreater(usage.counts[PONE]["legacy"], 0)

    def test_mapping_delegation_and_unknown_policy(self):
        counts = {"lookups": 0, "hits": 0}
        mapping = ObservedActions({"zero": 0}, counts)
        self.assertEqual(list(mapping), ["zero"])
        self.assertEqual(len(mapping), 1)
        self.assertEqual(mapping["zero"], 0)
        self.assertEqual(mapping.get("zero"), 0)
        self.assertIsNone(mapping.get("absent"))
        self.assertEqual(counts, {"lookups": 2, "hits": 1})
        custom = EndPolicy(False)
        usage = PolicyUsage({PONE: custom, DEALER: custom})
        self.assertIs(usage.policies[PONE], custom)

    def policies(self, mode):
        opening = PolicyView(PONE, (0, 1, 2, 3), 0, (), 4, (), ())
        legacy = LegacyHeuristicPolicy()
        table = TabularPeggingPolicy({opening.key(): 0}, legacy)
        if mode == "uniform-hand":
            root = UniformHandPolicy((legacy, table, table))
        else:
            constructor = (
                GeometricHandPolicy if mode == "geometric-hand" else PolicyMixture
            )
            root = constructor((legacy, table, table), (0.25, 0.25, 0.5))
        return {PONE: root, DEALER: root}, table

    def test_all_modes_preserve_actual_outputs_and_rng_and_original_graph(self):
        for mode in ("geometric", "uniform-hand", "geometric-hand"):
            policies, table = self.policies(mode)
            original = table.actions
            usage = PolicyUsage(policies)
            for seed in range(20):
                rng, observed_rng = random.Random(seed), random.Random(seed)
                result = simulate_pegging((0, 1, 2, 3), (4, 5, 6, 7), policies, rng)
                observed = simulate_pegging(
                    (0, 1, 2, 3), (4, 5, 6, 7), usage.policies, observed_rng
                )
                self.assertEqual(
                    (result.players, result.opening, rng.getstate()),
                    (observed.players, observed.opening, observed_rng.getstate()),
                )
            self.assertIs(table.actions, original)
            for role in (PONE, DEALER):
                counts = usage.counts[role]
                self.assertEqual(counts["hits"] + counts["legacy"], 80)
                self.assertGreater(counts["legacy"], 0)
                self.assertEqual(
                    usage.coverage[role],
                    {"tables": 1, "entries": 1, "distinct_stored_states": 1},
                )
            self.assertGreater(usage.counts[PONE]["hits"], 0)

    def test_parallel_counters_are_returned_and_do_not_enter_client_or_resume_samples(
        self,
    ):
        policies, _table = self.policies("geometric-hand")
        discards = all_first_four_policy()
        kwargs = {
            "samples": 5,
            "seed": 42,
            "hands": [(0, 1, 2, 3), (4, 5, 6, 7)],
            "play_policy_fingerprint": "test",
        }
        plain = generate_play_table(discards, policies, **kwargs)
        results = []
        for workers in (1, 2):
            result = generate_play_table(
                discards, policies, workers=workers, observe_policy_usage=True, **kwargs
            )
            self.assertEqual(build_client_table(plain), build_client_table(result))
            expected = deepcopy(plain)
            expected.pop("__metadata__")
            entries = deepcopy(result)
            metadata = entries.pop("__metadata__")
            self.assertEqual(entries, expected)
            results.append(metadata["policy_usage"])
            for role in (PONE, DEALER):
                counts = metadata["policy_usage"][role]
                self.assertEqual(counts["hits"] + counts["legacy"], 80)
            resumed = generate_play_table(
                discards,
                policies,
                existing_table=result,
                workers=workers,
                observe_policy_usage=True,
                **kwargs
            )
            for role in (PONE, DEALER):
                self.assertEqual(
                    resumed["__metadata__"]["policy_usage"][role]["legacy"], 0
                )
        self.assertEqual(results[0], results[1])
