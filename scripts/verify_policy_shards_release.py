"""Verify the index and shard bytes inside an approved export ZIP."""

import hashlib
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile


def verify(archive_path: Path, index_digest: str) -> int:
    """Check the exact archive inventory and every indexed gzip digest."""
    with ZipFile(archive_path) as archive:
        index_bytes = archive.read("shards.json")
        if hashlib.sha256(index_bytes).hexdigest() != index_digest:
            raise ValueError("shards.json SHA-256 mismatch")
        index = json.loads(index_bytes)
        if index["schema"] != "pegging-policy-shards.v1" or not index["shards"]:
            raise ValueError("Expected a nonempty pegging-policy-shards.v1 index")

        expected = {"shards.json"}
        for shard in index["shards"]:
            name = shard["file"]
            if not re.fullmatch(
                r"(pone|dealer)/[A2-9TJQK](?:_[A2-9TJQK]){3}\.bin\.gz", name
            ):
                raise ValueError(f"Invalid shard path: {name}")
            if name in expected:
                raise ValueError(f"Duplicate index entry: {name}")
            expected.add(name)

        if sorted(archive.namelist()) != sorted(expected):
            raise ValueError("ZIP members do not match the shard index")
        for shard in index["shards"]:
            data = archive.read(shard["file"])
            if hashlib.sha256(data).hexdigest() != shard["sha256"]:
                raise ValueError(f"Shard SHA-256 mismatch: {shard['file']}")
        return len(index["shards"])


if __name__ == "__main__":
    count = verify(Path(sys.argv[1]), sys.argv[2])
    print(f"Verified shards.json and {count:,} shards")
