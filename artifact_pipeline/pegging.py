"""Rank-only two-player pegging simulation and rollout policy improvement."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
import random
from typing import Callable, Mapping, Protocol, Sequence

from artifact_pipeline.adapter import legacy_select_play_rank

PONE = "Pone"
DEALER = "Dealer"
ROLES = (PONE, DEALER)
POINT_TYPES = ("fifteen", "thirty_one", "pair", "run", "go", "last_card")
GO_ACTION = -1
# Marks a sequence reset (after 31 or a go) in public_history. It stays part of
# the policy key and cannot collide with ranks (0-12) or GO_ACTION (-1).
SEQUENCE_RESET = -2


def other_role(role: str) -> str:
    """Return the opposing role."""
    if role == PONE:
        return DEALER
    if role == DEALER:
        return PONE
    raise ValueError(f"Invalid role: {role}")


def rank_count(rank: int) -> int:
    """Return the pegging count value for a zero-based rank."""
    if not 0 <= rank < 13:
        raise ValueError(f"Invalid rank: {rank}")
    return min(rank + 1, 10)


def canonical_hand_key(ranks: Sequence[int]) -> str:
    """Return the stable artifact key for a four-rank multiset."""
    if len(ranks) != 4:
        raise ValueError("A pegging hand must contain exactly four ranks")
    if any(not 0 <= rank < 13 for rank in ranks):
        raise ValueError(f"Invalid hand ranks: {ranks}")
    labels = "A23456789TJQK"
    return "_".join(labels[rank] for rank in sorted(ranks))


def get_canonical_hands() -> list[tuple[int, int, int, int]]:
    """Return all 1,820 physically possible four-rank multisets."""
    hands = []
    for first in range(13):
        for second in range(first, 13):
            for third in range(second, 13):
                for fourth in range(third, 13):
                    hands.append((first, second, third, fourth))
    return hands


def _empty_points() -> dict[str, float]:
    return {point_type: 0.0 for point_type in POINT_TYPES}


@dataclass
class RunningStatistics:
    """Online sample moments for one scalar estimate."""

    n: int = 0
    mean: float = 0.0
    moment_2: float = 0.0

    def add(self, value: float) -> None:
        """Add one observation."""
        self.n += 1
        delta = value - self.mean
        self.mean += delta / self.n
        self.moment_2 += delta * (value - self.mean)

    @property
    def standard_error(self) -> float:
        """Return the sample standard error."""
        if self.n < 2:
            return 0.0
        variance = self.moment_2 / (self.n - 1)
        return math.sqrt(variance / self.n)

    def to_dict(self) -> dict[str, float | int]:
        """Return the public artifact statistics shape."""
        return {"n": self.n, "mu": self.mean, "se": self.standard_error}

    @classmethod
    def from_dict(cls, statistics: Mapping[str, float | int]) -> "RunningStatistics":
        """Reconstruct resumable moments from n, mean, and standard error."""
        sample_count = int(statistics["n"])
        standard_error = float(statistics["se"])
        moment_2 = (
            standard_error * standard_error * sample_count * max(0, sample_count - 1)
        )
        return cls(
            n=sample_count,
            mean=float(statistics["mu"]),
            moment_2=moment_2,
        )


@dataclass(frozen=True)
class PolicyView:
    """The acting player's legitimate pegging information set."""

    role: str
    own_remaining: tuple[int, ...]
    count: int
    sequence: tuple[int, ...]
    opponent_remaining_count: int
    passed_roles: tuple[str, ...]
    public_history: tuple[int, ...]

    @property
    def legal_ranks(self) -> tuple[int, ...]:
        """Return distinct legal ranks in stable order."""
        return tuple(
            sorted(
                {
                    rank
                    for rank in self.own_remaining
                    if self.count + rank_count(rank) <= 31
                }
            )
        )

    def key(self) -> str:
        """Return a compact stable key suitable for policy serialization."""
        payload = (
            self.role,
            self.own_remaining,
            self.count,
            self.sequence,
            self.opponent_remaining_count,
            self.passed_roles,
            self.public_history,
        )
        return repr(payload)


