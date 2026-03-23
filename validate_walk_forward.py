from __future__ import annotations

import csv
import math
import statistics
from dataclasses import replace
from pathlib import Path

from bot.config import SimulationConfig
from bot.engine import run_simulation
from bot.models import SimulationResult
from bot.utils import (
    BACKTEST_EQUITY_CURVE_CSV_FILENAME,
    BACKTEST_SUMMARY_CSV_FILENAME,
    BACKTEST_TRADES_CSV_FILENAME,
)


OUTPUT_PATH = Path("validation_walk_forward.csv")
FIXED_CANDLE_COUNT = 300

WALK_FORWARD_SPLITS = [
    {"split_name": "split_1", "train_offset": 800, "test_offset": 500},
    {"split_name": "split_2", "train_offset": 500, "test_offset": 200},
    {"split_name": "split_3", "train_offset": 400, "test_offset": 100},
    {"split_name": "split_4", "train_offset": 300, "test_offset": 0},
]

BASE_CONFIG = SimulationConfig(
    execution_mode="paper",
    market_data_mode="binance_historical",
    symbol="ETHUSDT",
    short_window=5,
    long_window=20,
    stop_loss_pct=0.01,
    take_profit_pct=0.05,
    position_size_pct=0.5,
    max_drawdown_limit_pct=1.5,
    trend_filter_enabled=True,
    trend_window=50,
    trend_slope_filter_enabled=True,
    trend_slope_lookback=3,
    volatility_filter_enabled=False,
    regime_filter_enabled=False,
    signal_confirmation_bars=0,
    warmup_bars=0,
)


def snapshot_file(path: Path) -> bytes | None:
    if not path.exists():
        return None
    return path.read_bytes()


def restore_file(path: Path, content: bytes | None) -> None:
    if content is None:
        if path.exists():
            path.unlink()
        return
    path.write_bytes(content)


def format_metric(value: float) -> str:
    if math.isinf(value):
        return "inf"
    return f"{value:.6f}"


def safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def run_sample(offset: int) -> SimulationResult:
    config = replace(
        BASE_CONFIG,
        candle_count=FIXED_CANDLE_COUNT,
        historical_offset=offset,
    )
    return run_simulation(config)


def run_split(split: dict[str, int | str]) -> dict[str, object]:
    train_offset = int(split["train_offset"])
    test_offset = int(split["test_offset"])

    train_result = run_sample(train_offset)
    test_result = run_sample(test_offset)

    return {
        "row_type": "split",
        "split_name": split["split_name"],
        "candle_count": FIXED_CANDLE_COUNT,
        "train_offset": train_offset,
        "test_offset": test_offset,
        "train_return_pct": train_result.return_pct,
        "test_return_pct": test_result.return_pct,
        "train_profit_factor": train_result.profit_factor,
        "test_profit_factor": test_result.profit_factor,
        "train_drawdown_pct": train_result.max_drawdown_pct,
        "test_drawdown_pct": test_result.max_drawdown_pct,
        "train_total_trades": train_result.total_trades,
        "test_total_trades": test_result.total_trades,
        "avg_train_return_pct": "",
        "avg_test_return_pct": "",
        "std_test_return_pct": "",
        "positive_test_rate": "",
        "zero_trade_test_rate": "",
        "worst_test_return_pct": "",
    }


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    train_returns = [float(row["train_return_pct"]) for row in rows]
    test_returns = [float(row["test_return_pct"]) for row in rows]
    test_trade_counts = [int(row["test_total_trades"]) for row in rows]

    positive_test_runs = sum(1 for value in test_returns if value > 0.0)
    zero_trade_test_runs = sum(1 for value in test_trade_counts if value == 0)
    runs = len(rows)

    return {
        "row_type": "aggregate",
        "split_name": "aggregate",
        "candle_count": FIXED_CANDLE_COUNT,
        "train_offset": "",
        "test_offset": "",
        "train_return_pct": "",
        "test_return_pct": "",
        "train_profit_factor": "",
        "test_profit_factor": "",
        "train_drawdown_pct": "",
        "test_drawdown_pct": "",
        "train_total_trades": "",
        "test_total_trades": "",
        "avg_train_return_pct": safe_mean(train_returns),
        "avg_test_return_pct": safe_mean(test_returns),
        "std_test_return_pct": statistics.pstdev(test_returns) if len(test_returns) > 1 else 0.0,
        "positive_test_rate": (positive_test_runs / runs) if runs > 0 else 0.0,
        "zero_trade_test_rate": (zero_trade_test_runs / runs) if runs > 0 else 0.0,
        "worst_test_return_pct": min(test_returns) if test_returns else 0.0,
    }


def print_split_summary(row: dict[str, object]) -> None:
    print(
        f"- {row['split_name']} | train_offset={row['train_offset']} -> test_offset={row['test_offset']} | "
        f"train_return_pct={float(row['train_return_pct']):.2f}% | "
        f"test_return_pct={float(row['test_return_pct']):.2f}% | "
        f"train_profit_factor={format_metric(float(row['train_profit_factor']))} | "
        f"test_profit_factor={format_metric(float(row['test_profit_factor']))} | "
        f"train_drawdown_pct={float(row['train_drawdown_pct']):.2f}% | "
        f"test_drawdown_pct={float(row['test_drawdown_pct']):.2f}% | "
        f"train_total_trades={int(row['train_total_trades'])} | "
        f"test_total_trades={int(row['test_total_trades'])}"
    )


