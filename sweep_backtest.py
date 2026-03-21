import argparse
from itertools import product

from bot.config import MarketDataMode, SimulationConfig
from bot.engine import run_simulation


DEFAULT_MARKET_DATA_MODE: MarketDataMode = "binance_historical"
DEFAULT_SHORT_WINDOWS = [5, 8, 10]
DEFAULT_LONG_WINDOWS = [20, 30, 50]
DEFAULT_STOP_LOSS_PCTS = [0.01, 0.02]
DEFAULT_TAKE_PROFIT_PCTS = [0.03, 0.05]


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a backtest parameter sweep and append one summary row per run."
    )
    parser.add_argument(
        "--market-data-mode",
        choices=("simulated", "binance_historical"),
        default=DEFAULT_MARKET_DATA_MODE,
        help="Market data source used for all runs in the sweep.",
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        default=None,
        help="Optional limit for the number of valid runs to execute.",
    )
    parser.add_argument(
        "--candle-count",
        type=int,
        default=300,
        help="Number of candles per run.",
    )
    parser.add_argument(
        "--symbol",
        default="BTCUSDT",
        help="Symbol used for the sweep.",
    )
    return parser


def _iter_valid_parameter_sets():
    for short_window, long_window, stop_loss_pct, take_profit_pct in product(
        DEFAULT_SHORT_WINDOWS,
        DEFAULT_LONG_WINDOWS,
        DEFAULT_STOP_LOSS_PCTS,
        DEFAULT_TAKE_PROFIT_PCTS,
    ):
        if short_window >= long_window:
            continue
        yield short_window, long_window, stop_loss_pct, take_profit_pct


def main() -> None:
    args = _build_argument_parser().parse_args()
    parameter_sets = list(_iter_valid_parameter_sets())
    if args.max_runs is not None:
        parameter_sets = parameter_sets[: args.max_runs]

    total_runs = len(parameter_sets)
    if total_runs == 0:
        print("No hay combinaciones validas para ejecutar.")
        return

    print(
        f"Iniciando sweep: {total_runs} corridas "
        f"(market_data_mode={args.market_data_mode}, execution_mode=paper)"
    )

    for index, (short_window, long_window, stop_loss_pct, take_profit_pct) in enumerate(
        parameter_sets,
        start=1,
    ):
        config = SimulationConfig(
            execution_mode="paper",
            market_data_mode=args.market_data_mode,
            symbol=args.symbol,
            candle_count=args.candle_count,
            short_window=short_window,
            long_window=long_window,
            trend_filter_enabled=True,
            trend_window=50,
            volatility_filter_enabled=False,
            volatility_window=20,
            min_volatility_pct=0.10,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,      
        )
        result = run_simulation(config)
        print(
            f"[{index}/{total_runs}] "
            f"short={short_window} long={long_window} "
            f"sl={stop_loss_pct:.4f} tp={take_profit_pct:.4f} "
            f"return={result.return_pct:.2f}% final_balance={result.final_balance:.2f}"
        )

    print("Sweep finalizado. Las corridas quedaron agregadas en backtest_summary.csv.")


if __name__ == "__main__":
    main()