class PeggingPolicy(Protocol):  # pylint: disable=too-few-public-methods
    """Select one legal rank from a public information state."""

    def select_rank(self, view: PolicyView, rng: random.Random) -> int:
        """Return a legal rank."""


@dataclass
class LegacyHeuristicPolicy:
    """Iteration-zero adapter around the legacy simulator's best heuristic."""

    def select_rank(self, view: PolicyView, rng: random.Random) -> int:
        del rng
        legal_ranks = view.legal_ranks
        if not legal_ranks:
            return GO_ACTION
        return legacy_select_play_rank(legal_ranks, view.count, view.sequence)


@dataclass
class TabularPeggingPolicy:
    """Information-state action table with a deterministic fallback."""

    actions: Mapping[str, int]
    fallback: PeggingPolicy = field(default_factory=LegacyHeuristicPolicy)

    def select_rank(self, view: PolicyView, rng: random.Random) -> int:
        legal_ranks = view.legal_ranks
        if not legal_ranks:
            return GO_ACTION
        selected = self.actions.get(view.key())
        if selected in legal_ranks:
            return selected
        return self.fallback.select_rank(view, rng)


@dataclass
class PolicyMixture:
    """A reproducible mixture used to damp alternating best responses."""

    policies: Sequence[PeggingPolicy]
    weights: Sequence[float]

    def __post_init__(self) -> None:
        if not self.policies or len(self.policies) != len(self.weights):
            raise ValueError("Policy mixtures require matching policies and weights")
        if any(weight < 0.0 for weight in self.weights) or sum(self.weights) <= 0.0:
            raise ValueError("Policy mixture weights must be non-negative")

    def select_rank(self, view: PolicyView, rng: random.Random) -> int:
        chosen = rng.random() * sum(self.weights)
        cumulative = 0.0
        for policy, weight in zip(self.policies[:-1], self.weights[:-1]):
            cumulative += weight
            if chosen <= cumulative:
                return policy.select_rank(view, rng)
        return self.policies[-1].select_rank(view, rng)


@dataclass
class PeggingState:
    """Complete simulation state; hidden hands are never included in PolicyView."""

    hands: dict[str, list[int]]
    next_role: str = PONE
    count: int = 0
    sequence: list[int] = field(default_factory=list)
    passed_roles: set[str] = field(default_factory=set)
    public_history: list[int] = field(default_factory=list)
    last_player: str | None = None

    def copy(self) -> "PeggingState":
        """Return an independent state for rollout branches."""
        return PeggingState(
            hands={role: list(hand) for role, hand in self.hands.items()},
            next_role=self.next_role,
            count=self.count,
            sequence=list(self.sequence),
            passed_roles=set(self.passed_roles),
            public_history=list(self.public_history),
            last_player=self.last_player,
        )

    def view(self) -> PolicyView:
        """Project the complete state to the current player's information set."""
        role = self.next_role
        return PolicyView(
            role=role,
            own_remaining=tuple(sorted(self.hands[role])),
            count=self.count,
            sequence=tuple(self.sequence),
            opponent_remaining_count=len(self.hands[other_role(role)]),
            passed_roles=tuple(sorted(self.passed_roles)),
            public_history=tuple(self.public_history),
        )


@dataclass(frozen=True)
class DecisionTrace:
    """One decision state plus its full hidden simulation state for training."""

    view: PolicyView
    state: PeggingState


@dataclass
class PeggingResult:
    """Seat and point-type totals from one deal."""

    players: dict[str, dict[str, float]]
    decisions: list[DecisionTrace] = field(default_factory=list)

    def total(self, role: str) -> float:
        """Return one player's total pegging points."""
        return sum(self.players[role].values())

    def delta(self, role: str) -> float:
        """Return the requested player's points minus the opponent's."""
        return self.total(role) - self.total(other_role(role))


def _pair_points(sequence: Sequence[int]) -> int:
    rank = sequence[-1]
    matching = 1
    for prior in reversed(sequence[:-1]):
        if prior != rank:
            break
        matching += 1
    return {2: 2, 3: 6, 4: 12}.get(matching, 0)


