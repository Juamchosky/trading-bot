from __future__ import annotations

import argparse
import csv
import math
import statistics
from dataclasses import replace
from pathlib import Path
from typing import Any

from bot.config import SimulationConfig
from bot.engine import run_simulation
from bot.models import SimulationResult
from bot.utils import (
    BACKTEST_EQUITY_CURVE_CSV_FILENAME,
    BACKTEST_SUMMARY_CSV_FILENAME,
    BACKTEST_TRADES_CSV_FILENAME,
)


OUTPUT_PATH = Path("validation_multi_sample_real.csv")
CANDLE_COUNTS = [150, 200, 300, 500, 800]

BASE_CONFIG = SimulationConfig(
    execution_mode="paper",
    market_data_mode="binance_historical",
    symbol="ETHUSDT",
    short_window=5,
    long_window=20,
    stop_loss_pct=0.02,
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

CANDIDATE_CONFIGS = [
    {
        "config_name": "cfg_sw5_lw50_sl2_tp5_pos50_dd15",
        "params": {
            "short_window": 5,
            "long_window": 50,
            "stop_loss_pct": 0.02,
            "take_profit_pct": 0.05,
            "position_size_pct": 0.5,
            "max_drawdown_limit_pct": 1.5,
        },
    },
    {
        "config_name": "cfg_sw8_lw20_sl2_tp5_pos50_dd15",
        "params": {
            "short_window": 8,
            "long_window": 20,
            "stop_loss_pct": 0.02,
            "take_profit_pct": 0.05,
            "position_size_pct": 0.5,
            "max_drawdown_limit_pct": 1.5,
        },
    },
    {
        "config_name": "cfg_sw5_lw20_sl1_tp5_pos50_dd15",
        "params": {
            "short_window": 5,
            "long_window": 20,
            "stop_loss_pct": 0.01,
            "take_profit_pct": 0.05,
            "position_size_pct": 0.5,
            "max_drawdown_limit_pct": 1.5,
        },
    },
    {
        "config_name": "cfg_sw8_lw30_sl2_tp5_pos50_dd15",
        "params": {
            "short_window": 8,
            "long_window": 30,
            "stop_loss_pct": 0.02,
            "take_profit_pct": 0.05,
            "position_size_pct": 0.5,
            "max_drawdown_limit_pct": 1.5,
        },
    },
    {
        "config_name": "cfg_sw8_lw30_sl2_tp3_pos50_dd15",
        "params": {
            "short_window": 8,
            "long_window": 30,
            "stop_loss_pct": 0.02,
            "take_profit_pct": 0.03,
            "position_size_pct": 0.5,
            "max_drawdown_limit_pct": 1.5,
        },
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Valida configuraciones candidatas en multiples submuestras reales "
            "(proxy por candle_count) y rankea por robustez."
        )
    )
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="Smoke test rapido (3 candle_counts y 2 configuraciones).",
    )
    return parser.parse_args()


def get_result(row: dict[str, object]) -> SimulationResult:
    return row["result"]  # type: ignore[return-value]


def safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def format_metric(value: float) -> str:
    if math.isinf(value):
        return "inf"
    return f"{value:.6f}"


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


def summarize_pf(profit_factors: list[float]) -> float:
    finite_values = [value for value in profit_factors if math.isfinite(value)]
    if finite_values:
        return safe_mean(finite_values)
    if any(value > 0 and math.isinf(value) for value in profit_factors):
        return float("inf")
    return 0.0


