from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from bot.execution.paper_broker import PaperBroker
from bot.market.binance_data import BinanceMarketDataError, fetch_historical_candles
from bot.models import BacktestTrade, Candle
from bot.strategy.trend_pullback import TrendPullbackStrategy
from simulate_live_paper import calculate_closed_trade_metrics, calculate_max_drawdown_pct, upsert_equity_point


OUTPUT_PATH = Path("trend_pullback_evaluation.csv")


@dataclass(frozen=True)
class TrendPullbackConfig:
    symbol: str = "BTCUSDT"
    binance_interval: str = "1h"
    candle_count: int = 300
    historical_offset: int = 0
    initial_cash: float = 10_000.0
    fee_rate: float = 0.001
    position_size_pct: float = 0.5
    regime_sma_window: int = 50
    regime_slope_lookback: int = 5
    setup_ema_window: int = 20
    ema_touch_tolerance_pct: float = 0.25
    impulse_lookback: int = 5
    min_impulse_return_pct: float = 1.0
    atr_window: int = 14
    stop_atr_multiple: float = 1.0
    binance_spot_base_url: str = "https://api.binance.com"


@dataclass(frozen=True)
class TrendPullbackEvaluation:
    strategy_name: str
    symbol: str
    interval: str
    candle_count: int
    historical_offset: int
    total_signals_buy: int
    total_signals_sell: int
    total_signals_hold: int
    total_buys_executed: int
    total_sells_executed: int
    final_equity: float
    return_pct: float
    max_drawdown_pct: float
    closed_trades: int
    win_rate_pct: float
    profit_factor: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluacion offline de estrategia trend pullback minimalista."
    )
    parser.add_argument("--symbol", default=TrendPullbackConfig.symbol)
    parser.add_argument("--interval", default=TrendPullbackConfig.binance_interval)
    parser.add_argument("--candle-count", type=int, default=TrendPullbackConfig.candle_count)
    parser.add_argument("--historical-offset", type=int, default=TrendPullbackConfig.historical_offset)
    parser.add_argument("--initial-cash", type=float, default=TrendPullbackConfig.initial_cash)
    parser.add_argument("--fee-rate", type=float, default=TrendPullbackConfig.fee_rate)
    parser.add_argument("--position-size-pct", type=float, default=TrendPullbackConfig.position_size_pct)
    parser.add_argument(
        "--ema-touch-tolerance-pct",
        type=float,
        default=TrendPullbackConfig.ema_touch_tolerance_pct,
    )
    parser.add_argument("--impulse-lookback", type=int, default=TrendPullbackConfig.impulse_lookback)
    parser.add_argument(
        "--min-impulse-return-pct",
        type=float,
        default=TrendPullbackConfig.min_impulse_return_pct,
    )
    parser.add_argument("--stop-atr-multiple", type=float, default=TrendPullbackConfig.stop_atr_multiple)
    parser.add_argument("--output-path", type=Path, default=OUTPUT_PATH)
    return parser.parse_args()


def load_candles(config: TrendPullbackConfig) -> list[Candle]:
    try:
        candles = fetch_historical_candles(
            symbol=config.symbol,
            interval=config.binance_interval,
            limit=config.candle_count,
            historical_offset=config.historical_offset,
            base_url=config.binance_spot_base_url,
        )
    except BinanceMarketDataError as exc:
        raise RuntimeError(f"No se pudieron cargar velas historicas de Binance: {exc}") from exc

    if not candles:
        raise RuntimeError("No se recibieron velas para evaluar.")
    return candles


