from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


SUMMARY_PATH = Path("backtest_summary.csv")
OUTPUT_PATH = Path("ranked_configs_aggregated.csv")
ACTIVITY_OUTPUT_PATH = Path("ranked_configs_with_activity_filter.csv")
TOP_N = 10
GROUP_FIELDS = [
    "short_window",
    "long_window",
    "stop_loss_pct",
    "take_profit_pct",
    "position_size_pct",
    "max_drawdown_limit_pct",
]
METRIC_FIELDS = [
    "return_pct",
    "profit_factor",
    "max_drawdown_pct",
]
REQUIRED_FIELDS = GROUP_FIELDS + METRIC_FIELDS


def parse_float(value: Any) -> float | None:
    raw = str(value or "").strip().lower()
    if raw in {"", "nan", "none", "null"}:
        return None
    if raw in {"inf", "+inf", "infinity", "+infinity", "-inf", "-infinity"}:
        return None
    try:
        number = float(raw)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def fmt_float(value: float | None, decimals: int = 4) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}"


def load_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"No se encontro el archivo: {path}")

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        raise ValueError(f"El archivo {path} no tiene filas de datos.")

    missing_cols = [col for col in REQUIRED_FIELDS if col not in (reader.fieldnames or [])]
    if missing_cols:
        raise ValueError(f"Faltan columnas requeridas en {path}: {', '.join(missing_cols)}")

    return rows


def safe_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def compute_trade_activity_score(closed_trades: float | None) -> float:
    if closed_trades is None or closed_trades <= 0:
        return 0.0
    if closed_trades < 3:
        return 0.5
    return 1.0