def _run_points(sequence: Sequence[int]) -> int:
    for length in range(len(sequence), 2, -1):
        suffix = sequence[-length:]
        ranks = set(suffix)
        if len(ranks) == length and max(ranks) - min(ranks) == length - 1:
            return length
    return 0


def score_play(sequence: Sequence[int], count: int) -> dict[str, float]:
    """Score one just-played card; a single play can earn several categories."""
    if not sequence:
        raise ValueError("Cannot score an empty sequence")
    points = _empty_points()
    points["pair"] = float(_pair_points(sequence))
    points["run"] = float(_run_points(sequence))
    if count == 15:
        points["fifteen"] = 2.0
    if count == 31:
        points["thirty_one"] = 2.0
    return points


def _add_points(
    scores: dict[str, dict[str, float]],
    role: str,
    points: Mapping[str, float],
) -> None:
    for point_type, value in points.items():
        scores[role][point_type] += value


def _reset_sequence(state: PeggingState, next_role: str) -> None:
    state.count = 0
    state.sequence.clear()
    state.passed_roles.clear()
    state.public_history.append(SEQUENCE_RESET)
    state.next_role = next_role
    state.last_player = None


def _play_rank(
    state: PeggingState,
    rank: int,
    scores: dict[str, dict[str, float]],
) -> bool:
    role = state.next_role
    legal_ranks = state.view().legal_ranks
    if rank not in legal_ranks:
        raise ValueError(f"Illegal rank {rank} for {state.view()}")
    state.hands[role].remove(rank)
    state.count += rank_count(rank)
    state.sequence.append(rank)
    state.public_history.append(rank)
    state.last_player = role
    _add_points(scores, role, score_play(state.sequence, state.count))
    if not state.hands[PONE] and not state.hands[DEALER]:
        if state.count != 31:
            scores[role]["last_card"] += 1.0
        return True
    if state.count == 31:
        _reset_sequence(state, other_role(role))
    else:
        state.next_role = other_role(role)
    return False


def _say_go(
    state: PeggingState,
    scores: dict[str, dict[str, float]],
) -> None:
    role = state.next_role
    state.public_history.append(GO_ACTION)
    if other_role(role) in state.passed_roles:
        if state.last_player is None:
            raise ValueError("A closed sequence must have a last player")
        scores[state.last_player]["go"] += 1.0
        _reset_sequence(state, other_role(state.last_player))
        return
    state.passed_roles.add(role)
    state.next_role = other_role(role)


def simulate_from_state(
    initial_state: PeggingState,
    policies: Mapping[str, PeggingPolicy],
    rng: random.Random,
    forced_rank: int | None = None,
    collect_decisions: bool = False,
) -> PeggingResult:
    """Play from an arbitrary state and return only points scored afterward."""
    state = initial_state.copy()
    scores = {role: _empty_points() for role in ROLES}
    decisions = []
    first_action = True
    while state.hands[PONE] or state.hands[DEALER]:
        view = state.view()
        legal_ranks = view.legal_ranks
        if not legal_ranks:
            _say_go(state, scores)
            first_action = False
            continue
        if collect_decisions and len(legal_ranks) > 1:
            decisions.append(DecisionTrace(view=view, state=state.copy()))
        if first_action and forced_rank is not None:
            selected = forced_rank
        else:
            selected = policies[view.role].select_rank(view, rng)
        first_action = False
        if _play_rank(state, selected, scores):
            break
    return PeggingResult(players=scores, decisions=decisions)


def simulate_pegging(
    pone_hand: Sequence[int],
    dealer_hand: Sequence[int],
    policies: Mapping[str, PeggingPolicy],
    rng: random.Random,
    collect_decisions: bool = False,
) -> PeggingResult:
    """Play one complete rank-only pegging deal."""
    if len(pone_hand) != 4 or len(dealer_hand) != 4:
        raise ValueError("Both players must keep exactly four cards")
    state = PeggingState(
        hands={PONE: list(sorted(pone_hand)), DEALER: list(sorted(dealer_hand))}
    )
    return simulate_from_state(
        state, policies, rng, collect_decisions=collect_decisions
    )


DealSampler = Callable[[random.Random], tuple[Sequence[int], Sequence[int]]]


