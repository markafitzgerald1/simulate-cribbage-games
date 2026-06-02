import argparse
import csv
import json
import math
import os
import sys
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, TypedDict

if __package__ in (None, ""):  # pragma: no cover
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The imports below follow the script-mode path shim.
# pylint: disable=wrong-import-position
from artifact_pipeline.hessel import HESSEL_AVERAGES, RANKS
from artifact_pipeline.summarize_table import TableData, get_pair_estimate


class ComparisonRow(TypedDict):
    pair: str
    role: str
    generated: float
    hessel: float
    delta: float
    abs_delta: float
    se: float
    z_score: float
    n: float


PAIR_HEADER = "pair"
ROLE_HEADER = "role"
TABLE_STATS = ("delta", "z-score", "generated", "hessel", "se", "n")


def iter_rank_pairs() -> Iterable[str]:
    for row_index, row_rank in enumerate(RANKS):
        for col_rank in RANKS[: row_index + 1]:
            yield f"{col_rank}{row_rank}"


def compare_to_hessel(
    data: TableData,
    roles: Sequence[str],
    suit_weighting: str,
) -> List[ComparisonRow]:
    rows: List[ComparisonRow] = []
    for pair in iter_rank_pairs():
        rank_1, rank_2 = pair[0], pair[1]
        for role in roles:
            estimate = get_pair_estimate(data, rank_1, rank_2, role, suit_weighting)
            if estimate is None:
                continue
            hessel = HESSEL_AVERAGES[pair][role]
            delta = estimate["mu"] - hessel
            se = estimate.get("se", 0.0)
            if se:
                z_score = abs(delta) / se
            else:
                z_score = 0.0 if abs(delta) < 1e-9 else math.inf
            rows.append(
                {
                    "pair": pair,
                    "role": role,
                    "generated": estimate["mu"],
                    "hessel": hessel,
                    "delta": delta,
                    "abs_delta": abs(delta),
                    "se": se,
                    "z_score": z_score,
                    "n": estimate.get("n", 0.0),
                }
            )
    return rows


def summarize_rows(rows: Sequence[ComparisonRow]) -> Dict[str, float]:
    if not rows:
        return {
            "count": 0,
            "mean_delta": 0.0,
            "mean_abs_delta": 0.0,
            "max_abs_delta": 0.0,
            "rmse": 0.0,
            "max_z_score": 0.0,
        }

    deltas = [row["delta"] for row in rows]
    abs_deltas = [row["abs_delta"] for row in rows]
    z_scores = [row["z_score"] for row in rows]
    return {
        "count": float(len(rows)),
        "mean_delta": sum(deltas) / len(deltas),
        "mean_abs_delta": sum(abs_deltas) / len(abs_deltas),
        "max_abs_delta": max(abs_deltas),
        "rmse": math.sqrt(sum(delta * delta for delta in deltas) / len(deltas)),
        "max_z_score": max(z_scores),
    }


def sorted_rows(rows: Sequence[ComparisonRow], sort_key: str) -> List[ComparisonRow]:
    if sort_key == "abs-delta":
        return sorted(rows, key=lambda row: row["abs_delta"], reverse=True)
    if sort_key == "z-score":
        return sorted(rows, key=lambda row: row["z_score"], reverse=True)
    return list(rows)


def rows_by_pair_and_role(
    rows: Sequence[ComparisonRow],
) -> Mapping[Tuple[str, str], ComparisonRow]:
    return {(row["pair"], row["role"]): row for row in rows}


def format_float(value: float, precision: int) -> str:
    if math.isinf(value):
        return "inf"
    return f"{value:.{precision}f}"


def print_summary(summary: Mapping[str, float], precision: int) -> None:
    print(
        "Summary: "
        f"count={int(summary['count'])}, "
        f"mean_delta={format_float(summary['mean_delta'], precision)}, "
        f"mean_abs_delta={format_float(summary['mean_abs_delta'], precision)}, "
        f"max_abs_delta={format_float(summary['max_abs_delta'], precision)}, "
        f"rmse={format_float(summary['rmse'], precision)}, "
        f"max_z_score={format_float(summary['max_z_score'], precision)}"
    )


def row_value(row: ComparisonRow, statistic: str, precision: int) -> str:
    if statistic == "z-score":
        return format_float(row["z_score"], precision)
    if statistic == "n":
        return str(int(round(row["n"])))
    if statistic == "generated":
        return format_float(row["generated"], precision)
    if statistic == "hessel":
        return format_float(row["hessel"], precision)
    if statistic == "se":
        return format_float(row["se"], precision)
    return format_float(row["delta"], precision)


def print_markdown_table_line(values: Sequence[str], widths: Sequence[int]) -> None:
    cells = [value.rjust(width) for value, width in zip(values, widths)]
    print("| " + " | ".join(cells) + " |")


def markdown_rule(widths: Sequence[int]) -> str:
    return "| " + " | ".join("-" * width for width in widths) + " |"