def print_aggregate_summary(row: dict[str, object]) -> None:
    print("\nResumen agregado final")
    print(f"- avg_train_return_pct: {float(row['avg_train_return_pct']):.2f}%")
    print(f"- avg_test_return_pct: {float(row['avg_test_return_pct']):.2f}%")
    print(f"- std_test_return_pct: {float(row['std_test_return_pct']):.2f}")
    print(f"- positive_test_rate: {float(row['positive_test_rate']) * 100.0:.2f}%")
    print(f"- zero_trade_test_rate: {float(row['zero_trade_test_rate']) * 100.0:.2f}%")
    print(f"- worst_test_return_pct: {float(row['worst_test_return_pct']):.2f}%")


def export_csv(split_rows: list[dict[str, object]], aggregate_row: dict[str, object]) -> None:
    rows = [*split_rows, aggregate_row]
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "row_type",
                "split_name",
                "candle_count",
                "train_offset",
                "test_offset",
                "train_return_pct",
                "test_return_pct",
                "train_profit_factor",
                "test_profit_factor",
                "train_drawdown_pct",
                "test_drawdown_pct",
                "train_total_trades",
                "test_total_trades",
                "avg_train_return_pct",
                "avg_test_return_pct",
                "std_test_return_pct",
                "positive_test_rate",
                "zero_trade_test_rate",
                "worst_test_return_pct",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "row_type": row["row_type"],
                    "split_name": row["split_name"],
                    "candle_count": row["candle_count"],
                    "train_offset": row["train_offset"],
                    "test_offset": row["test_offset"],
                    "train_return_pct": (
                        f"{float(row['train_return_pct']):.6f}"
                        if row["train_return_pct"] != ""
                        else ""
                    ),
                    "test_return_pct": (
                        f"{float(row['test_return_pct']):.6f}"
                        if row["test_return_pct"] != ""
                        else ""
                    ),
                    "train_profit_factor": (
                        format_metric(float(row["train_profit_factor"]))
                        if row["train_profit_factor"] != ""
                        else ""
                    ),
                    "test_profit_factor": (
                        format_metric(float(row["test_profit_factor"]))
                        if row["test_profit_factor"] != ""
                        else ""
                    ),
                    "train_drawdown_pct": (
                        f"{float(row['train_drawdown_pct']):.6f}"
                        if row["train_drawdown_pct"] != ""
                        else ""
                    ),
                    "test_drawdown_pct": (
                        f"{float(row['test_drawdown_pct']):.6f}"
                        if row["test_drawdown_pct"] != ""
                        else ""
                    ),
                    "train_total_trades": row["train_total_trades"],
                    "test_total_trades": row["test_total_trades"],
                    "avg_train_return_pct": (
                        f"{float(row['avg_train_return_pct']):.6f}"
                        if row["avg_train_return_pct"] != ""
                        else ""
                    ),
                    "avg_test_return_pct": (
                        f"{float(row['avg_test_return_pct']):.6f}"
                        if row["avg_test_return_pct"] != ""
                        else ""
                    ),
                    "std_test_return_pct": (
                        f"{float(row['std_test_return_pct']):.6f}"
                        if row["std_test_return_pct"] != ""
                        else ""
                    ),
                    "positive_test_rate": (
                        f"{float(row['positive_test_rate']):.6f}"
                        if row["positive_test_rate"] != ""
                        else ""
                    ),
                    "zero_trade_test_rate": (
                        f"{float(row['zero_trade_test_rate']):.6f}"
                        if row["zero_trade_test_rate"] != ""
                        else ""
                    ),
                    "worst_test_return_pct": (
                        f"{float(row['worst_test_return_pct']):.6f}"
                        if row["worst_test_return_pct"] != ""
                        else ""
                    ),
                }
            )


def main() -> None:
    managed_paths = [
        Path(BACKTEST_SUMMARY_CSV_FILENAME),
        Path(BACKTEST_TRADES_CSV_FILENAME),
        Path(BACKTEST_EQUITY_CURVE_CSV_FILENAME),
    ]
    snapshots = {path: snapshot_file(path) for path in managed_paths}

    print("Validacion walk-forward temporal")
    print("- market_data_mode=binance_historical")
    print(f"- symbol={BASE_CONFIG.symbol}")
    print(f"- candle_count fijo={FIXED_CANDLE_COUNT}")
    print(
        "- config fija: short_window=5 long_window=20 stop_loss_pct=0.01 "
        "take_profit_pct=0.05 position_size_pct=0.5 max_drawdown_limit_pct=1.5"
    )
    print(
        "- filtros: trend_filter_enabled=True trend_window=50 "
        "trend_slope_filter_enabled=True trend_slope_lookback=3 "
        "volatility_filter_enabled=False regime_filter_enabled=False "
        "signal_confirmation_bars=0 warmup_bars=0"
    )
    print(
        "- nota_offsets: historical_offset mayor = ventana mas antigua; "
        "con estos pares train/test quedan en orden temporal hacia adelante."
    )

    try:
        split_rows: list[dict[str, object]] = []
        print("\nResumen por split")
        for split in WALK_FORWARD_SPLITS:
            row = run_split(split)
            split_rows.append(row)
            print_split_summary(row)

        aggregate_row = summarize(split_rows)
        print_aggregate_summary(aggregate_row)
        export_csv(split_rows, aggregate_row)
        print(f"\nCSV exportado: {OUTPUT_PATH}")
    finally:
        for path, content in snapshots.items():
            restore_file(path, content)


if __name__ == "__main__":
    main()
