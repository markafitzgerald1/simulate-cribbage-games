"""Compare shipped JSON with the issue #137 packed binary candidate, read-only.

Run from the repository root with python -m scripts.measure_uncertainty SIDECAR.
The binary candidate is an experiment, not a supported export format.
"""

import gzip
import json
import struct
import sys
from pathlib import Path

from artifact_pipeline.export_uncertainty import read_json


def packed_candidate(sidecar):
    """Use the specified header, presence masks and unrounded little-endian doubles."""
    header = {key: value for key, value in sidecar.items() if key != "record_groups"}
    columns = ["reported_marginal_se", "n"]
    if header["table"] == "crib":
        columns.append("sum_w2")
    header["columns"] = columns
    records = sidecar["record_groups"]["totals"]["records"]
    masks = bytearray()
    values = bytearray()
    for key in header["keys"]:
        for role in header["roles"]:
            for rank in header["ranks"] or [None]:
                prefix = f"{key}/{role}/" + (f"{rank}/" if rank else "")
                mask = 0
                for bit, slot in enumerate(header["slots"]):
                    record = records.get(prefix + slot)
                    if record is not None:
                        mask |= 1 << bit
                        values.extend(
                            struct.pack(
                                "<" + "d" * len(columns),
                                *(record[column] for column in columns),
                            )
                        )
                masks.append(mask)
    header["mask_bytes"] = len(masks)
    header["record_count"] = len(records)
    encoded_header = json.dumps(header, separators=(",", ":"), allow_nan=False).encode()
    return (
        b"EPU1"
        + struct.pack("<I", len(encoded_header))
        + encoded_header
        + masks
        + values
    )


def main():
    for argument in sys.argv[1:]:
        data = Path(argument).read_bytes()
        binary = packed_candidate(read_json(data))
        print(
            json.dumps(
                {
                    "file": argument,
                    "json_raw": len(data),
                    "json_gzip9": len(gzip.compress(data, 9, mtime=0)),
                    "binary_raw": len(binary),
                    "binary_gzip9": len(gzip.compress(binary, 9, mtime=0)),
                }
            )
        )


if __name__ == "__main__":
    main()
