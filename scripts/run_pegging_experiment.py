"""Run one isolated pegging experiment with read-only timing and lookup counters."""

from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
import hashlib
from importlib import import_module
import json
from pathlib import Path
import shelve
import sys
import time
from typing import Any, Iterator, Mapping
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


class CountedActions(dict[str, int]):
    """Observe real lookups without recomputing actions or consuming randomness."""

    def __init__(self, actions: Mapping[str, int], counts: dict[str, int]):
        super().__init__(actions)
        self.counts = counts

    def get(self, key: str, default: Any = None) -> Any:
        self.counts["lookups"] += 1
        value = super().get(key, default)
        self.counts["hits"] += int(value is not None)
        return value


@contextmanager
def count_policy_usage(policies: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    """Instrument the final frozen measurement, then restore every action table."""
    pegging = import_module("artifact_pipeline.pegging")
    usage: dict[str, Any] = {}
    restored = []
    for role in pegging.ROLES:
        counts = {"lookups": 0, "hits": 0, "legacy": 0, "tables": 0, "entries": 0}
        usage[role] = counts
        seen: set[int] = set()
        states: set[str] = set()

        def visit(policy: Any) -> None:
            if id(policy) in seen:
                return
            seen.add(id(policy))
            if isinstance(policy, pegging.TabularPeggingPolicy):
                restored.append((policy, policy.actions))
                states.update(policy.actions)
                counts["tables"] += 1
                counts["entries"] += len(policy.actions)
                policy.actions = CountedActions(policy.actions, counts)
                visit(policy.fallback)
            elif isinstance(
                policy,
                (
                    pegging.PolicyMixture,
                    pegging.UniformHandPolicy,
                    pegging.GeometricHandPolicy,
                ),
            ):
                for component in policy.policies:
                    visit(component)

        visit(policies[role])
        counts["distinct_stored_states"] = len(states)

    legacy_select = pegging.LegacyHeuristicPolicy.select_rank

    def counted_legacy(policy, view, rng):
        usage[view.role]["legacy"] += 1
        return legacy_select(policy, view, rng)

    try:
        with patch.object(pegging.LegacyHeuristicPolicy, "select_rank", counted_legacy):
            yield usage
    finally:
        for policy, actions in restored:
            policy.actions = actions


def run_experiment(generation_args: list[str]) -> dict[str, Any]:
    """Run the real generator; no alternate sampling or decision implementation."""
    # The runner has its own serial default; later explicit flags override it.
    generation_args = ["--workers=1", *generation_args]
    # Legacy cache construction happens on import, after main has changed cwd.
    generator = import_module("artifact_pipeline.generate_play_table")
    measure_quality = import_module("artifact_pipeline.play_quality").measure_quality
    with patch.object(sys, "argv", ["generate_play_table.py", *generation_args]):
        resolved_args = generator._parse_args()
    if Path("experiment.json").resolve() in {
        Path(path).resolve()
        for path in (
            resolved_args.output,
            resolved_args.client_output,
            resolved_args.lines_output,
        )
    }:
        raise ValueError("Artifact outputs must be separate from the report path")
    stages = []
    usage: dict[str, Any] = {}
    invocations: dict[str, int] = {}

    def timed(name, function):
        def invoke(*args, **kwargs):
            invocations[name] = invocations.get(name, 0) + 1
            label = f"{name}_{invocations[name]}"
            start = time.monotonic()
            if name == "sampling" and "checkpoint" in kwargs:
                kwargs["observe_policy_usage"] = True
                result = function(*args, **kwargs)
                usage.update(result["__metadata__"]["policy_usage"])
                label = "final_sampling"
            else:
                result = function(*args, **kwargs)
            seconds = time.monotonic() - start
            stages.append({"stage": label, "seconds": seconds})
            print(f"[experiment] {label}: {seconds:.3f}s", file=sys.stderr, flush=True)
            return result

        return invoke

    start = time.monotonic()
    with ExitStack() as stack:
        for name, attribute in (
            ("analytical", "solve_initial_discard_policy"),
            ("training", "train_iterative_best_response"),
            ("sampling", "generate_play_table"),
            ("refinement", "refine_discard_policy"),
            ("promotion_gate", "promotion_gate"),
        ):
            stack.enter_context(
                patch.object(
                    generator, attribute, timed(name, getattr(generator, attribute))
                )
            )
        stack.enter_context(
            patch.object(sys, "argv", ["generate_play_table.py", *generation_args])
        )
        generator.main()
    elapsed = time.monotonic() - start
    names = (
        resolved_args.output,
        resolved_args.client_output,
        resolved_args.lines_output,
    )
    full = json.loads(Path(names[0]).read_bytes())
    report = {
        "arguments": generation_args,
        "resolved_workers": resolved_args.workers,
        "elapsed_seconds": elapsed,
        "stages": stages,
        "policy_usage": usage,
        "metadata": full["__metadata__"],
        "gauge": measure_quality(
            Path(names[2]).read_bytes(), Path(names[1]).read_bytes()
        ),
        "sha256": {
            name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in names
        },
        "source_sha256": {
            str(path): hashlib.sha256((REPO_ROOT / path).read_bytes()).hexdigest()
            for path in (
                Path("artifact_pipeline/pegging.py"),
                Path("artifact_pipeline/generate_play_table.py"),
                Path("artifact_pipeline/play_quality.py"),
                Path("artifact_pipeline/promotion_gate.py"),
                Path("artifact_pipeline/policy_usage.py"),
                Path("scripts/run_pegging_experiment.py"),
            )
        },
    }
    Path("experiment.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    """Use an empty isolated output directory and forward generator flags."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args, generation_args = parser.parse_known_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    if any(args.directory.iterdir()):
        parser.error("Experiment directory must be empty")
    # All generator defaults write into this isolated working directory.
    import os  # pylint: disable=import-outside-toplevel

    os.chdir(args.directory)
    shelve.open("start_of_hand_position_results_tallies_shelf", flag="c").close()
    run_experiment(generation_args)


if __name__ == "__main__":  # pragma: no cover
    main()