def build_group_key(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(str(row.get(field, "")).strip() for field in GROUP_FIELDS)


def aggregate_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[build_group_key(row)].append(row)

    aggregated: list[dict[str, Any]] = []

    for key, group_rows in grouped.items():
        returns = [
            value
            for value in (parse_float(row.get("return_pct")) for row in group_rows)
            if value is not None
        ]
        profit_factors = [
            value
            for value in (parse_float(row.get("profit_factor")) for row in group_rows)
            if value is not None
        ]
        drawdowns = [
            value
            for value in (parse_float(row.get("max_drawdown_pct")) for row in group_rows)
            if value is not None
        ]
        closed_trades = [
            value for value in (parse_float(row.get("closed_trades")) for row in group_rows) if value is not None
        ]

        avg_return = safe_mean(returns)
        avg_profit_factor = safe_mean(profit_factors)
        avg_drawdown = safe_mean(drawdowns)
        avg_closed_trades = safe_mean(closed_trades)
        activity_score = compute_trade_activity_score(avg_closed_trades)

        aggregated_row: dict[str, Any] = dict(zip(GROUP_FIELDS, key))
        aggregated_row.update(
            {
                "count": len(group_rows),
                "avg_return_pct": avg_return,
                "avg_profit_factor": avg_profit_factor,
                "avg_drawdown": avg_drawdown,
                "closed_trades": avg_closed_trades,
                "trade_activity_score": activity_score,
                "adjusted_return": (avg_return * activity_score) if avg_return is not None else None,
                "adjusted_profit_factor": (avg_profit_factor * activity_score)
                if avg_profit_factor is not None
                else None,
                "win_rate_pct": (sum(1 for value in returns if value > 0) / len(returns) * 100)
                if returns
                else None,
                "best_return": max(returns) if returns else None,
                "worst_return": min(returns) if returns else None,
            }
        )
        aggregated.append(aggregated_row)

    return aggregated


def passes_filters(row: dict[str, Any]) -> bool:
    count = row.get("count", 0)
    avg_profit_factor = row.get("avg_profit_factor")
    return count >= 2 and avg_profit_factor is not None and avg_profit_factor > 1


def rank_key(row: dict[str, Any]) -> tuple[float, float, float]:
    avg_return = row.get("avg_return_pct")
    avg_profit_factor = row.get("avg_profit_factor")
    avg_drawdown = row.get("avg_drawdown")

    return (
        avg_return if avg_return is not None else float("-inf"),
        avg_profit_factor if avg_profit_factor is not None else float("-inf"),
        -(avg_drawdown if avg_drawdown is not None else float("inf")),
    )


def rank_key_with_activity(row: dict[str, Any]) -> tuple[float, float, float]:
    adjusted_return = row.get("adjusted_return")
    adjusted_profit_factor = row.get("adjusted_profit_factor")
    avg_drawdown = row.get("avg_drawdown")

    return (
        adjusted_return if adjusted_return is not None else float("-inf"),
        adjusted_profit_factor if adjusted_profit_factor is not None else float("-inf"),
        -(avg_drawdown if avg_drawdown is not None else float("inf")),
    )


def print_top(rows: list[dict[str, Any]], top_n: int = TOP_N) -> None:
    headers = [
        "short_window",
        "long_window",
        "stop_loss_pct",
        "take_profit_pct",
        "position_size_pct",
        "max_drawdown_limit_pct",
        "count",
        "avg_return_pct",
        "avg_profit_factor",
        "avg_drawdown",
        "win_rate_pct",
        "best_return",
        "worst_return",
    ]

    print(f"\nTop {top_n} configuraciones agregadas:")
    print(" | ".join(headers))
    print("-" * 200)

    for row in rows[:top_n]:
        line = " | ".join(
            [
                str(row.get("short_window", "N/A")),
                str(row.get("long_window", "N/A")),
                str(row.get("stop_loss_pct", "N/A")),
                str(row.get("take_profit_pct", "N/A")),
                str(row.get("position_size_pct", "N/A")),
                str(row.get("max_drawdown_limit_pct", "N/A")),
                str(row.get("count", "N/A")),
                fmt_float(row.get("avg_return_pct")),
                fmt_float(row.get("avg_profit_factor")),
                fmt_float(row.get("avg_drawdown")),
                fmt_float(row.get("win_rate_pct")),
                fmt_float(row.get("best_return")),
                fmt_float(row.get("worst_return")),
            ]
        )
        print(line)


def print_top_with_activity(rows: list[dict[str, Any]], top_n: int = TOP_N) -> None:
    headers = [
        "short_window",
        "long_window",
        "stop_loss_pct",
        "take_profit_pct",
        "position_size_pct",
        "max_drawdown_limit_pct",
        "count",
        "closed_trades",
        "trade_activity_score",
        "adjusted_return",
        "adjusted_profit_factor",
        "avg_drawdown",
    ]

    print(f"\nTop {top_n} configuraciones (filtro de actividad):")
    print(" | ".join(headers))
    print("-" * 200)

    for row in rows[:top_n]:
        line = " | ".join(
            [
                str(row.get("short_window", "N/A")),
                str(row.get("long_window", "N/A")),
                str(row.get("stop_loss_pct", "N/A")),
                str(row.get("take_profit_pct", "N/A")),
                str(row.get("position_size_pct", "N/A")),
                str(row.get("max_drawdown_limit_pct", "N/A")),
                str(row.get("count", "N/A")),
                fmt_float(row.get("closed_trades")),
                fmt_float(row.get("trade_activity_score")),
                fmt_float(row.get("adjusted_return")),
                fmt_float(row.get("adjusted_profit_factor")),
                fmt_float(row.get("avg_drawdown")),
            ]
        )
        print(line)


def print_summary(rows: list[dict[str, Any]]) -> None:
    avg_return = safe_mean(
        [value for value in (row.get("avg_return_pct") for row in rows) if value is not None]
    )
    avg_profit_factor = safe_mean(
        [value for value in (row.get("avg_profit_factor") for row in rows) if value is not None]
    )
    avg_drawdown = safe_mean(
        [value for value in (row.get("avg_drawdown") for row in rows) if value is not None]
    )

    print("\nResumen final de configuraciones seleccionadas:")
    print(f"- Promedio global de return: {fmt_float(avg_return)}")
    print(f"- Promedio global de profit_factor: {fmt_float(avg_profit_factor)}")
    print(f"- Promedio global de drawdown: {fmt_float(avg_drawdown)}")


def export_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "short_window",
        "long_window",
        "stop_loss_pct",
        "take_profit_pct",
        "position_size_pct",
        "max_drawdown_limit_pct",
        "count",
        "avg_return_pct",
        "avg_profit_factor",
        "avg_drawdown",
        "win_rate_pct",
        "best_return",
        "worst_return",
    ]

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "short_window": row.get("short_window"),
                    "long_window": row.get("long_window"),
                    "stop_loss_pct": row.get("stop_loss_pct"),
                    "take_profit_pct": row.get("take_profit_pct"),
                    "position_size_pct": row.get("position_size_pct"),
                    "max_drawdown_limit_pct": row.get("max_drawdown_limit_pct"),
                    "count": row.get("count"),
                    "avg_return_pct": fmt_float(row.get("avg_return_pct")),
                    "avg_profit_factor": fmt_float(row.get("avg_profit_factor")),
                    "avg_drawdown": fmt_float(row.get("avg_drawdown")),
                    "win_rate_pct": fmt_float(row.get("win_rate_pct")),
                    "best_return": fmt_float(row.get("best_return")),
                    "worst_return": fmt_float(row.get("worst_return")),
                }
            )


