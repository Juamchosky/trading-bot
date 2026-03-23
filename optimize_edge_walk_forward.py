from __future__ import annotations

import csv
import math
import statistics
import time
from dataclasses import replace
from http.client import IncompleteRead
from itertools import product
from pathlib import Path
from urllib.error import HTTPError, URLError

from bot.config import SimulationConfig
from bot.engine import run_simulation
from bot.models import SimulationResult
from bot.utils import (
    BACKTEST_EQUITY_CURVE_CSV_FILENAME,
    BACKTEST_SUMMARY_CSV_FILENAME,
    BACKTEST_TRADES_CSV_FILENAME,
)


OUTPUT_PATH = Path("optimization_walk_forward_edge.csv")
FIXED_CANDLE_COUNT = 300

WALK_FORWARD_SPLITS = [
    {"split_name": "split_1", "train_offset": 800, "test_offset": 500},
    {"split_name": "split_2", "train_offset": 500, "test_offset": 200},
    {"split_name": "split_3", "train_offset": 400, "test_offset": 100},
    {"split_name": "split_4", "train_offset": 300, "test_offset": 0},
]

TAKE_PROFIT_VALUES = [0.04, 0.05, 0.06]
SIGNAL_CONFIRMATION_VALUES = [0, 1, 2]

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


def format_metric(value: float, suffix: str = "") -> str:
    if math.isinf(value):
        return ("inf" if value > 0 else "-inf") + suffix
    return f"{value:.6f}{suffix}"


def safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def mean_profit_factor(values: list[float]) -> float:
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


def run_sample(config: SimulationConfig, offset: int) -> SimulationResult:
    sample_config = replace(
        config,
        candle_count=FIXED_CANDLE_COUNT,
        historical_offset=offset,
    )
    retries = 3
    for attempt in range(1, retries + 1):
        try:
            return run_simulation(sample_config)
        except (IncompleteRead, HTTPError, URLError, TimeoutError):
            if attempt == retries:
                raise
            time.sleep(1.0 * attempt)
    raise RuntimeError("No se pudo ejecutar run_simulation tras varios reintentos.")


def run_split(config: SimulationConfig, split: dict[str, int | str]) -> dict[str, object]:
    train_offset = int(split["train_offset"])
    test_offset = int(split["test_offset"])

    train_result = run_sample(config, train_offset)
    test_result = run_sample(config, test_offset)

    return {
        "split_name": split["split_name"],
        "train_offset": train_offset,
        "test_offset": test_offset,
        "train_return_pct": train_result.return_pct,
        "test_return_pct": test_result.return_pct,
        "test_profit_factor": test_result.profit_factor,
        "test_drawdown_pct": test_result.max_drawdown_pct,
        "test_total_trades": test_result.total_trades,
    }


def summarize_combination(
    take_profit_pct: float, signal_confirmation_bars: int, split_rows: list[dict[str, object]]
) -> dict[str, object]:
    train_returns = [float(row["train_return_pct"]) for row in split_rows]
    test_returns = [float(row["test_return_pct"]) for row in split_rows]
    test_trade_counts = [int(row["test_total_trades"]) for row in split_rows]
    test_profit_factors = [float(row["test_profit_factor"]) for row in split_rows]
    test_drawdowns = [float(row["test_drawdown_pct"]) for row in split_rows]

    positive_test_runs = sum(1 for value in test_returns if value > 0.0)
    zero_trade_test_runs = sum(1 for value in test_trade_counts if value == 0)
    runs = len(split_rows)

    return {
        "take_profit_pct": take_profit_pct,
        "signal_confirmation_bars": signal_confirmation_bars,
        "avg_train_return_pct": safe_mean(train_returns),
        "avg_test_return_pct": safe_mean(test_returns),
        "std_test_return_pct": statistics.pstdev(test_returns) if len(test_returns) > 1 else 0.0,
        "positive_test_rate": (positive_test_runs / runs) if runs > 0 else 0.0,
        "zero_trade_test_rate": (zero_trade_test_runs / runs) if runs > 0 else 0.0,
        "worst_test_return_pct": min(test_returns) if test_returns else 0.0,
        "avg_test_profit_factor": mean_profit_factor(test_profit_factors),
        "avg_test_drawdown_pct": safe_mean(test_drawdowns),
        "avg_test_total_trades": safe_mean([float(value) for value in test_trade_counts]),
        "split_test_returns": " | ".join(
            f"{row['split_name']}={float(row['test_return_pct']):.2f}%"
            for row in split_rows
        ),
    }


def sort_key(row: dict[str, object]) -> tuple[float, float, float, float]:
    return (
        -float(row["avg_test_return_pct"]),
        float(row["zero_trade_test_rate"]),
        -float(row["positive_test_rate"]),
        float(row["std_test_return_pct"]),
    )


