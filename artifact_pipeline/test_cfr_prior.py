"""Tests for the CFR discard population and 50/50 prior builder."""

from array import array
from collections import Counter
from fractions import Fraction
from itertools import combinations
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from artifact_pipeline import cfr_prior
from artifact_pipeline import generate_play_table as generator
from artifact_pipeline.analytical_solver import get_analytical_pairs
from artifact_pipeline.pegging import DEALER, PONE, ROLES, get_canonical_hands

KEYS = 1820


def lowest_keeps(ranks=cfr_prior.RANKS):
    """A complete keep map: each role keeps the four lowest dealt ranks."""
    return [
        (role, hand, hand[:4])
        for role in ROLES
        for hand in cfr_prior.rank_hands(cfr_prior.DEALT, ranks)
    ]


def seeded_keeps(ranks, seed):
    """A complete keep map choosing a random four of six for each role."""
    rng = random.Random(seed)
    rows = []
    for role in ROLES:
        for hand in cfr_prior.rank_hands(cfr_prior.DEALT, ranks):
            rows.append((role, hand, tuple(sorted(rng.sample(hand, 4)))))
    return rows


def card_level_matrix(rows, ranks):
    """Count every physical deal of two six-card hands, card by card.

    This oracle never uses rank multiplicities or binomials: it deals
    actual cards (rank, suit) and looks up each role's keep.
    """
    keeps = {(role, hand): keep for role, hand, keep in rows}
    index = {hand: i for i, hand in enumerate(cfr_prior.rank_hands(4, ranks))}
    count = len(index)
    matrix = [0] * (count * count)
    deck = [(rank, suit) for rank in range(ranks) for suit in range(4)]
    for pone in combinations(range(len(deck)), 6):
        pone_hand = tuple(sorted(deck[i][0] for i in pone))
        row = index[keeps[(PONE, pone_hand)]] * count
        rest = [i for i in range(len(deck)) if i not in pone]
        for dealer in combinations(rest, 6):
            dealer_hand = tuple(sorted(deck[i][0] for i in dealer))
            matrix[row + index[keeps[(DEALER, dealer_hand)]]] += 1
    return matrix


def stub_context(top=True):
    """A context whose discards are each hand's top (or bottom) two ranks."""
    pairs = {pair: i for i, pair in enumerate(get_analytical_pairs())}
    selected = [
        (
            hand,
            pairs[hand[4:] if top else hand[:2]],
            pairs[hand[4:] if top else hand[:2]],
        )
        for hand in cfr_prior.rank_hands(cfr_prior.DEALT)
    ]
    return SimpleNamespace(selected_discards=selected)


class TestRankHands(unittest.TestCase):
    """The key orders the solver depends on."""

    def test_four_card_order_is_the_solver_order(self):
        """Keys follow get_canonical_hands, which the Rust solve also uses."""
        self.assertEqual(cfr_prior.rank_hands(4), get_canonical_hands())

    def test_six_card_hands_exclude_five_of_a_rank(self):
        """18,564 multisets less 169 with five or six of one rank."""
        hands = cfr_prior.rank_hands(6)
        self.assertEqual(len(hands), 18_395)
        self.assertNotIn((0, 0, 0, 0, 0, 1), hands)


