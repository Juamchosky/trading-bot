from __future__ import annotations

import csv
import statistics
from pathlib import Path

from evaluate_time_series_momentum_multi import (
    TimeSeriesMomentumMultiConfig,
    build_robustness_rows,
    export_robustness_summary_csv,
)


SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
OFFSETS = (0, 500, 1000, 1500)
GLOBAL_OUTPUT_PATH = Path("time_series_momentum_multi_cross_asset_global_summary.csv")


def main() -> None:
    base_config = TimeSeriesMomentumMultiConfig(
        binance_interval="1h",
        candle_count=2000,
        initial_cash=10_000.0,
        fee_rate=0.001,
        position_size_pct=0.5,
    )

    all_offset_rows: list[dict[str, float | int | str]] = []
    asset_aggregate_rows: list[dict[str, float | str]] = []

    for symbol in SYMBOLS:
        config = TimeSeriesMomentumMultiConfig(
            symbol=symbol,
            binance_interval=base_config.binance_interval,
            candle_count=base_config.candle_count,
            historical_offset=0,
            initial_cash=base_config.initial_cash,
            fee_rate=base_config.fee_rate,
            position_size_pct=base_config.position_size_pct,
        )
        robustness_rows = build_robustness_rows(config, OFFSETS)
        output_path = Path(f"time_series_momentum_multi_robustness_{symbol.lower()}.csv")
        export_robustness_summary_csv(robustness_rows, output_path)

        for row in robustness_rows:
            if row.row_type == "offset":
                all_offset_rows.append(
                    {
                        "symbol": symbol,
                        "historical_offset": row.historical_offset,
                        "return_pct": float(row.return_pct),
                        "max_drawdown_pct": float(row.max_drawdown_pct),
                        "profit_factor": float(row.profit_factor),
                    }
                )
            else:
                asset_aggregate_rows.append(
                    {
                        "symbol": symbol,
                        "avg_return_pct": float(row.avg_return_pct),
                        "std_return_pct": float(row.std_return_pct),
                        "worst_return_pct": float(row.worst_return_pct),
                        "best_return_pct": float(row.best_return_pct),
                        "avg_drawdown": float(row.avg_drawdown),
                        "worst_drawdown": float(row.worst_drawdown),
                        "robustness_score": float(row.robustness_score),
                    }
                )

    returns = [float(row["return_pct"]) for row in all_offset_rows]
    drawdowns = [float(row["max_drawdown_pct"]) for row in all_offset_rows]

    avg_return_pct = sum(returns) / len(returns) if returns else 0.0
    std_return_pct = statistics.pstdev(returns) if len(returns) > 1 else 0.0
    worst_return_pct = min(returns) if returns else 0.0
    best_return_pct = max(returns) if returns else 0.0
    avg_drawdown = sum(drawdowns) / len(drawdowns) if drawdowns else 0.0
    worst_drawdown = max(drawdowns) if drawdowns else 0.0
    robustness_score = avg_return_pct - std_return_pct - worst_drawdown

    with GLOBAL_OUTPUT_PATH.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "row_type",
                "symbol",
                "historical_offset",
                "return_pct",
                "max_drawdown_pct",
                "profit_factor",
                "avg_return_pct",
                "std_return_pct",
                "worst_return_pct",
                "best_return_pct",
                "avg_drawdown",
                "worst_drawdown",
                "robustness_score",
            ],
        )
        writer.writeheader()

        for row in all_offset_rows:
            writer.writerow(
                {
                    "row_type": "offset",
                    "symbol": row["symbol"],
                    "historical_offset": row["historical_offset"],
                    "return_pct": f"{float(row['return_pct']):.6f}",
                    "max_drawdown_pct": f"{float(row['max_drawdown_pct']):.6f}",
                    "profit_factor": f"{float(row['profit_factor']):.6f}",
                    "avg_return_pct": "",
                    "std_return_pct": "",
                    "worst_return_pct": "",
                    "best_return_pct": "",
                    "avg_drawdown": "",
                    "worst_drawdown": "",
                    "robustness_score": "",
                }
            )

        for row in asset_aggregate_rows:
            writer.writerow(
                {
                    "row_type": "asset_aggregate",
                    "symbol": row["symbol"],
                    "historical_offset": "aggregate",
                    "return_pct": "",
                    "max_drawdown_pct": "",
                    "profit_factor": "",
                    "avg_return_pct": f"{float(row['avg_return_pct']):.6f}",
                    "std_return_pct": f"{float(row['std_return_pct']):.6f}",
                    "worst_return_pct": f"{float(row['worst_return_pct']):.6f}",
                    "best_return_pct": f"{float(row['best_return_pct']):.6f}",
                    "avg_drawdown": f"{float(row['avg_drawdown']):.6f}",
                    "worst_drawdown": f"{float(row['worst_drawdown']):.6f}",
                    "robustness_score": f"{float(row['robustness_score']):.6f}",
                }
            )

        writer.writerow(
            {
                "row_type": "global_aggregate",
                "symbol": "ALL",
                "historical_offset": "aggregate",
                "return_pct": "",
                "max_drawdown_pct": "",
                "profit_factor": "",
                "avg_return_pct": f"{avg_return_pct:.6f}",
                "std_return_pct": f"{std_return_pct:.6f}",
                "worst_return_pct": f"{worst_return_pct:.6f}",
                "best_return_pct": f"{best_return_pct:.6f}",
                "avg_drawdown": f"{avg_drawdown:.6f}",
                "worst_drawdown": f"{worst_drawdown:.6f}",
                "robustness_score": f"{robustness_score:.6f}",
            }
        )

    print("CSV exportados:")
    for symbol in SYMBOLS:
        print(f"- time_series_momentum_multi_robustness_{symbol.lower()}.csv")
    print(f"- {GLOBAL_OUTPUT_PATH}")
    print("\nResumen global")
    print(f"avg_return_pct={avg_return_pct:.6f}")
    print(f"std_return_pct={std_return_pct:.6f}")
    print(f"worst_return_pct={worst_return_pct:.6f}")
    print(f"best_return_pct={best_return_pct:.6f}")
    print(f"worst_drawdown={worst_drawdown:.6f}")
    print(f"robustness_score={robustness_score:.6f}")


if __name__ == "__main__":
    main()
