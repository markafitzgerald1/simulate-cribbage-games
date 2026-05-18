import argparse
import csv
import json
import math
import sys
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple


RANKS = "A23456789TJQK"
SUITED_WEIGHT = 0.25
UNSUITED_WEIGHT = 0.75


StatsByCut = Mapping[str, Mapping[str, float]]
RoleData = Mapping[str, StatsByCut]
TableData = Mapping[str, RoleData]
Estimate = Mapping[str, float]


def mean(values: Iterable[float]) -> Optional[float]:
    values_list = list(values)
    if not values_list:
        return None
    return sum(values_list) / len(values_list)


def mean_cut_stat(cut_stats: StatsByCut, statistic: str) -> Optional[float]:
    return mean(stats[statistic] for stats in cut_stats.values() if statistic in stats)


def pool_cut_estimate(cut_stats: StatsByCut) -> Optional[Estimate]:
    stats_with_mu = [stats for stats in cut_stats.values() if "mu" in stats]
    if not stats_with_mu:
        return None

    if all("n" in stats for stats in stats_with_mu):
        total_n = sum(int(stats["n"]) for stats in stats_with_mu)
        total = sum(stats["mu"] * stats["n"] for stats in stats_with_mu)
        sum_squares = 0.0
        for stats in stats_with_mu:
            n = int(stats["n"])
            mu = stats["mu"]
            se = stats.get("se", 0.0)
            sample_variance = se * se * n
            sum_squares += (n - 1) * sample_variance + n * mu * mu

        mu = total / total_n
        if total_n == 1:
            se = 0.0
        else:
            variance = (sum_squares - total_n * mu * mu) / (total_n - 1)
            se = math.sqrt(max(variance, 0.0)) / math.sqrt(total_n)
        return {"n": total_n, "mu": mu, "se": se}

    mu_values = [stats["mu"] for stats in stats_with_mu]
    se_values = [stats.get("se", 0.0) for stats in stats_with_mu]
    return {
        "n": len(stats_with_mu),
        "mu": sum(mu_values) / len(mu_values),
        "se": math.sqrt(sum(se * se for se in se_values)) / len(se_values),
    }


def combine_estimates(
    weighted_estimates: Sequence[Tuple[float, Estimate]]
) -> Optional[Estimate]:
    estimates = [
        (weight, estimate) for weight, estimate in weighted_estimates if estimate
    ]
    if not estimates:
        return None

    weight_total = sum(weight for weight, _estimate in estimates)
    normalized = [(weight / weight_total, estimate) for weight, estimate in estimates]
    mu = sum(weight * estimate["mu"] for weight, estimate in normalized)
    se = math.sqrt(
        sum((weight * estimate.get("se", 0.0)) ** 2 for weight, estimate in normalized)
    )
    n = sum(weight * estimate.get("n", 0.0) for weight, estimate in normalized)
    return {"n": n, "mu": mu, "se": se}


def canonical_key(rank_1: str, rank_2: str, suit_status: str) -> str:
    return f"{rank_1}_{rank_2}_{suit_status}"


def get_pair_estimate(
    data: TableData,
    rank_1: str,
    rank_2: str,
    role: str,
    suit_weighting: str,
) -> Optional[Estimate]:
    if rank_1 == rank_2:
        if suit_weighting == "suited-only":
            return None
        key = canonical_key(rank_1, rank_2, "Unsuited")
        role_data = data.get(key, {}).get(role)
        return pool_cut_estimate(role_data) if role_data else None

    suited_key = canonical_key(rank_1, rank_2, "Suited")
    unsuited_key = canonical_key(rank_1, rank_2, "Unsuited")
    suited_data = data.get(suited_key, {}).get(role)
    unsuited_data = data.get(unsuited_key, {}).get(role)
    suited = pool_cut_estimate(suited_data) if suited_data else None
    unsuited = pool_cut_estimate(unsuited_data) if unsuited_data else None

    if suit_weighting == "suited-only":
        return suited
    if suit_weighting == "unsuited-only":
        return unsuited
    if suited is None:
        return unsuited
    if unsuited is None:
        return suited
    if suit_weighting == "unweighted":
        return combine_estimates(((0.5, suited), (0.5, unsuited)))
    return combine_estimates(((SUITED_WEIGHT, suited), (UNSUITED_WEIGHT, unsuited)))