def print_combination_summary(row: dict[str, object]) -> None:
    print(
        f"- take_profit_pct={float(row['take_profit_pct']):.2f} | "
        f"signal_confirmation_bars={int(row['signal_confirmation_bars'])} | "
        f"avg_train_return_pct={float(row['avg_train_return_pct']):.2f}% | "
        f"avg_test_return_pct={float(row['avg_test_return_pct']):.2f}% | "
        f"std_test_return_pct={float(row['std_test_return_pct']):.2f} | "
        f"positive_test_rate={float(row['positive_test_rate']) * 100.0:.2f}% | "
        f"zero_trade_test_rate={float(row['zero_trade_test_rate']) * 100.0:.2f}% | "
        f"worst_test_return_pct={float(row['worst_test_return_pct']):.2f}% | "
        f"avg_test_profit_factor={format_metric(float(row['avg_test_profit_factor']))} | "
        f"avg_test_drawdown_pct={float(row['avg_test_drawdown_pct']):.2f}% | "
        f"avg_test_total_trades={float(row['avg_test_total_trades']):.2f}"
    )
    print(f"  test_returns_by_split: {row['split_test_returns']}")


def print_ranking(rows: list[dict[str, object]]) -> None:
    print("\nRanking final")
    for index, row in enumerate(rows, start=1):
        print(
            f"{index}. take_profit_pct={float(row['take_profit_pct']):.2f}, "
            f"signal_confirmation_bars={int(row['signal_confirmation_bars'])} | "
            f"avg_test_return_pct={float(row['avg_test_return_pct']):.2f}% | "
            f"zero_trade_test_rate={float(row['zero_trade_test_rate']) * 100.0:.2f}% | "
            f"positive_test_rate={float(row['positive_test_rate']) * 100.0:.2f}% | "
            f"std_test_return_pct={float(row['std_test_return_pct']):.2f}"
        )


def export_csv(rows: list[dict[str, object]]) -> None:
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "rank",
                "take_profit_pct",
                "signal_confirmation_bars",
                "avg_train_return_pct",
                "avg_test_return_pct",
                "std_test_return_pct",
                "positive_test_rate",
                "zero_trade_test_rate",
                "worst_test_return_pct",
                "avg_test_profit_factor",
                "avg_test_drawdown_pct",
                "avg_test_total_trades",
                "split_test_returns",
            ],
        )
        writer.writeheader()
        for index, row in enumerate(rows, start=1):
            writer.writerow(
                {
                    "rank": index,
                    "take_profit_pct": f"{float(row['take_profit_pct']):.6f}",
                    "signal_confirmation_bars": int(row["signal_confirmation_bars"]),
                    "avg_train_return_pct": f"{float(row['avg_train_return_pct']):.6f}",
                    "avg_test_return_pct": f"{float(row['avg_test_return_pct']):.6f}",
                    "std_test_return_pct": f"{float(row['std_test_return_pct']):.6f}",
                    "positive_test_rate": f"{float(row['positive_test_rate']):.6f}",
                    "zero_trade_test_rate": f"{float(row['zero_trade_test_rate']):.6f}",
                    "worst_test_return_pct": f"{float(row['worst_test_return_pct']):.6f}",
                    "avg_test_profit_factor": format_metric(float(row["avg_test_profit_factor"])),
                    "avg_test_drawdown_pct": f"{float(row['avg_test_drawdown_pct']):.6f}",
                    "avg_test_total_trades": f"{float(row['avg_test_total_trades']):.6f}",
                    "split_test_returns": row["split_test_returns"],
                }
            )


def main() -> None:
    managed_paths = [
        Path(BACKTEST_SUMMARY_CSV_FILENAME),
        Path(BACKTEST_TRADES_CSV_FILENAME),
        Path(BACKTEST_EQUITY_CURVE_CSV_FILENAME),
    ]
    snapshots = {path: snapshot_file(path) for path in managed_paths}

    print("Optimizacion controlada de edge (walk-forward)")
    print("- market_data_mode=binance_historical")
    print(f"- symbol={BASE_CONFIG.symbol}")
    print(f"- candle_count fijo={FIXED_CANDLE_COUNT}")
    print("- variaciones: take_profit_pct in [0.04, 0.05, 0.06]")
    print("- variaciones: signal_confirmation_bars in [0, 1, 2]")
    print("- todo lo demas fijo sobre la configuracion robusta actual")
    print("- splits: (800->500), (500->200), (400->100), (300->0)")

    try:
        rows: list[dict[str, object]] = []
        print("\nResumen por combinacion")
        for take_profit_pct, signal_confirmation_bars in product(
            TAKE_PROFIT_VALUES, SIGNAL_CONFIRMATION_VALUES
        ):
            config = replace(
                BASE_CONFIG,
                take_profit_pct=take_profit_pct,
                signal_confirmation_bars=signal_confirmation_bars,
            )
            split_rows = [run_split(config, split) for split in WALK_FORWARD_SPLITS]
            summary = summarize_combination(take_profit_pct, signal_confirmation_bars, split_rows)
            rows.append(summary)
            print_combination_summary(summary)

        ranked_rows = sorted(rows, key=sort_key)
        print_ranking(ranked_rows)
        export_csv(ranked_rows)
        print(f"\nCSV exportado: {OUTPUT_PATH}")
    finally:
        for path, content in snapshots.items():
            restore_file(path, content)


if __name__ == "__main__":
    main()
