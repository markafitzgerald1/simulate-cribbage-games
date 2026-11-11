"""Write the golden pegging scores that the Rust engine is checked against.

`native/cfr` implements the pegging rules a second time, in Rust. This module
plays a fixed sample of deals with `simulate_pegging`, the published Python
engine, under a deterministic choice rule both engines can apply, and writes
each deal's final points. The Rust test `native/cfr/tests/rules.rs` replays
the same deals and must match every line, and `test_pegging_golden.py` checks
that the committed file is exactly what this module writes.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
import os
from pathlib import Path
import random
import sys

if __package__ in (None, ""):  # pragma: no cover
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# pylint: disable=wrong-import-position
from artifact_pipeline.pegging import (  # noqa: E402
    DEALER,
    PONE,
    PolicyView,
    get_canonical_hands,
    simulate_pegging,
)

GOLDEN = Path(__file__).resolve().parents[1] / "native/cfr/tests/pegging_golden.txt"
# Every 37th Pone hand against every 11th Dealer hand: about 8,000 feasible
# deals, spread over the whole canonical order.
PONE_STEP, DEALER_STEP = 37, 11


class RotatingRule:
    """Pick legal rank number (count + cards held) modulo the legal ranks.

    It depends only on public facts both engines expose, and it varies the
    choice from move to move so every scoring rule gets exercised.
    """

    def select_rank(self, view: PolicyView, rng: random.Random) -> int:
        """Choose one legal rank; the random generator is not used."""
        del rng
        legal = view.legal_ranks
        return legal[(view.count + len(view.own_remaining)) % len(legal)]


def golden_lines() -> list[str]:
    """Return one `pone dealer pone_points dealer_points` line per deal."""
    hands = get_canonical_hands()
    policies = {PONE: RotatingRule(), DEALER: RotatingRule()}
    rng = random.Random(0)
    lines = []
    for pone in range(0, len(hands), PONE_STEP):
        for dealer in range(0, len(hands), DEALER_STEP):
            if max(Counter(hands[pone] + hands[dealer]).values()) > 4:
                continue
            result = simulate_pegging(hands[pone], hands[dealer], policies, rng)
            points = (int(result.total(PONE)), int(result.total(DEALER)))
            lines.append(f"{pone} {dealer} {points[0]} {points[1]}")
    return lines


def main(argv: Sequence[str] | None = None) -> None:
    """Write the golden file."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=GOLDEN)
    arguments = parser.parse_args(argv)
    arguments.output.write_text("\n".join(golden_lines()) + "\n", encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    main()