def export_rows_with_activity(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "short_window",
        "long_window",
        "stop_loss_pct",
        "take_profit_pct",
        "position_size_pct",
        "max_drawdown_limit_pct",
        "count",
        "closed_trades",
        "trade_activity_score",
        "avg_return_pct",
        "avg_profit_factor",
        "adjusted_return",
        "adjusted_profit_factor",
        "avg_drawdown",
        "win_rate_pct",
        "best_return",
        "worst_return",
    ]

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "short_window": row.get("short_window"),
                    "long_window": row.get("long_window"),
                    "stop_loss_pct": row.get("stop_loss_pct"),
                    "take_profit_pct": row.get("take_profit_pct"),
                    "position_size_pct": row.get("position_size_pct"),
                    "max_drawdown_limit_pct": row.get("max_drawdown_limit_pct"),
                    "count": row.get("count"),
                    "closed_trades": fmt_float(row.get("closed_trades")),
                    "trade_activity_score": fmt_float(row.get("trade_activity_score")),
                    "avg_return_pct": fmt_float(row.get("avg_return_pct")),
                    "avg_profit_factor": fmt_float(row.get("avg_profit_factor")),
                    "adjusted_return": fmt_float(row.get("adjusted_return")),
                    "adjusted_profit_factor": fmt_float(row.get("adjusted_profit_factor")),
                    "avg_drawdown": fmt_float(row.get("avg_drawdown")),
                    "win_rate_pct": fmt_float(row.get("win_rate_pct")),
                    "best_return": fmt_float(row.get("best_return")),
                    "worst_return": fmt_float(row.get("worst_return")),
                }
            )


def main() -> None:
    rows = load_rows(SUMMARY_PATH)
    aggregated = aggregate_rows(rows)
    selected = sorted((row for row in aggregated if passes_filters(row)), key=rank_key, reverse=True)
    selected_with_activity = sorted(
        (row for row in aggregated if passes_filters(row)),
        key=rank_key_with_activity,
        reverse=True,
    )

    print(f"Cantidad total de configuraciones unicas: {len(aggregated)}")
    print(f"Cantidad que pasan el filtro: {len(selected)}")

    if not selected:
        print("\nNo hay configuraciones agregadas que cumplan los criterios minimos.")
        return

    export_rows(OUTPUT_PATH, selected)
    export_rows_with_activity(ACTIVITY_OUTPUT_PATH, selected_with_activity)
    print_top(selected, top_n=TOP_N)
    print_top_with_activity(selected_with_activity, top_n=TOP_N)
    print_summary(selected)
    print(f"- Archivo exportado: {OUTPUT_PATH}")
    print(f"- Archivo exportado: {ACTIVITY_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