class TestJointKeepMatrix(unittest.TestCase):
    """The packed expansion against independent physical counts."""

    def test_matches_card_level_enumeration(self):
        """Every cell equals a card-by-card count of physical deals.

        Mutations caught (each shown failing in a scratch copy): K1, the
        Dealer factor omits ranks the shared sub-multiset does not use;
        K2, the inclusion-exclusion sign is dropped; K3, the Pone part
        omits the Pone hand's physical weight. The kernel's raw cells are
        compared first, so a mutant fails here (a wrong cell, or a negative
        lane that cannot be encoded) even without the mass guards.
        """
        rows = seeded_keeps(4, seed=7)
        expected = card_level_matrix(rows, 4)
        hands = cfr_prior.rank_hands(4, 4)
        index = {hand: i for i, hand in enumerate(hands)}
        by_role = {
            role: [(hand, index[keep]) for r, hand, keep in rows if r == role]
            for role in ROLES
        }
        raw = cfr_prior.joint_keep_matrix(by_role[PONE], by_role[DEALER], len(hands))
        self.assertEqual(list(cfr_prior.read_matrix(raw, len(hands))), expected)
        self.assertEqual(list(cfr_prior.production_matrix(rows, 4)), expected)

    def test_full_deck_cells_match_hand_counts(self):
        """Spot cells of the uniform prior, counted by hand."""
        uniform = cfr_prior.uniform_matrix()
        index = {hand: i for i, hand in enumerate(get_canonical_hands())}

        def cell(pone, dealer):
            return uniform[index[pone] * KEYS + index[dealer]]

        self.assertEqual(cell((0, 0, 0, 0), (0, 0, 0, 0)), 0)
        self.assertEqual(cell((0, 0, 0, 0), (1, 1, 1, 1)), 1)
        # Four distinct ranks: 4^4 Pone hands, then 3^4 Dealer hands.
        self.assertEqual(cell((0, 1, 2, 3), (0, 1, 2, 3)), 256 * 81)
        # Pone AA23: C(4,2)*4*4; Dealer AA44 from two Aces left: 1*C(4,2).
        self.assertEqual(cell((0, 0, 1, 2), (0, 0, 3, 3)), 96 * 6)
        self.assertEqual(sum(uniform), math.comb(52, 4) * math.comb(48, 4))

    def test_full_deck_rows_match_direct_pair_sums(self):
        """Two full-size production rows equal the research counter's sum.

        The research `exact_keep_population.cpp` visits every deal pair and
        adds weight(p) * prod C(4 - p_r, d_r); this repeats that directly
        for the Pone hands of two keeps.
        """
        rows = seeded_keeps(13, seed=11)
        matrix = cfr_prior.production_matrix(rows)
        index = {hand: i for i, hand in enumerate(get_canonical_hands())}
        dealer = [
            (Counter(hand), index[keep]) for role, hand, keep in rows if role == DEALER
        ]
        for keep in ((0, 1, 2, 3), (4, 4, 9, 12)):
            direct = [0] * KEYS
            for role, hand, kept in rows:
                if role != PONE or kept != keep:
                    continue
                own = Counter(hand)
                weight = math.prod(math.comb(4, n) for n in own.values())
                for counts, column in dealer:
                    direct[column] += weight * math.prod(
                        math.comb(4 - own[r], n) for r, n in counts.items()
                    )
            row = index[keep] * KEYS
            self.assertEqual(list(matrix[row : row + KEYS]), direct)


class TestMatrixGuards(unittest.TestCase):
    """The mass and marginal checks reject a damaged matrix."""

    def test_uniform_rejects_wrong_mass(self):
        """A uniform matrix missing one deal fails its exhaustion check."""
        good = cfr_prior.joint_keep_matrix

        def damaged(*args):
            values = array("Q", good(*args))
            values[0] += 1
            return values.tobytes()

        with patch.object(cfr_prior, "joint_keep_matrix", damaged):
            with self.assertRaisesRegex(ValueError, "four-card deals"):
                cfr_prior.uniform_matrix(2)

    def test_production_rejects_wrong_mass(self):
        """A production matrix with one extra deal fails its total check."""
        good = cfr_prior.joint_keep_matrix

        def damaged(*args):
            values = array("Q", good(*args))
            values[0] += 1
            return values.tobytes()

        with patch.object(cfr_prior, "joint_keep_matrix", damaged):
            with self.assertRaisesRegex(ValueError, "exhaust physical deals"):
                cfr_prior.production_matrix(lowest_keeps(3), 3)

    def test_production_rejects_wrong_marginal(self):
        """Mass moved between keeps keeps the total but breaks a marginal."""
        good = cfr_prior.joint_keep_matrix

        def damaged(*args):
            values = array("Q", good(*args))
            source = next(i for i, v in enumerate(values) if v)
            values[source] -= 1
            values[(source + 1) % len(values)] += 1
            return values.tobytes()

        with patch.object(cfr_prior, "joint_keep_matrix", damaged):
            with self.assertRaisesRegex(ValueError, "marginal"):
                cfr_prior.production_matrix(lowest_keeps(3), 3)

    def test_read_matrix_rejects_wrong_size(self):
        """A matrix of the wrong byte length is refused."""
        with self.assertRaisesRegex(ValueError, "2 x 2"):
            cfr_prior.read_matrix(b"\x00" * 24, 2)


