"""Export a fixed six-layer pegging policy as per-hand browser shards.

The input is a bundle that `bundle_fixed_play_inputs` wrote and
`SixLayerPolicy` accepts, named by its approved manifest digest. The output
folder receives one gzip file per own hand that has a real choice, under
`<role>/<hand key>.bin.gz`, and `shards.json`, which binds every file to its
bytes and to the bundle. `docs/policy-shards.md` is the format contract.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import struct
from typing import Any, Iterable

from artifact_pipeline.pegging import ROLES, get_canonical_hands
from artifact_pipeline.six_layer_policy import DENOMINATOR, SixLayerPolicy

SCHEMA = "pegging-policy-shards.v1"
MAGIC = b"CPS1"
RANK_LABELS = "A23456789TJQK"
DESCRIPTION = (
    "Rank-only CFR pegging policy for one seat and original four-card keep, "
    "rounded to integer counts out of 1000. Trained against a fixed discard "
    "population that was not jointly refined with it; carries no values."
)

Row = tuple[int, tuple[int, ...], tuple[int, ...], bool]


def hand_key(hand: Iterable[int]) -> str:
    """Spell zero-based ranks the way the app's play tables key a hand."""
    return "_".join(RANK_LABELS[rank] for rank in hand)


def encode_shard(rows: list[Row]) -> bytes:
    """Lay one menu out column by column, so gzip sees runs of like bytes."""
    histories, ranks, widths, support, counts = (bytearray() for _ in range(5))
    previous = 0
    for history, legal, weights, supported in rows:
        histories += struct.pack("<Q", history - previous)
        previous = history
        ranks += bytes((*legal, *(0,) * (4 - len(legal))))
        widths.append(len(legal))
        support.append(int(supported))
        counts += struct.pack(f"<{len(weights)}H", *weights)
    header = MAGIC + struct.pack("<I", len(widths))
    return bytes(header + histories + ranks + widths + support + counts)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def export(manifest_path: Path, manifest_sha256: str, output: Path) -> str:
    """Write every shard and the index; return the index's SHA-256."""
    manifest_bytes = manifest_path.read_bytes()
    if _sha256(manifest_bytes) != manifest_sha256:
        raise ValueError("Policy manifest differs from its approved digest")
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Output folder {output} must be empty")
    hands = get_canonical_hands()
    shards: list[dict[str, Any]] = []
    with SixLayerPolicy(manifest_path) as policy:
        for key in range(len(ROLES) * len(hands)):
            rows = list(policy.menu_rows(key))
            if not rows:
                continue
            role, hand = ROLES[key // len(hands)], hands[key % len(hands)]
            payload = encode_shard(rows)
            data = gzip.compress(payload, 9, mtime=0)
            name = f"{role.lower()}/{hand_key(hand)}.bin.gz"
            (output / name).parent.mkdir(parents=True, exist_ok=True)
            (output / name).write_bytes(data)
            shards.append(
                {
                    "role": role,
                    "own_hand": list(hand),
                    "file": name,
                    "rows": len(rows),
                    "bytes": len(data),
                    "sha256": _sha256(data),
                    "payload_sha256": _sha256(payload),
                }
            )
        index = {
            "schema": SCHEMA,
            "description": DESCRIPTION,
            "probability_denominator": DENOMINATOR,
            "policy_manifest_sha256": manifest_sha256,
            "behavioral_fingerprint": policy.behavioral_fingerprint,
            "shards": shards,
        }
    data = (json.dumps(index, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (output / "shards.json").write_bytes(data)
    return _sha256(data)


def summarize(index: dict[str, Any]) -> str:
    """State what a page would download, so a size change is visible."""
    sizes = sorted(shard["bytes"] for shard in index["shards"])
    return (
        f"{len(sizes)} shards, {sum(sizes)} bytes in all; "
        f"median {sizes[len(sizes) // 2]}, largest {sizes[-1]} bytes"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-manifest", type=Path, required=True)
    parser.add_argument("--policy-manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    digest = export(args.policy_manifest, args.policy_manifest_sha256, args.output)
    print(f"shards_index_sha256={digest}")
    print(summarize(json.loads((args.output / "shards.json").read_bytes())))


if __name__ == "__main__":  # pragma: no cover
    main()
