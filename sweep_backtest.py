import argparse
from pathlib import Path
from itertools import product

from bot.config import MarketDataMode, SimulationConfig
from bot.engine import run_simulation


DEFAULT_MARKET_DATA_MODE: MarketDataMode = "binance_historical"
DEFAULT_SHORT_WINDOWS = [5, 8, 10]
DEFAULT_LONG_WINDOWS = [20, 30, 50]
DEFAULT_STOP_LOSS_PCTS = [0.01, 0.02]
DEFAULT_TAKE_PROFIT_PCTS = [0.03, 0.05]
DEFAULT_BACKTEST_SUMMARY_PATH = Path("backtest_summary.csv")
DEFAULT_RANDOM_SEEDS = [5]
DEFAULT_BREAKOUT_MODES = ["off", "strict", "flexible"]


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Valor booleano invalido: {value}")


def _parse_int_list(value: str) -> list[int]:
    values = [item.strip() for item in value.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("Se requiere al menos un entero")
    return [int(item) for item in values]


def _parse_float_list(value: str) -> list[float]:
    values = [item.strip() for item in value.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("Se requiere al menos un decimal")
    return [float(item) for item in values]


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
    parser.add_argument(
        "--short-windows",
        type=_parse_int_list,
        default=DEFAULT_SHORT_WINDOWS,
        help="Comma-separated short SMA windows.",
    )
    parser.add_argument(
        "--long-windows",
        type=_parse_int_list,
        default=DEFAULT_LONG_WINDOWS,
        help="Comma-separated long SMA windows.",
    )
    parser.add_argument(
        "--stop-loss-pcts",
        type=_parse_float_list,
        default=DEFAULT_STOP_LOSS_PCTS,
        help="Comma-separated stop loss percentages.",
    )
    parser.add_argument(
        "--take-profit-pcts",
        type=_parse_float_list,
        default=DEFAULT_TAKE_PROFIT_PCTS,
        help="Comma-separated take profit percentages.",
    )
    parser.add_argument(
        "--random-seeds",
        type=_parse_int_list,
        default=DEFAULT_RANDOM_SEEDS,
        help="Comma-separated random seeds. Used by simulated market data runs.",
    )
    parser.add_argument("--trend-filter-enabled", type=_parse_bool, default=True)
    parser.add_argument("--trend-window", type=int, default=50)
    parser.add_argument("--trend-slope-filter-enabled", type=_parse_bool, default=True)
    parser.add_argument("--trend-slope-lookback", type=int, default=3)
    parser.add_argument("--volatility-filter-enabled", type=_parse_bool, default=False)
    parser.add_argument("--volatility-window", type=int, default=20)
    parser.add_argument("--min-volatility-pct", type=float, default=0.10)
    parser.add_argument("--regime-filter-enabled", type=_parse_bool, default=False)
    parser.add_argument("--regime-window", type=int, default=50)
    parser.add_argument("--min-regime-volatility-pct", type=float, default=0.30)
    parser.add_argument("--signal-confirmation-bars", type=int, default=0)
    parser.add_argument(
        "--signal-confirmation-bars-values",
        type=_parse_int_list,
        default=None,
        help=(
            "Comma-separated values to sweep for signal_confirmation_bars. "
            "If omitted, uses --signal-confirmation-bars."
        ),
    )
    parser.add_argument("--warmup-bars", type=int, default=0)
    parser.add_argument("--momentum-filter-enabled", type=_parse_bool, default=False)
    parser.add_argument("--momentum-window", type=int, default=14)
    parser.add_argument("--min-momentum-rsi", type=float, default=55.0)
    parser.add_argument("--breakout-filter-enabled", type=_parse_bool, default=False)
    parser.add_argument("--breakout-strict-mode", type=_parse_bool, default=True)
    parser.add_argument("--breakout-lookback", type=int, default=5)
    parser.add_argument("--min-trend-strength-pct", type=float, default=0.10)
    parser.add_argument(
        "--min-trend-strength-pct-values",
        type=_parse_float_list,
        default=None,
        help=(
            "Comma-separated values to sweep for min_trend_strength_pct. "
            "If omitted, uses --min-trend-strength-pct."
        ),
    )
    parser.add_argument(
        "--breakout-mode",
        choices=("off", "strict", "flexible", "all"),
        default=None,
        help=(
            "Modo de breakout para la corrida. "
            "Si se omite, usa breakout-filter-enabled + breakout-strict-mode. "
            "Usa 'all' para comparar off/strict/flexible en el mismo sweep."
        ),
    )
    parser.add_argument("--stop-loss-pct-fixed", type=float, default=None)
    parser.add_argument("--take-profit-pct-fixed", type=float, default=None)
    parser.add_argument("--max-drawdown-limit-pct", type=float, default=1.5)
    parser.add_argument("--position-size-pct", type=float, default=0.5)
    parser.add_argument("--fee-rate", type=float, default=0.001)
    return parser


def _iter_valid_parameter_sets(
    short_windows: list[int],
    long_windows: list[int],
    stop_loss_pcts: list[float],
    take_profit_pcts: list[float],
):
    for short_window, long_window, stop_loss_pct, take_profit_pct in product(
        short_windows,
        long_windows,
        stop_loss_pcts,
        take_profit_pcts,
    ):
        if short_window >= long_window:
            continue
        yield short_window, long_window, stop_loss_pct, take_profit_pct


def _resolve_breakout_modes(args: argparse.Namespace) -> list[tuple[bool, bool, str]]:
    if args.breakout_mode == "all":
        return [
            (False, True, "off"),
            (True, True, "strict"),
            (True, False, "flexible"),
        ]
    if args.breakout_mode == "off":
        return [(False, True, "off")]
    if args.breakout_mode == "strict":
        return [(True, True, "strict")]
    if args.breakout_mode == "flexible":
        return [(True, False, "flexible")]

    mode_label = "off"
    if args.breakout_filter_enabled:
        mode_label = "strict" if args.breakout_strict_mode else "flexible"
    return [(args.breakout_filter_enabled, args.breakout_strict_mode, mode_label)]


def _resolve_min_trend_strength_values(args: argparse.Namespace) -> list[float]:
    if args.min_trend_strength_pct_values is not None:
        return args.min_trend_strength_pct_values
    return [args.min_trend_strength_pct]


def _resolve_signal_confirmation_bars_values(args: argparse.Namespace) -> list[int]:
    if args.signal_confirmation_bars_values is not None:
        return args.signal_confirmation_bars_values
    return [args.signal_confirmation_bars]


def main() -> None:
    args = _build_argument_parser().parse_args()
    stop_loss_pcts = (
        [args.stop_loss_pct_fixed]
        if args.stop_loss_pct_fixed is not None
        else args.stop_loss_pcts
    )
    take_profit_pcts = (
        [args.take_profit_pct_fixed]
        if args.take_profit_pct_fixed is not None
        else args.take_profit_pcts
    )
    parameter_sets = list(
        _iter_valid_parameter_sets(
            args.short_windows,
            args.long_windows,
            stop_loss_pcts,
            take_profit_pcts,
        )
    )
    if args.max_runs is not None:
        parameter_sets = parameter_sets[: args.max_runs]

    random_seeds = args.random_seeds
    breakout_modes = _resolve_breakout_modes(args)
    min_trend_strength_values = _resolve_min_trend_strength_values(args)
    signal_confirmation_bars_values = _resolve_signal_confirmation_bars_values(args)
    total_runs = (
        len(parameter_sets)
        * len(random_seeds)
        * len(breakout_modes)
        * len(min_trend_strength_values)
        * len(signal_confirmation_bars_values)
    )
    if total_runs == 0:
        print("No hay combinaciones validas para ejecutar.")
        return

    print(
        f"Iniciando sweep: {total_runs} corridas "
        f"(market_data_mode={args.market_data_mode}, execution_mode=paper, "
        f"momentum_filter_enabled={args.momentum_filter_enabled}, "
        f"breakout_modes={','.join(mode_label for _, _, mode_label in breakout_modes)}, "
        f"min_trend_strength_values={','.join(f'{value:g}' for value in min_trend_strength_values)}, "
        f"signal_confirmation_bars_values={','.join(str(value) for value in signal_confirmation_bars_values)})"
    )

    run_index = 0
    for random_seed in random_seeds:
        for breakout_filter_enabled, breakout_strict_mode, breakout_mode_label in breakout_modes:
            for min_trend_strength_pct in min_trend_strength_values:
                for signal_confirmation_bars in signal_confirmation_bars_values:
                    for short_window, long_window, stop_loss_pct, take_profit_pct in parameter_sets:
                        run_index += 1
                        config = SimulationConfig(
                            execution_mode="paper",
                            market_data_mode=args.market_data_mode,
                            symbol=args.symbol,
                            candle_count=args.candle_count,
                            random_seed=random_seed,
                            fee_rate=args.fee_rate,
                            short_window=short_window,
                            long_window=long_window,
                            trend_filter_enabled=args.trend_filter_enabled,
                            trend_window=args.trend_window,
                            trend_slope_filter_enabled=args.trend_slope_filter_enabled,
                            trend_slope_lookback=args.trend_slope_lookback,
                            volatility_filter_enabled=args.volatility_filter_enabled,
                            volatility_window=args.volatility_window,
                            min_volatility_pct=args.min_volatility_pct,
                            regime_filter_enabled=args.regime_filter_enabled,
                            regime_window=args.regime_window,
                            min_regime_volatility_pct=args.min_regime_volatility_pct,
                            signal_confirmation_bars=signal_confirmation_bars,
                            warmup_bars=args.warmup_bars,
                            momentum_filter_enabled=args.momentum_filter_enabled,
                            momentum_window=args.momentum_window,
                            min_momentum_rsi=args.min_momentum_rsi,
                            breakout_filter_enabled=breakout_filter_enabled,
                            breakout_strict_mode=breakout_strict_mode,
                            breakout_lookback=args.breakout_lookback,
                            min_trend_strength_pct=min_trend_strength_pct,
                            stop_loss_pct=stop_loss_pct,
                            take_profit_pct=take_profit_pct,
                            max_drawdown_limit_pct=args.max_drawdown_limit_pct,
                            position_size_pct=args.position_size_pct,
                        )
                        result = run_simulation(config)
                        print(
                            f"[{run_index}/{total_runs}] "
                            f"mode={breakout_mode_label} seed={random_seed} "
                            f"signal_bars={signal_confirmation_bars} "
                            f"short={short_window} long={long_window} "
                            f"trend_strength={min_trend_strength_pct:.4f}% "
                            f"sl={stop_loss_pct:.4f} tp={take_profit_pct:.4f} "
                            f"return={result.return_pct:.2f}% final_balance={result.final_balance:.2f}"
                        )

    print(
        "Sweep finalizado. Las corridas quedaron agregadas en "
        f"{DEFAULT_BACKTEST_SUMMARY_PATH}."
    )


if __name__ == "__main__":
    main()
