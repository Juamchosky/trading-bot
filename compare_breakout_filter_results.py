from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any


SUMMARY_PATH = Path("backtest_summary.csv")
GROUP_OFF = "breakout filter off"
GROUP_ON = "breakout filter on"


def load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"No se encontro el archivo: {path}")

    with path.open("r", newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        rows = list(reader)
        headers = set(reader.fieldnames or [])

    if not rows:
        raise ValueError(f"El archivo {path} no tiene filas de datos.")

    required = {
        "breakout_filter_enabled",
        "breakout_lookback",
        "return_pct",
        "profit_factor",
        "closed_trades",
        "max_drawdown_pct",
    }
    missing = required.difference(headers)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(
            f"Faltan columnas requeridas en {path}: {missing_text}. "
            "Ejecuta nuevas corridas de backtest para poblarlas."
        )

    return rows


def parse_float(value: Any) -> float | None:
    raw = str(value or "").strip().lower()
    if raw in {"", "nan"}:
        return None
    if raw in {"inf", "+inf", "infinity", "+infinity"}:
        return float("inf")
    if raw in {"-inf", "-infinity"}:
        return float("-inf")
    try:
        return float(raw)
    except ValueError:
        return None


def parse_bool(value: Any) -> bool | None:
    raw = str(value or "").strip().lower()
    if raw in {"true", "1", "yes", "y", "on"}:
        return True
    if raw in {"false", "0", "no", "n", "off"}:
        return False
    return None


def average(values: list[float]) -> float:
    if not values:
        return 0.0
    finite_values = [value for value in values if math.isfinite(value)]
    if finite_values:
        return sum(finite_values) / len(finite_values)
    if any(math.isinf(value) and value > 0 for value in values):
        return float("inf")
    if any(math.isinf(value) and value < 0 for value in values):
        return float("-inf")
    return 0.0


def format_metric(value: float, suffix: str = "") -> str:
    if math.isinf(value):
        return ("inf" if value > 0 else "-inf") + suffix
    return f"{value:.6f}{suffix}"


def summarize_group(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    return_pcts = [value for row in rows if (value := parse_float(row.get("return_pct"))) is not None]
    profit_factors = [
        value for row in rows if (value := parse_float(row.get("profit_factor"))) is not None
    ]
    max_drawdowns = [
        value for row in rows if (value := parse_float(row.get("max_drawdown_pct"))) is not None
    ]
    closed_trades = [
        value for row in rows if (value := parse_float(row.get("closed_trades"))) is not None
    ]
    positive_return_count = sum(1 for value in return_pcts if value > 0)
    run_count = len(rows)
    positive_run_pct = ((positive_return_count / run_count) * 100.0) if run_count else 0.0

    return {
        "run_count": run_count,
        "avg_return_pct": average(return_pcts),
        "avg_profit_factor": average(profit_factors),
        "avg_max_drawdown_pct": average(max_drawdowns),
        "avg_closed_trades": average(closed_trades),
        "positive_run_pct": positive_run_pct,
    }


def print_group(title: str, stats: dict[str, float | int]) -> None:
    print(f"\n{title}")
    print(f"Cantidad de corridas: {stats['run_count']}")
    print(f"Promedio return_pct: {format_metric(float(stats['avg_return_pct']), '%')}")
    print(f"Promedio profit_factor: {format_metric(float(stats['avg_profit_factor']))}")
    print(f"Promedio max_drawdown_pct: {format_metric(float(stats['avg_max_drawdown_pct']), '%')}")
    print(f"Promedio closed_trades: {format_metric(float(stats['avg_closed_trades']))}")
    print(f"Porcentaje de corridas positivas: {format_metric(float(stats['positive_run_pct']), '%')}")


def main() -> None:
    rows = load_rows(SUMMARY_PATH)
    grouped_rows: dict[str, list[dict[str, Any]]] = {
        GROUP_OFF: [],
        GROUP_ON: [],
    }
    skipped = 0

    for row in rows:
        breakout_enabled = parse_bool(row.get("breakout_filter_enabled"))
        if breakout_enabled is None:
            skipped += 1
            continue
        group_key = GROUP_ON if breakout_enabled else GROUP_OFF
        grouped_rows[group_key].append(row)

    print(f"Archivo analizado: {SUMMARY_PATH}")
    print(f"Total corridas leidas: {len(rows)}")
    if skipped:
        print(f"Corridas omitidas por breakout_filter_enabled invalido/vacio: {skipped}")

    print_group("Grupo: breakout filter off", summarize_group(grouped_rows[GROUP_OFF]))
    print_group("Grupo: breakout filter on", summarize_group(grouped_rows[GROUP_ON]))


if __name__ == "__main__":
    main()
