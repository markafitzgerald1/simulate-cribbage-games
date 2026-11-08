"""Portable synthetic input bundles for fixed-policy tests."""

from collections import defaultdict
from functools import cache
import hashlib
import itertools
import json
from pathlib import Path
import struct
from typing import Any

from artifact_pipeline.generate_play_table import (
    DiscardPolicy,
    discard_keeps_fingerprint,
)
from artifact_pipeline.pegging import (
    LegacyHeuristicPolicy,
    ROLES,
    get_canonical_hands,
    policy_fingerprint,
)

FIXTURE = Path(__file__).parent / "fixtures" / "six_layer_policy.json"


@cache
def discard_bytes() -> tuple[bytes, str]:
    """Build every physically possible six-card multiset without research data."""
    hands = [
        h
        for h in itertools.combinations_with_replacement(range(13), 6)
        if max(h.count(r) for r in set(h)) <= 4
    ]
    keeps = {(role, h): h[:4] for role in ROLES for h in hands}
    fingerprint = discard_keeps_fingerprint(DiscardPolicy(keeps))
    data = json.dumps(
        {
            "discard_policy_fingerprint": fingerprint,
            "keeps": [[role, list(h), list(keep)] for (role, h), keep in keeps.items()],
        }
    ).encode()
    return data, fingerprint


def bind(root: Path, name: str) -> dict[str, Any]:
    """Hash actual fixture bytes, including deliberately mutated inputs."""
    data = (root / name).read_bytes()
    return {
        "file": name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _menu_record(row: dict[str, Any]) -> bytes:
    history = sum((rank + 1) << (4 * i) for i, rank in enumerate(row["history"]))
    return struct.pack(
        "<QII8B",
        history,
        0xFFFFFFFF,
        0,
        *row["actions"],
        0,
        row["stage"],
        3,
        row["heuristic_index"],
        0,
    )


def _write_menus(
    root: Path,
) -> tuple[bytearray, bytearray, bytearray, list[dict[str, Any]]]:
    """Encode the readable checked-in rows and build a complete frozen keep map."""
    grouped: dict[tuple[str, tuple[int, ...]], list[dict[str, Any]]] = defaultdict(list)
    for row in json.loads(FIXTURE.read_text())["rows"]:
        grouped[(row["role"], tuple(row["own_hand"]))].append(row)
    probabilities, offsets, support = bytearray(), bytearray(), bytearray()
    menus: list[dict[str, Any]] = []
    for (role, hand), rows in sorted(
        grouped.items(), key=lambda item: (ROLES.index(item[0][0]), item[0][1])
    ):
        for row in rows:
            offsets += struct.pack("<I", len(probabilities) // 2)
            probabilities += struct.pack("<3H", *row["counts"])
            support.append(row["support"])
        name = f"menu-{len(menus)}.bin"
        (root / name).write_bytes(b"".join(_menu_record(row) for row in rows))
        menus.append({"role": role, "own_hand": list(hand), **bind(root, name)})
    return probabilities, offsets, support, menus


def _write_prior(root: Path) -> None:
    # Three feasible chance pairs, sparse padding instead of a26MB git blob.
    hands = get_canonical_hands()
    with (root / "prior.bin").open("wb") as prior:
        prior.truncate(1820 * 1820 * 8)
        for pone, dealer in [
            ((0, 0, 1, 8), (0, 0, 1, 8)),
            ((0, 0, 1, 8), (4, 4, 4, 4)),
            ((4, 4, 4, 4), (0, 0, 1, 8)),
        ]:
            prior.seek((hands.index(pone) * 1820 + hands.index(dealer)) * 8)
            prior.write(struct.pack("<Q", 1))


def make_bundle(root: Path) -> Path:
    """Encode checked-in rows and build a complete frozen keep map."""
    probabilities, offsets, support, menus = _write_menus(root)
    for name, data in [
        ("probabilities.bin", probabilities),
        ("offsets.bin", offsets),
        ("support.bin", support),
    ]:
        (root / name).write_bytes(data)
    _write_prior(root)
    discards, fingerprint = discard_bytes()
    (root / "discards.json").write_bytes(discards)
    legacy = Path(__file__).resolve().parent.parent / "simulate_cribbage_games.py"
    manifest: dict[str, Any] = {
        "schema": "six-layer-pegging-policy.v1",
        "probability_denominator": 1000,
        **{
            key: bind(root, key + ".bin")
            for key in ("probabilities", "offsets", "support", "prior")
        },
        "fallback": {
            "identity": "legacy-heuristic-v1",
            "fingerprint": policy_fingerprint(LegacyHeuristicPolicy()),
            "source_sha256": hashlib.sha256(legacy.read_bytes()).hexdigest(),
        },
        "menus": menus,
        "discard_population": {
            **bind(root, "discards.json"),
            "keep_fingerprint": fingerprint,
            "converged": False,
            "description": "Synthetic keep-first-four rank map; not jointly refined with this policy",
        },
    }
    manifest["support"]["mask"] = 1
    path = root / "policy.json"
    path.write_text(json.dumps(manifest))
    return path
