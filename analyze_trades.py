from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any


TRADES_PATH = Path("backtest_trades.csv")
EXPECTED_EXIT_REASONS = ("signal", "stop_loss", "take_profit", "forced_close")


def load_trades(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"No se encontro el archivo: {path}")

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        raise ValueError(f"El archivo {path} no tiene filas de datos.")

    required_columns = {"pnl", "exit_reason"}
    missing_columns = required_columns.difference(reader.fieldnames or [])
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Faltan columnas requeridas en {path}: {missing}")

    return rows


def parse_pnl(raw_value: Any, row_number: int) -> float:
    try:
        return float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"PNL invalido en la fila {row_number}: {raw_value!r}") from exc


def average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def analyze_trades(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pnls: list[float] = []
    winners: list[float] = []
    losers: list[float] = []
    exit_reason_counts: Counter[str] = Counter()

    for idx, row in enumerate(rows, start=2):
        pnl = parse_pnl(row.get("pnl"), idx)
        exit_reason = str(row.get("exit_reason", "")).strip() or "unknown"

        pnls.append(pnl)
        exit_reason_counts[exit_reason] += 1

        if pnl > 0:
            winners.append(pnl)
        elif pnl < 0:
            losers.append(pnl)

    total_trades = len(rows)
    break_even = total_trades - len(winners) - len(losers)

    ordered_exit_reasons: dict[str, int] = {
        reason: exit_reason_counts.get(reason, 0) for reason in EXPECTED_EXIT_REASONS
    }
    for reason, count in sorted(exit_reason_counts.items()):
        if reason not in ordered_exit_reasons:
            ordered_exit_reasons[reason] = count

    return {
        "total_trades": total_trades,
        "winner_count": len(winners),
        "loser_count": len(losers),
        "break_even_count": break_even,
        "avg_winner_pnl": average(winners),
        "avg_loser_pnl": average(losers),
        "net_pnl": sum(pnls),
        "exit_reason_counts": ordered_exit_reasons,
    }


def print_report(stats: dict[str, Any]) -> None:
    total_trades = stats["total_trades"]
    winner_count = stats["winner_count"]
    loser_count = stats["loser_count"]
    break_even_count = stats["break_even_count"]

    print("Analisis de trades individuales")
    print(f"Archivo analizado: {TRADES_PATH}")
    print()
    print("Resumen general")
    print(f"Total trades: {total_trades}")
    print(f"Ganadores: {winner_count}")
    print(f"Perdedores: {loser_count}")
    print(f"Break-even: {break_even_count}")
    print(f"PNL neto: {stats['net_pnl']:.2f}")
    print(f"Promedio pnl ganadores: {stats['avg_winner_pnl']:.2f}")
    print(f"Promedio pnl perdedores: {stats['avg_loser_pnl']:.2f}")

    print()
    print("Distribucion por exit_reason")
    for reason, count in stats["exit_reason_counts"].items():
        percentage = (count / total_trades * 100) if total_trades else 0.0
        print(f"{reason}: {count} ({percentage:.2f}%)")


def main() -> None:
    rows = load_trades(TRADES_PATH)
    stats = analyze_trades(rows)
    print_report(stats)


if __name__ == "__main__":
    main()