def _stable_seed(*parts: object) -> int:
    digest = hashlib.sha256(repr(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def policy_fingerprint(policy: PeggingPolicy) -> str:
    """Return a stable digest for resume-compatibility checks."""
    if isinstance(policy, LegacyHeuristicPolicy):
        payload: object = ("legacy-heuristic-v1",)
    elif isinstance(policy, TabularPeggingPolicy):
        payload = (
            "tabular-v1",
            tuple(sorted(policy.actions.items())),
            policy_fingerprint(policy.fallback),
        )
    elif isinstance(policy, PolicyMixture):
        payload = (
            "mixture-v1",
            tuple(policy.weights),
            tuple(policy_fingerprint(item) for item in policy.policies),
        )
    else:
        payload = (type(policy).__module__, type(policy).__qualname__)
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


def train_rollout_best_response(
    target_role: str,
    policies: Mapping[str, PeggingPolicy],
    deal_sampler: DealSampler,
    samples: int,
    rollouts_per_action: int,
    seed: int,
) -> tuple[TabularPeggingPolicy, dict[str, dict[int, RunningStatistics]]]:
    """Fit one information-state rollout response against frozen policies."""
    # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    if target_role not in ROLES:
        raise ValueError(f"Invalid target role: {target_role}")
    if samples <= 0 or rollouts_per_action <= 0:
        raise ValueError("Training sample and rollout counts must be positive")
    rng = random.Random(seed)
    action_values: dict[str, dict[int, RunningStatistics]] = {}
    for sample_index in range(samples):
        pone_hand, dealer_hand = deal_sampler(rng)
        result = simulate_pegging(
            pone_hand,
            dealer_hand,
            policies,
            random.Random(_stable_seed(seed, "trace", sample_index)),
            collect_decisions=True,
        )
        for decision_index, decision in enumerate(result.decisions):
            if decision.view.role != target_role:
                continue
            state_values = action_values.setdefault(decision.view.key(), {})
            for rank in decision.view.legal_ranks:
                rank_values = state_values.setdefault(rank, RunningStatistics())
                for rollout_index in range(rollouts_per_action):
                    rollout = simulate_from_state(
                        decision.state,
                        policies,
                        random.Random(
                            _stable_seed(
                                seed,
                                sample_index,
                                decision_index,
                                rollout_index,
                            )
                        ),
                        forced_rank=rank,
                    )
                    rank_values.add(rollout.delta(target_role))
    actions = {
        state_key: max(values.items(), key=lambda item: (item[1].mean, -item[0]))[0]
        for state_key, values in action_values.items()
    }
    return (
        TabularPeggingPolicy(actions=actions, fallback=policies[target_role]),
        action_values,
    )


def train_iterative_best_response(
    deal_sampler: DealSampler,
    iterations: int,
    samples_per_role: int,
    rollouts_per_action: int,
    seed: int,
    mixture_weight: float = 0.5,
    initial_policies: Mapping[str, PeggingPolicy] | None = None,
) -> tuple[dict[str, PeggingPolicy], list[dict[str, object]]]:
    """Alternate rollout best responses for Pone and Dealer."""
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    if iterations <= 0:
        raise ValueError("IBR iterations must be positive")
    if not 0.0 < mixture_weight <= 1.0:
        raise ValueError("Mixture weight must be in (0, 1]")
    policies: dict[str, PeggingPolicy] = dict(
        initial_policies
        if initial_policies is not None
        else {
            PONE: LegacyHeuristicPolicy(),
            DEALER: LegacyHeuristicPolicy(),
        }
    )
    reports = []
    for iteration in range(iterations):
        for role_index, role in enumerate(ROLES):
            response, action_values = train_rollout_best_response(
                role,
                policies,
                deal_sampler,
                samples_per_role,
                rollouts_per_action,
                _stable_seed(seed, iteration, role_index),
            )
            prior = policies[role]
            policies[role] = PolicyMixture(
                policies=(prior, response),
                weights=(1.0 - mixture_weight, mixture_weight),
            )
            reports.append(
                {
                    "iteration": iteration + 1,
                    "role": role,
                    "states": len(action_values),
                    "actions": sum(len(values) for values in action_values.values()),
                }
            )
    return policies, reports
