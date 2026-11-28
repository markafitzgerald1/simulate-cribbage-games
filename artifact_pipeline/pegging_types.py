"""Roles and online moments shared by pegging and its exports."""

from dataclasses import dataclass
import math
from typing import Mapping

PONE = "Pone"
DEALER = "Dealer"
ROLES = (PONE, DEALER)


@dataclass
class RunningStatistics:
    """Online sample moments for one scalar estimate."""

    n: int = 0
    mean: float = 0.0
    moment_2: float = 0.0

    def add(self, value: float) -> None:
        """Add one observation."""
        self.n += 1
        delta = value - self.mean
        self.mean += delta / self.n
        self.moment_2 += delta * (value - self.mean)

    @property
    def standard_error(self) -> float:
        """Return the sample standard error."""
        if self.n < 2:
            return 0.0
        variance = self.moment_2 / (self.n - 1)
        return math.sqrt(variance / self.n)

    def to_dict(self) -> dict[str, float | int]:
        """Return the public artifact statistics shape."""
        return {"n": self.n, "mu": self.mean, "se": self.standard_error}

    @classmethod
    def from_dict(cls, statistics: Mapping[str, float | int]) -> "RunningStatistics":
        """Reconstruct resumable moments from n, mean, and standard error."""
        sample_count = int(statistics["n"])
        standard_error = float(statistics["se"])
        moment_2 = (
            standard_error * standard_error * sample_count * max(0, sample_count - 1)
        )
        return cls(
            n=sample_count,
            mean=float(statistics["mu"]),
            moment_2=moment_2,
        )
