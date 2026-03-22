from __future__ import annotations

import csv
import math
from dataclasses import replace
from pathlib import Path
from statistics import pstdev

from bot.config import MarketDataMode, SimulationConfig
from bot.engine import run_simulation
from bot.models import SimulationResult
from bot.utils import (
    BACKTEST_EQUITY_CURVE_CSV_FILENAME,
    BACKTEST_SUMMARY_CSV_FILENAME,
    BACKTEST_TRADES_CSV_FILENAME,
)


MARKET_DATA_MODE: MarketDataMode = "binance_historical"
RUNS_PER_CONFIG = 10
CANDLE_COUNTS = [200, 300, 500]
BASE_RANDOM_SEED = 5
MAX_DRAWDOWN_VARIANTS = [1.0]
DETAIL_OUTPUT_PATH = Path("validation_scenario_results.csv")
SUMMARY_OUTPUT_PATH = Path("validation_config_ranking.csv")

BASE_CONFIG = SimulationConfig(
    execution_mode="paper",
    market_data_mode=MARKET_DATA_MODE,
    symbol="ETHUSDT",
    candle_count=300,
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
    volatility_window=20,
    min_volatility_pct=0.10,
    signal_confirmation_bars=0,
    warmup_bars=0,
)


def build_scenarios(
    *,
    market_data_mode: MarketDataMode,
    runs_per_config: int,
    candle_counts: list[int],
    base_random_seed: int,
) -> list[dict[str, int | str]]:
    scenarios: list[dict[str, int | str]] = []

    for index in range(runs_per_config):
        candle_count = candle_counts[index % len(candle_counts)]
        scenario = {
            "name": f"scenario_{index + 1}",
            "candle_count": candle_count,
        }

        if market_data_mode == "simulated":
            scenario["random_seed"] = base_random_seed + index

        scenarios.append(scenario)

    return scenarios


def run_validation(
    config_template: SimulationConfig,
    scenarios: list[dict[str, int | str]],
) -> dict[str, object]:
    scenario_results: list[dict[str, object]] = []

    for scenario in scenarios:
        config = replace(config_template, candle_count=int(scenario["candle_count"]))
        if "random_seed" in scenario:
            config = replace(config, random_seed=int(scenario["random_seed"]))
        result = run_simulation(config)
        scenario_results.append(
            {
                "scenario_name": scenario["name"],
                "candle_count": config.candle_count,
                "random_seed": scenario.get("random_seed", ""),
                "result": result,
            }
        )

    return {
        "max_drawdown_limit_pct": config_template.max_drawdown_limit_pct,
        "scenario_results": scenario_results,
        "summary": summarize_results(config_template.max_drawdown_limit_pct, scenario_results),
    }


def summarize_results(
    max_drawdown_limit_pct: float | None,
    scenario_results: list[dict[str, object]],
) -> dict[str, float | int]:
    returns = [get_result(row).return_pct for row in scenario_results]
    win_rates = [get_result(row).win_rate_pct for row in scenario_results]
    drawdowns = [get_result(row).max_drawdown_pct for row in scenario_results]
    profit_factors = [
        get_result(row).profit_factor
        for row in scenario_results
        if math.isfinite(get_result(row).profit_factor)
    ]

    wins = sum(1 for value in returns if value > 0)

    return {
        "max_drawdown_limit_pct": max_drawdown_limit_pct if max_drawdown_limit_pct is not None else 0.0,
        "runs": len(scenario_results),
        "avg_return_pct": safe_mean(returns),
        "std_return_pct": pstdev(returns) if len(returns) > 1 else 0.0,
        "scenario_win_rate_pct": (wins / len(returns)) * 100.0 if returns else 0.0,
        "avg_trade_win_rate_pct": safe_mean(win_rates),
        "worst_return_pct": min(returns) if returns else 0.0,
        "best_return_pct": max(returns) if returns else 0.0,
        "avg_drawdown_pct": safe_mean(drawdowns),
        "avg_profit_factor": safe_mean(profit_factors),
    }


def get_result(row: dict[str, object]) -> SimulationResult:
    return row["result"]  # type: ignore[return-value]


def safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def robustness_rank_key(row: dict[str, object]) -> tuple[float, float, float, float]:
    summary = row["summary"]  # type: ignore[assignment]
    return (
        float(summary["scenario_win_rate_pct"]),
        float(summary["avg_return_pct"]),
        -float(summary["std_return_pct"]),
        float(summary["worst_return_pct"]),
    )


