"""Digest-bound, read-only six-layer rank pegging policy inputs."""

from __future__ import annotations

from collections import Counter, OrderedDict
from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
import json
import mmap
from pathlib import Path
import random
import struct
from typing import Any, Mapping, TypeGuard, cast

from artifact_pipeline.pegging import (
    DEALER,
    ROLES,
    GO_ACTION,
    SEQUENCE_RESET,
    LegacyHeuristicPolicy,
    PolicyView,
    get_canonical_hands,
    policy_fingerprint,
    rank_count,
)

SCHEMA = "six-layer-pegging-policy.v1"
DENOMINATOR = 1000
MENU = struct.Struct("<QII4B4B")
PUBLIC_ACTIONS = frozenset(range(-2, 13))
CATEGORIES = (
    "trained",
    "heuristic_equivalent",
    "off_support",
    "forced",
    "missing_menu_fallback",
)
HANDS = get_canonical_hands()
HAND_INDICES = {hand: index for index, hand in enumerate(HANDS)}
Buffer = bytes | mmap.mmap


def _integer(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def close_component(data: Buffer) -> None:
    if isinstance(data, mmap.mmap):
        data.close()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate policy field: {key}")
        result[key] = value
    return result


def read_manifest(path: Path) -> dict[str, Any]:
    """Read an unambiguous JSON input manifest, never measured statistics."""
    document = json.loads(path.read_bytes(), object_pairs_hook=_unique_object)
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise ValueError("Unsupported six-layer policy schema")
    for name in (
        "probabilities",
        "offsets",
        "support",
        "prior",
        "fallback",
        "discard_population",
    ):
        if not isinstance(document.get(name), dict):
            raise ValueError(f"Missing policy component: {name}")
    if not isinstance(document.get("menus"), list) or any(
        not isinstance(spec, dict) for spec in document["menus"]
    ):
        raise ValueError("Menus must be an array of component descriptors")
    return document


def verified_component(root: Path, spec: Mapping[str, Any]) -> Buffer:
    """Map and hash the same open file; callers own the returned mapping."""
    name, size, digest = spec.get("file"), spec.get("bytes"), spec.get("sha256")
    if (
        not isinstance(name, str)
        or not name
        or Path(name).is_absolute()
        or ".." in Path(name).parts
    ):
        raise ValueError("Component file must be relative to its manifest")
    if (
        not _integer(size)
        or size < 0
        or not isinstance(digest, str)
        or len(digest) != 64
    ):
        raise ValueError("Invalid component size/digest")
    with (root / name).open("rb") as source:
        data: Buffer = (
            mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ)
            if source.seek(0, 2)
            else b""
        )
    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        close_component(data)
        raise ValueError(f"Component size/digest mismatch: {name}")
    return data


def _address(view: PolicyView) -> tuple[int, int]:
    """Reconstruct the original own keep and validate the entire public view."""
    if view.role not in ROLES or len(view.public_history) > 16:
        raise ValueError("Invalid role/history length")
    role = int(view.role == DEALER)
    actor, last, count, code = 0, -1, 0, 0
    played: list[list[int]] = [[], []]
    sequence: list[int] = []
    passed: set[int] = set()
    pending_reset = False
    for index, action in enumerate(view.public_history):
        if not _integer(action) or action not in PUBLIC_ACTIONS:
            raise ValueError("Invalid public action")
        code |= (action + 1 if action >= 0 else 14 if action == GO_ACTION else 15) << (
            4 * index
        )
        if action == SEQUENCE_RESET:
            if not pending_reset:
                raise ValueError("Unexpected sequence reset")
            count, last, pending_reset = 0, -1, False
            sequence.clear()
            passed.clear()
        elif pending_reset:
            raise ValueError("Missing sequence reset")
        elif action >= 0:
            count += rank_count(action)
            if count > 31 or actor in passed:
                raise ValueError("Invalid public card/count")
            sequence.append(action)
            played[actor].append(action)
            last, actor = actor, 1 - actor
            pending_reset = count == 31
        else:
            actor, pending_reset = _go_actor(actor, last, passed)
    own = tuple(sorted((*view.own_remaining, *played[role])))
    if (
        pending_reset
        or actor != role
        or own not in HAND_INDICES
        or any(not _integer(rank) for rank in own)
    ):
        raise ValueError("Invalid acting player/original own keep")
    expected = (
        count,
        tuple(sequence),
        4 - len(played[1 - role]),
        tuple(sorted(ROLES[seat] for seat in passed)),
    )
    actual = (
        view.count,
        view.sequence,
        view.opponent_remaining_count,
        view.passed_roles,
    )
    if len(played[1 - role]) > 4 or actual != expected:
        raise ValueError("Public view disagrees with its history")
    # Membership in HAND_INDICES above already proves a four-rank tuple.
    index = HAND_INDICES[cast(tuple[int, int, int, int], own)]
    return role * len(HANDS) + index, code


