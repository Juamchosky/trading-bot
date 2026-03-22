from __future__ import annotations

import argparse
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


DETAIL_OUTPUT_PATH = Path("forward_preprod_detail.csv")
SUMMARY_OUTPUT_PATH = Path("forward_preprod_summary.csv")

CANDLE_COUNTS = [200, 300, 500, 800]
RANDOM_SEEDS = [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]

BASE_CONFIG = SimulationConfig(
    execution_mode="paper",
    market_data_mode="simulated",
    symbol="ETHUSDT",
    short_window=5,
    long_window=20,
    stop_loss_pct=0.02,
    take_profit_pct=0.03,
    position_size_pct=0.5,
    max_drawdown_limit_pct=1.0,
    trend_filter_enabled=True,
    trend_window=50,
    trend_slope_filter_enabled=True,
    trend_slope_lookback=3,
    volatility_filter_enabled=False,
    regime_filter_enabled=False,
    signal_confirmation_bars=2,
    warmup_bars=0,
)

CONFIG_NAME = "candidate_final"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validacion pre-produccion de configuracion candidata unica "
            "sobre multiples seeds y candle_count."
        )
    )
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="Smoke test rapido (2 seeds x 2 candle_counts).",
    )
    return parser.parse_args()


def build_scenarios(candle_counts: list[int], seeds: list[int]) -> list[dict[str, int | str]]:
    scenarios: list[dict[str, int | str]] = []
    for candle_count in candle_counts:
        for seed in seeds:
            scenarios.append(
                {
                    "scenario_name": f"cc_{candle_count}_seed_{seed}",
                    "candle_count": candle_count,
                    "random_seed": seed,
                }
            )
    return scenarios


