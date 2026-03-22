from __future__ import annotations

import csv
import math
import argparse
from dataclasses import replace
from pathlib import Path

from bot.config import MarketDataMode, SimulationConfig
from bot.engine import run_simulation
from bot.market.binance_data import BinanceMarketDataError, fetch_historical_candles
from bot.market.simulator import generate_candles
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
        regime_range_pct = calculate_regime_range_pct(config)
        result = run_simulation(config)
        scenario_results.append(
            {
                "scenario_name": scenario["name"],
                "candle_count": config.candle_count,
                "regime_range_pct": regime_range_pct,
                "result": result,
            }
        )

    return {
        "scenario_results": scenario_results,
        "summary": summarize_results(scenario_results),
    }


def calculate_regime_range_pct(config: SimulationConfig) -> float:
    candles = load_market_candles(config)
    if not candles:
        return 0.0

    recent_closes = [candle.close for candle in candles[-config.regime_window :]]
    if not recent_closes:
        return 0.0

    min_close = min(recent_closes)
    if min_close <= 0:
        return 0.0

    max_close = max(recent_closes)
    return ((max_close - min_close) / min_close) * 100.0


def load_market_candles(config: SimulationConfig):
    if config.market_data_mode == "simulated":
        return generate_candles(
            candle_count=config.candle_count,
            start_price=config.starting_price,
            volatility=config.volatility,
            seed=config.random_seed,
        )

    if config.market_data_mode == "binance_historical":
        try:
            return fetch_historical_candles(
                symbol=config.symbol,
                interval=config.binance_interval,
                limit=config.candle_count,
                base_url=config.binance_spot_base_url,
            )
        except BinanceMarketDataError as exc:
            raise ValueError(f"Failed to load Binance historical candles: {exc}") from exc

    raise ValueError(f"Unsupported market_data_mode: {config.market_data_mode}")


def summarize_results(scenario_results: list[dict[str, object]]) -> dict[str, float | int]:
    returns = [get_result(row).return_pct for row in scenario_results]
    drawdowns = [get_result(row).max_drawdown_pct for row in scenario_results]
    closed_trades = [float(get_result(row).closed_trades) for row in scenario_results]
    profit_factors = [
        get_result(row).profit_factor
        for row in scenario_results
        if math.isfinite(get_result(row).profit_factor)
    ]
    regime_ranges = [float(row["regime_range_pct"]) for row in scenario_results]

    return {
        "runs": len(scenario_results),
        "avg_return_pct": safe_mean(returns),
        "worst_return_pct": min(returns) if returns else 0.0,
        "best_return_pct": max(returns) if returns else 0.0,
        "avg_drawdown_pct": safe_mean(drawdowns),
        "avg_profit_factor": safe_mean(profit_factors),
        "avg_closed_trades": safe_mean(closed_trades),
        "min_regime_range_pct_observed": min(regime_ranges) if regime_ranges else 0.0,
        "max_regime_range_pct_observed": max(regime_ranges) if regime_ranges else 0.0,
        "avg_regime_range_pct_observed": safe_mean(regime_ranges),
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
        f"regime_range_pct_real={float(row['regime_range_pct']):.2f}% | "
        f"return_pct={result.return_pct:.2f}% | "
        f"win_rate_pct={result.win_rate_pct:.2f}% | "
        f"profit_factor={format_metric(result.profit_factor)} | "
        f"max_drawdown_pct={result.max_drawdown_pct:.2f}% | "
        f"closed_trades={result.closed_trades}"
    )


def print_summary(summary: dict[str, float | int]) -> None:
    print("\nResumen agregado")
    print(f"- escenarios evaluados: {summary['runs']}")
    print(f"- avg_return_pct: {float(summary['avg_return_pct']):.2f}%")
    print(f"- worst_return_pct: {float(summary['worst_return_pct']):.2f}%")
    print(f"- avg_profit_factor: {format_metric(float(summary['avg_profit_factor']))}")
    print(f"- avg_drawdown_pct: {float(summary['avg_drawdown_pct']):.2f}%")
    print(f"- avg_closed_trades: {float(summary['avg_closed_trades']):.2f}")
    print("\nResumen regime_range_pct observado")
    print(
        f"- minimo: {float(summary['min_regime_range_pct_observed']):.2f}% | "
        f"maximo: {float(summary['max_regime_range_pct_observed']):.2f}% | "
        f"promedio: {float(summary['avg_regime_range_pct_observed']):.2f}%"
    )