def _go_actor(actor: int, last: int, passed: set[int]) -> tuple[int, bool]:
    if 1 - actor in passed:
        if last < 0:
            raise ValueError("Go without a previous card")
        return 1 - last, True
    passed.add(actor)
    return 1 - actor, False


def _validate_fallback(fallback: Mapping[str, Any]) -> None:
    legacy = Path(__file__).resolve().parent.parent / "simulate_cribbage_games.py"
    expected = (
        "legacy-heuristic-v1",
        policy_fingerprint(LegacyHeuristicPolicy()),
        hashlib.sha256(legacy.read_bytes()).hexdigest(),
    )
    actual = (
        fallback.get("identity"),
        fallback.get("fingerprint"),
        fallback.get("source_sha256"),
    )
    if actual != expected:
        raise ValueError("Fallback identity differs from the current legacy engine")


def _validate_shapes(
    buffers: Mapping[str, Buffer], manifest: Mapping[str, Any], rows: int, actions: int
) -> None:
    expected = {
        "probabilities": actions * 2,
        "offsets": rows * 4,
        "support": rows,
        "prior": len(HANDS) ** 2 * 8,
    }
    if any(len(buffers[name]) != size for name, size in expected.items()):
        raise ValueError("Global policy component shapes disagree")
    mask = manifest["support"].get("mask")
    if not _integer(mask) or mask not in (1, 2):
        raise ValueError("Unsupported counterfactual support mask")
    with memoryview(buffers["support"]) as support:
        if any(value > 3 for value in support):
            raise ValueError("Invalid counterfactual support byte")


def _binding_fingerprint(
    manifest: Mapping[str, Any], menus: Mapping[int, Mapping[str, Any]]
) -> str:
    binding = {
        "schema": SCHEMA,
        "probability_denominator": DENOMINATOR,
        "fallback": manifest["fallback"],
        "components": {
            name: manifest[name]["sha256"]
            for name in ("probabilities", "offsets", "support", "prior")
        },
        "support_mask": manifest["support"]["mask"],
        "menus": [(key, spec["sha256"]) for key, spec in sorted(menus.items())],
    }
    return hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def _validate_record(
    record: tuple[int, ...], key: int, previous: int
) -> tuple[int, int]:
    history, stage, width, heuristic = record[0], record[7], record[8], record[9]
    if history <= previous or width not in (2, 3, 4):
        raise ValueError("Invalid menu ordering/width")
    legal = record[3 : 3 + width]
    if stage not in range(6) or stage % 2 != key // len(HANDS) or heuristic >= width:
        raise ValueError("Invalid menu stage/heuristic index")
    if legal != tuple(sorted(set(legal))) or max(legal) >= 13:
        raise ValueError("Invalid menu actions")
    return history, width


@dataclass(frozen=True)
class PolicyIndex:
    """Validated input identity and canonical variable-width row indexing."""

    root: Path
    manifest: Mapping[str, Any]
    menus: Mapping[int, Mapping[str, Any]]
    starts: tuple[int, ...]
    fingerprint: str
    cache_limit: int