class TestMixture(unittest.TestCase):
    """The exact equal-probability mixture."""

    def test_mixture_is_equal_probability(self):
        """Each cell's share is the mean of its two normalized shares.

        Mutation caught (shown failing in a scratch copy): M1, adding the
        raw weights (u + p), which weights the larger-mass prior more.
        """
        uniform = array("Q", [1, 3, 0, 6])
        production = array("Q", [5, 0, 2, 13])
        mixed = cfr_prior.mixture_weights(uniform, production)
        for u, p, m in zip(uniform, production, mixed):
            expected = (Fraction(u, sum(uniform)) + Fraction(p, sum(production))) / 2
            self.assertEqual(Fraction(m, sum(mixed)), expected)

    def test_mixture_scales_by_the_masses_gcd(self):
        """Equal masses mix to the plain sum, the smallest exact integers."""
        self.assertEqual(
            list(cfr_prior.mixture_weights([2, 2], [3, 1])),
            [5, 3],
        )

    def test_mixture_rejects_bad_inputs(self):
        """Mismatched, negative or empty inputs are refused."""
        for uniform, production, message in (
            ([1], [1, 1], "Incompatible"),
            ([-1, 2], [1, 1], "Incompatible"),
            ([1, 1], [-1, 2], "Incompatible"),
            ([0, 0], [1, 1], "Empty"),
            ([1, 1], [0, 0], "Empty"),
        ):
            with self.assertRaisesRegex(ValueError, message):
                cfr_prior.mixture_weights(uniform, production)

    def test_prior_mass_must_fit_the_solver_total(self):
        """The Rust solve sums the prior in u64, so a larger total fails."""
        huge = array("Q", [1 << 63, 1 << 63])
        with patch.object(cfr_prior, "mixture_weights", return_value=huge):
            with self.assertRaisesRegex(ValueError, "u64"):
                cfr_prior.build_prior(lowest_keeps(3), 3)


class TestValidateRows(unittest.TestCase):
    """The keep map must be complete and physically consistent."""

    def setUp(self):
        self.rows = [list(row) for row in lowest_keeps(3)]

    def test_accepts_a_complete_map(self):
        """A complete map parses to tuples."""
        parsed = cfr_prior.validate_rows(self.rows, 3)
        self.assertEqual(
            parsed[0],
            tuple(tuple(x) if isinstance(x, list) else x for x in self.rows[0]),
        )

    def test_rejects_each_defect(self):
        """Unknown role, bad keep, foreign keep, missing or repeated hand.

        Mutation caught (shown failing in a scratch copy): V1, skipping the
        coverage comparison, which lets a population that omits a hand
        produce a matrix missing that hand's deals.
        """
        hand = (0, 1, 1, 2, 2, 2)
        cases = [
            ([["Crib", hand, hand[:4]]] + self.rows[1:], "Unknown role"),
            ([[PONE, hand, hand[:3]]] + self.rows[1:], "four sorted"),
            ([[PONE, hand, list(reversed(hand[:4]))]] + self.rows[1:], "four sorted"),
            ([[PONE, [0, 0, 1, 1, 2, 2], [2, 2, 2, 2]]] + self.rows[1:], "not drawn"),
            (self.rows[1:], "every six-card hand"),
            (self.rows + self.rows[:1], "every six-card hand"),
        ]
        for rows, message in cases:
            with self.assertRaisesRegex(ValueError, message):
                cfr_prior.validate_rows(rows, 3)


