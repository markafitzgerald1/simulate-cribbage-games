"""Fixed four-shard pre-cut survey; execution requires maintainer approval."""

import argparse
from pathlib import Path

from scripts import run_crib_v4_diagnostic as diagnostic

# Declared before execution: three slightly slower Jack groups per shard.
# Others cost about 21 seconds/1,000 rows; Jack groups about 22 seconds.
SHARDS = {
    "1": (
        "A_2",
        "A_6",
        "A_T",
        "2_4",
        "2_8",
        "2_K",
        "3_7",
        "3_Q",
        "4_7",
        "4_Q",
        "5_8",
        "5_K",
        "6_T",
        "7_9",
        "8_9",
        "9_T",
        "T_K",
        "A_J",
        "5_J",
        "9_J",
    ),
    "2": (
        "A_3",
        "A_7",
        "A_Q",
        "2_5",
        "2_9",
        "3_4",
        "3_8",
        "3_K",
        "4_8",
        "4_K",
        "5_9",
        "6_7",
        "6_Q",
        "7_T",
        "8_T",
        "9_Q",
        "Q_K",
        "2_J",
        "6_J",
        "T_J",
    ),
    "3": (
        "A_4",
        "A_8",
        "A_K",
        "2_6",
        "2_T",
        "3_5",
        "3_9",
        "4_5",
        "4_9",
        "5_6",
        "5_T",
        "6_8",
        "6_K",
        "7_Q",
        "8_Q",
        "9_K",
        "3_J",
        "7_J",
        "J_Q",
    ),
    "4": (
        "A_5",
        "A_9",
        "2_3",
        "2_7",
        "2_Q",
        "3_6",
        "3_T",
        "4_6",
        "4_T",
        "5_7",
        "5_Q",
        "6_9",
        "7_8",
        "7_K",
        "8_K",
        "T_Q",
        "4_J",
        "8_J",
        "J_K",
    ),
}
SAMPLES = 22000
WORKFLOW = ".github/workflows/survey-crib-v4.yml"


def validate_resume_run(document, repository):
    """Require this survey's completed manual run before restoring its shard."""
    diagnostic.validate_resume_run(document, repository, workflow=WORKFLOW)


def run(source, client, output, stop_at, shard):
    """Use the shared checked coordinator with a shard-specific identity."""
    groups = SHARDS[shard]
    identity = diagnostic.manifest(
        groups, SAMPLES, ("scripts/run_crib_v4_survey.py", WORKFLOW)
    )
    identity["shard"] = shard
    return diagnostic.run(
        source,
        client,
        output,
        stop_at,
        groups=groups,
        samples=SAMPLES,
        identity=identity,
    )


def main():
    """Expose only the committed shard selection, paths and deadline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stop-at", type=float, required=True)
    parser.add_argument("--shard", choices=SHARDS, required=True)
    args = parser.parse_args()
    run(args.source, args.client, args.output, args.stop_at, args.shard)


if __name__ == "__main__":
    main()