def evaluate_strategy(config: TrendPullbackConfig, candles: Sequence[Candle]) -> TrendPullbackEvaluation:
    strategy = TrendPullbackStrategy(
        regime_sma_window=config.regime_sma_window,
        regime_slope_lookback=config.regime_slope_lookback,
        setup_ema_window=config.setup_ema_window,
        ema_touch_tolerance_pct=config.ema_touch_tolerance_pct,
        impulse_lookback=config.impulse_lookback,
        min_impulse_return_pct=config.min_impulse_return_pct,
        atr_window=config.atr_window,
        stop_atr_multiple=config.stop_atr_multiple,
    )
    broker = PaperBroker(
        cash=config.initial_cash,
        fee_rate=config.fee_rate,
        position_size_pct=config.position_size_pct,
    )

    history: list[Candle] = []
    equity_curve: list[tuple[int, float]] = []
    closed_trade_pnls: list[float] = []
    backtest_trades: list[BacktestTrade] = []
    total_signals_buy = 0
    total_signals_sell = 0
    total_signals_hold = 0
    total_buys_executed = 0
    total_sells_executed = 0
    current_stop_price: float | None = None
    current_take_profit_price: float | None = None
    entry_timestamp: int | None = None

    for candle in candles:
        history.append(candle)
        signal = strategy.signal(history, in_position=broker.position_qty > 0.0)

        if signal == "buy":
            total_signals_buy += 1
        elif signal == "sell":
            total_signals_sell += 1
        else:
            total_signals_hold += 1

        if broker.position_qty > 0.0 and current_stop_price is not None and candle.low <= current_stop_price:
            entry_price = broker.entry_price
            trade = broker.sell_all(current_stop_price)
            if trade is not None:
                total_sells_executed += 1
                closed_trade_pnls.append(trade.pnl)
                backtest_trades.append(
                    BacktestTrade(
                        entry_timestamp=_require_entry_timestamp(entry_timestamp),
                        exit_timestamp=candle.timestamp,
                        side="long",
                        entry_price=entry_price,
                        exit_price=trade.price,
                        quantity=trade.quantity,
                        pnl=trade.pnl,
                        exit_reason="stop_loss",
                    )
                )
                current_stop_price = None
                current_take_profit_price = None
                entry_timestamp = None
        elif (
            broker.position_qty > 0.0
            and current_take_profit_price is not None
            and candle.high >= current_take_profit_price
        ):
            entry_price = broker.entry_price
            trade = broker.sell_all(current_take_profit_price)
            if trade is not None:
                total_sells_executed += 1
                closed_trade_pnls.append(trade.pnl)
                backtest_trades.append(
                    BacktestTrade(
                        entry_timestamp=_require_entry_timestamp(entry_timestamp),
                        exit_timestamp=candle.timestamp,
                        side="long",
                        entry_price=entry_price,
                        exit_price=trade.price,
                        quantity=trade.quantity,
                        pnl=trade.pnl,
                        exit_reason="take_profit",
                    )
                )
                current_stop_price = None
                current_take_profit_price = None
                entry_timestamp = None
        elif signal == "buy":
            trade = broker.buy_all(candle.close)
            if trade is not None:
                total_buys_executed += 1
                entry_timestamp = candle.timestamp
                current_stop_price = strategy.initial_stop_price(trade.price)
                risk_r = trade.price - current_stop_price
                current_take_profit_price = trade.price + (2.0 * risk_r)

        upsert_equity_point(equity_curve, candle.timestamp, broker.equity(candle.close))

    if candles and broker.position_qty > 0.0:
        final_candle = candles[-1]
        entry_price = broker.entry_price
        trade = broker.sell_all(final_candle.close)
        if trade is not None:
            total_sells_executed += 1
            closed_trade_pnls.append(trade.pnl)
            backtest_trades.append(
                BacktestTrade(
                    entry_timestamp=_require_entry_timestamp(entry_timestamp),
                    exit_timestamp=final_candle.timestamp,
                    side="long",
                    entry_price=entry_price,
                    exit_price=trade.price,
                    quantity=trade.quantity,
                    pnl=trade.pnl,
                    exit_reason="forced_close",
                )
            )
            upsert_equity_point(equity_curve, final_candle.timestamp, broker.equity(final_candle.close))

    final_equity = broker.equity(candles[-1].close) if candles else config.initial_cash
    metrics = calculate_closed_trade_metrics(closed_trade_pnls)

    return TrendPullbackEvaluation(
        strategy_name=(
            "trend_pullback_ema20_touch_sma50_atr14"
            "_prior_return_impulse"
        ),
        symbol=config.symbol,
        interval=config.binance_interval,
        candle_count=config.candle_count,
        historical_offset=config.historical_offset,
        total_signals_buy=total_signals_buy,
        total_signals_sell=total_signals_sell,
        total_signals_hold=total_signals_hold,
        total_buys_executed=total_buys_executed,
        total_sells_executed=total_sells_executed,
        final_equity=final_equity,
        return_pct=((final_equity / config.initial_cash) - 1.0) * 100.0,
        max_drawdown_pct=calculate_max_drawdown_pct(equity_curve),
        closed_trades=int(metrics["closed_trades"]),
        win_rate_pct=float(metrics["win_rate_pct"]),
        profit_factor=float(metrics["profit_factor"]),
    )