class TestPopulation(unittest.TestCase):
    """The timing-free population writer and its reader."""

    def build(self, configuration=None, converged=False):
        """Run build_population on stubs whose refinement changes every keep.

        The analytical stub discards each hand's top two ranks and the
        refinement stub its bottom two, so the document shows which one it
        recorded.
        """
        context = stub_context()
        calls = {}

        def refine(analytical, args, hands, fixed_policies=None):
            calls["refine"] = (analytical, args, hands, fixed_policies)
            report = [{"outer_iteration": 1}]
            return stub_context(top=False), fixed_policies, report, converged

        def solve(*args):
            calls["solve"] = args
            return context

        with (
            patch.object(generator, "solve_initial_discard_policy", solve),
            patch.object(generator, "refine_discards", refine),
            redirect_stdout(io.StringIO()),
            patch("sys.stderr", io.StringIO()),
        ):
            if configuration is None:
                document = cfr_prior.build_population()
            else:
                document = cfr_prior.build_population(configuration)
        return document, calls

    def test_uses_the_generator_heuristic_fallback(self):
        """The configuration reaches the analytical start and refinement."""
        configuration = dict(cfr_prior.DEFAULT_CONFIGURATION, seed=7)
        document, calls = self.build(configuration)
        self.assertEqual(calls["solve"], (40, 2))
        _, args, hands, fixed = calls["refine"]
        self.assertEqual(
            (args.outer_iterations, args.policy_table_samples, args.seed), (2, 200, 7)
        )
        self.assertEqual(hands, get_canonical_hands())
        self.assertEqual(set(fixed), set(ROLES))
        self.assertEqual(document["configuration"], configuration)
        self.assertEqual(document["refinement"]["policy"], "legacy-heuristic")
        self.assertEqual(
            document["refinement"]["outer_iterations"], [{"outer_iteration": 1}]
        )
        self.assertFalse(document["converged"])
        self.assertTrue(self.build(converged=True)[0]["converged"])

    def test_records_the_refined_keeps(self):
        """The keeps are the refinement's, not the analytical start's.

        Mutation caught (shown failing in a scratch copy): R1, building the
        population from the analytical context instead of the refined one.
        """
        document, _ = self.build()
        for role, hand, keep in document["keeps"]:
            self.assertEqual(keep, hand[2:], (role, hand))

    def test_rows_are_sorted_dealer_then_pone(self):
        """Rows follow the research order, so keeps_sha256 stays comparable.

        Mutation caught (shown failing in a scratch copy): R2, writing the
        policy's rows in dictionary order rather than sorted.
        """
        document, _ = self.build()
        keys = [(role, hand) for role, hand, _ in document["keeps"]]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(keys[0], (DEALER, [0, 0, 0, 0, 1, 1]))
        self.assertEqual(keys[-1][0], PONE)

    def test_document_is_timing_free_and_byte_stable(self):
        """Two builds give identical bytes and no elapsed-time fields.

        Mutation caught (shown failing in a scratch copy): T1, recording an
        elapsed time as the research writer did, which changed the file
        digest on every run.
        """
        first, _ = self.build()
        second, _ = self.build()
        self.assertEqual(
            cfr_prior.encode_population(first), cfr_prior.encode_population(second)
        )
        self.assertFalse(any("seconds" in key for key in first))
        self.assertEqual(first["population_method"], cfr_prior.POPULATION_METHOD)

    def test_round_trips_through_the_reader(self):
        """The written document reads back with matching digests and weights."""
        document, _ = self.build()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "population.json"
            path.write_bytes(cfr_prior.encode_population(document))
            read, rows = cfr_prior.read_population(path)
        self.assertEqual(read, document)
        self.assertEqual(len(rows), 2 * 18_395)
        weight = math.comb(52, 6)
        self.assertEqual(
            document["six_hand_physical_weight_per_role"],
            {PONE: weight, DEALER: weight},
        )
        discard = generator.selected_discards_to_policy(
            stub_context(top=False).selected_discards
        )
        self.assertEqual(
            document["discard_policy_fingerprint"],
            generator.discard_keeps_fingerprint(discard),
        )

    def test_reader_rejects_tampering(self):
        """Digest, fingerprint and keep-population mismatches are refused."""
        rows = [
            list(map(lambda x: list(x) if isinstance(x, tuple) else x, row))
            for row in lowest_keeps(3)
        ]
        policy = generator.DiscardPolicy({(r, tuple(h)): tuple(k) for r, h, k in rows})
        good = {
            "keeps": rows,
            "keeps_sha256": cfr_prior.keeps_digest(rows),
            "discard_policy_fingerprint": generator.discard_keeps_fingerprint(policy),
        }
        swapped = [list(row) for row in rows]
        swapped[0] = [swapped[0][0], swapped[0][1], swapped[0][1][2:]]
        cases = [
            (dict(good, keeps_sha256="0" * 64), "digest"),
            (
                dict(good, keeps=swapped, keeps_sha256=cfr_prior.keeps_digest(swapped)),
                "fingerprint",
            ),
            (dict(good, keep_populations={PONE: {}, DEALER: {}}), "populations"),
            ({"keeps": rows}, "lacks"),
            (dict(good, population_method="other"), "Unknown population method"),
            (
                dict(good, six_hand_physical_weight_per_role={PONE: 0, DEALER: 0}),
                "weight totals",
            ),
            (dict(good, six_hand_physical_weight_per_role=None), "weight totals"),
        ]
        complete = dict(
            good,
            population_method=cfr_prior.POPULATION_METHOD,
            six_hand_physical_weight_per_role={PONE: 924, DEALER: 924},
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "population.json"
            path.write_text(json.dumps(good))
            self.assertEqual(len(cfr_prior.read_population(path, 3)[1]), len(rows))
            path.write_text(json.dumps(complete))
            self.assertEqual(cfr_prior.read_population(path, 3)[0], complete)
            for document, message in cases:
                path.write_text(json.dumps(document))
                with self.assertRaisesRegex(ValueError, message):
                    cfr_prior.read_population(path, 3)


class TestCommandLine(unittest.TestCase):
    """Both stages end to end, writing the Rust solve's prior format."""

    def test_population_then_prior(self):
        """The prior is 1820 x 1820 little-endian u64 and mixes 50/50."""
        context = stub_context()

        def refine(analytical, *_, fixed_policies=None):
            return analytical, fixed_policies, [], True

        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            population = folder / "population.json"
            with (
                patch.object(
                    generator, "solve_initial_discard_policy", return_value=context
                ),
                patch.object(generator, "refine_discards", refine),
                redirect_stdout(io.StringIO()),
                patch("sys.stderr", io.StringIO()),
            ):
                cfr_prior.main(
                    ["population", "--output", str(population), "--seed", "3"]
                )
            self.assertTrue(json.loads(population.read_text())["converged"])
            self.assertEqual(
                json.loads(population.read_text())["configuration"]["seed"], 3
            )
            paths = {
                name: folder / name
                for name in ("prior.bin", "matrix.bin", "prior.json")
            }
            with redirect_stdout(io.StringIO()) as printed:
                cfr_prior.main(
                    [
                        "prior",
                        "--population",
                        str(population),
                        "--output",
                        str(paths["prior.bin"]),
                        "--production-output",
                        str(paths["matrix.bin"]),
                        "--report",
                        str(paths["prior.json"]),
                    ]
                )
            report = json.loads(paths["prior.json"].read_text())
            self.assertEqual(json.loads(printed.getvalue()), report)
            prior_bytes = paths["prior.bin"].read_bytes()
            self.assertEqual(len(prior_bytes), KEYS * KEYS * 8)
            self.assertEqual(
                report["prior_sha256"], hashlib.sha256(prior_bytes).hexdigest()
            )
            self.assertEqual(
                report["production_sha256"],
                hashlib.sha256(paths["matrix.bin"].read_bytes()).hexdigest(),
            )
            self.assertFalse(list(folder.glob("*.partial")))
            prior = [
                int.from_bytes(prior_bytes[i : i + 8], "little")
                for i in range(0, len(prior_bytes), 8)
            ]
            production = cfr_prior.read_matrix(paths["matrix.bin"].read_bytes(), KEYS)
            uniform = cfr_prior.uniform_matrix()
            self.assertEqual(sum(prior), report["mixture_mass"])
            self.assertEqual(sum(production), math.comb(52, 6) * math.comb(46, 6))
            for cell in (0, KEYS + 5, 1234 * KEYS + 77, len(prior) - 1):
                expected = (
                    Fraction(uniform[cell], sum(uniform))
                    + Fraction(production[cell], sum(production))
                ) / 2
                self.assertEqual(Fraction(prior[cell], sum(prior)), expected)

    def test_prior_without_optional_outputs(self):
        """Only the prior is written when no other output is requested."""
        built = (b"m", b"p", {"prior_sha256": "x"})
        document = {"discard_policy_fingerprint": "f", "keeps_sha256": "k"}
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(cfr_prior, "read_population", return_value=(document, [])),
            patch.object(cfr_prior, "build_prior", return_value=built),
            redirect_stdout(io.StringIO()),
        ):
            output = Path(folder) / "prior.bin"
            cfr_prior.main(["prior", "--population", "unused", "--output", str(output)])
            self.assertEqual(output.read_bytes(), b"p")
            self.assertEqual(
                sorted(p.name for p in Path(folder).iterdir()), ["prior.bin"]
            )

    def test_rejects_non_positive_counts(self):
        """Iteration and sample counts must be positive; the seed need not be."""
        with patch("sys.stderr", io.StringIO()):
            for flag in ("--outer-iterations", "--policy-table-samples"):
                with self.assertRaises(SystemExit):
                    cfr_prior.parse_args(["population", "--output", "p", flag, "0"])
        args = cfr_prior.parse_args(["population", "--output", "p", "--seed", "-1"])
        self.assertEqual(args.seed, -1)

    def test_rejects_aliased_paths(self):
        """No output may be another output, the input, or a temporary name.

        Mutation caught (shown failing in a scratch copy): A1, dropping the
        check, so `--production-output` equal to `--output` silently leaves
        the production matrix where the Rust solve reads its prior.
        """
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            population = folder / "population.json"
            population.write_text("{}")
            linked = folder / "linked.json"
            linked.symlink_to(population)
            hard = folder / "hard.json"
            os.link(population, hard)
            prior = str(folder / "prior.bin")
            cases = [
                ["--output", prior, "--production-output", prior],
                ["--output", prior, "--report", prior],
                ["--output", str(population)],
                ["--output", str(linked)],
                ["--output", str(hard)],
                ["--output", str(folder / "x"), "--report", str(folder / "x.partial")],
                # Neither output exists yet, so only the real-path step sees it.
                [
                    "--output",
                    prior,
                    "--production-output",
                    str(folder / ".." / folder.name / "prior.bin"),
                ],
                ["--output", prior, "--production-output", str(folder / "PRIOR.bin")],
            ]
            document = {"discard_policy_fingerprint": "f", "keeps_sha256": "k"}
            with (
                patch.object(cfr_prior, "read_population", return_value=(document, [])),
                patch.object(cfr_prior, "build_prior", return_value=(b"m", b"p", {})),
                redirect_stdout(io.StringIO()),
            ):
                for extra in cases:
                    with self.assertRaisesRegex(ValueError, "different files"):
                        cfr_prior.main(
                            ["prior", "--population", str(population), *extra]
                        )
            self.assertEqual(population.read_text(), "{}")
            self.assertEqual(
                sorted(p.name for p in folder.iterdir()),
                ["hard.json", "linked.json", "population.json"],
            )


if __name__ == "__main__":
    unittest.main()