def print_run_detail(
    row: dict[str, object],
    run_index: int,
    total_runs: int,
    max_drawdown_limit_pct: float | None,
) -> None:
    result = get_result(row)
    seed_part = f" seed={row['random_seed']}" if row["random_seed"] != "" else ""
    print(
        f"    [{run_index}/{total_runs}] {row['scenario_name']} "
        f"max_drawdown_limit_pct={format_metric(float(max_drawdown_limit_pct or 0.0))}% "
        f"candles={row['candle_count']}{seed_part} "
        f"return={result.return_pct:.2f}% "
        f"win_rate={result.win_rate_pct:.2f}% "
        f"drawdown={result.max_drawdown_pct:.2f}% "
        f"profit_factor={format_metric(result.profit_factor)}"
    )


def print_config_summary(summary: dict[str, float | int]) -> None:
    max_drawdown_limit_pct = float(summary["max_drawdown_limit_pct"])
    print(
        "  Resumen -> "
        f"max_drawdown_limit_pct={max_drawdown_limit_pct:.2f}% | "
        f"avg_return={float(summary['avg_return_pct']):.2f}% | "
        f"std_return={float(summary['std_return_pct']):.2f} | "
        f"scenario_win_rate={float(summary['scenario_win_rate_pct']):.2f}% | "
        f"worst={float(summary['worst_return_pct']):.2f}% | "
        f"avg_drawdown={float(summary['avg_drawdown_pct']):.2f}% | "
        f"avg_profit_factor={format_metric(float(summary['avg_profit_factor']))}"
    )


def print_final_ranking(rows: list[dict[str, object]]) -> None:
    print("\nRanking final (max_drawdown_limit_pct)")
    print(
        "Criterio: mayor scenario_win_rate, luego mayor avg_return, "
        "luego menor std_return, luego mejor worst_return."
    )

    for index, row in enumerate(rows, start=1):
        summary = row["summary"]  # type: ignore[assignment]
        print(
            f"{index}. max_drawdown_limit_pct={float(summary['max_drawdown_limit_pct']):.2f}% | "
            f"avg_return={float(summary['avg_return_pct']):.2f}% | "
            f"std_return={float(summary['std_return_pct']):.2f} | "
            f"scenario_win_rate={float(summary['scenario_win_rate_pct']):.2f}% | "
            f"worst={float(summary['worst_return_pct']):.2f}% | "
            f"avg_drawdown={float(summary['avg_drawdown_pct']):.2f}% | "
            f"avg_profit_factor={format_metric(float(summary['avg_profit_factor']))}"
        )


def format_metric(value: float) -> str:
    if math.isinf(value):
        return "inf"
    return f"{value:.2f}"


def export_validation_outputs(rows: list[dict[str, object]]) -> None:
    export_scenario_results(rows, DETAIL_OUTPUT_PATH)
    export_summary_results(rows, SUMMARY_OUTPUT_PATH)
    print(f"\nArchivo detalle exportado: {DETAIL_OUTPUT_PATH}")
    print(f"Archivo ranking exportado: {SUMMARY_OUTPUT_PATH}")


def export_scenario_results(rows: list[dict[str, object]], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "max_drawdown_limit_pct",
                "scenario_name",
                "candle_count",
                "random_seed",
                "return_pct",
                "win_rate_pct",
                "profit_factor",
                "max_drawdown_pct",
                "closed_trades",
                "final_balance",
            ],
        )
        writer.writeheader()

        for row in rows:
            max_drawdown_limit_pct = float(row["max_drawdown_limit_pct"])
            scenario_results = row["scenario_results"]  # type: ignore[assignment]
            for scenario_row in scenario_results:
                result = get_result(scenario_row)
                writer.writerow(
                    {
                        "max_drawdown_limit_pct": f"{max_drawdown_limit_pct:.6f}",
                        "scenario_name": scenario_row["scenario_name"],
                        "candle_count": scenario_row["candle_count"],
                        "random_seed": scenario_row["random_seed"],
                        "return_pct": f"{result.return_pct:.6f}",
                        "win_rate_pct": f"{result.win_rate_pct:.6f}",
                        "profit_factor": format_metric(result.profit_factor),
                        "max_drawdown_pct": f"{result.max_drawdown_pct:.6f}",
                        "closed_trades": result.closed_trades,
                        "final_balance": f"{result.final_balance:.6f}",
                    }
                )


