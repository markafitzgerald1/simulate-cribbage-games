"""Bundle generator-layout outputs and load them through the real readers."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import unittest

from artifact_pipeline.bundle_fixed_play_inputs import bundle, main
from artifact_pipeline.pegging import ROLES, get_canonical_hands
from artifact_pipeline.six_layer_policy import SixLayerPolicy
from artifact_pipeline.test_fixed_policy_fixtures import make_bundle
from artifact_pipeline.test_six_layer_policy import temporary_directory


def generator_layout(root: Path, converged: object = False) -> tuple[Path, Path, dict]:
    """Lay the synthetic fixture out as the Rust work folder and prior artifact."""
    source = root / "source"
    source.mkdir()
    manifest = json.loads(make_bundle(source).read_text())
    work, prior = root / "work", root / "prior"
    (work / "menus").mkdir(parents=True)
    prior.mkdir()
    hands = get_canonical_hands()
    for index in range(len(ROLES) * len(hands)):
        (work / "menus" / f"{index}.bin").write_bytes(b"")
    for menu in manifest["menus"]:
        index = ROLES.index(menu["role"]) * len(hands) + hands.index(
            tuple(menu["own_hand"])
        )
        shutil.copyfile(source / menu["file"], work / "menus" / f"{index}.bin")
    for name, target in [
        ("probabilities.bin", work / "policy.bin"),
        ("offsets.bin", work / "offsets.bin"),
        ("support.bin", work / "support.bin"),
        ("prior.bin", prior / "prior.bin"),
    ]:
        shutil.copyfile(source / name, target)
    population = json.loads((source / "discards.json").read_bytes())
    if converged is not None:
        population["converged"] = converged
    (prior / "population.json").write_text(json.dumps(population))
    return work, prior, manifest


class BundleTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(temporary_directory()))

    def test_bundle_loads_and_its_digest_is_reproducible(self):
        work, prior, source = generator_layout(self.root)
        first = bundle(work, prior, self.root / "first")
        second = bundle(work, prior, self.root / "second")
        data = (self.root / "first" / "policy.json").read_bytes()
        self.assertEqual(first, hashlib.sha256(data).hexdigest())
        self.assertEqual(first, second)
        manifest = json.loads(data)
        self.assertEqual(list(manifest), sorted(manifest))
        self.assertEqual(manifest["support"]["mask"], 1)
        self.assertIs(manifest["discard_population"]["converged"], False)
        # Each menu file must stay bound to the hand the fixture wrote it for.
        self.assertEqual(
            sorted((m["role"], m["own_hand"], m["sha256"]) for m in manifest["menus"]),
            sorted((m["role"], m["own_hand"], m["sha256"]) for m in source["menus"]),
        )
        with SixLayerPolicy(self.root / "first" / "policy.json") as policy:
            self.assertEqual(sum(policy.decision_counts().values()), 0)

    def test_population_must_report_not_converged(self):
        for converged in (True, None):
            with self.subTest(converged=converged):
                root = self.root / str(converged)
                root.mkdir()
                work, prior, _ = generator_layout(root, converged)
                with self.assertRaisesRegex(ValueError, "converged: false"):
                    bundle(work, prior, root / "out")

    def test_bundle_rejects_inputs_its_readers_would_reject(self):
        # Each case is caught only by the bundler's own full-size load check.
        for name, message in [
            ("policy", "sum to 1000"),
            ("population", "cover every canonical"),
        ]:
            with self.subTest(name=name):
                root = self.root / name
                root.mkdir()
                work, prior, _ = generator_layout(root)
                if name == "policy":
                    data = bytearray((work / "policy.bin").read_bytes())
                    data[0] ^= 1
                    (work / "policy.bin").write_bytes(data)
                else:
                    population = json.loads((prior / "population.json").read_bytes())
                    population["keeps"].pop()
                    (prior / "population.json").write_text(json.dumps(population))
                with self.assertRaisesRegex(ValueError, message):
                    bundle(work, prior, root / "out")

    def test_output_folder_must_be_empty(self):
        work, prior, _ = generator_layout(self.root)
        (self.root / "out").mkdir()
        (self.root / "out" / "stale").write_text("x")
        with self.assertRaisesRegex(ValueError, "must be empty"):
            bundle(work, prior, self.root / "out")

    def test_main_prints_the_manifest_digest(self):
        work, prior, _ = generator_layout(self.root)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main(
                [
                    "--work",
                    str(work),
                    "--prior-dir",
                    str(prior),
                    "--output",
                    str(self.root / "out"),
                ]
            )
        digest = hashlib.sha256(
            (self.root / "out" / "policy.json").read_bytes()
        ).hexdigest()
        self.assertEqual(output.getvalue(), f"policy_manifest_sha256={digest}\n")


if __name__ == "__main__":
    unittest.main()
