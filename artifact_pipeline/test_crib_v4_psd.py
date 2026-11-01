"""Independent principal-minor oracle for exact integer PSD validation."""

import itertools
import random
import unittest

from artifact_pipeline.crib_v4_state import _exact_psd


def principal_minors_are_nonnegative(matrix):
    """Apply the all-principal-minors criterion, without elimination."""
    for size in range(1, len(matrix) + 1):
        for indices in itertools.combinations(range(len(matrix)), size):
            determinant = 0
            for permutation in itertools.permutations(range(size)):
                inversions = sum(
                    permutation[left] > permutation[right]
                    for left in range(size)
                    for right in range(left + 1, size)
                )
                product = (-1) ** inversions
                for row, column in enumerate(permutation):
                    product *= matrix[indices[row]][indices[column]]
                determinant += product
            if determinant < 0:
                return False
    return True


class TestExactPSD(unittest.TestCase):
    """Check definiteness, singular pivots and exact large integer arithmetic."""

    def test_exhaustive_symmetric_three_by_three(self):
        for entries in itertools.product((-1, 0, 1), repeat=6):
            a, b, c, d, e, f = entries
            matrix = [[a, b, c], [b, d, e], [c, e, f]]
            original = [row[:] for row in matrix]
            with self.subTest(matrix=matrix):
                self.assertEqual(
                    _exact_psd(matrix), principal_minors_are_nonnegative(matrix)
                )
                self.assertEqual(matrix, original)

    def test_large_integers_and_singular_congruences(self):
        rng = random.Random(135)
        for diagonal in ((0, 0, 0, 0), (1, 2, 3, 4), (1, 0, 2, 0), (1, -1, 2, 0)):
            basis = [[rng.randrange(-100, 101) for _ in range(4)] for _ in range(4)]
            matrix = [
                [
                    sum(basis[k][i] * diagonal[k] * basis[k][j] for k in range(4))
                    * 10**80
                    for j in range(4)
                ]
                for i in range(4)
            ]
            self.assertEqual(
                _exact_psd(matrix), principal_minors_are_nonnegative(matrix)
            )
        for matrix in (
            [],
            [[0, 0], [0, 2]],
            [[2, 2, 0], [2, 2, 0], [0, 0, 3]],
            [[2, 2, 0], [2, 2, 1], [0, 1, 3]],
            [[2, 0, 1], [0, 0, 0], [1, 0, 2]],
            [[2, 0, 1], [0, 0, 0], [1, 0, -2]],
        ):
            with self.subTest(matrix=matrix):
                self.assertEqual(
                    _exact_psd(matrix), principal_minors_are_nonnegative(matrix)
                )