class SixLayerPolicy:
    """Sample saved integer CDFs; decisions without stored rows use the heuristic."""

    def __init__(self, manifest_path: str | Path, cache_limit: int = 64):
        if not _integer(cache_limit) or cache_limit < 1:
            raise ValueError("Menu cache limit must be a positive integer")
        path = Path(manifest_path)
        manifest = read_manifest(path)
        if (
            not _integer(manifest.get("probability_denominator"))
            or manifest.get("probability_denominator") != DENOMINATOR
        ):
            raise ValueError("Unsupported probability denominator")
        _validate_fallback(manifest["fallback"])
        self._counts: Counter[tuple[str, str]] = Counter()
        self._cache: OrderedDict[int, Buffer] = OrderedDict()
        self._resources: ExitStack | None = None
        with ExitStack() as resources:
            self._buffers = {}
            for name in ("probabilities", "offsets", "support", "prior"):
                data = verified_component(path.parent, manifest[name])
                resources.callback(close_component, data)
                self._buffers[name] = data
            menus, starts, actions = self._validate_menus(path.parent, manifest)
            _validate_shapes(self._buffers, manifest, starts[-1], actions)
            self._index = PolicyIndex(
                path.parent,
                manifest,
                menus,
                starts,
                _binding_fingerprint(manifest, menus),
                cache_limit,
            )
            self._resources = resources.pop_all()

    def _validate_menus(
        self, root: Path, manifest: Mapping[str, Any]
    ) -> tuple[dict[int, Mapping[str, Any]], tuple[int, ...], int]:
        menus = {}
        for spec in manifest["menus"]:
            if (
                not isinstance(spec.get("own_hand"), list)
                or spec.get("role") not in ROLES
            ):
                raise ValueError("Missing menu own hand/role")
            hand = tuple(spec["own_hand"])
            if (
                any(not _integer(rank) for rank in hand)
                or hand not in HAND_INDICES
                or spec["role"] not in ROLES
            ):
                raise ValueError("Invalid canonical own hand/role")
            key = int(spec["role"] == DEALER) * len(HANDS) + HAND_INDICES[hand]
            if key in menus:
                raise ValueError("Duplicate own-hand menu")
            menus[key] = spec
        starts, rows, actions = [], 0, 0
        for key in range(2 * len(HANDS)):
            starts.append(rows)
            if key not in menus:
                continue
            data = verified_component(root, menus[key])
            try:
                if len(data) % MENU.size:
                    raise ValueError("Truncated menu record")
                previous = -1
                for record in MENU.iter_unpack(data):
                    history, width = _validate_record(record, key, previous)
                    if (
                        rows * 4 >= len(self._buffers["offsets"])
                        or struct.unpack_from("<I", self._buffers["offsets"], rows * 4)[
                            0
                        ]
                        != actions
                    ):
                        raise ValueError("Invalid action offset")
                    if (actions + width) * 2 > len(self._buffers["probabilities"]):
                        raise ValueError("Truncated probability array")
                    if (
                        sum(
                            struct.unpack_from(
                                f"<{width}H",
                                self._buffers["probabilities"],
                                actions * 2,
                            )
                        )
                        != DENOMINATOR
                    ):
                        raise ValueError("Probability counts must sum to 1000")
                    rows += 1
                    actions += width
                    previous = history
            finally:
                close_component(data)
        return menus, tuple((*starts, rows)), actions

    @property
    def behavioral_fingerprint(self) -> str:
        """Identify bytes and semantics, independently of paths or counters."""
        return self._index.fingerprint

    @property
    def manifest(self) -> Mapping[str, Any]:
        """Return the input manifest used to bind measurement provenance."""
        return json.loads(json.dumps(self._index.manifest))

    def reset_counts(self) -> None:
        """Exclude any preceding safety gate from measurement diagnostics."""
        self._counts.clear()

    def decision_counts(self) -> dict[str, int]:
        """Count actual select_rank calls; automatic goes are not observed."""
        return {
            category: sum(self._counts[(role, category)] for role in ROLES)
            for category in CATEGORIES
        }

    def _menu(self, key: int) -> Buffer:
        if key not in self._cache:
            data = verified_component(self._index.root, self._index.menus[key])
            if len(self._cache) == self._index.cache_limit:
                close_component(self._cache.popitem(last=False)[1])
            self._cache[key] = data
        self._cache.move_to_end(key)
        return self._cache[key]

    def select_rank(self, view: PolicyView, rng: random.Random) -> int:
        """Choose exactly one legal action without observing hidden cards."""
        if self._resources is None:
            raise RuntimeError("Six-layer policy is closed")
        heuristic = LegacyHeuristicPolicy().select_rank(view, rng)
        legal = view.legal_ranks
        if len(legal) < 2:
            self._counts[(view.role, "forced")] += 1
            return heuristic
        row = self._lookup(view)
        if row is None:
            self._counts[(view.role, "missing_menu_fallback")] += 1
            return heuristic
        ranks, weights, supported = row
        category = (
            "off_support"
            if not supported
            else (
                "heuristic_equivalent"
                if weights[ranks.index(heuristic)] == DENOMINATOR
                else "trained"
            )
        )
        self._counts[(view.role, category)] += 1
        draw = (
            rng.randrange(DENOMINATOR)
            if sum(weight > 0 for weight in weights) > 1
            else 0
        )
        for rank, weight in zip(ranks, weights):
            if draw < weight:
                return rank
            draw -= weight
        raise ValueError("CDF draw outside its declared range")

    def _lookup(
        self, view: PolicyView
    ) -> tuple[tuple[int, ...], tuple[int, ...], bool] | None:
        key, history = _address(view)
        if key not in self._index.menus:
            return None
        data = self._menu(key)
        low, high = 0, len(data) // MENU.size
        while low < high:
            middle = (low + high) // 2
            if struct.unpack_from("<Q", data, MENU.size * middle)[0] < history:
                low = middle + 1
            else:
                high = middle
        if (
            low == len(data) // MENU.size
            or struct.unpack_from("<Q", data, MENU.size * low)[0] != history
        ):
            return None
        record = MENU.unpack_from(data, MENU.size * low)
        ranks = record[3 : 3 + record[8]]
        if ranks != view.legal_ranks:
            raise ValueError("Stored menu differs from the real legal ranks")
        row = self._index.starts[key] + low
        offset = struct.unpack_from("<I", self._buffers["offsets"], row * 4)[0]
        weights = struct.unpack_from(
            f"<{record[8]}H", self._buffers["probabilities"], offset * 2
        )
        supported = (
            self._buffers["support"][row] & self._index.manifest["support"]["mask"]
        )
        return ranks, weights, bool(supported)

    def close(self) -> None:
        """Release all mappings, including the bounded own-hand menu cache."""
        for data in self._cache.values():
            close_component(data)
        self._cache.clear()
        if self._resources is not None:
            self._resources.close()
            self._resources = None

    def __enter__(self) -> SixLayerPolicy:
        return self

    def __exit__(self, *_exception: object) -> None:
        self.close()
