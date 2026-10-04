"""RNG-neutral policy observations carried back from measurement workers."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
import random
from typing import Any

from artifact_pipeline.pegging import (
    GeometricHandPolicy,
    LegacyHeuristicPolicy,
    PeggingPolicy,
    PolicyMixture,
    PolicyView,
    ROLES,
    TabularPeggingPolicy,
    UniformHandPolicy,
)


class ObservedActions(Mapping[str, int]):
    """Delegate action reads without copying the table or drawing randomness."""

    def __init__(self, actions: Mapping[str, int], counts: dict[str, int]):
        self.actions = actions
        self.counts = counts

    def __iter__(self) -> Iterator[str]:
        return iter(self.actions)

    def __len__(self) -> int:
        return len(self.actions)

    def __getitem__(self, key: str) -> int:
        return self.actions[key]

    def get(self, key: str, default: Any = None) -> Any:
        self.counts["lookups"] += 1
        value = self.actions.get(key, default)
        self.counts["hits"] += int(value is not None)
        return value


@dataclass
class ObservedLegacyPolicy(LegacyHeuristicPolicy):
    """Observe the terminal fallback while executing the exact legacy adapter."""

    counts: dict[str, int]

    def select_rank(self, view: PolicyView, rng: random.Random) -> int:
        self.counts["legacy"] += 1
        return super().select_rank(view, rng)


class PolicyUsage:  # pylint: disable=too-few-public-methods
    """One shared read-only graph per pass, copied once into each worker."""

    def __init__(self, policies: Mapping[str, PeggingPolicy]):
        self.counts = {role: {"lookups": 0, "hits": 0, "legacy": 0} for role in ROLES}
        self.coverage = {}
        self.policies = {}
        for role in ROLES:
            self.policies[role], self.coverage[role] = self._observe_role(
                policies[role], self.counts[role]
            )

    @staticmethod
    def _observe_role(
        root: PeggingPolicy, counts: dict[str, int]
    ) -> tuple[PeggingPolicy, dict[str, int]]:
        memo: dict[int, PeggingPolicy] = {}
        states: set[str] = set()
        coverage = {"tables": 0, "entries": 0}

        def visit(policy: PeggingPolicy) -> PeggingPolicy:
            if id(policy) in memo:
                return memo[id(policy)]
            if isinstance(policy, TabularPeggingPolicy):
                states.update(policy.actions)
                coverage["tables"] += 1
                coverage["entries"] += len(policy.actions)
                observed: PeggingPolicy = TabularPeggingPolicy(
                    ObservedActions(policy.actions, counts), visit(policy.fallback)
                )
            elif isinstance(policy, LegacyHeuristicPolicy):
                observed = ObservedLegacyPolicy(counts)
            elif isinstance(policy, (PolicyMixture, GeometricHandPolicy)):
                observed = type(policy)(
                    tuple(visit(p) for p in policy.policies), policy.weights
                )
            elif isinstance(policy, UniformHandPolicy):
                observed = UniformHandPolicy(tuple(visit(p) for p in policy.policies))
            else:
                observed = policy
            memo[id(policy)] = observed
            return observed

        observed_root = visit(root)
        return observed_root, {**coverage, "distinct_stored_states": len(states)}