def export_validation_outputs(
    scenario_results: list[dict[str, object]],
    summary: dict[str, float | int],
) -> None:
    export_scenario_results(scenario_results, DETAIL_OUTPUT_PATH)
    export_summary_results(summary, SUMMARY_OUTPUT_PATH)
    print(f"\nArchivo detalle exportado: {DETAIL_OUTPUT_PATH}")
    print(f"Archivo resumen exportado: {SUMMARY_OUTPUT_PATH}")


def export_scenario_results(scenario_results: list[dict[str, object]], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "scenario_name",
                "candle_count",
                "regime_range_pct_real",
                "min_regime_range_pct_configured",
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
                    "regime_range_pct_real": f"{float(scenario_row['regime_range_pct']):.6f}",
                    "min_regime_range_pct_configured": f"{BASE_CONFIG.min_regime_range_pct:.6f}",
                    "return_pct": f"{result.return_pct:.6f}",
                    "win_rate_pct": f"{result.win_rate_pct:.6f}",
                    "profit_factor": format_metric(result.profit_factor),
                    "max_drawdown_pct": f"{result.max_drawdown_pct:.6f}",
                    "closed_trades": result.closed_trades,
                    "final_balance": f"{result.final_balance:.6f}",
                }
            )


def export_summary_results(summary: dict[str, float | int], output_path: Path) -> None:
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
                "avg_closed_trades",
                "min_regime_range_pct_observed",
                "max_regime_range_pct_observed",
                "avg_regime_range_pct_observed",
                "min_regime_range_pct_configured",
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
                "avg_closed_trades": f"{float(summary['avg_closed_trades']):.6f}",
                "min_regime_range_pct_observed": f"{float(summary['min_regime_range_pct_observed']):.6f}",
                "max_regime_range_pct_observed": f"{float(summary['max_regime_range_pct_observed']):.6f}",
                "avg_regime_range_pct_observed": f"{float(summary['avg_regime_range_pct_observed']):.6f}",
                "min_regime_range_pct_configured": f"{BASE_CONFIG.min_regime_range_pct:.6f}",
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnostica regime filter en escenarios de candle_count con parametros fijos "
            "y reporta regime_range_pct real observado."
        )
    )
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="Corre una validacion rapida (solo 2 escenarios) para smoke test.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candle_counts = CANDLE_COUNTS[:2] if args.minimal else CANDLE_COUNTS

    scenarios = build_scenarios(candle_counts)
    managed_paths = [
        Path(BACKTEST_SUMMARY_CSV_FILENAME),
        Path(BACKTEST_TRADES_CSV_FILENAME),
        Path(BACKTEST_EQUITY_CURVE_CSV_FILENAME),
    ]
    snapshots = {path: snapshot_file(path) for path in managed_paths}

    print("Diagnostico de regime filter (proxy=candle_count)")
    print(f"- market_data_mode: {MARKET_DATA_MODE}")
    print(f"- symbol: {BASE_CONFIG.symbol}")
    print(f"- candle_count escenarios: {candle_counts}")
    print(f"- min_regime_range_pct configurado: {BASE_CONFIG.min_regime_range_pct:.1f}%")
    print("- configuracion fija: short=5 long=20 sl=0.02 tp=0.03 pos=0.5")
    print(
        "- filtros: trend=True(50) trend_slope=True(lookback=3) "
        "volatility=False(min=0.10) regime=True(window=50)"
    )
    print(
        f"- riesgo: max_drawdown_limit_pct={BASE_CONFIG.max_drawdown_limit_pct:.1f} "
        "signal_confirmation_bars=0 warmup_bars=0"
    )

    try:
        validation = run_validation(BASE_CONFIG, scenarios)
        scenario_results = validation["scenario_results"]  # type: ignore[assignment]
        summary = validation["summary"]  # type: ignore[assignment]

        print("\nResultados por escenario")
        for run_index, row in enumerate(scenario_results, start=1):
            print_run_detail(row, run_index, len(scenario_results))
        print_summary(summary)  # type: ignore[arg-type]

        export_validation_outputs(scenario_results, summary)  # type: ignore[arg-type]
    finally:
        for path, content in snapshots.items():
            restore_file(path, content)


if __name__ == "__main__":
    main()