def run_candidate(
    *,
    config_name: str,
    params: dict[str, Any],
    candle_counts: list[int],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    scenario_rows: list[dict[str, object]] = []

    for candle_count in candle_counts:
        config = replace(BASE_CONFIG, candle_count=candle_count, **params)
        result = run_simulation(config)
        row = {
            "config_name": config_name,
            "candle_count": candle_count,
            "params": params,
            "result": result,
        }
        scenario_rows.append(row)

        print(
            f"- {config_name} | candle_count={candle_count} | "
            f"return_pct={result.return_pct:.2f}% | "
            f"profit_factor={format_metric(result.profit_factor)} | "
            f"drawdown={result.max_drawdown_pct:.2f}% | "
            f"total_trades={result.total_trades} | "
            f"closed_trades={result.closed_trades}"
        )

    summary = summarize_candidate(config_name=config_name, params=params, runs=scenario_rows)
    return scenario_rows, summary


def summarize_candidate(
    *,
    config_name: str,
    params: dict[str, Any],
    runs: list[dict[str, object]],
) -> dict[str, object]:
    returns = [get_result(row).return_pct for row in runs]
    profit_factors = [get_result(row).profit_factor for row in runs]
    drawdowns = [get_result(row).max_drawdown_pct for row in runs]
    total_trades = [float(get_result(row).total_trades) for row in runs]
    closed_trades = [get_result(row).closed_trades for row in runs]

    runs_count = len(runs)
    positive_runs = sum(1 for value in returns if value > 0.0)
    zero_trade_runs = sum(1 for value in closed_trades if value == 0)

    return {
        "config_name": config_name,
        "short_window": params["short_window"],
        "long_window": params["long_window"],
        "stop_loss_pct": params["stop_loss_pct"],
        "take_profit_pct": params["take_profit_pct"],
        "position_size_pct": params["position_size_pct"],
        "max_drawdown_limit_pct": params["max_drawdown_limit_pct"],
        "runs": runs_count,
        "candle_counts": "|".join(str(row["candle_count"]) for row in runs),
        "avg_return_pct": safe_mean(returns),
        "std_return_pct": statistics.pstdev(returns) if len(returns) > 1 else 0.0,
        "best_return_pct": max(returns) if returns else 0.0,
        "worst_return_pct": min(returns) if returns else 0.0,
        "avg_profit_factor": summarize_pf(profit_factors),
        "avg_drawdown_pct": safe_mean(drawdowns),
        "avg_total_trades": safe_mean(total_trades),
        "positive_run_rate": (positive_runs / runs_count) if runs_count > 0 else 0.0,
        "zero_trade_runs": zero_trade_runs,
        "zero_trade_rate": (zero_trade_runs / runs_count) if runs_count > 0 else 0.0,
    }


def rank_by_robustness(summaries: list[dict[str, object]]) -> list[dict[str, object]]:
    ranked = sorted(
        summaries,
        key=lambda row: (
            float(row["zero_trade_rate"]),
            -float(row["positive_run_rate"]),
            float(row["std_return_pct"]),
            -float(row["avg_return_pct"]),
        ),
    )
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    return ranked


def print_candidate_summary(row: dict[str, object]) -> None:
    print(f"\nResumen por configuracion: {row['config_name']}")
    print(
        "- params: "
        f"short={row['short_window']} long={row['long_window']} "
        f"sl={row['stop_loss_pct']} tp={row['take_profit_pct']} "
        f"pos={row['position_size_pct']} max_dd={row['max_drawdown_limit_pct']}"
    )
    print(f"- avg_return_pct: {float(row['avg_return_pct']):.2f}%")
    print(f"- std_return_pct: {float(row['std_return_pct']):.2f}")
    print(f"- best_return_pct: {float(row['best_return_pct']):.2f}%")
    print(f"- worst_return_pct: {float(row['worst_return_pct']):.2f}%")
    print(f"- avg_profit_factor: {format_metric(float(row['avg_profit_factor']))}")
    print(f"- avg_drawdown_pct: {float(row['avg_drawdown_pct']):.2f}%")
    print(f"- avg_total_trades: {float(row['avg_total_trades']):.2f}")
    print(f"- positive_run_rate: {float(row['positive_run_rate']) * 100.0:.2f}%")
    print(
        f"- zero_trade_runs: {int(row['zero_trade_runs'])} "
        f"(rate={float(row['zero_trade_rate']) * 100.0:.2f}%)"
    )


def print_ranking(ranked: list[dict[str, object]]) -> None:
    print("\nRanking final por robustez")
    for row in ranked:
        print(
            f"{int(row['rank'])}. {row['config_name']} | "
            f"zero_trade_rate={float(row['zero_trade_rate']) * 100.0:.2f}% | "
            f"positive_run_rate={float(row['positive_run_rate']) * 100.0:.2f}% | "
            f"std_return_pct={float(row['std_return_pct']):.2f} | "
            f"avg_return_pct={float(row['avg_return_pct']):.2f}%"
        )


def export_summary(ranked_rows: list[dict[str, object]], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "rank",
                "config_name",
                "short_window",
                "long_window",
                "stop_loss_pct",
                "take_profit_pct",
                "position_size_pct",
                "max_drawdown_limit_pct",
                "runs",
                "candle_counts",
                "avg_return_pct",
                "std_return_pct",
                "best_return_pct",
                "worst_return_pct",
                "avg_profit_factor",
                "avg_drawdown_pct",
                "avg_total_trades",
                "positive_run_rate",
                "zero_trade_runs",
                "zero_trade_rate",
            ],
        )
        writer.writeheader()
        for row in ranked_rows:
            writer.writerow(
                {
                    "rank": int(row["rank"]),
                    "config_name": row["config_name"],
                    "short_window": row["short_window"],
                    "long_window": row["long_window"],
                    "stop_loss_pct": f"{float(row['stop_loss_pct']):.6f}",
                    "take_profit_pct": f"{float(row['take_profit_pct']):.6f}",
                    "position_size_pct": f"{float(row['position_size_pct']):.6f}",
                    "max_drawdown_limit_pct": f"{float(row['max_drawdown_limit_pct']):.6f}",
                    "runs": int(row["runs"]),
                    "candle_counts": row["candle_counts"],
                    "avg_return_pct": f"{float(row['avg_return_pct']):.6f}",
                    "std_return_pct": f"{float(row['std_return_pct']):.6f}",
                    "best_return_pct": f"{float(row['best_return_pct']):.6f}",
                    "worst_return_pct": f"{float(row['worst_return_pct']):.6f}",
                    "avg_profit_factor": format_metric(float(row["avg_profit_factor"])),
                    "avg_drawdown_pct": f"{float(row['avg_drawdown_pct']):.6f}",
                    "avg_total_trades": f"{float(row['avg_total_trades']):.6f}",
                    "positive_run_rate": f"{float(row['positive_run_rate']):.6f}",
                    "zero_trade_runs": int(row["zero_trade_runs"]),
                    "zero_trade_rate": f"{float(row['zero_trade_rate']):.6f}",
                }
            )


