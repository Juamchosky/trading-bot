from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from bot.execution.paper_broker import PaperBroker
from bot.market.binance_data import BinanceMarketDataError, fetch_historical_candles
from bot.models import BacktestTrade, Candle
from bot.strategy.compression_breakout import CompressionBreakoutStrategy
from simulate_live_paper import (
    calculate_closed_trade_metrics,
    calculate_max_drawdown_pct,
    upsert_equity_point,
)


OUTPUT_PATH = Path("compression_breakout_evaluation.csv")


@dataclass(frozen=True)
class CompressionBreakoutConfig:
    symbol: str = "BTCUSDT"
    binance_interval: str = "1h"
    candle_count: int = 300
    historical_offset: int = 0
    initial_cash: float = 10_000.0
    fee_rate: float = 0.001
    position_size_pct: float = 0.5
    binance_spot_base_url: str = "https://api.binance.com"


@dataclass(frozen=True)
class CompressionBreakoutEvaluation:
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
        description="Evaluacion offline de estrategia breakout de compresion minimalista."
    )
    parser.add_argument("--symbol", default=CompressionBreakoutConfig.symbol)
    parser.add_argument("--interval", default=CompressionBreakoutConfig.binance_interval)
    parser.add_argument("--candle-count", type=int, default=CompressionBreakoutConfig.candle_count)
    parser.add_argument(
        "--historical-offset",
        type=int,
        default=CompressionBreakoutConfig.historical_offset,
    )
    parser.add_argument("--initial-cash", type=float, default=CompressionBreakoutConfig.initial_cash)
    parser.add_argument("--fee-rate", type=float, default=CompressionBreakoutConfig.fee_rate)
    parser.add_argument(
        "--position-size-pct",
        type=float,
        default=CompressionBreakoutConfig.position_size_pct,
    )
    parser.add_argument("--output-path", type=Path, default=OUTPUT_PATH)
    return parser.parse_args()


def load_candles(config: CompressionBreakoutConfig) -> list[Candle]:
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


def evaluate_strategy(
    config: CompressionBreakoutConfig,
    candles: Sequence[Candle],
) -> CompressionBreakoutEvaluation:
    strategy = CompressionBreakoutStrategy()
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
                current_stop_price = strategy.initial_stop_price()
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
            upsert_equity_point(
                equity_curve,
                final_candle.timestamp,
                broker.equity(final_candle.close),
            )

    final_equity = broker.equity(candles[-1].close) if candles else config.initial_cash
    metrics = calculate_closed_trade_metrics(closed_trade_pnls)

    return CompressionBreakoutEvaluation(
        strategy_name="compression_breakout_box20_range3_tp2r",
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


def export_evaluation_csv(row: CompressionBreakoutEvaluation, output_path: Path) -> None:
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
                "profit_factor": (
                    "inf"
                    if row.profit_factor == float("inf")
                    else f"{row.profit_factor:.6f}"
                ),
            }
        )


def print_evaluation(row: CompressionBreakoutEvaluation, output_path: Path) -> None:
    print("Evaluacion compression breakout")
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
    config = CompressionBreakoutConfig(
        symbol=args.symbol.upper(),
        binance_interval=args.interval,
        candle_count=args.candle_count,
        historical_offset=args.historical_offset,
        initial_cash=args.initial_cash,
        fee_rate=args.fee_rate,
        position_size_pct=args.position_size_pct,
    )
    candles = load_candles(config)
    result = evaluate_strategy(config, candles)
    export_evaluation_csv(result, args.output_path)
    print_evaluation(result, args.output_path)


if __name__ == "__main__":
    main()
