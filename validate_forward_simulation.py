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


DETAIL_OUTPUT_PATH = Path("regime_filter_forward_results.csv")
SUMMARY_OUTPUT_PATH = Path("regime_filter_forward_comparison.csv")
RANKING_OUTPUT_PATH = Path("regime_filter_forward_ranking.csv")

CANDLE_COUNTS = [200, 300, 500]
RANDOM_SEEDS = [5, 6, 7, 8, 9, 10, 11, 12, 13, 14]

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
    signal_confirmation_bars=0,
    warmup_bars=0,
)

VARIANTS = [
    {
        "name": "base",
        "regime_filter_enabled": False,
        "regime_window": 50,
        "min_regime_volatility_pct": 0.2,
    },
    {
        "name": "regime_w50_min0.2",
        "regime_filter_enabled": True,
        "regime_window": 50,
        "min_regime_volatility_pct": 0.2,
    },
    {
        "name": "regime_w50_min0.3",
        "regime_filter_enabled": True,
        "regime_window": 50,
        "min_regime_volatility_pct": 0.3,
    },
    {
        "name": "regime_w50_min0.5",
        "regime_filter_enabled": True,
        "regime_window": 50,
        "min_regime_volatility_pct": 0.5,
    },
    {
        "name": "regime_w50_min0.7",
        "regime_filter_enabled": True,
        "regime_window": 50,
        "min_regime_volatility_pct": 0.7,
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Valida robustez de estrategia base (sin regime filter) en forward simulation "
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


def run_validation(
    scenarios: list[dict[str, int | str]], variant: dict[str, int | str]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for scenario in scenarios:
        config = replace(
            BASE_CONFIG,
            regime_filter_enabled=bool(variant["regime_filter_enabled"]),
            regime_window=int(variant["regime_window"]),
            min_regime_volatility_pct=float(variant["min_regime_volatility_pct"]),
            candle_count=int(scenario["candle_count"]),
            random_seed=int(scenario["random_seed"]),
        )
        result = run_simulation(config)
        row = {
            "variant_name": variant["name"],
            "regime_filter_enabled": config.regime_filter_enabled,
            "regime_window": config.regime_window,
            "min_regime_volatility_pct": config.min_regime_volatility_pct,
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
        "runs": float(len(results)),
        "avg_return": safe_mean(returns),
        "std_return": std_return,
        "scenario_win_rate": scenario_win_rate,
        "worst_return": min(returns) if returns else 0.0,
        "avg_drawdown": safe_mean(drawdowns),
        "avg_profit_factor": safe_mean(finite_profit_factors),
    }


def build_scenario_ranking(results: list[dict[str, object]]) -> list[dict[str, object]]:
    ranked = sorted(
        results,
        key=lambda row: (
            -get_result(row).return_pct,
            -safe_value(get_result(row).profit_factor),
            get_result(row).max_drawdown_pct,
            -get_result(row).win_rate_pct,
        ),
    )
    return [
        {
            "rank": idx,
            "scenario_name": row["scenario_name"],
            "candle_count": row["candle_count"],
            "random_seed": row["random_seed"],
            "result": get_result(row),
        }
        for idx, row in enumerate(ranked, start=1)
    ]


def build_variant_ranking(summaries: list[dict[str, object]]) -> list[dict[str, object]]:
    ranked = sorted(
        summaries,
        key=lambda row: (
            row["std_return"],
            -row["scenario_win_rate"],
            -row["avg_return"],
            -row["worst_return"],
            row["avg_drawdown"],
            -safe_value(row["avg_profit_factor"]),
        ),
    )
    return [
        {
            "rank": idx,
            "variant_name": row["variant_name"],
            "regime_filter_enabled": row["regime_filter_enabled"],
            "regime_window": row["regime_window"],
            "min_regime_volatility_pct": row["min_regime_volatility_pct"],
            "avg_return": row["avg_return"],
            "std_return": row["std_return"],
            "scenario_win_rate": row["scenario_win_rate"],
            "worst_return": row["worst_return"],
            "avg_drawdown": row["avg_drawdown"],
            "avg_profit_factor": row["avg_profit_factor"],
        }
        for idx, row in enumerate(ranked, start=1)
    ]


def export_detail(results: list[dict[str, object]], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "variant_name",
                "regime_filter_enabled",
                "regime_window",
                "min_regime_volatility_pct",
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
                    "variant_name": row["variant_name"],
                    "regime_filter_enabled": row["regime_filter_enabled"],
                    "regime_window": row["regime_window"],
                    "min_regime_volatility_pct": f"{row['min_regime_volatility_pct']:.6f}",
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
                "variant_name",
                "regime_filter_enabled",
                "regime_window",
                "min_regime_volatility_pct",
                "runs",
                "avg_return",
                "std_return",
                "scenario_win_rate",
                "worst_return",
                "avg_drawdown",
                "avg_profit_factor",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "variant_name": row["variant_name"],
                    "regime_filter_enabled": row["regime_filter_enabled"],
                    "regime_window": row["regime_window"],
                    "min_regime_volatility_pct": f"{row['min_regime_volatility_pct']:.6f}",
                    "runs": int(row["runs"]),
                    "avg_return": f"{row['avg_return']:.6f}",
                    "std_return": f"{row['std_return']:.6f}",
                    "scenario_win_rate": f"{row['scenario_win_rate']:.6f}",
                    "worst_return": f"{row['worst_return']:.6f}",
                    "avg_drawdown": f"{row['avg_drawdown']:.6f}",
                    "avg_profit_factor": format_metric(row["avg_profit_factor"]),
                }
            )


def export_ranking(ranking: list[dict[str, object]], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "rank",
                "variant_name",
                "regime_filter_enabled",
                "regime_window",
                "min_regime_volatility_pct",
                "avg_return",
                "std_return",
                "scenario_win_rate",
                "worst_return",
                "avg_drawdown",
                "avg_profit_factor",
            ],
        )
        writer.writeheader()
        for row in ranking:
            writer.writerow(
                {
                    "rank": row["rank"],
                    "variant_name": row["variant_name"],
                    "regime_filter_enabled": row["regime_filter_enabled"],
                    "regime_window": row["regime_window"],
                    "min_regime_volatility_pct": f"{row['min_regime_volatility_pct']:.6f}",
                    "avg_return": f"{row['avg_return']:.6f}",
                    "std_return": f"{row['std_return']:.6f}",
                    "scenario_win_rate": f"{row['scenario_win_rate']:.6f}",
                    "worst_return": f"{row['worst_return']:.6f}",
                    "avg_drawdown": f"{row['avg_drawdown']:.6f}",
                    "avg_profit_factor": format_metric(row["avg_profit_factor"]),
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
        f"- {row['variant_name']} | {row['scenario_name']} | "
        f"return_pct={result.return_pct:.2f}% | "
        f"win_rate={result.win_rate_pct:.2f}% | "
        f"max_drawdown_pct={result.max_drawdown_pct:.2f}% | "
        f"profit_factor={format_metric(result.profit_factor)}"
    )


def print_summary(summary: dict[str, object]) -> None:
    print(f"\nResumen global - {summary['variant_name']}")
    print(
        f"- params: regime_filter_enabled={summary['regime_filter_enabled']} "
        f"regime_window={summary['regime_window']} "
        f"min_regime_volatility_pct={summary['min_regime_volatility_pct']:.2f}"
    )
    print(f"- avg_return: {summary['avg_return']:.2f}%")
    print(f"- std_return: {summary['std_return']:.2f}")
    print(f"- scenario_win_rate: {summary['scenario_win_rate']:.2f}%")
    print(f"- worst_return: {summary['worst_return']:.2f}%")
    print(f"- avg_drawdown: {summary['avg_drawdown']:.2f}%")
    print(f"- avg_profit_factor: {format_metric(summary['avg_profit_factor'])}")


def print_ranking(ranking: list[dict[str, object]]) -> None:
    print("\nRanking final entre variantes (1) menor std_return, (2) mayor scenario_win_rate, (3) mayor avg_return")
    for row in ranking:
        print(
            f"{row['rank']}. {row['variant_name']} | "
            f"regime_filter_enabled={row['regime_filter_enabled']} | "
            f"regime_window={row['regime_window']} | "
            f"min_regime_volatility_pct={row['min_regime_volatility_pct']:.2f} | "
            f"std_return={row['std_return']:.2f} | "
            f"scenario_win_rate={row['scenario_win_rate']:.2f}% | "
            f"avg_return={row['avg_return']:.2f}% | "
            f"worst_return={row['worst_return']:.2f}% | "
            f"avg_drawdown={row['avg_drawdown']:.2f}% | "
            f"avg_profit_factor={format_metric(row['avg_profit_factor'])}"
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

    print("Forward simulation de robustez con calibracion de regime filter")
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
        "volatility_filter_enabled=False signal_confirmation_bars=0 warmup_bars=0"
    )
    print("- variantes a comparar:")
    for variant in VARIANTS:
        print(
            f"  - {variant['name']}: regime_filter_enabled={variant['regime_filter_enabled']} "
            f"regime_window={variant['regime_window']} "
            f"min_regime_volatility_pct={variant['min_regime_volatility_pct']}"
        )
    print(f"- escenarios: candle_counts={candle_counts} random_seeds={random_seeds}")
    print(f"- total_runs_por_variante={len(scenarios)}")
    print(f"- total_runs_global={len(scenarios) * len(VARIANTS)}")

    try:
        all_results: list[dict[str, object]] = []
        summaries: list[dict[str, object]] = []
        for variant in VARIANTS:
            print(f"\nEjecutando variante: {variant['name']}")
            variant_results = run_validation(scenarios, variant)
            variant_summary = summarize(variant_results)
            variant_summary_row = {
                "variant_name": variant["name"],
                "regime_filter_enabled": variant["regime_filter_enabled"],
                "regime_window": variant["regime_window"],
                "min_regime_volatility_pct": variant["min_regime_volatility_pct"],
                **variant_summary,
            }
            print_summary(variant_summary_row)
            all_results.extend(variant_results)
            summaries.append(variant_summary_row)

        ranking = build_variant_ranking(summaries)
        print_ranking(ranking)
        export_detail(all_results, DETAIL_OUTPUT_PATH)
        export_summary(summaries, SUMMARY_OUTPUT_PATH)
        export_ranking(ranking, RANKING_OUTPUT_PATH)
        print(f"\nCSV detalle por escenario+variante: {DETAIL_OUTPUT_PATH}")
        print(f"CSV comparativo por variante: {SUMMARY_OUTPUT_PATH}")
        print(f"CSV ranking: {RANKING_OUTPUT_PATH}")
    finally:
        for path, content in snapshots.items():
            restore_file(path, content)


if __name__ == "__main__":
    main()

