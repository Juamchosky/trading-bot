from __future__ import annotations

import csv
import math
from dataclasses import replace
from pathlib import Path

from bot.config import MarketDataMode, SimulationConfig
from bot.engine import run_simulation
from bot.models import SimulationResult
from bot.utils import (
    BACKTEST_EQUITY_CURVE_CSV_FILENAME,
    BACKTEST_SUMMARY_CSV_FILENAME,
    BACKTEST_TRADES_CSV_FILENAME,
)


MARKET_DATA_MODE: MarketDataMode = "binance_historical"
CANDLE_COUNTS = [100, 200, 300, 500, 800]
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
    regime_filter_enabled=True,
    regime_window=50,
    min_regime_range_pct=1.5,
    signal_confirmation_bars=0,
    warmup_bars=0,
)


def build_scenarios(candle_counts: list[int]) -> list[dict[str, int | str]]:
    return [
        {
            "name": f"regime_{candle_count}",
            "candle_count": candle_count,
        }
        for candle_count in candle_counts
    ]


def run_validation(
    config_template: SimulationConfig,
    scenarios: list[dict[str, int | str]],
) -> dict[str, object]:
    scenario_results: list[dict[str, object]] = []

    for scenario in scenarios:
        config = replace(config_template, candle_count=int(scenario["candle_count"]))
        result = run_simulation(config)
        scenario_results.append(
            {
                "scenario_name": scenario["name"],
                "candle_count": config.candle_count,
                "result": result,
            }
        )

    return {
        "scenario_results": scenario_results,
        "summary": summarize_results(scenario_results),
    }


def summarize_results(scenario_results: list[dict[str, object]]) -> dict[str, float | int]:
    returns = [get_result(row).return_pct for row in scenario_results]
    drawdowns = [get_result(row).max_drawdown_pct for row in scenario_results]
    profit_factors = [
        get_result(row).profit_factor
        for row in scenario_results
        if math.isfinite(get_result(row).profit_factor)
    ]

    return {
        "runs": len(scenario_results),
        "avg_return_pct": safe_mean(returns),
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


def format_metric(value: float) -> str:
    if math.isinf(value):
        return "inf"
    return f"{value:.2f}"


def print_run_detail(row: dict[str, object], run_index: int, total_runs: int) -> None:
    result = get_result(row)
    print(
        f"[{run_index}/{total_runs}] scenario={row['scenario_name']} candles={row['candle_count']} | "
        f"return_pct={result.return_pct:.2f}% | "
        f"win_rate_pct={result.win_rate_pct:.2f}% | "
        f"profit_factor={format_metric(result.profit_factor)} | "
        f"max_drawdown_pct={result.max_drawdown_pct:.2f}% | "
        f"closed_trades={result.closed_trades}"
    )


def print_final_summary(summary: dict[str, float | int]) -> None:
    print("\nResumen final agregado (regimenes por candle_count)")
    print(f"- escenarios evaluados: {summary['runs']}")
    print(f"- promedio return_pct: {float(summary['avg_return_pct']):.2f}%")
    print(f"- peor return_pct: {float(summary['worst_return_pct']):.2f}%")
    print(f"- mejor return_pct: {float(summary['best_return_pct']):.2f}%")
    print(f"- promedio profit_factor: {format_metric(float(summary['avg_profit_factor']))}")
    print(f"- promedio drawdown: {float(summary['avg_drawdown_pct']):.2f}%")


def export_validation_outputs(validation: dict[str, object]) -> None:
    export_scenario_results(validation, DETAIL_OUTPUT_PATH)
    export_summary_results(validation, SUMMARY_OUTPUT_PATH)
    print(f"\nArchivo detalle exportado: {DETAIL_OUTPUT_PATH}")
    print(f"Archivo resumen exportado: {SUMMARY_OUTPUT_PATH}")


def export_scenario_results(validation: dict[str, object], output_path: Path) -> None:
    scenario_results = validation["scenario_results"]  # type: ignore[assignment]
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "scenario_name",
                "candle_count",
                "return_pct",
                "win_rate_pct",
                "profit_factor",
                "max_drawdown_pct",
                "closed_trades",
                "final_balance",
            ],
        )
        writer.writeheader()

        for scenario_row in scenario_results:
            result = get_result(scenario_row)
            writer.writerow(
                {
                    "scenario_name": scenario_row["scenario_name"],
                    "candle_count": scenario_row["candle_count"],
                    "return_pct": f"{result.return_pct:.6f}",
                    "win_rate_pct": f"{result.win_rate_pct:.6f}",
                    "profit_factor": format_metric(result.profit_factor),
                    "max_drawdown_pct": f"{result.max_drawdown_pct:.6f}",
                    "closed_trades": result.closed_trades,
                    "final_balance": f"{result.final_balance:.6f}",
                }
            )


def export_summary_results(validation: dict[str, object], output_path: Path) -> None:
    summary = validation["summary"]  # type: ignore[assignment]
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "runs",
                "avg_return_pct",
                "worst_return_pct",
                "best_return_pct",
                "avg_drawdown_pct",
                "avg_profit_factor",
            ],
        )
        writer.writeheader()

        writer.writerow(
            {
                "runs": summary["runs"],
                "avg_return_pct": f"{float(summary['avg_return_pct']):.6f}",
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
    scenarios = build_scenarios(CANDLE_COUNTS)
    managed_paths = [
        Path(BACKTEST_SUMMARY_CSV_FILENAME),
        Path(BACKTEST_TRADES_CSV_FILENAME),
        Path(BACKTEST_EQUITY_CURVE_CSV_FILENAME),
    ]
    snapshots = {path: snapshot_file(path) for path in managed_paths}

    print("Stress test por regimen de mercado (proxy=candle_count)")
    print(f"- market_data_mode: {MARKET_DATA_MODE}")
    print(f"- symbol: {BASE_CONFIG.symbol}")
    print(f"- candle_count escenarios: {CANDLE_COUNTS}")
    print("- configuracion fija: short=5 long=20 sl=0.02 tp=0.03 pos=0.5")
    print(
        "- filtros: trend=True(50) trend_slope=True(lookback=3) "
        "volatility=False regime=True(window=50,min=1.5%)"
    )
    print(
        f"- riesgo: max_drawdown_limit_pct={BASE_CONFIG.max_drawdown_limit_pct:.1f} "
        "signal_confirmation_bars=0 warmup_bars=0"
    )

    try:
        validation = run_validation(BASE_CONFIG, scenarios)

        scenario_results = validation["scenario_results"]  # type: ignore[assignment]
        print("\nResultados por escenario")
        for run_index, row in enumerate(scenario_results, start=1):
            print_run_detail(row, run_index, len(scenario_results))

        print_final_summary(validation["summary"])  # type: ignore[arg-type]
        export_validation_outputs(validation)
    finally:
        for path, content in snapshots.items():
            restore_file(path, content)


if __name__ == "__main__":
    main()
