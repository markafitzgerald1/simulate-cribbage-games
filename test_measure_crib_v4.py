"""Guard the pilot report's population weights and joint comparison errors."""

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from artifact_pipeline.crib_v4 import _physical_group
from artifact_pipeline import generate_table
from artifact_pipeline.crib_v4_state import (
    SCALE,
    add_row,
    coordinate_labels,
    empty_moments,
)
from scripts.measure_crib_v4 import comparison


class TestPilotComparison(unittest.TestCase):
    """Use hand-calculated row projections, including negative covariance."""

    def test_precut_weights_and_cross_cut_covariance(self):
        group = _physical_group("3_8", generate_table)
        streams = {
            name: empty_moments(
                coordinate_labels(group, generate_table.Index.indices, name)
            )
            for name in ("base", "residual", "suit")
        }
        for observation in (
            {"3/base/runs": 5000, "3/residual/runs": 50, "8/Suited/root/flushes": 50},
            {"A/Suited/root/nobs": 50},
        ):
            for name, moments in streams.items():
                add_row(
                    moments,
                    [SCALE * observation.get(label, 0) for label in moments["labels"]],
                )
        result = comparison(streams, "3_8")
        # Own-rank weights are 3/50, other ranks 4/50. Residual rows
        # project to (3,0), suit totals to (3,4), not independent F and J.
        self.assertEqual(result["residual"], {"n": 2, "mu": 1.5, "se": 1.5})
        self.assertEqual(result["flush"], {"n": 2, "mu": 1.5, "se": 1.5})
        self.assertEqual(result["nobs"], {"n": 2, "mu": 2.0, "se": 2.0})
        self.assertEqual(result["gap"], {"n": 2, "mu": 5.0, "se": math.sqrt(2.5)})


class TestPilotSourceProtection(unittest.TestCase):
    """Reject writer paths that can destroy the diagnostic input."""

    def test_temporary_path_aliases_are_rejected_before_writing(self):
        repository = Path(__file__).resolve().parent
        for alias in ("direct", "symlink", "hard_link"):
            with self.subTest(alias=alias), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                output = folder / "diagnostic.json"
                temporary = Path(f"{output}.tmp")
                source = temporary if alias == "direct" else folder / "source.json"
                original = json.dumps(
                    {"__metadata__": {"generation_accumulators": None}}
                ).encode()
                source.write_bytes(original)
                if alias == "symlink":
                    temporary.symlink_to(source)
                elif alias == "hard_link":
                    os.link(source, temporary)
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "scripts.measure_crib_v4",
                        "--source",
                        str(source),
                        "--output",
                        str(output),
                        "--samples",
                        "2",
                    ],
                    cwd=folder,
                    env={**os.environ, "PYTHONPATH": str(repository)},
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertTrue("source" in result.stderr)
                self.assertEqual(source.read_bytes(), original)
                self.assertFalse(output.exists())
