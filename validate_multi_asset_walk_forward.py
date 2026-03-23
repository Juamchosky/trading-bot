from __future__ import annotations

import csv
import math
import statistics
import time
from dataclasses import replace
from http.client import IncompleteRead
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


OUTPUT_PATH = Path("validation_multi_asset_walk_forward.csv")
FIXED_CANDLE_COUNT = 300

ASSETS = ["ETHUSDT", "BTCUSDT"]
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

CONFIGS = [
    {
        "config_name": "CONFIG_A",
        "short_window": 5,
        "long_window": 20,
        "stop_loss_pct": 0.01,
        "take_profit_pct": 0.05,
        "signal_confirmation_bars": 0,
    },
    {
        "config_name": "CONFIG_B",
        "short_window": 5,
        "long_window": 20,
        "stop_loss_pct": 0.01,
        "take_profit_pct": 0.05,
        "signal_confirmation_bars": 1,
    },
]


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


def safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def safe_pstdev(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    return statistics.pstdev(values)


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


def format_metric(value: float, decimals: int = 2, suffix: str = "") -> str:
    if math.isinf(value):
        return ("inf" if value > 0 else "-inf") + suffix
    return f"{value:.{decimals}f}{suffix}"


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


def summarize_asset_config(
    asset: str,
    config_name: str,
    split_rows: list[dict[str, object]],
) -> dict[str, object]:
    test_returns = [float(row["test_return_pct"]) for row in split_rows]
    test_trade_counts = [int(row["test_total_trades"]) for row in split_rows]
    test_profit_factors = [float(row["test_profit_factor"]) for row in split_rows]
    test_drawdowns = [float(row["test_drawdown_pct"]) for row in split_rows]

    positive_test_runs = sum(1 for value in test_returns if value > 0.0)
    zero_trade_test_runs = sum(1 for value in test_trade_counts if value == 0)
    runs = len(split_rows)

    return {
        "row_type": "asset_config_summary",
        "asset": asset,
        "config_name": config_name,
        "avg_test_return_pct": safe_mean(test_returns),
        "std_test_return_pct": safe_pstdev(test_returns),
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


def summarize_config_cross_asset(
    config_name: str, rows: list[dict[str, object]]
) -> dict[str, object]:
    avg_returns = [float(row["avg_test_return_pct"]) for row in rows]
    std_returns = [float(row["std_test_return_pct"]) for row in rows]
    zero_trade_rates = [float(row["zero_trade_test_rate"]) for row in rows]
    positive_rates = [float(row["positive_test_rate"]) for row in rows]
    worst_returns = [float(row["worst_test_return_pct"]) for row in rows]
    avg_profit_factors = [float(row["avg_test_profit_factor"]) for row in rows]
    avg_drawdowns = [float(row["avg_test_drawdown_pct"]) for row in rows]
    avg_trades = [float(row["avg_test_total_trades"]) for row in rows]

    return {
        "row_type": "config_cross_asset_summary",
        "asset": "ALL",
        "config_name": config_name,
        "avg_test_return_pct": safe_mean(avg_returns),
        "std_test_return_pct": safe_mean(std_returns),
        "positive_test_rate": safe_mean(positive_rates),
        "zero_trade_test_rate": max(zero_trade_rates) if zero_trade_rates else 0.0,
        "worst_test_return_pct": min(worst_returns) if worst_returns else 0.0,
        "avg_test_profit_factor": safe_mean(avg_profit_factors),
        "avg_test_drawdown_pct": safe_mean(avg_drawdowns),
        "avg_test_total_trades": safe_mean(avg_trades),
        "cross_asset_return_std": safe_pstdev(avg_returns),
        "split_test_returns": "",
    }


def ranking_sort_key(row: dict[str, object]) -> tuple[int, int, float, float, float]:
    zero_trade_rate = float(row["zero_trade_test_rate"])
    avg_test_return = float(row["avg_test_return_pct"])
    cross_asset_return_std = float(row["cross_asset_return_std"])
    std_test_return_pct = float(row["std_test_return_pct"])
    positive_rate = float(row["positive_test_rate"])

    zero_trade_ok = 1 if zero_trade_rate == 0.0 else 0
    positive_return_ok = 1 if avg_test_return > 0.0 else 0

    return (
        -zero_trade_ok,
        -positive_return_ok,
        cross_asset_return_std,
        -avg_test_return,
        std_test_return_pct - positive_rate,
    )


def to_csv_row(row: dict[str, object], rank: int | str = "") -> dict[str, object]:
    return {
        "row_type": row["row_type"],
        "rank": rank,
        "asset": row["asset"],
        "config_name": row["config_name"],
        "avg_test_return_pct": f"{float(row['avg_test_return_pct']):.6f}",
        "std_test_return_pct": f"{float(row['std_test_return_pct']):.6f}",
        "positive_test_rate": f"{float(row['positive_test_rate']):.6f}",
        "zero_trade_test_rate": f"{float(row['zero_trade_test_rate']):.6f}",
        "worst_test_return_pct": f"{float(row['worst_test_return_pct']):.6f}",
        "avg_test_profit_factor": format_metric(float(row["avg_test_profit_factor"]), decimals=6),
        "avg_test_drawdown_pct": f"{float(row['avg_test_drawdown_pct']):.6f}",
        "avg_test_total_trades": f"{float(row['avg_test_total_trades']):.6f}",
        "cross_asset_return_std": (
            f"{float(row['cross_asset_return_std']):.6f}"
            if "cross_asset_return_std" in row
            else ""
        ),
        "split_test_returns": row["split_test_returns"],
    }


def print_asset_config_summary(row: dict[str, object]) -> None:
    print(
        f"- asset={row['asset']} | config={row['config_name']} | "
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


def print_final_ranking(rows: list[dict[str, object]]) -> None:
    print("\nRanking final cross-asset (por configuracion)")
    print("- prioridad: zero_trade_test_rate=0, avg_test_return_pct>0, consistencia cross-asset, estabilidad")
    for index, row in enumerate(rows, start=1):
        print(
            f"{index}. config={row['config_name']} | "
            f"avg_test_return_pct={float(row['avg_test_return_pct']):.2f}% | "
            f"zero_trade_test_rate={float(row['zero_trade_test_rate']) * 100.0:.2f}% | "
            f"cross_asset_return_std={float(row['cross_asset_return_std']):.2f} | "
            f"std_test_return_pct={float(row['std_test_return_pct']):.2f} | "
            f"positive_test_rate={float(row['positive_test_rate']) * 100.0:.2f}%"
        )


def export_csv(asset_config_rows: list[dict[str, object]], ranked_rows: list[dict[str, object]]) -> None:
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "row_type",
                "rank",
                "asset",
                "config_name",
                "avg_test_return_pct",
                "std_test_return_pct",
                "positive_test_rate",
                "zero_trade_test_rate",
                "worst_test_return_pct",
                "avg_test_profit_factor",
                "avg_test_drawdown_pct",
                "avg_test_total_trades",
                "cross_asset_return_std",
                "split_test_returns",
            ],
        )
        writer.writeheader()
        for row in asset_config_rows:
            writer.writerow(to_csv_row(row))
        for index, row in enumerate(ranked_rows, start=1):
            writer.writerow(to_csv_row(row, rank=index))


def main() -> None:
    managed_paths = [
        Path(BACKTEST_SUMMARY_CSV_FILENAME),
        Path(BACKTEST_TRADES_CSV_FILENAME),
        Path(BACKTEST_EQUITY_CURVE_CSV_FILENAME),
    ]
    snapshots = {path: snapshot_file(path) for path in managed_paths}

    print("Validacion multi-activo walk-forward")
    print("- market_data_mode=binance_historical")
    print("- activos: ETHUSDT, BTCUSDT")
    print("- configs: CONFIG_A(signal_confirmation_bars=0), CONFIG_B(signal_confirmation_bars=1)")
    print("- candle_count fijo=300")
    print("- splits: (800->500), (500->200), (400->100), (300->0)")

    try:
        asset_config_rows: list[dict[str, object]] = []
        grouped_by_config: dict[str, list[dict[str, object]]] = {}

        print("\nResumen por asset/config")
        for asset in ASSETS:
            for config_params in CONFIGS:
                config_name = str(config_params["config_name"])
                config = replace(
                    BASE_CONFIG,
                    symbol=asset,
                    short_window=int(config_params["short_window"]),
                    long_window=int(config_params["long_window"]),
                    stop_loss_pct=float(config_params["stop_loss_pct"]),
                    take_profit_pct=float(config_params["take_profit_pct"]),
                    signal_confirmation_bars=int(config_params["signal_confirmation_bars"]),
                )
                split_rows = [run_split(config, split) for split in WALK_FORWARD_SPLITS]
                summary_row = summarize_asset_config(asset, config_name, split_rows)
                asset_config_rows.append(summary_row)
                grouped_by_config.setdefault(config_name, []).append(summary_row)
                print_asset_config_summary(summary_row)

        config_rank_rows = [
            summarize_config_cross_asset(config_name, rows)
            for config_name, rows in grouped_by_config.items()
        ]
        ranked_rows = sorted(config_rank_rows, key=ranking_sort_key)
        print_final_ranking(ranked_rows)

        export_csv(asset_config_rows, ranked_rows)
        print(f"\nCSV exportado: {OUTPUT_PATH}")
    finally:
        for path, content in snapshots.items():
            restore_file(path, content)


if __name__ == "__main__":
    main()
