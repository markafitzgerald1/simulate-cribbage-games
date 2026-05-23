"""Craig Hessel crib discard averages used for artifact comparisons.

The source table is rank-only and therefore has 91 discard pairs. It does not
distinguish suited from unsuited discards.

Source:
https://cribbage121.com/cardcombinations/discardtables.php
http://www.cribbageforum.com/YourCrib.htm
http://www.cribbageforum.com/OppCrib.htm

Cribbage 121 republishes comparison values from Hessel's discard tables for
"player" (own crib) and "opponent" (opponent's crib). In this repository's
artifact terminology, Dealer means discarding to your crib and Pone means
discarding to the opponent's crib.

The numeric averages are used here as factual reference data for comparison.
The surrounding Python code, tests, names, and repository organization are part
of this MPL-2.0 project, but this file does not claim copyright over the
underlying cribbage averages themselves.
"""

RANKS = "A23456789TJQK"


# Pair key -> {"Dealer": own crib average, "Pone": opponent crib average}
HESSEL_AVERAGES = {
    "AA": {"Dealer": 5.26, "Pone": 6.07},
    "A2": {"Dealer": 4.18, "Pone": 5.07},
    "A3": {"Dealer": 4.47, "Pone": 5.17},
    "A4": {"Dealer": 5.45, "Pone": 5.74},
    "A5": {"Dealer": 5.48, "Pone": 6.06},
    "A6": {"Dealer": 3.80, "Pone": 4.93},
    "A7": {"Dealer": 3.73, "Pone": 4.95},
    "A8": {"Dealer": 3.70, "Pone": 4.92},
    "A9": {"Dealer": 3.33, "Pone": 4.66},
    "AT": {"Dealer": 3.37, "Pone": 4.46},
    "AJ": {"Dealer": 3.65, "Pone": 4.72},
    "AQ": {"Dealer": 3.39, "Pone": 4.41},
    "AK": {"Dealer": 3.42, "Pone": 4.34},
    "22": {"Dealer": 5.67, "Pone": 6.43},
    "23": {"Dealer": 6.97, "Pone": 7.34},
    "24": {"Dealer": 4.51, "Pone": 5.44},
    "25": {"Dealer": 5.44, "Pone": 6.17},
    "26": {"Dealer": 3.87, "Pone": 5.13},
    "27": {"Dealer": 3.81, "Pone": 5.12},
    "28": {"Dealer": 3.58, "Pone": 5.03},
    "29": {"Dealer": 3.63, "Pone": 4.82},
    "2T": {"Dealer": 3.51, "Pone": 4.64},
    "2J": {"Dealer": 3.79, "Pone": 4.91},
    "2Q": {"Dealer": 3.52, "Pone": 4.60},
    "2K": {"Dealer": 3.55, "Pone": 4.53},
    "33": {"Dealer": 5.90, "Pone": 6.78},
    "34": {"Dealer": 4.88, "Pone": 6.10},
    "35": {"Dealer": 6.01, "Pone": 6.85},
    "36": {"Dealer": 3.72, "Pone": 4.92},
    "37": {"Dealer": 3.67, "Pone": 5.16},
    "38": {"Dealer": 3.84, "Pone": 5.08},
    "39": {"Dealer": 3.66, "Pone": 4.82},
    "3T": {"Dealer": 3.61, "Pone": 4.70},
    "3J": {"Dealer": 3.88, "Pone": 4.97},
    "3Q": {"Dealer": 3.62, "Pone": 4.66},
    "3K": {"Dealer": 3.66, "Pone": 4.59},
    "44": {"Dealer": 5.65, "Pone": 6.59},
    "45": {"Dealer": 6.54, "Pone": 7.46},
    "46": {"Dealer": 3.87, "Pone": 5.47},
    "47": {"Dealer": 3.74, "Pone": 4.91},
    "48": {"Dealer": 3.84, "Pone": 5.02},
    "49": {"Dealer": 3.69, "Pone": 4.75},
    "4T": {"Dealer": 3.62, "Pone": 4.55},
    "4J": {"Dealer": 3.89, "Pone": 4.80},
    "4Q": {"Dealer": 3.63, "Pone": 4.49},
    "4K": {"Dealer": 3.67, "Pone": 4.43},
    "55": {"Dealer": 8.95, "Pone": 9.39},
    "56": {"Dealer": 6.65, "Pone": 7.66},
    "57": {"Dealer": 6.04, "Pone": 7.08},
    "58": {"Dealer": 5.49, "Pone": 6.36},
    "59": {"Dealer": 5.47, "Pone": 6.22},
    "5T": {"Dealer": 6.68, "Pone": 7.46},
    "5J": {"Dealer": 7.04, "Pone": 7.75},
    "5Q": {"Dealer": 6.71, "Pone": 7.42},
    "5K": {"Dealer": 6.70, "Pone": 7.31},
    "66": {"Dealer": 5.74, "Pone": 7.17},
    "67": {"Dealer": 4.94, "Pone": 6.64},
    "68": {"Dealer": 4.70, "Pone": 6.05},
    "69": {"Dealer": 5.11, "Pone": 6.31},
    "6T": {"Dealer": 3.15, "Pone": 4.41},
    "6J": {"Dealer": 3.40, "Pone": 4.61},
    "6Q": {"Dealer": 3.08, "Pone": 4.29},
    "6K": {"Dealer": 3.13, "Pone": 4.25},
    "77": {"Dealer": 5.98, "Pone": 7.25},
    "78": {"Dealer": 6.58, "Pone": 7.88},
    "79": {"Dealer": 4.06, "Pone": 5.46},
    "7T": {"Dealer": 3.10, "Pone": 4.44},
    "7J": {"Dealer": 3.43, "Pone": 4.73},
    "7Q": {"Dealer": 3.17, "Pone": 4.44},
    "7K": {"Dealer": 3.21, "Pone": 4.38},
    "88": {"Dealer": 5.42, "Pone": 6.76},
    "89": {"Dealer": 4.74, "Pone": 5.97},
    "8T": {"Dealer": 3.86, "Pone": 5.02},
    "8J": {"Dealer": 3.39, "Pone": 4.65},
    "8Q": {"Dealer": 3.16, "Pone": 4.38},
    "8K": {"Dealer": 3.20, "Pone": 4.31},
    "99": {"Dealer": 5.09, "Pone": 6.44},
    "9T": {"Dealer": 4.27, "Pone": 5.52},
    "9J": {"Dealer": 3.98, "Pone": 4.98},
    "9Q": {"Dealer": 2.97, "Pone": 4.14},
    "9K": {"Dealer": 3.05, "Pone": 4.13},
    "TT": {"Dealer": 4.73, "Pone": 6.11},
    "TJ": {"Dealer": 4.64, "Pone": 5.60},
    "TQ": {"Dealer": 3.36, "Pone": 4.65},
    "TK": {"Dealer": 2.86, "Pone": 3.99},
    "JJ": {"Dealer": 5.37, "Pone": 6.56},
    "JQ": {"Dealer": 4.90, "Pone": 5.55},
    "JK": {"Dealer": 4.07, "Pone": 4.89},
    "QQ": {"Dealer": 4.66, "Pone": 5.89},
    "QK": {"Dealer": 3.50, "Pone": 4.56},
    "KK": {"Dealer": 4.62, "Pone": 5.72},
}
