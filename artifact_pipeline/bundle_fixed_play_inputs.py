"""Bundle generated CFR outputs into a fixed-policy measurement manifest.

Inputs are the CFR input generator's work folder (`menus/<k>.bin`,
`offsets.bin`, `policy.bin`, `support.bin`) and the prior folder
(`prior.bin`, `population.json`). The output folder receives copies of every
component plus `policy.json`, written with sorted keys and fixed separators so
its SHA-256 depends only on the component bytes. The bundle is then loaded once
at full size, which is the format check a measurement run would otherwise do.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from artifact_pipeline.fixed_play_inputs import load_fixed_discards
from artifact_pipeline.pegging import (
    LegacyHeuristicPolicy,
    ROLES,
    get_canonical_hands,
    policy_fingerprint,
)
from artifact_pipeline.six_layer_policy import SixLayerPolicy

LEGACY_SOURCE = Path(__file__).resolve().parent.parent / "simulate_cribbage_games.py"
POPULATION_DESCRIPTION = (
    "Discard refinement from the CFR prior generator, not converged; "
    "not jointly refined with this pegging policy"
)


def _place(source: Path, output: Path, name: str) -> dict[str, Any]:
    """Copy one component into the bundle and bind its exact bytes."""
    target = output / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return {"file": name, "bytes": target.stat().st_size, "sha256": digest.hexdigest()}


def build_manifest(work: Path, prior_dir: Path, output: Path) -> dict[str, Any]:
    """Assemble the manifest; refuse a population that claims convergence."""
    population = json.loads((prior_dir / "population.json").read_bytes())
    if population.get("converged") is not False:
        raise ValueError("Discard population must report converged: false")
    hands = get_canonical_hands()
    menus = []
    for index in range(len(ROLES) * len(hands)):
        source = work / "menus" / f"{index}.bin"
        if source.stat().st_size:
            menus.append(
                {
                    "role": ROLES[index // len(hands)],
                    "own_hand": list(hands[index % len(hands)]),
                    **_place(source, output, f"menus/{index}.bin"),
                }
            )
    return {
        "schema": "six-layer-pegging-policy.v1",
        "probability_denominator": 1000,
        "probabilities": _place(work / "policy.bin", output, "policy.bin"),
        "offsets": _place(work / "offsets.bin", output, "offsets.bin"),
        "support": {**_place(work / "support.bin", output, "support.bin"), "mask": 1},
        "prior": _place(prior_dir / "prior.bin", output, "prior.bin"),
        "fallback": {
            "identity": "legacy-heuristic-v1",
            "fingerprint": policy_fingerprint(LegacyHeuristicPolicy()),
            "source_sha256": hashlib.sha256(LEGACY_SOURCE.read_bytes()).hexdigest(),
        },
        "menus": menus,
        "discard_population": {
            **_place(prior_dir / "population.json", output, "population.json"),
            "keep_fingerprint": population.get("discard_policy_fingerprint"),
            "converged": False,
            "description": POPULATION_DESCRIPTION,
        },
    }


def bundle(work: Path, prior_dir: Path, output: Path) -> str:
    """Write and load-check the bundle; return the manifest SHA-256."""
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Output folder {output} must be empty")
    output.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(work, prior_dir, output)
    data = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path = output / "policy.json"
    path.write_bytes(data)
    with SixLayerPolicy(path):
        pass
    load_fixed_discards(output, manifest["discard_population"])
    return hashlib.sha256(data).hexdigest()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--prior-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    digest = bundle(args.work, args.prior_dir, args.output)
    print(f"policy_manifest_sha256={digest}")


if __name__ == "__main__":  # pragma: no cover
    main()
