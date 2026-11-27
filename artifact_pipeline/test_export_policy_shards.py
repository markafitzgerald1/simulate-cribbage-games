"""Export the synthetic fixture bundle and read the shards back."""

import contextlib
import gzip
import hashlib
import io
import json
from pathlib import Path
import struct
import unittest
from unittest import mock

from artifact_pipeline.export_policy_shards import (
    encode_shard,
    export,
    hand_key,
    main,
    summarize,
)
from artifact_pipeline.pegging import ROLES, get_canonical_hands
from artifact_pipeline.six_layer_policy import SixLayerPolicy
from artifact_pipeline.test_fixed_policy_fixtures import FIXTURE, bind, make_bundle
from artifact_pipeline.test_six_layer_policy import temporary_directory


def decode_shard(payload: bytes) -> list[tuple]:
    """Read the documented columns back into rows."""
    if payload[:4] != b"CPS1":
        raise ValueError("magic")
    (count,) = struct.unpack_from("<I", payload, 4)
    position = 8
    deltas = struct.unpack_from(f"<{count}Q", payload, position)
    position += 8 * count
    ranks = payload[position : position + 4 * count]
    position += 4 * count
    widths = payload[position : position + count]
    support = payload[position + count : position + 2 * count]
    position += 2 * count
    rows, history = [], 0
    for index in range(count):
        history += deltas[index]
        width = widths[index]
        weights = struct.unpack_from(f"<{width}H", payload, position)
        position += 2 * width
        legal = tuple(ranks[4 * index : 4 * index + width])
        rows.append((history, legal, weights, bool(support[index])))
    if position != len(payload):
        raise ValueError("trailing bytes")
    return rows


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(temporary_directory()))
        (self.root / "bundle").mkdir()
        self.manifest = make_bundle(self.root / "bundle")
        self.digest = hashlib.sha256(self.manifest.read_bytes()).hexdigest()

    def test_layout_is_pinned_byte_for_byte(self):
        rows = [(0, (2, 5), (1000, 0), True), (0x31, (0, 3, 9), (250, 0, 750), False)]
        expected = (
            b"CPS1"
            + struct.pack("<I", 2)
            + struct.pack("<2Q", 0, 0x31)
            + bytes([2, 5, 0, 0, 0, 3, 9, 0])
            + bytes([2, 3])
            + bytes([1, 0])
            + struct.pack("<5H", 1000, 0, 250, 0, 750)
        )
        self.assertEqual(encode_shard(rows), expected)
        self.assertEqual(decode_shard(expected), rows)

    def test_hand_key_spells_ranks_like_the_app(self):
        self.assertEqual(hand_key((0, 9, 10, 12)), "A_T_J_K")

    def test_every_menu_row_round_trips_and_is_bound(self):
        index_digest = export(self.manifest, self.digest, self.root / "out")
        index_bytes = (self.root / "out" / "shards.json").read_bytes()
        self.assertEqual(index_digest, hashlib.sha256(index_bytes).hexdigest())
        index = json.loads(index_bytes)
        self.assertEqual(list(index), sorted(index))
        self.assertEqual(index["schema"], "pegging-policy-shards.v1")
        self.assertEqual(index["policy_manifest_sha256"], self.digest)
        source = json.loads(self.manifest.read_text())
        self.assertEqual(len(index["shards"]), len(source["menus"]))
        hands = get_canonical_hands()
        with SixLayerPolicy(self.manifest) as policy:
            self.assertEqual(
                index["behavioral_fingerprint"], policy.behavioral_fingerprint
            )
            for shard in index["shards"]:
                data = (self.root / "out" / shard["file"]).read_bytes()
                self.assertEqual(shard["bytes"], len(data))
                self.assertEqual(shard["sha256"], hashlib.sha256(data).hexdigest())
                payload = gzip.decompress(data)
                self.assertEqual(
                    shard["payload_sha256"], hashlib.sha256(payload).hexdigest()
                )
                key = ROLES.index(shard["role"]) * len(hands) + hands.index(
                    tuple(shard["own_hand"])
                )
                rows = decode_shard(payload)
                self.assertEqual(rows, list(policy.menu_rows(key)))
                self.assertEqual(shard["rows"], len(rows))
                self.assertEqual(
                    shard["file"],
                    f"{shard['role'].lower()}/{hand_key(shard['own_hand'])}.bin.gz",
                )

    def test_rows_match_the_checked_in_fixture_under_mask_two(self):
        # Expected rows come from the fixture's readable JSON, not the reader.
        # Mask 2 with bytes 2 and 1 tells the mask apart from a hard-coded 1.
        bundle = self.root / "bundle"
        fixture = json.loads(FIXTURE.read_text())["rows"]
        (bundle / "support.bin").write_bytes(
            bytes(2 if row["support"] else 1 for row in fixture)
        )
        manifest = json.loads(self.manifest.read_text())
        manifest["support"] = {**bind(bundle, "support.bin"), "mask": 2}
        self.manifest.write_text(json.dumps(manifest))
        digest = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        export(self.manifest, digest, self.root / "out")
        exported = {}
        for shard in json.loads((self.root / "out" / "shards.json").read_text())[
            "shards"
        ]:
            payload = gzip.decompress((self.root / "out" / shard["file"]).read_bytes())
            for row in decode_shard(payload):
                exported[(shard["role"], tuple(shard["own_hand"]), row[0])] = row[1:]
        expected = {
            (
                row["role"],
                tuple(row["own_hand"]),
                sum((rank + 1) << (4 * i) for i, rank in enumerate(row["history"])),
            ): (tuple(row["actions"]), tuple(row["counts"]), bool(row["support"]))
            for row in fixture
        }
        self.assertEqual(exported, expected)

    def test_index_order_denominator_and_gzip_time_are_fixed(self):
        export(self.manifest, self.digest, self.root / "out")
        index = json.loads((self.root / "out" / "shards.json").read_text())
        self.assertEqual(index["probability_denominator"], 1000)
        hands = get_canonical_hands()
        keys = [
            (ROLES.index(shard["role"]), hands.index(tuple(shard["own_hand"])))
            for shard in index["shards"]
        ]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(set(keys)), len(keys))
        for shard in index["shards"]:
            header = (self.root / "out" / shard["file"]).read_bytes()[:8]
            self.assertEqual(header[4:8], b"\0\0\0\0")

    def test_rejects_a_manifest_swapped_while_loading(self):
        swapped = json.loads(self.manifest.read_text())
        swapped["support"]["mask"] = 2
        load = SixLayerPolicy

        def swap_then_load(path):
            Path(path).write_text(json.dumps(swapped))
            return load(path)

        with mock.patch(
            "artifact_pipeline.export_policy_shards.SixLayerPolicy",
            side_effect=swap_then_load,
        ):
            with self.assertRaisesRegex(ValueError, "changed while it was loaded"):
                export(self.manifest, self.digest, self.root / "out")

    def test_export_is_byte_reproducible(self):
        first = export(self.manifest, self.digest, self.root / "first")
        second = export(self.manifest, self.digest, self.root / "second")
        self.assertEqual(first, second)

    def test_rejects_a_manifest_other_than_the_approved_one(self):
        with self.assertRaisesRegex(ValueError, "approved digest"):
            export(self.manifest, "0" * 64, self.root / "out")

    def test_output_folder_must_be_empty(self):
        (self.root / "out").mkdir()
        (self.root / "out" / "stale").write_text("")
        with self.assertRaisesRegex(ValueError, "must be empty"):
            export(self.manifest, self.digest, self.root / "out")

    def test_main_prints_the_index_digest(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main(
                [
                    "--policy-manifest",
                    str(self.manifest),
                    "--policy-manifest-sha256",
                    self.digest,
                    "--output",
                    str(self.root / "out"),
                ]
            )
        index = (self.root / "out" / "shards.json").read_bytes()
        digest = hashlib.sha256(index).hexdigest()
        first, second = output.getvalue().splitlines()
        self.assertEqual(first, f"shards_index_sha256={digest}")
        self.assertEqual(second, summarize(json.loads(index)))

    def test_summary_of_no_shards_says_so(self):
        self.assertEqual(summarize({"shards": []}), "0 shards")

    def test_summary_names_count_total_median_and_largest(self):
        index = {"shards": [{"bytes": size} for size in (30, 10, 20, 40)]}
        self.assertEqual(
            summarize(index),
            "4 shards, 100 bytes in all; median 30, largest 40 bytes",
        )


class MenuRowsTest(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(temporary_directory()))
        self.manifest = make_bundle(root)

    def test_a_hand_without_a_menu_yields_nothing(self):
        source = json.loads(self.manifest.read_text())
        hands = get_canonical_hands()
        listed = {
            ROLES.index(menu["role"]) * len(hands)
            + hands.index(tuple(menu["own_hand"]))
            for menu in source["menus"]
        }
        missing = next(key for key in range(2 * len(hands)) if key not in listed)
        with SixLayerPolicy(self.manifest) as policy:
            self.assertEqual(policy.menu_rows(missing), [])

    def test_rows_taken_do_not_block_closing_or_eviction(self):
        source = json.loads(self.manifest.read_text())
        hands = get_canonical_hands()
        keys = [
            ROLES.index(menu["role"]) * len(hands)
            + hands.index(tuple(menu["own_hand"]))
            for menu in source["menus"]
        ]
        policy = SixLayerPolicy(self.manifest, cache_limit=1)
        rows = [policy.menu_rows(key) for key in keys]
        policy.close()
        self.assertTrue(all(rows))

    def test_a_closed_policy_yields_no_rows(self):
        policy = SixLayerPolicy(self.manifest)
        policy.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            policy.menu_rows(0)


if __name__ == "__main__":
    unittest.main()