def export_evaluation_csv(row: TrendPullbackEvaluation, output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "strategy_name",
                "symbol",
                "interval",
                "candle_count",
                "historical_offset",
                "total_signals_buy",
                "total_signals_sell",
                "total_signals_hold",
                "total_buys_executed",
                "total_sells_executed",
                "final_equity",
                "return_pct",
                "max_drawdown_pct",
                "closed_trades",
                "win_rate_pct",
                "profit_factor",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "strategy_name": row.strategy_name,
                "symbol": row.symbol,
                "interval": row.interval,
                "candle_count": row.candle_count,
                "historical_offset": row.historical_offset,
                "total_signals_buy": row.total_signals_buy,
                "total_signals_sell": row.total_signals_sell,
                "total_signals_hold": row.total_signals_hold,
                "total_buys_executed": row.total_buys_executed,
                "total_sells_executed": row.total_sells_executed,
                "final_equity": f"{row.final_equity:.6f}",
                "return_pct": f"{row.return_pct:.6f}",
                "max_drawdown_pct": f"{row.max_drawdown_pct:.6f}",
                "closed_trades": row.closed_trades,
                "win_rate_pct": f"{row.win_rate_pct:.6f}",
                "profit_factor": "inf" if row.profit_factor == float("inf") else f"{row.profit_factor:.6f}",
            }
        )


def print_evaluation(row: TrendPullbackEvaluation, output_path: Path) -> None:
    print("Evaluacion trend pullback")
    print(f"strategy_name: {row.strategy_name}")
    print(f"symbol: {row.symbol}")
    print(f"interval: {row.interval}")
    print(f"candle_count: {row.candle_count}")
    print(f"historical_offset: {row.historical_offset}")
    print(
        "signals buy/sell/hold: "
        f"{row.total_signals_buy}/{row.total_signals_sell}/{row.total_signals_hold}"
    )
    print(
        "executions buy/sell: "
        f"{row.total_buys_executed}/{row.total_sells_executed}"
    )
    print(f"final_equity: {row.final_equity:.2f}")
    print(f"return_pct: {row.return_pct:.2f}%")
    print(f"max_drawdown_pct: {row.max_drawdown_pct:.2f}%")
    print(f"closed_trades: {row.closed_trades}")
    print(f"win_rate_pct: {row.win_rate_pct:.2f}%")
    print(f"profit_factor: {row.profit_factor:.6f}")
    print(f"CSV exportado: {output_path}")


def _require_entry_timestamp(entry_timestamp: int | None) -> int:
    if entry_timestamp is None:
        raise ValueError("Cierre detectado sin timestamp de entrada asociado.")
    return entry_timestamp


def main() -> None:
    args = parse_args()
    config = TrendPullbackConfig(
        symbol=args.symbol.upper(),
        binance_interval=args.interval,
        candle_count=args.candle_count,
        historical_offset=args.historical_offset,
        initial_cash=args.initial_cash,
        fee_rate=args.fee_rate,
        position_size_pct=args.position_size_pct,
        ema_touch_tolerance_pct=args.ema_touch_tolerance_pct,
        impulse_lookback=args.impulse_lookback,
        min_impulse_return_pct=args.min_impulse_return_pct,
        stop_atr_multiple=args.stop_atr_multiple,
    )
    candles = load_candles(config)
    result = evaluate_strategy(config, candles)
    export_evaluation_csv(result, args.output_path)
    print_evaluation(result, args.output_path)


if __name__ == "__main__":
    main()
