from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any


SUMMARY_PATH = Path("backtest_summary.csv")
TOP_N = 5
PARAM_FIELDS = ["short_window", "long_window", "stop_loss_pct", "take_profit_pct"]


def parse_float(value: str) -> float:
    raw = (value or "").strip().lower()
    if raw in {"", "nan"}:
        return float("-inf")
    if raw in {"inf", "+inf", "infinity", "+infinity"}:
        return float("inf")
    if raw in {"-inf", "-infinity"}:
        return float("-inf")
    try:
        return float(raw)
    except ValueError:
        return float("-inf")


def metric_label(metric_name: str, value: float) -> str:
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return f"{value:.6f}"


def load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"No se encontro el archivo: {path}")

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        raise ValueError(f"El archivo {path} no tiene filas de datos.")
    return rows


def print_top(rows: list[dict[str, Any]], metric: str, top_n: int = TOP_N) -> None:
    ranked = sorted(rows, key=lambda row: parse_float(row.get(metric, "")), reverse=True)[:top_n]

    print(f"\nTop {top_n} por {metric}:")
    for idx, row in enumerate(ranked, start=1):
        metric_value = parse_float(row.get(metric, ""))
        params = ", ".join(f"{p}={row.get(p, 'N/A')}" for p in PARAM_FIELDS)
        print(f"{idx}. {metric}={metric_label(metric, metric_value)} | {params}")


def main() -> None:
    rows = load_rows(SUMMARY_PATH)
    print_top(rows, "return_pct")
    print_top(rows, "profit_factor")


if __name__ == "__main__":
    main()
