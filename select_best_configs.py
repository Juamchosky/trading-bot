from __future__ import annotations

import csv
import math
from collections import Counter
from pathlib import Path
from typing import Any


SUMMARY_PATH = Path("backtest_summary.csv")
TOP_N = 10

REQUIRED_FIELDS = [
    "short_window",
    "long_window",
    "stop_loss_pct",
    "take_profit_pct",
    "position_size_pct",
    "max_drawdown_limit_pct",
    "return_pct",
    "profit_factor",
    "max_drawdown_pct",
    "total_trades",
    "closed_trades",
]


def parse_float(value: Any) -> float | None:
    raw = str(value or "").strip().lower()
    if raw in {"", "nan", "none", "null"}:
        return None
    if raw in {"inf", "+inf", "infinity", "+infinity"}:
        return float("inf")
    if raw in {"-inf", "-infinity"}:
        return float("-inf")
    try:
        number = float(raw)
    except ValueError:
        return None
    if math.isnan(number):
        return None
    return number


def fmt_float(value: float | None, decimals: int = 4) -> str:
    if value is None:
        return "N/A"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
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


def passes_filters(row: dict[str, str]) -> bool:
    profit_factor = parse_float(row.get("profit_factor"))
    return_pct = parse_float(row.get("return_pct"))
    max_drawdown_pct = parse_float(row.get("max_drawdown_pct"))

    if profit_factor is None or return_pct is None or max_drawdown_pct is None:
        return False
    return profit_factor > 1 and return_pct > 0 and max_drawdown_pct <= 2.0


def rank_key(row: dict[str, str]) -> tuple[float, float, float]:
    return_pct = parse_float(row.get("return_pct")) or float("-inf")
    profit_factor = parse_float(row.get("profit_factor")) or float("-inf")
    max_drawdown_pct = parse_float(row.get("max_drawdown_pct")) or float("inf")
    # Mejor retorno, luego mejor profit factor, y menor drawdown.
    return (return_pct, profit_factor, -max_drawdown_pct)


def safe_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def most_common_value(rows: list[dict[str, str]], field: str) -> str:
    values = [str(row.get(field, "")).strip() for row in rows if str(row.get(field, "")).strip()]
    if not values:
        return "N/A"
    value, count = Counter(values).most_common(1)[0]
    return f"{value} ({count}x)"


def print_top(rows: list[dict[str, str]], top_n: int = TOP_N) -> None:
    headers = [
        "short_window",
        "long_window",
        "stop_loss_pct",
        "take_profit_pct",
        "position_size_pct",
        "max_drawdown_limit_pct",
        "return_pct",
        "profit_factor",
        "max_drawdown_pct",
        "total_trades",
        "closed_trades",
    ]

    print(f"\nTop {top_n} configuraciones ganadoras:")
    print(" | ".join(headers))
    print("-" * 170)

    for row in rows[:top_n]:
        line = " | ".join(str(row.get(h, "N/A")) for h in headers)
        print(line)


def print_summary(winners: list[dict[str, str]]) -> None:
    return_values = [
        v
        for v in (parse_float(row.get("return_pct")) for row in winners)
        if v is not None and not math.isinf(v)
    ]
    profit_factor_values = [
        v
        for v in (parse_float(row.get("profit_factor")) for row in winners)
        if v is not None and not math.isinf(v)
    ]
    drawdown_values = [
        v
        for v in (parse_float(row.get("max_drawdown_pct")) for row in winners)
        if v is not None and not math.isinf(v)
    ]

    avg_return = safe_mean(return_values)
    avg_profit_factor = safe_mean(profit_factor_values)
    avg_drawdown = safe_mean(drawdown_values)

    print("\nResumen de ganadoras:")
    print(f"- Promedio return_pct: {fmt_float(avg_return)}")
    print(f"- Promedio profit_factor: {fmt_float(avg_profit_factor)}")
    print(f"- Promedio max_drawdown_pct: {fmt_float(avg_drawdown)}")
    print("- Parametros mas frecuentes:")
    print(f"  short_window: {most_common_value(winners, 'short_window')}")
    print(f"  long_window: {most_common_value(winners, 'long_window')}")
    print(f"  stop_loss_pct: {most_common_value(winners, 'stop_loss_pct')}")
    print(f"  take_profit_pct: {most_common_value(winners, 'take_profit_pct')}")


def main() -> None:
    rows = load_rows(SUMMARY_PATH)
    winners = [row for row in rows if passes_filters(row)]
    ranked = sorted(winners, key=rank_key, reverse=True)

    print(f"Cantidad total de corridas leidas: {len(rows)}")
    print(f"Cantidad de corridas que pasan el filtro: {len(winners)}")

    if not winners:
        print("\nNo hay configuraciones que cumplan los criterios minimos.")
        return

    print_top(ranked, top_n=TOP_N)
    print_summary(ranked)


if __name__ == "__main__":
    main()