def export_summary_results(rows: list[dict[str, object]], output_path: Path) -> None:
    ranking = sorted(rows, key=robustness_rank_key, reverse=True)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "rank",
                "max_drawdown_limit_pct",
                "runs",
                "avg_return_pct",
                "std_return_pct",
                "scenario_win_rate_pct",
                "avg_trade_win_rate_pct",
                "worst_return_pct",
                "best_return_pct",
                "avg_drawdown_pct",
                "avg_profit_factor",
            ],
        )
        writer.writeheader()

        for index, row in enumerate(ranking, start=1):
            summary = row["summary"]  # type: ignore[assignment]
            writer.writerow(
                {
                    "rank": index,
                    "max_drawdown_limit_pct": f"{float(summary['max_drawdown_limit_pct']):.6f}",
                    "runs": summary["runs"],
                    "avg_return_pct": f"{float(summary['avg_return_pct']):.6f}",
                    "std_return_pct": f"{float(summary['std_return_pct']):.6f}",
                    "scenario_win_rate_pct": f"{float(summary['scenario_win_rate_pct']):.6f}",
                    "avg_trade_win_rate_pct": f"{float(summary['avg_trade_win_rate_pct']):.6f}",
                    "worst_return_pct": f"{float(summary['worst_return_pct']):.6f}",
                    "best_return_pct": f"{float(summary['best_return_pct']):.6f}",
                    "avg_drawdown_pct": f"{float(summary['avg_drawdown_pct']):.6f}",
                    "avg_profit_factor": format_metric(float(summary["avg_profit_factor"])),
                }
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


def main() -> None:
    scenarios = build_scenarios(
        market_data_mode=MARKET_DATA_MODE,
        runs_per_config=RUNS_PER_CONFIG,
        candle_counts=CANDLE_COUNTS,
        base_random_seed=BASE_RANDOM_SEED,
    )
    managed_paths = [
        Path(BACKTEST_SUMMARY_CSV_FILENAME),
        Path(BACKTEST_TRADES_CSV_FILENAME),
        Path(BACKTEST_EQUITY_CURVE_CSV_FILENAME),
    ]
    snapshots = {path: snapshot_file(path) for path in managed_paths}

    print("Validacion: configuracion fija en datos reales (binance_historical)")
    print(f"- market_data_mode: {MARKET_DATA_MODE}")
    print(f"- corridas: {len(scenarios)}")
    print(f"- candle_counts evaluados: {CANDLE_COUNTS}")
    print(f"- symbol: {BASE_CONFIG.symbol}")
    print(f"- base config fija: short=5 long=20 sl=0.0200 tp=0.0300")
    print(
        "- base filtros: trend=True trend_window=50 trend_slope=True "
        "trend_slope_lookback=3 volatility=False min_volatility_pct=0.10 warmup=0"
    )
    print(f"- max_drawdown_limit_pct fijo: {BASE_CONFIG.max_drawdown_limit_pct:.1f}")
    if MARKET_DATA_MODE == "simulated":
        print(
            f"- random_seed evaluados: "
            f"{list(range(BASE_RANDOM_SEED, BASE_RANDOM_SEED + len(scenarios)))}"
        )

    validation_rows: list[dict[str, object]] = []

    try:
        for max_drawdown_limit_pct in MAX_DRAWDOWN_VARIANTS:
            config_variant = replace(BASE_CONFIG, max_drawdown_limit_pct=max_drawdown_limit_pct)
            print(f"\nConfiguracion fija max_drawdown_limit_pct={max_drawdown_limit_pct:.2f}%")
            validation = run_validation(config_variant, scenarios)
            validation_rows.append(validation)

            scenario_results = validation["scenario_results"]  # type: ignore[assignment]
            for run_index, row in enumerate(scenario_results, start=1):
                print_run_detail(row, run_index, len(scenario_results), max_drawdown_limit_pct)

            print_config_summary(validation["summary"])  # type: ignore[arg-type]
    finally:
        for path, content in snapshots.items():
            restore_file(path, content)

    ranking = sorted(validation_rows, key=robustness_rank_key, reverse=True)
    print_final_ranking(ranking)
    export_validation_outputs(validation_rows)


if __name__ == "__main__":
    main()