def main() -> None:
    args = parse_args()
    candle_counts = CANDLE_COUNTS[:3] if args.minimal else CANDLE_COUNTS
    candidate_configs = CANDIDATE_CONFIGS[:2] if args.minimal else CANDIDATE_CONFIGS

    managed_paths = [
        Path(BACKTEST_SUMMARY_CSV_FILENAME),
        Path(BACKTEST_TRADES_CSV_FILENAME),
        Path(BACKTEST_EQUITY_CURVE_CSV_FILENAME),
    ]
    snapshots = {path: snapshot_file(path) for path in managed_paths}

    print("Validacion multi-sample real (proxy por distintos candle_count)")
    print("- market_data_mode=binance_historical")
    print(f"- symbol={BASE_CONFIG.symbol}")
    print(f"- candle_counts={candle_counts}")
    print(
        "- nota: no hay offset de historico en el engine actual; "
        "se usa candle_count como proxy de submuestras reales."
    )
    print(f"- total configuraciones candidatas={len(candidate_configs)}")

    try:
        summaries: list[dict[str, object]] = []
        for candidate in candidate_configs:
            config_name = str(candidate["config_name"])
            params = dict(candidate["params"])
            print(f"\nEjecutando {config_name}")
            _, summary = run_candidate(
                config_name=config_name,
                params=params,
                candle_counts=candle_counts,
            )
            print_candidate_summary(summary)
            summaries.append(summary)

        ranked = rank_by_robustness(summaries)
        print_ranking(ranked)
        export_summary(ranked, OUTPUT_PATH)
        print(f"\nCSV exportado: {OUTPUT_PATH}")
    finally:
        for path, content in snapshots.items():
            restore_file(path, content)


if __name__ == "__main__":
    main()