def get_pair_stat(
    data: TableData,
    rank_1: str,
    rank_2: str,
    role: str,
    statistic: str,
    suit_weighting: str,
) -> Optional[float]:
    estimate = get_pair_estimate(data, rank_1, rank_2, role, suit_weighting)
    if not estimate:
        return None
    return estimate.get(statistic)


def build_table(
    data: TableData,
    role: str,
    suit_weighting: str,
) -> List[List[Optional[Estimate]]]:
    table: List[List[Optional[Estimate]]] = []
    for row_index, row_rank in enumerate(RANKS):
        row: List[Optional[Estimate]] = []
        for col_index, col_rank in enumerate(RANKS):
            rank_1, rank_2 = (
                (row_rank, col_rank) if row_index <= col_index else (col_rank, row_rank)
            )
            row.append(
                get_pair_estimate(
                    data,
                    rank_1,
                    rank_2,
                    role,
                    suit_weighting,
                )
            )
        table.append(row)
    return table


def format_value(
    estimate: Optional[Estimate], statistic: str, precision: int, show_se: bool
) -> str:
    if not estimate or statistic not in estimate:
        return ""
    value = estimate[statistic]
    if show_se and statistic == "mu":
        return f"{value:.{precision}f} +/- {estimate['se']:.{precision}f}"
    if statistic == "n":
        return str(int(round(value)))
    return f"{value:.{precision}f}"


def print_markdown_table(
    table: Sequence[Sequence[Optional[Estimate]]],
    statistic: str,
    precision: int,
    show_se: bool,
) -> None:
    formatted_rows = [
        [format_value(value, statistic, precision, show_se) for value in row]
        for row in table
    ]
    headers = ["", *RANKS]
    widths = [3]
    for index, header in enumerate(headers[1:]):
        column_values = [row[index] for row in formatted_rows if index < len(row)]
        widths.append(max(len(header), 3, *[len(value) for value in column_values]))

    print(
        "| "
        + " | ".join(header.rjust(width) for header, width in zip(headers, widths))
        + " |"
    )
    print("| " + " | ".join("-" * width for width in widths) + " |")
    for rank, row in zip(RANKS, formatted_rows):
        values = [
            rank.rjust(widths[0]),
            *[value.rjust(width) for value, width in zip(row, widths[1:])],
        ]
        print("| " + " | ".join(values) + " |")


def print_csv_table(
    table: Sequence[Sequence[Optional[Estimate]]],
    statistic: str,
    precision: int,
    show_se: bool,
) -> None:
    writer = csv.writer(sys.stdout)
    writer.writerow(["", *RANKS])
    for rank, row in zip(RANKS, table):
        writer.writerow(
            [
                rank,
                *[format_value(value, statistic, precision, show_se) for value in row],
            ]
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render expected crib points JSON as a 13x13 discard table."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="expected_crib_points.json",
        help="Path to expected_crib_points.json.",
    )
    parser.add_argument(
        "--role",
        choices=("Dealer", "Pone"),
        default="Dealer",
        help="Dealer means discarding to your crib; Pone means discarding to opponent's crib.",
    )
    parser.add_argument(
        "--statistic",
        choices=("mu", "se", "n"),
        default="mu",
        help="Statistic to print from each summarized discard value.",
    )
    parser.add_argument(
        "--show-se",
        action="store_true",
        help="Print each mean as 'mu +/- se'. Only applies with --statistic mu.",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "csv"),
        default="markdown",
        help="Output format.",
    )
    parser.add_argument(
        "--precision",
        type=int,
        default=2,
        help="Digits after the decimal point.",
    )
    parser.add_argument(
        "--suit-weighting",
        choices=("actual", "unweighted", "suited-only", "unsuited-only"),
        default="actual",
        help=(
            "How to combine suited and unsuited different-rank discards. "
            "actual uses 25%% suited and 75%% unsuited."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with open(args.path, "r") as table_file:
        data = json.load(table_file)

    table = build_table(data, args.role, args.suit_weighting)
    if args.format == "csv":
        print_csv_table(table, args.statistic, args.precision, args.show_se)
    else:
        print_markdown_table(table, args.statistic, args.precision, args.show_se)


if __name__ == "__main__":  # pragma: no cover
    main()
