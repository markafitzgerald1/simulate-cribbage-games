"""Curated Cribbage Pro pegging averages used for artifact sanity checks.

A small, representative sample (32 of the 1820 hands, not the full table) of the
rank-only expected pegging values published by Cribbage Pro (Fuller Systems,
Inc.) on its public pegging-quiz page. The page serves these values to any
browser as client-side JavaScript:

https://www.cribbagepro.net/pegging_quiz/pegging_quiz.html
https://www.cribbagepro.net/pegging_quiz/pegging_data.js

Retrieved 2026-06-27. Each entry lists four expected pegging totals for a kept
four-card hand. In this repository's terminology they are, in order, the points
the keeper pegs as Pone, the points the opponent pegs while the keeper is Pone,
the points the keeper pegs as Dealer, and the points the opponent pegs while the
keeper is Dealer.

These numeric averages are facts, used here only as third-party reference data
for an optional validation comparison against this project's independently
simulated table. They are re-expressed in this project's own canonical-hand keys
and seat order rather than copied in Cribbage Pro's file format, and only a small
representative sample is kept. The surrounding Python code, tests, names, and
repository organization are part of this MPL-2.0 project, but this file does not
claim copyright over the underlying cribbage averages themselves.
"""

RETRIEVED = "2026-06-27"

# Canonical kept-hand key -> (pone_player, pone_opponent, dealer_player,
# dealer_opponent) expected pegging points.
CRIBBAGE_PRO_PEGGING_SAMPLE = {
    "A_A_A_A": (0.72, 1.99, 2.23, 1.42),
    "5_5_5_5": (0.36, 4.32, 2.76, 1.74),
    "T_T_T_T": (1.04, 3.31, 2.5, 2.47),
    "K_K_K_K": (1.05, 3.05, 2.54, 2.16),
    "2_3_3_3": (3.84, 3.12, 3.29, 2.07),
    "A_5_5_5": (2.24, 3.06, 3.23, 2.25),
    "5_T_T_T": (2.01, 3.19, 2.85, 2.05),
    "A_2_3_4": (3.07, 3.6, 3.93, 2.48),
    "3_4_5_6": (2.15, 3.92, 4.76, 2.46),
    "4_5_6_7": (2.36, 3.9, 4.99, 2.41),
    "6_7_8_9": (1.95, 3.61, 3.72, 2.13),
    "7_8_9_T": (1.66, 3.7, 3.54, 2.33),
    "T_J_Q_K": (1.48, 3.82, 2.74, 2.72),
    "3_4_5_7": (2.32, 3.68, 4.46, 2.46),
    "A_A_2_2": (2.45, 2.65, 3.87, 1.93),
    "4_4_5_5": (3.01, 3.7, 4.97, 2.34),
    "5_5_6_6": (2.66, 3.91, 5.36, 2.16),
    "7_7_8_8": (2.07, 3.03, 3.18, 2.11),
    "5_5_5_T": (1.48, 3.59, 3.5, 2.03),
    "6_9_T_K": (1.86, 3.56, 2.89, 2.32),
    "4_5_6_K": (1.81, 3.61, 4.21, 2.11),
    "9_T_K_K": (1.98, 3.57, 2.71, 2.62),
    "T_T_J_K": (1.97, 3.62, 2.74, 2.68),
    "J_Q_K_K": (1.77, 3.63, 2.55, 2.5),
    "8_9_T_J": (1.79, 4.01, 3.54, 2.58),
    "A_3_6_9": (2.05, 3.29, 3.2, 1.98),
    "2_4_7_9": (2.05, 3.42, 3.96, 1.97),
    "A_4_8_K": (1.91, 3.04, 3.28, 1.92),
    "2_6_9_Q": (1.71, 3.38, 3.07, 1.74),
    "3_7_T_K": (1.63, 3.41, 2.95, 2.52),
    "A_2_8_9": (2.18, 3.62, 3.77, 2.08),
    "5_6_7_8": (2.06, 3.98, 4.41, 2.34),
}