def build_markdown_table_rows(
    rows: Sequence[ComparisonRow],
    role: str,
    statistic: str,
    precision: int,
) -> List[List[str]]:
    indexed_rows = rows_by_pair_and_role(rows)
    table_rows: List[List[str]] = []
    for row_index, row_rank in enumerate(RANKS):
        values = [row_rank]
        for col_index, col_rank in enumerate(RANKS):
            if col_index > row_index:
                values.append("")
                continue
            pair = f"{col_rank}{row_rank}"
            row = indexed_rows.get((pair, role))
            values.append(row_value(row, statistic, precision) if row else "")
        table_rows.append(values)
    return table_rows


def print_markdown_rows(rows: Sequence[ComparisonRow], precision: int) -> None:
    headers = [PAIR_HEADER, ROLE_HEADER, "generated", "hessel", "delta", "se", "z", "n"]
    print("| " + " | ".join(headers) + " |")
    print("| " + " | ".join("---" for _header in headers) + " |")
    for row in rows:
        print("| " + " | ".join(row_fields(row, precision)) + " |")


def row_fields(row: ComparisonRow, precision: int) -> List[str]:
    return [
        row["pair"],
        row["role"],
        format_float(row["generated"], precision),
        format_float(row["hessel"], precision),
        format_float(row["delta"], precision),
        format_float(row["se"], precision),
        format_float(row["z_score"], precision),
        str(int(round(row["n"]))),
    ]


def print_markdown_table(
    rows: Sequence[ComparisonRow],
    roles: Sequence[str],
    statistic: str,
    precision: int,
) -> None:
    headers = ["", *RANKS]
    for role in roles:
        print(f"{role} {statistic}")
        table_rows = build_markdown_table_rows(rows, role, statistic, precision)
        widths = [
            max(len(value) for value in column_values)
            for column_values in zip(headers, *table_rows)
        ]
        print_markdown_table_line(headers, widths)
        print(markdown_rule(widths))
        for table_row in table_rows:
            print_markdown_table_line(table_row, widths)
        print()


def print_csv(rows: Sequence[ComparisonRow], precision: int) -> None:
    writer = csv.writer(sys.stdout)
    writer.writerow(
        [PAIR_HEADER, ROLE_HEADER, "generated", "hessel", "delta", "se", "z", "n"]
    )
    for row in rows:
        writer.writerow(row_fields(row, precision))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare expected crib points JSON against Hessel averages."
    )
    parser.add_argument("path", help="Path to expected_crib_points JSON.")
    parser.add_argument(
        "--role",
        choices=("Dealer", "Pone", "both"),
        default="both",
        help="Dealer is own crib; Pone is opponent's crib.",
    )
    parser.add_argument(
        "--suit-weighting",
        choices=("actual", "unweighted", "suited-only", "unsuited-only"),
        default="actual",
        help="How to combine generated suited and unsuited estimates.",
    )
    parser.add_argument(
        "--sort",
        choices=("rank", "abs-delta", "z-score"),
        default="rank",
        help="Output row ordering.",
    )
    parser.add_argument(
        "--precision",
        type=int,
        default=3,
        help="Digits after the decimal point.",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "csv"),
        default="markdown",
        help="Comparison report format.",
    )
    parser.add_argument(
        "--view",
        choices=("table", "rows"),
        default="table",
        help="Markdown view. CSV output is always row-oriented.",
    )
    parser.add_argument(
        "--table-statistic",
        choices=TABLE_STATS,
        default="delta",
        help="Statistic to print in Markdown table view.",
    )
    parser.add_argument(
        "--max-abs-delta",
        type=float,
        help="Exit non-zero if any absolute delta is greater than this value.",
    )
    parser.add_argument(
        "--max-z-score",
        type=float,
        help="Exit non-zero if any abs(delta) / se is greater than this value.",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Do not fail the comparison if the table is incomplete.",
    )
    return parser.parse_args()


def roles_from_arg(role: str) -> Sequence[str]:
    if role == "both":
        return ("Dealer", "Pone")
    return (role,)


def threshold_failed(
    summary: Mapping[str, float],
    max_abs_delta: Optional[float],
    max_z_score: Optional[float],
    expected_count: int = 91,
) -> bool:
    if summary.get("count", 0.0) < expected_count:
        return True
    return (max_abs_delta is not None and summary["max_abs_delta"] > max_abs_delta) or (
        max_z_score is not None and summary["max_z_score"] > max_z_score
    )


def main() -> None:
    args = parse_args()
    with open(args.path, "r", encoding="utf-8") as table_file:
        data = json.load(table_file)

    roles = roles_from_arg(args.role)
    rows = sorted_rows(
        compare_to_hessel(data, roles, args.suit_weighting),
        args.sort,
    )
    summary = summarize_rows(rows)

    if args.format == "csv":
        print_csv(rows, args.precision)
    elif args.view == "rows":
        print_markdown_rows(rows, args.precision)
        print_summary(summary, args.precision)
    else:
        print_markdown_table(
            rows,
            roles,
            args.table_statistic,
            args.precision,
        )
        print_summary(summary, args.precision)

    pairs_per_role = 78 if args.suit_weighting == "suited-only" else 91
    expected_count = 0 if args.allow_incomplete else (pairs_per_role * len(roles))
    if threshold_failed(
        summary, args.max_abs_delta, args.max_z_score, expected_count=expected_count
    ):
        raise SystemExit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