def run_validation(scenarios: list[dict[str, int | str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for scenario in scenarios:
        config = replace(
            BASE_CONFIG,
            candle_count=int(scenario["candle_count"]),
            random_seed=int(scenario["random_seed"]),
        )
        result = run_simulation(config)
        row = {
            "config_name": CONFIG_NAME,
            "scenario_name": scenario["scenario_name"],
            "symbol": config.symbol,
            "candle_count": config.candle_count,
            "random_seed": config.random_seed,
            "result": result,
        }
        rows.append(row)
        print_run_detail(row)
    return rows


def summarize(results: list[dict[str, object]]) -> dict[str, float]:
    returns = [get_result(row).return_pct for row in results]
    drawdowns = [get_result(row).max_drawdown_pct for row in results]
    finite_profit_factors = [
        get_result(row).profit_factor
        for row in results
        if math.isfinite(get_result(row).profit_factor)
    ]
    positive_runs = [value for value in returns if value > 0.0]

    std_return = statistics.pstdev(returns) if len(returns) > 1 else 0.0
    scenario_win_rate = (len(positive_runs) / len(returns) * 100.0) if returns else 0.0

    return {
        "total_runs": float(len(results)),
        "avg_return": safe_mean(returns),
        "std_return": std_return,
        "scenario_win_rate": scenario_win_rate,
        "worst_return": min(returns) if returns else 0.0,
        "avg_drawdown": safe_mean(drawdowns),
        "avg_profit_factor": safe_mean(finite_profit_factors),
    }


def export_detail(results: list[dict[str, object]], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "config_name",
                "scenario_name",
                "symbol",
                "candle_count",
                "random_seed",
                "return_pct",
                "win_rate",
                "max_drawdown_pct",
                "profit_factor",
                "closed_trades",
                "final_balance",
            ],
        )
        writer.writeheader()
        for row in results:
            result = get_result(row)
            writer.writerow(
                {
                    "config_name": row["config_name"],
                    "scenario_name": row["scenario_name"],
                    "symbol": row["symbol"],
                    "candle_count": row["candle_count"],
                    "random_seed": row["random_seed"],
                    "return_pct": f"{result.return_pct:.6f}",
                    "win_rate": f"{result.win_rate_pct:.6f}",
                    "max_drawdown_pct": f"{result.max_drawdown_pct:.6f}",
                    "profit_factor": format_metric(result.profit_factor),
                    "closed_trades": result.closed_trades,
                    "final_balance": f"{result.final_balance:.6f}",
                }
            )


def export_summary(rows: list[dict[str, object]], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "config_name",
                "avg_return",
                "std_return",
                "scenario_win_rate",
                "worst_return",
                "avg_drawdown",
                "avg_profit_factor",
                "total_runs",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "config_name": row["config_name"],
                    "avg_return": f"{row['avg_return']:.6f}",
                    "std_return": f"{row['std_return']:.6f}",
                    "scenario_win_rate": f"{row['scenario_win_rate']:.6f}",
                    "worst_return": f"{row['worst_return']:.6f}",
                    "avg_drawdown": f"{row['avg_drawdown']:.6f}",
                    "avg_profit_factor": format_metric(row["avg_profit_factor"]),
                    "total_runs": int(row["total_runs"]),
                }
            )


def get_result(row: dict[str, object]) -> SimulationResult:
    return row["result"]  # type: ignore[return-value]


def safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def safe_value(value: float) -> float:
    if math.isinf(value):
        return 1_000_000_000.0
    return value


def format_metric(value: float) -> str:
    if math.isinf(value):
        return "inf"
    return f"{value:.6f}"


def print_run_detail(row: dict[str, object]) -> None:
    result = get_result(row)
    print(
        f"- {row['scenario_name']} | "
        f"return_pct={result.return_pct:.2f}% | "
        f"win_rate={result.win_rate_pct:.2f}% | "
        f"max_drawdown_pct={result.max_drawdown_pct:.2f}% | "
        f"profit_factor={format_metric(result.profit_factor)}"
    )


def print_summary(summary: dict[str, object]) -> None:
    print(f"\nResumen global - {summary['config_name']}")
    print(f"- avg_return: {summary['avg_return']:.2f}%")
    print(f"- std_return: {summary['std_return']:.2f}")
    print(f"- scenario_win_rate: {summary['scenario_win_rate']:.2f}%")
    print(f"- worst_return: {summary['worst_return']:.2f}%")
    print(f"- avg_drawdown: {summary['avg_drawdown']:.2f}%")
    print(f"- avg_profit_factor: {format_metric(summary['avg_profit_factor'])}")
    print(f"- total_runs: {int(summary['total_runs'])}")


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


def main() -> None:
    args = parse_args()
    candle_counts = CANDLE_COUNTS[:2] if args.minimal else CANDLE_COUNTS
    random_seeds = RANDOM_SEEDS[:2] if args.minimal else RANDOM_SEEDS
    scenarios = build_scenarios(candle_counts, random_seeds)

    managed_paths = [
        Path(BACKTEST_SUMMARY_CSV_FILENAME),
        Path(BACKTEST_TRADES_CSV_FILENAME),
        Path(BACKTEST_EQUITY_CURVE_CSV_FILENAME),
    ]
    snapshots = {path: snapshot_file(path) for path in managed_paths}

    print("Forward simulation pre-produccion - configuracion candidata unica")
    if args.minimal:
        print("- modo=minimal (validacion rapida, 2 seeds x 2 candle_counts)")
    else:
        print("- modo=full (todos los escenarios solicitados)")
    print(f"- symbol={BASE_CONFIG.symbol}")
    print(
        "- fixed_config: short_window=5 long_window=20 stop_loss_pct=0.02 "
        "take_profit_pct=0.03 position_size_pct=0.5 max_drawdown_limit_pct=1.0"
    )
    print(
        "- filtros: trend_filter_enabled=True trend_window=50 "
        "trend_slope_filter_enabled=True trend_slope_lookback=3 "
        "volatility_filter_enabled=False regime_filter_enabled=False "
        "signal_confirmation_bars=2 warmup_bars=0"
    )
    print(f"- escenarios: candle_counts={candle_counts} random_seeds={random_seeds}")
    print(f"- total_runs={len(scenarios)}")

    try:
        results = run_validation(scenarios)
        summary_row = {"config_name": CONFIG_NAME, **summarize(results)}
        print_summary(summary_row)
        export_detail(results, DETAIL_OUTPUT_PATH)
        export_summary([summary_row], SUMMARY_OUTPUT_PATH)
        print(f"\nCSV detalle por corrida: {DETAIL_OUTPUT_PATH}")
        print(f"CSV resumen global: {SUMMARY_OUTPUT_PATH}")
    finally:
        for path, content in snapshots.items():
            restore_file(path, content)


if __name__ == "__main__":
    main()

